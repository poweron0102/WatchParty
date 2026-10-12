class MediaSourceError(Exception):
    """Base class for errors safe to translate at the transport boundary."""


class InvalidSourceConfiguration(MediaSourceError):
    pass


class SourceNotFound(MediaSourceError):
    pass


class SourceUnavailable(MediaSourceError):
    pass


class UpstreamUnavailable(SourceUnavailable):
    """Safe, structured diagnostics from a remote playback worker."""

    def __init__(self, *, status=0, operation="", retry_after=1, attempt=0, stage=""):
        super().__init__("origem temporariamente indisponível")
        self.status = status
        self.operation = operation
        self.retry_after = max(1, retry_after)
        self.attempt = attempt
        self.stage = stage


class CollectionNotFound(MediaSourceError):
    pass


class MediaItemNotFound(MediaSourceError):
    pass


class ResourceNotFound(MediaSourceError):
    pass


class InvalidByteRange(MediaSourceError):
    pass


class SourceReadError(MediaSourceError):
    pass
