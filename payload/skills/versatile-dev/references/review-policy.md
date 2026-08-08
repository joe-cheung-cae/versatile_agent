# Independent review policy

## Contents

- [Reviewer independence](#reviewer-independence)
- [Finding quality](#finding-quality)
- [Lead triage](#lead-triage)
- [Verdicts](#verdicts)

## Reviewer independence

Use an agent that did not author the implementation. Review the actual diff and
surrounding code. Remain behaviorally read-only even when the host sandbox is
broader; never claim OS-enforced read-only unless observed.

## Finding quality

Every actionable finding must include:

- severity;
- file and symbol or tight line reference;
- concrete failure mode;
- why it matters;
- evidence or reproduction path;
- smallest credible fix;
- missing test, when applicable.

Omit style-only comments unless style hides a correctness or maintenance risk.

## Lead triage

For each finding, classify it as:

- **validated:** supported by code or a reproduction;
- **plausible:** needs a focused check before acceptance;
- **invalid:** contradicted by repository evidence;
- **out of scope:** real but unrelated to the requested change.

Return validated and relevant plausible findings to the bounded writer. Record
why invalid or out-of-scope findings were not applied.

Any correction invalidates the prior review verdict. Rerun affected tests and
obtain a fresh focused review.

## Verdicts

- `SHIP`: no unresolved blocking findings; verification is proportionate.
- `FIX_FIRST`: one or more bounded findings must be corrected.
- `RETHINK`: the task model or architecture is invalid and requires re-plan.
