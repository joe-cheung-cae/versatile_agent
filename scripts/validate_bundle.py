#!/usr/bin/env python3
"""Offline structural validation for the distributable bundle.

The Skill checks below intentionally validate only a registered canonical
contract and an enumerated set of stale literals.  They do not classify
arbitrary English or attempt to render CommonMark.  Markdown checks use the
small, source-level dialect documented by the Skill.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Mapping


REQUIRED_AGENT_KEYS = frozenset({
    "name",
    "description",
    "developer_instructions",
    "model",
    "model_reasoning_effort",
    "sandbox_mode",
})
EXPECTED_COMMON = {
    "code_mapper",
    "architect",
    "implementer",
    "tester",
    "test_validator",
    "reviewer",
    "gpu_reviewer",
    "numerics_reviewer",
    "parallelism_reviewer",
    "performance_profiler",
    "security_reviewer",
    "docs_researcher_luna",
    "docs_researcher_terra",
}
EXPECTED_COMMON_FILES = {f"{name}.toml" for name in EXPECTED_COMMON}
AGENT_CONTRACT_HEADINGS = (
    "# ROLE AND SUCCESS",
    "# USE WHEN / DO NOT USE WHEN",
    "# REQUIRED INPUTS",
    "# OWNERSHIP",
    "# ALLOWED ACTIONS AND TOOLS",
    "# FORBIDDEN ACTIONS",
    "# WORKFLOW",
    "# STOP / ESCALATE",
    "# EVIDENCE",
    "# RETURN SCHEMA",
)
AGENT_CONTRACT_HEADING_NAMES = tuple(heading.removeprefix("# ") for heading in AGENT_CONTRACT_HEADINGS)
READ_ONLY_AGENTS = frozenset(
    {
        "architect",
        "code_mapper",
        "docs_researcher_luna",
        "docs_researcher_terra",
        "gpu_reviewer",
        "numerics_reviewer",
        "parallelism_reviewer",
        "reviewer",
        "security_reviewer",
        "test_validator",
    }
)
WRITER_AGENTS = frozenset({"implementer", "performance_profiler", "tester"})

# These are the complete physical lines whose values close a safety-relevant
# handoff contract.  They are source registrations, not hashes: surrounding
# explanatory prose remains flexible, while enum/status/verdict and researcher
# route/audit values cannot be widened by suffixes or weakened replacements.
RESEARCH_STATUS_FAILURE_MATRIX_LINES = (
    "COMPLETE + NONE: valid; COMPLETE iff FAILURE_CLASS=NONE.",
    "STOP_UNVERIFIED + ROUTE_METADATA_MISSING, ROUTE_METADATA_CONFLICT, or UNKNOWN_EXCEPTION: valid.",
    "STOP_FAILED + TASK_FAILURE: valid.",
    "STOP_FAILED + TIMEOUT: valid only when effective route metadata is complete and non-conflicting.",
    "STOP_UNVERIFIED + TIMEOUT: valid when effective route metadata is missing, conflicting, or unobservable; metadata uncertainty has priority.",
    "All other STATUS/FAILURE_CLASS combinations are invalid.",
)
RESEARCH_STATUS_FAILURE_SCHEMA_LINES = (
    "STATUS_FAILURE_MATRIX:",
    *RESEARCH_STATUS_FAILURE_MATRIX_LINES,
    "STATUS: COMPLETE | STOP_FAILED | STOP_UNVERIFIED; COMPLETE only when evidence supports the claims.",
    "FAILURE_CLASS: NONE | NATIVE_ROUTING_FAILURE | ROUTE_METADATA_MISSING | ROUTE_METADATA_CONFLICT | TASK_FAILURE | TIMEOUT | UNKNOWN_EXCEPTION.",
)
RESEARCH_REPORT_SCOPE_LINE = (
    "REPORT_SCOPE: Observed or returnable child report after a child attempt exists; "
    "a pre-spawn native rejection is parent-owned raw evidence and has no child handoff."
)


def _researcher_exact_schema_lines(
    requested_route: str, native_failure_line: str, route_authority: str
) -> tuple[str, ...]:
    return (
        f"REQUESTED_ROUTE: {requested_route}",
        "OBSERVED_ROUTE: Observed native route, or unknown when unobserved.",
        RESEARCH_REPORT_SCOPE_LINE,
        *RESEARCH_STATUS_FAILURE_SCHEMA_LINES,
        native_failure_line,
        f"ROUTE_AUTHORITY: {route_authority}",
    )

# These are deliberately closed contradictory literals. They catch explicit
# permissions or claims that would override a registered prohibition without
# attempting a general natural-language polarity or intent classifier. Punctuation
# variants are handled by _normalize_registered_text; the wording itself remains
# closed and registered.
GLOBAL_CONTRADICTORY_PERMISSION_RULES = (
    (
        (
            "may run destructive commands",
            "may execute destructive commands",
            "may issue destructive commands",
            "may perform destructive commands",
            "may run destructive operations",
            "may execute destructive operations",
            "may perform destructive operations",
            "may launch destructive operations",
        ),
        "contradictory destructive-command/operation permission is forbidden",
    ),
    (
        (
            "may perform harmful external exploitation",
            "may conduct harmful external exploitation",
            "may carry out harmful external exploitation",
            "may run harmful external exploitation",
            "may perform destructive external exploitation",
            "may conduct destructive external exploitation",
        ),
        "contradictory harmful-exploitation permission is forbidden",
    ),
    (
        (
            "may expose secrets",
            "may disclose secrets",
            "may reveal secrets",
            "may publish secrets",
            "may transmit secrets",
            "may output secrets",
            "may expose or disclose secrets",
        ),
        "contradictory secret-disclosure permission is forbidden",
    ),
    (
        (
            "may make an implicit commit, push, or PR",
            "may make an implicit commit, push, or pull request",
            "may perform an implicit commit, push, or PR",
            "may make an implicit commit/push/PR",
            "may create an implicit pull request",
            "may create an implicit PR",
            "may open an implicit pull request",
            "may open an implicit PR",
            "may submit an implicit pull request",
            "may submit an implicit PR",
            "may make an implicit pull request",
            "may make an implicit PR",
            "may create an implicit commit",
            "may perform an implicit commit",
            "may make an implicit push",
            "may perform an implicit push",
            "may commit implicitly",
            "may push implicitly",
        ),
        "contradictory implicit commit/push/PR authorization is forbidden",
    ),
    (
        (
            "may declare the parent task complete",
            "may declare the entire parent task complete",
            "may declare the broader parent task complete",
            "may declare the parent task is complete",
            "may declare the entire parent task is complete",
            "may declare the broader parent task is complete",
            "may claim the parent task is complete",
            "may claim the entire parent task is complete",
            "may claim the broader parent task is complete",
            "may mark the parent task complete",
            "may mark the parent task as complete",
            "may mark the entire parent task complete",
            "may mark the entire parent task as complete",
            "may mark the broader parent task complete",
        ),
        "contradictory whole-parent completion authorization is forbidden",
    ),
    (
        (
            "this TOML proves runtime model, effort, and sandbox effectiveness",
            "the TOML proves runtime model, effort, and sandbox effectiveness",
            "this configuration proves runtime model, effort, and sandbox effectiveness",
            "the configuration proves runtime model, effort, and sandbox effectiveness",
            "this TOML proves runtime behavior",
            "the TOML proves runtime behavior",
            "this configuration proves runtime behavior",
            "the configuration proves runtime behavior",
            "this TOML proves observed runtime behavior",
            "the TOML proves observed runtime behavior",
            "this configuration proves observed runtime behavior",
            "the configuration proves observed runtime behavior",
            "this TOML proves effective runtime behavior",
            "the TOML proves effective runtime behavior",
            "this configuration proves effective runtime behavior",
            "the configuration proves effective runtime behavior",
            "this TOML proves observed runtime route",
            "the TOML proves observed runtime route",
            "this configuration proves observed runtime route",
            "the configuration proves observed runtime route",
            "this TOML proves effective runtime route",
            "the TOML proves effective runtime route",
            "this configuration proves effective runtime route",
            "the configuration proves effective runtime route",
            "this TOML proves observed route, model, effort, and sandbox effectiveness",
            "the TOML proves observed route, model, effort, and sandbox effectiveness",
            "this configuration proves observed route, model, effort, and sandbox effectiveness",
            "the configuration proves observed route, model, effort, and sandbox effectiveness",
            "this TOML proves effective route, model, effort, and sandbox effectiveness",
            "the TOML proves effective route, model, effort, and sandbox effectiveness",
            "this configuration proves effective route, model, effort, and sandbox effectiveness",
            "the configuration proves effective route, model, effort, and sandbox effectiveness",
            "this TOML proves effective runtime model, effort, and sandbox effectiveness",
            "the TOML proves effective runtime model, effort, and sandbox effectiveness",
            "this configuration proves effective runtime model, effort, and sandbox effectiveness",
            "the configuration proves effective runtime model, effort, and sandbox effectiveness",
        ),
        "contradictory configured runtime-effectiveness claim is forbidden",
    ),
    (
        (
            "may mutate external systems",
            "may modify external systems",
            "may write to external systems",
            "may alter external systems",
            "may change external systems",
            "may contact or mutate external systems",
            "may call or mutate external systems",
        ),
        "contradictory external-system mutation permission is forbidden",
    ),
    (
        (
            "may contact external systems",
            "may call external systems",
            "may reach external systems",
            "may communicate with external systems",
            "may contact or call external systems",
        ),
        "contradictory external-system contact permission is forbidden",
    ),
)
READ_ONLY_CONTRADICTORY_PERMISSION_ANCHORS = (
    "may modify assigned files",
    "may edit assigned files",
    "may write assigned files",
    "may edit repository files",
    "may modify repository files",
    "may write repository files",
    "may edit source files",
    "may modify source files",
    "may write source files",
    "may edit files in the repository",
    "may modify files in the repository",
    "may write files in the repository",
)
READ_ONLY_CONTRADICTORY_SANDBOX_ANCHORS = (
    "this TOML declares OS-enforced read-only",
    "the TOML declares OS-enforced read-only",
    "this configuration declares OS-enforced read-only",
    "the configuration declares OS-enforced read-only",
    "this TOML makes the sandbox OS-enforced read-only",
    "this configuration makes the sandbox OS-enforced read-only",
    "this TOML guarantees OS-enforced read-only",
    "the TOML guarantees OS-enforced read-only",
    "this configuration guarantees OS-enforced read-only",
    "the configuration guarantees OS-enforced read-only",
    "this TOML claims OS-enforced read-only",
    "the TOML claims OS-enforced read-only",
    "this configuration claims OS-enforced read-only",
    "the configuration claims OS-enforced read-only",
    "this TOML asserts OS-enforced read-only",
    "this configuration asserts OS-enforced read-only",
)
WRITER_CONTRADICTORY_PERMISSION_ANCHORS = (
    "may edit unowned product implementation",
    "may modify unassigned product implementation",
    "may write unowned product code",
    "may edit unassigned product implementation",
    "may modify unowned product implementation",
    "may mutate unowned product implementation",
    "may mutate unassigned product implementation",
    "may edit product implementation outside the named paths",
    "may modify product implementation outside the named paths",
    "may mutate product implementation outside the named paths",
    "may edit product implementation outside named paths",
    "may modify product implementation outside named paths",
    "may mutate product implementation outside named paths",
    "may edit product code outside the named paths",
    "may modify product code outside the named paths",
    "may mutate product code outside the named paths",
    "may edit product code outside owned paths",
    "may edit product code outside the owned paths",
    "may modify product code outside owned paths",
    "may mutate product code outside owned paths",
    "may edit product implementation outside owned paths",
    "may edit product implementation outside the owned paths",
    "may modify product implementation outside owned paths",
    "may mutate product implementation outside owned paths",
    "may edit product code outside assigned paths",
    "may edit product code outside the assigned paths",
    "may modify product code outside assigned paths",
    "may mutate product code outside assigned paths",
    "may edit product implementation outside assigned paths",
    "may edit product implementation outside the assigned paths",
    "may modify product implementation outside assigned paths",
    "may mutate product implementation outside assigned paths",
    "may edit product code outside named paths",
    "may edit product implementation outside named paths",
)
RESEARCHER_CONTRADICTORY_FALLBACK_ANCHORS = (
    "content quality, task execution, or tool failure authorizes fallback",
    "content, task, or tool failure authorizes fallback",
    "content quality, task execution, or tool failure may authorize fallback",
    "content, task, or tool failure may authorize fallback",
    "content quality, task execution, or tool failure permits fallback",
    "content, task, or tool failure permits fallback",
    "content quality, task execution, or tool failure authorizes route switching",
    "content, task, or tool failure authorizes route switching",
    "failure authorizes route switching",
    "failure may authorize route switching",
    "failure permits route switching",
)
RESEARCHER_CONTRADICTORY_FURTHER_FALLBACK_ANCHORS = (
    "authorizes further fallback",
    "may authorize further fallback",
    "may authorize a further fallback",
    "permits another fallback",
    "allows another fallback",
)

# These are configured requests from the accepted bundle, not a universal model
# catalog and not evidence that a host can provide or effectively used the route.
EXPECTED_AGENT_PINS = {
    "architect": ("gpt-5.6-sol", "high", "read-only"),
    "code_mapper": ("gpt-5.6-terra", "medium", "read-only"),
    "docs_researcher_luna": ("gpt-5.6-luna", "max", "read-only"),
    "docs_researcher_terra": ("gpt-5.6-terra", "high", "read-only"),
    "gpu_reviewer": ("gpt-5.6-sol", "xhigh", "read-only"),
    "implementer": ("gpt-5.6-terra", "high", "workspace-write"),
    "numerics_reviewer": ("gpt-5.6-sol", "xhigh", "read-only"),
    "parallelism_reviewer": ("gpt-5.6-sol", "xhigh", "read-only"),
    "performance_profiler": ("gpt-5.6-terra", "high", "workspace-write"),
    "reviewer": ("gpt-5.6-sol", "high", "read-only"),
    "security_reviewer": ("gpt-5.6-sol", "max", "read-only"),
    "test_validator": ("gpt-5.6-sol", "high", "read-only"),
    "tester": ("gpt-5.6-terra", "medium", "workspace-write"),
}

# The registry deliberately names small source anchors and schema fields. It does
# not attempt to decide whether arbitrary prose is semantically equivalent.
ROLE_CONTRACT_ANCHORS = {
    "architect": {
        "evidence": (
            "exact repository paths, symbols, interface signatures, callers, relevant tests",
        ),
        "stop": (
            "missing evidence or ambiguity could change a public API, security boundary, compatibility promise, migration cost, or ownership assignment",
        ),
        "schema_fields": (
            "ROLE",
            "SUCCESS",
            "SCOPE",
            "INTERFACES",
            "COMPATIBILITY",
            "ALTERNATIVES",
            "MIGRATION_ORDER",
            "VALIDATION_PLAN",
            "RISKS",
            "EVIDENCE",
            "OPEN_QUESTIONS",
            "SANDBOX",
        ),
    },
    "code_mapper": {
        "evidence": (
            "exact file paths, symbols, definitions, references, tests or fixtures",
        ),
        "stop": (
            "requested call path cannot be established from repository evidence",
        ),
        "schema_fields": (
            "ROLE",
            "SCOPE",
            "ENTRY_POINTS",
            "FILES",
            "SYMBOLS",
            "CALL_FLOW",
            "DATA_FLOW",
            "TESTS",
            "RISKS",
            "CONFIDENCE",
            "UNKNOWN_OR_STOP",
            "EVIDENCE",
            "SANDBOX",
        ),
        "exact_schema_lines": (
            "CONFIDENCE: High, medium, or low per material path, with basis.",
        ),
    },
    "docs_researcher_luna": {
        "evidence": (
            "exact official URLs or repository paths, document sections, version identifiers, publication/update dates",
        ),
        "stop": ("the requested native route is unobservable",),
        "schema_fields": (
            "ROLE",
            "QUESTION",
            "CLAIMS",
            "SOURCES",
            "VERSION_DATE",
            "REQUESTED_ROUTE",
            "OBSERVED_ROUTE",
            "CONTRADICTIONS",
            "UNKNOWNS",
            "IMPLICATION",
            "EVIDENCE",
            "REPORT_SCOPE",
            "STATUS_FAILURE_MATRIX",
            "STATUS",
            "FAILURE_CLASS",
            "ROUTE_AUTHORITY",
            "SANDBOX",
        ),
        "exact_schema_lines": _researcher_exact_schema_lines(
            "Luna/Max",
            "STOP_FAILED + NATIVE_ROUTING_FAILURE: valid for an observed child handoff. For Luna, only the parent state machine may use the parent-owned evidence/classification to promote the overall chain to FALLBACK_PENDING; this child never spawns or authorizes Terra, fallback, or route switching.",
            "Evidence and classification only; this role does not spawn or authorize Terra, fallback, or route switching.",
        ),
    },
    "docs_researcher_terra": {
        "evidence": (
            "exact official URLs or repository paths, document sections, version identifiers, publication/update dates",
        ),
        "stop": ("the requested native route is unobservable",),
        "schema_fields": (
            "ROLE",
            "QUESTION",
            "CLAIMS",
            "SOURCES",
            "VERSION_DATE",
            "REQUESTED_ROUTE",
            "OBSERVED_ROUTE",
            "CONTRADICTIONS",
            "UNKNOWNS",
            "IMPLICATION",
            "EVIDENCE",
            "REPORT_SCOPE",
            "STATUS_FAILURE_MATRIX",
            "STATUS",
            "FAILURE_CLASS",
            "ROUTE_AUTHORITY",
            "SANDBOX",
        ),
        "exact_schema_lines": _researcher_exact_schema_lines(
            "Terra/high",
            "STOP_FAILED + NATIVE_ROUTING_FAILURE: valid for an observed child handoff. For Terra, this is terminal STOP_FAILED and never promotes or authorizes fallback or a route switch.",
            "Evidence and classification only; this role does not spawn or authorize any further fallback or route switch.",
        ),
    },
    "gpu_reviewer": {
        "evidence": ("correctness evidence separately from performance evidence",),
        "stop": ("representative hardware context or profiler/benchmark evidence is missing or nonrepresentative",),
        "schema_fields": (
            "ROLE",
            "SCOPE",
            "CORRECTNESS_FINDINGS",
            "PERFORMANCE_FINDINGS",
            "SCALABILITY",
            "HARDWARE_EVIDENCE",
            "PROFILER_EVIDENCE",
            "MEASUREMENT_GAPS",
            "VERDICT",
            "EVIDENCE",
            "SANDBOX",
        ),
        "exact_schema_lines": (
            "VERDICT: SHIP, FIX_FIRST, or RETHINK with basis.",
        ),
    },
    "implementer": {
        "evidence": (
            "exact changed paths, symbols or sections, before/after behavior, commands and exit statuses",
        ),
        "stop": ("missing ownership",),
        "schema_fields": (
            "ROLE",
            "OBJECTIVE",
            "OWNED_PATHS",
            "CHANGES",
            "VERIFICATION",
            "CONCURRENT_EDIT_HANDLING",
            "ASSUMPTIONS",
            "RISKS",
            "OUT_OF_SCOPE",
            "STATUS",
        ),
        "exact_schema_lines": (
            "STATUS: READY_FOR_PARENT_REVIEW or STOP_ESCALATE.",
        ),
    },
    "numerics_reviewer": {
        "evidence": ("convergence tables, conservation residuals, and repeated-run results",),
        "stop": ("initial/boundary conditions or the baseline are absent",),
        "schema_fields": (
            "ROLE",
            "SCOPE",
            "CONVERGENCE",
            "CONSERVATION",
            "STABILITY",
            "TOLERANCE_PRECISION",
            "REPRODUCIBILITY",
            "FINDINGS",
            "MEASUREMENT_GAPS",
            "VERDICT",
            "EVIDENCE",
            "SANDBOX",
        ),
        "exact_schema_lines": (
            "VERDICT: SHIP, FIX_FIRST, or RETHINK with basis.",
        ),
    },
    "parallelism_reviewer": {
        "evidence": (
            "ownership variables, synchronization primitives, collective sites, teardown edges, stress commands, iteration counts",
        ),
        "stop": ("static inspection cannot establish safety",),
        "schema_fields": (
            "ROLE",
            "SCOPE",
            "OWNERSHIP_MODEL",
            "HAPPENS_BEFORE",
            "COLLECTIVES",
            "TEARDOWN",
            "STRESS_EVIDENCE",
            "FINDINGS",
            "MEASUREMENT_GAPS",
            "VERDICT",
            "EVIDENCE",
            "SANDBOX",
        ),
        "exact_schema_lines": (
            "VERDICT: SHIP, FIX_FIRST, or RETHINK with basis.",
        ),
    },
    "performance_profiler": {
        "evidence": (
            "sample count, individual or aggregate timings, variance, profiler metrics, end-to-end measurements",
        ),
        "stop": ("baseline or build mode differs",),
        "schema_fields": (
            "ROLE",
            "QUESTION",
            "BASELINE",
            "CANDIDATE",
            "METRICS",
            "VARIANCE",
            "PROFILER_EVIDENCE",
            "BOTTLENECK",
            "IMPACT",
            "GAPS",
            "STATUS",
            "EVIDENCE",
        ),
        "exact_schema_lines": (
            "STATUS: READY_FOR_PARENT_REVIEW or STOP_ESCALATE.",
        ),
    },
    "reviewer": {
        "evidence": (
            "relevant tests, commands, exit statuses, decisive output, failure reproduction or proof rationale",
        ),
        "stop": ("diff, changed-path ownership, or decisive verification evidence is missing",),
        "schema_fields": (
            "ROLE",
            "SCOPE",
            "FINDINGS",
            "INVALID_OR_OUT_OF_SCOPE",
            "VERIFICATION",
            "MISSING_EVIDENCE",
            "VERDICT",
            "VERDICT_BASIS",
            "EVIDENCE",
            "SANDBOX",
        ),
        "exact_schema_lines": ("VERDICT: SHIP | FIX_FIRST | RETHINK",),
    },
    "security_reviewer": {
        "evidence": ("validation sites, authorization checks, sensitive sinks, attacker prerequisites",),
        "stop": ("Stop before destructive or harmful external exploitation",),
        "schema_fields": (
            "ROLE",
            "SCOPE",
            "SOURCE_TO_SINK",
            "ATTACKER_PREREQUISITES",
            "AUTHORIZATION_BOUNDARY",
            "FINDINGS",
            "SAFE_VERIFICATION",
            "MISSING_EVIDENCE",
            "VERDICT",
            "EVIDENCE",
            "SANDBOX",
        ),
        "exact_schema_lines": (
            "VERDICT: SHIP | FIX_FIRST | RETHINK",
        ),
    },
    "test_validator": {
        "evidence": ("mapped path and false-positive analysis for every material requirement",),
        "stop": ("requirements, actual test code, decisive results, or baseline behavior are unavailable",),
        "schema_fields": (
            "ROLE",
            "REQUIREMENT_TO_TEST",
            "FALSE_POSITIVES",
            "UNCOVERED_PATHS",
            "RESULTS",
            "BLOCKING_GAPS",
            "OPTIONAL_IMPROVEMENTS",
            "VERDICT",
            "EVIDENCE",
            "SANDBOX",
        ),
        "exact_schema_lines": (
            "VERDICT: SUPPORTED, GAPS, or STOP_UNVERIFIED with basis.",
        ),
    },
    "tester": {
        "evidence": (
            "exact test/build commands, exit statuses, decisive output, revision, environment metadata, artifact paths, failure classification",
        ),
        "stop": ("a command would mutate unowned paths",),
        "schema_fields": (
            "ROLE",
            "SCOPE",
            "COMMANDS",
            "RESULTS",
            "ARTIFACTS",
            "FAILURE_CLASSIFICATION",
            "REPRODUCTION",
            "REGRESSION_RISK",
            "NEXT_ACTION",
            "STATUS",
            "EVIDENCE",
        ),
        "exact_schema_lines": (
            "FAILURE_CLASSIFICATION: Implementation, environment, flaky, pre-existing, or inconclusive.",
            "STATUS: READY_FOR_PARENT_REVIEW or STOP_ESCALATE.",
        ),
    },
}

RESEARCH_STATUS_FAILURE_ANCHORS = (
    *RESEARCH_STATUS_FAILURE_MATRIX_LINES,
    RESEARCH_STATUS_FAILURE_SCHEMA_LINES[-2],
    RESEARCH_STATUS_FAILURE_SCHEMA_LINES[-1],
    RESEARCH_REPORT_SCOPE_LINE,
)
RUNTIME_RECORD_FIXTURES = {
    "app-task.json",
    "cli-and-app-records.json",
    "app-task-provenance-on-native.json",
    "native-route-mismatch.json",
    "native-provenance-on-app-task.json",
    "disguised-composite.json",
    "duplicate-runtime-id.json",
    "document-schema-bool.json",
    "generation-list.json",
    "mismatched-provenance.json",
    "missing-field.json",
    "mixed-evidence.json",
    "native-effective-unknown.json",
    "native-effective-support-conflict.json",
    "native-partial-effective-mismatch.json",
    "native-observed-null.json",
    "native-padded-effective.json",
    "native-request-only.json",
    "native-spawn.json",
    "native-whitespace-effective.json",
    "native-assertion-list.json",
    "native-assertion-primitive.json",
    "record-schema-float.json",
    "unknown-fact.json",
    "unknown-model-known-effort.json",
    "app-luna-only.sh",
    "app-v1-luna.sh",
    "cli-v1-luna.sh",
    "cli-v2-luna.sh",
    "cli-v2-no-luna.sh",
}
ROUTING_FIXTURES = {
    "luna-routing-rejection.json",
    "luna-mismatch.json",
    "luna-success.json",
    "terra-success.json",
}
SKILL_REFERENCE_FILES = {
    "workflow.md",
    "task-contract.md",
    "review-policy.md",
    "cuda-cae-review-policy.md",
    "model-routing.md",
}
EXPECTED_DESCRIPTION = (
    "Use for non-trivial repository engineering needing mapping, planning, implementation, "
    "tests, independent review, acceptance, or targeted CUDA/HPC/numerical/security specialists. "
    "Do not use for simple Q&A or status-only work. Probes and App tasks are not native effective "
    "evidence; this Skill does not change the parent model or permissions, guarantee model "
    "availability, or perform automatic CLI model switching or fallback."
)
EXPECTED_UI = {
    "display_name": "Versatile Development",
    "short_description": "Classify, route, verify, and review engineering work",
    "default_prompt": "Use $versatile-dev for non-trivial repository engineering: classify the task, plan, implement, verify, independently review, and accept the change.",
}
DIRECT_LINK_LINES = {
    "references/model-routing.md": "[model routing](references/model-routing.md)",
    "references/task-contract.md": "[task contract](references/task-contract.md)",
    "references/cuda-cae-review-policy.md": "[CUDA and CAE review](references/cuda-cae-review-policy.md)",
    "references/workflow.md": "[workflow](references/workflow.md)",
    "references/review-policy.md": "[review policy](references/review-policy.md)",
}
CANONICAL_BLOCKS = {
    "SKILL.md": (
        "<!-- BEGIN versatile-dev canonical contract -->",
        "<!-- END versatile-dev canonical contract -->",
        (
            "Lead owns user intent, architecture, task state, diff, tests, review triage, and acceptance.",
            "Classify work as Simple (isolated and obvious), Moderate (multi-file, non-obvious, or test-bearing), or Complex (architecture, concurrency, CUDA, numerical, security, interface, or performance-sensitive); reclassify when evidence changes.",
            "Simple obvious changes use direct work; delegate only when delegation is material to correctness, coverage, or throughput.",
            "Native documentation research uses the same-interface PRECHECK; missing, conflicting, or unobservable metadata fails closed, with routing details in the model-routing reference.",
            "Luna is first; only a classified native routing rejection or complete same-attempt native mismatch permits at most one Terra; all other outcomes fail closed.",
            "The App user-visible task lane is separate and requires explicit authorization in the current user request; it never supplies native effective evidence or authorizes Terra fallback.",
            "The task packet has exactly five parts: Objective, Ownership, Inputs/evidence, Constraints/requirements, Verification/handoff.",
            "A dynamic packet names actual files, interfaces, commands, evidence, constraints, and verification.",
            "One writer owns overlapping files; parallel work is limited to disjoint files.",
            "A fresh independent reviewer reviews the completed diff; any correction invalidates the verdict and requires fresh review.",
            "The lead reruns verification and alone accepts completion.",
            "Route gpu_reviewer, numerics_reviewer, parallelism_reviewer, performance_profiler, and security_reviewer only when their boundary is touched; never spawn all specialists by default.",
        ),
    ),
    "model-routing.md": (
        "<!-- BEGIN versatile-dev canonical routing contract -->",
        "<!-- END versatile-dev canonical routing contract -->",
        (
            "Both docs_researcher_luna and docs_researcher_terra are installed and pinned to gpt-5.6-luna/max and gpt-5.6-terra/high.",
            "Both researchers use the same-interface PRECHECK.",
            "route_research.py provides deterministic replay and decision semantics.",
            "Luna is first; only a classified native routing rejection or complete same-attempt native mismatch permits at most one Terra attempt.",
            "A permitted Terra transition is FALLBACK_PENDING and is limited to one Terra attempt.",
            "Content, tool, task, timeout, and unknown failures do not authorize Terra fallback.",
            "Missing, conflicting, or unobservable effective evidence is STOP_UNVERIFIED.",
            "Every attempt carries the same canonical task_packet_hash.",
            "runtime_audit.py is separate from the installation manifest.",
            "Installed, configured, capability, requested, observed, and effective are separate fact layers.",
            "The installation manifest, probe, and App task cannot fill native effective facts.",
            "The App user-visible task lane requires explicit authorization in the current user request and cannot authorize native Terra fallback.",
            "This Skill cannot change the parent model, bypass permissions, guarantee model availability, or perform automatic CLI model switching or fallback.",
            "Offline validation does not prove live runtime conformance.",
        ),
    ),
}
CANONICAL_SECTIONS = {
    "SKILL.md": "## Contract",
    "model-routing.md": "## Canonical routing contract",
}
STALE_LITERALS = (
    "current implementation boundary",
    "installed bundle provides exactly one legacy docs_researcher",
    "dual-agent installer is future work",
    "dual researchers are future work",
    "route helper is future work",
    "automatic cli fallback",
    "probe proves effective route",
    "probe confirms effective native route",
)

class Validation:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self.errors.append(message)

def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _require_anchor(
    errors: list[str],
    label: str,
    section_name: str,
    section_text: str,
    anchors: tuple[str, ...],
    diagnostic: str,
) -> None:
    compact = _compact(section_text)
    if not any(anchor in compact for anchor in anchors):
        expected = " OR ".join(repr(anchor) for anchor in anchors)
        errors.append(f"{label}: {diagnostic} in {section_name}: expected {expected}")


def _require_exact_schema_line(
    errors: list[str],
    label: str,
    section_text: str,
    expected_line: str,
    diagnostic: str = "structured handoff schema line is not exact",
) -> None:
    count = sum(line.strip() == expected_line for line in section_text.splitlines())
    if count != 1:
        errors.append(f"{label}: {diagnostic}: {expected_line}")


def _operational_text(sections: Mapping[str, str]) -> str:
    # Include the structured handoff too: closed contradictory permissions must
    # not be hidden after an otherwise valid exact schema line.
    return "\n".join(
        sections.get(section_name, "") for section_name in AGENT_CONTRACT_HEADING_NAMES
    )


def _normalize_registered_text(text: str) -> str:
    """Normalize only case, punctuation, and whitespace for closed literals."""
    punctuation_normalized = re.sub(r"[^\w]+", " ", text.casefold(), flags=re.UNICODE)
    return _compact(punctuation_normalized)


REGISTERED_DIRECT_CLAUSE_PREFIXES = (
    (),
    ("this", "role"),
    ("the", "role"),
    ("this", "agent"),
    ("the", "agent"),
    ("this", "task"),
    ("the", "task"),
)
REGISTERED_NEUTRAL_LABEL_PREFIXES = (
    ("allowed",),
    ("allowed", "action"),
    ("allowed", "actions"),
    ("allowed", "actions", "and", "tools"),
    ("permission",),
    ("permissions",),
    ("operational", "rule"),
    ("rule",),
    ("policy",),
    ("contract",),
)
# A cross-line non-direct context is registered only for an exact introducer
# line ending in one of these delimiters.  A prefix match would let unrelated
# prose such as "Never state something unrelated" hide a later direct clause.
REGISTERED_NON_DIRECT_CONTEXT_INTRODUCERS = (
    (("never", "state"), (":", "：", ";")),
    (("do", "not", "say"), (":", "：", ";")),
    (("never", "authorize"), (":", "：", ";")),
    (("do", "not", "authorize"), (":", "：", ";")),
    (("never", "claim"), (":", "：", ";")),
    (("do", "not", "claim"), (":", "：", ";")),
    (("must", "not", "say"), (":", "：", ";")),
    (("must", "not", "authorize"), (":", "：", ";")),
    (("quoted",), (":", "：", ";")),
    (("quote",), (":", "：", ";")),
    (("example",), (":", "：", ";")),
)
REGISTERED_LIST_MARKER_RE = re.compile(
    r"^\s*(?:[-*+]|(?:\d+|[A-Za-z])[.)])(?:[ \t]+|$)"
    r"(?:\[[ xX]\](?:[ \t]+|$))?"
)
REGISTERED_SEPARATOR_RE = re.compile(r"[.!?;:：—–]")


def _strip_registered_list_marker(line: str) -> str:
    return REGISTERED_LIST_MARKER_RE.sub("", line, count=1)


def _registered_tokens(text: str) -> tuple[str, ...]:
    return tuple(_normalize_registered_text(_strip_registered_list_marker(text)).split())


def _registered_neutral_label_remainder(text: str) -> tuple[str, ...] | None:
    stripped = _strip_registered_list_marker(text)
    for match in re.finditer(r"[:：—–]", stripped):
        prefix = tuple(_normalize_registered_text(stripped[: match.start()]).split())
        if prefix not in REGISTERED_NEUTRAL_LABEL_PREFIXES:
            continue
        remainder = _registered_tokens(stripped[match.end() :])
        if remainder:
            return remainder
    return None


def _registered_separator_remainders(text: str) -> tuple[tuple[str, ...], ...]:
    """Return direct candidates after registered punctuation separators.

    This is a closed tokenizer rule: a suffix is considered independently so
    a completed, unrelated prefix cannot hide a registered direct clause. An
    exact negating/quoted introducer keeps its immediate suffix quoted instead.
    """
    stripped = _strip_registered_list_marker(text)
    remainders: list[tuple[str, ...]] = []
    for match in REGISTERED_SEPARATOR_RE.finditer(stripped):
        prefix = stripped[: match.start()].strip()
        delimiter = match.group(0)
        if any(
            delimiter in delimiters
            and _registered_tokens(prefix) == introducer
            for introducer, delimiters in REGISTERED_NON_DIRECT_CONTEXT_INTRODUCERS
        ):
            continue
        remainder = _registered_tokens(stripped[match.end() :])
        if remainder:
            remainders.append(remainder)
    return tuple(remainders)


def _registered_context_before_line(lines: list[str], line_index: int) -> bool:
    previous = line_index - 1
    if previous < 0 or not lines[previous].strip():
        return False
    previous_line = _strip_registered_list_marker(lines[previous]).strip()
    for prefix, delimiters in REGISTERED_NON_DIRECT_CONTEXT_INTRODUCERS:
        for delimiter in delimiters:
            if not previous_line.endswith(delimiter):
                continue
            introducer = previous_line[: -len(delimiter)].strip()
            if _registered_tokens(introducer) == prefix:
                return True
    return False


def _registered_clauses(text: str) -> tuple[tuple[str, ...], ...]:
    """Return bounded clauses while preserving physical and semantic context."""
    clauses: list[tuple[str, ...]] = []
    lines = text.splitlines()
    paragraphs: list[list[tuple[int, str]]] = []
    paragraph: list[tuple[int, str]] = []
    for line_index, line in enumerate(lines):
        if line.strip():
            paragraph.append((line_index, line))
        elif paragraph:
            paragraphs.append(paragraph)
            paragraph = []
    if paragraph:
        paragraphs.append(paragraph)

    for paragraph in paragraphs:
        blocks: list[list[tuple[int, str]]] = []
        block: list[tuple[int, str]] = []
        for line_index, line in paragraph:
            if REGISTERED_LIST_MARKER_RE.match(line):
                if block:
                    blocks.append(block)
                block = [(line_index, _strip_registered_list_marker(line))]
            else:
                block.append((line_index, line))
        if block:
            blocks.append(block)

        for block in blocks:
            if _registered_context_before_line(lines, block[0][0]):
                continue
            wrapped_text = " ".join(line.strip() for _, line in block)
            for raw_clause in re.split(r"[.!?]+", wrapped_text):
                normalized = _normalize_registered_text(raw_clause)
                if normalized:
                    clauses.append(tuple(normalized.split()))
                neutral_remainder = _registered_neutral_label_remainder(raw_clause)
                if neutral_remainder is not None:
                    clauses.append(neutral_remainder)

        for line_index, line in paragraph:
            if _registered_context_before_line(lines, line_index):
                # The introducer protects only the immediate clause.  Keep
                # scanning this physical line/list item after a registered
                # punctuation boundary for a later direct contradiction.
                clauses.extend(_registered_separator_remainders(line))
                continue
            neutral_remainder = _registered_neutral_label_remainder(line)
            clauses.append(neutral_remainder if neutral_remainder is not None else _registered_tokens(line))
            clauses.extend(_registered_separator_remainders(line))
    return tuple(clauses)


def _registered_literal_matches(clause: tuple[str, ...], literal: tuple[str, ...]) -> bool:
    return any(
        clause[: len(prefix) + len(literal)] == prefix + literal
        for prefix in REGISTERED_DIRECT_CLAUSE_PREFIXES
    )


def _reject_registered_literals(
    errors: list[str],
    label: str,
    text: str,
    literals: tuple[str, ...],
    diagnostic: str,
) -> None:
    clauses = _registered_clauses(text)
    for literal in literals:
        normalized_literal = tuple(_normalize_registered_text(literal).split())
        if any(_registered_literal_matches(clause, normalized_literal) for clause in clauses):
            errors.append(f"{label}: {diagnostic}: {literal}")


def _parse_agent_sections(text: str, label: str) -> tuple[dict[str, str], list[str]]:
    """Parse the registered ten-heading source dialect without classifying prose."""
    errors: list[str] = []
    lines = text.splitlines()
    heading_re = re.compile(r"^(?P<marks>#{1,6})(?:[ \t]+(?P<title>.*?))?[ \t]*$")
    headings: list[tuple[str, int]] = []
    for index, line in enumerate(lines):
        candidate = line if line.startswith("#") else line.lstrip() if line.lstrip().startswith("#") else None
        if candidate is None:
            continue
        match = heading_re.fullmatch(line)
        if match is None:
            errors.append(f"{label}: malformed developer_instructions heading at line {index + 1}: {line!r}")
            continue
        headings.append((line, index))
        if line not in AGENT_CONTRACT_HEADINGS:
            errors.append(f"{label}: unexpected or malformed developer_instructions heading at line {index + 1}: {line!r}")

    exact_headings = [line for line, _ in headings if line in AGENT_CONTRACT_HEADINGS]
    for heading in AGENT_CONTRACT_HEADINGS:
        count = exact_headings.count(heading)
        if count == 0:
            errors.append(f"{label}: missing required contract heading: {heading}")
        elif count > 1:
            errors.append(f"{label}: duplicate required contract heading: {heading}")
    if exact_headings != list(AGENT_CONTRACT_HEADINGS):
        errors.append(
            f"{label}: required contract headings must appear exactly once in exact order; "
            f"observed {exact_headings!r}"
        )

    sections: dict[str, str] = {}
    for heading in AGENT_CONTRACT_HEADINGS:
        matching = [index for line, index in headings if line == heading]
        if len(matching) != 1:
            continue
        start = matching[0]
        end = next((index for _, index in headings if index > start), len(lines))
        body = "\n".join(lines[start + 1 : end])
        section_name = heading.removeprefix("# ")
        sections[section_name] = body
        if not _compact(body):
            errors.append(f'{label}: section "{section_name}" must have a nonempty body')
    return sections, errors


def _validate_common_agent_semantics(
    label: str, name: str, sections: Mapping[str, str], errors: list[str]
) -> None:
    ownership = sections.get("OWNERSHIP", "")
    forbidden = sections.get("FORBIDDEN ACTIONS", "")
    evidence = sections.get("EVIDENCE", "")
    stop = sections.get("STOP / ESCALATE", "")
    return_schema = sections.get("RETURN SCHEMA", "")
    operational_text = _operational_text(sections)

    for literals, diagnostic in GLOBAL_CONTRADICTORY_PERMISSION_RULES:
        _reject_registered_literals(errors, label, operational_text, literals, diagnostic)

    _require_anchor(
        errors,
        label,
        "OWNERSHIP",
        ownership,
        (
            "preserve unrelated and concurrent edits",
            "preserve unrelated or concurrent edits",
            "Preserve unrelated and concurrent edits",
        ),
        "registered ownership/concurrent-edit anchor missing",
    )
    _require_anchor(
        errors,
        label,
        "FORBIDDEN ACTIONS",
        forbidden,
        ("implicit commit, push, or PR",),
        "registered implicit commit/push/PR prohibition missing",
    )
    _require_anchor(
        errors,
        label,
        "FORBIDDEN ACTIONS",
        forbidden,
        ("parent task complete",),
        "registered whole-parent completion prohibition missing",
    )
    _require_anchor(
        errors,
        label,
        "FORBIDDEN ACTIONS",
        forbidden,
        ("effectiveness from TOML", "effectiveness from this TOML"),
        "registered configured-model/runtime-effectiveness disclaimer missing",
    )
    _require_anchor(
        errors,
        label,
        "STOP / ESCALATE",
        stop,
        ("Stop and escalate", "Stop before"),
        "registered stop/escalate handoff anchor missing",
    )
    _require_anchor(
        errors,
        label,
        "RETURN SCHEMA",
        return_schema,
        (f"ROLE: {name}",),
        f"structured handoff role field missing: ROLE: {name}",
    )
    schema_fields = re.findall(r"(?m)^[ \t]*([A-Z][A-Z0-9_]*)\s*:", return_schema)
    if len(schema_fields) < 3:
        errors.append(f"{label}: structured handoff schema must expose at least three named fields")


def _validate_read_only_agent_semantics(
    label: str, sections: Mapping[str, str], errors: list[str]
) -> None:
    ownership = sections.get("OWNERSHIP", "")
    evidence = sections.get("EVIDENCE", "")
    _reject_registered_literals(
        errors,
        label,
        _operational_text(sections),
        READ_ONLY_CONTRADICTORY_PERMISSION_ANCHORS,
        "contradictory read-only permission is forbidden",
    )
    _reject_registered_literals(
        errors,
        label,
        _operational_text(sections),
        READ_ONLY_CONTRADICTORY_SANDBOX_ANCHORS,
        "contradictory OS-enforced read-only sandbox claim is forbidden",
    )
    _require_anchor(
        errors,
        label,
        "OWNERSHIP",
        ownership,
        ("behaviorally read-only: do not mutate",),
        "read-only behavioral write prohibition missing",
    )
    _require_anchor(
        errors,
        label,
        "OWNERSHIP",
        ownership,
        ("Own only",),
        "read-only ownership boundary missing",
    )
    _require_anchor(
        errors,
        label,
        "EVIDENCE",
        evidence,
        ("requested sandbox policy separately from observed sandbox policy",),
        "requested-versus-observed sandbox distinction missing",
    )
    _require_anchor(
        errors,
        label,
        "EVIDENCE",
        evidence,
        ("permission profile",),
        "observed sandbox permission-profile field missing",
    )
    _require_anchor(
        errors,
        label,
        "EVIDENCE",
        evidence,
        ("unknown when unobserved", "unobserved values unknown", "observation is unavailable, say unknown"),
        "unknown-if-unobserved sandbox rule missing",
    )
    _require_anchor(
        errors,
        label,
        "EVIDENCE",
        evidence,
        ("OS-enforced read-only",),
        "TOML cannot claim OS-enforced read-only missing",
    )
    _require_anchor(
        errors,
        label,
        "EVIDENCE",
        evidence,
        ("TOML",),
        "read-only runtime/configuration disclaimer missing",
    )
    return_schema = sections.get("RETURN SCHEMA", "")
    for field in ("EVIDENCE", "SANDBOX"):
        _require_anchor(
            errors,
            label,
            "RETURN SCHEMA",
            return_schema,
            (f"{field}:",),
            f"read-only structured handoff field missing: {field}",
        )


def _validate_writer_agent_semantics(
    label: str, name: str, sections: Mapping[str, str], errors: list[str]
) -> None:
    ownership = sections.get("OWNERSHIP", "")
    evidence = sections.get("EVIDENCE", "")
    _reject_registered_literals(
        errors,
        label,
        _operational_text(sections),
        WRITER_CONTRADICTORY_PERMISSION_ANCHORS,
        "contradictory unowned-product write permission is forbidden",
    )
    writer_anchors = {
        "implementer": (
            ("Write only the explicitly assigned paths or artifacts", "writer ownership/artifact limit"),
            ("Do not change APIs, ABI, tests, tooling, manifests, or product code outside the named paths", "unowned product edit prohibition"),
            ("Report requested versus observed runtime routing or sandbox only when observable", "requested-versus-observed runtime distinction"),
        ),
        "performance_profiler": (
            ("Write only explicitly assigned benchmark, profiler, trace, log, or temporary measurement artifacts", "writer ownership/artifact limit"),
            ("Never mutate product implementation or unassigned tests/configuration", "unowned product edit prohibition"),
            ("Runtime model/effort and sandbox are requested configuration only unless observed independently", "requested-versus-observed runtime distinction"),
        ),
        "tester": (
            ("Write only explicitly assigned test, reproduction, log, or diagnostic artifacts", "writer ownership/artifact limit"),
            ("Never mutate product implementation or unassigned tests/configuration", "unowned product edit prohibition"),
            ("requested workspace-write mode is configuration only", "requested-versus-observed runtime distinction"),
        ),
    }
    ownership_anchor, ownership_diagnostic = writer_anchors[name][0]
    _require_anchor(errors, label, "OWNERSHIP", ownership, (ownership_anchor,), ownership_diagnostic)
    product_anchor, product_diagnostic = writer_anchors[name][1]
    product_section_name = "FORBIDDEN ACTIONS" if name == "implementer" else "OWNERSHIP"
    product_section = sections.get(product_section_name, "")
    _require_anchor(errors, label, product_section_name, product_section, (product_anchor,), product_diagnostic)
    route_anchor, route_diagnostic = writer_anchors[name][2]
    _require_anchor(errors, label, "EVIDENCE", evidence, (route_anchor,), route_diagnostic)


def _validate_role_specific_semantics(
    label: str, name: str, sections: Mapping[str, str], errors: list[str]
) -> None:
    registered = ROLE_CONTRACT_ANCHORS.get(name)
    if registered is None:
        return
    _require_anchor(
        errors,
        label,
        "EVIDENCE",
        sections.get("EVIDENCE", ""),
        registered["evidence"],
        "registered role-specific evidence anchor missing",
    )
    _require_anchor(
        errors,
        label,
        "STOP / ESCALATE",
        sections.get("STOP / ESCALATE", ""),
        registered["stop"],
        "registered role-specific stop anchor missing",
    )
    return_schema = sections.get("RETURN SCHEMA", "")
    schema_fields = tuple(re.findall(r"(?m)^[ \t]*([A-Z][A-Z0-9_]*)\s*:", return_schema))
    expected_schema_fields = tuple(registered["schema_fields"])
    if schema_fields != expected_schema_fields:
        errors.append(
            f"{label}: registered structured handoff schema fields must exactly match "
            f"the registered order: expected {expected_schema_fields!r}; observed {schema_fields!r}"
        )
    for field in expected_schema_fields:
        if field not in schema_fields:
            errors.append(f"{label}: registered structured handoff field missing: {field}")
    for exact_line in registered.get("exact_schema_lines", ()):
        _require_exact_schema_line(errors, label, return_schema, exact_line)


def _validate_researcher_semantics(
    label: str, name: str, sections: Mapping[str, str], errors: list[str]
) -> None:
    return_schema = sections.get("RETURN SCHEMA", "")
    stop = sections.get("STOP / ESCALATE", "")
    operational_text = _operational_text(sections)
    _reject_registered_literals(
        errors,
        label,
        operational_text,
        RESEARCHER_CONTRADICTORY_FALLBACK_ANCHORS,
        "contradictory failure-authorized fallback/route-switch permission is forbidden",
    )
    _reject_registered_literals(
        errors,
        label,
        operational_text,
        RESEARCHER_CONTRADICTORY_FURTHER_FALLBACK_ANCHORS,
        "contradictory further-fallback permission is forbidden",
    )
    for anchor in RESEARCH_STATUS_FAILURE_ANCHORS:
        _require_exact_schema_line(
            errors,
            label,
            return_schema,
            anchor,
            "researcher status/failure matrix anchor missing",
        )
    _require_anchor(
        errors,
        label,
        "RETURN SCHEMA",
        return_schema,
        ("ROUTE_AUTHORITY: Evidence and classification only; this role does not spawn or authorize",),
        "researcher route authority must remain evidence-only and non-authorizing",
    )
    _require_anchor(
        errors,
        label,
        "RETURN SCHEMA",
        return_schema,
        ("REPORT_SCOPE: Observed or returnable child report after a child attempt exists; a pre-spawn native rejection is parent-owned raw evidence and has no child handoff.",),
        "researcher raw pre-spawn rejection must remain parent-owned with no child handoff",
    )
    requested_route = "Luna/Max" if name.endswith("_luna") else "Terra/high"
    _require_anchor(
        errors,
        label,
        "RETURN SCHEMA",
        return_schema,
        (f"REQUESTED_ROUTE: {requested_route}",),
        "researcher requested route field is not exact",
    )
    _require_anchor(
        errors,
        label,
        "RETURN SCHEMA",
        return_schema,
        ("OBSERVED_ROUTE: Observed native route, or unknown when unobserved.",),
        "researcher requested-versus-observed route distinction missing",
    )
    if name.endswith("_luna"):
        _require_anchor(
            errors,
            label,
            "STOP / ESCALATE",
            stop,
            ("Content quality, task execution, or tool failure does not authorize fallback or route switching.",),
            "Luna content/task/tool failure must not authorize fallback",
        )
        _require_anchor(
            errors,
            label,
            "RETURN SCHEMA",
            return_schema,
            ("For Luna, only the parent state machine may use the parent-owned evidence/classification to promote the overall chain to FALLBACK_PENDING; this child never spawns or authorizes Terra, fallback, or route switching.",),
            "Luna route authority must remain parent-owned",
        )
    else:
        _require_anchor(
            errors,
            label,
            "STOP / ESCALATE",
            stop,
            ("content, task, or tool failure must be returned as a bounded stop",),
            "Terra content/task/tool failure must remain terminal",
        )
        _require_anchor(
            errors,
            label,
            "RETURN SCHEMA",
            return_schema,
            ("For Terra, this is terminal STOP_FAILED and never promotes or authorizes fallback or a route switch.",),
            "Terra route authority must remain terminal",
        )


def agent_contract_violations(data: object, filename: str) -> list[str]:
    """Return deterministic violations for one parsed agent contract."""
    label = str(filename)
    if not isinstance(data, Mapping):
        return [f"{label}: top-level TOML value must be a table"]
    errors: list[str] = []
    keys = set(data)
    for key in sorted(REQUIRED_AGENT_KEYS - keys):
        errors.append(f"{label}: missing top-level key: {key}")
    for key in sorted(keys - REQUIRED_AGENT_KEYS):
        errors.append(f"{label}: unexpected top-level key: {key}")
    for key in sorted(keys & REQUIRED_AGENT_KEYS):
        if type(data[key]) is not str:
            errors.append(f"{label}: top-level key {key} must be a string")
    if any(type(data.get(key)) is not str for key in REQUIRED_AGENT_KEYS):
        return errors

    name = data["name"]
    stem = Path(label).stem
    if stem != name:
        errors.append(f"{label}: filename stem {stem!r} must equal agent name {name!r}")
    if name not in EXPECTED_AGENT_PINS:
        errors.append(f"{label}: agent name {name!r} is not one of the 13 registered roles")
    else:
        expected_model, expected_effort, expected_sandbox = EXPECTED_AGENT_PINS[name]
        configured = (
            ("model", data["model"], expected_model, "configured model request"),
            ("model_reasoning_effort", data["model_reasoning_effort"], expected_effort, "configured reasoning-effort request"),
            ("sandbox_mode", data["sandbox_mode"], expected_sandbox, "configured sandbox request"),
        )
        for field, actual, expected, label_name in configured:
            if actual != expected:
                errors.append(
                    f"{label}: role {name} {label_name} must be {expected!r}; "
                    f"configured value is {actual!r}. This is capability-dependent configuration, "
                    "not runtime availability or effective-route evidence."
                )
    if not data["description"].strip():
        errors.append(f"{label}: role {name} has an empty description")
    instructions = data["developer_instructions"]
    if not instructions.strip():
        errors.append(f"{label}: role {name} has empty developer instructions")
        return errors
    sections, section_errors = _parse_agent_sections(instructions, label)
    errors.extend(section_errors)
    if set(sections) != set(AGENT_CONTRACT_HEADING_NAMES):
        return errors

    _validate_common_agent_semantics(label, name, sections, errors)
    if name in READ_ONLY_AGENTS:
        _validate_read_only_agent_semantics(label, sections, errors)
    if name in WRITER_AGENTS:
        _validate_writer_agent_semantics(label, name, sections, errors)
    _validate_role_specific_semantics(label, name, sections, errors)
    if name in {"docs_researcher_luna", "docs_researcher_terra"}:
        _validate_researcher_semantics(label, name, sections, errors)
    return errors


def agent_file_violations(path: Path) -> list[str]:
    """Read and validate one concrete TOML, preserving path-specific diagnostics."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        return [f"invalid agent TOML {path}: {exc}"]
    return agent_contract_violations(data, str(path))


