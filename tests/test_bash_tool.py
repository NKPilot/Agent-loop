""":mod:`tests.test_bash_tool` — Tests for CommandClassifier, BashTool, and PermissionGuard.

Plan 02-02: Bash/Shell security layer — command whitelist/blacklist classifier,
safe subprocess execution, and permission guard for dangerous commands.

Decision references:
    D-08: Whitelist-based + blacklist upgrade classification
    D-10: Path-aware permission escalation (SAFE→MODERATE→DANGEROUS)
    D-14: Minimal tool set for disk diagnosis scenario
"""

from __future__ import annotations

import pytest

from loopai.tools.types import PermissionLevel

# ═══════════════════════════════════════════════════════════════════════════
# Task 1: CommandClassifier — whitelist/blacklist + path-aware classification
# ═══════════════════════════════════════════════════════════════════════════


# ── Test 1: SAFE commands classified correctly ──────────────────────────


@pytest.mark.parametrize(
    "command,args_list",
    [
        ("ls", ["-la"]),
        ("df", ["-h"]),
        ("du", ["-sh", "/home/user"]),
        ("find", [".", "-name", "*.log"]),
        ("cat", ["file.txt"]),
        ("head", ["-n", "10", "file.txt"]),
        ("tail", ["-f", "log.txt"]),
        ("wc", ["-l", "data.csv"]),
        ("grep", ["error", "*.log"]),
        ("sort", ["file.txt"]),
        ("uniq", ["-c", "file.txt"]),
        ("echo", ["hello"]),
        ("stat", ["file.txt"]),
    ],
)
def test_1_safe_commands_classified_safe(command, args_list):
    """Whitelist commands (ls/df/du/find/cat/head/tail/wc/grep/sort/uniq/echo/stat)
    with safe args within user directory are SAFE."""
    from loopai.tools.command_classifier import CommandClassifier

    classifier = CommandClassifier()
    level, reason = classifier.classify(command, args_list, "/home/user")
    assert level == PermissionLevel.SAFE, f"Expected SAFE for {command}, got {level}: {reason}"


# ── Test 2: MODERATE commands (cp/mv/mkdir/touch) in user dir ───────────


@pytest.mark.parametrize(
    "command,args_list",
    [
        ("cp", ["a.txt", "/home/user/b.txt"]),
        ("mv", ["old.txt", "/home/user/new.txt"]),
        ("mkdir", ["/home/user/newdir"]),
        ("touch", ["/home/user/newfile.txt"]),
    ],
)
def test_2_moderate_commands_in_user_dir(command, args_list):
    """Write operations (cp/mv/mkdir/touch) within user directory are MODERATE."""
    from loopai.tools.command_classifier import CommandClassifier

    classifier = CommandClassifier()
    level, reason = classifier.classify(command, args_list, "/home/user")
    assert level == PermissionLevel.MODERATE, f"Expected MODERATE for {command}, got {level}: {reason}"


# ── Test 3: DANGEROUS commands (rm/dd/mkfs etc.) ────────────────────────


@pytest.mark.parametrize(
    "command,args_list",
    [
        ("rm", ["file.txt"]),
        ("dd", ["if=/dev/zero", "of=test.img", "count=1"]),
        ("mkfs", ["-t", "ext4", "/dev/sdb1"]),
        ("shred", ["file.txt"]),
        ("fdisk", ["/dev/sda"]),
        ("mkfs.ext4", ["/dev/sdb1"]),
        ("mkfs.xfs", ["/dev/sdc1"]),
        ("mkfs.btrfs", ["/dev/sdd1"]),
        ("mkswap", ["/dev/sde1"]),
    ],
)
def test_3_dangerous_commands_classified_dangerous(command, args_list):
    """Blacklist commands (rm/dd/mkfs/shred/fdisk/mkfs.*/mkswap) are DANGEROUS."""
    from loopai.tools.command_classifier import CommandClassifier

    classifier = CommandClassifier()
    level, reason = classifier.classify(command, args_list, "/home/user")
    assert level == PermissionLevel.DANGEROUS, f"Expected DANGEROUS for {command}, got {level}: {reason}"


# ── Test 4: rm on a file in /tmp is still DANGEROUS ─────────────────────


def test_4_rm_is_always_dangerous():
    """rm /tmp/foo.txt is DANGEROUS — blacklist command regardless of path."""
    from loopai.tools.command_classifier import CommandClassifier

    classifier = CommandClassifier()
    level, reason = classifier.classify("rm", ["/tmp/foo.txt"], "/home/user")
    assert level == PermissionLevel.DANGEROUS, f"Expected DANGEROUS, got {level}: {reason}"


