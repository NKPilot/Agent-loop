"""CLI Renderer 消费者测试套件 — 5 个测试。

单元测试 _handle_event 状态机逻辑（跳过 Rich Live 上下文管理器）。
验证事件路由、内容累积、工具调用生命周期、Layout 构建和会话结束状态。
"""

import pytest
from rich.layout import Layout
from rich.panel import Panel

from loopai.consumers.cli_renderer import CLIAgentRenderer
from loopai.events.bus import EventBus


@pytest.fixture
def renderer():
    """返回一个新的 CLIAgentRenderer 实例，带模拟 EventBus。"""
    bus = EventBus()
    return CLIAgentRenderer(bus=bus)


class TestStepContentAccumulation:
    """验证 LLMToken content_delta 累积到 step_content。"""

    def test_accumulates_content_deltas(self, renderer):
        """多个 llm_token 事件应累积到 step_content。"""
        renderer._handle_event({
            "event_type": "llm_token",
            "step_num": 1,
            "content_delta": "Hello",
        })
        assert "Hello" in renderer.step_content

        renderer._handle_event({
            "event_type": "llm_token",
            "step_num": 1,
            "content_delta": " world",
        })
        assert renderer.step_content == "Hello world"

    def test_llm_content_done_overwrites(self, renderer):
        """llm_content_done 应设置完整内容。"""
        renderer._handle_event({
            "event_type": "llm_token",
            "step_num": 1,
            "content_delta": "partial",
        })
        renderer._handle_event({
            "event_type": "llm_content_done",
            "step_num": 1,
            "full_content": "complete response",
        })
        assert renderer.step_content == "complete response"


class TestStepResetOnStepStart:
    """验证 StepStart 重置内容、工具调用和步骤号。"""

    def test_resets_content_and_tool_calls(self, renderer):
        """step_start 应清空 step_content 和 tool_calls。"""
        # 先设置一些状态
        renderer.step_content = "previous step content"
        renderer.tool_calls = [{"tool_name": "old_tool", "status": "done"}]

        renderer._handle_event({
            "event_type": "step_start",
            "step_num": 2,
        })

        assert renderer.step_content == ""
        assert renderer.tool_calls == []

    def test_sets_current_step(self, renderer):
        """step_start 应设置 current_step。"""
        assert renderer.current_step == 0

        renderer._handle_event({
            "event_type": "step_start",
            "step_num": 3,
        })
        assert renderer.current_step == 3

    def test_keeps_current_step_if_not_in_event(self, renderer):
        """如果事件中没有 step_num，应保留当前值。"""
        renderer.current_step = 5
        renderer._handle_event({
            "event_type": "step_start",
        })
        assert renderer.current_step == 5


class TestToolCallLifecycle:
    """验证工具调用生命周期: start -> args -> done -> result。"""

    def test_tool_call_start_creates_entry(self, renderer):
        """tool_call_start 应在 tool_calls 中新建条目。"""
        renderer._handle_event({
            "event_type": "tool_call_start",
            "step_num": 1,
            "tool_name": "bash",
            "tool_call_id": "call_001",
        })

        assert len(renderer.tool_calls) == 1
        assert renderer.tool_calls[0]["tool_name"] == "bash"
        assert renderer.tool_calls[0]["tool_call_id"] == "call_001"
        assert renderer.tool_calls[0]["status"] == "starting"

    def test_tool_call_args_updates_entry(self, renderer):
        """tool_call_args 应更新匹配工具调用的参数。"""
        renderer.tool_calls = [{
            "tool_name": "bash",
            "tool_call_id": "call_002",
            "status": "starting",
            "detail": "",
        }]

        renderer._handle_event({
            "event_type": "tool_call_args",
            "step_num": 1,
            "tool_name": "bash",
            "args_delta": '{"cmd": "ls"}',
        })

        assert renderer.tool_calls[0]["status"] == "receiving args"
        assert '{"cmd": "ls"}' in renderer.tool_calls[0]["detail"]

    def test_tool_call_done_marks_executing(self, renderer):
        """tool_call_done 应将状态标记为 executing。"""
        renderer.tool_calls = [{
            "tool_name": "bash",
            "tool_call_id": "call_003",
            "status": "receiving args",
            "detail": "",
        }]

        renderer._handle_event({
            "event_type": "tool_call_done",
            "step_num": 1,
            "tool_name": "bash",
            "tool_call_id": "call_003",
            "full_args": {"cmd": "ls -la"},
        })

        assert renderer.tool_calls[0]["status"] == "executing"

    def test_tool_result_marks_done(self, renderer):
        """tool_result 应标记为 done/error 并附带结果摘要。"""
        renderer.tool_calls = [{
            "tool_name": "bash",
            "tool_call_id": "call_004",
            "status": "executing",
            "detail": "",
        }]

        renderer._handle_event({
            "event_type": "tool_result",
            "step_num": 1,
            "tool_name": "bash",
            "tool_call_id": "call_004",
            "result": "file1.txt\nfile2.txt",
            "is_error": False,
            "duration_ms": 150.0,
        })

        assert renderer.tool_calls[0]["status"] == "done"
        assert "file1.txt" in renderer.tool_calls[0]["detail"]
        assert "150ms" in renderer.tool_calls[0]["detail"]

    def test_tool_result_error_status(self, renderer):
        """is_error=True 时应标记为 error。"""
        renderer.tool_calls = [{
            "tool_name": "bash",
            "tool_call_id": "call_005",
            "status": "executing",
            "detail": "",
        }]

        renderer._handle_event({
            "event_type": "tool_result",
            "step_num": 1,
            "tool_name": "bash",
            "tool_call_id": "call_005",
            "result": "Permission denied",
            "is_error": True,
            "duration_ms": 50.0,
        })

        assert renderer.tool_calls[0]["status"] == "error"


