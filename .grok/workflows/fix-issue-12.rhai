let meta = #{
    name: "fix-issue-12",
    description: "Fix GitHub issue #12 Codex CLI findings: skill trigger, config overwrite, PRECHECK, and docs",
    phases: [
        #{ title: "Implement", detail: "parallel disjoint tracks for config, skill trigger, and docs" },
        #{ title: "Precheck", detail: "Codex-observable PRECHECK capability inventory" },
        #{ title: "Verify", detail: "run offline tests and repair failures" },
        #{ title: "Review", detail: "confirm every issue #12 finding is addressed" },
    ],
    when_to_use: "When repairing versatile_agent issue #12 Codex CLI findings on this checkout",
};

let work_schema = #{
    "type": "object",
    "required": ["status", "files_changed", "summary"],
    "properties": #{
        "status": #{ "type": "string", "enum": ["done", "blocked"] },
        "files_changed": #{ "type": "array", "items": #{ "type": "string" } },
        "summary": #{ "type": "string" },
        "blocked_reason": #{ "type": "string" },
    },
};

let verify_schema = #{
    "type": "object",
    "required": ["passed", "commands", "summary"],
    "properties": #{
        "passed": #{ "type": "boolean" },
        "commands": #{ "type": "array", "items": #{ "type": "string" } },
        "summary": #{ "type": "string" },
        "failures": #{ "type": "string" },
    },
};

let review_schema = #{
    "type": "object",
    "required": ["remaining", "notes"],
    "properties": #{
        "remaining": #{
            "type": "array",
            "items": #{
                "type": "object",
                "required": ["id", "status", "evidence"],
                "properties": #{
                    "id": #{ "type": "string" },
                    "status": #{ "type": "string", "enum": ["fixed", "open", "partial"] },
                    "evidence": #{ "type": "string" },
                },
            },
        },
        "notes": #{ "type": "string" },
    },
};

let repo = if args == () { () } else { args.repo };
if repo == () {
    repo = "/Users/chao/Documents/ChatGPT/versatile_agent";
}

fn common_rules(repo_path) {
    let s = "";
    s += "Repository root: " + repo_path + "\n";
    s += "You are implementing GitHub issue #12 in this checkout. Read the files you will change before editing.\n";
    s += "Use tools: read_file, grep, list_dir, search_replace, write, run_terminal_command.\n";
    s += "Stay inside your allowed file list. Do not commit, push, or comment on GitHub.\n";
    s += "Do not invent new product names or extra flags beyond the locked contract below.\n";
    s += "Follow nearby style: Python 4-space, type hints, pathlib; Bash set -euo pipefail, 2-space indent.\n";
    s += "Every behavior change needs a regression assertion. Run focused tests for your files after editing.\n";
    s += "Do not rewrite unrelated comments. Do not add placeholders.\n";
    s
}

phase("Implement");

let merge_prompt = common_rules(repo);
merge_prompt += "TRACK: merge-config preservation (issue #12 HIGH + install follow-through).\n";
merge_prompt += "ALLOWED FILES ONLY:\n";
merge_prompt += "- scripts/merge_config.py\n";
merge_prompt += "- tests/test_merge_config.py\n";
merge_prompt += "- install.sh\n";
merge_prompt += "- tests/test_install.sh\n";
merge_prompt += "LOCKED CONTRACT:\n";
merge_prompt += "1. Default merge inserts only missing MANAGED keys. Present [agents] values stay untouched.\n";
merge_prompt += "2. Add --force-config. Only that flag replaces present MANAGED keys with the hardcoded MANAGED values.\n";
merge_prompt += "3. --check without --force-config is green when every MANAGED key exists, even if values differ.\n";
merge_prompt += "4. --check --force-config is green only when present MANAGED values equal the hardcoded values and missing keys would be inserted.\n";
merge_prompt += "5. install.sh grows --force-config and passes it through to merge_config.py for both write and --check.\n";
merge_prompt += "6. tests/test_merge_config.py currently expects overwrite of max_concurrent 2->6. Change that to preservation; add explicit force-replace and --check cases.\n";
merge_prompt += "7. tests/test_install.sh line that asserts max_concurrent_threads_per_session = 6 after a normal install must expect = 2 (user value preserved). Add a --force-config install that then writes 6.\n";
merge_prompt += "8. Keep custom_key, unrelated sections, idempotency, invalid TOML, duplicate [agents], and array-table stop behavior.\n";
merge_prompt += "Implement merge_text(text, *, force=False) or equivalent. Wire argparse --force-config.\n";
merge_prompt += "After edits run: python3 tests/test_merge_config.py\n";
merge_prompt += "Return status=done with files_changed and a short summary, or status=blocked with blocked_reason.\n";

