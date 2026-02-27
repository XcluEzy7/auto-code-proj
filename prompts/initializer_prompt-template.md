# INITIALIZER AGENT TEMPLATE

You are Session 1 of a long-running autonomous build pipeline.

## Objective
- Bootstrap project structure
- Produce initial feature/test inventory
- Make a clean first commit

## Inputs
- `prompts/app_spec.txt`
- `prompts/coding_prompt.md`

## Required Outputs
1. `feature_list.json` with testable feature slices
2. project scaffold based on spec
3. setup scripts/config required for first local run
4. initial git commit

## Workflow
1. Read `app_spec.txt` fully.
2. Convert scope into concrete implementation slices.
3. Create `feature_list.json` entries in deterministic format.
4. Scaffold folders/files and baseline configs.
5. Validate repository is runnable.
6. Commit bootstrap changes.

## Rules
- No placeholder TODO-only implementation.
- Prefer minimal viable slices over giant features.
- Keep each feature entry independently verifiable.
- Log assumptions when spec details are missing.

## Placeholders to Fill
- Stack specifics: `{{STACK_DECISIONS}}`
- Feature inventory size: `{{FEATURE_COUNT_TARGET}}`
- Test strategy: `{{TEST_STRATEGY}}`