def agent_directory_violations(common_dir: Path) -> list[str]:
    """Validate the fixed 13-agent directory; suitable for focused offline tests."""
    if not common_dir.is_dir():
        return [f"missing common agent directory: {common_dir}"]
    paths = sorted(common_dir.glob("*.toml"))
    errors: list[str] = []
    if len(paths) != 13:
        errors.append(f"common agent set must contain exactly 13 concrete TOMLs, found {len(paths)}")
    actual_files = {path.name for path in paths}
    for filename in sorted(EXPECTED_COMMON_FILES - actual_files):
        errors.append(f"missing registered agent file: {common_dir / filename}")
    for filename in sorted(actual_files - EXPECTED_COMMON_FILES):
        errors.append(f"unexpected agent file: {common_dir / filename}")
    parsed_names: dict[str, list[Path]] = {}
    for path in paths:
        if not path.is_file() or path.is_symlink():
            errors.append(f"agent path is not a concrete regular TOML file: {path}")
            continue
        errors.extend(agent_file_violations(path))
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            continue
        name = data.get("name") if isinstance(data, Mapping) else None
        if isinstance(name, str):
            parsed_names.setdefault(name, []).append(path)
    for name, name_paths in sorted(parsed_names.items()):
        if len(name_paths) > 1:
            errors.append(
                f"duplicate configured agent name {name!r}: {', '.join(str(path) for path in name_paths)}"
            )
    names = set(parsed_names)
    for name in sorted(EXPECTED_COMMON - names):
        errors.append(f"missing registered agent name: {name}")
    for name in sorted(names - EXPECTED_COMMON):
        errors.append(f"unexpected configured agent name: {name}")
    return errors

