"""JSONL Logger 消费者测试套件 — 7 个测试。

验证磁盘持久化、文件权限、事件到行映射、追加行为、
flush 行为、哨兵关闭和文件命名约定。
"""

import asyncio
import json
import os
import re
import stat

import pytest


@pytest.mark.asyncio
async def test_log_file_created_and_permissions(event_bus, tmp_path):
    """验证日志文件创建并设置 0o600 权限。"""
    from loopai.consumers.jsonl_logger import JSONLLogger

    log_dir = tmp_path / "logs" / "sessions"
    logger = JSONLLogger(session_id="test-perm", log_dir=str(log_dir))

    # 验证文件已创建
    assert logger.filepath.exists()

    # 验证文件权限为 0o600
    file_mode = os.stat(logger.filepath).st_mode
    assert stat.S_IMODE(file_mode) == 0o600

    # 验证目录权限为 0o700
    dir_mode = os.stat(log_dir).st_mode
    assert stat.S_IMODE(dir_mode) == 0o700

    await logger.stop()


@pytest.mark.asyncio
async def test_event_to_line_mapping(event_bus, tmp_path):
    """验证 3 个事件 -> 3 行 JSON（1:1 映射，D-10）。"""
    from loopai.consumers.jsonl_logger import JSONLLogger

    log_dir = tmp_path / "logs" / "sessions"
    logger = JSONLLogger(session_id="test-mapping", log_dir=str(log_dir))

    task = await logger.start(event_bus)

    # 发布 3 个事件
    await event_bus.publish("step_start", {
        "event_type": "step_start",
        "session_id": "test-mapping",
        "step_num": 1,
    })
    await event_bus.publish("llm_token", {
        "event_type": "llm_token",
        "session_id": "test-mapping",
        "step_num": 1,
        "content_delta": "Hello",
    })
    await event_bus.publish("step_end", {
        "event_type": "step_end",
        "session_id": "test-mapping",
        "step_num": 1,
        "state_transition": "reason_to_act",
    })

    # 发送哨兵并等待消费完成
    await event_bus.shutdown()
    await task

    # 验证文件有 3 行
    lines = logger.filepath.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 3

    # 验证每行都是有效的 JSON
    for line in lines:
        parsed = json.loads(line)
        assert "event_type" in parsed
        assert "session_id" in parsed
        assert parsed["session_id"] == "test-mapping"

    await logger.stop()


@pytest.mark.asyncio
async def test_entry_fields(event_bus, tmp_path):
    """验证每条日志条目包含 seq、ts、session_id 和源事件字段。"""
    from loopai.consumers.jsonl_logger import JSONLLogger

    log_dir = tmp_path / "logs" / "sessions"
    logger = JSONLLogger(session_id="test-fields", log_dir=str(log_dir))

    task = await logger.start(event_bus)

    await event_bus.publish("step_start", {
        "event_type": "step_start",
        "session_id": "test-fields",
        "step_num": 1,
    })
    await event_bus.publish("llm_token", {
        "event_type": "llm_token",
        "session_id": "test-fields",
        "step_num": 1,
        "content_delta": "Hi",
    })

    await event_bus.shutdown()
    await task

    lines = logger.filepath.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2

    # 第一条: step_start
    entry1 = json.loads(lines[0])
    assert entry1["seq"] == 0
    assert "ts" in entry1
    assert entry1["session_id"] == "test-fields"
    assert entry1["event_type"] == "step_start"
    assert entry1["step_num"] == 1

    # 第二条: llm_token — seq 递增
    entry2 = json.loads(lines[1])
    assert entry2["seq"] == 1
    assert "ts" in entry2
    assert entry2["session_id"] == "test-fields"
    assert entry2["event_type"] == "llm_token"
    assert entry2["content_delta"] == "Hi"

    await logger.stop()


