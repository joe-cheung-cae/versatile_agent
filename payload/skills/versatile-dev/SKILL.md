---
name: versatile-dev
description: Use for non-trivial repository engineering needing mapping, planning, implementation, tests, independent review, acceptance, targeted CUDA/HPC/numerical/security specialists, or native documentation research, vendor research, or API research (Luna-first / Terra-second). Do not use for simple Q&A or status-only work, including diagnostic status questions.
---

# Versatile Development

## Contract

<!-- BEGIN versatile-dev canonical contract -->
Lead owns user intent, architecture, task state, diff, tests, review triage, and acceptance.
Classify work as Simple (isolated and obvious), Moderate (multi-file, non-obvious, or test-bearing), or Complex (architecture, concurrency, CUDA, numerical, security, interface, or performance-sensitive); reclassify when evidence changes.
Simple obvious changes use direct work; delegate only when delegation is material to correctness, coverage, or throughput.
Native documentation research uses the same-interface PRECHECK; missing, conflicting, or unobservable metadata fails closed, with routing details in the model-routing reference.
Luna is first; only a classified native routing rejection or complete same-attempt native mismatch permits at most one Terra; all other outcomes fail closed.
The App user-visible task lane is separate and requires explicit authorization in the current user request; it never supplies native effective evidence or authorizes Terra fallback.
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