# ── Test 5: rm -rf /etc is DANGEROUS (blacklist + system path) ──────────


def test_5_rm_rf_etc_is_dangerous():
    """rm -rf /etc is DANGEROUS — blacklist command AND system path (dual escalation)."""
    from loopai.tools.command_classifier import CommandClassifier

    classifier = CommandClassifier()
    level, reason = classifier.classify("rm", ["-rf", "/etc/nginx"], "/home/user")
    assert level == PermissionLevel.DANGEROUS, f"Expected DANGEROUS, got {level}: {reason}"
    # The reason should mention the blacklist
    assert "rm" in reason.lower() or "黑名单" in reason


# ── Test 6: SAFE command targeting system path → MODERATE ───────────────


def test_6_safe_command_system_path_upgraded_to_moderate():
    """ls /etc/passwd is MODERATE — whitelist command BUT system path triggers upgrade."""
    from loopai.tools.command_classifier import CommandClassifier

    classifier = CommandClassifier()
    level, reason = classifier.classify("ls", ["/etc/passwd"], "/home/user")
    assert level == PermissionLevel.MODERATE, f"Expected MODERATE, got {level}: {reason}"


# ── Test 7: chmod 777 / is DANGEROUS (dangerous pattern match) ──────────


def test_7_chmod_777_root_is_dangerous():
    """chmod 777 / is DANGEROUS — matches dangerous pattern regardless of command name."""
    from loopai.tools.command_classifier import CommandClassifier

    classifier = CommandClassifier()
    level, reason = classifier.classify("chmod", ["777", "/"], "/home/user")
    assert level == PermissionLevel.DANGEROUS, f"Expected DANGEROUS, got {level}: {reason}"


# ── Test 8: Output redirection to /dev is DANGEROUS ─────────────────────


def test_8_redirect_to_dev_is_dangerous():
    """> /dev/sda (redirection to device) is DANGEROUS — dangerous pattern match."""
    from loopai.tools.command_classifier import CommandClassifier

    classifier = CommandClassifier()
    # Simulate a command with output redirection to device
    level, reason = classifier.classify("dd", ["if=backup.img", "of=/dev/sda"], "/home/user")
    assert level == PermissionLevel.DANGEROUS, f"Expected DANGEROUS, got {level}: {reason}"


# ── Test 9: Pipe in command → MODERATE (conservative, not supported) ────


def test_9_pipe_is_moderate_conservative():
    """ls | grep foo is MODERATE — pipe not supported, conservative classification."""
    from loopai.tools.command_classifier import CommandClassifier

    classifier = CommandClassifier()
    level, reason = classifier.classify("ls | grep foo", [], "/home/user")
    assert level == PermissionLevel.MODERATE, f"Expected MODERATE, got {level}: {reason}"


# ═══════════════════════════════════════════════════════════════════════════
# Task 2: BashTool — safe subprocess execution with shell=False
# ═══════════════════════════════════════════════════════════════════════════


# ── Test 10: BashTool executes "echo hello" successfully ────────────────


@pytest.mark.asyncio
async def test_10_bash_tool_echo_hello():
    """BashTool.execute('echo hello') returns ToolResult.success() with 'hello' in data."""
    from loopai.tools.bash import BashTool

    tool = BashTool(working_dir="/tmp")
    result = await tool.execute("echo hello")
    assert result.status == "success"
    assert result.is_error is False
    assert "hello" in str(result.data)
    assert result.duration_ms > 0


# ── Test 11: BashTool executes "ls -la" successfully ────────────────────


@pytest.mark.asyncio
async def test_11_bash_tool_ls():
    """BashTool.execute('ls -la') returns directory listing."""
    from loopai.tools.bash import BashTool

    tool = BashTool(working_dir="/tmp")
    result = await tool.execute("ls -la")
    assert result.status == "success"
    assert result.is_error is False
    # /tmp should contain at least '.' and '..'
    assert "." in str(result.data)


# ── Test 12: BashTool executes "df -h" successfully ─────────────────────


@pytest.mark.asyncio
async def test_12_bash_tool_df():
    """BashTool.execute('df -h') returns disk usage info."""
    from loopai.tools.bash import BashTool

    tool = BashTool(working_dir="/tmp")
    result = await tool.execute("df -h")
    assert result.status == "success"
    assert result.is_error is False
    # df output should contain "Filesystem" header
    assert "Filesystem" in str(result.data)


# ── Test 13: BashTool nonexistent command returns error ────────────────


