# 模型与接口路由

本 reference 描述已验收的 native research orchestration contract。它要求
显式编排，不把 CLI 的模型选择、probe、TOML、catalog 或 App task 当作
native effective evidence。

## Canonical routing contract

<!-- BEGIN versatile-dev canonical routing contract -->
Both docs_researcher_luna and docs_researcher_terra are installed and pinned to gpt-5.6-luna/max and gpt-5.6-terra/high.
Both researchers use the same-interface PRECHECK.
route_research.py provides deterministic replay and decision semantics.
Luna is first; only a classified native routing rejection or complete same-attempt native mismatch permits at most one Terra attempt.
A permitted Terra transition is FALLBACK_PENDING and is limited to one Terra attempt.
Content, tool, task, timeout, and unknown failures do not authorize Terra fallback.
Missing, conflicting, or unobservable effective evidence is STOP_UNVERIFIED.
Every attempt carries the same canonical task_packet_hash.
runtime_audit.py is separate from the installation manifest.
Installed, configured, capability, requested, observed, and effective are separate fact layers.
The installation manifest, probe, and App task cannot fill native effective facts.
The App user-visible task lane requires explicit authorization in the current user request and cannot authorize native Terra fallback.
This Skill cannot change the parent model, bypass permissions, guarantee model availability, or perform automatic CLI model switching or fallback.
Offline validation does not prove live runtime conformance.
<!-- END versatile-dev canonical routing contract -->

安装 bundle 同时包含两个 read-only named agents：

1. `docs_researcher_luna`，请求 `gpt-5.6-luna` / `max`；
2. `docs_researcher_terra`，请求 `gpt-5.6-terra` / `high`，最多一次
   (at most one) Terra attempt。

`route_research.py` 是离线、纯函数、确定性的 replay/decision helper；它不
spawn agent、不访问网络或认证、不执行 probe，也不从配置或 App 数据发明
事实。Luna 与 Terra attempt 必须使用相同的 canonical `task_packet_hash`，
且 `fallback_attempt` 最多为 `1`。

## 证据分层与 runtime record

不得将 CLI、App-bundled CLI、native spawn 和 App task 的数据拼接为一个
runtime，除非有明确 bridge evidence。每个 runtime 独立记录：

```text
schema_version
runtime_id
binary_path
version
interface_kind
multi_agent_generation
exposed_agent_types
model_support
effort_support
evidence_source
captured_at
diagnostic_only
```

层次必须保持分离：

| 层 | 可用证据 | 不可推导的结论 |
| --- | --- | --- |
| installed | 文件路径、install manifest、`selected_profile` | 当前任务实际运行的 route |
| configured | custom-agent TOML、`[agents]` default | native runtime 实际采纳的 model/effort |
| capability | CLI/App-bundled CLI probe、model catalog、active interface schema | 某次 native attempt 已接受或实际生效 |
| requested | 本次 native spawn 的 agent/model/effort 请求 | 请求已被接受或生效 |
| observed | 返回的 native runtime details、sandbox/permission details | 未返回字段的值 |
| effective | 与 observed native details 一一对应的 model/effort | CLI/App probe、catalog 或 TOML 的推测 |

`scripts/detect-runtime.sh`、model catalog 及 `--native-v2-luna yes` 只能是
capability/diagnostic evidence，并必须标记 `diagnostic_only=true`。即使 probe
建议或安装器选择了 profile，`selected_profile` 也只是 install-time 选择，
不是 effective runtime route。

## 目标 native 状态与失败分类

目标 pair 的 `PRECHECK` 先于任何 spawn：同一 active native interface 必须
同时暴露 `docs_researcher_luna` 和 `docs_researcher_terra`。同一 interface 上
Codex-observable 的 parent-authored native capability inventory 是合法的
exposure 能力证据。exposure metadata 缺失、不可观测，或只暴露其中一个
type 时，立即 `STOP_UNVERIFIED`；不得 spawn Luna、Terra 或 alternate role。
此时不存在可分类的 Luna attempt。

PRECHECK 成功后才可 spawn Luna。只有该次 Luna native spawn 从**同一
interface** 返回明确且可归因的 routing rejection，才是
`NATIVE_ROUTING_FAILURE`：包括 requested role/model/effort 不可用、access
denied、spawn 明确因这些 routing 条件被拒绝，或完整的 same-attempt observed
role/model/effort 明确不匹配 requested/configured route。这个已实际发生的
rejection 或 mismatch 可进入 `FALLBACK_PENDING`。已接受或运行中的 Luna
attempt 若缺少、内部冲突、跨 runtime 混用或不可观测的 effective metadata，
始终是 `STOP_UNVERIFIED`，不触发 Terra。

