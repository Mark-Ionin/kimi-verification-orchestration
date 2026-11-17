import hashlib
import json
from pathlib import Path

import pytest
import yaml

from test_validate_package import agent_card, issue_codes, load_manifest, save_manifest, write_minimal_package
from validate_package import validate_package
from work_subagent_verification import package_revision


PROFILE = {
    "name": "code-example",
    "models": {
        "k3.1-pro": {"display_name": "K3.1 Pro"},
        "kimi-for-coding": {"display_name": "K2.8 Preview"},
    },
    "aliases": [
        {"model": model, "effort": effort, "runtime_alias": f"{model}-{effort}"}
        for model in ("k3.1-pro", "kimi-for-coding")
        for effort in ("low", "high", "max")
    ],
}


def write_schema3_package(root: Path) -> dict:
    write_minimal_package(root)
    manifest = load_manifest(root)
    manifest.update(
        {
            "schema_version": 3,
            "scope": {"objective": "test", "acceptance_criteria": ["result"]},
            "execution": {
                "owner": "kimi_code",
                "mode": "team",
                "stop_policy": None,
                "implementation_authorized": False,
                "continue_after_preflight": True,
                "approval": {"approved_at": None, "approved_by": None, "evidence": None},
            },
            "permissions": {
                "subagents": "allow",
                "verifier_subagent": "allow",
                "swarm": "deny",
                "approved_agents": ["A1", "A2", "A4"],
                "max_parallel": 1,
                "evidence": "RUN_LOG.md",
            },
            "package_check": {
                "status": "not_started",
                "agent": "A4",
                "result": "verification/PACKAGE_CHECK.json",
                "log": "verification/PACKAGE_CHECK.log",
            },
            "decision_checkpoints": [],
            "implementation": {"status": "not_started", "scope": "test", "draft_outputs": []},
            "model_profile": {
                "name": "code-example",
                "path": "model-profile.yaml",
                "sha256": "",
            },
        }
    )
    manifest["agents"].append(
        {
            "id": "A4",
            "role": "package_checker",
            "path": "agents/A4_package_checker/AGENT.md",
            "capability": "deterministic_package_check",
            "required_skills": [],
            "optional_skills": [],
        }
    )
    (root / "agents" / "A4_package_checker").mkdir()
    (root / "agents" / "A4_package_checker" / "AGENT.md").write_text(
        agent_card("A4", "deterministic_package_check").replace("## Роль\ngenerator", "## Роль\npackage_checker"),
        encoding="utf-8",
    )
    manifest["tasks"][0].update(
        {"model": "k3.1-pro", "effort": "low", "reason": "General implementation.", "assignment_source": "kimi"}
    )
    manifest["tasks"][1].update(
        {
            "model": "k3.1-pro",
            "effort": "high",
            "reason": "Independent verification uses the fixed strong assignment.",
            "assignment_source": "fixed_policy",
        }
    )
    manifest["verification"].update(
        {"status": "not_started", "independent_required": True, "open_p0": 0, "open_p1": 0, "open_p2": 0}
    )
    profile_text = yaml.safe_dump(PROFILE, allow_unicode=True, sort_keys=False)
    (root / "model-profile.yaml").write_text(profile_text, encoding="utf-8")
    manifest["model_profile"]["sha256"] = hashlib.sha256((root / "model-profile.yaml").read_bytes()).hexdigest()
    save_manifest(root, manifest)
    (root / "RUN_LOG.md").write_text(
        "- действие: стартовое согласование пользователя\n"
        "- доказательство: исполнительные субагенты A1, верификатор A2, package_checker A4; swarm deny\n"
        "- итог: разрешения подтверждены\n"
        "- открытые замечания: нет\n",
        encoding="utf-8",
    )
    return manifest


