"""CLI Agent 渲染器 — 使用 Rich Live 在终端实时显示 agent 活动。

作为 Event Bus 消费者运行，将事件流渲染为原子更新的 Rich Layout。
遵循双粒度显示 (D-03): 步骤面板 + Token 流式输出 + 工具调用卡片。
"""

from __future__ import annotations

import asyncio
from typing import Any

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from loopai.events.bus import EventBus


class CLIAgentRenderer:
    """使用 Rich Live 在终端渲染 agent 活动轨迹的消费者。

    从 Event Bus 消费事件，在内存中维护渲染状态，
    并在每次事件后原子性地更新 Rich Live 显示。
    按 RESEARCH.md 陷阱 5: 始终全量重建 Layout 树，永不增量更新面板。

    Attributes:
        current_step: 当前步骤编号。
        max_steps: 最大步骤预算（用于进度显示）。
        step_content: 当前步骤中 LLM 的累积文本输出。
        tool_calls: 当前步骤中活跃的工具调用列表。
        current_state: 当前 FSM 状态名称 (REASON/ACT/OBSERVE/FINISH/ERROR)。
        exit_reason: 会话结束原因文本。
        _bus: EventBus 引用。
        _queue: 订阅者队列。
    """

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self.current_step: int = 0
        self.max_steps: int = 15
        self.step_content: str = ""
        self.current_state: str = "REASON"
        self.exit_reason: str = ""
        self.tool_calls: list[dict[str, Any]] = []
        self._queue: asyncio.Queue[dict | None] | None = None

    def build_renderable(self) -> Layout:
        """从当前状态构建完整的 Rich Layout 树。

        布局:
        - 顶部: 步骤进度面板 (步骤 N/M, 状态)
        - 中间: LLM 思考内容 (Markdown 渲染)
        - 底部: 工具调用状态卡片

        Returns:
            完全构建的 Rich Layout 对象。
        """
        layout = Layout()

        # 顶部: 步骤进度
        progress_text = Text.assemble(
            ("Step ", "bold"),
            (f"{self.current_step}/{self.max_steps}", "bold cyan"),
            ("  State: ", "bold"),
            (self.current_state, "bold yellow"),
        )
        if self.exit_reason:
            progress_text.append(f"  Exit: {self.exit_reason}", style="bold red")
        upper = Panel(progress_text, title="Agent Progress", border_style="blue")

        # 中间: LLM 思考内容
        if self.step_content:
            middle = Panel(
                Markdown(self.step_content),
                title="Thinking",
                border_style="green",
            )
        else:
            middle = Panel(
                Text("Waiting for LLM response...", style="dim italic"),
                title="Thinking",
                border_style="green",
            )

        # 底部: 工具调用卡片
        lower = self._build_tool_panel()

        # 分割布局
        layout.split_column(
            Layout(upper, size=3),
            Layout(middle, ratio=2),
            Layout(lower, size=6),
        )

        return layout

    def _build_tool_panel(self) -> Panel:
        """构建工具调用状态面板。

        Returns:
            包含工具调用状态表的 Panel，如无活跃工具调用则显示提示。
        """
        if not self.tool_calls:
            return Panel(
                Text("No active tool calls", style="dim italic"),
                title="Tool Calls",
                border_style="magenta",
            )

        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Tool", style="cyan")
        table.add_column("Status", style="yellow")
        table.add_column("Details", style="white")

        for tc in self.tool_calls[-5:]:  # 最近 5 个工具调用
            table.add_row(
                tc.get("tool_name", "?"),
                tc.get("status", "?"),
                tc.get("detail", ""),
            )

        return Panel(table, title="Tool Calls", border_style="magenta")

    def _handle_event(self, event: dict[str, Any]) -> None:
        """根据事件类型更新渲染状态。

        路由逻辑:
        - step_start: 重置内容/工具调用，设置步骤号
        - llm_token: 累积 content_delta
        - llm_content_done: 记录完整内容
        - tool_call_start: 开始追踪新的工具调用
        - tool_call_args: 更新工具调用参数
        - tool_call_done: 标记工具参数已完成
        - tool_result: 记录工具结果
        - step_end: 更新状态转移信息
        - session_end: 记录最终状态和退出原因
        - budget_warning/error: 追加指示文本
        - loop_detected/budget_exhausted: 追加警告

        Args:
            event: 来自 Event Bus 的事件字典。
        """
        event_type = event.get("event_type")

        if event_type == "step_start":
            self.current_step = event.get("step_num", self.current_step)
            self.step_content = ""
            self.tool_calls = []

        elif event_type == "llm_token":
            delta = event.get("content_delta", "")
            self.step_content += delta

        elif event_type == "llm_content_done":
            full = event.get("full_content", "")
            if full:
                self.step_content = full

        elif event_type == "tool_call_start":
            tool_name = event.get("tool_name", "unknown")
            tool_call_id = event.get("tool_call_id", "")
            self.tool_calls.append({
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "status": "starting",
                "detail": "",
            })

        elif event_type == "tool_call_args":
            tool_name = event.get("tool_name", "")
            args_delta = event.get("args_delta", "")
            # 更新最后一个匹配的工具调用
            for tc in reversed(self.tool_calls):
                if tc.get("tool_name") == tool_name:
                    tc["detail"] = tc.get("detail", "") + args_delta
                    tc["status"] = "receiving args"
                    break

        elif event_type == "tool_call_done":
            tool_call_id = event.get("tool_call_id", "")
            full_args = event.get("full_args", {})
            for tc in self.tool_calls:
                if tc.get("tool_call_id") == tool_call_id:
                    tc["status"] = "executing"
                    tc["detail"] = str(full_args)[:200]
                    break

        elif event_type == "tool_result":
            tool_call_id = event.get("tool_call_id", "")
            is_error = event.get("is_error", False)
            result = event.get("result", "")
            duration_ms = event.get("duration_ms", 0)
            for tc in self.tool_calls:
                if tc.get("tool_call_id") == tool_call_id:
                    status = "error" if is_error else "done"
                    tc["status"] = status
                    tc["detail"] = (
                        f"{result[:100]} ({duration_ms:.0f}ms)"
                    )
                    break

        elif event_type == "step_end":
            state_transition = event.get("state_transition", "")
            if state_transition:
                self.current_state = state_transition.split("_to_")[-1].upper()

        elif event_type == "session_end":
            self.current_state = event.get("final_state", "FINISH")
            self.exit_reason = event.get("exit_reason", "")
            if total_steps := event.get("total_steps"):
                self.current_step = total_steps

        elif event_type == "budget_warning":
            warning = (
                f"\n\n**[Budget Warning]** "
                f"Step budget at {event.get('used_pct', 0):.0f}%. "
                f"Prioritize reaching a conclusion."
            )
            self.step_content += warning

        elif event_type == "budget_exhausted":
            self.step_content += (
                "\n\n**[Budget Exhausted]** "
                "Step budget fully consumed. Providing final answer."
            )

        elif event_type == "loop_detected":
            self.step_content += (
                f"\n\n**[Loop Detected]** "
                f"Tool '{event.get('tool_name', '?')}' called "
                f"{event.get('consecutive_count', 0)} times consecutively."
            )

        elif event_type == "error":
            self.step_content += (
                f"\n\n**[Error]** "
                f"{event.get('error_type', 'unknown')}: "
                f"{event.get('message', '')}"
            )

    async def run(self, max_steps: int = 15) -> None:
        """启动 Rich Live 渲染循环。

        订阅 Event Bus 的所有事件，进入 Rich Live 上下文管理器，
        在每次事件后原子性地全量重建并更新终端显示。

        Args:
            max_steps: 最大步骤预算，用于进度显示。
        """
        self.max_steps = max_steps
        self._queue = await self._bus.subscribe("*")

        console = Console()
        with Live(
            self.build_renderable(),
            refresh_per_second=10,
            transient=True,
            console=console,
        ) as live:
            while True:
                event = await self._queue.get()
                if event is None:  # 关闭哨兵
                    # 最终更新
                    live.update(self.build_renderable())
                    break

                self._handle_event(event)
                live.update(self.build_renderable())