let skill_prompt = common_rules(repo);
skill_prompt += "TRACK: SKILL.md trigger + openai.yaml (issue #12 HIGH + related MEDIUM).\n";
skill_prompt += "ALLOWED FILES ONLY:\n";
skill_prompt += "- payload/skills/versatile-dev/SKILL.md\n";
skill_prompt += "- payload/skills/versatile-dev/agents/openai.yaml\n";
skill_prompt += "- scripts/validate_bundle.py\n";
skill_prompt += "- tests/test_skill_contract.py\n";
skill_prompt += "LOCKED CONTRACT:\n";
skill_prompt += "1. Frontmatter stays exactly two fields: name and description. No extra YAML keys.\n";
skill_prompt += "2. Rewrite description so Codex 0.147 auto-select includes native documentation / vendor / API research (Luna-first / Terra-second).\n";
skill_prompt += "3. Keep and strengthen when-not: do not use for simple Q&A or status-only work.\n";
skill_prompt += "4. Remove probe / App-task / parent-model / CLI-fallback policy from the description. That policy already lives in the canonical contract body; do not duplicate it in frontmatter.\n";
skill_prompt += "5. Keep these exact test anchors in the description: \"non-trivial repository engineering\" and \"Do not use for simple Q&A or status-only work\".\n";
skill_prompt += "6. Align agents/openai.yaml short_description and default_prompt with the same when/when-not contract. Keep the exact four-line interface schema and display_name \"Versatile Development\". Mention documentation research and the Q&A exclusion.\n";
skill_prompt += "7. Update EXPECTED_DESCRIPTION and EXPECTED_UI in scripts/validate_bundle.py to the new exact strings. Do not change CANONICAL_BLOCKS, DIRECT_LINK_LINES, or other validator rules unless a test forces a one-line adjustment you can justify.\n";
skill_prompt += "8. In test_skill_contract.py, keep existing frontmatter exact-match tests working via EXPECTED_DESCRIPTION. Add an assertion that the description names documentation research.\n";
skill_prompt += "9. Do not change the SKILL.md canonical contract block sentences.\n";
skill_prompt += "After edits run: python3 tests/test_skill_contract.py\n";
skill_prompt += "Return status=done with files_changed and a short summary, or status=blocked with blocked_reason.\n";

let docs_prompt = common_rules(repo);
docs_prompt += "TRACK: AGENTS.md, workflow concurrency, docs-consistency gate (issue #12 advisory items 5-11).\n";
docs_prompt += "ALLOWED FILES ONLY:\n";
docs_prompt += "- AGENTS.md\n";
docs_prompt += "- DEVELOPMENT_PLAN.md\n";
docs_prompt += "- payload/skills/versatile-dev/references/workflow.md\n";
docs_prompt += "- tests/test_docs_consistency.py\n";
docs_prompt += "LOCKED CONTRACT:\n";
docs_prompt += "AGENTS.md:\n";
docs_prompt += "- State that payload/ is source-only. Codex 0.147 discovers skills from <repo>/.agents/skills and $HOME/.agents/skills, and agents from .codex/agents, only after install.sh.\n";
docs_prompt += "- Delete the payload/agents/profiles/ claim. The 13 files in payload/agents/common/ are the only install sources.\n";
docs_prompt += "- describe validate.sh as syntax/structure/diagnostic-probe validation only, not live Codex runtime detection.\n";
docs_prompt += "- Tests verify closed schemas, installer behavior, and replay helpers — not live native routing.\n";
docs_prompt += "- Delete or replace \"The repository has no existing commit history.\"\n";
docs_prompt += "workflow.md Concurrency:\n";
docs_prompt += "- Independent exploration / test / log / specialist review may still run concurrently.\n";
docs_prompt += "- Exclude docs_researcher_luna and docs_researcher_terra from concurrent documentation. Native docs research is PRECHECK then Luna then at most one Terra.\n";
docs_prompt += "tests/test_docs_consistency.py:\n";
docs_prompt += "- Include AGENTS.md in the concatenated docs corpus (readme + plan + AGENTS.md).\n";
docs_prompt += "- Reject stale phrases: payload/agents/profiles/, no existing commit history, exercises runtime detection.\n";
docs_prompt += "- Keep existing derived-fact assertions working. If a required token now belongs in AGENTS.md, put it there rather than weakening the test.\n";
docs_prompt += "DEVELOPMENT_PLAN.md: only edit if a test requires the docs-consistency gate description to mention AGENTS.md. Do not restyle the rest of the plan.\n";
docs_prompt += "After edits run: python3 tests/test_docs_consistency.py\n";
docs_prompt += "Return status=done with files_changed and a short summary, or status=blocked with blocked_reason.\n";

