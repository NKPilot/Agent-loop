"""LLMClient: OpenAI-compatible API wrapper with beta streaming + EventBus.

Encapsulates openai.AsyncOpenAI beta streaming API. Iterates stream events
and publishes typed events (LLMToken, ToolCallStart, ToolCallArgs,
ToolCallDone, LLMContentDone, Error) to the EventBus.
"""

from __future__ import annotations

import json
import traceback
from typing import Any

from openai import AsyncOpenAI

from loopai.config import AgentConfig
from loopai.events.bus import EventBus


class LLMClient:
    """Wraps the OpenAI-compatible API with beta streaming and EventBus integration.

    Streams content and tool call events token-by-token to the EventBus.
    Uses client.beta.chat.completions.stream() for the rich event API
    that auto-accumulates tool call arguments.

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

        Uses client.beta.chat.completions.stream() for structured events:
        - content.delta -> LLMToken
        - content.done -> LLMContentDone
        - tool_calls.function.arguments.delta -> ToolCallArgs (and ToolCallStart on first)
        - tool_calls.function.arguments.done -> ToolCallDone
        - chunk -> extract tool_call_ids from delta

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
        # Track which tool call indices have had their ToolCallStart emitted
        tool_started_indices: set[int] = set()
        # Map index -> tool_call_id extracted from ChunkEvent
        tool_call_ids: dict[int, str] = {}

        stream_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if tools:
            stream_kwargs["tools"] = tools

        try:
            async with self._async_client.beta.chat.completions.stream(
                **stream_kwargs
            ) as stream:
                async for event in stream:
                    event_type = event.type

                    if event_type == "content.delta":
                        await self.bus.publish(
                            "llm_token",
                            {
                                "event_type": "llm_token",
                                "session_id": session_id,
                                "step_num": step_num,
                                "content_delta": event.delta,
                            },
                        )

                    elif event_type == "content.done":
                        await self.bus.publish(
                            "llm_content_done",
                            {
                                "event_type": "llm_content_done",
                                "session_id": session_id,
                                "step_num": step_num,
                                "full_content": event.content,
                            },
                        )

                    elif event_type == "chunk":
                        # Extract tool_call_ids from the chunk's delta
                        for choice in event.chunk.choices:
                            if choice.delta.tool_calls:
                                for tc in choice.delta.tool_calls:
                                    if tc.id is not None:
                                        tool_call_ids[tc.index] = tc.id

                    elif event_type == "tool_calls.function.arguments.delta":
                        idx = event.index
                        tool_name = event.name

                        # Emit ToolCallStart on the first arguments.delta for this index
                        if idx not in tool_started_indices:
                            tool_started_indices.add(idx)
                            tc_id = tool_call_ids.get(idx, f"call_{session_id}_{idx}")
                            await self.bus.publish(
                                "tool_call_start",
                                {
                                    "event_type": "tool_call_start",
                                    "session_id": session_id,
                                    "step_num": step_num,
                                    "tool_name": tool_name,
                                    "tool_call_id": tc_id,
                                },
                            )

                        # Always emit ToolCallArgs for each delta
                        await self.bus.publish(
                            "tool_call_args",
                            {
                                "event_type": "tool_call_args",
                                "session_id": session_id,
                                "step_num": step_num,
                                "tool_name": tool_name,
                                "args_delta": event.arguments_delta,
                            },
                        )

                    elif event_type == "tool_calls.function.arguments.done":
                        # Emit ToolCallDone with fully accumulated arguments
                        parsed_args = event.parsed_arguments
                        if parsed_args is None:
                            try:
                                parsed_args = json.loads(event.arguments)
                            except (json.JSONDecodeError, TypeError):
                                parsed_args = {}

                        await self.bus.publish(
                            "tool_call_done",
                            {
                                "event_type": "tool_call_done",
                                "session_id": session_id,
                                "step_num": step_num,
                                "tool_name": event.name,
                                "tool_call_id": tool_call_ids.get(
                                    event.index,
                                    f"call_{session_id}_{event.index}",
                                ),
                                "full_args": parsed_args,
                            },
                        )

                # After stream completes, get the final completion
                final = await stream.get_final_completion()
                return self._build_response(final)

        except Exception as exc:
            # Publish Error event before re-raising
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

    def _build_response(self, final: Any) -> dict[str, Any]:
        """Extract content and tool_calls from the final completion object.

        Args:
            final: A ParsedChatCompletion from stream.get_final_completion().

        Returns:
            A dict with "content", "tool_calls", and "role" keys.
        """
        msg = final.choices[0].message
        content = msg.content

        tool_calls: list[dict[str, Any]] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                args = tc.function.parsed_arguments
                if args is None:
                    try:
                        args = json.loads(tc.function.arguments)
                    except (json.JSONDecodeError, TypeError):
                        args = {}

                tool_calls.append(
                    {
                        "name": tc.function.name,
                        "arguments": args,
                        "tool_call_id": tc.id,
                    }
                )

        return {
            "content": content,
            "tool_calls": tool_calls,
            "role": "assistant",
        }
