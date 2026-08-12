#!/usr/bin/env python3
"""Structural and semantic validation for the distributable bundle."""

from __future__ import annotations

import argparse
from bisect import bisect_left
import html
import posixpath
import re
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple
from urllib.parse import unquote


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
ATX_TASK_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?)[ \t]*|[ \t]*)$")
SETEXT_UNDERLINE_RE = re.compile(r"^ {0,3}(?:=+|-+)[ \t]*$")
CONTRACT_CLAUSE_SPLIT_RE = re.compile(
    r"(?:[.!?;:。！？；：|]+(?=\s|$))"
)
SENSITIVE_CONNECTOR_RE = re.compile(
    r"(?:\b(?:and|yet|or|plus|while|whereas|but|however|although|though|"
    r"nevertheless|nonetheless)\b|,(?=\s+))"
)
RAW_HTML_LINK_TAG_RE = re.compile(r"<\s*/?\s*a(?:\s|/?>)", re.IGNORECASE)
RAW_HTML_HEADING_TAG_RE = re.compile(r"<\s*/?\s*h[1-6](?:\s|/?>)", re.IGNORECASE)
RAW_HTML_TAG_PREFIX_RE = re.compile(
    r"<\s*/?\s*(?:a|h[1-6])(?:\s|$)", re.IGNORECASE
)
HTML_ENTITY_RE = re.compile(r"&(?:#\d{1,7}|#x[0-9a-f]{1,6}|[a-z][a-z0-9]{1,31});", re.IGNORECASE)
SENSITIVE_PREDICATE_START_RE = re.compile(
    r"^(?:is|are|was|were|may|can|could|will|must|should|do|does|did|"
    r"authorize|authorizes|allow|allows|require|requires|rely|relies|"
    r"grant|grants|change|changes|switch|switches|prove|proves|"
    r"establish|establishes|confirm|confirms|guarantee|guarantees|"
    r"use|uses|attempt|attempts|carry|carries|forward|inherit|inherits|"
    r"confer|confers|qualify|qualifies|reason|reasons|perform|performs|"
    r"bypass|bypasses|fallback|falls?|default|defaults|creation|creations|"
    r"enable|enables)\b"
)
SENSITIVE_SUBJECT_START_RE = re.compile(
    r"^(?:they|it|this\s+skill|app(?:\s+user-visible)?\s+tasks?|"
    r"previous|prior|earlier|tool|content|task|timeout|unknown|"
    r"the\s+manifest|the\s+probe|a\s+probe)\b"
)
GOVERNING_MODAL_NEGATION_RE = re.compile(
    r"\b(?:do\s+not|does\s+not|did\s+not|don't|doesn't|cannot|can't|"
    r"may\s+not|will\s+not|must\s+not|should\s+not)\b"
)
NEGATED_ELLIPTICAL_BASE_RE = re.compile(
    r"^(?:change|grant|switch|prove|establish|confirm|guarantee|perform|"
    r"bypass|authorize|allow|require|rely|use|attempt|carry|inherit|"
    r"qualify|reason|fallback)\b"
)
NEGATED_CLAIM_RE = re.compile(r"\b(?:do|does|did)\s+not\s+claim\s+that\b")
SENSITIVE_ELLIPSIS_START_RE = re.compile(
    r"^(?:they|it|those|these|that|this(?:\s+skill)?|"
    r"such\s+(?:tasks?|outcomes?)|"
    r"(?:the\s+)?(?:probe|manifest)|"
    r"(?:content|tool|task|timeout|unknown)(?:\s+\w+){0,2})\b"
)
SENSITIVE_ELLIPSIS_WORD_RE = re.compile(
    r"\b(?:do|does|did|can|could|may|might|will|would|qualif\w*|"
    r"carr\w*|rely|relies|inherit|inherits|confer|confers)\b"
)
SENSITIVE_ELLIPSIS_AUXILIARY_RE = re.compile(r"\b(?:do|does|did)\b")
SENSITIVE_ELLIPSIS_PROTECTED_RE: dict[str, re.Pattern[str]] = {
    "App task authorization/opt-in policy is ambiguous or unsafe": re.compile(
        r"\b(?:authori[sz](?:e|ed|es|ing)?|accept\w*|require\w*|need\w*|creat\w*|"
        r"default|current[-\s]+request|no|prior|previous|earlier|"
        r"suffic\w*|reason\w*|"
        r"qualif\w*|allow\w*|permit\w*|grant\w*|carried?|carry|"
        r"forward|inherit\w*|confer\w*|rely|relies|implicit|implied|"
        r"opt[-\s]?(?:in|out))\b"
    ),
    "Failure-to-Terra/fallback policy is ambiguous or unsafe": re.compile(
        r"\b(?:trigger\w*|terra|fallback|attempt\w*|authori[sz]\w*|"
        r"suffic\w*|reason\w*|qualif\w*|allow\w*|permit\w*|"
        r"permitted|allowed)\b"
    ),
    "Offline-to-runtime/native conformance policy is ambiguous or unsafe": re.compile(
        r"\b(?:proof|prove\w*|establish\w*|confirm\w*|guarantee\w*|"
        r"proven|established|confirmed|guaranteed)\b"
    ),
    "Skill authority over model/permissions/CLI policy is ambiguous or unsafe": re.compile(
        r"\b(?:parent\s+model|permission\w*|availability|automatic\s+cli|"
        r"cli\s+(?:routing|fallback)|switch\w*|change\w*|grant\w*|"
        r"confer\w*|bypass\w*)\b"
    ),
    "Probe/manifest/App evidence for effective route is ambiguous or unsafe": re.compile(
        r"\b(?:demonstrat\w*|prove\w*|establish\w*|confirm\w*|"
        r"guarantee\w*|proven|established|confirmed|guaranteed|"
        r"effective[-\s]+(?:native[-\s]+)?route)\b"
    ),
}


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
            re.compile(r"\bapp(?:\s+user-visible)?\s+tasks?\s+(?:cannot|can't|must\s+not|should\s+not|may\s+not)\s+require\s+(?:an?\s+)?explicit\s+(?:current[-\s]+request\s+)?authori[sz]ation\b"),
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
            re.compile(r"\bapp(?:\s+user-visible)?\s+tasks?\b[^.!?;:]{0,35}\baccept\s+neither\s+(?:the\s+)?(?:prior|previous|earlier|past)\s+(?:request\s+)?authori[sz]ation\s+nor\s+(?:implicit|implied)\s+consent\b"),
            re.compile(r"\bapp(?:\s+user-visible)?\s+tasks?\b[^.!?;:]{0,35}\baccept\s+no\s+(?:the\s+)?(?:prior|previous|earlier|past)\s+(?:request\s+)?authori[sz]ation\b"),
            re.compile(r"\bapp(?:\s+user-visible)?\s+tasks?\b[^.!?;:]{0,40}\b(?:do\s+not|don't|never|cannot|can't|may\s+not|must\s+not|should\s+not)\s+accept\b[^.!?;:]{0,50}\b(?:prior|previous|earlier|past)\s+(?:request\s+)?authori[sz]ation\b"),
            re.compile(r"\bapp(?:\s+user-visible)?\s+tasks?\b[^.!?;:]{0,40}\b(?:do\s+not|don't|never|cannot|can't|may\s+not|must\s+not|should\s+not)\s+accept\b[^.!?;:]{0,50}\b(?:implicit|implied)\s+consent\b"),
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
            re.compile(rf"\bno\s+{FAILURE_SOURCE}\s+(?:(?:may|can|could|will)\s+)?{ROUTING_ACTION}\s+{ROUTING_TARGET}\b"),
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
            re.compile(rf"\bneither\b[^.!?;:]{{0,120}}(?:prove|proves|proven|establish|establishes|established|demonstrate|demonstrates|demonstrated|confirm|confirms|confirmed)\s+{EFFECTIVE_ROUTE}\b"),
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