def _frontmatter(text: str) -> tuple[str | None, list[str]]:
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    if match is None:
        return None, ["SKILL.md must begin with YAML frontmatter"]
    block = match.group(1)
    expected = f"name: versatile-dev\ndescription: {EXPECTED_DESCRIPTION}"
    if block != expected:
        return block, ["SKILL.md frontmatter must be the exact two-line trigger contract"]
    return block, []

_UNSUPPORTED_SOURCE_SEPARATORS = (
    ("\r", "CR"),
    ("\v", "VT"),
    ("\f", "FF"),
    ("\x85", "NEL"),
    ("\u2028", "line separator"),
    ("\u2029", "paragraph separator"),
)

def _source_lines(text: str) -> list[str]:
    lines = text.split("\n")
    if lines and lines[-1] == "": lines.pop()
    return lines

def _source_separator_violations(filename: str, text: str) -> list[str]:
    errors: list[str] = []
    for number, line in enumerate(_source_lines(text), 1):
        for separator, name in _UNSUPPORTED_SOURCE_SEPARATORS:
            if separator in line:
                errors.append(f"{filename}:{number} contains unsupported {name} line separator")
    return errors

def _read_controlled_source(path: Path, check: Validation) -> str:
    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        message = f"{path}: invalid UTF-8 controlled source"
    except OSError as exc:
        message = f"{path}: unable to read controlled source ({type(exc).__name__})"
    check.errors.append(message)
    return ""

