#!/usr/bin/env python3
"""Focused offline mutation coverage for the registered 13-agent contracts."""

from __future__ import annotations

import importlib.util
import re
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / "payload/agents/common"
VALIDATOR_PATH = ROOT / "scripts/validate_bundle.py"
SPEC = importlib.util.spec_from_file_location("validate_bundle_agent_contract", VALIDATOR_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"unable to load validator: {VALIDATOR_PATH}")
VALIDATOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VALIDATOR
SPEC.loader.exec_module(VALIDATOR)


AGENT_SOURCES = {
    path.name: path.read_text(encoding="utf-8")
    for path in sorted(AGENT_DIR.glob("*.toml"))
}


def mutate_field(source: str, field: str, value: str) -> str:
    candidate, count = re.subn(
        rf"^{re.escape(field)}\s*=.*$",
        f"{field} = {value}",
        source,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise AssertionError(f"field mutation anchor is absent: {field!r}")
    return candidate


def mutate_whitespace_anchor(source: str, anchor: str, replacement: str = "") -> str:
    words = re.split(r"\s+", anchor.strip())
    pattern = r"\s+".join(re.escape(word) for word in words)
    candidate, count = re.subn(pattern, replacement, source, count=1)
    if count != 1:
        raise AssertionError(f"whitespace-tolerant mutation anchor is absent: {anchor!r}")
    return candidate


def replace_section_body(source: str, section: str, body: str) -> str:
    lines = source.splitlines()
    heading = f"# {section}"
    try:
        start = lines.index(heading)
    except ValueError as exc:
        raise AssertionError(f"section is absent: {section!r}") from exc
    end = next((index for index in range(start + 1, len(lines)) if lines[index].startswith("# ")), len(lines))
    lines[start + 1 : end] = body.splitlines() if body else []
    result = "\n".join(lines)
    return result + ("\n" if source.endswith("\n") else "")


def swap_headings(source: str, first: str, second: str) -> str:
    lines = source.splitlines()
    first_index = lines.index(first)
    second_index = lines.index(second)
    lines[first_index], lines[second_index] = lines[second_index], lines[first_index]
    result = "\n".join(lines)
    return result + ("\n" if source.endswith("\n") else "")


def inject_after_heading(source: str, section: str, sentence: str) -> str:
    marker = f"# {section}\n"
    if marker not in source:
        raise AssertionError(f"section insertion anchor is absent: {section!r}")
    return source.replace(marker, marker + sentence + "\n", 1)


def remove_schema_field(source: str, field: str) -> str:
    candidate, count = re.subn(
        rf"(?m)^[ \t]*{re.escape(field)}:.*(?:\n|$)",
        "",
        source,
        count=1,
    )
    if count != 1:
        raise AssertionError(f"schema field mutation anchor is absent: {field!r}")
    return candidate


def schema_fields(source: str) -> tuple[str, ...]:
    body = source.split("# RETURN SCHEMA\n", 1)[1]
    return tuple(re.findall(r"(?m)^[ \t]*([A-Z][A-Z0-9_]*)\s*:", body))


def duplicate_schema_field(source: str, field: str) -> str:
    pattern = rf"(?m)^[ \t]*{re.escape(field)}\s*:.*(?:\n|$)"
    match = re.search(pattern, source)
    if match is None:
        raise AssertionError(f"schema duplicate anchor is absent: {field!r}")
    return source[: match.end()] + match.group(0) + source[match.end() :]


def swap_schema_fields(source: str, first: str, second: str) -> str:
    lines = source.splitlines(keepends=True)
    first_index = next(
        (index for index, line in enumerate(lines) if re.match(rf"^[ \t]*{re.escape(first)}\s*:", line)),
        None,
    )
    second_index = next(
        (index for index, line in enumerate(lines) if re.match(rf"^[ \t]*{re.escape(second)}\s*:", line)),
        None,
    )
    if first_index is None or second_index is None:
        raise AssertionError(f"schema reorder anchors are absent: {first!r}, {second!r}")
    lines[first_index], lines[second_index] = lines[second_index], lines[first_index]
    return "".join(lines)


def rename_schema_field(source: str, field: str, replacement: str) -> str:
    candidate, count = re.subn(
        rf"(?m)^([ \t]*){re.escape(field)}(\s*:)",
        rf"\g<1>{replacement}\g<2>",
        source,
        count=1,
    )
    if count != 1:
        raise AssertionError(f"schema rename anchor is absent: {field!r}")
    return candidate


def add_extra_schema_field(source: str, field: str) -> str:
    pattern = rf"(?m)^([ \t]*){re.escape(field)}\s*:.*(?:\n|$)"
    match = re.search(pattern, source)
    if match is None:
        raise AssertionError(f"schema extra-field anchor is absent: {field!r}")
    return source[: match.end()] + "EXTRA_SCHEMA_FIELD: injected\n" + source[match.end() :]


def mutate_exact_schema_line(source: str, expected: str, replacement: str | None) -> str:
    pattern = rf"(?m)^(?P<indent>[ \t]*){re.escape(expected)}[ \t]*$"
    replacement_line = "" if replacement is None else rf"\g<indent>{replacement}"
    candidate, count = re.subn(pattern, replacement_line, source, count=1)
    if count != 1:
        raise AssertionError(f"exact schema-line mutation anchor is absent: {expected!r}")
    return candidate


def append_return_schema_line(source: str, line: str) -> str:
    marker = '\n"""'
    index = source.rfind(marker)
    if index == -1:
        raise AssertionError("RETURN SCHEMA closing delimiter is absent")
    return source[:index] + f"\n{line}" + source[index:]


def mutate_section_boundary(
    source: str,
    previous_section: str,
    next_section: str,
    previous_line: str,
    next_line: str,
) -> str:
    lines = source.splitlines()
    previous_heading = f"# {previous_section}"
    next_heading = f"# {next_section}"
    try:
        next_index = lines.index(next_heading)
    except ValueError as exc:
        raise AssertionError(f"section boundary is absent: {previous_section!r} -> {next_section!r}") from exc
    if lines.index(previous_heading) >= next_index:
        raise AssertionError(f"section boundary is not ordered: {previous_section!r} -> {next_section!r}")
    lines.insert(next_index, previous_line)
    lines.insert(next_index + 2, next_line)
    result = "\n".join(lines)
    return result + ("\n" if source.endswith("\n") else "")


class AgentContractTests(unittest.TestCase):
    def materialize(
        self,
        mutations: dict[str, str] | None = None,
        *,
        remove: tuple[str, ...] = (),
        extra: dict[str, str] | None = None,
    ) -> list[str]:
        mutations = mutations or {}
        extra = extra or {}
        with tempfile.TemporaryDirectory() as directory:
            common = Path(directory) / "payload/agents/common"
            common.mkdir(parents=True)
            for filename, source in AGENT_SOURCES.items():
                if filename not in remove:
                    (common / filename).write_text(mutations.get(filename, source), encoding="utf-8")
            for filename, source in extra.items():
                (common / filename).write_text(source, encoding="utf-8")
            return VALIDATOR.agent_directory_violations(common)

    def errors_for(self, filename: str, source: str) -> list[str]:
        return VALIDATOR.agent_contract_violations(tomllib.loads(source), filename)

    def assert_diagnostic(self, errors: list[str], fragment: str) -> None:
        self.assertTrue(
            any(fragment in error for error in errors),
            f"diagnostic {fragment!r} was absent from:\n" + "\n".join(errors),
        )

    def test_all_thirteen_baseline_contracts_are_accepted(self) -> None:
        self.assertEqual(set(AGENT_SOURCES), VALIDATOR.EXPECTED_COMMON_FILES)
        self.assertEqual(self.materialize(), [])
        for filename, source in AGENT_SOURCES.items():
            errors = self.errors_for(filename, source)
            self.assertEqual(errors, [], filename)

    def test_validate_agents_integrates_the_focused_directory_validator(self) -> None:
        check = VALIDATOR.Validation()
        VALIDATOR.validate_agents(ROOT, check)
        self.assertEqual(check.errors, [])

    def test_contract_headings_are_closed_ordered_unique_and_nonempty(self) -> None:
        filename = "architect.toml"
        source = AGENT_SOURCES[filename]
        cases = (
            (
                "missing",
                source.replace("# EVIDENCE\n", "", 1),
                "missing required contract heading: # EVIDENCE",
            ),
            (
                "reordered",
                swap_headings(source, "# ROLE AND SUCCESS", "# USE WHEN / DO NOT USE WHEN"),
                "required contract headings must appear exactly once in exact order",
            ),
            (
                "duplicate",
                source.replace("# EVIDENCE\n", "# EVIDENCE\n# EVIDENCE\n", 1),
                "duplicate required contract heading: # EVIDENCE",
            ),
            (
                "empty",
                replace_section_body(source, "EVIDENCE", ""),
                'section "EVIDENCE" must have a nonempty body',
            ),
            (
                "extra",
                source.replace("# RETURN SCHEMA\n", "# EXTRA\n# RETURN SCHEMA\n", 1),
                "unexpected or malformed developer_instructions heading",
            ),
            (
                "malformed",
                source.replace("# EVIDENCE\n", "## EVIDENCE\n", 1),
                "unexpected or malformed developer_instructions heading",
            ),
        )
        for case, candidate, diagnostic in cases:
            with self.subTest(case=case):
                self.assert_diagnostic(self.errors_for(filename, candidate), diagnostic)

    def test_directory_requires_exact_registered_files_and_unique_names(self) -> None:
        self.assert_diagnostic(
            self.materialize(remove=("architect.toml",)),
            "missing registered agent file",
        )
        self.assert_diagnostic(
            self.materialize(extra={"unexpected.toml": AGENT_SOURCES["architect.toml"]}),
            "unexpected agent file",
        )

        duplicate = AGENT_SOURCES["architect.toml"].replace('name = "architect"', 'name = "code_mapper"', 1)
        errors = self.materialize({"architect.toml": duplicate})
        self.assert_diagnostic(errors, "filename stem")
        self.assert_diagnostic(errors, "duplicate configured agent name")

        unknown = AGENT_SOURCES["architect.toml"].replace('name = "architect"', 'name = "architect_variant"', 1)
        self.assert_diagnostic(self.errors_for("architect.toml", unknown), "filename stem")

    def test_every_registered_role_pin_is_exact_and_capability_dependent(self) -> None:
        for name, (model, effort, sandbox) in VALIDATOR.EXPECTED_AGENT_PINS.items():
            filename = f"{name}.toml"
            source = AGENT_SOURCES[filename]
            bad_values = {
                "model": '"gpt-5.5"' if model != "gpt-5.5" else '"gpt-5.4"',
                "model_reasoning_effort": '"low"' if effort != "low" else '"high"',
                "sandbox_mode": '"workspace-write"' if sandbox == "read-only" else '"read-only"',
            }
            for field, bad_value in bad_values.items():
                with self.subTest(role=name, field=field):
                    errors = self.errors_for(filename, mutate_field(source, field, bad_value))
                    diagnostic = {
                        "model": "configured model request",
                        "model_reasoning_effort": "configured reasoning-effort request",
                        "sandbox_mode": "configured sandbox request",
                    }[field]
                    self.assert_diagnostic(errors, diagnostic)
                    self.assert_diagnostic(errors, "capability-dependent configuration")

    def test_top_level_keys_and_scalar_types_are_closed(self) -> None:
        source = AGENT_SOURCES["architect.toml"]
        self.assert_diagnostic(
            self.errors_for("architect.toml", source + '\nextra_contract_key = "unexpected"\n'),
            "unexpected top-level key: extra_contract_key",
        )
        missing = re.sub(r"^description\s*=.*\n", "", source, count=1, flags=re.MULTILINE)
        self.assert_diagnostic(
            self.errors_for("architect.toml", missing),
            "missing top-level key: description",
        )
        wrong_type = mutate_field(source, "model_reasoning_effort", "7")
        self.assert_diagnostic(
            self.errors_for("architect.toml", wrong_type),
            "top-level key model_reasoning_effort must be a string",
        )

    def test_read_only_behavior_and_provenance_anchors_are_enforced(self) -> None:
        filename = "architect.toml"
        source = AGENT_SOURCES[filename]
        cases = (
            (
                mutate_whitespace_anchor(source, "behaviorally read-only: do not mutate"),
                "read-only behavioral write prohibition missing",
            ),
            (
                mutate_whitespace_anchor(source, "Own only"),
                "read-only ownership boundary missing",
            ),
            (
                mutate_whitespace_anchor(source, "requested sandbox policy separately from observed sandbox policy"),
                "requested-versus-observed sandbox distinction missing",
            ),
            (
                mutate_whitespace_anchor(source, "effectiveness from this TOML"),
                "configured-model/runtime-effectiveness disclaimer missing",
            ),
            (
                mutate_whitespace_anchor(source, "OS-enforced read-only"),
                "TOML cannot claim OS-enforced read-only missing",
            ),
        )
        for candidate, diagnostic in cases:
            with self.subTest(diagnostic=diagnostic):
                self.assert_diagnostic(self.errors_for(filename, candidate), diagnostic)

    def test_every_read_only_role_rejects_explicit_write_and_os_claim_permissions(self) -> None:
        cases = (
            (
                "This role may modify assigned files.",
                "contradictory read-only permission is forbidden",
            ),
            (
                "This role may edit repository files.",
                "contradictory read-only permission is forbidden",
            ),
            (
                "THIS   TOML DECLARES OS-ENFORCED READ-ONLY!",
                "contradictory OS-enforced read-only sandbox claim is forbidden",
            ),
            (
                "This TOML guarantees OS-enforced read-only.",
                "contradictory OS-enforced read-only sandbox claim is forbidden",
            ),
        )
        for name in VALIDATOR.READ_ONLY_AGENTS:
            filename = f"{name}.toml"
            for sentence, diagnostic in cases:
                with self.subTest(role=name, mutation=sentence):
                    candidate = inject_after_heading(
                        AGENT_SOURCES[filename],
                        "ALLOWED ACTIONS AND TOOLS",
                        sentence,
                    )
                    self.assert_diagnostic(self.errors_for(filename, candidate), diagnostic)

    def test_read_only_handoff_requires_evidence_and_sandbox_fields(self) -> None:
        source = AGENT_SOURCES["architect.toml"]
        for field in ("EVIDENCE", "SANDBOX"):
            with self.subTest(field=field):
                self.assert_diagnostic(
                    self.errors_for("architect.toml", remove_schema_field(source, field)),
                    f"read-only structured handoff field missing: {field}",
                )

    def test_writer_ownership_and_unowned_product_limits_are_registered(self) -> None:
        anchors = {
            "implementer": (
                "Write only the explicitly assigned paths or artifacts",
                "Do not change APIs, ABI, tests, tooling, manifests, or product code outside the named paths",
            ),
            "performance_profiler": (
                "Write only explicitly assigned benchmark, profiler, trace, log, or temporary measurement artifacts",
                "Never mutate product implementation or unassigned tests/configuration",
            ),
            "tester": (
                "Write only explicitly assigned test, reproduction, log, or diagnostic artifacts",
                "Never mutate product implementation or unassigned tests/configuration",
            ),
        }
        for name, (ownership_anchor, product_anchor) in anchors.items():
            filename = f"{name}.toml"
            source = AGENT_SOURCES[filename]
            with self.subTest(role=name, mutation="ownership"):
                self.assert_diagnostic(
                    self.errors_for(filename, mutate_whitespace_anchor(source, ownership_anchor)),
                    "writer ownership/artifact limit",
                )
            with self.subTest(role=name, mutation="unowned product"):
                self.assert_diagnostic(
                    self.errors_for(filename, mutate_whitespace_anchor(source, product_anchor)),
                    "unowned product edit prohibition",
                )

    def test_each_writer_rejects_explicit_unowned_product_permission(self) -> None:
        sentences = (
            "This role may edit unowned product implementation.",
            "This role may edit product implementation outside the named paths.",
            "This role may mutate unassigned product implementation.",
            "This role may edit product code outside owned paths.",
            "This role may edit product implementation outside assigned paths.",
        )
        for name in VALIDATOR.WRITER_AGENTS:
            filename = f"{name}.toml"
            for sentence in sentences:
                with self.subTest(role=name, mutation=sentence):
                    candidate = inject_after_heading(
                        AGENT_SOURCES[filename],
                        "ALLOWED ACTIONS AND TOOLS",
                        sentence,
                    )
                    self.assert_diagnostic(
                        self.errors_for(filename, candidate),
                        "contradictory unowned-product write permission is forbidden",
                    )

    def test_every_role_group_has_registered_evidence_and_stop_anchors(self) -> None:
        for name, registered in VALIDATOR.ROLE_CONTRACT_ANCHORS.items():
            filename = f"{name}.toml"
            source = AGENT_SOURCES[filename]
            evidence_anchor = registered["evidence"][0]
            stop_anchor = registered["stop"][0]
            with self.subTest(role=name, section="evidence"):
                self.assert_diagnostic(
                    self.errors_for(filename, mutate_whitespace_anchor(source, evidence_anchor)),
                    "registered role-specific evidence anchor missing",
                )
            with self.subTest(role=name, section="stop"):
                self.assert_diagnostic(
                    self.errors_for(filename, mutate_whitespace_anchor(source, stop_anchor)),
                    "registered role-specific stop anchor missing",
                )

    def test_all_role_global_prohibitions_are_checked(self) -> None:
        for filename, source in AGENT_SOURCES.items():
            candidate = mutate_whitespace_anchor(source, "implicit commit, push, or PR")
            with self.subTest(role=Path(filename).stem):
                self.assert_diagnostic(
                    self.errors_for(filename, candidate),
                    "registered implicit commit/push/PR prohibition missing",
                )

    def test_every_role_rejects_parent_completion_and_runtime_effectiveness_bypass(self) -> None:
        for filename, source in AGENT_SOURCES.items():
            with self.subTest(role=Path(filename).stem, mutation="whole parent completion"):
                self.assert_diagnostic(
                    self.errors_for(filename, mutate_whitespace_anchor(source, "parent task complete")),
                    "registered whole-parent completion prohibition missing",
                )
            compact = re.sub(r"\s+", " ", source)
            disclaimer = (
                "effectiveness from this TOML"
                if "effectiveness from this TOML" in compact
                else "effectiveness from TOML"
            )
            with self.subTest(role=Path(filename).stem, mutation="runtime effectiveness"):
                self.assert_diagnostic(
                    self.errors_for(filename, mutate_whitespace_anchor(source, disclaimer)),
                    "configured-model/runtime-effectiveness disclaimer missing",
                )

    def test_every_role_rejects_registered_contradictory_global_permissions(self) -> None:
        cases = (
            (
                "destructive command permission",
                "This role may run destructive commands.",
                "contradictory destructive-command/operation permission is forbidden",
            ),
            (
                "destructive operation permission variant",
                "This role may perform destructive operations.",
                "contradictory destructive-command/operation permission is forbidden",
            ),
            (
                "harmful external exploitation permission",
                "This role may perform harmful external exploitation.",
                "contradictory harmful-exploitation permission is forbidden",
            ),
            (
                "secret exposure permission",
                "This role may expose secrets.",
                "contradictory secret-disclosure permission is forbidden",
            ),
            (
                "secret disclosure permission variant",
                "This role may disclose secrets.",
                "contradictory secret-disclosure permission is forbidden",
            ),
            (
                "external contact permission",
                "This role may contact external systems.",
                "contradictory external-system contact permission is forbidden",
            ),
            (
                "external call permission variant",
                "This role may call external systems.",
                "contradictory external-system contact permission is forbidden",
            ),
            (
                "implicit commit/push/PR permission",
                "This role may make an implicit commit, push, or PR.",
                "contradictory implicit commit/push/PR authorization is forbidden",
            ),
            (
                "implicit pull-request creation permission",
                "This role may create an implicit pull request.",
                "contradictory implicit commit/push/PR authorization is forbidden",
            ),
            (
                "implicit commit permission variant",
                "This role may create an implicit commit.",
                "contradictory implicit commit/push/PR authorization is forbidden",
            ),
            (
                "parent completion declaration permission",
                "This role may declare the parent task complete.",
                "contradictory whole-parent completion authorization is forbidden",
            ),
            (
                "parent completion claim permission",
                "This role may claim the parent task is complete.",
                "contradictory whole-parent completion authorization is forbidden",
            ),
            (
                "parent completion mark permission variant",
                "This role may mark the entire parent task as complete.",
                "contradictory whole-parent completion authorization is forbidden",
            ),
            (
                "runtime model/effort/sandbox claim",
                "This TOML proves runtime model, effort, and sandbox effectiveness.",
                "contradictory configured runtime-effectiveness claim is forbidden",
            ),
            (
                "observed runtime behavior claim",
                "This TOML proves observed runtime behavior.",
                "contradictory configured runtime-effectiveness claim is forbidden",
            ),
            (
                "effective route/model/effort/sandbox claim variant",
                "This configuration proves effective route, model, effort, and sandbox effectiveness.",
                "contradictory configured runtime-effectiveness claim is forbidden",
            ),
            (
                "external mutation permission",
                "This role may mutate external systems.",
                "contradictory external-system mutation permission is forbidden",
            ),
            (
                "compound external contact/mutation permission variant",
                "This role may contact or mutate external systems.",
                "contradictory external-system mutation permission is forbidden",
            ),
        )
        for filename, source in AGENT_SOURCES.items():
            for case_name, sentence, diagnostic in cases:
                with self.subTest(role=Path(filename).stem, mutation=case_name):
                    candidate = inject_after_heading(source, "ALLOWED ACTIONS AND TOOLS", sentence)
                    self.assert_diagnostic(self.errors_for(filename, candidate), diagnostic)

    def test_confirmed_adversarial_global_contradictions_are_rejected(self) -> None:
        cases = (
            (
                "architect.toml",
                "This role may run destructive commands.",
                "contradictory destructive-command/operation permission is forbidden",
            ),
            (
                "implementer.toml",
                "This role may expose secrets.",
                "contradictory secret-disclosure permission is forbidden",
            ),
            (
                "security_reviewer.toml",
                "This role may contact external systems.",
                "contradictory external-system contact permission is forbidden",
            ),
            (
                "architect.toml",
                "This role may create an implicit pull request.",
                "contradictory implicit commit/push/PR authorization is forbidden",
            ),
            (
                "implementer.toml",
                "This role may claim the parent task is complete.",
                "contradictory whole-parent completion authorization is forbidden",
            ),
            (
                "security_reviewer.toml",
                "This TOML proves observed runtime behavior.",
                "contradictory configured runtime-effectiveness claim is forbidden",
            ),
            (
                "architect.toml",
                "This role may edit repository files.",
                "contradictory read-only permission is forbidden",
            ),
            (
                "security_reviewer.toml",
                "This role may perform harmful external exploitation.",
                "contradictory harmful-exploitation permission is forbidden",
            ),
            (
                "implementer.toml",
                "This role may edit product code outside owned paths.",
                "contradictory unowned-product write permission is forbidden",
            ),
            (
                "architect.toml",
                "This TOML guarantees OS-enforced read-only.",
                "contradictory OS-enforced read-only sandbox claim is forbidden",
            ),
        )
        for filename, sentence, diagnostic in cases:
            with self.subTest(role=Path(filename).stem, mutation=sentence):
                candidate = inject_after_heading(
                    AGENT_SOURCES[filename],
                    "ALLOWED ACTIONS AND TOOLS",
                    sentence,
                )
                self.assert_diagnostic(self.errors_for(filename, candidate), diagnostic)

    def test_negated_or_surrounding_permission_prose_is_not_a_contradiction(self) -> None:
        cases = (
            (
                "architect.toml",
                "Never state that this role may expose secrets.",
            ),
            (
                "architect.toml",
                "Do not say this role may run destructive commands.",
            ),
            (
                "architect.toml",
                "Never authorize this role may contact external systems.",
            ),
            (
                "architect.toml",
                "Do not say this role may edit repository files.",
            ),
            (
                "implementer.toml",
                "Never authorize this role may edit product code outside owned paths.",
            ),
            (
                "architect.toml",
                "Never state that this TOML proves observed runtime behavior.",
            ),
        )
        for filename, sentence in cases:
            with self.subTest(role=Path(filename).stem, sentence=sentence):
                candidate = inject_after_heading(
                    AGENT_SOURCES[filename],
                    "ALLOWED ACTIONS AND TOOLS",
                    sentence,
                )
                self.assertEqual(self.errors_for(filename, candidate), [], sentence)

    def test_bounded_matcher_preserves_wrapping_and_colon_context(self) -> None:
        rejected = (
            (
                "This role may\nexpose secrets.",
                "contradictory secret-disclosure permission is forbidden",
            ),
            (
                "THIS   ROLE MAY:\nEXPOSE, SECRETS!",
                "contradictory secret-disclosure permission is forbidden",
            ),
            (
                "Allowed actions: This role may expose secrets.",
                "contradictory secret-disclosure permission is forbidden",
            ),
        )
        for sentence, diagnostic in rejected:
            with self.subTest(sentence=sentence):
                candidate = inject_after_heading(
                    AGENT_SOURCES["architect.toml"],
                    "ALLOWED ACTIONS AND TOOLS",
                    sentence,
                )
                self.assert_diagnostic(self.errors_for("architect.toml", candidate), diagnostic)
        benign = (
            "Never state:\nthis role may expose secrets.",
            "Do not say: this role may expose secrets.",
        )
        for sentence in benign:
            with self.subTest(sentence=sentence):
                candidate = inject_after_heading(
                    AGENT_SOURCES["architect.toml"],
                    "ALLOWED ACTIONS AND TOOLS",
                    sentence,
                )
                self.assertEqual(self.errors_for("architect.toml", candidate), [], sentence)

    def test_authentic_physical_boundaries_and_neutral_label_variants(self) -> None:
        filename = "architect.toml"
        source = AGENT_SOURCES[filename]
        existing_line = "Use bounded repository search and file inspection, read-only Git status/diff/log, and\n"
        direct_variants = (
            "This role may expose secrets.\n",
            "- This role may expose secrets.\n",
            "\nThis role may expose secrets.\n",
            "Inspect only\nThis role may expose secrets.\n",
            "Allowed actions： This role may expose secrets.\n",
            "Allowed actions — This role may expose secrets.\n",
        )
        for insertion in direct_variants:
            with self.subTest(insertion=insertion):
                candidate, count = source.replace(
                    existing_line,
                    existing_line + insertion,
                    1,
                ), source.count(existing_line)
                self.assertEqual(count, 1)
                self.assertNotEqual(candidate, source)
                self.assert_diagnostic(
                    self.errors_for(filename, candidate),
                    "contradictory secret-disclosure permission is forbidden",
                )

        benign_variants = (
            "Never state;\nThis role may expose secrets.\n",
            "Do not say;\n- This role may expose secrets.\n",
            "Never state：\nThis role may expose secrets.\n",
        )
        for insertion in benign_variants:
            with self.subTest(insertion=insertion):
                candidate, count = source.replace(
                    existing_line,
                    existing_line + insertion,
                    1,
                ), source.count(existing_line)
                self.assertEqual(count, 1)
                self.assertNotEqual(candidate, source)
                self.assertEqual(self.errors_for(filename, candidate), [], insertion)

        direct_after_unrelated_context = (
            "Do not say something untrue.\n- This role may expose secrets.\n",
            "Example unrelated prose.\n- This role may expose secrets.\n",
            "Never state unrelated prose\nThis role may expose secrets.\n",
            "Never state:\n\nThis role may expose secrets.\n",
        )
        for insertion in direct_after_unrelated_context:
            with self.subTest(insertion=insertion):
                candidate, count = source.replace(
                    existing_line,
                    existing_line + insertion,
                    1,
                ), source.count(existing_line)
                self.assertEqual(count, 1)
                self.assertNotEqual(candidate, source)
                self.assert_diagnostic(
                    self.errors_for(filename, candidate),
                    "contradictory secret-disclosure permission is forbidden",
                )

        exact_introducer_controls = (
            "Never state:\nThis role may expose secrets.\n",
            "Never state：\n- This role may expose secrets.\n",
            "Do not say;\n- This role may expose secrets.\n",
        )
        for insertion in exact_introducer_controls:
            with self.subTest(insertion=insertion):
                candidate, count = source.replace(
                    existing_line,
                    existing_line + insertion,
                    1,
                ), source.count(existing_line)
                self.assertEqual(count, 1)
                self.assertNotEqual(candidate, source)
                self.assertEqual(self.errors_for(filename, candidate), [], insertion)

    def test_registered_separator_and_checkbox_variants_are_closed(self) -> None:
        cases = (
            (
                "architect.toml",
                "Use bounded repository search and file inspection, read-only Git status/diff/log, and\n",
                "Unrelated completed prose; This role may edit repository files.\n",
                "contradictory read-only permission is forbidden",
            ),
            (
                "architect.toml",
                "Use bounded repository search and file inspection, read-only Git status/diff/log, and\n",
                "Unrelated completed prose:This role may edit repository files.\n",
                "contradictory read-only permission is forbidden",
            ),
            (
                "architect.toml",
                "Use bounded repository search and file inspection, read-only Git status/diff/log, and\n",
                "- [x] This role may expose secrets!\n",
                "contradictory secret-disclosure permission is forbidden",
            ),
            (
                "architect.toml",
                "Use bounded repository search and file inspection, read-only Git status/diff/log, and\n",
                "- [X] This role may expose secrets.\n",
                "contradictory secret-disclosure permission is forbidden",
            ),
            (
                "architect.toml",
                "Use bounded repository search and file inspection, read-only Git status/diff/log, and\n",
                "- [ ] This role may expose secrets.\n",
                "contradictory secret-disclosure permission is forbidden",
            ),
            (
                "implementer.toml",
                "Read and search the relevant repository, edit assigned files using repository\n",
                "Unrelated completed prose — This role may edit product code outside owned paths.\n",
                "contradictory unowned-product write permission is forbidden",
            ),
            (
                "docs_researcher_luna.toml",
                "Inspect assigned repository and local documentation, and use bounded read-only search\n",
                "Unrelated completed prose: Content, task, or tool failure authorizes route switching.\n",
                "contradictory failure-authorized fallback/route-switch permission is forbidden",
            ),
            (
                "docs_researcher_terra.toml",
                "Inspect assigned repository and local documentation, and use bounded read-only search\n",
                "Unrelated completed prose: Content, task, or tool failure authorizes route switching.\n",
                "contradictory failure-authorized fallback/route-switch permission is forbidden",
            ),
        )
        for filename, context_anchor, insertion, diagnostic in cases:
            with self.subTest(role=filename, insertion=insertion):
                source = AGENT_SOURCES[filename]
                self.assertEqual(source.count(context_anchor), 1)
                candidate = source.replace(context_anchor, context_anchor + insertion, 1)
                self.assertNotEqual(candidate, source)
                self.assert_diagnostic(self.errors_for(filename, candidate), diagnostic)

        benign = (
            "Never state: This role may expose secrets.\n",
            "Never state：This role may expose secrets.\n",
            "Do not say; - This role may expose secrets.\n",
        )
        source = AGENT_SOURCES["architect.toml"]
        context_anchor = "Use bounded repository search and file inspection, read-only Git status/diff/log, and\n"
        for insertion in benign:
            with self.subTest(benign=insertion):
                candidate = source.replace(context_anchor, context_anchor + insertion, 1)
                self.assertNotEqual(candidate, source)
                self.assertEqual(self.errors_for("architect.toml", candidate), [], insertion)

    def test_cross_line_introducer_only_protects_one_clause_plain_and_list(self) -> None:
        cases = (
            (
                "architect.toml",
                "This role may expose secrets.",
                "contradictory secret-disclosure permission is forbidden",
            ),
            (
                "architect.toml",
                "This role may mutate external systems.",
                "contradictory external-system mutation permission is forbidden",
            ),
            (
                "architect.toml",
                "This role may edit repository files.",
                "contradictory read-only permission is forbidden",
            ),
            (
                "implementer.toml",
                "This role may edit product code outside owned paths.",
                "contradictory unowned-product write permission is forbidden",
            ),
            (
                "docs_researcher_luna.toml",
                "Content, task, or tool failure authorizes route switching.",
                "contradictory failure-authorized fallback/route-switch permission is forbidden",
            ),
            (
                "docs_researcher_terra.toml",
                "This role may authorize further fallback.",
                "contradictory further-fallback permission is forbidden",
            ),
        )
        boundaries = (".", ";", ":", "：", "—", "–")
        for filename, direct_clause, diagnostic in cases:
            source = AGENT_SOURCES[filename]
            for marker in ("", "- "):
                for boundary in boundaries:
                    insertion = f"Never state:\n{marker}unrelated{boundary} {direct_clause}\n"
                    with self.subTest(role=filename, marker=marker or "plain", boundary=boundary):
                        candidate = inject_after_heading(
                            source,
                            "ALLOWED ACTIONS AND TOOLS",
                            insertion.rstrip("\n"),
                        )
                        self.assertNotEqual(candidate, source)
                        self.assert_diagnostic(self.errors_for(filename, candidate), diagnostic)

        same_line = (
            "Never state: unrelated; This role may expose secrets.",
            "Never state: unrelated — This role may expose secrets.",
            "Never state: unrelated: This role may expose secrets.",
            "Never state: unrelated; - This role may expose secrets.",
        )
        source = AGENT_SOURCES["architect.toml"]
        for insertion in same_line:
            with self.subTest(same_line=insertion):
                candidate = inject_after_heading(source, "ALLOWED ACTIONS AND TOOLS", insertion)
                self.assert_diagnostic(
                    self.errors_for("architect.toml", candidate),
                    "contradictory secret-disclosure permission is forbidden",
                )

        benign = (
            "Never state:\nThis role may expose secrets.",
            "Never state:\n- This role may expose secrets.",
            "Never state：\n- This role may expose secrets.",
            "Do not say;\n- This role may expose secrets.",
        )
        for insertion in benign:
            with self.subTest(benign=insertion):
                candidate = inject_after_heading(source, "ALLOWED ACTIONS AND TOOLS", insertion)
                self.assertEqual(self.errors_for("architect.toml", candidate), [], insertion)

    def test_closed_contradictions_are_scanned_inside_return_schema(self) -> None:
        cases = (
            (
                "architect.toml",
                "This role may expose secrets.",
                "contradictory secret-disclosure permission is forbidden",
            ),
            (
                "architect.toml",
                "This role may edit repository files.",
                "contradictory read-only permission is forbidden",
            ),
            (
                "implementer.toml",
                "This role may edit product code outside owned paths.",
                "contradictory unowned-product write permission is forbidden",
            ),
            (
                "docs_researcher_luna.toml",
                "Content, task, or tool failure authorizes route switching.",
                "contradictory failure-authorized fallback/route-switch permission is forbidden",
            ),
            (
                "docs_researcher_terra.toml",
                "This role may authorize further fallback.",
                "contradictory further-fallback permission is forbidden",
            ),
        )
        for filename, line, diagnostic in cases:
            with self.subTest(role=filename, line=line):
                candidate = append_return_schema_line(AGENT_SOURCES[filename], line)
                self.assertNotEqual(candidate, AGENT_SOURCES[filename])
                self.assert_diagnostic(self.errors_for(filename, candidate), diagnostic)

    def test_section_boundaries_do_not_leak_context_or_literals(self) -> None:
        sections = VALIDATOR.AGENT_CONTRACT_HEADING_NAMES
        source = AGENT_SOURCES["architect.toml"]
        for index in range(len(sections) - 1):
            previous_section, next_section = sections[index : index + 2]
            for marker in ("", "- [x] "):
                with self.subTest(
                    mutation="introducer",
                    previous_section=previous_section,
                    next_section=next_section,
                    marker=marker or "plain",
                ):
                    candidate = mutate_section_boundary(
                        source,
                        previous_section,
                        next_section,
                        "Never state:",
                        f"{marker}This role may expose secrets.",
                    )
                    self.assertNotEqual(candidate, source)
                    self.assert_diagnostic(
                        self.errors_for("architect.toml", candidate),
                        "contradictory secret-disclosure permission is forbidden",
                    )

            with self.subTest(
                mutation="split literal",
                previous_section=previous_section,
                next_section=next_section,
            ):
                candidate = mutate_section_boundary(
                    source,
                    previous_section,
                    next_section,
                    "This role may expose",
                    "secrets.",
                )
                self.assertNotEqual(candidate, source)
                self.assertEqual(self.errors_for("architect.toml", candidate), [])

    def test_section_boundary_regressions_cover_writer_and_researchers(self) -> None:
        cases = (
            (
                "implementer.toml",
                "OWNERSHIP",
                "ALLOWED ACTIONS AND TOOLS",
                "This role may edit product code outside owned paths.",
                "contradictory unowned-product write permission is forbidden",
            ),
            (
                "docs_researcher_luna.toml",
                "STOP / ESCALATE",
                "EVIDENCE",
                "Content, task, or tool failure authorizes route switching.",
                "contradictory failure-authorized fallback/route-switch permission is forbidden",
            ),
            (
                "docs_researcher_terra.toml",
                "EVIDENCE",
                "RETURN SCHEMA",
                "This role may authorize further fallback.",
                "contradictory further-fallback permission is forbidden",
            ),
        )
        for filename, previous_section, next_section, direct_line, diagnostic in cases:
            source = AGENT_SOURCES[filename]
            for marker in ("", "- [x] "):
                with self.subTest(role=filename, marker=marker or "plain"):
                    candidate = mutate_section_boundary(
                        source,
                        previous_section,
                        next_section,
                        "Never state:",
                        marker + direct_line,
                    )
                    self.assertNotEqual(candidate, source)
                    self.assert_diagnostic(self.errors_for(filename, candidate), diagnostic)

            with self.subTest(role=filename, mutation="split literal"):
                candidate = mutate_section_boundary(
                    source,
                    previous_section,
                    next_section,
                    "This role may expose",
                    "secrets.",
                )
                self.assertNotEqual(candidate, source)
                self.assertFalse(
                    any(diagnostic in error for error in self.errors_for(filename, candidate)),
                    candidate,
                )

    def test_global_contradictions_are_checked_in_every_operative_section(self) -> None:
        filename = "architect.toml"
        source = AGENT_SOURCES[filename]
        for section in VALIDATOR.AGENT_CONTRACT_HEADING_NAMES[:-1]:
            with self.subTest(section=section):
                candidate = inject_after_heading(
                    source,
                    section,
                    "This role may mutate external systems.",
                )
                self.assert_diagnostic(
                    self.errors_for(filename, candidate),
                    "contradictory external-system mutation permission is forbidden",
                )

    def test_registered_schema_registry_matches_every_accepted_base_sequence(self) -> None:
        for name, registered in VALIDATOR.ROLE_CONTRACT_ANCHORS.items():
            filename = f"{name}.toml"
            self.assertEqual(
                schema_fields(AGENT_SOURCES[filename]),
                tuple(registered["schema_fields"]),
                filename,
            )

    def test_every_registered_role_schema_rejects_every_removed_field(self) -> None:
        for name, registered in VALIDATOR.ROLE_CONTRACT_ANCHORS.items():
            filename = f"{name}.toml"
            for field in registered["schema_fields"]:
                with self.subTest(role=name, field=field):
                    candidate = remove_schema_field(AGENT_SOURCES[filename], field)
                    self.assertNotEqual(candidate, AGENT_SOURCES[filename])
                    self.assert_diagnostic(
                        self.errors_for(filename, candidate),
                        f"registered structured handoff field missing: {field}",
                    )

    def test_every_registered_role_schema_rejects_duplicate_reordered_renamed_and_extra_fields(self) -> None:
        diagnostic = "registered structured handoff schema fields must exactly match the registered order"
        for name, registered in VALIDATOR.ROLE_CONTRACT_ANCHORS.items():
            filename = f"{name}.toml"
            fields = tuple(registered["schema_fields"])
            first, second = fields[:2]
            cases = (
                ("duplicate", duplicate_schema_field(AGENT_SOURCES[filename], first), diagnostic),
                ("reordered", swap_schema_fields(AGENT_SOURCES[filename], first, second), diagnostic),
                (
                    "renamed",
                    rename_schema_field(AGENT_SOURCES[filename], second, "RENAMED_SCHEMA_FIELD"),
                    diagnostic,
                ),
                ("extra", add_extra_schema_field(AGENT_SOURCES[filename], first), diagnostic),
            )
            for mutation, candidate, expected in cases:
                with self.subTest(role=name, mutation=mutation):
                    self.assertNotEqual(candidate, AGENT_SOURCES[filename])
                    self.assert_diagnostic(self.errors_for(filename, candidate), expected)

    def test_every_registered_exact_safety_line_rejects_suffix_replacement_and_deletion(self) -> None:
        for name, registered in VALIDATOR.ROLE_CONTRACT_ANCHORS.items():
            filename = f"{name}.toml"
            source = AGENT_SOURCES[filename]
            for expected in registered.get("exact_schema_lines", ()):
                field, _, value = expected.partition(":")
                replacement = f"{field}: MUTATED_VALUE" if value else f"{expected} MUTATED_VALUE"
                mutations = (
                    ("suffix widening", expected + " MUTATED_SUFFIX"),
                    ("replacement", replacement),
                    ("deletion", None),
                )
                for mutation, replacement_line in mutations:
                    with self.subTest(role=name, line=expected, mutation=mutation):
                        candidate = mutate_exact_schema_line(source, expected, replacement_line)
                        self.assertNotEqual(candidate, source)
                        self.assert_diagnostic(
                            self.errors_for(filename, candidate),
                            "structured handoff schema line is not exact",
                        )
                        self.assert_diagnostic(self.errors_for(filename, candidate), expected)

    def test_reviewer_verdict_enum_cannot_be_widened(self) -> None:
        source = AGENT_SOURCES["reviewer.toml"]
        candidate = source.replace(
            "VERDICT: SHIP | FIX_FIRST | RETHINK",
            "VERDICT: SHIP | FIX_FIRST | RETHINK | MAYBE",
            1,
        )
        self.assert_diagnostic(
            self.errors_for("reviewer.toml", candidate),
            "structured handoff schema line is not exact: VERDICT: SHIP | FIX_FIRST | RETHINK",
        )

    def test_researcher_status_matrix_route_authority_and_raw_rejection_are_closed(self) -> None:
        for name in ("docs_researcher_luna", "docs_researcher_terra"):
            filename = f"{name}.toml"
            source = AGENT_SOURCES[filename]
            with self.subTest(role=name, mutation="status enum"):
                candidate = source.replace(
                    "STATUS: COMPLETE | STOP_FAILED | STOP_UNVERIFIED; COMPLETE only when evidence supports the claims.",
                    "STATUS: COMPLETE | STOP_FAILED | STOP_UNVERIFIED | MAYBE; COMPLETE only when evidence supports the claims.",
                    1,
                )
                self.assert_diagnostic(self.errors_for(filename, candidate), "researcher status/failure matrix anchor missing")
            with self.subTest(role=name, mutation="failure enum"):
                candidate = source.replace(
                    "FAILURE_CLASS: NONE | NATIVE_ROUTING_FAILURE | ROUTE_METADATA_MISSING | ROUTE_METADATA_CONFLICT | TASK_FAILURE | TIMEOUT | UNKNOWN_EXCEPTION.",
                    "FAILURE_CLASS: NONE | NATIVE_ROUTING_FAILURE | ROUTE_METADATA_MISSING | ROUTE_METADATA_CONFLICT | TIMEOUT | UNKNOWN_EXCEPTION.",
                    1,
                )
                self.assert_diagnostic(self.errors_for(filename, candidate), "researcher status/failure matrix anchor missing")
            if name.endswith("_luna"):
                failure_anchor = "Content quality, task execution, or tool failure does not authorize fallback or route switching."
            else:
                failure_anchor = "content, task, or tool failure must be returned as a bounded stop"
            with self.subTest(role=name, mutation="failure-authorized fallback"):
                self.assert_diagnostic(
                    self.errors_for(filename, mutate_whitespace_anchor(source, failure_anchor)),
                    "must remain terminal" if name.endswith("_terra") else "must not authorize fallback",
                )
            route_anchor = "ROUTE_AUTHORITY: Evidence and classification only; this role does not spawn or authorize"
            with self.subTest(role=name, mutation="route authority"):
                candidate = mutate_whitespace_anchor(
                    source,
                    route_anchor,
                    "ROUTE_AUTHORITY: Evidence and classification only; this role may spawn or authorize",
                )
                self.assert_diagnostic(self.errors_for(filename, candidate), "route authority must remain evidence-only")
            raw_anchor = "REPORT_SCOPE: Observed or returnable child report after a child attempt exists; a pre-spawn native rejection is parent-owned raw evidence and has no child handoff."
            with self.subTest(role=name, mutation="raw rejection child handoff"):
                candidate = mutate_whitespace_anchor(
                    source,
                    raw_anchor,
                    "REPORT_SCOPE: Observed or returnable child report after a child attempt exists; a pre-spawn native rejection may use a child handoff.",
                )
                self.assert_diagnostic(self.errors_for(filename, candidate), "raw pre-spawn rejection")

    def test_every_researcher_status_failure_matrix_anchor_is_required(self) -> None:
        for name in ("docs_researcher_luna", "docs_researcher_terra"):
            filename = f"{name}.toml"
            source = AGENT_SOURCES[filename]
            for index, anchor in enumerate(VALIDATOR.RESEARCH_STATUS_FAILURE_ANCHORS):
                with self.subTest(role=name, anchor=index):
                    candidate = mutate_whitespace_anchor(source, anchor)
                    self.assertNotEqual(candidate, source)
                    self.assert_diagnostic(
                        self.errors_for(filename, candidate),
                        "researcher status/failure matrix anchor missing",
                    )

    def test_researcher_route_and_authority_fields_reject_each_mutation(self) -> None:
        for name in ("docs_researcher_luna", "docs_researcher_terra"):
            filename = f"{name}.toml"
            source = AGENT_SOURCES[filename]
            requested_route = "Luna/Max" if name.endswith("_luna") else "Terra/high"
            alternate_route = "Terra/high" if name.endswith("_luna") else "Luna/Max"
            cases = [
                (
                    "requested route",
                    f"REQUESTED_ROUTE: {requested_route}",
                    f"REQUESTED_ROUTE: {alternate_route}",
                    "researcher requested route field is not exact",
                ),
                (
                    "observed route",
                    "OBSERVED_ROUTE: Observed native route, or unknown when unobserved.",
                    "OBSERVED_ROUTE: observed route metadata only.",
                    "researcher requested-versus-observed route distinction missing",
                ),
                (
                    "route authority",
                    "ROUTE_AUTHORITY: Evidence and classification only; this role does not spawn or authorize",
                    "ROUTE_AUTHORITY: Evidence and classification only; this role may spawn or authorize",
                    "researcher route authority must remain evidence-only",
                ),
                (
                    "raw pre-spawn report scope",
                    "REPORT_SCOPE: Observed or returnable child report after a child attempt exists; a pre-spawn native rejection is parent-owned raw evidence and has no child handoff.",
                    "REPORT_SCOPE: Observed or returnable child report after a child attempt exists; a pre-spawn native rejection may use a child handoff.",
                    "researcher raw pre-spawn rejection must remain parent-owned with no child handoff",
                ),
            ]
            if name.endswith("_luna"):
                cases.append(
                    (
                        "Luna parent-only promotion",
                        "For Luna, only the parent state machine may use the parent-owned evidence/classification to promote the overall chain to FALLBACK_PENDING; this child never spawns or authorizes Terra, fallback, or route switching.",
                        "For Luna, this child may promote the overall chain to FALLBACK_PENDING; this child never spawns or authorizes Terra, fallback, or route switching.",
                        "Luna route authority must remain parent-owned",
                    )
                )
            else:
                cases.append(
                    (
                        "Terra terminal authority",
                        "For Terra, this is terminal STOP_FAILED and never promotes or authorizes fallback or a route switch.",
                        "For Terra, this is terminal STOP_FAILED and may promote or authorize fallback or a route switch.",
                        "Terra route authority must remain terminal",
                    )
                )
            for mutation, anchor, replacement, diagnostic in cases:
                with self.subTest(role=name, mutation=mutation):
                    candidate = mutate_whitespace_anchor(source, anchor, replacement)
                    self.assertNotEqual(candidate, source)
                    self.assert_diagnostic(self.errors_for(filename, candidate), diagnostic)

    def test_researchers_reject_failure_authorized_fallback_and_route_switch_permissions(self) -> None:
        for name in ("docs_researcher_luna", "docs_researcher_terra"):
            filename = f"{name}.toml"
            source = AGENT_SOURCES[filename]
            fallback_sentence = "Content, task, or tool failure authorizes fallback to another route."
            route_sentence = "Content, task, or tool failure authorizes route switching."
            with self.subTest(role=name, mutation="failure-authorized fallback"):
                self.assert_diagnostic(
                    self.errors_for(
                        filename,
                        inject_after_heading(source, "ALLOWED ACTIONS AND TOOLS", fallback_sentence),
                    ),
                    "contradictory failure-authorized fallback/route-switch permission is forbidden",
                )
            with self.subTest(role=name, mutation="failure-authorized route switch"):
                self.assert_diagnostic(
                    self.errors_for(
                        filename,
                        inject_after_heading(source, "ALLOWED ACTIONS AND TOOLS", route_sentence),
                    ),
                    "contradictory failure-authorized fallback/route-switch permission is forbidden",
                )

        terra_source = AGENT_SOURCES["docs_researcher_terra.toml"]
        self.assert_diagnostic(
            self.errors_for(
                "docs_researcher_terra.toml",
                inject_after_heading(
                    terra_source,
                    "ALLOWED ACTIONS AND TOOLS",
                    "This task may authorize further fallback to Luna.",
                ),
            ),
            "contradictory further-fallback permission is forbidden",
        )


if __name__ == "__main__":
    unittest.main()
