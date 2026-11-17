import copy
import hashlib
import json
import shutil
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]
TEMPLATE = ROOT / "instructions" / "templates" / "task-package"
sys.path.insert(0, str(ROOT / "scripts"))
import validate_package as validator
from validate_package import validate_package


def load_manifest(root: Path) -> dict:
    return yaml.safe_load((root / "MANIFEST.yaml").read_text(encoding="utf-8"))


def save_manifest(root: Path, manifest: dict) -> None:
    (root / "MANIFEST.yaml").write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def issue_codes(root: Path) -> set[str]:
    return {issue.code for issue in validate_package(root)}


def agent_card(role: str, capability: str) -> str:
    return f"""# Проверяющий агент

## Роль
{role}

## Задача
Запустить общий валидатор и сохранить фактический результат.

## Профиль способностей
{capability}

## Обязательные скиллы
нет

## Опциональные скиллы
нет

## Разрешённые действия
Запускать валидатор и сохранять его вывод без исправления пакета.

## Вход
Путь к пакету и валидатору.

## Выход
Машиночитаемый результат и журнал запуска.

## Definition of Done
Сохранены команда, код выхода, stdout, stderr и след вызова.

## Требования проверки
Вердикт принадлежит только общему валидатору.

## Условия отката
После изменения пакета повторяет проверку новый экземпляр.
"""


def approval_text() -> str:
    return (
        "# Журнал\n\n"
        "- действие: стартовое согласование пользователя\n"
        "- доказательство: пользователь разрешил исполнительных субагентов A2, "
        "верификатора A3, package_checker A4 и swarm с max_parallel=2\n"
        "- итог: разрешения subagents, verifier_subagent и swarm подтверждены\n"
        "- открытые замечания: нет\n"
    )