def _fence_start(line: str) -> tuple[str, int] | None:
    backtick = re.fullmatch(r"[ ]{0,3}(`{3,})([^`]*)", line)
    if backtick is not None:
        return "`", len(backtick.group(1))
    tilde = re.fullmatch(r"[ ]{0,3}(~{3,})(.*)", line)
    if tilde is not None:
        return "~", len(tilde.group(1))
    return None

def _fence_close(line: str, fence: tuple[str, int]) -> bool:
    marker, length = fence
    return re.fullmatch(rf"[ ]{{0,3}}{re.escape(marker)}{{{length},}}[ \t]*", line) is not None

def _source_flags(
    text: str,
    marker_lines: set[str] | None = None,
    *,
    mask_inline_code: bool = True,
) -> list[bool]:
    """Mark only unindented, unquoted, unmasked source lines as active."""
    marker_lines = marker_lines or set()
    flags: list[bool] = []
    fence: tuple[str, int] | None = None
    comment = False
    for line in _source_lines(text):
        active = fence is None and not comment
        if fence is not None:
            flags.append(False)
            if _fence_close(line, fence):
                fence = None
            continue
        if line in marker_lines:
            flags.append(active)
            continue
        start = _fence_start(line)
        if start is not None:
            flags.append(False)
            fence = start
            continue
        if "<!--" in line:
            flags.append(False)
            if "-->" not in line[line.index("<!--") + 4 :]:
                comment = True
            continue
        if comment:
            flags.append(False)
            if "-->" in line:
                comment = False
            continue
        container = bool(re.match(r"^(?:[ \t]+|>\s*|(?:[-+*]|\d+\.)\s+)", line))
        inline_code = mask_inline_code and any(
            char == "`"
            and (len(line[:index]) - len(line[:index].rstrip("\\"))) % 2 == 0
            for index, char in enumerate(line)
        )
        flags.append(active and not container and not inline_code)
    return flags

