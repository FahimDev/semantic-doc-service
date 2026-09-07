# 17 — Benchmark Recall, Latency, Build Time, and Size

**Working directory:** `policy-vault/`  
**Build output:** a repeatable exact-versus-ANN experiment

Do not ask “which index is fastest?” without specifying data size, dimensions, metric, filters,
hardware, recall target, build budget, and concurrency. This lab holds most variables constant and
changes the search method and query-time effort.

## Measurement model

For every query:

1. exact search creates the ground-truth top `k` IDs;
2. HNSW or IVFFlat returns an approximate top `k`;
3. recall compares their overlap;
4. p50 describes a typical query and p95 exposes the slower tail.

$$Recall@k=\frac{|Approximate_k \cap Exact_k|}{k}$$

Synthetic random vectors isolate index behavior. They do **not** measure whether an embedding
model represents your documents well; that requires a labeled semantic evaluation set.

## Implement the benchmark

This script uses a dedicated `ann_benchmark` table, never your application tables.

**File:** `policy-vault/scripts/benchmark_indexes.py`

```python
"""Compare exact, HNSW, and IVFFlat cosine search against identical queries."""

import argparse
import statistics
import time
from dataclasses import dataclass

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from sqlalchemy.engine import make_url

from app.core.config import get_settings


@dataclass(frozen=True, slots=True)
class Result:
    name: str
    build_seconds: float
    index_megabytes: float
    p50_ms: float
    p95_ms: float
    recall_at_k: float


def database_dsn() -> str:
    """Convert SQLAlchemy's driver-qualified URL into a psycopg URI."""
    url = make_url(get_settings().database_url)
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.maximum(norms, np.finfo(np.float32).eps)


def generate_data(
    rows: int, dimensions: int, query_count: int
) -> tuple[np.ndarray, np.ndarray]:
    # A fixed seed makes index-parameter comparisons use identical data.
    generator = np.random.default_rng(42)
    vectors = normalize(
        generator.normal(size=(rows, dimensions)).astype(np.float32)
    )
    queries = normalize(
        generator.normal(size=(query_count, dimensions)).astype(np.float32)
    )
    return vectors, queries


def reset_table(connection: psycopg.Connection, vectors: np.ndarray) -> None:
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS ann_benchmark")
        cursor.execute(
            "CREATE TABLE ann_benchmark "
            f"(id integer PRIMARY KEY, embedding vector({vectors.shape[1]}))"
        )
        # Batching reduces client round trips without hiding index build time.
        for start in range(0, len(vectors), 500):
            stop = min(start + 500, len(vectors))
            cursor.executemany(
                "INSERT INTO ann_benchmark (id, embedding) VALUES (%s, %s)",
                [(index, vectors[index]) for index in range(start, stop)],
            )
        cursor.execute("ANALYZE ann_benchmark")
    connection.commit()


def search_many(
    connection: psycopg.Connection,
    queries: np.ndarray,
    k: int,
    setting: tuple[str, int] | None,
    exact: bool,
) -> tuple[list[set[int]], list[float]]:
    result_sets: list[set[int]] = []
    latencies: list[float] = []
    with connection.cursor() as cursor:
        for query in queries:
            if exact:
                # Exact truth must not silently use an ANN index left by another run.
                cursor.execute("SET LOCAL enable_indexscan = off")
                cursor.execute("SET LOCAL enable_bitmapscan = off")
            else:
                # Force the selected ANN index so a tiny table cannot choose a seq scan.
                cursor.execute("SET LOCAL enable_seqscan = off")
                if setting is not None:
                    name, value = setting
                    # The caller owns this fixed setting name; the value is an integer.
                    cursor.execute(f"SET LOCAL {name} = {int(value)}")

            started = time.perf_counter()
            cursor.execute(
                "SELECT id FROM ann_benchmark ORDER BY embedding <=> %s LIMIT %s",
                (query, k),
            )
            result_ids = {row[0] for row in cursor.fetchall()}
            latencies.append((time.perf_counter() - started) * 1_000)
            result_sets.append(result_ids)
            # ROLLBACK resets every SET LOCAL before the next query.
            connection.rollback()
    return result_sets, latencies


def index_size_megabytes(connection: psycopg.Connection, index_name: str) -> float:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_relation_size(%s::regclass)", (index_name,))
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError(f"Could not read size for {index_name}")
        return float(row[0]) / (1024 * 1024)


def build_index(
    connection: psycopg.Connection, method: str, lists: int
) -> tuple[float, float]:
    index_name = f"ann_benchmark_{method}"
    with connection.cursor() as cursor:
        cursor.execute("DROP INDEX IF EXISTS ann_benchmark_hnsw")
        cursor.execute("DROP INDEX IF EXISTS ann_benchmark_ivfflat")
        connection.commit()
        started = time.perf_counter()
        if method == "hnsw":
            cursor.execute(
                "CREATE INDEX ann_benchmark_hnsw ON ann_benchmark "
                "USING hnsw (embedding vector_cosine_ops) "
                "WITH (m = 16, ef_construction = 64)"
            )
        elif method == "ivfflat":
            cursor.execute(
                "CREATE INDEX ann_benchmark_ivfflat ON ann_benchmark "
                f"USING ivfflat (embedding vector_cosine_ops) WITH (lists = {lists})"
            )
        else:
            raise ValueError(f"Unsupported method {method}")
        connection.commit()
        elapsed = time.perf_counter() - started
    return elapsed, index_size_megabytes(connection, index_name)


def summarize(
    name: str,
    build_seconds: float,
    index_megabytes: float,
    truth: list[set[int]],
    observed: list[set[int]],
    latencies: list[float],
    k: int,
) -> Result:
    recalls = [
        len(expected & actual) / k
        for expected, actual in zip(truth, observed, strict=True)
    ]
    return Result(
        name=name,
        build_seconds=build_seconds,
        index_megabytes=index_megabytes,
        p50_ms=statistics.median(latencies),
        p95_ms=float(np.percentile(latencies, 95)),
        recall_at_k=statistics.mean(recalls),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure pgvector exact, HNSW, and IVFFlat search"
    )
    parser.add_argument("--rows", type=int, default=10_000)
    parser.add_argument("--dimensions", type=int, default=384)
    parser.add_argument("--queries", type=int, default=30)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--lists", type=int, default=100)
    args = parser.parse_args()
    if min(args.rows, args.dimensions, args.queries, args.k, args.lists) < 1:
        parser.error("All numeric options must be positive")
    if args.k > args.rows:
        parser.error("k must not exceed rows")
    if args.dimensions > 2_000:
        parser.error("vector HNSW/IVFFlat supports at most 2,000 dimensions")
    if args.lists > args.rows:
        parser.error("lists must not exceed rows")

    vectors, queries = generate_data(args.rows, args.dimensions, args.queries)
    results: list[Result] = []
    with psycopg.connect(database_dsn()) as connection:
        # The initial migration has already installed the vector extension.
        register_vector(connection)
        reset_table(connection, vectors)

        truth, exact_times = search_many(connection, queries, args.k, None, exact=True)
        results.append(summarize("exact", 0, 0, truth, truth, exact_times, args.k))

        hnsw_build, hnsw_size = build_index(connection, "hnsw", args.lists)
        for ef_search in sorted({max(args.k, 20), max(args.k, 40), max(args.k, 100)}):
            found, times = search_many(
                connection,
                queries,
                args.k,
                ("hnsw.ef_search", ef_search),
                exact=False,
            )
            results.append(
                summarize(
                    f"hnsw ef={ef_search}",
                    hnsw_build,
                    hnsw_size,
                    truth,
                    found,
                    times,
                    args.k,
                )
            )

        ivf_build, ivf_size = build_index(connection, "ivfflat", args.lists)
        probe_values = sorted({1, max(1, args.lists // 10), min(args.lists, 50)})
        for probes in probe_values:
            found, times = search_many(
                connection,
                queries,
                args.k,
                ("ivfflat.probes", probes),
                exact=False,
            )
            results.append(
                summarize(
                    f"ivfflat probes={probes}",
                    ivf_build,
                    ivf_size,
                    truth,
                    found,
                    times,
                    args.k,
                )
            )

    print(
        f"rows={args.rows:,}, dimensions={args.dimensions}, "
        f"queries={len(queries)}, k={args.k}"
    )
    print(
        f"{'method':24} {'build s':>9} {'index MB':>10} "
        f"{'p50 ms':>9} {'p95 ms':>9} {'recall@k':>10}"
    )
    for result in results:
        print(
            f"{result.name:24} {result.build_seconds:9.2f} "
            f"{result.index_megabytes:10.2f} {result.p50_ms:9.2f} "
            f"{result.p95_ms:9.2f} {result.recall_at_k:10.3f}"
        )


if __name__ == "__main__":
    main()
```

