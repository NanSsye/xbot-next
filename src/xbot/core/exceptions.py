class XBotError(Exception):
    """Base framework exception."""


class PolicyDeniedError(XBotError):
    """Raised when agent policy denies a tool call."""


class PluginLoadError(XBotError):
    """Raised when a plugin cannot be loaded."""


class SkillLoadError(XBotError):
    """Raised when a skill cannot be loaded."""