# The Skill contract uses a deliberately controlled semantic vocabulary.  A
# sensitive clause that mentions one of these subject/action groups is legal
# only when it contains an explicit prohibition/negation or an approved
# positive form.  Unknown affirmative and modal wording fails closed; this is
# intentionally bounded policy, not general natural-language inference.
SENSITIVE_NEGATION_RE = re.compile(
    r"\b(?:no|neither|nor|not|never|cannot|can't|may\s+not|will\s+not|"
    r"does\s+not|doesn't|do\s+not|don't|must\s+not|should\s+not)\b|"
    r"(?:不是|不得|不把|不可|不能|不会|没有|除非)"
)
DOUBLE_NEGATION_RE = re.compile(
    r"\b(?:do\s+not|does\s+not|did\s+not|doesn't|don't|never|not|cannot|can't|"
    r"may\s+not|will\s+not|must\s+not|should\s+not)\b"
    r"[^.!?;:]{0,48}\b(?:do\s+not|does\s+not|did\s+not|doesn't|don't|never|not|"
    r"cannot|can't|may\s+not|will\s+not|must\s+not|should\s+not)\b"
    r"[^.!?;:]{0,32}\b(?:authorize|authorizes|allow|allows|change|changes|switch|"
    r"switches|grant|grants|prove|proves|establish|establishes|confirm|confirms|"
    r"guarantee|guarantees|rely|relies|use|uses|attempt|attempts)\b"
)
APP_UNSAFE_ELLIPSIS_RE = re.compile(
    r"\b(?:require\w*|need\w*)\s+(?:no\s+)?"
    r"(?:current[-\s]+request\s+)?authori[sz]\w*\b|"
    r"\baccept\w*\s+(?:the\s+)?(?:prior|previous|earlier|past)\s+"
    r"(?:user\s+)?request\s+authori[sz]\w*\b"
)
APP_LEGAL_ACCEPT_NEGATION_RE = re.compile(
    r"\bapp(?:\s+user-visible)?\s+tasks?\b[^.!?;:]{0,40}\b"
    r"(?:do\s+not|don't|never|cannot|can't|may\s+not|must\s+not|should\s+not)\s+"
    r"accept\b[^.!?;:]{0,50}\b(?:prior|previous|earlier|past)\s+"
    r"(?:request\s+)?authori[sz]ation\b|"
    r"\bapp(?:\s+user-visible)?\s+tasks?\b[^.!?;:]{0,40}\b"
    r"(?:do\s+not|don't|never|cannot|can't|may\s+not|must\s+not|should\s+not)\s+"
    r"accept\b[^.!?;:]{0,50}\b(?:implicit|implied)\s+consent\b"
    r"|\bapp(?:\s+user-visible)?\s+tasks?\b[^.!?;:]{0,35}\baccept\s+neither\s+"
    r"(?:the\s+)?(?:prior|previous|earlier|past)\s+(?:request\s+)?authori[sz]ation\s+nor\s+"
    r"(?:implicit|implied)\s+consent\b"
    r"|\bapp(?:\s+user-visible)?\s+tasks?\b[^.!?;:]{0,35}\baccept\s+no\s+"
    r"(?:the\s+)?(?:prior|previous|earlier|past)\s+(?:request\s+)?authori[sz]ation\b"
)
APP_UNSAFE_REQUIRE_NEGATION_RE = re.compile(
    r"\bapp(?:\s+user-visible)?\s+tasks?\b[^.!?;:]{0,35}\b"
    r"(?:cannot|can't|must\s+not|should\s+not|may\s+not)\s+require\b"
    r"[^.!?;:]{0,50}\b(?:an?\s+)?explicit\s+(?:current[-\s]+request\s+)?"
    r"authori[sz]ation\b"
)


class _SensitiveContractPolicy(NamedTuple):
    label: str
    subject: re.Pattern[str]
    action: re.Pattern[str]
    approved_positive: tuple[re.Pattern[str], ...] = ()


SENSITIVE_CONTRACT_POLICIES: tuple[_SensitiveContractPolicy, ...] = (
    _SensitiveContractPolicy(
        "App task authorization/opt-in policy is ambiguous or unsafe",
        re.compile(r"\bapp(?:\s+user-visible)?\s+tasks?\b|\bcreate\s+an?\s+app(?:\s+user-visible)?\s+task\b"),
        re.compile(
            r"\b(?:authori[sz]|consent|opt[-\s]?(?:in|out)|prior|previous|earlier|past|"
            r"carried|carry|forward|inherit|confer|implicit|implied|rely|suffic|enough|optional|required|omit|default|"
            r"create|created|creation)\w*\b"
        ),
        (
            re.compile(
                r"\b(?:create|creating)\s+an?\s+app(?:\s+user-visible)?\s+task\b"
                r"[^.!?;:]{0,100}\bonly\s+(?:after|when)\s+(?:the\s+)?(?:user\s+)?"
                r"(?:explicit(?:ly)?\s+)?authori[sz](?:e|ed|ation)\b[^.!?;:]{0,60}"
                r"\bcurrent(?:[-\s]+user)?[-\s]+request\b"
            ),
            re.compile(
                r"\bapp(?:\s+user-visible)?\s+tasks?\b[^.!?;:]{0,100}"
                r"\brequire(?:s)?\s+(?:an?\s+)?explicit\s+"
                r"(?:current[-\s]+request\s+)?authori[sz]ation\b"
            ),
            re.compile(r"\bapp(?:\s+user-visible)?\s+tasks?\b[^.!?;:]{0,80}\bexplicit\s+opt[-\s]?in\b"),
            re.compile(r"\bonly\s+when\s+(?:the\s+)?user\s+(?:explicitly\s+)?authori[sz]es?\b"),
        ),
    ),
    _SensitiveContractPolicy(
        "Failure-to-Terra/fallback policy is ambiguous or unsafe",
        re.compile(
            r"\b(?:content|tool|task)(?:\s+\w+){0,2}\s+"
            r"(?:failure|failures|fail|fails|failed|error|errors|outcome|outcomes)\b|"
            r"\btimeout\b|\bunknown(?:[-\s]+(?:exception|failure|error|outcome))s?\b"
        ),
        re.compile(r"\b(?:terra|fallback|attempt|authorize|use|suffic|enough|reason|qualif)\w*\b"),
    ),
    _SensitiveContractPolicy(
        "Offline-to-runtime/native conformance policy is ambiguous or unsafe",
        re.compile(r"\boffline\s+(?:validation|checks?|validator)\b"),
        re.compile(
            r"\b(?:live|native|runtime|conformance|behavior|behaviour|proof|prove|proven|"
            r"establish|establishes|established|confirm|confirms|confirmed|guarantee|guarantees)\w*\b"
        ),
    ),
    _SensitiveContractPolicy(
        "Skill authority over model/permissions/CLI policy is ambiguous or unsafe",
        re.compile(r"\b(?:this\s+)?skill\b"),
        re.compile(
            r"\b(?:parent\s+model|permissions?|permission|model\s+availability|availability|"
            r"automatic\s+cli|cli\s+(?:routing|fallback)|model\s+switch(?:ing)?|"
            r"switch(?:es|ed)?|grant(?:s|ed)?|confer(?:s|red)?|bypass(?:es|ed)?)\b"
        ),
    ),
    _SensitiveContractPolicy(
        "Probe/manifest/App evidence for effective route is ambiguous or unsafe",
        re.compile(r"\b(?:probe|probes|installation\s+manifest|manifest|app\s+tasks?)\b"),
        re.compile(
            r"\b(?:infer|inferred|proof|prove|proven|establish|establishes|"
            r"established|confirm|confirms|confirmed|guarantee|guarantees)\w*\b"
        ),
    ),
)