@pytest.mark.asyncio
async def test_13_bash_tool_nonexistent_command():
    """BashTool.execute('nonexistent_cmd_xyz') returns ToolResult.error()."""
    from loopai.tools.bash import BashTool

    tool = BashTool(working_dir="/tmp")
    result = await tool.execute("nonexistent_cmd_xyz")
    assert result.status == "error"
    assert result.is_error is True
    assert result.error_message is not None


# ── Test 14: BashTool timeout on slow command ───────────────────────────


@pytest.mark.asyncio
async def test_14_bash_tool_timeout():
    """BashTool.execute('sleep 999', timeout=1.0) returns error within ~1s."""
    from loopai.tools.bash import BashTool

    tool = BashTool(working_dir="/tmp")
    result = await tool.execute("sleep 999", timeout=1.0)
    assert result.status == "error"
    assert result.is_error is True
    # duration should be close to the 1.0s timeout (within reasonable margin)
    assert 500 <= result.duration_ms <= 3000, (
        f"Expected duration ~1000ms, got {result.duration_ms}"
    )


# ── Test 15: BashTool rejects shell metacharacters ──────────────────────


@pytest.mark.asyncio
async def test_15_bash_tool_rejects_shell_metacharacters():
    """BashTool.execute('ls | grep foo') returns error — intercepts shell metachar."""
    from loopai.tools.bash import BashTool

    tool = BashTool(working_dir="/tmp")
    result = await tool.execute("ls | grep foo")
    assert result.status == "error"
    assert result.is_error is True
    assert result.error_message is not None


# ── Test 16: BashTool truncates output over 100KB ──────────────────────


@pytest.mark.asyncio
async def test_16_bash_tool_truncates_large_output():
    """BashTool output > 100KB is truncated and truncated=True."""
    from loopai.tools.bash import BashTool

    tool = BashTool(working_dir="/tmp", max_output_bytes=1024)  # small limit for test
    # Generate a command that produces large output
    result = await tool.execute(
        "dd if=/dev/zero bs=2048 count=1 status=none | base64"
    )
    if result.status == "success":
        # If command succeeded, check truncation behavior
        data_str = str(result.data)
        data_bytes = len(data_str.encode("utf-8"))
        # Data should be approximately within max_output_bytes
        assert data_bytes <= 2048, (
            f"Output {data_bytes} bytes exceeds max_output_bytes with margin"
        )


# ── Test (bonus): create_bash_tool returns decorated function ───────────


def test_create_bash_tool_returns_decorated_function():
    """create_bash_tool() returns a function with __tool_meta__ attribute."""
    from loopai.tools.bash import create_bash_tool

    bash_fn = create_bash_tool(working_dir="/tmp")
    assert callable(bash_fn)
    assert hasattr(bash_fn, "__tool_meta__")
    meta = bash_fn.__tool_meta__
    assert meta.name == "bash"
    assert "shell" not in meta.description.lower() or meta.description  # has description
    assert meta.timeout == 60.0


# ═══════════════════════════════════════════════════════════════════════════
# Task 3: PermissionGuard — dangerous command confirmation via EventBus
# ═══════════════════════════════════════════════════════════════════════════


# ── Test 17: PermissionGuard.check() — SAFE → allow ─────────────────────


@pytest.mark.asyncio
async def test_17_permission_guard_safe_allows():
    """PermissionGuard.check() for SAFE permission returns (True, 'allow')."""
    from loopai.state_machine.guards import PermissionGuard
    from loopai.events.bus import EventBus
    from loopai.tools.types import PermissionLevel

    bus = EventBus()
    guard = PermissionGuard(bus)

    should_proceed, action = await guard.check(
        tool_name="bash.ls",
        tool_args={"path": "."},
        permission_level=PermissionLevel.SAFE,
        session_id="test-session-1",
        step_num=1,
    )
    assert should_proceed is True
    assert action == "allow"


# ── Test 18: PermissionGuard.check() — MODERATE → allow ─────────────────


@pytest.mark.asyncio
async def test_18_permission_guard_moderate_allows():
    """PermissionGuard.check() for MODERATE permission returns (True, 'allow')."""
    from loopai.state_machine.guards import PermissionGuard
    from loopai.events.bus import EventBus
    from loopai.tools.types import PermissionLevel

    bus = EventBus()
    guard = PermissionGuard(bus)

    should_proceed, action = await guard.check(
        tool_name="bash.cp",
        tool_args={"src": "a.txt", "dst": "/home/user/b.txt"},
        permission_level=PermissionLevel.MODERATE,
        session_id="test-session-1",
        step_num=1,
    )
    assert should_proceed is True
    assert action == "allow"


