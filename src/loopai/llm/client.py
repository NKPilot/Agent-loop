"""LLMClient：兼容 OpenAI API 的流式调用封装 + EventBus 集成。

使用标准的 OpenAI 流式 API（chat.completions.create 配合 stream=True）
以获得广泛的提供商兼容性，然后手动解析内容和工具调用增量。
"""

from __future__ import annotations

import json
import traceback
from typing import Any

from openai import AsyncOpenAI

from loopai.config import AgentConfig
from loopai.events.bus import EventBus


class LLMClient:
    """封装 OpenAI 兼容 API，集成流式输出和 EventBus。

    将内容和工具调用增量流式推送到 EventBus。使用标准
    chat.completions.create(stream=True) API，而非 beta 端点，
    后者要求的严格工具模式并非所有提供商都支持。

    Attributes:
        config: 用于创建底层 AsyncOpenAI 客户端的 AgentConfig。
        bus: 用于发布流式事件的 EventBus。
        model: API 调用使用的模型名称。
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
        """调用 LLM 并将事件流式推送到 EventBus。

        使用标准流式 API 以确保提供商兼容性。
        手动跟踪跨分块的参数累积。

        Args:
            messages: OpenAI 格式的对话消息。
            tools: 可选的工具定义列表。
            session_id: 事件元数据的会话标识符。
            step_num: 事件元数据的当前步骤编号。

        Returns:
            包含 "content"、"tool_calls" 和 "role" 键的字典。

        Raises:
            API 调用产生的任何异常（在发布 Error 事件之后）。
        """
        stream_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            stream_kwargs["tools"] = tools

        # 累积器
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        token_usage: dict[str, int] | None = None
        tool_calls_acc: dict[int, dict[str, Any]] = {}  # index -> {name, id, args_str}
        tool_starts_emitted: set[int] = set()

        try:
            stream = await self._async_client.chat.completions.create(**stream_kwargs)

            async for chunk in stream:
                # 从最终块中捕获使用量（stream_options include_usage）
                if getattr(chunk, "usage", None):
                    token_usage = {
                        "prompt_tokens": chunk.usage.prompt_tokens,
                        "completion_tokens": chunk.usage.completion_tokens,
                        "total_tokens": chunk.usage.total_tokens,
                    }

                for choice in chunk.choices:
                    delta = choice.delta

                    # 文本内容
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

                    # 推理内容（DeepSeek 思考模式 / o1 风格）
                    rc = getattr(delta, "reasoning_content", None)
                    if rc and isinstance(rc, str):
                        reasoning_parts.append(rc)

                    # 工具调用
                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index or 0

                            # 为新工具调用初始化累积器
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

                            # 每个工具调用只发出一次 ToolCallStart
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

            # 发布 content_done
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

            # 以 OpenAI 兼容格式构建最终的 tool_calls 列表
            tool_calls: list[dict[str, Any]] = []
            for idx in sorted(tool_calls_acc.keys()):
                acc = tool_calls_acc[idx]
                args_str = acc["args_str"]
                # 确保 arguments 是有效的 JSON，默认 "{}"
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