let implement_jobs = [
    #{
        prompt: merge_prompt,
        label: "fix:merge-config",
        capability_mode: "all",
        output_schema: work_schema,
    },
    #{
        prompt: skill_prompt,
        label: "fix:skill-trigger",
        capability_mode: "all",
        output_schema: work_schema,
    },
    #{
        prompt: docs_prompt,
        label: "fix:docs",
        capability_mode: "all",
        output_schema: work_schema,
    },
];

let implement_results = parallel(implement_jobs);
let implement_notes = [];
let i = 0;
for r in implement_results {
    let label = ["merge-config", "skill-trigger", "docs"][i];
    if r == () || !r.success {
        implement_notes.push(label + ": agent failed or empty");
    } else if r.output != () && r.output.status == "blocked" {
        let why = r.output.blocked_reason;
        if why == () { why = "blocked"; }
        implement_notes.push(label + ": blocked: " + why);
    } else if r.output != () && r.output.summary != () {
        implement_notes.push(label + ": " + r.output.summary);
    } else {
        implement_notes.push(label + ": completed without summary");
    }
    i += 1;
}
log("Implement tracks: " + implement_notes.len().to_string());

phase("Precheck");

let precheck_prompt = common_rules(repo);
precheck_prompt += "TRACK: Codex-observable PRECHECK (issue #12 HIGH).\n";
precheck_prompt += "ALLOWED FILES:\n";
precheck_prompt += "- payload/skills/versatile-dev/scripts/runtime_records.py\n";
precheck_prompt += "- payload/skills/versatile-dev/scripts/route_research.py\n";
precheck_prompt += "- payload/skills/versatile-dev/references/model-routing.md\n";
precheck_prompt += "- tests/test_runtime_records.py\n";
precheck_prompt += "- tests/test_routing_state.py\n";
precheck_prompt += "- tests/fixtures/runtime/ (add a new inventory fixture only)\n";
precheck_prompt += "- DEVELOPMENT_PLAN.md only if a derived-token test requires the new kind to appear in public docs\n";
precheck_prompt += "- README.md only if an existing test requires a public-docs token you add\n";
precheck_prompt += "DO NOT edit SKILL.md, openai.yaml, validate_bundle.py EXPECTED_* strings, merge_config.py, install.sh, or AGENTS.md.\n";
precheck_prompt += "LOCKED CONTRACT:\n";
precheck_prompt += "The current fail-closed PRECHECK is unsatisfiable on Codex 0.147 because detect-runtime.sh only writes diagnostic_only=true probes with empty exposed_agent_types, and there is no native_spawn_attempt emitter. Honest helper use then fail-closes every docs task.\n";
precheck_prompt += "Add interface_kind native_capability_inventory:\n";
precheck_prompt += "- Meaning: a closed parent-authored inventory of custom-agent names discovered on the current native spawn interface.\n";
precheck_prompt += "- evidence_source.kind allowed: native_interface_inventory, fixture_native_capability_inventory.\n";
precheck_prompt += "- binary_path must be empty or unknown, like other non-binary interfaces.\n";
precheck_prompt += "- observed may not include effective_agent_type / effective_model / effective_effort. Prefer rejecting observed entirely on this kind.\n";
precheck_prompt += "- This kind must never satisfy native effective-route queries. _preflight_effective_route stays native_spawn_attempt-only.\n";
precheck_prompt += "- detect-runtime.sh must NOT start writing this kind. CLI/App probes stay diagnostic_only=true with empty exposure.\n";
precheck_prompt += "- Install manifest, TOML, catalog, and probes still cannot satisfy PRECHECK and cannot fill effective facts.\n";
precheck_prompt += "route_research.py _precheck accepts exactly one selected record when:\n";
precheck_prompt += "- interface_kind is native_spawn_attempt OR native_capability_inventory;\n";
precheck_prompt += "- diagnostic_only is false;\n";
precheck_prompt += "- multi_agent_generation is v2;\n";
precheck_prompt += "- exposed_agent_types is a canonical list containing both docs_researcher_luna and docs_researcher_terra.\n";
precheck_prompt += "Keep existing rejections: missing record, wrong interface (cli_binary/app_bundled_cli/app_task), diagnostic_only, non-v2, empty/unknown/partial/noncanonical exposure.\n";
precheck_prompt += "model-routing.md: update the PRECHECK prose so Codex-observable same-interface inventory is valid capability evidence for exposure. Do not put probe/TOML/install into that path. Prefer edits outside the canonical HTML comment block. If you must change a canonical sentence, you will break validate_bundle.py — avoid that.\n";
precheck_prompt += "Tests required:\n";
precheck_prompt += "- New fixture tests/fixtures/runtime/native-capability-inventory.json with both researcher types, diagnostic_only=false, v2.\n";
precheck_prompt += "- PRECHECK on that fixture reaches LUNA_PENDING / spawn_luna.\n";
precheck_prompt += "- Inventory missing one type, diagnostic inventory, and probe records still STOP_UNVERIFIED.\n";
precheck_prompt += "- Existing native_spawn_attempt dual-exposure PRECHECK still passes.\n";
precheck_prompt += "- runtime_records rejects effective fields / wrong provenance on the new kind.\n";
precheck_prompt += "- Inventory cannot be queried as an effective native route.\n";
precheck_prompt += "After edits run: python3 tests/test_runtime_records.py && python3 tests/test_routing_state.py\n";
precheck_prompt += "Return status=done with files_changed and a short summary, or status=blocked with blocked_reason.\n";