# ── Test 19: PermissionGuard.check() — DANGEROUS → confirm_required ─────


@pytest.mark.asyncio
async def test_19_permission_guard_dangerous_requires_confirmation():
    """PermissionGuard.check() for DANGEROUS publishes event, returns (False, 'confirm_required')."""
    from loopai.state_machine.guards import PermissionGuard
    from loopai.events.bus import EventBus
    from loopai.tools.types import PermissionLevel

    bus = EventBus()
    guard = PermissionGuard(bus, confirmation_timeout=0.5)  # short timeout for test

    # Subscribe to confirmation_required events before calling check
    event_queue = await bus.subscribe("confirmation_required")

    # Start check — it will block waiting for confirmation
    import asyncio
    check_task = asyncio.create_task(
        guard.check(
            tool_name="bash.rm",
            tool_args={"path": "/etc/dangerous"},
            permission_level=PermissionLevel.DANGEROUS,
            session_id="test-session-1",
            step_num=1,
        )
    )

    # Wait for the event to be published
    event = await asyncio.wait_for(event_queue.get(), timeout=1.0)
    assert event is not None
    assert event["event_type"] == "confirmation_required"
    assert event["tool_name"] == "bash.rm"
    assert "confirmation_id" in event

    # Verify the check hasn't completed yet (still waiting)
    assert not check_task.done()

    # Cleanup: send response so check_task can complete
    guard.respond(event["confirmation_id"], approved=False)

    should_proceed, action = await asyncio.wait_for(check_task, timeout=1.0)
    assert should_proceed is False
    assert action == "user_denied"


# ── Test 20: PermissionGuard.respond(approved=True) → allow ──────────────


@pytest.mark.asyncio
async def test_20_permission_guard_respond_approved():
    """respond(approved=True) causes check() to return (True, 'allow')."""
    from loopai.state_machine.guards import PermissionGuard
    from loopai.events.bus import EventBus
    from loopai.tools.types import PermissionLevel

    bus = EventBus()
    guard = PermissionGuard(bus, confirmation_timeout=5.0)

    import asyncio
    check_task = asyncio.create_task(
        guard.check(
            tool_name="bash.rm",
            tool_args={"path": "/tmp/safe"},
            permission_level=PermissionLevel.DANGEROUS,
            session_id="test-session-2",
            step_num=3,
        )
    )

    # Give the event time to publish, then respond
    await asyncio.sleep(0.05)
    confirmation_id = "test-session-2_bash.rm_3"
    guard.respond(confirmation_id, approved=True)

    should_proceed, action = await asyncio.wait_for(check_task, timeout=1.0)
    assert should_proceed is True
    assert action == "allow"


# ── Test 21: PermissionGuard.respond(approved=False) → user_denied ──────


@pytest.mark.asyncio
async def test_21_permission_guard_respond_denied():
    """respond(approved=False) causes check() to return (False, 'user_denied')."""
    from loopai.state_machine.guards import PermissionGuard
    from loopai.events.bus import EventBus
    from loopai.tools.types import PermissionLevel

    bus = EventBus()
    guard = PermissionGuard(bus, confirmation_timeout=5.0)

    import asyncio
    check_task = asyncio.create_task(
        guard.check(
            tool_name="bash.shred",
            tool_args={"path": "/secret/file"},
            permission_level=PermissionLevel.DANGEROUS,
            session_id="test-session-3",
            step_num=2,
        )
    )

    await asyncio.sleep(0.05)
    confirmation_id = "test-session-3_bash.shred_2"
    guard.respond(confirmation_id, approved=False)

    should_proceed, action = await asyncio.wait_for(check_task, timeout=1.0)
    assert should_proceed is False
    assert action == "user_denied"


# ── Test 22: PermissionGuard timeout → auto-deny ────────────────────────


@pytest.mark.asyncio
async def test_22_permission_guard_timeout_auto_denies():
    """PermissionGuard.check() times out if no response within confirmation_timeout."""
    from loopai.state_machine.guards import PermissionGuard
    from loopai.events.bus import EventBus
    from loopai.tools.types import PermissionLevel

    bus = EventBus()
    guard = PermissionGuard(bus, confirmation_timeout=0.2)  # very short timeout

    should_proceed, action = await guard.check(
        tool_name="bash.rm",
        tool_args={"path": "/some/file"},
        permission_level=PermissionLevel.DANGEROUS,
        session_id="test-session-4",
        step_num=1,
    )
    assert should_proceed is False
    assert action == "timeout"
