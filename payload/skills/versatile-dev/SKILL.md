---
name: versatile-dev
description: Use for non-trivial repository engineering needing mapping, planning, implementation, tests, independent review, acceptance, or targeted CUDA/HPC/numerical/security specialists. Do not use for simple Q&A or status-only work. Probes and App tasks are not native effective evidence; this Skill does not change the parent model or permissions, guarantee model availability, or perform automatic CLI model switching or fallback.
---

# Versatile Development

## Contract

<!-- BEGIN versatile-dev canonical contract -->
Lead owns user intent, architecture, task state, diff, tests, review triage, and acceptance.
Simple obvious changes use direct work; delegation is only for material work.
The task packet has exactly five parts: Objective, Ownership, Inputs/evidence, Constraints/requirements, Verification/handoff.
A dynamic packet names actual files, interfaces, commands, evidence, constraints, and verification.
One writer owns overlapping files; parallel work is limited to disjoint files.
A fresh independent reviewer reviews the completed diff; any correction invalidates the verdict and requires fresh review.
The lead reruns verification and alone accepts completion.
Route gpu_reviewer, numerics_reviewer, parallelism_reviewer, performance_profiler, and security_reviewer only when their boundary is touched; never spawn all specialists by default.
<!-- END versatile-dev canonical contract -->

Use the direct references below when the task needs their detailed schema or review rules.

## References

[model routing](references/model-routing.md)
[task contract](references/task-contract.md)
[CUDA and CAE review](references/cuda-cae-review-policy.md)
[workflow](references/workflow.md)
[review policy](references/review-policy.md)