def _is_sensitive_ellipsis(fragment: str, policy: _SensitiveContractPolicy) -> bool:
    """Recognize one bounded auxiliary/pronoun continuation in a policy group."""

    if SENSITIVE_ELLIPSIS_START_RE.match(fragment) is None:
        return False
    protected = SENSITIVE_ELLIPSIS_PROTECTED_RE.get(policy.label)
    has_protected_predicate = protected is not None and protected.search(fragment) is not None
    if has_protected_predicate:
        return True
    if SENSITIVE_ELLIPSIS_WORD_RE.search(fragment) is None:
        return False
    has_policy_subject = policy.subject.search(fragment) is not None
    return has_policy_subject and SENSITIVE_ELLIPSIS_AUXILIARY_RE.search(fragment) is not None


def _last_policy_action(clause: str, policy: _SensitiveContractPolicy) -> str | None:
    matches = [match.group(0) for match in policy.action.finditer(clause)]
    return matches[-1] if matches else None


def _inherited_sensitive_fragments(
    clause: str,
    previous_clause: str | None,
    policy: _SensitiveContractPolicy,
) -> list[str]:
    if previous_clause is None or not _is_sensitive_ellipsis(clause, policy):
        return []
    subjects = list(policy.subject.finditer(previous_clause))
    action = _last_policy_action(previous_clause, policy)
    if not subjects or action is None:
        return []
    return [f"{subject.group(0)} {clause} {action}" for subject in subjects[-2:]]


def _contract_sensitive_fragments(
    clause: str,
    policy: _SensitiveContractPolicy,
    previous_clause: str | None = None,
) -> list[str]:
    """Return connector-local fragments with immediate subject carry-over.

    The Skill contract uses a small controlled vocabulary.  Coordinated
    pronouns and elliptical predicates are therefore expanded only from a
    sensitive subject immediately to their left; an earlier legal fragment
    never immunizes the coordinated fragment that follows it.
    """

    fragments = [clause]
    fragments.extend(_inherited_sensitive_fragments(clause, previous_clause, policy))

    # Consume connector spans once and inspect only the adjacent segment.
    # Keeping spans, subjects, actions, and negation matches avoids rescanning
    # every growing prefix/suffix for long comma-and connector chains.
    boundaries = list(SENSITIVE_CONNECTOR_RE.finditer(clause))
    subjects = list(policy.subject.finditer(clause))
    actions = list(policy.action.finditer(clause))
    negations = list(GOVERNING_MODAL_NEGATION_RE.finditer(clause))
    negated_claims = list(NEGATED_CLAIM_RE.finditer(clause))
    subject_index = 0
    action_index = 0
    negation_index = 0
    claim_index = 0
    recent_subjects: list[re.Match[str]] = []
    last_action: str | None = None
    has_left_negation = False
    has_left_negated_claim = False

    for boundary_index, boundary in enumerate(boundaries):
        boundary_start = boundary.start()
        while subject_index < len(subjects) and subjects[subject_index].start() < boundary_start:
            recent_subjects.append(subjects[subject_index])
            recent_subjects = recent_subjects[-2:]
            subject_index += 1
        while action_index < len(actions) and actions[action_index].end() <= boundary_start:
            last_action = actions[action_index].group(0)
            action_index += 1
        while negation_index < len(negations) and negations[negation_index].end() <= boundary_start:
            has_left_negation = True
            negation_index += 1
        while claim_index < len(negated_claims) and negated_claims[claim_index].end() <= boundary_start:
            has_left_negated_claim = True
            claim_index += 1

        right_start = boundary.end()
        right_end = (
            boundaries[boundary_index + 1].start()
            if boundary_index + 1 < len(boundaries)
            else len(clause)
        )
        right = clause[right_start:right_end].strip()
        if not right:
            continue
        fragments.append(right)
        predicate_start = SENSITIVE_PREDICATE_START_RE.match(right) is not None
        if not recent_subjects or (
            policy.action.search(right) is None
            and not _is_sensitive_ellipsis(right, policy)
            and not predicate_start
        ):
            continue
        if not predicate_start and (
            SENSITIVE_SUBJECT_START_RE.match(right) is None
            and SENSITIVE_ELLIPSIS_START_RE.match(right) is None
        ):
            continue
        connector = boundary.group(0).strip().casefold()
        if (
            connector in {"or", ","}
            and has_left_negation
            and SENSITIVE_PREDICATE_START_RE.match(right) is not None
            and (
                NEGATED_ELLIPTICAL_BASE_RE.match(right) is not None
                or has_left_negated_claim
            )
        ):
            for subject in recent_subjects:
                fragments.append(f"{subject.group(0)} does not {right}")
            continue
        for subject in recent_subjects:
            if policy.action.search(right) is None and last_action is not None:
                fragments.append(f"{subject.group(0)} {right} {last_action}")
            else:
                fragments.append(f"{subject.group(0)} {right}")
    return fragments


def _sensitive_clause_is_legal(fragment: str, policy: _SensitiveContractPolicy) -> bool:
    local_fragments = re.split(
        r"\b(?:and|nor|but|however|although|while|whereas|though|"
        r"nevertheless|nonetheless)\b",
        fragment,
    )
    if any(DOUBLE_NEGATION_RE.search(local) is not None for local in local_fragments):
        return False
    if (
        policy.label == "App task authorization/opt-in policy is ambiguous or unsafe"
        and APP_UNSAFE_REQUIRE_NEGATION_RE.search(fragment) is not None
    ):
        return False
    if (
        policy.label == "App task authorization/opt-in policy is ambiguous or unsafe"
        and APP_LEGAL_ACCEPT_NEGATION_RE.search(fragment) is not None
    ):
        return True
    if (
        policy.label == "App task authorization/opt-in policy is ambiguous or unsafe"
        and APP_UNSAFE_ELLIPSIS_RE.search(fragment) is not None
    ):
        return False
    if SENSITIVE_NEGATION_RE.search(fragment) is not None:
        return True
    return any(pattern.search(fragment) is not None for pattern in policy.approved_positive)


