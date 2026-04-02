class OLTDriverError(Exception):
    """Base exception for OLT driver operations."""


class OLTConnectionError(OLTDriverError):
    """SSH connection failed or dropped."""


class OLTCommandError(OLTDriverError):
    """OLT returned an error to a CLI command."""

    def __init__(self, message: str, command: str = "", raw_output: str = ""):
        super().__init__(message)
        self.command = command
        self.raw_output = raw_output


class OLTTimeoutError(OLTDriverError):
    """Command or connection timed out."""


class ONUNotFoundError(OLTDriverError):
    """Referenced ONU does not exist on the OLT."""