def add_model_reviewer(root: Path) -> None:
    manifest = load_manifest(root)
    manifest["agents"].append(
        {
            "id": "A5",
            "role": "model_reviewer",
            "path": "agents/A5_model_reviewer/AGENT.md",
            "capability": "model_assignment_review",
            "required_skills": [],
            "optional_skills": [],
        }
    )
    manifest["permissions"]["approved_agents"].append("A5")
    manifest["tasks"].append(
        {
            "id": "TR",
            "agent": "A5",
            "kind": "model_review",
            "depends_on": [],
            "inputs": ["MANIFEST.yaml"],
            "outputs": ["verification/MODEL_REVIEW.md"],
            "model": "k3.1-pro",
            "effort": "high",
            "reason": "Fixed policy assignment for model review; recursive review is forbidden.",
            "assignment_source": "fixed_policy",
        }
    )
    (root / "agents" / "A5_model_reviewer").mkdir()
    (root / "agents" / "A5_model_reviewer" / "AGENT.md").write_text(
        agent_card("A5", "model_assignment_review").replace("## Роль\ngenerator", "## Роль\nmodel_reviewer"),
        encoding="utf-8",
    )
    save_manifest(root, manifest)


def test_valid_schema3_team_package(tmp_path):
    write_schema3_package(tmp_path)
    assert issue_codes(tmp_path) == set()


@pytest.mark.parametrize("field", ["model", "effort", "reason"])
def test_schema3_task_requires_model_effort_and_reason(tmp_path, field):
    manifest = write_schema3_package(tmp_path)
    del manifest["tasks"][0][field]
    save_manifest(tmp_path, manifest)
    assert "invalid_model_assignment" in issue_codes(tmp_path)


def test_schema3_rejects_empty_reason(tmp_path):
    manifest = write_schema3_package(tmp_path)
    manifest["tasks"][0]["reason"] = "  "
    save_manifest(tmp_path, manifest)
    assert "invalid_model_assignment" in issue_codes(tmp_path)