def _mask_contract_rendered_text(text: str) -> str:
    """Return one rendered-text view for all semantic contract checks.

    Valid fenced code, inline code, and HTML comments are non-rendered for
    this controlled dialect.  Delimiters are recognized only with even
    backslash parity, so an escaped delimiter cannot hide visible prose.
    """

    lines, _ = _unfenced_lines(text)
    rendered = "\n".join(lines)
    escaped = _escaped_character_flags(rendered)
    output: list[str] = []
    index = 0
    inline_code_length: int | None = None
    comment_active = False

    while index < len(rendered):
        if comment_active:
            close = rendered.find("-->", index)
            if close < 0:
                output.extend(" " for _ in rendered[index:])
                break
            output.extend(" " for _ in rendered[index : close + 3])
            index = close + 3
            comment_active = False
            continue

        if inline_code_length is not None:
            delimiter = "`" * inline_code_length
            if rendered.startswith(delimiter, index) and not escaped[index]:
                output.extend(" " for _ in delimiter)
                index += inline_code_length
                inline_code_length = None
            else:
                output.append(" ")
                index += 1
            continue

        if rendered.startswith("<!--", index) and not escaped[index]:
            output.extend(" " for _ in "<!--")
            index += 4
            comment_active = True
            continue

        if rendered[index] == "`" and not escaped[index]:
            run_end = index + 1
            while run_end < len(rendered) and rendered[run_end] == "`":
                run_end += 1
            inline_code_length = run_end - index
            output.extend(" " for _ in rendered[index:run_end])
            index = run_end
            continue

        output.append(rendered[index])
        index += 1
    return "".join(output)


def _strip_inline_code_for_contract(text: str) -> str:
    """Compatibility wrapper for the shared rendered-text masking path."""

    return _mask_contract_rendered_text(text)


def sensitive_contract_violations(texts: tuple[str, ...]) -> list[str]:
    """Fail closed for unknown affirmative/modal clauses in protected groups."""

    violations: list[str] = []
    for text in texts:
        rendered_text = _mask_contract_rendered_text(text)
        paragraphs = re.split(r"\n[ \t]*\n", rendered_text)
        for paragraph in paragraphs:
            clauses = _contract_clauses(paragraph)
            for index, clause in enumerate(clauses):
                previous_clause = clauses[index - 1] if index else None
                for policy in SENSITIVE_CONTRACT_POLICIES:
                    for fragment in _contract_sensitive_fragments(
                        clause, policy, previous_clause
                    ):
                        if policy.subject.search(fragment) and policy.action.search(fragment):
                            if not _sensitive_clause_is_legal(fragment, policy):
                                if policy.label not in violations:
                                    violations.append(policy.label)
                                break
                    if policy.label in violations:
                        break
    return violations
REQUIRED_CONTRACT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "App task must require explicit current-request authorization",
        re.compile(
            r"\bcreate\s+an?\s+app(?:\s+user-visible)?\s+task\b.{0,80}\bonly\s+after\s+explicit\s+authori[sz]ation\s+in\s+the\s+current\s+user\s+request\b"
        ),
    ),
)


def _decode_percent_escapes(text: str) -> str:
    decoded = text
    for _ in range(4):
        next_value = unquote(decoded)
        if next_value == decoded:
            return decoded
        decoded = next_value
    return decoded


def _normalize_markdown_target_details(
    raw_target: str,
) -> tuple[str | None, str | None]:
    target = _decode_html_entities(raw_target.strip())
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    target = _decode_percent_escapes(target)
    if not target or target.startswith("//") or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
        return None, None
    target = re.split(r"[?#]", target, maxsplit=1)[0]
    while target.startswith("./"):
        target = target[2:]
    if not target:
        return None, None

    had_trailing_separator = target.endswith("/")
    normalized = posixpath.normpath(target)
    if normalized in {"", "."}:
        return None, "empty local Markdown destination"

    # Normalize dot segments before topology classification, but preserve the
    # evidence that a Markdown file-shaped path was followed by another path
    # separator or component.  Such a target must not masquerade as an exact
    # first-level sibling file.
    path_casefold = target.casefold()
    invalid_file_shape = (
        ".md/" in path_casefold
        or (had_trailing_separator and normalized.casefold().endswith(".md"))
    )
    diagnostic = (
        "local Markdown destination has a file-shaped path suffix or trailing separator"
        if invalid_file_shape
        else None
    )
    return normalized, diagnostic


def _normalize_markdown_target(raw_target: str) -> str | None:
    target, _ = _normalize_markdown_target_details(raw_target)
    return target


def _normalize_reference_label(label: str) -> str:
    return re.sub(r"\s+", " ", label.casefold().strip())


def _decode_html_entities(text: str) -> str:
    """Decode nested HTML character references in a bounded deterministic pass."""

    decoded = text
    for _ in range(4):
        next_value = html.unescape(decoded)
        if next_value == decoded:
            return decoded
        decoded = next_value
    return decoded


def _raw_html_diagnostics(line: str) -> list[str]:
    diagnostics: list[str] = []
    if RAW_HTML_LINK_TAG_RE.search(line):
        diagnostics.append("raw HTML link tag is outside the controlled Markdown dialect")
    if RAW_HTML_HEADING_TAG_RE.search(line):
        diagnostics.append("raw HTML heading tag is outside the controlled Markdown dialect")
    return diagnostics


def _raw_html_pending_prefix(line: str) -> str | None:
    """Return a relevant raw-HTML opener that continues past this line."""

    for match in RAW_HTML_TAG_PREFIX_RE.finditer(line):
        if ">" not in line[match.start() :]:
            return line[match.start() :]
    return None


def _mask_raw_html_ignored_line(
    line: str,
    inline_code_length: int | None,
    comment_active: bool,
) -> tuple[str, int | None, bool]:
    """Mask inline code, comments, and escaped ``<`` before raw-tag checks."""

    escaped = _escaped_character_flags(line)
    masked: list[str] = []
    index = 0
    while index < len(line):
        if comment_active:
            close = line.find("-->", index)
            if close < 0:
                masked.extend(" " for _ in line[index:])
                return "".join(masked), inline_code_length, True
            masked.extend(" " for _ in line[index : close + 3])
            index = close + 3
            comment_active = False
            continue
        if inline_code_length is not None:
            run = "`" * inline_code_length
            if line.startswith(run, index) and not escaped[index]:
                masked.extend(" " for _ in run)
                index += inline_code_length
                inline_code_length = None
            else:
                masked.append(" ")
                index += 1
            continue
        if line.startswith("<!--", index) and not escaped[index]:
            masked.extend(" " for _ in "<!--")
            index += 4
            comment_active = True
            continue
        if line[index] == "`" and not escaped[index]:
            run_end = index + 1
            while run_end < len(line) and line[run_end] == "`":
                run_end += 1
            inline_code_length = run_end - index
            masked.extend(" " for _ in line[index:run_end])
            index = run_end
            continue
        if line[index] == "<" and escaped[index]:
            masked.append(" ")
        else:
            masked.append(line[index])
        index += 1
    return "".join(masked), inline_code_length, comment_active