def static_package_revision(root: Path) -> str:
    manifest = load_manifest(root)
    static = copy.deepcopy(manifest)
    static.pop("status", None)
    static.pop("package_check", None)
    static.get("implementation", {}).pop("status", None)
    static.get("implementation", {}).pop("draft_outputs", None)
    for field in ("status", "open_p0", "open_p1", "open_p2"):
        static.get("verification", {}).pop(field, None)
    files = {
        "MANIFEST.yaml": hashlib.sha256(
            json.dumps(static, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    }
    relative_files = {"00_ORCHESTRATOR.md", "LAUNCH.md", "verification/PLAN.md"}
    relative_files.update(agent["path"] for agent in manifest.get("agents", []))
    model_profile = manifest.get("model_profile")
    if manifest.get("schema_version") == 3 and isinstance(model_profile, dict):
        relative_files.add(model_profile["path"])
    for relative in sorted(relative_files):
        files[relative] = hashlib.sha256((root / relative).read_bytes()).hexdigest()
    canonical = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def seal_package_check(root: Path, invocation_id: str = "package-call-1") -> None:
    manifest = load_manifest(root)
    validator = (ROOT / "scripts" / "validate_package.py").resolve()
    record = {
        "record_type": "actual_validator_run",
        "validator_path": str(validator),
        "command": f'python "{validator}" "{root.resolve()}"',
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
        "package_revision": static_package_revision(root),
        "trace": {"invocation_id": invocation_id, "role": "package_checker"},
    }
    (root / manifest["package_check"]["result"]).write_text(
        json.dumps(record, ensure_ascii=False), encoding="utf-8"
    )
    (root / manifest["package_check"]["log"]).write_text(
        f"ID вызова: {invocation_id}\nКод выхода: 0\nРоль: package_checker\n",
        encoding="utf-8",
    )


def write_package(root: Path, owner: str = "kimi_work") -> dict:
    shutil.copytree(TEMPLATE, root, dirs_exist_ok=True)
    (root / "agents" / "A4_package_checker").mkdir(parents=True, exist_ok=True)
    (root / "agents" / "A4_package_checker" / "AGENT.md").write_text(
        agent_card("package_checker", "deterministic_package_check"), encoding="utf-8"
    )
    manifest = load_manifest(root)
    manifest["status"] = "ready_for_work" if owner == "kimi_work" else "ready_for_kimi_code"
    manifest["implementation"]["scope"] = "тестовый результат"
    manifest["implementation"]["draft_outputs"] = []
    manifest["execution"].update(
        {
            "owner": owner,
            "stop_policy": "cooperative" if owner == "kimi_work" else None,
            "implementation_authorized": True,
            "approval": {
                "approved_at": "2026-11-10T13:05:00+03:00",
                "approved_by": "user",
                "evidence": "RUN_LOG.md",
            },
        }
    )
    if owner == "kimi_work":
        manifest["execution"]["session_defaults"] = {"model": "k3.1-pro", "effort": "high"}
        for task in manifest["tasks"]:
            task.update(
                {
                    "model": "k3.1-pro",
                    "effort": "high",
                    "assignment_source": "work_session_default",
                }
            )
    manifest["permissions"] = {
        "subagents": "allow",
        "verifier_subagent": "allow",
        "swarm": "allow",
        "approved_agents": ["A2", "A3", "A4"],
        "max_parallel": 1,
        "evidence": "RUN_LOG.md",
    }
    if not any(agent["id"] == "A4" for agent in manifest["agents"]):
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
    manifest["package_check"] = {
        "status": "passed",
        "agent": "A4",
        "result": "verification/PACKAGE_CHECK.json",
        "log": "verification/PACKAGE_CHECK.log",
    }
    save_manifest(root, manifest)
    (root / "RUN_LOG.md").write_text(approval_text(), encoding="utf-8")
    seal_package_check(root)
    return manifest


def canonical_revision(value: object) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def write_verified_result(root: Path, with_trace: bool = True) -> None:
    manifest = load_manifest(root)
    (root / "result.md").write_text("Проверенный результат\n", encoding="utf-8")
    files = {"result.md": hashlib.sha256((root / "result.md").read_bytes()).hexdigest()}
    metadata = {
        "independent": True,
        "criteria_revision": canonical_revision(validator.criteria_for_revision(manifest)),
        "result_revision": canonical_revision(files),
        "result_files": files,
        "previous_report": None,
        "snapshot": None,
        "diff": None,
        "open_p0": 0,
        "open_p1": 0,
        "open_p2": 0,
    }
    invocation_id = "verifier-call-1"
    if with_trace:
        metadata["verifier_agent"] = "A3"
        metadata["invocation_id"] = invocation_id
    report = "---\n" + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False) + "---\n"
    report += (
        "- действие: независимая проверка отдельным субагентом\n"
        f"- доказательство: вызов {invocation_id}\n"
        "- итог: критерии выполнены\n"
        "- открытые замечания: нет\n"
    )
    (root / "verification" / "REPORT.md").write_text(report, encoding="utf-8")
    with (root / "RUN_LOG.md").open("a", encoding="utf-8") as log:
        log.write(f"\nA3 | verifier | ID вызова: {invocation_id}\n")
    manifest["status"] = "result_verified"
    manifest["implementation"]["status"] = "implemented"
    manifest["verification"]["status"] = "passed"
    save_manifest(root, manifest)


def test_valid_work_package_with_real_package_checker_trace(tmp_path):
    write_package(tmp_path)
    assert validate_package(tmp_path) == []


def test_legacy_code_package_without_new_fields_keeps_working(tmp_path):
    manifest = write_package(tmp_path, "kimi_code")
    manifest["schema_version"] = 2
    manifest.pop("permissions")
    manifest.pop("package_check")
    manifest.pop("model_profile")
    manifest["execution"].pop("stop_policy")
    manifest["execution"].pop("mode")
    for task in manifest["tasks"]:
        for field in ("model", "effort", "reason", "assignment_source"):
            task.pop(field)
    save_manifest(tmp_path, manifest)
    assert validate_package(tmp_path) == []


def test_work_requires_cooperative_stop_policy(tmp_path):
    manifest = write_package(tmp_path)
    manifest["execution"]["stop_policy"] = None
    save_manifest(tmp_path, manifest)
    assert "invalid_stop_policy" in issue_codes(tmp_path)


def test_ready_for_work_requires_passed_package_check(tmp_path):
    manifest = write_package(tmp_path)
    manifest["package_check"]["status"] = "pending"
    save_manifest(tmp_path, manifest)
    assert "package_check_required" in issue_codes(tmp_path)


def test_package_check_pending_is_valid_without_checker_permission(tmp_path):
    manifest = write_package(tmp_path)
    manifest["status"] = "package_check_pending"
    manifest["package_check"]["status"] = "pending"
    manifest["permissions"]["verifier_subagent"] = "deny"
    manifest["permissions"]["approved_agents"] = ["A2"]
    save_manifest(tmp_path, manifest)
    assert validate_package(tmp_path) == []


def test_verifier_permission_does_not_authorize_work_generator(tmp_path):
    manifest = write_package(tmp_path)
    manifest["permissions"]["subagents"] = "ask"
    manifest["permissions"]["approved_agents"] = ["A3", "A4"]
    save_manifest(tmp_path, manifest)
    assert "missing_subagent_permission" in issue_codes(tmp_path)
    assert "unapproved_agent" in issue_codes(tmp_path)


def test_unapproved_work_generator_is_rejected(tmp_path):
    manifest = write_package(tmp_path)
    manifest["permissions"]["approved_agents"] = ["A3", "A4"]
    save_manifest(tmp_path, manifest)
    assert "unapproved_agent" in issue_codes(tmp_path)


def test_parallelism_above_one_requires_swarm(tmp_path):
    manifest = write_package(tmp_path)
    manifest["permissions"]["max_parallel"] = 2
    manifest["permissions"]["swarm"] = "deny"
    save_manifest(tmp_path, manifest)
    assert "invalid_parallelism" in issue_codes(tmp_path)


def test_sequential_fallback_without_swarm_is_valid(tmp_path):
    manifest = write_package(tmp_path)
    manifest["status"] = "running"
    manifest["implementation"]["status"] = "in_progress"
    manifest["permissions"]["swarm"] = "deny"
    manifest["permissions"]["max_parallel"] = 1
    save_manifest(tmp_path, manifest)
    with (tmp_path / "RUN_LOG.md").open("a", encoding="utf-8") as log:
        log.write("\nSwarm недоступен: последовательный fallback согласованных ролей.\n")
    seal_package_check(tmp_path)
    assert validate_package(tmp_path) == []


def test_verification_pending_does_not_cancel_implementation(tmp_path):
    manifest = write_package(tmp_path)
    (tmp_path / "result.md").write_text("Результат\n", encoding="utf-8")
    manifest["status"] = "verification_pending"
    manifest["implementation"]["status"] = "implemented"
    manifest["verification"]["status"] = "pending"
    manifest["permissions"]["verifier_subagent"] = "deny"
    manifest["permissions"]["approved_agents"] = ["A2", "A4"]
    save_manifest(tmp_path, manifest)
    seal_package_check(tmp_path)
    assert validate_package(tmp_path) == []


def test_result_verified_requires_verifier_permission(tmp_path):
    manifest = write_package(tmp_path)
    manifest["permissions"]["verifier_subagent"] = "deny"
    save_manifest(tmp_path, manifest)
    write_verified_result(tmp_path)
    assert "missing_verifier_permission" in issue_codes(tmp_path)


def test_result_verified_requires_real_verifier_trace(tmp_path):
    write_package(tmp_path)
    write_verified_result(tmp_path, with_trace=False)
    assert "missing_subagent_trace" in issue_codes(tmp_path)


def test_result_verified_accepts_real_verifier_trace(tmp_path):
    write_package(tmp_path)
    write_verified_result(tmp_path)
    assert validate_package(tmp_path) == []


def test_package_change_makes_package_check_stale(tmp_path):
    write_package(tmp_path)
    (tmp_path / "LAUNCH.md").write_text("Изменённый запуск\n", encoding="utf-8")
    assert "stale_package_check" in issue_codes(tmp_path)


def test_boolean_is_not_a_real_package_checker_trace(tmp_path):
    manifest = write_package(tmp_path)
    (tmp_path / manifest["package_check"]["result"]).write_text(
        json.dumps({"actual_validator_run": True, "exit_code": 0}), encoding="utf-8"
    )
    assert "invalid_package_check_evidence" in issue_codes(tmp_path)


def test_allow_without_logged_user_permission_is_rejected(tmp_path):
    write_package(tmp_path)
    (tmp_path / "RUN_LOG.md").write_text(approval_text().replace("стартовое согласование пользователя", "автоматическая настройка"), encoding="utf-8")
    assert "missing_permission_evidence" in issue_codes(tmp_path)


def test_cancelled_requires_cooperative_stop_between_calls(tmp_path):
    manifest = write_package(tmp_path)
    manifest["status"] = "cancelled"
    manifest["implementation"]["status"] = "in_progress"
    save_manifest(tmp_path, manifest)
    assert "invalid_cancellation_evidence" in issue_codes(tmp_path)
    with (tmp_path / "RUN_LOG.md").open("a", encoding="utf-8") as log:
        log.write("\nКонтролируемая остановка между завершёнными вызовами. Новые ветки не запускались.\n")
    assert validate_package(tmp_path) == []


def test_interrupted_requires_uncertain_integrity_and_no_auto_resume(tmp_path):
    manifest = write_package(tmp_path)
    manifest["status"] = "interrupted"
    manifest["implementation"]["status"] = "in_progress"
    manifest["implementation"]["draft_outputs"] = ["draft.md"]
    (tmp_path / "draft.md").write_text("Черновик\n", encoding="utf-8")
    save_manifest(tmp_path, manifest)
    with (tmp_path / "RUN_LOG.md").open("a", encoding="utf-8") as log:
        log.write("\ninterrupted: целостность не подтверждена; автоматическое продолжение запрещено.\n")
    assert validate_package(tmp_path) == []


def test_interrupted_cannot_continue_without_user_decision(tmp_path):
    manifest = write_package(tmp_path)
    manifest["status"] = "running"
    manifest["implementation"]["status"] = "in_progress"
    save_manifest(tmp_path, manifest)
    with (tmp_path / "RUN_LOG.md").open("a", encoding="utf-8") as log:
        log.write("\nпредыдущий статус -> interrupted: целостность не подтверждена.\n")
    assert "automatic_resume" in issue_codes(tmp_path)
    with (tmp_path / "RUN_LOG.md").open("a", encoding="utf-8") as log:
        log.write("\nрешение пользователя: продолжить после interrupted\n")
    assert "automatic_resume" not in issue_codes(tmp_path)


def test_draft_outputs_block_final_implementation(tmp_path):
    manifest = write_package(tmp_path)
    (tmp_path / "result.md").write_text("Результат\n", encoding="utf-8")
    (tmp_path / "draft.md").write_text("Черновик\n", encoding="utf-8")
    manifest["status"] = "verification_pending"
    manifest["implementation"]["status"] = "implemented"
    manifest["verification"]["status"] = "pending"
    manifest["implementation"]["draft_outputs"] = ["draft.md"]
    save_manifest(tmp_path, manifest)
    assert "draft_outputs_not_final" in issue_codes(tmp_path)


def test_draft_file_cannot_enter_verified_result_files(tmp_path):
    manifest = write_package(tmp_path)
    (tmp_path / "draft.md").write_text("Черновик\n", encoding="utf-8")
    manifest["implementation"]["draft_outputs"] = ["draft.md"]
    save_manifest(tmp_path, manifest)
    write_verified_result(tmp_path)
    report = tmp_path / "verification" / "REPORT.md"
    text = report.read_text(encoding="utf-8")
    metadata = yaml.safe_load(text.split("---", 2)[1])
    metadata["result_files"] = {"draft.md": hashlib.sha256((tmp_path / "draft.md").read_bytes()).hexdigest()}
    metadata["result_revision"] = canonical_revision(metadata["result_files"])
    report.write_text("---\n" + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False) + "---" + text.split("---", 2)[2], encoding="utf-8")
    assert "draft_in_result" in issue_codes(tmp_path)


