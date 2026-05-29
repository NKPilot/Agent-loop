""":mod:`loopai.resilience` — Resilience and recovery subsystem (Phase 4).

Components:
- :class:`CheckpointManager` — JSONL session checkpointing for crash recovery.
- :class:`FailureRegistry` — Persistent known-failure tracking with sha256 dedup.
- :class:`CircuitBreaker` — Three-state (closed/open/half_open) tool circuit breaker.
"""
