"""AgentConfig 测试 —— 环境变量加载、CLI 覆盖、默认值、密钥屏蔽。"""

from __future__ import annotations

import argparse
import os

import pytest

from loopai.config import AgentConfig, add_cli_args, load_config


class TestLoadFromEnvVars:
    """测试从环境变量加载配置。"""

    def test_load_from_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """所有值都从环境变量正确读取。"""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-env-key-123")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://custom.api.example.com/v1")
        monkeypatch.setenv("OPENAI_MODEL", "gpt-4-turbo")

        config = load_config()

        assert config.api_key.get_secret_value() == "sk-env-key-123"
        assert config.base_url == "https://custom.api.example.com/v1"
        assert config.model == "gpt-4-turbo"
        assert config.max_steps == 15  # 默认值

    def test_cli_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CLI 标志优先于环境变量。"""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-env-key-123")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://env.url.example.com/v1")
        monkeypatch.setenv("OPENAI_MODEL", "gpt-4-turbo")

        parser = argparse.ArgumentParser()
        add_cli_args(parser)
        cli_args = parser.parse_args([
            "--api-key", "sk-cli-override",
            "--base-url", "https://cli.url.example.com/v1",
            "--model", "gpt-4o-mini",
            "--max-steps", "10",
        ])

        config = load_config(cli_args)

        assert config.api_key.get_secret_value() == "sk-cli-override"
        assert config.base_url == "https://cli.url.example.com/v1"
        assert config.model == "gpt-4o-mini"
        assert config.max_steps == 10

    def test_cli_partial_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CLI 只覆盖部分值时，其他值回退到环境变量。"""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-env-key-123")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://env.url.example.com/v1")
        monkeypatch.setenv("OPENAI_MODEL", "gpt-4-turbo")

        parser = argparse.ArgumentParser()
        add_cli_args(parser)
        cli_args = parser.parse_args(["--max-steps", "20"])

        config = load_config(cli_args)

        # 只有 max_steps 被覆盖
        assert config.max_steps == 20
        # 其他值保持环境变量
        assert config.api_key.get_secret_value() == "sk-env-key-123"
        assert config.base_url == "https://env.url.example.com/v1"
        assert config.model == "gpt-4-turbo"

    def test_default_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """当环境变量未设置时使用默认值。"""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-default")
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        monkeypatch.delenv("OPENAI_MODEL", raising=False)

        # max_steps 没有对应的环境变量，仅靠 CLI 覆盖

        config = load_config()

        assert config.base_url == "https://api.openai.com/v1"
        assert config.model == "gpt-4o"
        assert config.max_steps == 15


class TestValidation:
    """测试配置验证。"""

    def test_missing_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """缺少 api_key 时抛出 ValueError。"""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        with pytest.raises(ValueError, match="OPENAI_API_KEY environment variable is required"):
            load_config()

    def test_empty_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """api_key 为空字符串时抛出 ValueError。"""
        monkeypatch.setenv("OPENAI_API_KEY", "")

        with pytest.raises(ValueError, match="OPENAI_API_KEY environment variable is required"):
            load_config()

    def test_api_key_not_in_repr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """api_key 不在 repr/str 输出中暴露。"""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-key-abc123")

        config = load_config()
        repr_output = repr(config)
        str_output = str(config)

        assert "sk-super-secret-key-abc123" not in repr_output
        assert "sk-super-secret-key-abc123" not in str_output
        # SecretStr 显示为 "**********"
        assert "**********" in repr_output or "SecretStr" in repr_output

    def test_api_key_not_in_model_dump(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """api_key 序列化时不被暴露。"""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-key-abc123")

        config = load_config()
        dumped = config.model_dump()

        # SecretStr 在 model_dump 中默认返回 '**********'
        assert dumped["api_key"] != "sk-super-secret-key-abc123"
        assert "sk-super-secret-key-abc123" not in str(dumped)

    def test_add_cli_args_registers_all_flags(self) -> None:
        """add_cli_args 注册了所有预期的 CLI 标志。"""
        parser = argparse.ArgumentParser()
        add_cli_args(parser)

        # 验证所有参数都已注册
        actions = {action.dest for action in parser._actions}
        assert "api_key" in actions
        assert "base_url" in actions
        assert "model" in actions
        assert "max_steps" in actions

    def test_max_steps_only_from_cli(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """max_steps 不从环境变量读取，仅通过 CLI 覆盖。"""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        # 没有 CLI 参数时，max_steps 使用默认值
        config = load_config()
        assert config.max_steps == 15

        # 通过 CLI 覆盖
        parser = argparse.ArgumentParser()
        add_cli_args(parser)
        cli_args = parser.parse_args(["--max-steps", "25"])
        config = load_config(cli_args)
        assert config.max_steps == 25

    def test_api_key_whitespace_only_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """api_key 仅为空白字符时也抛出 ValueError。"""
        monkeypatch.setenv("OPENAI_API_KEY", "   ")

        with pytest.raises(ValueError, match="OPENAI_API_KEY environment variable is required"):
            load_config()
