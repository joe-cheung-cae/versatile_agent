#!/usr/bin/env python3
"""Structural and semantic validation for the distributable bundle."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path


REQUIRED_AGENT_KEYS = {"name", "description", "developer_instructions", "model", "model_reasoning_effort", "sandbox_mode"}
ALLOWED_MODELS = {"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"}
ALLOWED_EFFORTS = {"low", "medium", "high", "xhigh", "max", "ultra"}
ALLOWED_SANDBOX = {"read-only", "workspace-write", "danger-full-access"}
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
    "cuda-cae-review-policy.md",
    "model-routing.md",
    "review-policy.md",
    "task-contract.md",
    "workflow.md",
}
TASK_CONTRACT_HEADINGS = (
    "## 1. Objective",
    "## 2. Ownership",
    "## 3. Inputs/evidence",
    "## 4. Constraints/requirements",
    "## 5. Verification/handoff",
)
ATX_TASK_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*$")
FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
FENCE_CLOSE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")
SETEXT_UNDERLINE_RE = re.compile(r"^ {0,3}(?:=+|-+)[ \t]*$")
CONTRACT_CLAUSE_SPLIT_RE = re.compile(r"(?:[.!?;:]+(?=\s|$)|\b(?:but|however|although)\b)")


def _normalize_contract_text(text: str) -> str:
    """Normalize prose enough for small, deterministic semantic checks."""

    normalized = text.casefold().replace("’", "'").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", normalized).strip()


def _contract_clauses(text: str) -> list[str]:
    """Split normalized prose at sentence and adversative clause boundaries."""

    normalized = _normalize_contract_text(text)
    return [clause.strip() for clause in CONTRACT_CLAUSE_SPLIT_RE.split(normalized) if clause.strip()]


FAILURE_KIND = r"(?:content|tool|task|timeout|unknown(?:[-\s]+exception)?)"
FAILURE_SOURCE = (
    rf"{FAILURE_KIND}(?:[ ,/&]+(?:and\s+)?{FAILURE_KIND}){{0,4}}"
    r"(?:\s+(?:failure|failures|error|errors|outcome|outcomes|exception|exceptions))?"
)
ROUTING_ACTION = r"(?:authorize|authorizes|authorizing|trigger|triggers|triggering|permit|permits|permitting|allow|allows|allowing|enable|enables|enabling)"
ROUTING_TARGET = r"(?:terra(?:\s+fallback)?|fallback)"
PASSIVE_ROUTING_ACTION = r"(?:authorized|triggered|permitted|allowed|enabled)"
ROUTE_EVIDENCE = r"(?:the\s+)?(?:installation\s+manifest|manifest|probe)"
EFFECTIVE_ROUTE = r"(?:the\s+)?(?:effective\s+)?(?:native\s+)?route"
AUTOMATIC_CLI = r"automatic\s+cli\s+(?:routing|fallback|model\s+switch(?:ing)?)"
LIVE_CONFORMANCE_EVIDENCE = r"(?:offline\s+validation|offline\s+checks|offline\s+validator)"
LIVE_RUNTIME_CONFORMANCE = r"(?:live\s+runtime\s+conformance|live\s+conformance)"


# Each rule has positive forms and explicit local negation guards. Matching is
# clause-local; a negation in one sentence cannot suppress a contradiction in a
# later sentence.
CONTRACT_CONTRADICTION_RULES: tuple[
    tuple[str, tuple[re.Pattern[str], ...], tuple[re.Pattern[str], ...]], ...
] = (
    (
        "App task may bypass current-request authorization",
        (
            re.compile(r"\bapp(?:\s+user-visible)?\s+tasks?\s+(?:require|requires|need|needs)\s+no\s+(?:explicit\s+)?authori[sz]ation\b"),
            re.compile(r"\bno\s+(?:explicit\s+)?authori[sz]ation\s+(?:is\s+)?required\s+for\s+app(?:\s+user-visible)?\s+tasks?\b"),
            re.compile(r"\bapp(?:\s+user-visible)?\s+tasks?\s+(?:do\s+not|don't|never)\s+require\s+(?:any\s+)?(?:explicit\s+)?authori[sz]ation\b"),
            re.compile(r"\b(?:create|creating)\s+(?:an?\s+)?app(?:\s+user-visible)?\s+task\b[^.!?;:]{0,80}\bwithout\s+(?:an?\s+)?(?:explicit\s+)?authori[sz]ation\b"),
            re.compile(r"\bapp(?:\s+user-visible)?\s+tasks?\b[^.!?;:]{0,80}\b(?:may|can|could|will|is|are)\s+(?:be\s+)?created\s+without\s+(?:an?\s+)?(?:explicit\s+)?authori[sz]ation\b"),
            re.compile(r"\bapp(?:\s+user-visible)?\s+tasks?\b[^.!?;:]{0,100}\b(?:may|can|could|will)\s+(?:be\s+)?created[^.!?;:]{0,40}\bby\s+default\b"),
            re.compile(r"\b(?:create|creating)\s+(?:an?\s+)?app(?:\s+user-visible)?\s+task\b[^.!?;:]{0,80}\bunless\s+(?:the\s+)?user\s+opts?\s+out\b"),
        ),
        (
            re.compile(r"\bapp(?:\s+user-visible)?\s+tasks?\s+cannot\s+be\s+created\s+without\s+(?:an?\s+)?(?:explicit\s+)?authori[sz]ation\b"),
            re.compile(r"\bapp(?:\s+user-visible)?\s+tasks?\s+(?:must|should)\s+not\s+be\s+created\s+without\s+(?:an?\s+)?(?:explicit\s+)?authori[sz]ation\b"),
            re.compile(r"\b(?:do\s+not|don't|never|must\s+not|should\s+not)\s+(?:create|creating)\s+(?:an?\s+)?app(?:\s+user-visible)?\s+task\b[^.!?;:]{0,80}\bwithout\s+(?:an?\s+)?(?:explicit\s+)?authori[sz]ation\b"),
        ),
    ),
    (
        "App task accepts prior or implicit authorization",
        (
            re.compile(r"\bauthori[sz]ation\s+from\s+(?:an?\s+)?(?:prior|previous|earlier|past)\s+request\b\s+(?:is\s+)?(?:also\s+)?(?:acceptable|accepted|sufficient|enough)\b"),
            re.compile(r"\b(?:prior|previous|earlier|past)\s+(?:user\s+)?request\s+authori[sz]ation\b\s+(?:is\s+)?(?:also\s+)?(?:acceptable|accepted|sufficient|enough)\b"),
            re.compile(r"\b(?:prior|previous|earlier|past)\s+authori[sz]ation\b\s+(?:is\s+)?(?:also\s+)?(?:acceptable|accepted|sufficient|enough)\b[^.!?;:]{0,80}\b(?:app(?:\s+user-visible)?\s+tasks?|creat(?:e|ing))\b"),
            re.compile(r"\bapp(?:\s+user-visible)?\s+tasks?\b[^.!?;:]{0,80}\b(?:accept|accepts|allow|allows|use|uses)\b[^.!?;:]{0,50}\b(?:prior|previous|earlier|past)\s+(?:request\s+)?authori[sz]ation\b"),
            re.compile(r"\bunless\s+(?:(?:the\s+user\s+was)\s+)?(?:previously|prior|earlier)\s+authori[sz]ed\b"),
            re.compile(r"\bunless\s+(?:a\s+)?(?:prior|previous|earlier)\s+request\s+authori[sz]ation\b"),
            re.compile(r"\b(?:implicit|implied)\s+(?:consent|authori[sz]ation)\b\s+(?:is\s+)?(?:also\s+)?(?:acceptable|accepted|sufficient|enough)\b"),
            re.compile(r"\b(?:implicit|implied)\s+(?:consent|authori[sz]ation)\b\s+(?:is\s+)?(?:allowed|permitted)\b"),
            re.compile(r"\b(?:implicit|implied)\s+(?:consent|authori[sz]ation)\b\s+suffices\b"),
            re.compile(r"\b(?:app\s+task\s+creation|app(?:\s+user-visible)?\s+tasks?)\b[^.!?;:]{0,60}\b(?:accept|accepts|allow|allows|may\s+use)\b[^.!?;:]{0,50}\b(?:implicit|implied)\s+(?:consent|authori[sz]ation)\b"),
            re.compile(r"\bapp(?:\s+user-visible)?\s+tasks?\b[^.!?;:]{0,60}\b(?:may|can|could|will)\s+rely\s+on\s+(?:implicit|implied)\s+(?:consent|authori[sz]ation)\b"),
            re.compile(r"\bcurrent[-\s]+(?:user[-\s]+)?request\s+authori[sz]ation\b\s+(?:is\s+)?(?:optional|unnecessary)\b"),
            re.compile(r"\b(?:current[-\s]+(?:user[-\s]+)?request\s+)?authori[sz]ation\b\s+(?:may|can)\s+be\s+omitted\b"),
            re.compile(r"\b(?:may|can)\s+omit\s+(?:the\s+)?(?:current[-\s]+(?:user[-\s]+)?request\s+)?authori[sz]ation\b"),
        ),
        (
            re.compile(r"\b(?:prior|previous|earlier|past)\s+authori[sz]ation\s+is\s+not\s+(?:acceptable|accepted|sufficient|enough)\b"),
            re.compile(r"\b(?:implicit|implied)\s+consent\s+is\s+not\s+(?:acceptable|accepted|sufficient|enough)\b"),
            re.compile(r"\bapp(?:\s+user-visible)?\s+tasks?\b\s+(?:cannot|can't|may\s+not|must\s+not|should\s+not)\s+rely\s+on\s+(?:implicit|implied)\s+(?:consent|authori[sz]ation)\b"),
            re.compile(r"\bcurrent[-\s]+(?:user[-\s]+)?request\s+authori[sz]ation\s+is\s+not\s+(?:optional|unnecessary)\b"),
        ),
    ),
    (
        "Non-routing failures may authorize Terra or fallback",
        (
            re.compile(rf"\b{FAILURE_SOURCE}\s+(?:(?:may|can|could|will)\s+)?{ROUTING_ACTION}\s+{ROUTING_TARGET}\b"),
            re.compile(rf"\b{ROUTING_TARGET}\s+(?:is|are|can\s+be|could\s+be)\s+{PASSIVE_ROUTING_ACTION}\s+by\s+{FAILURE_SOURCE}\b"),
            re.compile(rf"\b(?:if|when)\s+(?:a\s+)?task\s+(?:fails?|has\s+failed)\b[^.!?;:]{{0,50}}\b(?:use|select|route\s+to)\s+{ROUTING_TARGET}\b"),
            re.compile(rf"\b(?:use|select|route\s+to)\s+{ROUTING_TARGET}\b[^.!?;:]{{0,50}}\b(?:if|when)\s+(?:a\s+)?task\s+(?:fails?|has\s+failed)\b"),
            re.compile(rf"\b{FAILURE_SOURCE}\s+and\s+native\s+routing\s+failures\s+(?:(?:may|can|could|will)\s+)?{ROUTING_ACTION}\s+{ROUTING_TARGET}\b"),
            re.compile(rf"\bnative\s+routing\s+failures\s+and\s+{FAILURE_SOURCE}\s+(?:(?:may|can|could|will)\s+)?{ROUTING_ACTION}\s+{ROUTING_TARGET}\b"),
        ),
        (
            re.compile(rf"\b{FAILURE_SOURCE}\s+(?:never|does\s+not|do\s+not|cannot|can't)\s+{ROUTING_ACTION}\s+{ROUTING_TARGET}\b"),
            re.compile(rf"\b{FAILURE_SOURCE}\s+{ROUTING_ACTION}\s+no\s+{ROUTING_TARGET}\b"),
            re.compile(rf"\b{ROUTING_TARGET}\s+(?:is|are)\s+(?:not|never)\s+{PASSIVE_ROUTING_ACTION}\s+by\s+{FAILURE_SOURCE}\b"),
            re.compile(rf"\b(?:do\s+not|don't|never|must\s+not|should\s+not)\s+claim\s+that\s+{FAILURE_SOURCE}\s+{ROUTING_ACTION}\s+{ROUTING_TARGET}\b"),
            re.compile(rf"\bneither\s+{FAILURE_SOURCE}\s+nor\s+{FAILURE_SOURCE}\s+{ROUTING_ACTION}\s+{ROUTING_TARGET}\b"),
            re.compile(rf"\b(?:do\s+not|don't|never|cannot|can't)\s+use\s+{ROUTING_TARGET}\b[^.!?;:]{{0,50}}\b(?:if|when)\s+(?:a\s+)?task\s+(?:fails?|has\s+failed)\b"),
        ),
    ),
    (
        "Dual researchers or routing helper described as incomplete",
        (
            re.compile(r"\b(?:dual[-\s]?(?:researcher|agent)s?|dual[-\s]?agent installer|docs_researcher_luna\s*(?:and|/)\s*docs_researcher_terra|(?:two|both)\s+(?:named\s+)?researchers?|route_research\.py|(?:route|routing)(?:[-\s]+research)?[-\s]+helper)\b[^.!?;:]{0,120}\b(?:future|pending|planned|later|unimplemented)\b"),
            re.compile(r"\b(?:dual[-\s]?(?:researcher|agent)s?|dual[-\s]?agent installer|docs_researcher_luna\s*(?:and|/)\s*docs_researcher_terra|(?:two|both)\s+(?:named\s+)?researchers?|route_research\.py|(?:route|routing)(?:[-\s]+research)?[-\s]+helper)\b[^.!?;:]{0,80}\b(?:is|are)\s+not\s+(?:installed|implemented)\b"),
        ),
        (
            re.compile(r"\b(?:dual[-\s]?(?:researcher|agent)s?|route_research\.py|(?:route|routing)(?:[-\s]+research)?[-\s]+helper)\b[^.!?;:]{0,80}\b(?:is|are)\s+not\s+(?:future|pending|planned)\b"),
        ),
    ),
    (
        "Legacy single-only researcher route described as current",
        (
            re.compile(r"\blegacy\s+single(?:[-\s]+only)?\b"),
            re.compile(r"\binstalled\s+bundle\s+provides\s+exactly\s+one\b[^.!?;:]{0,60}\b(?:legacy\s+)?docs_researcher\b"),
            re.compile(r"\blegacy\s+single\s+configured\b"),
        ),
        (re.compile(r"\b(?:not|no\s+longer)\s+legacy\s+single(?:[-\s]+only)?\b"),),
    ),
    (
        "All or every specialist is selected by default",
        (
            re.compile(r"\b(?:spawn|run|start|delegate|launch|schedule|use)\s+(?:all|every)\s+(?:the\s+)?(?:specialists?|reviewers?|agents?)\s+(?:by\s+default|as\s+default|automatically)\b"),
        ),
        (re.compile(r"\b(?:never|do\s+not|don't|must\s+not|should\s+not)\s+(?:spawn|run|start|delegate|launch|schedule|use)\s+(?:all|every)\b"),),
    ),
    (
        "Fixed specialist pipeline is required",
        (re.compile(r"\b(?:fixed|predefined|rigid)\s+(?:agent|specialist)\s+(?:pipeline|sequence|roster)\b"),),
        (re.compile(r"\b(?:not|never|do\s+not|don't|must\s+not|should\s+not)\s+(?:(?:schedule|use|require|define|follow)\s+)?(?:a\s+)?(?:fixed|predefined|rigid)\s+(?:agent|specialist)\s+(?:pipeline|sequence|roster)\b"),),
    ),
    (
        "CLI automatic fallback or model switching is enabled",
        (
            re.compile(rf"\b{AUTOMATIC_CLI}\s+(?:is|are)\s+(?:enabled|performed|available|allowed)\b"),
            re.compile(r"\b(?:this\s+)?skill\s+(?:(?:performs?|provides?|enables?|uses?)|(?:may|can|could|will)\s+(?:perform|provide|enable|use))\s+" + AUTOMATIC_CLI + r"\b"),
            re.compile(r"\bautomatic\s+model\s+fallback\s+(?:is|are)\s+(?:enabled|performed|available|allowed)\b"),
            re.compile(r"\bcli\s+automatically\s+(?:switch(?:es|ing)?\s+models?|falls?\s+back)\b"),
        ),
        (
            re.compile(r"\b(?:this\s+)?skill\s+(?:does\s+not|doesn't|do\s+not|don't|never|cannot|can't|may\s+not)\s+(?:perform|provide|enable|use)\s+" + AUTOMATIC_CLI + r"\b"),
            re.compile(r"\b(?:automatic\s+cli\s+(?:routing|fallback|model\s+switch(?:ing)?)|automatic\s+model\s+fallback)\s+(?:is|are)\s+not\s+(?:enabled|performed|available|allowed)\b"),
            re.compile(r"\bcli\s+(?:does\s+not|doesn't|do\s+not|don't|never|cannot|can't)\s+automatically\s+(?:switch(?:es|ing)?\s+models?|falls?\s+back)\b"),
        ),
    ),
    (
        "Stale implementation or live-conformance claim",
        (
            re.compile(r"\bcurrent\s+implementation\s+boundary\b"),
            re.compile(r"\blive\s+conformance\b[^.!?;:]{0,80}\b(?:future|pending|not implemented|planned)\b"),
        ),
        (),
    ),
    (
        "Probe, manifest, or App task proves effective route",
        (
            re.compile(rf"\b{ROUTE_EVIDENCE}\s+(?:proves?|establishes?|demonstrates?|confirms?)\s+{EFFECTIVE_ROUTE}\b"),
            re.compile(rf"\b{ROUTE_EVIDENCE}\s+(?:may|can|could|will)\s+(?:prove|establish|demonstrate|confirm)\s+{EFFECTIVE_ROUTE}\b"),
            re.compile(rf"\b{EFFECTIVE_ROUTE}\s+(?:is|are|can\s+be|could\s+be)\s+(?:proven|established|demonstrated|confirmed)\s+by\s+{ROUTE_EVIDENCE}\b"),
        ),
        (
            re.compile(rf"\b{ROUTE_EVIDENCE}\s+(?:does\s+not|doesn't|do\s+not|don't|never|cannot|can't|will\s+not)\s+(?:prove|establish|demonstrate|confirm)\s+{EFFECTIVE_ROUTE}\b"),
            re.compile(rf"\b{EFFECTIVE_ROUTE}\s+(?:is|are)\s+(?:not|never)\s+(?:proven|established|demonstrated|confirmed)\s+by\s+{ROUTE_EVIDENCE}\b"),
        ),
    ),
    (
        "Offline validation proves live runtime conformance",
        (
            re.compile(rf"\b{LIVE_CONFORMANCE_EVIDENCE}\s+(?:proves?|establishes?|demonstrates?|confirms?)\s+(?:the\s+)?{LIVE_RUNTIME_CONFORMANCE}\b"),
            re.compile(rf"\b{LIVE_CONFORMANCE_EVIDENCE}\s+(?:may|can|could|will)\s+(?:prove|establish|demonstrate|confirm)\s+(?:the\s+)?{LIVE_RUNTIME_CONFORMANCE}\b"),
            re.compile(rf"\b{LIVE_RUNTIME_CONFORMANCE}\s+(?:is|are|can\s+be|could\s+be)\s+(?:proven|established|demonstrated|confirmed)\s+by\s+{LIVE_CONFORMANCE_EVIDENCE}\b"),
        ),
        (
            re.compile(rf"\b{LIVE_CONFORMANCE_EVIDENCE}\s+(?:does\s+not|doesn't|do\s+not|don't|never|cannot|can't|will\s+not)\s+(?:prove|establish|demonstrate|confirm)\s+(?:the\s+)?{LIVE_RUNTIME_CONFORMANCE}\b"),
            re.compile(rf"\b{LIVE_RUNTIME_CONFORMANCE}\s+(?:is|are)\s+(?:not|never)\s+(?:proven|established|demonstrated|confirmed)\s+by\s+{LIVE_CONFORMANCE_EVIDENCE}\b"),
        ),
    ),
    (
        "Skill changes parent model or permissions",
        (
            re.compile(r"\b(?:this\s+)?skill\s+(?:(?:changes?|switches?|controls?|overrides?)|(?:can|could|may)\s+(?:change|switch|control|override))\s+(?:the\s+)?(?:parent\s+model|permissions?)\b"),
            re.compile(r"\b(?:the\s+)?(?:parent\s+model|permissions?)\s+(?:is|are|can\s+be|could\s+be)\s+(?:changed|switched|controlled|overridden)\s+by\s+(?:this\s+)?skill\b"),
        ),
        (
            re.compile(r"\b(?:this\s+)?skill\s+(?:does\s+not|doesn't|do\s+not|don't|never|cannot|can't|may\s+not)\s+(?:change|switch|control|override)\s+(?:the\s+)?(?:parent\s+model|permissions?)\b"),
            re.compile(r"\b(?:do\s+not|don't|never|must\s+not|should\s+not)\s+claim\s+that\s+(?:this\s+)?skill\s+(?:changes?|switches?|controls?|overrides?)\s+(?:the\s+)?(?:parent\s+model|permissions?)\b"),
            re.compile(r"\b(?:the\s+)?(?:parent\s+model|permissions?)\s+(?:is|are)\s+(?:not|never)\s+(?:changed|switched|controlled|overridden)\s+by\s+(?:this\s+)?skill\b"),
        ),
    ),
    (
        "Skill guarantees model availability",
        (
            re.compile(r"\b(?:this\s+)?skill\s+(?:guarantees?|ensures?)\s+(?:the\s+)?(?:model\s+)?availability\b"),
            re.compile(r"\b(?:model\s+)?availability\s+(?:is|are)\s+(?:guaranteed|ensured)\s+by\s+(?:this\s+)?skill\b"),
        ),
        (
            re.compile(r"\b(?:this\s+)?skill\s+(?:does\s+not|doesn't|do\s+not|don't|never|cannot|can't)\s+(?:guarantee|ensure)\s+(?:the\s+)?(?:model\s+)?availability\b"),
            re.compile(r"\b(?:model\s+)?availability\s+(?:is|are)\s+not\s+(?:guaranteed|ensured)\s+by\s+(?:this\s+)?skill\b"),
        ),
    ),
)
REQUIRED_CONTRACT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "App task must require explicit current-request authorization",
        re.compile(
            r"\bcreate\s+an?\s+app(?:\s+user-visible)?\s+task\b.{0,80}\bonly\s+after\s+explicit\s+authori[sz]ation\s+in\s+the\s+current\s+user\s+request\b"
        ),
    ),
)


def _normalize_markdown_target(raw_target: str) -> str | None:
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    if not target or target.startswith("//") or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
        return None
    target = re.split(r"[?#]", target, maxsplit=1)[0]
    while target.startswith("./"):
        target = target[2:]
    return target or None


def _normalize_reference_label(label: str) -> str:
    return re.sub(r"\s+", " ", label.casefold().strip())


def _line_fence_marker(line: str) -> tuple[str, int] | None:
    indent = 0
    while indent < len(line) and indent < 3 and line[indent] == " ":
        indent += 1
    if indent >= len(line) or line[indent] not in "`~":
        return None
    marker = line[indent]
    end = indent
    while end < len(line) and line[end] == marker:
        end += 1
    if end - indent < 3:
        return None
    return marker, end - indent


def _parse_reference_definition(line: str) -> tuple[str, str] | None:
    indent = 0
    while indent < len(line) and indent < 3 and line[indent] == " ":
        indent += 1
    if indent >= len(line) or line[indent] != "[":
        return None
    close = indent + 1
    while close < len(line) and line[close] != "]":
        close += 1
    if close >= len(line) or close + 1 >= len(line) or line[close + 1] != ":":
        return None
    label = _normalize_reference_label(line[indent + 1 : close])
    target_start = close + 2
    while target_start < len(line) and line[target_start] in " \t":
        target_start += 1
    if target_start >= len(line):
        return None
    if line[target_start] == "<":
        target_end = target_start + 1
        while target_end < len(line) and line[target_end] != ">":
            target_end += 1
        if target_end >= len(line):
            return None
        target = line[target_start : target_end + 1]
    else:
        target_end = target_start
        while target_end < len(line) and line[target_end] not in " \t":
            target_end += 1
        target = line[target_start:target_end]
    return (label, target) if label else None


def _scan_rendered_markdown(text: str) -> tuple[list[str], list[str]]:
    """Scan the needed Markdown link subset once, ignoring code and images."""

    definitions: dict[str, str] = {}
    direct_targets: list[str] = []
    reference_usages: list[tuple[str, bool]] = []
    fence_marker: str | None = None
    fence_length = 0

    for line in text.splitlines():
        marker = _line_fence_marker(line)
        if fence_marker is not None:
            if marker is not None and marker[0] == fence_marker and marker[1] >= fence_length:
                remainder = line[line.find(marker[0]) + marker[1] :].strip()
                if not remainder:
                    fence_marker = None
                    fence_length = 0
            continue
        if marker is not None:
            fence_marker, fence_length = marker
            continue

        definition = _parse_reference_definition(line)
        if definition is not None:
            definitions[definition[0]] = definition[1]
            continue

        i = 0
        label_start: int | None = None
        while i < len(line):
            if line[i] == "`":
                run_end = i + 1
                while run_end < len(line) and line[run_end] == "`":
                    run_end += 1
                run_length = run_end - i
                close = line.find("`" * run_length, run_end)
                i = len(line) if close < 0 else close + run_length
                label_start = None
                continue

            if line[i] == "[" and label_start is None:
                label_start = i + 1
                image = i > 0 and line[i - 1] == "!"
                candidate_start = i
                i += 1
                continue

            if line[i] == "]" and label_start is not None:
                label = line[label_start:i]
                image = candidate_start > 0 and line[candidate_start - 1] == "!"
                next_index = i + 1
                while next_index < len(line) and line[next_index] in " \t":
                    next_index += 1
                consumed = i + 1
                if next_index < len(line) and line[next_index] == "(":
                    target_end = next_index + 1
                    while target_end < len(line) and line[target_end] != ")":
                        target_end += 1
                    if target_end >= len(line):
                        i = len(line)
                    else:
                        if not image:
                            direct_targets.append(line[next_index + 1 : target_end].strip())
                        i = target_end + 1
                    label_start = None
                    continue
                if next_index < len(line) and line[next_index] == "[":
                    reference_end = next_index + 1
                    while reference_end < len(line) and line[reference_end] != "]":
                        reference_end += 1
                    if reference_end < len(line):
                        if not image:
                            reference_label = line[next_index + 1 : reference_end] or label
                            reference_usages.append((reference_label, True))
                        consumed = reference_end + 1
                elif not image and label:
                    reference_usages.append((label, False))
                label_start = None
                i = consumed
                continue

            i += 1

    raw_targets = list(direct_targets)
    unresolved: list[str] = []
    for label, explicit in reference_usages:
        target = definitions.get(_normalize_reference_label(label))
        if target is None:
            if explicit:
                unresolved.append(label)
        else:
            raw_targets.append(target)

    targets: list[str] = []
    for raw_target in raw_targets:
        target = _normalize_markdown_target(raw_target)
        if target is not None:
            targets.append(target)
    return targets, unresolved


def extract_local_markdown_targets(text: str) -> list[str]:
    """Extract normalized targets from rendered inline and reference-use links."""

    targets, _ = _scan_rendered_markdown(text)
    return targets


def _contract_rule_matches(
    clauses: list[str],
    positive_patterns: tuple[re.Pattern[str], ...],
    negative_patterns: tuple[re.Pattern[str], ...],
) -> bool:
    """Match a contradiction unless a negation overlaps that same match."""

    for clause in clauses:
        negative_spans = [
            match.span()
            for pattern in negative_patterns
            for match in pattern.finditer(clause)
        ]
        for pattern in positive_patterns:
            for positive_match in pattern.finditer(clause):
                positive_start, positive_end = positive_match.span()
                if not any(
                    negative_start < positive_end and positive_start < negative_end
                    for negative_start, negative_end in negative_spans
                ):
                    return True
    return False


def semantic_contract_violations(
    skill_text: str,
    reference_map: Mapping[str, str],
    ui_text: str = "",
) -> list[str]:
    """Return explicit contradiction labels for the frozen Skill contract."""

    reference_text = (reference_map[name] for name in sorted(reference_map))
    corpus = ". ".join((skill_text, *reference_text, ui_text))
    clauses = _contract_clauses(corpus)
    violations: list[str] = []
    for label, positive_patterns, negative_patterns in CONTRACT_CONTRADICTION_RULES:
        if _contract_rule_matches(clauses, positive_patterns, negative_patterns):
            violations.append(label)
    skill_corpus = _normalize_contract_text(skill_text)
    for label, pattern in REQUIRED_CONTRACT_PATTERNS:
        if pattern.search(skill_corpus) is None:
            violations.append(label)
    return violations


def _unfenced_lines(text: str) -> tuple[list[str], bool]:
    """Return rendered lines and whether a backtick/tilde fence is unclosed."""

    rendered: list[str] = []
    fence_char: str | None = None
    fence_length = 0
    for line in text.splitlines():
        if fence_char is None:
            opening = FENCE_OPEN_RE.match(line)
            if opening is not None:
                fence = opening.group(1)
                fence_char = fence[0]
                fence_length = len(fence)
                continue
            rendered.append(line)
            continue

        closing = FENCE_CLOSE_RE.match(line)
        if closing is not None:
            fence = closing.group(1)
            if fence[0] == fence_char and len(fence) >= fence_length:
                fence_char = None
                fence_length = 0
    return rendered, fence_char is not None


def task_contract_violations(text: str) -> list[str]:
    """Require exactly five rendered H2 sections and reject Setext headings."""

    lines, unclosed_fence = _unfenced_lines(text)
    headings: list[str] = []
    non_h2_headings: list[str] = []
    for line in lines:
        match = ATX_TASK_HEADING_RE.match(line)
        if match is None:
            continue
        level = len(match.group(1))
        heading_text = re.sub(r"[ \t]+#+[ \t]*$", "", match.group(2).strip())
        heading = f"{'#' * level} {heading_text}"
        if level == 2:
            headings.append(heading)
        elif level >= 3:
            non_h2_headings.append(heading)

    violations: list[str] = []
    if headings != list(TASK_CONTRACT_HEADINGS):
        violations.append(f"task-contract H2 headings must be exactly {list(TASK_CONTRACT_HEADINGS)}: {headings}")
    if non_h2_headings:
        violations.append(f"task-contract must not contain rendered H3-H6 headings: {non_h2_headings}")
    if unclosed_fence:
        violations.append("task-contract contains an unclosed fenced code block")
    for index, line in enumerate(lines[:-1]):
        if line.strip() and SETEXT_UNDERLINE_RE.match(lines[index + 1]):
            violations.append("task-contract must not contain rendered Setext headings")
            break
    return violations


def reference_topology_violations(
    skill_text: str,
    reference_map: Mapping[str, str],
    skill_path: Path | None = None,
) -> list[str]:
    """Validate direct Skill links and reject reference-to-reference links."""

    violations: list[str] = []
    actual_references = set(reference_map)
    if actual_references != SKILL_REFERENCE_FILES:
        violations.append(
            f"skill references must be exactly {sorted(SKILL_REFERENCE_FILES)}: {sorted(actual_references)}"
        )

    expected_links = {f"references/{name}" for name in SKILL_REFERENCE_FILES}
    rendered_skill_links, unresolved_skill_links = _scan_rendered_markdown(skill_text)
    local_links = set(rendered_skill_links)
    for label in unresolved_skill_links:
        violations.append(f"SKILL.md has an unresolved reference-style link: {label}")
    if local_links != expected_links:
        violations.append(f"SKILL.md links must resolve to direct references only: {sorted(local_links)}")

    if skill_path is not None:
        for target in local_links:
            if not (skill_path.parent / target).is_file():
                violations.append(f"SKILL.md has an unresolved local link: {target}")

    for name, text in reference_map.items():
        rendered_links, unresolved_links = _scan_rendered_markdown(text)
        for label in unresolved_links:
            violations.append(f"skill reference has an unresolved reference-style link: {name}: {label}")
        nested_links = [target for target in rendered_links if target.casefold().endswith(".md")]
        if nested_links:
            violations.append(f"skill reference must not link to another local reference: {name}: {nested_links}")
    return violations


class Validation:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self.errors.append(message)


def parse_agent(path: Path, check: Validation) -> dict:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        check.errors.append(f"invalid agent TOML {path}: {exc}")
        return {}
    missing = REQUIRED_AGENT_KEYS - set(data)
    check.require(not missing, f"{path} missing keys: {sorted(missing)}")
    check.require(data.get("model") in ALLOWED_MODELS, f"{path} has unsupported model: {data.get('model')}")
    check.require(data.get("model_reasoning_effort") in ALLOWED_EFFORTS, f"{path} has unsupported effort: {data.get('model_reasoning_effort')}")
    check.require(data.get("sandbox_mode") in ALLOWED_SANDBOX, f"{path} has unsupported sandbox: {data.get('sandbox_mode')}")
    check.require(bool(str(data.get("description", "")).strip()), f"{path} has an empty description")
    check.require(bool(str(data.get("developer_instructions", "")).strip()), f"{path} has empty developer instructions")
    return data


def validate_skill(root: Path, check: Validation) -> None:
    skill = root / "payload/skills/versatile-dev/SKILL.md"
    check.require(skill.is_file(), f"missing {skill}")
    if not skill.is_file():
        return
    text = skill.read_text(encoding="utf-8")
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    check.require(match is not None, "SKILL.md must begin with YAML frontmatter")
    if match:
        frontmatter = match.group(1)
        keys = [line.split(":", 1)[0].strip() for line in frontmatter.splitlines() if ":" in line]
        check.require(keys == ["name", "description"], f"SKILL.md frontmatter keys must be name and description only: {keys}")
        check.require("name: versatile-dev" in frontmatter, "SKILL.md name must be versatile-dev")
        check.require("TODO" not in text, "SKILL.md still contains TODO text")

    ui = root / "payload/skills/versatile-dev/agents/openai.yaml"
    ui_text = ""
    check.require(ui.is_file(), "missing agents/openai.yaml")
    if ui.is_file():
        ui_text = ui.read_text(encoding="utf-8")
        check.require("$versatile-dev" in ui_text, "openai.yaml default_prompt must mention $versatile-dev")

    reference_dir = root / "payload/skills/versatile-dev/references"
    actual_references = {item.name for item in reference_dir.glob("*.md")}
    check.require(
        actual_references == SKILL_REFERENCE_FILES,
        f"skill references must be exactly {sorted(SKILL_REFERENCE_FILES)}: {sorted(actual_references)}",
    )
    reference_map = {
        path.name: path.read_text(encoding="utf-8")
        for path in reference_dir.glob("*.md")
    }
    for violation in semantic_contract_violations(text, reference_map, ui_text):
        check.errors.append(f"Skill semantic contradiction: {violation}")
    for violation in task_contract_violations(reference_map.get("task-contract.md", "")):
        check.errors.append(violation)
    for violation in reference_topology_violations(text, reference_map, skill):
        check.errors.append(violation)


def validate_agents(root: Path, check: Validation) -> None:
    for obsolete in (
        root / "payload/agents/profiles/luna-v1/docs_researcher.toml",
        root / "payload/agents/profiles/terra-fallback/docs_researcher.toml",
    ):
        check.require(not obsolete.exists() and not obsolete.is_symlink(), f"obsolete profile payload must be absent: {obsolete}")

    common_dir = root / "payload/agents/common"
    common_paths = sorted(common_dir.glob("*.toml"))
    common_data = {path.name: parse_agent(path, check) for path in common_paths}
    common_files = set(common_data)
    check.require(
        common_files == EXPECTED_COMMON_FILES,
        f"common agent files mismatch: {sorted(common_files)}",
    )

    common_names = [str(item.get("name")) for item in common_data.values() if item]
    check.require(len(common_paths) == 13, f"common agent set must contain exactly 13 TOMLs, found {len(common_paths)}")
    check.require(
        len(common_names) == len(set(common_names)),
        f"common agent names must be unique: {sorted(common_names)}",
    )
    check.require(set(common_names) == EXPECTED_COMMON, f"common agent names mismatch: {sorted(common_names)}")

    researcher_pins = {
        "docs_researcher_luna.toml": ("docs_researcher_luna", "gpt-5.6-luna", "max"),
        "docs_researcher_terra.toml": ("docs_researcher_terra", "gpt-5.6-terra", "high"),
    }
    for filename, (name, model, effort) in researcher_pins.items():
        data = common_data.get(filename, {})
        check.require(data.get("name") == name, f"{filename} must provide {name}")
        check.require(data.get("model") == model, f"{filename} must pin {model}")
        check.require(data.get("model_reasoning_effort") == effort, f"{filename} must use {effort} effort")
        check.require(data.get("sandbox_mode") == "read-only", f"{filename} must use read-only sandbox")


def validate_runtime_records(root: Path, check: Validation) -> None:
    helper = root / "payload/skills/versatile-dev/scripts/runtime_records.py"
    focused_test = root / "tests/test_runtime_records.py"
    check.require(helper.is_file(), f"missing runtime-record helper: {helper}")
    check.require(focused_test.is_file(), f"missing runtime-record test: {focused_test}")
    for path in (helper, focused_test):
        if path.is_file():
            try:
                compile(path.read_text(encoding="utf-8"), str(path), "exec")
            except (OSError, SyntaxError) as exc:
                check.errors.append(f"invalid Python runtime-record file {path}: {exc}")

    fixture_dir = root / "tests/fixtures/runtime"
    actual_fixtures = {path.name for path in fixture_dir.iterdir()} if fixture_dir.is_dir() else set()
    check.require(
        actual_fixtures == RUNTIME_RECORD_FIXTURES,
        f"runtime fixture set mismatch: {sorted(actual_fixtures)}",
    )


def validate_route_research(root: Path, check: Validation) -> None:
    helper = root / "payload/skills/versatile-dev/scripts/route_research.py"
    focused_test = root / "tests/test_routing_state.py"
    check.require(helper.is_file(), f"missing route-research helper: {helper}")
    check.require(focused_test.is_file(), f"missing route-research test: {focused_test}")
    for path in (helper, focused_test):
        if path.is_file():
            try:
                compile(path.read_text(encoding="utf-8"), str(path), "exec")
            except (OSError, SyntaxError) as exc:
                check.errors.append(f"invalid Python route-research file {path}: {exc}")

    fixture_dir = root / "tests/fixtures/routing"
    actual_fixtures = {path.name for path in fixture_dir.iterdir()} if fixture_dir.is_dir() else set()
    check.require(
        actual_fixtures == ROUTING_FIXTURES,
        f"routing fixture set mismatch: {sorted(actual_fixtures)}",
    )


def validate_runtime_audit(root: Path, check: Validation) -> None:
    helper = root / "payload/skills/versatile-dev/scripts/runtime_audit.py"
    focused_test = root / "tests/test_manifest_audit.py"
    check.require(helper.is_file(), f"missing runtime-audit helper: {helper}")
    check.require(focused_test.is_file(), f"missing manifest/audit test: {focused_test}")
    for path in (helper, focused_test):
        if path.is_file():
            try:
                compile(path.read_text(encoding="utf-8"), str(path), "exec")
            except (OSError, SyntaxError) as exc:
                check.errors.append(f"invalid Python manifest/audit file {path}: {exc}")


def validate_root(root: Path, check: Validation) -> None:
    for relative in (
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
    ):
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
    args = parser.parse_args()
    root = args.root.resolve()
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