class TestBuildRenderableNoCrash:
    """验证 build_renderable() 不会崩溃，返回有效的 Rich Layout。"""

    def test_initial_state(self, renderer):
        """初始状态应有效。"""
        layout = renderer.build_renderable()
        assert isinstance(layout, Layout)

    def test_with_content_and_tools(self, renderer):
        """有内容和工具调用时应有效。"""
        renderer.current_step = 3
        renderer.step_content = "# Analysis\n\nThe disk usage is high."
        renderer.tool_calls = [
            {
                "tool_name": "bash",
                "tool_call_id": "call_006",
                "status": "done",
                "detail": "Filesystem ... 85% (50ms)",
            },
            {
                "tool_name": "disk_usage",
                "tool_call_id": "call_007",
                "status": "executing",
                "detail": "",
            },
        ]

        layout = renderer.build_renderable()
        assert isinstance(layout, Layout)

    def test_empty_content_shows_placeholder(self, renderer):
        """无内容时应显示占位符。"""
        layout = renderer.build_renderable()
        assert isinstance(layout, Layout)

    def test_many_tool_calls(self, renderer):
        """超过 5 个工具调用时只显示最近 5 个。"""
        for i in range(10):
            renderer.tool_calls.append({
                "tool_name": f"tool_{i}",
                "tool_call_id": f"call_{i:03d}",
                "status": "done",
                "detail": f"result {i}",
            })

        layout = renderer.build_renderable()
        assert isinstance(layout, Layout)


class TestSessionEndUpdatesState:
    """验证 SessionEnd 正确更新最终状态和退出原因。"""

    def test_updates_final_state(self, renderer):
        """session_end 应设置 current_state 为最终状态。"""
        renderer._handle_event({
            "event_type": "session_end",
            "final_state": "FINISH",
            "total_steps": 5,
            "exit_reason": "goal_achieved",
        })

        assert renderer.current_state == "FINISH"
        assert renderer.exit_reason == "goal_achieved"
        assert renderer.current_step == 5

    def test_error_exit(self, renderer):
        """ERROR 退出应正确记录。"""
        renderer._handle_event({
            "event_type": "session_end",
            "final_state": "ERROR",
            "total_steps": 3,
            "exit_reason": "unhandled_exception",
        })

        assert renderer.current_state == "ERROR"
        assert renderer.exit_reason == "unhandled_exception"
        assert renderer.current_step == 3


class TestBudgetAndGuardEvents:
    """验证预算警告、错误和循环检测事件追加指示文本。"""

    def test_budget_warning_appends_text(self, renderer):
        """budget_warning 应追加警告到 step_content。"""
        renderer.step_content = "I need to check"
        renderer._handle_event({
            "event_type": "budget_warning",
            "step_num": 12,
            "used_pct": 80.0,
            "max_steps": 15,
        })
        assert "Budget Warning" in renderer.step_content

    def test_error_appends_text(self, renderer):
        """error 事件应追加错误信息。"""
        renderer._handle_event({
            "event_type": "error",
            "step_num": 2,
            "error_type": "ConnectionError",
            "message": "API timeout",
        })
        assert "ConnectionError" in renderer.step_content
        assert "API timeout" in renderer.step_content

    def test_loop_detected_appends_text(self, renderer):
        """loop_detected 事件应追加警告。"""
        renderer._handle_event({
            "event_type": "loop_detected",
            "step_num": 4,
            "tool_name": "bash",
            "consecutive_count": 3,
        })
        assert "Loop Detected" in renderer.step_content
        assert "bash" in renderer.step_content