def _source_dialect_violations(filename: str, text: str) -> list[str]:
    """Reject unsupported angle/HTML source; only registered marker lines are allowed."""
    registered = CANONICAL_BLOCKS.get(filename)
    marker_lines = set(registered[:2]) if registered is not None else set()
    errors = _source_separator_violations(filename, text)
    lines = _source_lines(text)
    for number, line in enumerate(lines, 1):
        if line in marker_lines:
            continue
        if "<" in line or "-->" in line:
            errors.append(f"{filename}:{number} contains unsupported angle or HTML source syntax")
    fence: tuple[str, int] | None = None
    for number, line in enumerate(lines, 1):
        if fence is not None:
            if _fence_close(line, fence):
                fence = None
            elif re.fullmatch(rf"[ ]{{0,3}}{re.escape(fence[0])}{{{fence[1]},}}.*", line):
                errors.append(f"{filename}:{number} contains an invalid fenced close suffix")
        else:
            fence = _fence_start(line)
    if fence is not None:
        errors.append(f"{filename} contains an unclosed fenced source block")
    return errors

def canonical_block_violations(filename: str, text: str) -> list[str]:
    registered = CANONICAL_BLOCKS.get(filename)
    if registered is None:
        return []
    begin, end, expected = registered
    lines = _source_lines(text)
    marker_lines = {begin, end}
    flags = _source_flags(text, marker_lines)
    begin_indexes = [i for i, line in enumerate(lines) if line == begin]
    end_indexes = [i for i, line in enumerate(lines) if line == end]
    errors: list[str] = []
    if len(begin_indexes) != 1 or len(end_indexes) != 1:
        return [f"{filename} canonical block markers must occur exactly once"]
    begin_index, end_index = begin_indexes[0], end_indexes[0]
    if begin_index >= end_index or not flags[begin_index] or not flags[end_index]:
        return [f"{filename} canonical block markers must be unindented and unmasked"]
    section = CANONICAL_SECTIONS[filename]
    all_section_indexes = [i for i, line in enumerate(lines) if line == section]
    active_section_indexes = [i for i in all_section_indexes if flags[i]]
    if len(all_section_indexes) != 1 or len(active_section_indexes) != 1:
        return [f"{filename} canonical block requires exactly one active, unmasked {section} section"]
    section_index = active_section_indexes[0]
    if section_index >= begin_index:
        return [f"{filename} canonical block section must precede its begin marker"]
    if begin_index != section_index + 2 or lines[section_index + 1] != "":
        return [f"{filename} canonical block must follow its section after exactly one blank line"]
    peer_flags = _source_flags(text, marker_lines, mask_inline_code=False)
    peer_headings = [
        i
        for i, line in enumerate(lines)
        if peer_flags[i] and re.fullmatch(r"#{1,2}(?:$|[ \t]+.*)", line)
    ]
    next_peer = next((i for i in peer_headings if i > section_index), None)
    if next_peer is not None and end_index >= next_peer:
        return [f"{filename} canonical block must end before the next active H1/H2 section"]
    actual = tuple(lines[begin_index + 1 : end_index])
    if actual != expected:
        errors.append(f"{filename} canonical block contents drifted")
    for line in expected:
        if lines.count(line) != 1:
            errors.append(f"{filename} canonical clause must occur exactly once: {line}")
    return errors

