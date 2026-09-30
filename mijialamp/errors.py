class MijiaLampError(Exception):
    """Base project error."""


class ConfigError(MijiaLampError):
    pass


class SecretError(MijiaLampError):
    pass


class CommunicationError(MijiaLampError):
    pass


class DeviceMismatchError(MijiaLampError):
    pass


class LockTimeoutError(MijiaLampError):
    pass


class StaleIntentError(MijiaLampError):
    """Work was cancelled because a newer user/system intent exists."""
