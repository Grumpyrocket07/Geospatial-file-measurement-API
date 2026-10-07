"""Domain errors. Each maps to a clear, user-facing message instead of a stack trace."""


class GeoFileError(Exception):
    """Base class for problems with an uploaded geospatial file."""


class UnsupportedFileTypeError(GeoFileError):
    """The upload is not a .kml or a .zip."""


class InvalidArchiveError(GeoFileError):
    """The file is corrupt, unsafe, or does not contain a usable Shapefile/KML."""


class MissingCRSError(GeoFileError):
    """The file has no coordinate reference system, so measurements would be guesses."""


class EmptyFileError(GeoFileError):
    """The file was read successfully but contains no features."""