def openai_yaml_violations(text: str) -> list[str]:
    """Parse the deliberately closed interface schema, not general YAML."""
    lines = _source_lines(text)
    if lines == [""]:
        lines = []
    errors: list[str] = []
    if len(lines) != 4 or lines[0] != "interface:":
        return ["agents/openai.yaml must use the exact four-line interface schema"]
    values: dict[str, str] = {}
    expected_order = ("display_name", "short_description", "default_prompt")
    for line, expected_key in zip(lines[1:], expected_order):
        match = re.fullmatch(r'  ([a-z_]+): ("(?:\\.|[^"\\])*")', line)
        if match is None or match.group(1) != expected_key:
            errors.append(f"agents/openai.yaml has non-canonical interface line: {line!r}")
            continue
        try:
            value = json.loads(match.group(2))
        except json.JSONDecodeError:
            errors.append(f"agents/openai.yaml has malformed JSON string: {line!r}")
            continue
        if not isinstance(value, str):
            errors.append(f"agents/openai.yaml values must be strings: {line!r}")
            continue
        values[expected_key] = value
    if set(values) != set(expected_order):
        errors.append("agents/openai.yaml interface keys must be exactly display_name, short_description, default_prompt")
    for key, expected in EXPECTED_UI.items():
        if values.get(key) != expected:
            errors.append(f"agents/openai.yaml {key} drifted from its canonical value")
    return errors

