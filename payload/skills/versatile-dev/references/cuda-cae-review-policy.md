# CUDA, HPC, CAE, and numerical review

## Route by changed behavior

| Change | Required specialist |
| --- | --- |
| CUDA kernels, memory, streams, launches | `gpu_reviewer` |
| Numerical methods, solvers, conservation | `numerics_reviewer` |
| CPU threads, CUDA streams, MPI, NCCL | `parallelism_reviewer` |
| Claimed performance improvement | `performance_profiler` |
| Behavior or tolerance change | `test_validator` |
| General implementation | `reviewer` |

Do not start every specialist when the change does not cross its boundary.

## Immutable correctness harness

Treat the existing compile, regression, numerical, and physical checks as the
baseline. A candidate optimization must not weaken thresholds, remove cases, or
change reference outputs merely to pass. Any intentional tolerance or reference
change requires an explicit rationale and independent validation.

## GPU evidence

Check synchronization, stream dependencies, races, atomics, allocation
lifetime, coalescing, shared memory, register pressure, occupancy, divergence,
transfers, launch configuration, and async API error handling.

Do not claim a speedup from source inspection. Require representative benchmark
or profiler evidence and compare end-to-end behavior, not only one kernel.

## Numerical and physical evidence

Check stability, convergence, conservation, conditioning, discretization,
boundary conditions, floating-point sensitivity, determinism assumptions, and
physically meaningful invariants. Validate representative scales and edge
cases, not only a toy input.

## Parallel evidence

Check data ownership, ordering, barriers, progress, collectives, reduction
semantics, cancellation, teardown, and oversubscription. Include at least one
stress or repeated execution when practical.
