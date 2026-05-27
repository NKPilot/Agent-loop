---
phase: 01
slug: agent-core-loop
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-27
---

# 阶段 01 — 验证策略

> 执行期间用于反馈采样的逐阶段验证合约。

---

## 测试基础设施

| 属性 | 值 |
|----------|-------|
| **框架** | pytest + pytest-asyncio |
| **配置文件** | 无 — Wave 0 会创建 pyproject.toml |
| **快速运行命令** | `python -m pytest tests/ -x --timeout=10` |
| **完整套件命令** | `python -m pytest tests/ -v --cov=loopai --cov-report=term-missing` |
| **预计运行时间** | 约 15 秒（快速）/ 约 30 秒（完整） |

---

## 采样频率

- **每次任务提交后：** 运行 `python -m pytest tests/ -x --timeout=10`
- **每个计划 Wave 之后：** 运行 `python -m pytest tests/ -v --cov=loopai --cov-report=term-missing`
- **执行 `/gsd-verify-work` 之前：** 完整套件必须全部通过
- **最大反馈延迟：** 15 秒

---

## 逐任务验证映射表

| Task ID | Plan | Wave | Requirement | Threat Ref | 安全行为 | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-01-01 | 01 | 1 | CORE-01 | — | 无 tool_calls 时 FSM 从 REASON 转换到 FINISH | unit | `pytest tests/test_fsm.py::test_reason_to_finish_no_tool_calls -x` | ❌ W0 | ⬜ pending |
| 01-01-02 | 01 | 1 | CORE-01 | — | 完整的 REASON→ACT→OBSERVE→REASON 循环 | unit | `pytest tests/test_fsm.py::test_full_react_cycle -x` | ❌ W0 | ⬜ pending |
| 01-01-03 | 01 | 1 | CORE-01 | — | 未处理的异常 → ERROR | unit | `pytest tests/test_fsm.py::test_error_state_on_exception -x` | ❌ W0 | ⬜ pending |
| 01-01-04 | 01 | 1 | CORE-02 | T-01-01 | API 密钥仅从环境变量读取，绝不硬编码 | unit | `pytest tests/test_llm_client.py::test_client_configuration -x` | ❌ W0 | ⬜ pending |
| 01-01-05 | 01 | 1 | CORE-02 | T-01-01 | 可配置的 base_url 和 model | integration | `pytest tests/test_llm_client.py::test_chat_completion -x` | ❌ W0 | ⬜ pending |
| 01-01-06 | 01 | 1 | CORE-03 | — | 内容增量发送 llm_token 事件 | unit | `pytest tests/test_event_bus.py::test_llm_token_streaming -x` | ❌ W0 | ⬜ pending |
| 01-01-07 | 01 | 1 | CORE-03 | — | step_start 和 step_end 包裹每个循环 | unit | `pytest tests/test_fsm.py::test_step_events_emitted -x` | ❌ W0 | ⬜ pending |
| 01-01-08 | 01 | 1 | CORE-04 | — | 80% 预算警告注入消息中 | unit | `pytest tests/test_guards.py::test_budget_warning_at_80_percent -x` | ❌ W0 | ⬜ pending |
| 01-01-09 | 01 | 1 | CORE-04 | — | 预算耗尽 → 最后总结机会 | unit | `pytest tests/test_guards.py::test_budget_exhausted_final_summary -x` | ❌ W0 | ⬜ pending |
| 01-01-10 | 01 | 1 | CORE-05 | T-01-04 | 在发送给 LLM 之前拒绝孤立的 tool_call | unit | `pytest tests/test_guards.py::test_orphan_tool_call_rejected -x` | ❌ W0 | ⬜ pending |
| 01-01-11 | 01 | 1 | CORE-05 | T-01-04 | 有效的交替消息通过验证 | unit | `pytest tests/test_guards.py::test_valid_messages_pass -x` | ❌ W0 | ⬜ pending |
| 01-01-12 | 01 | 1 | CORE-06 | — | 连续 3 次相同工具调用 → 警告 | unit | `pytest tests/test_guards.py::test_loop_detection_warns_at_3 -x` | ❌ W0 | ⬜ pending |
| 01-01-13 | 01 | 1 | CORE-06 | — | 连续 5 次相同工具调用 → 阻止 | unit | `pytest tests/test_guards.py::test_loop_detection_blocks_at_5 -x` | ❌ W0 | ⬜ pending |
| 01-01-14 | 01 | 1 | CORE-07 | T-01-05 | 会话启动时创建日志文件并设权限为 0o600 | unit | `pytest tests/test_jsonl_logger.py::test_log_file_created -x` | ❌ W0 | ⬜ pending |
| 01-01-15 | 01 | 1 | CORE-07 | T-01-05 | 每个事件 → 一行 JSON，格式正确 | unit | `pytest tests/test_jsonl_logger.py::test_event_to_line_mapping -x` | ❌ W0 | ⬜ pending |

*状态：⬜ 待处理 · ✅ 通过 · ❌ 失败 · ⚠️ 不稳定*

---

## Wave 0 需求

- [ ] `tests/conftest.py` — 共享 fixtures：模拟 EventBus、模拟 AsyncOpenAI、测试 Session
- [ ] `tests/test_fsm.py` — CORE-01 状态机转换（6 个测试用例）
- [ ] `tests/test_event_bus.py` — CORE-03 事件发布/订阅、扇出、排序、关闭（5 个测试用例）
- [ ] `tests/test_guards.py` — CORE-04 预算、CORE-05 消息验证、CORE-06 循环检测（8 个测试用例）
- [ ] `tests/test_jsonl_logger.py` — CORE-07 日志文件创建、格式、追加（4 个测试用例）
- [ ] `tests/test_llm_client.py` — CORE-02 配置、模拟响应（3 个测试用例）
- [ ] `tests/test_cli_renderer.py` — Rich 可渲染输出（3 个测试用例）
- [ ] `uv pip install pytest pytest-asyncio pytest-cov pytest-timeout` — 安装测试框架
- [ ] `pyproject.toml` — 配置 asyncio 模式、测试路径、超时设置

---

## 仅手动验证项

| 行为 | Requirement | 为何手动验证 | 测试说明 |
|----------|-------------|------------|-------------------|
| CLI 实时显示渲染正确 | CORE-03 | Rich 终端输出捕获不稳定；需要人工目视检查 | 使用 `--verbose` 运行 agent，验证终端中步骤面板渲染正常 |
| OpenAI API 密钥从环境变量读取 | CORE-02 | 在自动化测试中无法测试实际的环境变量读取而不泄露密钥 | 手动：取消设置 `OPENAI_API_KEY`，验证错误信息；设置后，验证 agent 能启动 |

---

## 验证签核

- [ ] 所有任务均具有 `<automated>` 验证或 Wave 0 依赖项
- [ ] 采样连续性：不存在连续 3 个任务无自动化验证的情况
- [ ] Wave 0 覆盖所有 MISSING 引用
- [ ] 无 watch-mode 标志
- [ ] 反馈延迟 < 15 秒
- [ ] frontmatter 中设置 `nyquist_compliant: true`

**审批：** 待定
