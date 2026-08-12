---
name: versatile-dev
description: Use for non-trivial repository engineering needing mapping, planning, implementation, tests, independent review, acceptance, or targeted CUDA/HPC/numerical/security specialists. Do not use for simple Q&A or status-only work. Probes and App tasks are not native effective evidence; this Skill does not change the parent model or permissions, guarantee model availability, or perform automatic CLI model switching or fallback.
---

# Versatile Development

Act as the lead engineer. Own the user's intent, architecture, task state and
plan, integration, diff, tests, review triage, acceptance, and final handoff.
Keep the execution graph evidence-driven; do not schedule a fixed agent
pipeline.

## Classify the work

- **Simple:** isolated and obvious. Work directly; add review only when it
  materially improves confidence.
- **Moderate:** spans several files, has a non-obvious path, or needs tests.
  Use targeted mapping, bounded delegation, and independent review.
- **Complex:** changes architecture, concurrency, CUDA, numerical behavior,
  security boundaries, public interfaces, or performance-sensitive code. Use
  explicit checkpoints and only the specialists whose boundaries are touched.

Reclassify when repository evidence changes the task shape. Delegate only when
the delegation materially improves correctness, coverage, or throughput.

## Route native research conservatively

The installed common bundle contains both read-only researcher agents:
`docs_researcher_luna` requests `gpt-5.6-luna`/`max`, and
`docs_researcher_terra` requests `gpt-5.6-terra`/`high`. Before native research,
use the active interface's own exposure metadata for the same-interface
`PRECHECK`; it must expose both exact agent types. Missing, conflicting, or
unobservable metadata is `STOP_UNVERIFIED` and authorizes no spawn.

Use `route_research.py` for deterministic offline replay and decision evidence.
Dispatch Luna first. Permit at most one Terra attempt only after a classified native
routing rejection or a complete same-attempt native route mismatch, with
`FALLBACK_PENDING` and the same canonical `task_packet_hash`. Content, tool,
task, timeout, and unknown-exception outcomes never authorize Terra. Do not
infer a native effective route from a probe, TOML, catalog, install manifest,
or App task.

Record each attempt through `runtime_audit.py` as a separate runtime audit;
keep it separate from the installation manifest. The manifest records only
installed/configured facts, while observed native effective facts require
complete, same-attempt native runtime details. Preserve `unknown` and stop
fail-closed when effective metadata is missing or conflicts. Read the complete
state, failure, field, and evidence contract in
[references/model-routing.md](references/model-routing.md).

The App user-visible task lane is separate from native research. Create an App
task only after explicit authorization in the current user request. App task
capability or result data cannot establish native effective model or effort,
and cannot authorize native Terra fallback.

## Keep the lead context clean

Keep requirements, constraints, architecture decisions, material task state,
diff inspection, decisive verification, and acceptance in the lead task.
Delegate noisy read-heavy mapping, bounded implementation, test analysis, or
independent review with concise evidence, risks, and artifacts.

Use direct work for simple obvious changes. For delegated work, use exactly the
five-part packet in [references/task-contract.md](references/task-contract.md):
Objective, Ownership, Inputs/evidence, Constraints/requirements, and
Verification/handoff. The static contract stays generic; each dynamic packet
must name the actual files, interfaces, commands, and acceptance evidence.

Assign one owned file set or bounded responsibility. One writer owns overlapping
files or regions; parallel writers require disjoint paths and an explicit
integration order. Preserve unrelated edits and adapt to concurrent changes.
Use complete packets with `fork_turns: none` by default when V2 supports it;
omit unsupported fields under V1.

## Select specialists by touched boundary

Route selectively: `gpu_reviewer` for CUDA/GPU kernels, memory, or launches;
`numerics_reviewer` for numerical methods, solvers, stability, or conservation;
`parallelism_reviewer` for threads, streams, MPI/NCCL, races, or deadlocks;
`performance_profiler` for claimed performance changes; and
`security_reviewer` for trust boundaries, validation, secrets, injection, or
privilege. Add `test_validator` for behavior/tolerance changes and `reviewer`
for general correctness. Never spawn all specialists by default. For CUDA,
HPC, CAE, solvers, or performance work, apply
[references/cuda-cae-review-policy.md](references/cuda-cae-review-policy.md).

## Implement, verify, and accept

Establish repository evidence before editing, keep the smallest complete
change, preserve existing API/ABI and architecture unless required, and expand
verification from focused checks to relevant regressions by risk. Use
[references/workflow.md](references/workflow.md) for phase gates.

For non-trivial changes, obtain review from an agent that did not author the
change. Triage every finding against code and evidence; a correction invalidates
the prior verdict, so rerun affected checks and obtain a fresh focused review.
Treat three fix/review cycles as the default advisory limit. Honor explicit
current-request authorization and terminal scope when they permit continued
corrections; otherwise report the blocker and evidence. Apply
[references/review-policy.md](references/review-policy.md).

Only the lead accepts completion. Confirm requested behavior, proportionate
builds/tests, no blocking validated finding, truthful installed/configured/
requested/observed/effective evidence separation, authorized scope, and visible
remaining risks. Do not claim that this Skill changes the parent model,
bypasses permissions, guarantees a model, performs automatic CLI routing, or
performs automatic CLI fallback; it establishes no runtime conformance from
offline validation.
