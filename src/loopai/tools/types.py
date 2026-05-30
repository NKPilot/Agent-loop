""":mod:`loopai.tools.types` — 工具系统的核心类型定义。

定义装饰器、注册表、执行器和错误分类模块使用的基础类型。
所有 Pydantic 模型遵循 Phase 1 中建立的约定
（``loopai.events.schemas``）。

决策引用:
    D-01: ToolMetadata 捕获完整的装饰器配置
    D-02: 基于 Pydantic 的参数验证，通过生成模型实现
    D-03: Python 到 JSON Schema 类型映射表
    D-05: ToolResult 标准化包装，支持截断
    D-06: 同步/异步双重支持（func_ref 持有其一）
    D-07: 每工具超时，默认 30 秒
    D-11: ErrorCategory 分类，用于重试决策
    D-12: RetryConfig 指数退避 + 抖动
    D-13: 只有 TRANSIENT 触发自动重试
"""

from __future__ import annotations

import random
from enum import IntEnum, StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

# ── 枚举 ────────────────────────────────────────────────────────────────


class ErrorCategory(StrEnum):
    """用于重试决策逻辑的错误分类（D-11, D-13）。

    每个类别对应不同的恢复策略：

    * **TRANSIENT** — 使用指数退避重试（超时、网络错误、速率限制）
    * **TOOL_EXECUTION** — 不重试；将结构化错误注入 LLM 上下文
    * **GUARD_VIOLATION** — 不重试；向 LLM 解释拒绝原因
    * **FATAL** — 立即终止会话（OOM、磁盘满、API 密钥无效）
    """

    TRANSIENT = "transient"
    TOOL_EXECUTION = "tool_execution"
    GUARD_VIOLATION = "guard_violation"
    FATAL = "fatal"


class PermissionLevel(StrEnum):
    """工具操作的安全分类（D-08, D-10）。

    * **SAFE** — 工作目录内的只读操作
    * **MODERATE** — 用户目录内的写入操作
    * **DANGEROUS** — 不可逆或超出范围的操作（需要确认）
    """

    SAFE = "safe"
    MODERATE = "moderate"
    DANGEROUS = "dangerous"


class RecoveryLayer(IntEnum):
    """恢复升级层级（D-03, D-04）。

    每一层都有独立的进入条件。
    """

    COSMETIC = 1       # 修复参数格式，重试
    IN_CONTEXT = 2     # LLM 看到结构化错误，自我纠正（FSM 级别）
    BACKOFF = 3        # 指数退避重试（现有机制）
    ESCALATE = 4       # 暂停，升级到人工处理


class RecoveryConfig(BaseModel):
    """4 层恢复的每层阈值（D-04）。

    每一层有自己的 max_attempts 计数器，独立升级。

    Attributes:
        cosmetic_max_attempts: 第 1 层（外观 JSON 修复）的最大尝试次数。
        in_context_max_attempts: 第 2 层（FSM 级别）的最大 LLM 重新调用次数。
        backoff_max_attempts: 第 3 层（退避 + 抖动）的最大重试次数。
        escalate_timeout: 第 4 层等待人工输入的秒数。
    """

    cosmetic_max_attempts: int = 1
    in_context_max_attempts: int = 2
    backoff_max_attempts: int = 3
    escalate_timeout: float = 120.0


# ── 配置模型 ────────────────────────────────────────────────────────────


class RetryConfig(BaseModel):
    """瞬态错误的重试策略（D-12, D-13）。

    指数退避加随机抖动:
        delay = min(base_delay * (backoff ** attempt) + random(0, jitter), max_delay)

    Attributes:
        max_attempts: 总执行尝试次数（1 次原始 + N-1 次重试）。
        base_delay: 首次重试前的初始延迟秒数。
        max_delay: 计算延迟的上限秒数。
        backoff: 每次尝试的乘法因子。
        jitter: 添加到计算延迟的最大随机抖动值。
    """

    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    backoff: float = 2.0
    jitter: float = 0.1

    def compute_delay(self, attempt: int) -> float:
        """计算给定尝试次数的重试延迟。

        Args:
            attempt: 从 0 开始的重试尝试索引（0 = 第一次重试）。

        Returns:
            延迟秒数，上限为 ``max_delay``。
        """
        exponential = self.base_delay * (self.backoff ** attempt)
        jitter_amount = random.uniform(0, self.jitter)
        delay = min(exponential + jitter_amount, self.max_delay)
        return delay


# ── 工具结果 ────────────────────────────────────────────────────────────


class ToolResult(BaseModel):
    """所有工具执行结果的标准化包装（D-05）。

    每次工具调用，无论成功或失败，都包装在 ``ToolResult`` 中，
    以便 Agent 循环有一致的接口将结果注入 LLM 上下文。

    Attributes:
        status: ``"success"`` 或 ``"error"``。
        data: 工具的返回值（成功时）。
        error: 错误消息字符串（失败时）。
        duration_ms: 实际执行时间（毫秒）。
        truncated: ``data`` 是否因上下文预算被截断。
        overflow_file: 包含完整（未截断）结果的溢出文件路径。
    """

    status: Literal["success", "error"]
    data: Any = None
    error_message: str | None = None
    duration_ms: float
    truncated: bool = False
    overflow_file: str | None = None

    @property
    def is_error(self) -> bool:
        """便捷访问器：当 ``status == 'error'`` 时返回 ``True``。"""
        return self.status == "error"

    @classmethod
    def success(
        cls,
        data: Any,
        duration_ms: float,
        truncated: bool = False,
        overflow_file: str | None = None,
    ) -> ToolResult:
        """成功结果的工厂方法。"""
        return cls(
            status="success",
            data=data,
            duration_ms=duration_ms,
            truncated=truncated,
            overflow_file=overflow_file,
        )

    @classmethod
    def error(cls, error_msg: str, duration_ms: float) -> ToolResult:
        """失败结果的工厂方法。"""
        return cls(
            status="error",
            error_message=error_msg,
            duration_ms=duration_ms,
        )


# ── 工具元数据 ──────────────────────────────────────────────────────────


class ToolMetadata(BaseModel):
    """已注册工具的元数据（D-01）。

    由 ``@tool`` 装饰器创建，以 ``__tool_meta__`` 形式存储在函数上。
    ``func_ref`` 字段被排除在 Pydantic 序列化之外，以防止
    函数引用泄露到 JSON Schema 输出或日志文件中（T-02-04）。

    Attributes:
        name: 唯一工具标识符（从函数名自动推导）。
        description: 人类可读的描述（从文档字符串自动推导）。
        permission_level: 安全分类。
        timeout: 执行超时秒数。
        retry: 瞬态错误的重试策略。
        tags: 用于分类和发现的任意字符串标签。
        param_schema: 工具参数的 JSON Schema（从类型提示生成）。
        func_ref: 可调用对象的引用（排除在序列化之外）。
    """

    name: str
    description: str
    permission_level: PermissionLevel = PermissionLevel.SAFE
    timeout: float = 30.0
    retry: RetryConfig = RetryConfig()
    tags: list[str] = []
    param_schema: dict = {}
    func_ref: Any = Field(default=None, exclude=True)
    validation_model: Any = Field(default=None, exclude=True)

    model_config = {"arbitrary_types_allowed": True}

    def to_openai_schema(self) -> dict:
        """返回此工具的 OpenAI 函数调用 JSON Schema。

        Returns:
            具有以下形状的字典::

                {
                    "type": "function",
                    "function": {
                        "name": "...",
                        "description": "...",
                        "parameters": {...}
                    }
                }
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.param_schema,
            },
        }
