class MediaSourceError(Exception):
    """Base class for errors safe to translate at the transport boundary."""


class InvalidSourceConfiguration(MediaSourceError):
    pass


class SourceNotFound(MediaSourceError):
    pass


class SourceUnavailable(MediaSourceError):
    pass


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