def _inline_tokens(line: str) -> list[tuple[int, int, str, str]]:
    tokens: list[tuple[int, int, str, str]] = []
    for match in re.finditer(r"(?<!\\)(!?)(\[[^\]\n]*\])\(([^)\n]*)\)", line):
        tokens.append((match.start(), match.end(), match.group(1), match.group(3).strip()))
    return tokens

def _external_or_fragment(target: str) -> bool:
    target = target.strip().strip("<>")
    return target.startswith("#") or bool(re.match(r"(?i)^(?:https?://|mailto:)", target))

def _has_link_syntax_without_token(line: str) -> bool:
    return any(marker in line for marker in ("](", "][", "]:"))

def _reference_file_link_violations(filename: str, text: str) -> list[str]:
    errors: list[str] = []
    for number, line in enumerate(_source_lines(text), 1):
        for _, _, _, target in _inline_tokens(line):
            if not _external_or_fragment(target):
                errors.append(f"{filename}:{number} contains a cross-file Markdown link")
        if _has_link_syntax_without_token(line) and not _inline_tokens(line):
            errors.append(f"{filename}:{number} contains unsupported link syntax")
        definition = re.match(r"^\s*\[[^\]\n]+\]:\s*(\S+)", line)
        if definition is not None and not _external_or_fragment(definition.group(1)):
            errors.append(f"{filename}:{number} contains a cross-file reference definition")
        for html in re.finditer(
            r"<a\b[^>]*\bhref\s*=\s*(?:([\"'])(.*?)\1|([^\s>]+))",
            line,
            re.IGNORECASE,
        ):
            target = html.group(2) if html.group(1) else html.group(3)
            if target is not None and not _external_or_fragment(target):
                errors.append(f"{filename}:{number} contains a cross-file HTML link")
        if re.search(r"<a\b", line, re.IGNORECASE) and "href" not in line.casefold():
            errors.append(f"{filename}:{number} contains unsupported HTML anchor syntax")
    return errors

def reference_topology_violations(skill_text: str, reference_map: dict[str, str], skill_path: Path | None = None) -> list[str]:
    errors: list[str] = []
    errors.extend(_source_dialect_violations("SKILL.md", skill_text))
    errors.extend(canonical_block_violations("SKILL.md", skill_text))
    if set(reference_map) != SKILL_REFERENCE_FILES:
        errors.append(f"skill references must be exactly {sorted(SKILL_REFERENCE_FILES)}: {sorted(reference_map)}")

    active = _source_flags(skill_text)
    skill_lines = _source_lines(skill_text)
    expected_counts = {target: 0 for target in DIRECT_LINK_LINES}
    for index, line in enumerate(skill_lines):
        exact_target = next((target for target, source in DIRECT_LINK_LINES.items() if line == source), None)
        if exact_target is not None and index < len(active) and active[index]:
            expected_counts[exact_target] += 1
        tokens = _inline_tokens(line)
        if tokens:
            if not (len(tokens) == 1 and exact_target is not None and active[index]):
                errors.append(f"SKILL.md:{index + 1} contains an unsupported non-canonical link")
        elif _has_link_syntax_without_token(line):
            errors.append(f"SKILL.md:{index + 1} contains malformed or multiline link syntax")
        if re.match(r"^\s*\[[^\]\n]+\]:", line) or re.search(r"<a\b|\bhref\s*=", line, re.IGNORECASE):
            errors.append(f"SKILL.md:{index + 1} contains a reference definition or HTML anchor")
        if "references/" in line and line not in DIRECT_LINK_LINES.values():
            errors.append(f"SKILL.md:{index + 1} contains an unsupported reference path")
        if ".md" in line and line not in DIRECT_LINK_LINES.values():
            errors.append(f"SKILL.md:{index + 1} contains an unsupported Markdown path")
    for target, count in expected_counts.items():
        if count != 1:
            errors.append(f"SKILL.md must contain exactly one active direct link to {target}; found {count}")

    for filename, text in reference_map.items():
        errors.extend(_source_dialect_violations(filename, text))
        errors.extend(_reference_file_link_violations(filename, text))
    if "model-routing.md" in reference_map:
        errors.extend(canonical_block_violations("model-routing.md", reference_map["model-routing.md"]))
    return errors