## Run a progression, not one benchmark

Start small to validate the method:

```bash
uv run python -m scripts.benchmark_indexes \
  --rows 1000 --dimensions 384 --queries 20 --k 10 --lists 20
```

Then run the intended baseline:

```bash
mkdir -p benchmark-results
uv run python -m scripts.benchmark_indexes \
  --rows 10000 --dimensions 384 --queries 30 --k 10 --lists 100 \
  | tee benchmark-results/10k.txt
```

Scale only if your machine has enough memory and time:

```bash
uv run python -m scripts.benchmark_indexes \
  --rows 50000 --dimensions 384 --queries 50 --k 10 --lists 223 \
  | tee benchmark-results/50k.txt
```

PowerShell can omit `tee` or use `Tee-Object`:

```powershell
uv run python -m scripts.benchmark_indexes --rows 10000 --queries 30 --lists 100 |
  Tee-Object benchmark-results/10k.txt
```

## Interpret the table

Make these predictions before each run:

- HNSW recall should usually improve as `ef_search` increases, with more query work.
- IVFFlat recall should usually improve as `probes` increases, with more scanned lists.
- exact recall is `1.0` by definition and has no ANN build cost.
- HNSW often builds more slowly and consumes more index space than IVFFlat.
- at only 1,000 rows, exact scan may be naturally competitive; the script forces ANN only so you
  can inspect it, not because forcing it is production advice.

