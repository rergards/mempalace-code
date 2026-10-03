"""mempalace_code.errors — Exception types shared across the CLI, MCP, and library layers."""

from __future__ import annotations


class InvalidArgumentError(ValueError):
    """A caller-supplied argument value failed validation.

    Subclasses ``ValueError`` so existing ``except ValueError`` callers keep
    working. The MCP dispatcher answers it with JSON-RPC ``-32602`` and this
    message instead of an opaque internal error, so a client can correct the
    argument and retry.

    ``argument`` names the offending argument when the raiser knows it. When it
    does not (a shared parser such as the KG temporal parser), ``value`` carries
    the rejected value so a caller holding the original arguments can name it.
    """

    def __init__(self, message: str, *, argument: str | None = None, value: object = None):
        super().__init__(message)
        self.argument = argument
        self.value = value