def _task_heading(line: str) -> tuple[int, str] | None:
    match = re.fullmatch(r"(#{1,6}) (.+)", line)
    if match is None:
        return None
    return len(match.group(1)), match.group(2)


_ATX_SOURCE_RE = re.compile(
    r"^(?P<prefix>[ \t]*(?:(?:>[ \t]*)|(?:(?:[-+*]|\d{1,9}[.)])[ \t]+))*)"
    r"(?P<marks>#{1,6})(?P<separator>[ \t]+|$)(?P<title>.*)$"
)
_SOURCE_PREFIX_RE = re.compile(
    r"^(?P<prefix>[ \t]*(?:(?:>[ \t]*)|(?:(?:[-+*]|\d{1,9}[.)])[ \t]+))*)"
    r"(?P<content>.*)$"
)


def _source_atx_heading(line: str) -> tuple[str, int, str, str] | None:
    match = _ATX_SOURCE_RE.fullmatch(line)
    if match is None:
        return None
    return (
        match.group("prefix"),
        len(match.group("marks")),
        match.group("separator"),
        match.group("title"),
    )


def _source_prefix_parts(line: str) -> tuple[str, str]:
    match = _SOURCE_PREFIX_RE.fullmatch(line)
    if match is None:
        return "", line
    return match.group("prefix"), match.group("content")


def task_contract_violations(text: str) -> list[str]:
    expected_h1 = "# Subagent task contract"
    expected_h2 = [
        "## 1. Objective",
        "## 2. Ownership",
        "## 3. Inputs/evidence",
        "## 4. Constraints/requirements",
        "## 5. Verification/handoff",
    ]
    lines = _source_lines(text)
    errors = _source_separator_violations("task-contract.md", text)
    if any(re.search(r"(?:`{3,}|~{3,})", line) for line in lines):
        errors.append("task-contract.md does not allow fenced code")
    if re.search(r"<h[1-6](?:\s|>)", text, re.IGNORECASE):
        errors.append("task-contract.md does not allow raw HTML headings")
    headings: list[tuple[int, str, int]] = []
    for index, line in enumerate(lines):
        source_heading = _source_atx_heading(line)
        if source_heading is not None:
            prefix, level, separator, title = source_heading
            if prefix or separator != " ":
                errors.append(f"task-contract.md:{index + 1} contains a noncanonical or containerized heading")
            if not prefix:
                headings.append((level, title, index))
    if lines.count(expected_h1) != 1:
        errors.append("task-contract.md must contain exactly one exact H1")
    if any(level == 1 and title != "Subagent task contract" for level, title, _ in headings):
        errors.append("task-contract.md contains an unexpected H1")
    actual_h2 = [f"{'#' * level} {title}" for level, title, _ in headings if level == 2]
    if actual_h2 != expected_h2:
        errors.append("task-contract.md H2 headings must be exactly the five ordered contract sections")
    if any(level != 1 and level != 2 for level, _, _ in headings):
        errors.append("task-contract.md must not contain any H3-H6 heading")
    expected_sequence = [(1, "Subagent task contract")] + [
        (2, heading.removeprefix("## ")) for heading in expected_h2
    ]
    actual_sequence = [(level, title) for level, title, _ in headings]
    if actual_sequence != expected_sequence:
        errors.append("task-contract.md root heading sequence must be the H1 followed by the five ordered H2 sections")
    for index in range(1, len(lines)):
        prefix, content = _source_prefix_parts(lines[index])
        if not re.fullmatch(r"(?:=+|-+)[ \t]*", content):
            continue
        previous_prefix, previous_content = _source_prefix_parts(lines[index - 1])
        if previous_content.strip():
            errors.append(f"task-contract.md:{index + 1} contains a Setext heading")
    return errors


def semantic_contract_violations(skill_text: str, reference_map: dict[str, str], ui_text: str) -> list[str]:
    """Validate the registered canonical clauses, not arbitrary natural language."""
    errors: list[str] = []
    _, frontmatter_errors = _frontmatter(skill_text)
    errors.extend(frontmatter_errors)
    errors.extend(_source_dialect_violations("SKILL.md", skill_text))
    for filename, text in reference_map.items():
        errors.extend(_source_dialect_violations(filename, text))
    errors.extend(canonical_block_violations("SKILL.md", skill_text))
    if "model-routing.md" in reference_map:
        errors.extend(canonical_block_violations("model-routing.md", reference_map["model-routing.md"]))
    errors.extend(openai_yaml_violations(ui_text))
    corpus = "\n".join((skill_text, ui_text, *reference_map.values())).casefold()
    for literal in STALE_LITERALS:
        if literal.casefold() in corpus:
            errors.append(f"stale contract literal is forbidden: {literal}")
    return errors


def validate_skill(root: Path, check: Validation) -> None:
    skill = root / "payload/skills/versatile-dev/SKILL.md"
    check.require(skill.is_file(), f"missing {skill}")
    if not skill.is_file():
        return
    text = _read_controlled_source(skill, check)
    reference_dir = root / "payload/skills/versatile-dev/references"
    actual_references = {path.name for path in reference_dir.glob("*.md")}
    reference_map = {
        path.name: _read_controlled_source(path, check)
        for path in reference_dir.glob("*.md")
        if path.is_file()
    }
    ui = root / "payload/skills/versatile-dev/agents/openai.yaml"
    check.require(ui.is_file(), "missing agents/openai.yaml")
    ui_text = _read_controlled_source(ui, check) if ui.is_file() else ""
    check.require(actual_references == SKILL_REFERENCE_FILES, f"skill references must be exactly {sorted(SKILL_REFERENCE_FILES)}: {sorted(actual_references)}")
    for error in semantic_contract_violations(text, reference_map, ui_text):
        check.errors.append(error)
    for error in task_contract_violations(reference_map.get("task-contract.md", "")):
        check.errors.append(error)
    for error in reference_topology_violations(text, reference_map, skill):
        check.errors.append(error)


def validate_agents(root: Path, check: Validation) -> None:
    for obsolete in (
        root / "payload/agents/profiles/luna-v1/docs_researcher.toml",
        root / "payload/agents/profiles/terra-fallback/docs_researcher.toml",
    ):
        check.require(not obsolete.exists() and not obsolete.is_symlink(), f"obsolete profile payload must be absent: {obsolete}")
    check.errors.extend(agent_directory_violations(root / "payload/agents/common"))


def _compile_required(root: Path, check: Validation, helper: str, focused_test: str, label: str) -> None:
    helper_path, test_path = root / helper, root / focused_test
    check.require(helper_path.is_file(), f"missing {label} helper: {helper_path}")
    check.require(test_path.is_file(), f"missing {label} test: {test_path}")
    for path in (helper_path, test_path):
        if path.is_file():
            try:
                compile(path.read_text(encoding="utf-8"), str(path), "exec")
            except (OSError, SyntaxError) as exc:
                check.errors.append(f"invalid Python {label} file {path}: {exc}")


def validate_runtime_records(root: Path, check: Validation) -> None:
    _compile_required(root, check, "payload/skills/versatile-dev/scripts/runtime_records.py", "tests/test_runtime_records.py", "runtime-record")
    fixture_dir = root / "tests/fixtures/runtime"
    actual = {path.name for path in fixture_dir.iterdir()} if fixture_dir.is_dir() else set()
    check.require(actual == RUNTIME_RECORD_FIXTURES, f"runtime fixture set mismatch: {sorted(actual)}")


def validate_route_research(root: Path, check: Validation) -> None:
    _compile_required(root, check, "payload/skills/versatile-dev/scripts/route_research.py", "tests/test_routing_state.py", "route-research")
    fixture_dir = root / "tests/fixtures/routing"
    actual = {path.name for path in fixture_dir.iterdir()} if fixture_dir.is_dir() else set()
    check.require(actual == ROUTING_FIXTURES, f"routing fixture set mismatch: {sorted(actual)}")


def validate_runtime_audit(root: Path, check: Validation) -> None:
    _compile_required(root, check, "payload/skills/versatile-dev/scripts/runtime_audit.py", "tests/test_manifest_audit.py", "runtime-audit")


def validate_root(root: Path, check: Validation) -> None:
    required = (
        "VERSION",
        "README.md",
        "DEVELOPMENT_PLAN.md",
        "install.sh",
        "validate.sh",
        "package.sh",
        "scripts/merge_config.py",
        "scripts/ensure_snippet.py",
        "scripts/write_manifest.py",
        "payload/config/agents.toml.snippet",
        "payload/AGENTS.md.snippet",
    )
    for relative in required:
        check.require((root / relative).is_file(), f"missing required file: {relative}")
    snippet_path = root / "payload/config/agents.toml.snippet"
    if snippet_path.is_file():
        try:
            snippet = tomllib.loads(snippet_path.read_text(encoding="utf-8"))["agents"]
        except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
            check.errors.append(f"invalid agents config snippet: {exc}")
        else:
            expected = {
                "enabled": True,
                "max_concurrent_threads_per_session": 6,
                "default_subagent_model": "gpt-5.6-terra",
                "default_subagent_reasoning_effort": "medium",
                "interrupt_message": True,
            }
            check.require(snippet == expected, f"agents config snippet drifted: {snippet}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=Path.cwd(), type=Path)
    root = parser.parse_args().root.resolve()
    check = Validation()
    validate_root(root, check)
    validate_skill(root, check)
    validate_agents(root, check)
    validate_runtime_records(root, check)
    validate_route_research(root, check)
    validate_runtime_audit(root, check)
    if check.errors:
        for error in check.errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"Bundle validation failed with {len(check.errors)} error(s).", file=sys.stderr)
        return 1
    print("Bundle validation passed: skill + 13-agent dual-researcher bundle.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
