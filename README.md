# Kimi Verification Orchestration

A portable skill for package-based task orchestration, explicit model and effort assignments, and independent result verification in Kimi Code and Kimi Work.

## What is included

- Schema 3 packages with `team` mode by default.
- `solo` only after an explicit user choice. Independent verification still uses a separate subagent.
- Required `model`, `effort`, and task-specific `reason` for every schema 3 task.
- A user-editable YAML profile that maps every allowed `model + effort` pair to a `runtime_alias`.
- SHA-256 profile binding and stale package-check detection after profile changes.
- Separate `package_checker` runs in both Code and Work.
- Model review before discretionary `high` or `max` execution assignments.
- Work session defaults applied to creation and execution, including verifier and package checker.
- Legacy schema 2 support without new mandatory fields.
- Local validation and tests. No GitHub Actions, installer, automatic configuration changes, or publication steps.

Internal agent rules remain in Russian. Public setup and examples are in English.

## Repository layout

- `SKILL.md`: skill entry point.
- `instructions/`: canonical routing rules, adapters, registries, and the package template.
- `scripts/`: shared package validator and workflow checks.
- `tests/`: local regression tests.
- `requirements.txt` and `requirements-dev.txt`: runtime and test dependencies.

## Manual installation for Kimi Code

No installer is provided or required.

1. Copy this complete directory to your chosen Kimi Code skill directory, for example `~/.agents/skills/kimi-verification-orchestration/`. Keep `SKILL.md`, `instructions/`, and `scripts/` together.
2. Alternatively, copy `instructions/` into a managed project instruction directory and connect `AGENTS.md` as project instructions.
3. Reload instructions or start a new Kimi Code session.
4. Do not replace your persistent `config.toml`. The skill does not modify it.

The installed validator must remain at `<skill-root>/scripts/validate_package.py`.

## Manual installation for Kimi Work

1. Import or copy this complete directory through the manual project-skill workflow available in your Work environment.
2. Preserve `SKILL.md`, `instructions/`, and `scripts/` as one unit.
3. Select the model and effort for the Work session before creating a package.
4. Do not change persistent Kimi Code configuration for a Work installation.

The Work adapter uses these session-level mappings:

- `Standard -> low`
- `Advanced -> high`
- `Extreme -> max`

The selected defaults apply to package creation and execution and to every subagent, including the verifier and `package_checker`. Each manifest task records the actual values with `assignment_source: work_session_default`. This edition does not claim that Work supports different session effort values for individual subagents within one session.

## Create a package

Copy the template:

```bash
cp -R "<skill-root>/instructions/templates/task-package" "<absolute-task-package>"
```

Edit `MANIFEST.yaml` and the referenced files:

1. Set the objective, scope, acceptance criteria, inputs, outputs, roles, and DAG.
2. Keep `execution.mode: team` unless the user explicitly selects `solo`.
3. Assign `model`, `effort`, `reason`, and `assignment_source` to every task.
4. Customize `model-profile.yaml` for aliases actually available in your environment.
5. Update `model_profile.sha256` after every profile edit.
6. Record the user's starting approval and exact role permissions in `RUN_LOG.md`.

A separate `package_checker` must run:

```bash
python "<skill-root>/scripts/validate_package.py" "<absolute-task-package>"
```

The checker records the command, exit code, stdout, stderr, JSON result, `package_revision`, and invocation trace. The creating main session does not replace this role.

## Start a Code package in a new session

A Code session that creates a package does not execute it. After a successful package check, it saves `LAUNCH.md` and immediately ends its current response. In that same session, execution pre-flight, DAG or executor-subagent launch, implementation, and package tests are forbidden. Starting approval, `implementation_authorized`, `continue_after_preflight`, other permissions, and later user messages do not override this prohibition.

The user manually starts a new main Code session using the command and first message from `LAUNCH.md`. Only that new session continues immediately after pre-flight without another starting approval within the existing permissions.

Pre-flight must confirm the assigned model, effort, and every runtime alias. Unavailability is a blocker. Hidden fallback is forbidden; a replacement requires renewed user agreement and package revalidation.

## Example model profile

The template profile is an example, not a hard requirement for every user.

| Logical model | Display name | Typical use |
| --- | --- | --- |
| `k3.1-pro` | K3.1 Pro | General work, research, ambiguous requirements, cross-component changes, complex implementation, and verification |
| `kimi-for-coding` | K2.8 Preview | Clearly decomposed coding cards, local fixes, refactoring, tests, and mechanical transformations |

Example efforts are `low`, `high`, and `max`. Each pair has its own illustrative alias, such as `k3.1-pro-low`. Replace aliases with values exposed by your actual subagent runtime.

Example policy:

- K3.1 low is the default general executor.
- Choose K3.1 when uncertain.
- Use K3.1 high for complex or risky implementation and independent verification.
- Choose K2.8 effort by task complexity.
- Use K2.8 max only by an orchestrator decision with a concrete reason why lower effort is insufficient.
- The example verifier and model reviewer use K3.1 high.

Explicit user choices take priority and are recorded as `user_override`. Work session defaults take priority over the fixed verifier assignment in the Code example.

## Discretionary high and max review

An execution task assigned discretionary `high` or `max`, including generation and automated/practical checks, must reference a preceding `model_review` task through `model_review_task` and `depends_on`.

The model reviewer assesses only whether the model and effort fit the task card and reason. It does not replace deterministic package checking or assess the future result. Fixed verifier and model-reviewer assignments, user overrides, and Work session defaults need no additional review. Recursive review is forbidden.

After a failed run, the orchestrator may escalate the same task with a recorded reason. Escalation to discretionary high or max requires a fresh review. Changing roles or task boundaries requires separate user approval.

## Local checks

See [RELEASE.md](RELEASE.md) for the combined pre-release gate, accepted release risks, and manual GitHub publication alternatives. The harness never publishes the repository.

Create an isolated Python environment, install the requirements, and run:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 python scripts/validate_package.py instructions/templates/task-package
```

The tests cover legacy behavior, schema 3 assignments, profile hashes and revisions, DAG and permission checks, model review, Work defaults, package-check evidence, and the distributable layout. Package-check evidence must include an absolute `validator_path`, the same absolute validator in its command, and an absolute package path rather than a path relative to the package working directory.

## Verification status and limits

Code pilot status: PARTIAL. The available Agent tool accepts `model` and `subagent_type`, but has no `effort` argument. Therefore a real model call and runtime alias were observed, while `effort: low` was not passed or confirmed. This environment blocker remains open; no fallback or inferred effort is claimed.

No human interactive launch was performed. Separate non-interactive CLI processes were started by the agent and do not satisfy the manual-launch requirement. That manual requirement remains unverified.

The earlier execution process violated stop-on-effort by invoking A2 after recording unavailable effort. That historical violation remains in the evidence and is not rewritten or claimed as fixed. A remediation recheck correctly stopped with `status: blocked`, one open P1, zero Agent calls, and no new marker. This confirms stop behavior only in that recheck and does not retroactively complete the earlier pilot.

The earlier package-check coordinator timed out after its A4 subagents and successful validator runs. Its main session ID and coordinator summary remain unavailable even though the A4 and validator traces exist.

Real Work pilot: not performed in this revision. Static tests are not a substitute for a complete Code pilot, a human interactive launch, actual effort assignment, or independent verification. Consult the accompanying verification evidence for what was actually exercised.

No commit, remote repository creation, push, installation, or publication is performed by this source package. Those actions require separate permission.

## License

MIT. See `LICENSE`.
