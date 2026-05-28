""":mod:`loopai.context` — Context management package.

Provides token counting and context compression infrastructure for the
agent context window.  Exports :class:`TokenCounter`,
:class:`TokenizerProtocol`, and :class:`ContextCompressor`.
"""

from loopai.context.compressor import ContextCompressor
from loopai.context.token_counter import TokenCounter, TokenizerProtocol

__all__ = ["ContextCompressor", "TokenCounter", "TokenizerProtocol"]