| 事件 | 状态 | 是否可重派 Terra |
| --- | --- | --- |
| PRECHECK 的 exposure metadata 缺失/不可观测，或同一 interface 未同时暴露两个 target type | `STOP_UNVERIFIED`，不 spawn | 否 |
| Luna attempt 收到同一 interface 的明确、可归因 routing rejection，或完整 observed role/model/effort 明确不匹配 requested/configured route | `FALLBACK_PENDING`，随后至多一次 `docs_researcher_terra` | 是 |
| 已接受/运行 Luna attempt 的 effective metadata 缺失、冲突、不可观测，或不同 runtime 的证据被混用 | `STOP_UNVERIFIED` | 否 |
| Luna 的 observed agent/model/effort 与请求和配置一致 | `DONE_LUNA` | 否 |
| Terra attempt 的 observed agent/model/effort 与请求和配置一致 | `DONE_TERRA` | 否 |
| 内容质量、工具调用、任务执行失败 | `STOP_FAILED` | 否 |
| timeout | `STOP_FAILED`；若同时缺 effective metadata，优先 `STOP_UNVERIFIED` | 否 |
| unknown exception | `STOP_UNVERIFIED` | 否 |
| Terra 尝试后任何路由或执行失败 | `STOP_FAILED`；缺/冲突 effective metadata 时为 `STOP_UNVERIFIED` | 否 |

只有表中第二行的、发生在 PRECHECK 成功之后的
`NATIVE_ROUTING_FAILURE` 允许显式创建 Terra 尝试。不得把 PRECHECK 中的
type 缺失，或“Luna 不可用”的 probe、TOML profile、模型 catalog、配置选择，
视为这类失败或直接启动 Terra。每次 STOP 都要保留 failure class 和原始
evidence。

`failure_class` 使用以下封闭分类：`NONE`、`NATIVE_ROUTING_FAILURE`、
`ROUTE_METADATA_MISSING`、`ROUTE_METADATA_CONFLICT`、`TASK_FAILURE`、
`TIMEOUT`、`UNKNOWN_EXCEPTION`。只有 `NATIVE_ROUTING_FAILURE` 可进入
`FALLBACK_PENDING`；metadata 类始终失败关闭为 `STOP_UNVERIFIED`。

## App task lane

Codex App 的 user-visible task 是独立的 explicit opt-in lane，不是 native
subagent thread，也不是 Luna→Terra fallback。只有用户明确授权创建可见任务
时才可使用；App capability 或创建结果不得证明 native route 的 effective
model/effort。App task 记录可保留 requested/observed App 事实，但不得填充
native `effective_*` 字段。

## Per-attempt audit

安装清单与 per-attempt audit 是两个不同的封闭 artifact。`install-manifest.json`
只能是 `artifact_kind=installation_manifest`、`schema_version=2`，并只记录
`bundle_version`、`installed_at`、`scope`、`selected_profile`、13 个
`installed_agents`，以及 keyed `configured_researchers`（Luna 与 Terra 的
`agent_type`/`model`/`effort`）。它不能记录 probe、observed/effective、fallback
success 或 capability claim；`selected_profile` 只是 legacy install selector。

每次 native 或独立 App-task 尝试都通过
`scripts/runtime_audit.py` 写一个独立的 `artifact_kind=runtime_route_audit`、
`schema_version=1` 文档。文档只有 `schema_version`、`artifact_kind`、`attempt`；
`attempt` 恰好包含下列字段，未知事实必须保留字面值 `unknown`：

```text
attempt_id
task_packet_hash
interface
requested_agent_type
requested_model
requested_effort
configured_agent_type
configured_model
configured_effort
observed_agent_type
observed_effective_model
observed_effective_effort
requested_sandbox
observed_sandbox
permission_profile
status
failure_class
fallback_reason
fallback_attempt
evidence_source
```

`configured_*` 只能来自 TOML；`observed_effective_*` 只能来自本次 native
runtime details。不得用 installed/configured/capability data 填 effective
字段。`evidence_source` 恰好包含 `kind`、`interface`、`runtime_id`、
`attempt_id`、`scope`、`diagnostic_only`；允许的 kind 只有
`native_runtime_details`、`app_task_details`、`configured_agent_toml`、
`install_manifest`、`diagnostic_probe`。已知 observed effective agent/model/effort
必须是完整 tuple，并要求 `native_runtime_details`、`scope=single-attempt`、
`diagnostic_only=false`、native interface 及相同 `attempt_id`；其余 source 不能
填充该 tuple。requested/configured tuple 也必须全 known 或全 `unknown`。

Helper 只做离线、确定性、closed/type-strict validation 与 canonical JSON；它不
spawn、probe、读取 TOML/catalog、合并 runtime records 或发明事实。JSON 输入严格
UTF-8，重复成员和 padded/mixed 值 fail closed；canonicalize 的文件输出采用
atomic replacement。Luna/Terra 的 `task_packet_hash` 变化必须由消费者视为不同
attempt chain；helper 只验证 canonical hash 及 attempt/fallback 字段，不跨文件
推断连续性。

Luna 与 Terra 使用相同 task packet，除 agent/model/effort 和路由审计元数据外不改变任务内容。

## Context transfer

Subagent V2 history forking 是传输选项，不是复制全部 parent context 的理由。
优先使用完整 task packet 与 `fork_turns: none`；仅在确有必要时使用小的
positive fork。V1 不支持时省略该字段，但仍使用同一完整 packet。
