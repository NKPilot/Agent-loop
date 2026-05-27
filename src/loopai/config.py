"""Agent 配置模块。

从环境变量和 CLI 参数加载 LLM 配置，使用 Pydantic 模型提供类型安全的配置对象。
"""

from __future__ import annotations

import argparse
import os

from pydantic import BaseModel, SecretStr, model_validator


class AgentConfig(BaseModel):
    """Agent 运行时配置。

    从环境变量和可选的 CLI 参数中加载。api_key 使用 SecretStr 存储，
    在 repr/str 输出中自动屏蔽。

    Attributes:
        api_key: OpenAI API 密钥，从 OPENAI_API_KEY 环境变量或 --api-key CLI 标志读取。
        base_url: OpenAI API 基础 URL，默认 https://api.openai.com/v1。
        model: 要使用的模型名称，默认 gpt-4o。
        max_steps: 最大步骤预算，默认 15。
        tool_working_dir: Bash 工具的工作目录，默认 /home/user。
        tool_timeout: 工具执行默认超时（秒），默认 60.0。
        confirmation_timeout: 危险命令确认等待超时（秒），默认 120.0。
    """

    api_key: SecretStr
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o"
    max_steps: int = 15
    tool_working_dir: str = "/home/user"
    tool_timeout: float = 60.0
    confirmation_timeout: float = 120.0

    @model_validator(mode="after")
    def _validate_api_key_not_empty(self) -> AgentConfig:
        if not self.api_key.get_secret_value().strip():
            raise ValueError("OPENAI_API_KEY environment variable is required")
        return self


def add_cli_args(parser: argparse.ArgumentParser) -> None:
    """向 ArgumentParser 添加 CLI 配置标志。

    所有参数使用 argparse.SUPPRESS 作为默认值，以便 load_config()
    能够区分"未通过 CLI 提供"和"显式设置"这两种情况。

    Args:
        parser: 要添加参数的 argparse.ArgumentParser 实例。
    """
    parser.add_argument(
        "--api-key",
        default=argparse.SUPPRESS,
        help="OpenAI API 密钥（覆盖 OPENAI_API_KEY 环境变量）",
    )
    parser.add_argument(
        "--base-url",
        default=argparse.SUPPRESS,
        help="OpenAI API 基础 URL（覆盖 OPENAI_BASE_URL 环境变量）",
    )
    parser.add_argument(
        "--model",
        default=argparse.SUPPRESS,
        help="要使用的模型名称（覆盖 OPENAI_MODEL 环境变量）",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=argparse.SUPPRESS,
        help="最大步骤预算（覆盖默认值 15）",
    )
    parser.add_argument(
        "--tool-working-dir",
        default=argparse.SUPPRESS,
        help="Bash 工具的工作目录（覆盖默认值 /home/user）",
    )
    parser.add_argument(
        "--tool-timeout",
        type=float,
        default=argparse.SUPPRESS,
        help="工具执行默认超时秒数（覆盖默认值 60.0）",
    )
    parser.add_argument(
        "--confirmation-timeout",
        type=float,
        default=argparse.SUPPRESS,
        help="危险命令确认等待超时秒数（覆盖默认值 120.0）",
    )


def load_config(cli_args: argparse.Namespace | None = None) -> AgentConfig:
    """从环境变量和可选的 CLI 参数加载 Agent 配置。

    优先级: CLI 标志 > 环境变量 > 默认值。

    Args:
        cli_args: 可选的 argparse.Namespace，包含 CLI 覆盖值。
                  使用 add_cli_args() 配置的 parser 解析得到。

    Returns:
        验证后的 AgentConfig 实例。

    Raises:
        ValueError: 如果 api_key 缺失或为空。
    """
    cli = cli_args or argparse.Namespace()

    # 读取配置——CLI 标志优先于环境变量
    api_key = _get_cli_or_env(cli, "api_key", "OPENAI_API_KEY", "")
    base_url = _get_cli_or_env(
        cli, "base_url", "OPENAI_BASE_URL", "https://api.openai.com/v1"
    )
    model = _get_cli_or_env(cli, "model", "OPENAI_MODEL", "gpt-4o")
    max_steps_str = _get_cli_or_env(cli, "max_steps", None, "15")
    max_steps = int(max_steps_str) if max_steps_str else 15

    tool_working_dir = _get_cli_or_env(
        cli, "tool_working_dir", "LOOPAI_TOOL_WORKING_DIR", "/home/user"
    )
    tool_timeout_str = _get_cli_or_env(
        cli, "tool_timeout", "LOOPAI_TOOL_TIMEOUT", "60.0"
    )
    tool_timeout = float(tool_timeout_str) if tool_timeout_str else 60.0
    confirmation_timeout_str = _get_cli_or_env(
        cli, "confirmation_timeout", "LOOPAI_CONFIRMATION_TIMEOUT", "120.0"
    )
    confirmation_timeout = float(confirmation_timeout_str) if confirmation_timeout_str else 120.0

    return AgentConfig(
        api_key=api_key,
        base_url=base_url,
        model=model,
        max_steps=max_steps,
        tool_working_dir=tool_working_dir,
        tool_timeout=tool_timeout,
        confirmation_timeout=confirmation_timeout,
    )


def _get_cli_or_env(
    cli: argparse.Namespace,
    cli_attr: str,
    env_var: str | None,
    default: str,
) -> str:
    """获取配置值，CLI 优先于环境变量。

    Args:
        cli: argparse.Namespace 对象。
        cli_attr: CLI Namespace 中的属性名。
        env_var: 环境变量名，None 表示不从环境变量读取。
        default: 如果两者都未设置时的默认值。

    Returns:
        配置字符串值。
    """
    cli_value = getattr(cli, cli_attr, None)
    if cli_value is not None:
        return str(cli_value)
    if env_var is not None:
        env_value = os.environ.get(env_var)
        if env_value is not None:
            return env_value
    return default
