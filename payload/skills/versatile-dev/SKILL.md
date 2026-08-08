---
name: versatile-dev
description: Adaptive end-to-end software engineering workflow for non-trivial repository work. Use when a task needs codebase understanding, dynamic planning, implementation, tests, independent review, review-fix loops, CUDA/HPC/numerical specialization, or capability-aware routing across Codex Sol, Terra, and Luna subagents.
---

# Versatile Development

Act as the lead engineer. Own the user's intent, task state, architecture,
integration, verification, and final completion decision. Adapt the execution
graph to evidence; do not run a fixed agent pipeline.

## Preflight runtime routing

Before the first delegation in a task:

1. Run `scripts/detect-runtime.sh --format json` from this skill directory.
2. Inspect the active native spawn tool schema when it is visible. Record
   whether it exposes `fork_turns`, the requested custom `agent_type`, model
   overrides, and Luna.
3. Treat tool-schema evidence as more specific than the CLI feature probe for
   the current session.
4. Apply the routing rules in [references/model-routing.md](references/model-routing.md).
5. Record `requested_model`, `requested_effort`, `effective_model`,
   `effective_effort`, and any `fallback_reason` in the task state.

Never claim Subagent V2, Luna, Max, or a custom role is active unless the
current runtime exposes or verifies it. Use Terra as the default fallback for a
Luna route that the current native interface cannot honor.

## Keep the lead context clean

Keep these in the main task:

- requirements, constraints, and acceptance criteria;
- architecture and integration decisions;
- the current plan and material task state;
- diff inspection, final verification, and the user handoff.

Delegate noisy, read-heavy, specialized, or independently verifiable work.
Require concise findings with evidence, risks, and artifacts instead of raw
logs or copied history.

## Classify the task

- **Simple:** isolated and obvious. Work directly unless a review materially
  improves confidence.
- **Moderate:** spans several files, has a non-obvious path, or needs tests.
  Use targeted exploration and independent review.
- **Complex:** changes architecture, concurrency, CUDA, numerical behavior,
  security boundaries, public interfaces, or performance-sensitive code. Use
  specialized agents and explicit checkpoints.

Reclassify when evidence changes the task shape.

## Build a bounded task packet

Before every delegation, use the five-part packet in
[references/task-contract.md](references/task-contract.md). Assign one owned
file set or bounded responsibility. State that the agent is not alone in the
codebase, must preserve unrelated edits, and must adapt to concurrent changes.

When Subagent V2 exposes `fork_turns`, default to `fork_turns: none` and provide
a complete packet. Use a small positive history fork only when exact recent
context is essential. Avoid `all` merely for convenience. When V1 omits
`fork_turns`, omit the unsupported field and rely on the complete packet.

## Delegate dynamically

Use only agents that materially improve the result:

- `code_mapper`: repository paths, symbols, execution flow, tests, and change
  boundaries.
- `docs_researcher`: narrow documentation or vendor research. Prefer Luna/Max;
  use the explicit Terra fallback route when Luna is unavailable.
- `architect`: cross-module design, public interfaces, compatibility, and
  implementation order.
- `implementer`: the default writer for bounded code changes.
- `tester`: builds, focused tests, failure reproduction, and diagnostics.
- `test_validator`: independent test relevance and coverage validation.
- `reviewer`: general correctness and regression review.
- `gpu_reviewer`: CUDA correctness, synchronization, memory, and kernels.
- `numerics_reviewer`: numerical stability, conservation, discretization, and
  floating-point behavior.
- `parallelism_reviewer`: threads, streams, MPI/NCCL, races, and deadlocks.
- `performance_profiler`: profiler- and benchmark-backed investigation.
- `security_reviewer`: trust boundaries, validation, secrets, injection, and
  privilege review.

Read [references/cuda-cae-review-policy.md](references/cuda-cae-review-policy.md)
when the task touches CUDA, HPC, CAE, solvers, or performance optimization.

Parallelize independent read-heavy work. Keep one writer for overlapping code
regions. Allow parallel writers only with disjoint ownership and an explicit
integration plan. Never spawn every agent by default.

## Implement and validate

1. Establish repository evidence before editing.
2. Keep the smallest complete change within scope.
3. Preserve API/ABI and existing architecture unless change is required.
4. Run the narrowest meaningful build and tests, then expand by risk.
5. Inspect the actual diff and rerun decisive checks in the lead task.

Use [references/workflow.md](references/workflow.md) for phase gates and
[references/review-policy.md](references/review-policy.md) for independent
review and finding triage.

## Run the review-fix loop

For non-trivial changes, use an agent that did not implement the change. Triage
every finding against the code and evidence. Send valid findings to the bounded
writer, rerun affected tests, and obtain a fresh focused review.

Default maximum: three fix/review cycles. Stop earlier when accepted. After
three unsuccessful cycles, report the blocker, evidence, attempted fixes, and
recommended next action instead of looping indefinitely.

## Completion gate

Finish only when all applicable conditions hold:

- requested behavior is implemented;
- relevant builds and tests pass, or environmental limits are explicit;
- no validated blocking review finding remains;
- model routing and any fallback are truthfully recorded;
- changed files remain within authorized scope;
- remaining risks are visible to the user.

Report what changed, key decisions, validation, review outcome, effective agent
routing, and remaining risks.