let precheck_result = agent(precheck_prompt, #{
    label: "fix:precheck",
    capability_mode: "all",
    output_schema: work_schema,
});
if precheck_result == () || !precheck_result.success {
    log("PRECHECK track failed or returned empty");
} else if precheck_result.output != () && precheck_result.output.summary != () {
    log(precheck_result.output.summary);
}

phase("Verify");

let verify_prompt = "";
verify_prompt += "Repository root: " + repo + "\n";
verify_prompt += "Run the offline gates for this repo and report whether they passed.\n";
verify_prompt += "Working directory must be the repository root.\n";
verify_prompt += "Run these commands with run_terminal_command, in order, without changing files:\n";
verify_prompt += "1. ./validate.sh\n";
verify_prompt += "2. ./tests/run.sh\n";
verify_prompt += "Set passed=true only if both exit 0. If either fails, set passed=false and put the failing command names plus the relevant tail of stderr/stdout in failures.\n";
verify_prompt += "Do not commit. Do not rerun package.sh unless validate/tests already passed and you only need a packaging check — skip package.sh.\n";

let verify_result = agent(verify_prompt, #{
    label: "verify:offline-gates",
    capability_mode: "execute",
    output_schema: verify_schema,
});

let gates_passed = false;
let verify_failures = "";
if verify_result != () && verify_result.success && verify_result.output != () {
    if verify_result.output.passed == true {
        gates_passed = true;
    }
    if verify_result.output.failures != () {
        verify_failures = verify_result.output.failures;
    } else if verify_result.output.summary != () {
        verify_failures = verify_result.output.summary;
    }
} else {
    verify_failures = "verify agent failed or returned no evidence";
}

