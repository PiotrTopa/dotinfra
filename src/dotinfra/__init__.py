"""dotinfra: a self-maintaining Markdown infrastructure CMDB for humans and AI agents."""

__version__ = "0.1.1"


class DotinfraError(Exception):
    """An expected, user-facing failure. The CLI prints it without a traceback."""
