# Adaptive workflow

## Contents

- [State model](#state-model)
- [Phase gates](#phase-gates)
- [Concurrency](#concurrency)
- [Stop and re-plan](#stop-and-re-plan)

## State model

Treat the workflow as a policy-driven loop:

```text
UNDERSTAND -> PLAN -> DELEGATE/IMPLEMENT -> VALIDATE -> REVIEW -> ACCEPT
                   ^                         |           |
                   |-------------------------+-----------+
                              re-plan or fix
```

The lead chooses the next transition from current evidence. Do not schedule
all phases or agents in advance.

## Phase gates

### Understand

Exit when the goal, constraints, repository rules, likely execution path, and
acceptance criteria are known. Delegate mapping when ownership or flow remains
unclear.

### Plan

Exit when the change boundary, implementation order, validation strategy, and
material risks are explicit. Keep plans outcome-focused and update them when
new evidence invalidates an assumption.

### Implement

Exit when the bounded writer has produced a coherent change and local focused
checks. A worker report is a claim, not acceptance evidence.

### Validate

Escalate from affected-target compilation to focused tests, relevant regression
tests, and broader suites only when risk justifies it. Classify failures as
implementation, environment, flaky, or pre-existing.

### Review

Use independent review for moderate and complex work. Add domain reviewers only
when the changed behavior intersects their scope.

### Accept

The lead inspects the diff, reruns decisive verification, resolves blocking
findings, and confirms scope. Only the lead declares the user task complete.

## Concurrency

- Independent exploration, test analysis, log analysis, and specialist review
  may still run concurrently.
- Exclude `docs_researcher_luna` and `docs_researcher_terra` from concurrent
  documentation. Native docs research is PRECHECK then Luna then at most one
  Terra.
- Keep overlapping code changes serial under one writer.
- If writers are disjoint, name exact owned paths and the later integration
  order before spawning them.
- Default to no more than six open subagent threads unless project or runtime
  policy is lower.
- Close or reuse completed threads when supported instead of accumulating idle
  context.

## Stop and re-plan

Re-plan when evidence changes the failure model, required interface, ownership
boundary, or correctness strategy. Do not restart completed, still-valid work.

Stop autonomous iteration when:

- a required permission or user decision would materially change scope;
- the same blocker survives three corrected attempts;
- the requested runtime/model cannot be verified and no declared fallback is
  safe;
- verification cannot distinguish a correct change from a false positive.

## Offline forward helper

After the parent has explicitly classified a closed task packet, the shipped
`payload/skills/versatile-dev/scripts/forward_router.py` may be used for a
deterministic offline plan or full route-document replay:

```text
python3 payload/skills/versatile-dev/scripts/forward_router.py plan -
python3 payload/skills/versatile-dev/scripts/forward_router.py replay PACKET.json ROUTE.json
```

The helper validates canonical packet hashes, repository-relative paths, writer
ownership, and closed role choices. It never classifies English, spawns a
native agent, authenticates or probes, creates an App task, or promotes
configured/App facts to native effective evidence. Replay requires the full
closed route document and replays the offline route helper; native spawn and
App actions remain parent Skill authority.