if !gates_passed {
    log("Offline gates failed; launching one repair pass");
    let repair_prompt = common_rules(repo);
    repair_prompt += "TRACK: repair remaining test/validate failures after the issue #12 implementation.\n";
    repair_prompt += "You may edit any project file required to restore green ./validate.sh and ./tests/run.sh.\n";
    repair_prompt += "Do not weaken tests to hide a broken contract. Do not commit.\n";
    repair_prompt += "Preserve the locked contracts:\n";
    repair_prompt += "- merge_config inserts missing keys only unless --force-config.\n";
    repair_prompt += "- SKILL.md description names documentation research and excludes simple Q&A; policy stays out of frontmatter.\n";
    repair_prompt += "- PRECHECK accepts native_capability_inventory or non-diagnostic native_spawn_attempt with same-record dual exposure; probes/TOML/install still fail closed and cannot fill effective facts.\n";
    repair_prompt += "- AGENTS.md no longer claims profiles/, live payload layout, runtime detection, live routing tests, or empty git history.\n";
    repair_prompt += "Reported failures:\n";
    repair_prompt += verify_failures + "\n";
    repair_prompt += "Read the failing test output, fix the cause, then rerun ./validate.sh and ./tests/run.sh yourself.\n";
    repair_prompt += "Return status=done only if both gates exit 0.\n";
    let repair_result = agent(repair_prompt, #{
        label: "repair:offline-gates",
        capability_mode: "all",
        output_schema: work_schema,
    });
    if repair_result != () && repair_result.success && repair_result.output != () && repair_result.output.summary != () {
        log(repair_result.output.summary);
    }
}

phase("Review");

let review_prompt = "";
review_prompt += "Repository root: " + repo + "\n";
review_prompt += "Read-only review of whether issue #12 findings were actually fixed in this checkout.\n";
review_prompt += "Use only read_file, grep, and list_dir. Read the current files; do not trust earlier summaries.\n";
review_prompt += "Check each finding id:\n";
review_prompt += "H1 skill-trigger: SKILL.md description names documentation research and excludes simple Q&A; probe/App policy is not the trigger.\n";
review_prompt += "H2 merge-overwrite: merge_config.py keeps present [agents] values unless --force-config; --check without force accepts user values.\n";
review_prompt += "H3 precheck: _precheck accepts native_capability_inventory or non-diagnostic native_spawn_attempt with dual exposure; detect-runtime probes still cannot pass; effective route still requires native_spawn_attempt.\n";
review_prompt += "M4 openai.yaml short_description/default_prompt aligned with the skill when/when-not contract.\n";
review_prompt += "M5 AGENTS.md no longer documents payload/agents/profiles/.\n";
review_prompt += "M6 workflow.md excludes the two docs researchers from concurrent documentation.\n";
review_prompt += "M7 AGENTS.md states payload/ is source-only and install is required for Codex discovery.\n";
review_prompt += "M8 AGENTS.md does not claim validate.sh exercises live Codex runtime detection.\n";
review_prompt += "M9 AGENTS.md does not claim offline tests verify live native routing.\n";
review_prompt += "M10 test_docs_consistency.py reads AGENTS.md and rejects the stale phrases.\n";
review_prompt += "L11 AGENTS.md no longer claims the repository has no commit history.\n";
review_prompt += "For each id set status fixed/open/partial with file:line evidence you actually read.\n";
review_prompt += "notes should be a short overall verdict.\n";

let review_result = agent(review_prompt, #{
    label: "review:issue-12",
    capability_mode: "read-only",
    output_schema: review_schema,
});

let remaining = [];
let notes = "review produced no structured output";
if review_result != () && review_result.success && review_result.output != () {
    if review_result.output.remaining != () {
        remaining = review_result.output.remaining;
    }
    if review_result.output.notes != () {
        notes = review_result.output.notes;
    }
}

let report = "";
report += "# Issue #12 fix workflow result\n\n";
report += notes + "\n\n";
report += "## Implement notes\n";
for line in implement_notes {
    report += "- " + line + "\n";
}
report += "\n## Finding review\n";
for item in remaining {
    let ident = item.id;
    let st = item.status;
    let ev = item.evidence;
    if ident == () { ident = "?"; }
    if st == () { st = "?"; }
    if ev == () { ev = ""; }
    report += "- " + ident + " [" + st + "]: " + ev + "\n";
}

let report_path = write_scratch_file("issue-12-fix-report.md", report);
complete(#{
    report_path: report_path,
    notes: notes,
    remaining: remaining,
});