def _raw_html_diagnostics_for_rendered_lines(lines: list[str]) -> list[str]:
    """Detect same-line and soft-break raw HTML, ignoring rendered code blocks."""

    diagnostics: list[str] = []
    fence_char: str | None = None
    fence_length = 0
    pending: str | None = None
    inline_code_length: int | None = None
    comment_active = False

    def add_all(items: list[str]) -> None:
        for item in items:
            if item not in diagnostics:
                diagnostics.append(item)

    for line in lines:
        if fence_char is not None:
            pending = None
            if _fence_closes(line, fence_char, fence_length):
                fence_char = None
                fence_length = 0
                inline_code_length = None
                comment_active = False
            continue
        marker = _line_fence_marker(line)
        if marker is not None:
            pending = None
            fence_char, fence_length = marker
            inline_code_length = None
            comment_active = False
            continue
        if _is_rendered_indented_code_line(line) and pending is None:
            # Inline-code/comment state inside an indented code block cannot
            # leak into the following rendered paragraph.
            inline_code_length = None
            comment_active = False
            continue
        masked, inline_code_length, comment_active = _mask_raw_html_ignored_line(
            line, inline_code_length, comment_active
        )
        if pending is not None:
            combined = pending + "\n" + masked
            add_all(_raw_html_diagnostics(combined))
            pending = _raw_html_pending_prefix(combined)
            continue
        add_all(_raw_html_diagnostics(masked))
        pending = _raw_html_pending_prefix(masked)

    if pending is not None:
        if re.match(r"<\s*/?\s*a\b", pending, re.IGNORECASE):
            diagnostics.append("unterminated raw HTML link tag opener")
        else:
            diagnostics.append("unterminated raw HTML heading tag opener")
    if fence_char is not None:
        diagnostics.append("raw HTML scan encountered an unclosed fenced code block")
    return diagnostics


def _fence_marker_details(line: str) -> tuple[str, int, int] | None:
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
    return marker, end - indent, end


def _invalid_backtick_fence_opener(line: str) -> bool:
    details = _fence_marker_details(line)
    return details is not None and details[0] == "`" and "`" in line[details[2] :]


def _line_fence_marker(line: str) -> tuple[str, int] | None:
    """Return a valid fence marker; backtick info strings cannot contain backticks."""

    if _invalid_backtick_fence_opener(line):
        return None
    details = _fence_marker_details(line)
    return None if details is None else details[:2]


def _fence_closes(line: str, active_char: str, active_length: int) -> bool:
    details = _fence_marker_details(line)
    if details is None:
        return False
    marker, length, end = details
    return marker == active_char and length >= active_length and not line[end:].strip()


def _is_indented_code_line(line: str) -> bool:
    return line.startswith("\t") or line.startswith("    ")


class _RenderedLine(str):
    """A normalized line carrying shared rendered/code classification bits."""

    def __new__(
        cls,
        value: str,
        *,
        paragraph_continuation: bool = False,
        indented_code: bool = False,
    ):
        instance = str.__new__(cls, value)
        instance.paragraph_continuation = paragraph_continuation
        instance.indented_code = indented_code
        return instance


def _is_rendered_indented_code_line(line: str) -> bool:
    if getattr(line, "indented_code", False):
        return True
    return _is_indented_code_line(line) and not getattr(line, "paragraph_continuation", False)


LIST_ITEM_RE = re.compile(r"^( {0,3})(?:[-+*]|[0-9]{1,9}[.)])[ \t]{1,4}(.*)$")
LIST_ITEM_FULL_RE = re.compile(r"^( *)([-+*]|[0-9]{1,9}[.)])([ \t]{1,4})(.*)$")
INVALID_LIST_SPACING_RE = re.compile(r"^ *(?:[-+*]|[0-9]{1,9}[.)])[ \t]{5,}")
LONG_ORDERED_MARKER_RE = re.compile(r"^ *[0-9]{10,}[.)][ \t]+")
MAX_CONTAINER_PREFIX_DEPTH = 16


def _container_prefixes_remain(line: str) -> bool:
    return (
        re.match(r"^ {0,3}>[ \t]?", line) is not None
        or LIST_ITEM_RE.match(line) is not None
    )


def _peel_container_prefixes_details(line: str) -> tuple[str, int | None, int, bool]:
    """Peel bounded CommonMark container prefixes and report depth exhaustion."""

    current = line
    first_list_indent: int | None = None
    list_count = 0
    for _ in range(MAX_CONTAINER_PREFIX_DEPTH):
        blockquote = re.match(r"^ {0,3}>[ \t]?", current)
        if blockquote is not None:
            current = current[blockquote.end() :]
            continue
        list_match = LIST_ITEM_RE.match(current)
        if list_match is not None:
            if first_list_indent is None:
                first_list_indent = len(list_match.group(1))
            list_count += 1
            current = list_match.group(2)
            continue
        break
    return current, first_list_indent, list_count, _container_prefixes_remain(current)


def _container_normalized_lines(text: str) -> list[str]:
    """Normalize a conservative blockquote/list container subset.

    Four-space and tab indentation remains code at the document root.  Once a
    list item is seen, one bounded continuation indentation level is rendered
    as that item's content so the link scanner and task-heading validator use
    the same container interpretation.
    """

    normalized, _ = _container_normalized_lines_with_diagnostics(text)
    return normalized