@pytest.mark.parametrize(
    ("model", "effort"),
    [("unknown-model", "low"), ("k3.1-pro", "medium"), ("kimi-for-coding", "low")],
)
def test_schema3_rejects_pair_without_exact_runtime_alias(tmp_path, model, effort):
    manifest = write_schema3_package(tmp_path)
    manifest["tasks"][0]["model"] = model
    manifest["tasks"][0]["effort"] = effort
    if model == "kimi-for-coding":
        profile = yaml.safe_load((tmp_path / "model-profile.yaml").read_text(encoding="utf-8"))
        profile["aliases"] = [item for item in profile["aliases"] if item["model"] != model]
        text = yaml.safe_dump(profile, allow_unicode=True, sort_keys=False)
        (tmp_path / "model-profile.yaml").write_text(text, encoding="utf-8")
        manifest["model_profile"]["sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    save_manifest(tmp_path, manifest)
    assert "invalid_model_assignment" in issue_codes(tmp_path)


def test_schema3_rejects_empty_runtime_alias(tmp_path):
    manifest = write_schema3_package(tmp_path)
    profile = yaml.safe_load((tmp_path / "model-profile.yaml").read_text(encoding="utf-8"))
    profile["aliases"][0]["runtime_alias"] = ""
    text = yaml.safe_dump(profile, allow_unicode=True, sort_keys=False)
    (tmp_path / "model-profile.yaml").write_text(text, encoding="utf-8")
    manifest["model_profile"]["sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    save_manifest(tmp_path, manifest)
    assert "invalid_model_profile" in issue_codes(tmp_path)


def test_schema3_rejects_profile_sha256_mismatch(tmp_path):
    manifest = write_schema3_package(tmp_path)
    manifest["model_profile"]["sha256"] = "0" * 64
    save_manifest(tmp_path, manifest)
    assert "invalid_model_profile" in issue_codes(tmp_path)


def test_schema3_rejects_profile_name_mismatch(tmp_path):
    manifest = write_schema3_package(tmp_path)
    manifest["model_profile"]["name"] = "another-profile"
    save_manifest(tmp_path, manifest)
    assert "invalid_model_profile" in issue_codes(tmp_path)


def test_profile_file_is_part_of_package_revision(tmp_path):
    write_schema3_package(tmp_path)
    before = package_revision(load_manifest(tmp_path), tmp_path)
    (tmp_path / "model-profile.yaml").write_text("name: changed\n", encoding="utf-8")
    after = package_revision(load_manifest(tmp_path), tmp_path)
    assert before != after


def test_schema3_team_execution_requires_generator_permission_in_code(tmp_path):
    manifest = write_schema3_package(tmp_path)
    manifest["status"] = "running"
    manifest["implementation"]["status"] = "in_progress"
    manifest["permissions"]["subagents"] = "deny"
    save_manifest(tmp_path, manifest)
    assert "missing_subagent_permission" in issue_codes(tmp_path)


def test_schema3_solo_requires_explicit_user_choice(tmp_path):
    manifest = write_schema3_package(tmp_path)
    manifest["execution"]["mode"] = "solo"
    manifest["status"] = "running"
    manifest["implementation"]["status"] = "in_progress"
    save_manifest(tmp_path, manifest)
    assert "missing_solo_approval" in issue_codes(tmp_path)


def test_schema3_solo_with_explicit_user_choice_does_not_require_generators(tmp_path):
    manifest = write_schema3_package(tmp_path)
    manifest["execution"]["mode"] = "solo"
    manifest["status"] = "running"
    manifest["implementation"]["status"] = "in_progress"
    manifest["permissions"]["subagents"] = "deny"
    save_manifest(tmp_path, manifest)
    with (tmp_path / "RUN_LOG.md").open("a", encoding="utf-8") as log:
        log.write("явный выбор пользователя: solo\n")
    assert "missing_subagent_permission" not in issue_codes(tmp_path)
    assert "missing_solo_approval" not in issue_codes(tmp_path)


def test_schema3_discretionary_high_requires_model_review_task(tmp_path):
    manifest = write_schema3_package(tmp_path)
    manifest["tasks"][0]["effort"] = "high"
    manifest["tasks"][0]["reason"] = "Risky migration needs discretionary high effort."
    save_manifest(tmp_path, manifest)
    assert "missing_model_review" in issue_codes(tmp_path)


def test_schema3_discretionary_max_requires_model_review_task(tmp_path):
    manifest = write_schema3_package(tmp_path)
    manifest["tasks"][0]["effort"] = "max"
    save_manifest(tmp_path, manifest)
    assert "missing_model_review" in issue_codes(tmp_path)


def test_schema3_discretionary_high_accepts_prior_model_review(tmp_path):
    manifest = write_schema3_package(tmp_path)
    add_model_reviewer(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["tasks"][0].update(
        {
            "effort": "high",
            "reason": "Risky migration needs discretionary high effort.",
            "model_review_task": "TR",
        }
    )
    manifest["tasks"][0]["depends_on"] = ["TR"]
    save_manifest(tmp_path, manifest)
    assert "missing_model_review" not in issue_codes(tmp_path)


def test_schema3_model_review_must_precede_execution_task(tmp_path):
    manifest = write_schema3_package(tmp_path)
    add_model_reviewer(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["tasks"][0].update({"effort": "high", "model_review_task": "TR"})
    save_manifest(tmp_path, manifest)
    assert "missing_model_review" in issue_codes(tmp_path)


@pytest.mark.parametrize("source", ["user_override", "work_session_default"])
def test_schema3_user_choices_do_not_require_discretionary_review(tmp_path, source):
    manifest = write_schema3_package(tmp_path)
    manifest["tasks"][0].update({"effort": "max", "assignment_source": source})
    save_manifest(tmp_path, manifest)
    assert "missing_model_review" not in issue_codes(tmp_path)


def test_schema3_fixed_verifier_assignment_does_not_require_review(tmp_path):
    write_schema3_package(tmp_path)
    assert "missing_model_review" not in issue_codes(tmp_path)


def test_work_session_defaults_apply_to_every_task(tmp_path):
    manifest = write_schema3_package(tmp_path)
    manifest["execution"].update(
        {
            "owner": "kimi_work",
            "stop_policy": "cooperative",
            "session_defaults": {"model": "kimi-for-coding", "effort": "high"},
        }
    )
    for task in manifest["tasks"]:
        task["assignment_source"] = "work_session_default"
    manifest["tasks"][0].update({"model": "kimi-for-coding", "effort": "high"})
    save_manifest(tmp_path, manifest)
    assert "session_default_mismatch" in issue_codes(tmp_path)


def test_work_session_defaults_accept_matching_verifier(tmp_path):
    manifest = write_schema3_package(tmp_path)
    manifest["execution"].update(
        {
            "owner": "kimi_work",
            "stop_policy": "cooperative",
            "session_defaults": {"model": "kimi-for-coding", "effort": "high"},
        }
    )
    for task in manifest["tasks"]:
        task.update(
            {
                "model": "kimi-for-coding",
                "effort": "high",
                "assignment_source": "work_session_default",
            }
        )
    save_manifest(tmp_path, manifest)
    assert "session_default_mismatch" not in issue_codes(tmp_path)


def test_schema2_does_not_require_new_model_fields(tmp_path):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["schema_version"] = 2
    save_manifest(tmp_path, manifest)
    assert "invalid_model_assignment" not in issue_codes(tmp_path)


def make_ready_for_code(root: Path) -> None:
    manifest = load_manifest(root)
    manifest["status"] = "ready_for_kimi_code"
    manifest["execution"]["implementation_authorized"] = True
    manifest["execution"]["approval"] = {
        "approved_at": "2026-11-17T14:00:00+03:00",
        "approved_by": "user",
        "evidence": "RUN_LOG.md",
    }
    save_manifest(root, manifest)


def seal_schema3_package_check(root: Path) -> None:
    manifest = load_manifest(root)
    manifest["package_check"]["status"] = "passed"
    save_manifest(root, manifest)
    validator = (Path(__file__).parents[1] / "scripts" / "validate_package.py").resolve()
    record = {
        "record_type": "actual_validator_run",
        "validator_path": str(validator),
        "command": f'python "{validator}" "{root.resolve()}"',
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
        "package_revision": package_revision(manifest, root),
        "trace": {"invocation_id": "schema3-package-check", "role": "package_checker"},
    }
    (root / manifest["package_check"]["result"]).write_text(json.dumps(record), encoding="utf-8")
    (root / manifest["package_check"]["log"]).write_text(
        "ID вызова: schema3-package-check\nКод выхода: 0\n", encoding="utf-8"
    )


def test_schema3_ready_code_requires_actual_package_checker(tmp_path):
    write_schema3_package(tmp_path)
    make_ready_for_code(tmp_path)
    assert "package_check_required" in issue_codes(tmp_path)


def test_schema3_ready_code_accepts_actual_package_checker(tmp_path):
    write_schema3_package(tmp_path)
    make_ready_for_code(tmp_path)
    seal_schema3_package_check(tmp_path)
    assert issue_codes(tmp_path) == set()


def test_schema3_ready_code_requires_start_approval(tmp_path):
    write_schema3_package(tmp_path)
    make_ready_for_code(tmp_path)
    seal_schema3_package_check(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["execution"]["approval"] = None
    save_manifest(tmp_path, manifest)
    assert "missing_approval" in issue_codes(tmp_path)


def test_schema3_preflight_requires_machine_evidence(tmp_path):
    manifest = write_schema3_package(tmp_path)
    manifest["status"] = "preflight_passed"
    save_manifest(tmp_path, manifest)
    assert "missing_evidence" in issue_codes(tmp_path)


def test_schema3_profile_change_makes_package_check_stale(tmp_path):
    write_schema3_package(tmp_path)
    make_ready_for_code(tmp_path)
    seal_schema3_package_check(tmp_path)
    with (tmp_path / "model-profile.yaml").open("a", encoding="utf-8") as profile:
        profile.write("changed: true\n")
    assert "stale_package_check" in issue_codes(tmp_path)


def test_schema3_team_code_requires_approved_generation_agent(tmp_path):
    manifest = write_schema3_package(tmp_path)
    manifest["status"] = "running"
    manifest["implementation"]["status"] = "in_progress"
    manifest["permissions"]["approved_agents"] = ["A2", "A4"]
    save_manifest(tmp_path, manifest)
    assert "unapproved_agent" in issue_codes(tmp_path)


def test_schema3_verified_result_requires_revision_bound_report(tmp_path):
    write_schema3_package(tmp_path)
    make_ready_for_code(tmp_path)
    seal_schema3_package_check(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["status"] = "result_verified"
    manifest["implementation"]["status"] = "implemented"
    manifest["verification"]["status"] = "passed"
    save_manifest(tmp_path, manifest)
    (tmp_path / "result.md").write_text("result\n", encoding="utf-8")
    (tmp_path / "verification" / "REPORT.md").write_text(
        "- действие: независимая проверка\n"
        "- доказательство: вызов verifier-call\n"
        "- итог: критерии выполнены\n"
        "- открытые замечания: нет\n",
        encoding="utf-8",
    )
    with (tmp_path / "RUN_LOG.md").open("a", encoding="utf-8") as log:
        log.write("A2 | verifier | ID вызова: verifier-call\n")
    assert "invalid_report_metadata" in issue_codes(tmp_path)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("execution", "mode", []),
        ("manifest", "status", []),
        ("task", "assignment_source", []),
    ],
)
def test_schema3_unhashable_control_fields_return_p1_without_exception(tmp_path, section, field, value):
    manifest = write_schema3_package(tmp_path)
    target = manifest if section == "manifest" else manifest["execution"] if section == "execution" else manifest["tasks"][0]
    target[field] = value
    save_manifest(tmp_path, manifest)
    issues = validate_package(tmp_path)
    assert any(issue.severity == "P1" for issue in issues)


def test_schema3_invalid_review_dependencies_return_p1_without_exception(tmp_path):
    manifest = write_schema3_package(tmp_path)
    manifest["tasks"][0].update({"effort": "high", "depends_on": None, "model_review_task": "TR"})
    save_manifest(tmp_path, manifest)
    issues = validate_package(tmp_path)
    assert any(issue.severity == "P1" for issue in issues)


@pytest.mark.parametrize("effort", ["high", "max"])
def test_discretionary_practical_checks_require_model_review(tmp_path, effort):
    manifest = write_schema3_package(tmp_path)
    manifest["tasks"][0].update(
        {
            "kind": "automated_and_practical_checks",
            "effort": effort,
            "reason": "Practical execution checks need discretionary elevated effort.",
        }
    )
    save_manifest(tmp_path, manifest)
    assert "missing_model_review" in issue_codes(tmp_path)


def test_discretionary_practical_checks_accept_prior_model_review(tmp_path):
    manifest = write_schema3_package(tmp_path)
    add_model_reviewer(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["tasks"][0].update(
        {
            "kind": "automated_and_practical_checks",
            "effort": "high",
            "depends_on": ["TR"],
            "model_review_task": "TR",
        }
    )
    save_manifest(tmp_path, manifest)
    assert "missing_model_review" not in issue_codes(tmp_path)


def test_practical_checks_user_override_does_not_require_review(tmp_path):
    manifest = write_schema3_package(tmp_path)
    manifest["tasks"][0].update(
        {
            "kind": "automated_and_practical_checks",
            "effort": "max",
            "assignment_source": "user_override",
        }
    )
    save_manifest(tmp_path, manifest)
    assert "missing_model_review" not in issue_codes(tmp_path)
