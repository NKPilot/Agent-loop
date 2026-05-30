"""LLMClient: OpenAI-compatible API wrapper with streaming + EventBus.

Uses the standard OpenAI streaming API (chat.completions.create with
stream=True) for broad provider compatibility, then manually parses
content and tool call deltas.
"""

from __future__ import annotations

import json
import traceback
from typing import Any

from openai import AsyncOpenAI

from loopai.config import AgentConfig
from loopai.events.bus import EventBus


class LLMClient:
    """Wraps the OpenAI-compatible API with streaming and EventBus integration.

    Streams content and tool call deltas to the EventBus.  Uses the standard
    chat.completions.create(stream=True) API instead of the beta endpoint,
    which requires strict tool schemas not supported by all providers.

    Attributes:
        config: The AgentConfig used to create the underlying AsyncOpenAI client.
        bus: The EventBus to publish streaming events to.
        model: The model name to use for API calls.
    """

    def __init__(self, config: AgentConfig, bus: EventBus) -> None:
        self._api_key = config.api_key.get_secret_value()
        self._async_client = AsyncOpenAI(
            api_key=self._api_key,
            base_url=config.base_url,
        )
        self.bus = bus
        self.model = config.model

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        session_id: str = "",
        step_num: int = 0,
    ) -> dict[str, Any]:
        """Call the LLM and stream events to the EventBus.

        Uses the standard streaming API for provider compatibility.
        Manually tracks tool call argument accumulation across chunks.

        Args:
            messages: The conversation messages in OpenAI format.
            tools: Optional list of tool definitions.
            session_id: Session identifier for event metadata.
            step_num: Current step number for event metadata.

        Returns:
            A dict with keys "content", "tool_calls", and "role".

        Raises:
            Any exception from the API call (after publishing an Error event).
        """
        stream_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            stream_kwargs["tools"] = tools

        # Accumulators
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        token_usage: dict[str, int] | None = None
        tool_calls_acc: dict[int, dict[str, Any]] = {}  # index -> {name, id, args_str}
        tool_starts_emitted: set[int] = set()

        try:
            stream = await self._async_client.chat.completions.create(**stream_kwargs)

            async for chunk in stream:
                # Capture usage from final chunk (stream_options include_usage)
                if getattr(chunk, "usage", None):
                    token_usage = {
                        "prompt_tokens": chunk.usage.prompt_tokens,
                        "completion_tokens": chunk.usage.completion_tokens,
                        "total_tokens": chunk.usage.total_tokens,
                    }

                for choice in chunk.choices:
                    delta = choice.delta

                    # Text content
                    if delta.content:
                        content_parts.append(delta.content)
                        await self.bus.publish(
                            "llm_token",
                            {
                                "event_type": "llm_token",
                                "session_id": session_id,
                                "step_num": step_num,
                                "content_delta": delta.content,
                            },
                        )

                    # Reasoning content (DeepSeek thinking mode / o1-style)
                    rc = getattr(delta, "reasoning_content", None)
                    if rc and isinstance(rc, str):
                        reasoning_parts.append(rc)

                    # Tool calls
                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index or 0

                            # Initialize accumulator for new tool call
                            if idx not in tool_calls_acc:
                                tool_calls_acc[idx] = {
                                    "name": "",
                                    "id": "",
                                    "args_str": "",
                                }

                            if tc.id:
                                tool_calls_acc[idx]["id"] = tc.id
                            if tc.function:
                                if tc.function.name:
                                    tool_calls_acc[idx]["name"] = tc.function.name
                                if tc.function.arguments:
                                    tool_calls_acc[idx]["args_str"] += tc.function.arguments

                            # Emit ToolCallStart once per tool call
                            if idx not in tool_starts_emitted and tool_calls_acc[idx]["name"]:
                                tool_starts_emitted.add(idx)
                                await self.bus.publish(
                                    "tool_call_start",
                                    {
                                        "event_type": "tool_call_start",
                                        "session_id": session_id,
                                        "step_num": step_num,
                                        "tool_name": tool_calls_acc[idx]["name"],
                                        "tool_call_id": tool_calls_acc[idx]["id"] or f"call_{session_id}_{idx}",
                                    },
                                )

            # Publish content_done
            full_content = "".join(content_parts)
            if full_content:
                await self.bus.publish(
                    "llm_content_done",
                    {
                        "event_type": "llm_content_done",
                        "session_id": session_id,
                        "step_num": step_num,
                        "full_content": full_content,
                    },
                )

            # Build final tool_calls list in OpenAI-compatible format
            tool_calls: list[dict[str, Any]] = []
            for idx in sorted(tool_calls_acc.keys()):
                acc = tool_calls_acc[idx]
                args_str = acc["args_str"]
                # Ensure arguments is valid JSON, default to "{}"
                try:
                    json.loads(args_str)
                except (json.JSONDecodeError, TypeError):
                    args_str = "{}"
                tool_calls.append({
                    "id": acc["id"] or f"call_{session_id}_{idx}",
                    "type": "function",
                    "function": {
                        "name": acc["name"],
                        "arguments": args_str,
                    },
                })

            return {
                "content": full_content,
                "tool_calls": tool_calls,
                "role": "assistant",
                "reasoning_content": "".join(reasoning_parts) or None,
                "token_usage": token_usage,
            }

        except Exception as exc:
            await self.bus.publish(
                "error",
                {
                    "event_type": "error",
                    "session_id": session_id,
                    "step_num": step_num,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                },
            )
            raise