def _container_normalized_lines_with_diagnostics(text: str) -> tuple[list[str], list[str]]:
    """Normalize containers using each marker's actual content-start column."""

    normalized: list[str] = []
    diagnostics: list[str] = []
    # Entries are (marker-start column, content-start column, paragraph-open).
    # Keeping the open-paragraph bit with each item prevents a blank-separated
    # code block from borrowing the state of a sibling container.
    list_stack: list[tuple[int, int, bool]] = []

    list_blank_pending = False
    lazy_continuation_active = False
    paragraph_active = False
    root_indented_code_active = False
    for raw_line in text.splitlines():
        _, _, _, depth_exhausted = _peel_container_prefixes_details(raw_line)
        if depth_exhausted:
            diagnostics.append("container prefix depth exceeded in Markdown line")

        line, blockquote_count = _strip_blockquote_prefixes(raw_line)
        if INVALID_LIST_SPACING_RE.match(line):
            diagnostics.append("list marker has more than four spaces after its marker")
            normalized.append("    " + line.lstrip())
            list_stack = []
            paragraph_active = False
            continue
        if LONG_ORDERED_MARKER_RE.match(line):
            diagnostics.append("ordered list marker has more than nine digits")

        list_match = LIST_ITEM_FULL_RE.match(line)
        if list_match is not None and _accept_list_marker(
            len(list_match.group(1)),
            list_match.group(2),
            list_stack,
            diagnostics,
            paragraph_active,
        ):
            marker_start = len(list_match.group(1))
            content_start = list_match.start(4)
            while list_stack and list_stack[-1][0] > marker_start:
                list_stack.pop()
            if list_stack and list_stack[-1][0] == marker_start:
                list_stack.pop()
            content, _, _, content_exhausted = _peel_container_prefixes_details(
                list_match.group(4)
            )
            if content_exhausted:
                diagnostics.append("container prefix depth exceeded in Markdown line")
            paragraph_open = bool(content.strip()) and not _is_block_boundary_line(content)
            if LIST_ITEM_RE.match(content) is not None:
                paragraph_open = False
            list_stack.append((marker_start, content_start, paragraph_open))
            normalized.append(content)
            lazy_continuation_active = False
            paragraph_active = False
            root_indented_code_active = False
            continue

        if not line.strip():
            normalized.append(line)
            list_blank_pending = bool(list_stack)
            if not list_stack:
                paragraph_active = False
            continue

        if _is_block_boundary_line(line):
            list_stack = []
            list_blank_pending = False
            lazy_continuation_active = False
            normalized.append(line)
            paragraph_active = False
            root_indented_code_active = False
            continue

        leading_spaces = len(line) - len(line.lstrip(" "))
        candidate_index = -1
        if list_stack:
            if line.startswith("\t"):
                candidate_index = len(list_stack) - 1
                candidate_indent = list_stack[candidate_index][1]
            else:
                candidate_index = max(
                    (
                        index
                        for index, (_, content_start, _) in enumerate(list_stack)
                        if leading_spaces >= content_start
                    ),
                    default=-1,
                )
                candidate_indent = (
                    list_stack[candidate_index][1] if candidate_index >= 0 else -1
                )
            if candidate_index >= 0:
                if lazy_continuation_active:
                    diagnostics.append(
                        "ambiguous lazy list continuation before indented content"
                    )
                    lazy_continuation_active = False
                candidate = line[1:] if line.startswith("\t") else line[candidate_indent:]
                if INVALID_LIST_SPACING_RE.match(candidate):
                    diagnostics.append("list marker has more than four spaces after its marker")
                    normalized.append("    " + candidate.lstrip())
                    list_stack = list_stack[: candidate_index + 1]
                    paragraph_active = False
                    continue
                candidate_leading = len(candidate) - len(candidate.lstrip(" "))
                item_paragraph_open = list_stack[candidate_index][2]
                if (
                    candidate_leading >= 4
                    and item_paragraph_open
                    and not list_blank_pending
                    and not lazy_continuation_active
                ):
                    # An open list paragraph keeps its continuation rendered,
                    # even at six source-column spaces.  Mark it once so
                    # heading validation does not mistake paragraph text for
                    # an ATX heading.
                    list_stack = list_stack[: candidate_index + 1]
                    normalized.append(
                        _RenderedLine(
                            candidate.lstrip(" \t"), paragraph_continuation=True
                        )
                    )
                    list_blank_pending = False
                    paragraph_active = True
                    root_indented_code_active = False
                    continue
                if candidate.startswith("\t") or candidate_leading >= 4:
                    # Four spaces beyond a list item's content start are an
                    # indented code block.  Keep the source text and mark it
                    # once so scanner, semantic masking, raw HTML, and task
                    # headings all ignore the same rendered line.
                    list_stack = list_stack[: candidate_index + 1]
                    normalized.append(
                        _RenderedLine(candidate, indented_code=True)
                    )
                    list_blank_pending = False
                    paragraph_active = False
                    continue
                content, _, _, content_exhausted = _peel_container_prefixes_details(candidate)
                if content_exhausted:
                    diagnostics.append("container prefix depth exceeded in Markdown line")
                list_stack = list_stack[: candidate_index + 1]
                normalized.append(content)
                list_blank_pending = False
                paragraph_active = False
                continue
            if leading_spaces and blockquote_count == 0:
                diagnostics.append("ambiguous list continuation indentation")
                list_stack = []
                list_blank_pending = False
                lazy_continuation_active = False
            elif blockquote_count == 0:
                # CommonMark permits a lazy paragraph continuation without
                # repeating the list marker.  Preserve the stack so a later
                # indented link/heading is not silently reclassified as root
                # code.  If the continuation follows a blank, the boundary
                # is ambiguous but still remains fail-closed via the shared
                # diagnostic path when a nested construct is encountered.
                if list_blank_pending:
                    # An unindented line after a blank starts a new root
                    # paragraph in this bounded dialect.  A directly
                    # indented line was handled above as list content.
                    list_stack = []
                    lazy_continuation_active = False
                    list_blank_pending = False
                else:
                    lazy_continuation_active = True
                    list_blank_pending = False
            else:
                list_stack = []
                list_blank_pending = False
                lazy_continuation_active = False

        # A blockquote is a rendered container even when it follows a list;
        # its own open paragraph likewise keeps an indented continuation
        # rendered, while a blank-separated continuation is code.
        if not list_stack and blockquote_count > 0:
            leading_spaces = len(line) - len(line.lstrip(" "))
            if line.startswith("\t") or leading_spaces >= 4:
                if paragraph_active and not root_indented_code_active:
                    normalized.append(
                        _RenderedLine(
                            line.lstrip(" \t"), paragraph_continuation=True
                        )
                    )
                    root_indented_code_active = False
                    paragraph_active = True
                else:
                    normalized.append(_RenderedLine(line, indented_code=True))
                    root_indented_code_active = True
                    paragraph_active = False
                list_blank_pending = False
                continue

        # At the document root, four-space and tab-indented lines remain code
        # unless the immediately preceding paragraph is still open.
        if not list_stack and blockquote_count == 0:
            leading_spaces = len(line) - len(line.lstrip(" "))
            if line.startswith("\t") or leading_spaces >= 4:
                if paragraph_active and not root_indented_code_active:
                    # An indented line cannot interrupt an open paragraph;
                    # preserve its rendered content for link/heading checks.
                    normalized.append(
                        _RenderedLine(
                            line.lstrip(" \t"), paragraph_continuation=True
                        )
                    )
                    root_indented_code_active = False
                    paragraph_active = True
                else:
                    # A blank-separated root indentation is a genuine code
                    # block.  The empty rendered line is shared by scanner,
                    # task headings, and both semantic validation passes.
                    normalized.append(_RenderedLine("", indented_code=True))
                    root_indented_code_active = True
                    paragraph_active = False
                list_blank_pending = False
                continue
        normalized.append(line)
        paragraph_active = True
        root_indented_code_active = False
        list_blank_pending = False
    return normalized, diagnostics


def _is_block_boundary_line(line: str) -> bool:
    return (
        ATX_TASK_HEADING_RE.match(line) is not None
        or _line_fence_marker(line) is not None
    )


def _strip_blockquote_prefixes(line: str) -> tuple[str, int]:
    current = line
    count = 0
    while count < MAX_CONTAINER_PREFIX_DEPTH:
        blockquote = re.match(r"^ {0,3}>[ \t]?", current)
        if blockquote is None:
            break
        current = current[blockquote.end() :]
        count += 1
    return current, count


def _accept_list_marker(
    marker_start: int,
    marker: str,
    list_stack: list[tuple[int, int, bool]],
    diagnostics: list[str],
    paragraph_active: bool,
) -> bool:
    if not list_stack:
        if marker[0].isdigit() and int(marker.rstrip(".)")) != 1 and paragraph_active:
            diagnostics.append("ordered list marker other than one cannot interrupt a paragraph")
            return False
        return marker_start <= 3
    parent_marker, parent_content, _ = list_stack[-1]
    if marker_start > parent_marker and marker_start < parent_content:
        diagnostics.append("ambiguous list marker indentation")
    return marker_start == 0 or marker_start >= parent_content


def _peel_container_prefixes(line: str) -> tuple[str, int | None]:
    """Peel bounded blockquote/list prefixes until the line reaches content."""

    current, first_list_indent, _, _ = _peel_container_prefixes_details(line)
    return current, first_list_indent


def _find_unescaped_character(text: str, start: int, character: str) -> int | None:
    escaped = False
    index = start
    while index < len(text):
        current = text[index]
        if current == character and not escaped:
            return index
        if current == "\\":
            escaped = not escaped
        else:
            escaped = False
        index += 1
    return None


def _balanced_parentheses(text: str) -> bool:
    depth = 0
    escaped = False
    for current in text:
        if escaped:
            escaped = False
            continue
        if current == "\\":
            escaped = True
            continue
        if current == "(":
            depth += 1
        elif current == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _destination_diagnostic(raw_target: str, kind: str) -> str | None:
    target = _decode_html_entities(raw_target.strip())
    if not target:
        return f"empty {kind} destination"
    if HTML_ENTITY_RE.search(target):
        return f"unresolved HTML entity in {kind} destination"
    if re.search(r"%(?![0-9a-fA-F]{2})", target):
        return f"invalid percent escape in {kind} destination"
    if target.startswith("<"):
        angle_close = _find_unescaped_character(target, 1, ">")
        if angle_close is None or angle_close != len(target) - 1:
            return f"unclosed angle bracket in {kind} destination"
        if any(character.isspace() for character in target[1:-1]):
            return f"whitespace-invalid {kind} destination"
        return None
    if any(character.isspace() for character in target):
        return f"whitespace-invalid {kind} destination"
    if not _balanced_parentheses(target):
        return f"unbalanced parentheses in {kind} destination"
    return None