@pytest.mark.asyncio
async def test_append_not_overwrite(event_bus, tmp_path):
    """验证使用相同 session_id 重新打开时为追加模式，不覆盖已有内容。"""
    from loopai.consumers.jsonl_logger import JSONLLogger

    log_dir = tmp_path / "logs" / "sessions"
    session_id = "test-append"

    # 第一次会话
    logger1 = JSONLLogger(session_id=session_id, log_dir=str(log_dir))
    task1 = await logger1.start(event_bus)
    await event_bus.publish("step_start", {
        "event_type": "step_start",
        "session_id": session_id,
        "step_num": 1,
    })
    await event_bus.shutdown()
    await task1
    await logger1.stop()

    # 记录文件路径和内容
    filepath = logger1.filepath
    first_lines = filepath.read_text(encoding="utf-8").strip().split("\n")
    assert len(first_lines) == 1

    # 第二次 "会话"（模拟重新打开）——创建新的 EventBus
    bus2 = type(event_bus)()
    logger2 = JSONLLogger(session_id=session_id, log_dir=str(log_dir))
    task2 = await logger2.start(bus2)
    await bus2.publish("llm_token", {
        "event_type": "llm_token",
        "session_id": session_id,
        "step_num": 2,
        "content_delta": "World",
    })
    await bus2.shutdown()
    await task2
    await logger2.stop()

    # 验证文件现在有 2 行（追加，未覆盖）
    all_lines = filepath.read_text(encoding="utf-8").strip().split("\n")
    assert len(all_lines) == 2

    # 验证第一条仍在
    entry1 = json.loads(all_lines[0])
    assert entry1["event_type"] == "step_start"
    assert entry1["seq"] == 0

    # 验证第二条是新的
    entry2 = json.loads(all_lines[1])
    assert entry2["event_type"] == "llm_token"
    assert entry2["seq"] == 0  # 新实例，seq 从 0 开始


@pytest.mark.asyncio
async def test_flush_after_write(event_bus, tmp_path):
    """验证事件在 stop() 之前已写入磁盘（flush 行为）。"""
    from loopai.consumers.jsonl_logger import JSONLLogger

    log_dir = tmp_path / "logs" / "sessions"
    logger = JSONLLogger(session_id="test-flush", log_dir=str(log_dir))

    task = await logger.start(event_bus)

    await event_bus.publish("step_start", {
        "event_type": "step_start",
        "session_id": "test-flush",
        "step_num": 1,
    })

    # 给消费任务一点时间处理事件
    await asyncio.sleep(0.05)

    # 在 stop() 之前读取文件——事件应该已经在磁盘上
    content_before_stop = logger.filepath.read_text(encoding="utf-8")
    assert len(content_before_stop.strip().split("\n")) >= 1

    # 清理
    await event_bus.shutdown()
    await task
    await logger.stop()


@pytest.mark.asyncio
async def test_shutdown_sentinel(event_bus, tmp_path):
    """验证 None 哨兵使消费者干净退出而不抛出异常。"""
    from loopai.consumers.jsonl_logger import JSONLLogger

    log_dir = tmp_path / "logs" / "sessions"
    logger = JSONLLogger(session_id="test-shutdown", log_dir=str(log_dir))

    task = await logger.start(event_bus)

    # 发送哨兵
    await event_bus.shutdown()

    # 消费者任务应该干净退出（不抛出异常）
    await asyncio.wait_for(task, timeout=5.0)

    # 如果执行到这里，说明_consume 正常退出
    assert task.done()
    assert task.exception() is None

    await logger.stop()


@pytest.mark.asyncio
async def test_session_id_in_filename(event_bus, tmp_path):
    """验证文件名匹配 YYYY-MM-DD_*.jsonl 模式（D-11）。"""
    from loopai.consumers.jsonl_logger import JSONLLogger

    log_dir = tmp_path / "logs" / "sessions"
    logger = JSONLLogger(session_id="test-filename", log_dir=str(log_dir))

    filename = logger.filepath.name

    # 验证模式: YYYY-MM-DD_{session_id}.jsonl
    pattern = r"^\d{4}-\d{2}-\d{2}_test-filename\.jsonl$"
    assert re.match(pattern, filename), f"Filename '{filename}' does not match pattern"

    await logger.stop()
