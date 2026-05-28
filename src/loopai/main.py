"""CLI entry point and session orchestration for the loopAI agent.

Provides run_session() for programmatic use and main_cli() for the
command-line interface. Orchestrates the full agent lifecycle:
create components -> run FSM -> graceful shutdown with sentinel drain.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import TYPE_CHECKING

from loopai.config import add_cli_args, load_config
from loopai.consumers.cli_renderer import CLIAgentRenderer
from loopai.consumers.jsonl_logger import JSONLLogger
from loopai.events.bus import EventBus
from loopai.llm.client import LLMClient
from loopai.session.context import Session
from loopai.state_machine.fsm import ReActFSM
from loopai.state_machine.guards import (
    BudgetGuard,
    LoopDetector,
    MessageValidator,
    PermissionGuard,
)
from loopai.tools.bash import create_bash_tool
from loopai.tools.executor import ToolExecutor
from loopai.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from loopai.config import AgentConfig


async def run_session(
    prompt: str,
    config: AgentConfig,
    max_steps_override: int | None = None,
) -> Session:
    """Orchestrate a complete agent session from creation to graceful shutdown.

    Lifecycle:
    1. Create EventBus, Session with system + user messages
    2. Wire up LLMClient, guards, ReActFSM
    3. Start JSONLLogger and CLIAgentRenderer consumers
    4. Execute FSM loop
    5. Shutdown: send None sentinels, drain consumers (5s timeout), close logger

    Args:
        prompt: The user's question or instruction.
        config: AgentConfig with API key, model, and defaults.
        max_steps_override: If provided, overrides config.max_steps for BudgetGuard.
                            This allows programmatic callers to set a custom budget
                            without modifying the config object.

    Returns:
        The completed Session in FINISH or ERROR state.
    """
    actual_max = max_steps_override if max_steps_override is not None else config.max_steps

    # ── Create core components ──────────────────────────────────────
    bus = EventBus()
    session = Session(config=config)

    # Populate initial conversation
    session.add_message(
        "system",
        content=(
            "You are a helpful AI assistant with access to a Bash tool. "
            "Use the 'bash' tool to execute shell commands when needed. "
            "The bash tool supports common commands like ls, df, du, find, "
            "cat, head, tail, grep, sort, echo, and stat. "
            "Dangerous commands (rm, dd, mkfs) require user confirmation. "
            "Always explain what you're doing before running commands."
        ),
    )
    session.add_message("user", content=prompt)

    # Wire up agent components
    client = LLMClient(config, bus)
    budget_guard = BudgetGuard(max_steps=actual_max)
    loop_detector = LoopDetector()
    message_validator = MessageValidator()

    # ── Wire up tool system (Phase 2) ──────────────────────────────
    registry = ToolRegistry()
    executor = ToolExecutor(registry)
    permission_guard = PermissionGuard(
        bus, confirmation_timeout=config.confirmation_timeout
    )

    # Register Bash tool
    bash_fn = create_bash_tool(working_dir=config.tool_working_dir)
    registry.register(bash_fn)

    fsm = ReActFSM(
        client, bus, budget_guard, loop_detector, message_validator,
        registry, executor, permission_guard,
    )

    # ── Start consumers ──────────────────────────────────────────────
    logger = JSONLLogger(session.session_id)
    renderer = CLIAgentRenderer(bus, permission_guard=permission_guard)

    logger_task = await logger.start(bus)
    renderer_task = asyncio.create_task(renderer.run(max_steps=actual_max))

    # ── Execute agent loop ──────────────────────────────────────────
    try:
        session = await fsm.run(session)
    finally:
        # Graceful shutdown sequence:
        # 1. Send None sentinels to all subscriber queues
        await bus.shutdown()

        # 2. Wait for consumers to drain (with timeout)
        await asyncio.wait_for(
            asyncio.gather(logger_task, renderer_task, return_exceptions=True),
            timeout=10.0,
        )

        # 3. Flush and close the logger
        await logger.stop()

    return session


def main_cli() -> None:
    """Command-line entry point for the loopAI agent.

    Parses CLI arguments, loads configuration, and runs a session.
    Invoke via: python -m loopai.main "Your question here"

    Arguments:
        prompt          Positional: the user prompt (required if --prompt not used)
        --prompt        Named alternative for the user prompt
        --max-steps     Maximum step budget (default: 15, from config)
        --verbose       Enable verbose output (API key is never printed)
        --api-key       OpenAI API key (overrides OPENAI_API_KEY env var)
        --base-url      OpenAI API base URL (overrides OPENAI_BASE_URL env var)
        --model         Model name (overrides OPENAI_MODEL env var)
    """
    parser = argparse.ArgumentParser(
        description="loopAI — ReAct Agent CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            '  python -m loopai.main "What is 17 * 23?"\n'
            '  python -m loopai.main "List files" --max-steps 5\n'
            '  python -m loopai.main "Hello" --model gpt-4o-mini'
        ),
    )

    # Prompt: positional or --prompt flag
    parser.add_argument(
        "prompt",
        nargs="?",
        help="The user prompt (positional argument)",
    )
    parser.add_argument(
        "--prompt",
        dest="prompt_opt",
        default=None,
        help="The user prompt (named argument alternative)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose mode (extra output, API key NEVER printed)",
    )

    # Add config-related CLI flags (--api-key, --base-url, --model, --max-steps)
    add_cli_args(parser)

    args = parser.parse_args()

    # Extract prompt from positional or --prompt flag
    prompt = args.prompt or args.prompt_opt
    if not prompt:
        parser.error(
            "A prompt is required.\n"
            "Usage: python -m loopai.main 'Your question here'\n"
            "   or: python -m loopai.main --prompt 'Your question here'"
        )

    # Load configuration (CLI flags override environment variables)
    try:
        config = load_config(args)
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        print(
            "Set OPENAI_API_KEY environment variable or pass --api-key.",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.verbose:
        print(f"Model: {config.model}")
        print(f"Base URL: {config.base_url}")
        print(f"Max steps: {config.max_steps}")
        # API key is NEVER printed — SecretStr prevents accidental exposure

    # Extract max_steps override from CLI args (load_config already applied it,
    # but passing None means "use config value")
    max_steps_override: int | None = None
    cli_max_steps = getattr(args, "max_steps", None)
    if cli_max_steps is not None:
        max_steps_override = int(cli_max_steps)

    # Run the session
    try:
        session = asyncio.run(run_session(prompt, config, max_steps_override))
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        sys.exit(130)

    # Final status
    if args.verbose:
        print(f"\nSession {session.session_id}")
        print(f"Final state: {session.state.value}")
        print(f"Total steps: {session.step_count}")


if __name__ == "__main__":
    main_cli()