def _inline_target_end(line: str, start: int) -> int | None:
    """Find a simple balanced inline destination close in one linear pass."""

    if start >= len(line):
        return None
    angle_target = line[start] == "<"
    angle_closed = not angle_target
    depth = 0
    escaped = False
    index = start
    while index < len(line):
        current = line[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if current == "\\":
            escaped = True
            index += 1
            continue
        if angle_target and not angle_closed:
            if current == ">":
                angle_closed = True
            index += 1
            continue
        if angle_target and angle_closed:
            if current == ")":
                return index
            index += 1
            continue
        if current == "(":
            depth += 1
        elif current == ")":
            if depth == 0:
                return index
            depth -= 1
        index += 1
    return None


def _parse_reference_definition(line: str) -> tuple[str, str] | None:
    indent = 0
    while indent < len(line) and indent < 3 and line[indent] == " ":
        indent += 1
    if indent >= len(line) or line[indent] != "[":
        return None
    close = _find_unescaped_character(line, indent + 1, "]")
    if close is None or close + 1 >= len(line) or line[close + 1] != ":":
        return None
    label = _normalize_reference_label(line[indent + 1 : close])
    target_start = close + 2
    while target_start < len(line) and line[target_start] in " \t":
        target_start += 1
    if target_start >= len(line):
        return None
    if line[target_start] == "<":
        target_end = _find_unescaped_character(line, target_start + 1, ">")
        if target_end is None:
            return None
        target = line[target_start : target_end + 1]
    else:
        target_end = target_start
        while target_end < len(line) and line[target_end] not in " \t":
            target_end += 1
        target = line[target_start:target_end]
    return (label, target) if label else None


def _reference_definition_diagnostic(line: str) -> str | None:
    indent = 0
    while indent < len(line) and indent < 3 and line[indent] == " ":
        indent += 1
    if indent >= len(line) or line[indent] != "[":
        return None
    close = _find_unescaped_character(line, indent + 1, "]")
    if close is None or close + 1 >= len(line) or line[close + 1] != ":":
        return None
    target_start = close + 2
    while target_start < len(line) and line[target_start] in " \t":
        target_start += 1
    if target_start >= len(line):
        return "empty reference definition destination"
    if line[target_start] == "<":
        target_end = _find_unescaped_character(line, target_start + 1, ">")
        if target_end is None:
            return "unclosed angle bracket in reference definition destination"
        remainder = line[target_end + 1 :].strip()
        if remainder:
            return "whitespace-invalid reference definition destination"
        return _destination_diagnostic(line[target_start : target_end + 1], "reference definition")
    target_end = target_start
    while target_end < len(line) and not line[target_end].isspace():
        target_end += 1
    target = line[target_start:target_end]
    if target_end < len(line) and line[target_end:].strip():
        return "whitespace-invalid reference definition destination"
    return _destination_diagnostic(target, "reference definition")


def _escaped_character_flags(text: str) -> list[bool]:
    """Return odd-backslash escape state for each character in one pass."""

    flags: list[bool] = []
    backslashes = 0
    for current in text:
        flags.append(backslashes % 2 == 1)
        if current == "\\":
            backslashes += 1
        else:
            backslashes = 0
    return flags


class _MarkdownScan(NamedTuple):
    targets: list[str]
    unresolved: list[str]
    diagnostics: list[str]


def _scan_rendered_markdown_details(text: str) -> _MarkdownScan:
    """Scan the bounded Markdown subset once, returning fail-closed diagnostics."""

    definitions: dict[str, str] = {}
    direct_targets: list[str] = []
    reference_usages: list[tuple[str, bool]] = []
    diagnostics: list[str] = []
    fence_marker: str | None = None
    fence_length = 0
    label_active = False
    label_buffer: list[str] = []
    label_is_image = False
    nested_label_reported = False

    lines, container_diagnostics = _container_normalized_lines_with_diagnostics(text)
    diagnostics.extend(container_diagnostics)
    diagnostics.extend(_raw_html_diagnostics_for_rendered_lines(lines))
    for line in lines:
        if fence_marker is not None:
            if label_active:
                diagnostics.append("link label crosses a fenced code block")
                label_active = False
                label_buffer = []
            if _fence_closes(line, fence_marker, fence_length):
                fence_marker = None
                fence_length = 0
            continue

        if _invalid_backtick_fence_opener(line):
            diagnostics.append("invalid backtick fence opener")
        marker = _line_fence_marker(line)
        if marker is not None:
            fence_marker, fence_length = marker
            continue

        if _is_rendered_indented_code_line(line):
            if label_active:
                diagnostics.append("link label crosses an indented code block")
                label_active = False
                label_buffer = []
            continue
        if not label_active:
            definition_diagnostic = _reference_definition_diagnostic(line)
            if definition_diagnostic is not None:
                diagnostics.append(definition_diagnostic)
                continue
            definition = _parse_reference_definition(line)
            if definition is not None:
                label, target = definition
                if label in definitions:
                    diagnostics.append(f"duplicate reference definition: {label}")
                else:
                    definitions[label] = target
                continue

        if not line:
            if label_active:
                diagnostics.append("link label crosses a blank line")
                label_active = False
                label_buffer = []
            continue

        escaped = _escaped_character_flags(line)
        i = 0
        while i < len(line):
            if line[i] == "`" and not escaped[i]:
                run_end = i + 1
                while run_end < len(line) and line[run_end] == "`":
                    run_end += 1
                run_length = run_end - i
                close = run_end
                backtick_run = "`" * run_length
                while close < len(line):
                    if line.startswith(backtick_run, close) and not escaped[close]:
                        break
                    close += 1
                if close >= len(line):
                    diagnostics.append("unclosed or unequal inline backtick run")
                    if label_active:
                        label_active = False
                        label_buffer = []
                    i = len(line)
                else:
                    if label_active:
                        diagnostics.append("inline code in link label is ambiguous")
                        label_active = False
                        label_buffer = []
                    i = close + run_length
                continue

            if line[i] == "[" and not label_active:
                if escaped[i]:
                    i += 1
                    continue
                label_active = True
                label_buffer = []
                nested_label_reported = False
                label_is_image = (
                    i > 0 and line[i - 1] == "!" and not escaped[i - 1]
                )
                i += 1
                continue

            if line[i] == "[" and label_active:
                if escaped[i]:
                    label_buffer.append(line[i])
                    i += 1
                    continue
                if not nested_label_reported:
                    diagnostics.append("nested bracket label is ambiguous")
                    nested_label_reported = True
                label_buffer.append(line[i])
                i += 1
                continue

            if line[i] == "]" and label_active:
                if escaped[i]:
                    label_buffer.append(line[i])
                    i += 1
                    continue
                label = "".join(label_buffer)
                next_index = i + 1
                while next_index < len(line) and line[next_index] in " \t":
                    next_index += 1
                consumed = i + 1
                if next_index < len(line) and line[next_index] == "(":
                    target_end = _inline_target_end(line, next_index + 1)
                    if target_end is None:
                        diagnostics.append("unclosed inline link target")
                        i = len(line)
                    else:
                        raw_target = line[next_index + 1 : target_end].strip()
                        destination_diagnostic = _destination_diagnostic(raw_target, "inline")
                        if destination_diagnostic is not None:
                            diagnostics.append(destination_diagnostic)
                        if not label_is_image:
                            if destination_diagnostic is None:
                                direct_targets.append(raw_target)
                        i = target_end + 1
                    label_active = False
                    label_buffer = []
                    continue
                if next_index < len(line) and line[next_index] == "[":
                    reference_end = _find_unescaped_character(line, next_index + 1, "]")
                    if reference_end is not None:
                        if not label_is_image:
                            reference_label = line[next_index + 1 : reference_end] or label
                            reference_usages.append((reference_label, True))
                        consumed = reference_end + 1
                    else:
                        diagnostics.append("unclosed reference label")
                elif not label_is_image and label:
                    reference_usages.append((label, False))
                label_active = False
                label_buffer = []
                i = consumed
                continue

            if label_active:
                label_buffer.append(line[i])
            i += 1

        if label_active:
            label_buffer.append("\n")

    if fence_marker is not None:
        diagnostics.append("unclosed fenced code block")
    if label_active:
        diagnostics.append("unclosed link label")

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
        target, target_diagnostic = _normalize_markdown_target_details(raw_target)
        if target_diagnostic is not None:
            diagnostics.append(target_diagnostic)
        if target is not None:
            targets.append(target)
    return _MarkdownScan(targets, unresolved, diagnostics)


def _scan_rendered_markdown(text: str) -> tuple[list[str], list[str]]:
    """Return rendered targets and unresolved explicit references."""

    scan = _scan_rendered_markdown_details(text)
    return scan.targets, scan.unresolved


def extract_local_markdown_targets(text: str) -> list[str]:
    """Extract normalized targets from rendered inline and reference-use links."""

    targets, _ = _scan_rendered_markdown(text)
    return targets


def _contract_rule_matches(
    clauses: list[str],
    positive_patterns: tuple[re.Pattern[str], ...],
    negative_patterns: tuple[re.Pattern[str], ...],
) -> bool:
    """Match a contradiction unless a negation overlaps that same match.

    Negative spans are merged once and queried by interval position.  This
    keeps a large clause with many legal guards and positive candidates out of
    the old positive-by-negative nested scan.
    """

    for clause in clauses:
        raw_negative_spans = [
            match.span()
            for pattern in negative_patterns
            for match in pattern.finditer(clause)
        ]
        raw_negative_spans.sort()
        negative_spans: list[tuple[int, int]] = []
        for start, end in raw_negative_spans:
            if negative_spans and start <= negative_spans[-1][1]:
                negative_spans[-1] = (
                    negative_spans[-1][0],
                    max(negative_spans[-1][1], end),
                )
            else:
                negative_spans.append((start, end))
        negative_starts = [start for start, _ in negative_spans]
        for pattern in positive_patterns:
            for positive_match in pattern.finditer(clause):
                positive_start, positive_end = positive_match.span()
                negative_index = bisect_left(negative_starts, positive_end) - 1
                overlaps = (
                    negative_index >= 0
                    and negative_spans[negative_index][1] > positive_start
                )
                if not overlaps:
                    return True
    return False


def semantic_contract_violations(
    skill_text: str,
    reference_map: Mapping[str, str],
    ui_text: str = "",
) -> list[str]:
    """Return explicit contradiction labels for the frozen Skill contract."""

    documents = (skill_text, *tuple(reference_map[name] for name in sorted(reference_map)), ui_text)
    rendered_documents = tuple(_mask_contract_rendered_text(document) for document in documents)
    corpus = ". ".join(rendered_documents)
    clauses = _contract_clauses(corpus)
    violations: list[str] = []
    for label, positive_patterns, negative_patterns in CONTRACT_CONTRADICTION_RULES:
        if _contract_rule_matches(clauses, positive_patterns, negative_patterns):
            violations.append(label)
    skill_corpus = _normalize_contract_text(rendered_documents[0])
    for label, pattern in REQUIRED_CONTRACT_PATTERNS:
        if pattern.search(skill_corpus) is None:
            violations.append(label)
    violations.extend(
        sensitive_contract_violations(
            rendered_documents
        )
    )
    return violations


def _unfenced_lines(text: str) -> tuple[list[str], bool]:
    """Return rendered lines and whether a backtick/tilde fence is unclosed."""

    rendered, unclosed, _ = _unfenced_lines_with_diagnostics(text)
    return rendered, unclosed


def _unfenced_lines_with_diagnostics(text: str) -> tuple[list[str], bool, list[str]]:
    """Return rendered lines, fence state, and container normalization diagnostics."""

    rendered: list[str] = []
    fence_char: str | None = None
    fence_length = 0
    normalized, container_diagnostics = _container_normalized_lines_with_diagnostics(text)
    for line in normalized:
        if fence_char is None:
            if _is_rendered_indented_code_line(line):
                rendered.append("")
                continue
            marker = _line_fence_marker(line)
            if marker is not None:
                fence_char, fence_length = marker
                continue
            rendered.append(line)
            continue

        if _fence_closes(line, fence_char, fence_length):
            fence_char = None
            fence_length = 0
    return rendered, fence_char is not None, container_diagnostics


def task_contract_violations(text: str) -> list[str]:
    """Require exactly five rendered H2 sections and reject Setext headings."""

    lines, unclosed_fence, container_diagnostics = _unfenced_lines_with_diagnostics(text)
    headings: list[str] = []
    non_h2_headings: list[str] = []
    for line in lines:
        if getattr(line, "paragraph_continuation", False):
            continue
        match = ATX_TASK_HEADING_RE.match(line)
        if match is None:
            continue
        level = len(match.group(1))
        heading_text = re.sub(
            r"[ \t]+#+[ \t]*$", "", (match.group(2) or "").strip()
        )
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
    violations.extend(container_diagnostics)
    if any(_invalid_backtick_fence_opener(line) for line in lines):
        violations.append("task-contract contains an invalid backtick fence opener")
    for diagnostic in _raw_html_diagnostics_for_rendered_lines(lines):
        violations.append(f"task-contract contains unsupported raw HTML: {diagnostic}")

    for index, line in enumerate(lines[:-1]):
        if (
            line.strip()
            and not getattr(line, "paragraph_continuation", False)
            and not getattr(lines[index + 1], "paragraph_continuation", False)
            and not _is_rendered_indented_code_line(line)
            and not _is_rendered_indented_code_line(lines[index + 1])
            and SETEXT_UNDERLINE_RE.match(lines[index + 1])
        ):
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
    skill_scan = _scan_rendered_markdown_details(skill_text)
    rendered_skill_links, unresolved_skill_links = skill_scan.targets, skill_scan.unresolved
    for diagnostic in skill_scan.diagnostics:
        violations.append(f"SKILL.md Markdown scan is ambiguous or invalid: {diagnostic}")
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
        reference_scan = _scan_rendered_markdown_details(text)
        rendered_links, unresolved_links = reference_scan.targets, reference_scan.unresolved
        for diagnostic in reference_scan.diagnostics:
            violations.append(f"skill reference Markdown scan is ambiguous or invalid: {name}: {diagnostic}")
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
