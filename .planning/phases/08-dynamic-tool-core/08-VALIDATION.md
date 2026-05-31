# Phase 08: 动态工具创建核心 (MVP) - Validation Strategy

**Phase:** 08-dynamic-tool-core
**Created:** 2026-05-31
**Status:** Active

## Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| Quick run command | `pytest tests/test_dynamic_creator.py -x -v` |
| Full suite command | `pytest tests/ -x -v --timeout=30` |

## Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DYN-01 | generate_tool 作为内置工具注册到 ToolRegistry，LLM 可调用 | unit | `pytest tests/test_dynamic_creator.py::test_generate_tool_registered -x` | No |
| DYN-02 | Python ast.parse() 语法错误返回结构化错误；bash -n 非零退出返回错误 | unit | `pytest tests/test_dynamic_creator.py::test_syntax_check_python_error -x` | No |
| DYN-02 | 语法正确代码通过检查 | unit | `pytest tests/test_dynamic_creator.py::test_syntax_check_python_ok -x` | No |
| DYN-03 | DangerousModuleScanner 检测 os/subprocess/ctypes/eval/exec 等 30+ 入口 | unit | `pytest tests/test_sandbox.py::test_dangerous_scan_30plus -x` | No |
| DYN-03 | 安全代码不触发扫描告警 | unit | `pytest tests/test_sandbox.py::test_dangerous_scan_clean -x` | No |
| DYN-04 | 工具元数据构造正确 — dynamic.{hash[:8]}_{name} 命名空间 | unit | `pytest tests/test_dynamic_creator.py::test_metadata_namespace -x` | No |
| DYN-05 | tool_creation_requested 事件 payload 包含完整字段 | unit | `pytest tests/test_dynamic_creator.py::test_creation_event_payload -x` | No |
| DYN-06 | 确认弹窗 payload 包含 persistence_level 字段 | integration | `pytest tests/test_api_tools.py::test_confirm_persistence_level -x` | No |
| DYN-07 | 用户可在确认弹窗中指定额外目录 | integration | `pytest tests/test_api_tools.py::test_confirm_extra_dirs -x` | No |
| DYN-08 | 用户确认后 asyncio.Event 解除阻塞 | unit | `pytest tests/test_dynamic_creator.py::test_confirmation_flow -x` | No |
| DYN-09 | SandboxExecutor 在隔离子进程中执行自测代码 | unit | `pytest tests/test_sandbox.py::test_self_test_execution -x` | No |
| DYN-10 | 自测结果 event payload 包含 status + output + error | unit | `pytest tests/test_dynamic_creator.py::test_self_test_result_event -x` | No |
| DYN-24 | 会话级工具在 Session 关闭时从 Registry 移除 | unit | `pytest tests/test_dynamic_creator.py::test_session_level_cleanup -x` | No |
| DYN-25 | 沙箱级工具写入 .sandbox/tools/{tool_name}/ 目录 | unit | `pytest tests/test_tool_persistence.py::test_sandbox_persist -x` | No |
| DYN-26 | 项目级工具写入 src/loopai/tools/dynamic/{tool_name}.py | unit | `pytest tests/test_tool_persistence.py::test_project_persist -x` | No |

## Sampling Rate

- **Per task commit:** `pytest tests/test_dynamic_creator.py tests/test_sandbox.py tests/test_tool_persistence.py -x`
- **Per wave merge:** `pytest tests/ -x --timeout=30`
- **Phase gate:** Full suite green before `/gsd-verify-work`

## Wave 0 Gaps (Test Files to Create)

- [ ] `tests/test_dynamic_creator.py` — 覆盖 DYN-01/02/04/05/08/10/24 (DynamicToolCreator 管道)
- [ ] `tests/test_sandbox.py` — 覆盖 DYN-03/09 (DangerousModuleScanner + SandboxExecutor)
- [ ] `tests/test_tool_persistence.py` — 覆盖 DYN-25/26 (三级持久化读写)
- [ ] `tests/test_api_tools.py` — 覆盖 DYN-06/07/08 (API 确认端点)
- [ ] `tests/conftest.py` — 添加 fixtures: `dynamic_creator`, `sandbox`, `persistence_manager`

---

*Generated from 08-RESEARCH.md Validation Architecture section*
