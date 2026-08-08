# Subagent task contract

Use exactly these five sections for every delegated task.

## 1. Objective

State one concrete outcome and why it matters. Separate analysis from changes.

## 2. Ownership

Name the owned files, module, or bounded responsibility. State whether the task
is read-only or may edit. Tell the agent it is not alone in the codebase, must
preserve unrelated edits, and must adapt to concurrent work.

## 3. Inputs and evidence

Provide only relevant requirements, repository rules, paths, symbols, known
facts, and prior verified findings. Do not paste the entire parent history.

## 4. Constraints and requirements

State API/ABI, compatibility, security, performance, numerical, style, and
scope limits. Identify forbidden external or destructive actions.

## 5. Verification and handoff

Specify commands or evidence required, stopping conditions, and the response
shape. Require:

- concise outcome;
- changed or inspected files;
- verification evidence;
- assumptions and unresolved risks;
- artifacts or exact references needed by the lead.

Subagents never declare the whole user task complete.
