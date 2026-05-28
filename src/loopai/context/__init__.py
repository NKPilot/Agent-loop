""":mod:`loopai.context` — Context management package.

Provides token counting infrastructure for the agent context window.
Exports :class:`TokenCounter` and :class:`TokenizerProtocol`.
"""

from loopai.context.token_counter import TokenCounter, TokenizerProtocol

__all__ = ["TokenCounter", "TokenizerProtocol"]
