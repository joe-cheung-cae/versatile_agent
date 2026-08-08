# Model and interface routing

## Contents

- [Routing order](#routing-order)
- [Role defaults](#role-defaults)
- [Luna fallback](#luna-fallback)
- [Context transfer](#context-transfer)
- [Audit record](#audit-record)

## Routing order

Use current-session evidence in this order:

1. Active native spawn tool schema and returned agent details.
2. `scripts/detect-runtime.sh` results for CLI and App-bundled CLI.
3. Installed custom-agent TOML.
4. Project `[agents]` defaults.
5. Parent model and effort.

If sources conflict, prefer the active callable interface and record the
conflict.

## Role defaults

- Sol/High or higher: architecture, independent review, security, numerical,
  and high-consequence boundary reasoning.
- Terra/Medium or High: implementation, exploration, testing, profiling, and
  the general native fallback lane.
- Luna/Max: narrow, explicit, repeatable research or high-throughput support
  work when the interface supports the combination.

Model pins in installed agent files take precedence over `[agents]` defaults.

## Luna fallback

Apply this decision table:

| Runtime evidence | Effective route |
| --- | --- |
| Native V2 exposes Luna and Max | Luna/Max |
| Native V2 exists but omits Luna | Terra/High fallback |
| CLI V1 custom agents support Luna and Max | Luna/Max V1 profile |
| Luna or Max validation fails | Terra/High fallback |
| App task tools expose Luna/Max and the user explicitly requests a separate visible task | Luna/Max App task |

Do not silently substitute. Emit `fallback_reason` and continue only when Terra
can satisfy the task.

Use this fallback order when a Luna profile was installed but the active spawn
schema proves it cannot be honored:

1. Spawn a read-only built-in/default agent with an explicit Terra/High override
   when the schema supports model and effort overrides.
2. Otherwise send the same narrow research packet to `code_mapper`, record its
   effective Terra/Medium pin, and prohibit code edits.
3. If neither route is observable, keep the research in the lead task and report
   that no subagent fallback was available.

The App task route is not a native subagent thread. Do not create a user-visible
task without explicit authorization, and do not describe it as a V2 spawn.

## Context transfer

Subagent V2 history forking is a transport option, not a reason to copy all
parent context. Prefer a complete task packet with no history. Use a bounded
positive fork only when exact recent exchanges are essential. V1 receives the
same explicit packet without unsupported fork arguments.

## Audit record

Keep this compact record for every non-default route:

```text
role:
interface: native-v2 | native-v1 | app-task | single-agent
requested_model:
requested_effort:
effective_model:
effective_effort:
fallback_reason: none | <reason>
evidence:
```