def test_instruction_regression_for_subagent_only_verification():
    files = [
        ROOT / "instructions" / "core" / "verification.md",
        ROOT / "instructions" / "core" / "orchestration.md",
        ROOT / "instructions" / "adapters" / "kimi-code.md",
        ROOT / "instructions" / "adapters" / "work.md",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in files)
    assert "отдельную свежую сессию" not in text
    assert "новый экземпляр" in text
    assert "package_checker" in text
    assert "cooperative" in text
    assert "foreground" in text
    assert "kimi_work" in text


def test_package_revision_cli_uses_the_common_static_contract(tmp_path):
    import subprocess

    write_package(tmp_path)
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_package.py"), "--package-revision", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == static_package_revision(tmp_path) + "\n"
    assert result.stderr == ""


def test_revised_skill_validator_is_synchronized_and_relocatable(tmp_path):
    import subprocess

    installed_scripts = tmp_path / "installed-skill" / "scripts"
    installed_scripts.mkdir(parents=True)
    for name in ("validate_package.py", "work_subagent_verification.py"):
        source = ROOT / "scripts" / name
        bundled = ROOT / "scripts" / name
        assert bundled.is_file()
        assert bundled.read_bytes() == source.read_bytes()
        (installed_scripts / name).write_bytes(bundled.read_bytes())
    relocated = installed_scripts / "validate_package.py"
    package = tmp_path / "package"
    write_package(package)
    result = subprocess.run(
        [sys.executable, str(relocated), "--package-revision", str(package)],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert result.returncode == 0
    assert result.stdout == static_package_revision(package) + "\n"
    assert result.stderr == ""


import pytest


@pytest.mark.parametrize(
    ("section", "value"),
    [
        ("execution", None),
        ("implementation", None),
        ("verification", None),
        ("agents", None),
        ("tasks", None),
        ("permissions", []),
        ("package_check", []),
    ],
)
def test_invalid_schema2_section_types_return_p1_without_exception(tmp_path, section, value):
    manifest = write_package(tmp_path)
    manifest[section] = value
    save_manifest(tmp_path, manifest)
    issues = validate_package(tmp_path)
    assert any(issue.code == "invalid_manifest" and issue.severity == "P1" for issue in issues)


def test_revised_skill_description_preserves_explicit_work_execution():
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "execution.owner: kimi_work" in text
    assert "В Kimi Work только согласовывать" not in text
    assert "Не исполнять DAG" not in text


def test_revised_skill_front_matter_is_valid_yaml():
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    try:
        metadata = yaml.safe_load(text.split("---", 2)[1])
    except yaml.YAMLError as exc:
        pytest.fail(f"Некорректный YAML front matter: {exc}")
    assert metadata["name"] == "kimi-verification-orchestration"
    assert "execution.owner: kimi_work" in metadata["description"]


def test_package_checker_uses_skill_rooted_absolute_validator_path():
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    card = (ROOT / "instructions" / "templates" / "task-package" / "agents" / "A4_package_checker" / "AGENT.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "scripts/validate_package.py" in skill
    assert "относительно каталога этого скилла" in skill
    assert "абсолютный путь" in card
    assert "от корня установленного навыка" in card
    assert 'python scripts/validate_package.py "<absolute-task-package>"' not in readme
    assert '<skill-root>/scripts/validate_package.py' in readme
    assert "package_revision" in card
    assert "абсолютный `validator_path`" in card


def set_absolute_package_check_command(root: Path, validator: Path | None = None) -> None:
    manifest = load_manifest(root)
    record_path = root / manifest["package_check"]["result"]
    record = json.loads(record_path.read_text(encoding="utf-8"))
    validator = (validator or ROOT / "scripts" / "validate_package.py").resolve()
    record["validator_path"] = str(validator)
    record["command"] = f'python "{validator}" "{root.resolve()}"'
    record_path.write_text(json.dumps(record), encoding="utf-8")


def package_check_record(root: Path) -> tuple[Path, dict]:
    manifest = load_manifest(root)
    path = root / manifest["package_check"]["result"]
    return path, json.loads(path.read_text(encoding="utf-8"))


def test_package_check_rejects_relative_command_without_validator_path(tmp_path):
    write_package(tmp_path)
    path, record = package_check_record(tmp_path)
    record.pop("validator_path", None)
    record["command"] = "python scripts/validate_package.py ."
    path.write_text(json.dumps(record), encoding="utf-8")
    assert "invalid_package_check_evidence" in issue_codes(tmp_path)


def test_package_check_requires_validator_path_even_with_absolute_command(tmp_path):
    write_package(tmp_path)
    set_absolute_package_check_command(tmp_path)
    path, record = package_check_record(tmp_path)
    record.pop("validator_path")
    path.write_text(json.dumps(record), encoding="utf-8")
    assert "invalid_package_check_evidence" in issue_codes(tmp_path)


def test_package_check_rejects_relative_validator_path(tmp_path):
    write_package(tmp_path)
    set_absolute_package_check_command(tmp_path)
    path, record = package_check_record(tmp_path)
    record["validator_path"] = "scripts/validate_package.py"
    path.write_text(json.dumps(record), encoding="utf-8")
    assert "invalid_package_check_evidence" in issue_codes(tmp_path)


def test_package_check_rejects_relative_validator_in_command(tmp_path):
    write_package(tmp_path)
    set_absolute_package_check_command(tmp_path)
    path, record = package_check_record(tmp_path)
    record["command"] = f'python scripts/validate_package.py "{tmp_path.resolve()}"'
    path.write_text(json.dumps(record), encoding="utf-8")
    assert "invalid_package_check_evidence" in issue_codes(tmp_path)


def test_package_check_rejects_package_path_from_cwd(tmp_path):
    write_package(tmp_path)
    set_absolute_package_check_command(tmp_path)
    path, record = package_check_record(tmp_path)
    validator = record["validator_path"]
    record["command"] = f'python "{validator}" .'
    path.write_text(json.dumps(record), encoding="utf-8")
    assert "invalid_package_check_evidence" in issue_codes(tmp_path)


def test_package_check_rejects_mismatched_absolute_validator(tmp_path):
    write_package(tmp_path)
    set_absolute_package_check_command(tmp_path)
    path, record = package_check_record(tmp_path)
    other = (ROOT / "scripts" / "work_subagent_verification.py").resolve()
    record["command"] = f'python "{other}" "{tmp_path.resolve()}"'
    path.write_text(json.dumps(record), encoding="utf-8")
    assert "invalid_package_check_evidence" in issue_codes(tmp_path)


def test_package_check_accepts_consistent_portable_absolute_validator(tmp_path):
    write_package(tmp_path)
    portable = tmp_path.parent / "portable-skill" / "scripts"
    portable.mkdir(parents=True)
    validator = portable / "validate_package.py"
    shutil.copy2(ROOT / "scripts" / "validate_package.py", validator)
    shutil.copy2(ROOT / "scripts" / "work_subagent_verification.py", portable / "work_subagent_verification.py")
    set_absolute_package_check_command(tmp_path, validator)
    assert validate_package(tmp_path) == []