Do not compare tiny differences from one run. Repeat at least five times, discard the first warm-up
run, report hardware and PostgreSQL settings, and vary query order for serious performance work.

## Inspect the selected plan

After the script leaves its final IVFFlat index in place:

```bash
docker compose exec postgres psql -U policy_vault -d policy_vault -c \
  "EXPLAIN (ANALYZE, BUFFERS) SELECT id FROM ann_benchmark ORDER BY embedding <=> array_fill(1.0, ARRAY[384])::vector LIMIT 10;"
```

Look for `Index Scan using ann_benchmark_ivfflat`. A plan is evidence that PostgreSQL used the
structure; a low elapsed time alone is not.

## Cleanup

The benchmark table is disposable and isolated:

```bash
docker compose exec postgres psql -U policy_vault -d policy_vault -c \
  "DROP TABLE IF EXISTS ann_benchmark;"
```

## Mastery exercise

Add command-line options for HNSW `m`, `ef_construction`, and multiple random seeds. Write results
as CSV, then answer:

1. What is the lowest query effort that reaches recall@10 ≥ 0.95 on your machine?
2. Which method has the lower p95 at that recall target?
3. How do build time and index bytes per vector change?
4. Does the conclusion change at 1k, 10k, and 50k rows?
5. What happens when you add a selective metadata filter to the query?

Commit:

```bash
git add scripts/benchmark_indexes.py
git commit -m "perf: benchmark exact hnsw and ivfflat recall"
```

Continue with `18_SIX_HOUR_EXECUTION_PLAN.md`.
