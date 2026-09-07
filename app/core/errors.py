"""Errors the HTTP layer can translate into stable client responses."""


class PolicyVaultError(Exception):
    """Base type for expected use-case failures."""


class NotFoundError(PolicyVaultError):
    pass


class UnsupportedDocumentError(PolicyVaultError):
    pass


class InvalidDocumentError(PolicyVaultError):
    pass


class OCRRequiredError(InvalidDocumentError):
    """The PDF is valid but has no usable text layer."""


class UploadTooLargeError(InvalidDocumentError):
    pass


class EmbeddingConfigurationError(PolicyVaultError):
    pass