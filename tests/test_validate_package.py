from pathlib import Path
import re
import subprocess
import sys

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import validate_package as validator
from validate_package import validate_package


def agent_card(title: str, capability: str, required: str = "нет", optional: str = "нет") -> str:
    role = "verifier" if capability == "independent_verification" else "generator"
    return f"""# {title}

## Роль
{role}

## Задача
Выполнить назначенную задачу.

## Профиль способностей
{capability}

## Обязательные скиллы
{required}

## Опциональные скиллы
{optional}

## Разрешённые действия
Читать входы и записывать только назначенные выходы.

## Вход
Исходная задача и назначенные входы.

## Выход
Назначенный файл результата.

## Definition of Done
Выполнены обязательные критерии.

## Требования проверки
Проверить выход по критериям и приложить доказательства.

## Условия отката
Остановиться при нарушении входного контракта.
"""


def write_minimal_package(root: Path) -> None:
    (root / "agents" / "A1_generator").mkdir(parents=True)
    (root / "agents" / "A2_verifier").mkdir(parents=True)
    (root / "verification").mkdir()
    (root / "00_ORCHESTRATOR.md").write_text("# Оркестратор\n", encoding="utf-8")
    (root / "LAUNCH.md").write_text("# Запуск\n", encoding="utf-8")
    (root / "agents" / "A1_generator" / "AGENT.md").write_text(
        agent_card("A1", "generation"), encoding="utf-8"
    )
    (root / "agents" / "A2_verifier" / "AGENT.md").write_text(
        agent_card("A2", "independent_verification"), encoding="utf-8"
    )
    (root / "verification" / "PLAN.md").write_text("# План\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "package_id": "test-package",
        "status": "drafted",
        "agents": [
            {
                "id": "A1",
                "role": "generator",
                "path": "agents/A1_generator/AGENT.md",
                "capability": "generation",
                "required_skills": [],
                "optional_skills": [],
            },
            {
                "id": "A2",
                "role": "verifier",
                "path": "agents/A2_verifier/AGENT.md",
                "capability": "independent_verification",
                "required_skills": [],
                "optional_skills": [],
            },
        ],
        "tasks": [
            {
                "id": "T1",
                "agent": "A1",
                "kind": "generation",
                "depends_on": [],
                "inputs": [],
                "outputs": ["result.md"],
            },
            {
                "id": "T2",
                "agent": "A2",
                "kind": "verification",
                "depends_on": ["T1"],
                "inputs": ["result.md"],
                "outputs": ["verification/REPORT.md"],
            },
        ],
        "verification": {
            "enabled": True,
            "level": "small",
            "small_profile": "М1",
            "full_profiles": [],
            "verifier": "A2",
            "plan": "verification/PLAN.md",
        },
    }
    (root / "MANIFEST.yaml").write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def test_valid_minimal_package(tmp_path):
    write_minimal_package(tmp_path)
    assert validate_package(tmp_path) == []


def test_missing_required_file_is_p1(tmp_path):
    write_minimal_package(tmp_path)
    (tmp_path / "LAUNCH.md").unlink()
    issues = validate_package(tmp_path)
    assert any(issue.code == "missing_file" and issue.severity == "P1" for issue in issues)


def test_invalid_yaml_is_p1(tmp_path):
    write_minimal_package(tmp_path)
    (tmp_path / "MANIFEST.yaml").write_text("agents: [\n", encoding="utf-8")
    issues = validate_package(tmp_path)
    assert any(issue.code == "invalid_yaml" for issue in issues)


def load_manifest(root: Path) -> dict:
    return yaml.safe_load((root / "MANIFEST.yaml").read_text(encoding="utf-8"))


def save_manifest(root: Path, manifest: dict) -> None:
    (root / "MANIFEST.yaml").write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def issue_codes(root: Path) -> set[str]:
    return {issue.code for issue in validate_package(root)}


def test_cycle_is_rejected(tmp_path):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["tasks"][0]["depends_on"] = ["T2"]
    save_manifest(tmp_path, manifest)
    assert "dag_cycle" in issue_codes(tmp_path)


def test_unknown_dependency_is_rejected(tmp_path):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["tasks"][1]["depends_on"] = ["T404"]
    save_manifest(tmp_path, manifest)
    assert "unknown_dependency" in issue_codes(tmp_path)


def test_verifier_cannot_generate(tmp_path):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["tasks"][0]["agent"] = "A2"
    save_manifest(tmp_path, manifest)
    assert "verifier_generates" in issue_codes(tmp_path)


def test_verifier_must_be_distinct(tmp_path):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["verification"]["verifier"] = "A1"
    save_manifest(tmp_path, manifest)
    assert "invalid_verifier" in issue_codes(tmp_path)


def test_unknown_profile_is_rejected(tmp_path):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["verification"]["small_profile"] = "М99"
    save_manifest(tmp_path, manifest)
    assert "invalid_profile" in issue_codes(tmp_path)


def test_missing_agent_card_is_rejected(tmp_path):
    write_minimal_package(tmp_path)
    (tmp_path / "agents" / "A1_generator" / "AGENT.md").unlink()
    assert "missing_agent_file" in issue_codes(tmp_path)


def test_done_requires_evidence(tmp_path):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["status"] = "done"
    save_manifest(tmp_path, manifest)
    assert "missing_evidence" in issue_codes(tmp_path)


def test_ready_requires_package_report(tmp_path):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["status"] = "ready_for_kimi_code"
    save_manifest(tmp_path, manifest)
    assert "missing_evidence" in issue_codes(tmp_path)


def test_broken_local_markdown_link_is_rejected(tmp_path):
    write_minimal_package(tmp_path)
    (tmp_path / "00_ORCHESTRATOR.md").write_text("[Вход](missing.md)\n", encoding="utf-8")
    assert "broken_link" in issue_codes(tmp_path)


def test_em_dash_is_rejected(tmp_path):
    write_minimal_package(tmp_path)
    (tmp_path / "LAUNCH.md").write_text("Недопустимый символ: " + chr(0x2014), encoding="utf-8")
    assert "forbidden_dash" in issue_codes(tmp_path)


def evidence_text(open_findings: str = "нет") -> str:
    return (
        "# Отчет\n\n"
        "- действие: выполнена проверка критериев\n"
        "- доказательство: команда проверки завершилась с кодом 0\n"
        "- итог: обязательные критерии выполнены\n"
        f"- открытые замечания: {open_findings}\n"
    )


def write_done_evidence(root: Path, open_findings: str = "нет") -> None:
    (root / "RUN_LOG.md").write_text(evidence_text(), encoding="utf-8")
    (root / "verification" / "REPORT.md").write_text(
        evidence_text(open_findings), encoding="utf-8"
    )


@pytest.mark.parametrize("status", ["done", "done_with_p2"])
def test_positive_completion_evidence_is_accepted(tmp_path, status):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["status"] = status
    save_manifest(tmp_path, manifest)
    write_done_evidence(tmp_path, "P2: локальное улучшение" if status == "done_with_p2" else "нет")
    assert validate_package(tmp_path) == []


@pytest.mark.parametrize("status", ["done", "done_with_p2"])
def test_empty_completion_evidence_is_rejected(tmp_path, status):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["status"] = status
    save_manifest(tmp_path, manifest)
    (tmp_path / "RUN_LOG.md").touch()
    (tmp_path / "verification" / "REPORT.md").touch()
    assert "invalid_evidence" in issue_codes(tmp_path)


@pytest.mark.parametrize("status", ["done", "done_with_p2"])
@pytest.mark.parametrize("level", ["P0", "P1"])
def test_open_blocking_findings_reject_completion(tmp_path, status, level):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["status"] = status
    save_manifest(tmp_path, manifest)
    write_done_evidence(tmp_path, f"{level}: открытое замечание")
    assert "blocking_finding" in issue_codes(tmp_path)


def test_done_rejects_open_p2(tmp_path):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["status"] = "done"
    save_manifest(tmp_path, manifest)
    write_done_evidence(tmp_path, "P2: открытое замечание")
    assert "unexpected_open_finding" in issue_codes(tmp_path)


def test_unknown_status_is_rejected(tmp_path):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["status"] = "finished"
    save_manifest(tmp_path, manifest)
    issues = validate_package(tmp_path)
    assert any(issue.code == "invalid_status" and issue.severity == "P1" for issue in issues)


def test_unknown_verification_level_is_rejected(tmp_path):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["verification"]["level"] = "maximum"
    save_manifest(tmp_path, manifest)
    issues = validate_package(tmp_path)
    assert any(issue.code == "invalid_level" and issue.severity == "P1" for issue in issues)


def test_unknown_full_profile_is_rejected(tmp_path):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["verification"]["full_profiles"] = ["П99"]
    save_manifest(tmp_path, manifest)
    assert "invalid_profile" in issue_codes(tmp_path)


def test_full_level_requires_profiles(tmp_path):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["verification"]["level"] = "full"
    save_manifest(tmp_path, manifest)
    assert "invalid_profile" in issue_codes(tmp_path)


def test_enabled_verification_requires_selected_verifier_task(tmp_path):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["tasks"] = manifest["tasks"][:1]
    save_manifest(tmp_path, manifest)
    assert "missing_verification_task" in issue_codes(tmp_path)


def test_verification_task_depends_on_checked_generation(tmp_path):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["tasks"][1]["depends_on"] = []
    save_manifest(tmp_path, manifest)
    assert "missing_verification_dependency" in issue_codes(tmp_path)


@pytest.mark.parametrize("section", ["agents", "tasks"])
@pytest.mark.parametrize("bad_item", [None, "agent", 7, []])
def test_invalid_list_items_return_issues_without_exception(tmp_path, section, bad_item):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest[section] = [bad_item]
    save_manifest(tmp_path, manifest)
    issues = validate_package(tmp_path)
    assert any(issue.code == "invalid_manifest" and issue.severity == "P1" for issue in issues)


@pytest.mark.parametrize("root", [[], "manifest", None])
def test_invalid_manifest_root_returns_p1(tmp_path, root):
    write_minimal_package(tmp_path)
    (tmp_path / "MANIFEST.yaml").write_text(
        yaml.safe_dump(root, allow_unicode=True), encoding="utf-8"
    )
    issues = validate_package(tmp_path)
    assert any(issue.code == "invalid_manifest" and issue.severity == "P1" for issue in issues)


@pytest.mark.parametrize("section", ["agents", "tasks", "verification"])
def test_invalid_section_types_return_p1(tmp_path, section):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest[section] = "invalid"
    save_manifest(tmp_path, manifest)
    issues = validate_package(tmp_path)
    assert any(issue.code == "invalid_manifest" and issue.severity == "P1" for issue in issues)


def test_invalid_nested_fields_return_p1_without_exception(tmp_path):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["tasks"][0]["depends_on"] = None
    save_manifest(tmp_path, manifest)
    issues = validate_package(tmp_path)
    assert any(issue.code == "invalid_manifest" for issue in issues)


def test_file_read_error_returns_p1_without_exception(tmp_path):
    write_minimal_package(tmp_path)
    (tmp_path / "LAUNCH.md").write_bytes(b"\xff")
    issues = validate_package(tmp_path)
    assert any(issue.code == "file_read_error" and issue.severity == "P1" for issue in issues)


def test_absolute_agent_path_is_rejected(tmp_path):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["agents"][0]["path"] = str((tmp_path / "agents" / "A1_generator" / "AGENT.md").resolve())
    save_manifest(tmp_path, manifest)
    assert "unsafe_path" in issue_codes(tmp_path)


def test_parent_agent_path_is_rejected(tmp_path):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["agents"][0]["path"] = "../outside.md"
    save_manifest(tmp_path, manifest)
    assert "unsafe_path" in issue_codes(tmp_path)


def test_external_agent_symlink_is_rejected(tmp_path):
    write_minimal_package(tmp_path)
    outside = tmp_path.parent / "outside-agent.md"
    outside.write_text("Внешний файл", encoding="utf-8")
    link = tmp_path / "agents" / "A1_generator" / "EXTERNAL.md"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Символические ссылки недоступны")
    manifest = load_manifest(tmp_path)
    manifest["agents"][0]["path"] = "agents/A1_generator/EXTERNAL.md"
    save_manifest(tmp_path, manifest)
    assert "unsafe_path" in issue_codes(tmp_path)


def test_absolute_markdown_link_is_rejected(tmp_path):
    write_minimal_package(tmp_path)
    target = tmp_path / "LAUNCH.md"
    (tmp_path / "00_ORCHESTRATOR.md").write_text(f"[Запуск]({target.resolve()})", encoding="utf-8")
    assert "unsafe_path" in issue_codes(tmp_path)


def test_parent_markdown_link_is_rejected(tmp_path):
    write_minimal_package(tmp_path)
    (tmp_path / "00_ORCHESTRATOR.md").write_text("[Внешний файл](../outside.md)", encoding="utf-8")
    assert "unsafe_path" in issue_codes(tmp_path)


def test_external_markdown_symlink_is_rejected(tmp_path):
    write_minimal_package(tmp_path)
    outside = tmp_path.parent / "outside.md"
    outside.write_text("Внешний файл", encoding="utf-8")
    link = tmp_path / "local.md"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Символические ссылки недоступны")
    (tmp_path / "00_ORCHESTRATOR.md").write_text("[Внешний файл](local.md)", encoding="utf-8")
    assert "unsafe_path" in issue_codes(tmp_path)


def test_valid_local_and_external_links_are_accepted(tmp_path):
    write_minimal_package(tmp_path)
    (tmp_path / "00_ORCHESTRATOR.md").write_text(
        "[Запуск](LAUNCH.md#команда)\n[Документация](https://example.com/docs)\n[Раздел](#цель)",
        encoding="utf-8",
    )
    assert validate_package(tmp_path) == []


def test_agent_card_requires_all_headings(tmp_path):
    write_minimal_package(tmp_path)
    (tmp_path / "agents" / "A1_generator" / "AGENT.md").write_text("# A1\n", encoding="utf-8")
    assert "invalid_agent_card" in issue_codes(tmp_path)


def test_agent_card_capability_must_match_manifest(tmp_path):
    write_minimal_package(tmp_path)
    (tmp_path / "agents" / "A1_generator" / "AGENT.md").write_text(
        agent_card("A1", "other_capability"), encoding="utf-8"
    )
    assert "agent_profile_mismatch" in issue_codes(tmp_path)


def test_agent_card_skills_must_match_manifest(tmp_path):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["agents"][0]["required_skills"] = ["a3-build"]
    manifest["agents"][0]["optional_skills"] = ["visual-review"]
    save_manifest(tmp_path, manifest)
    (tmp_path / "agents" / "A1_generator" / "AGENT.md").write_text(
        agent_card("A1", "generation", "a3-build", "visual-review"), encoding="utf-8"
    )
    assert validate_package(tmp_path) == []
    (tmp_path / "agents" / "A1_generator" / "AGENT.md").write_text(
        agent_card("A1", "generation", "a3-system", "visual-review"), encoding="utf-8"
    )
    assert "agent_skills_mismatch" in issue_codes(tmp_path)


def test_yaml_em_dash_is_rejected(tmp_path):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["package_id"] = "пакет" + chr(0x2014) + "1"
    save_manifest(tmp_path, manifest)
    assert "forbidden_dash" in issue_codes(tmp_path)


def test_invalid_yaml_has_p1_severity(tmp_path):
    write_minimal_package(tmp_path)
    (tmp_path / "MANIFEST.yaml").write_text("agents: [\n", encoding="utf-8")
    issues = validate_package(tmp_path)
    assert any(issue.code == "invalid_yaml" and issue.severity == "P1" for issue in issues)


def run_cli(package: Path) -> subprocess.CompletedProcess:
    script = Path(__file__).parents[1] / "scripts" / "validate_package.py"
    return subprocess.run(
        [sys.executable, str(script), str(package)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_cli_exit_zero_without_traceback(tmp_path):
    write_minimal_package(tmp_path)
    result = run_cli(tmp_path)
    assert result.returncode == 0
    assert "Traceback" not in result.stderr


def test_cli_exit_one_without_traceback_for_invalid_data(tmp_path):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["tasks"] = [None]
    save_manifest(tmp_path, manifest)
    result = run_cli(tmp_path)
    assert result.returncode == 1
    assert "P1 invalid_manifest" in result.stdout
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("manifest", "status", []),
        ("verification", "level", []),
        ("verification", "verifier", []),
        ("verification", "full_profiles", [["П1"]]),
        ("task", "agent", []),
        ("task", "inputs", [{}]),
        ("task", "outputs", [{}]),
    ],
)
def test_unhashable_nested_values_return_p1_without_exception(tmp_path, section, key, value):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    if section == "task":
        target = manifest["tasks"][0]
    else:
        target = manifest if section == "manifest" else manifest[section]
    target[key] = value
    save_manifest(tmp_path, manifest)
    issues = validate_package(tmp_path)
    assert any(issue.severity == "P1" for issue in issues)


def test_open_blocking_finding_rejects_package_verified(tmp_path):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["status"] = "package_verified"
    save_manifest(tmp_path, manifest)
    (tmp_path / "verification" / "PACKAGE_REPORT.md").write_text(
        evidence_text("P1: открытое замечание"), encoding="utf-8"
    )
    assert "blocking_finding" in issue_codes(tmp_path)


def test_relative_root_and_bad_agent_utf8_return_p1_without_traceback(tmp_path, monkeypatch):
    write_minimal_package(tmp_path)
    (tmp_path / "agents" / "A1_generator" / "AGENT.md").write_bytes(b"\xff")
    monkeypatch.chdir(tmp_path.parent)
    relative_root = Path(tmp_path.name)
    issues = validate_package(relative_root)
    assert any(issue.code == "file_read_error" and issue.severity == "P1" for issue in issues)
    result = run_cli(relative_root)
    assert result.returncode == 1
    assert "P1 file_read_error" in result.stdout
    assert "Traceback" not in result.stderr


def test_each_verification_task_requires_its_own_generation_dependencies(tmp_path):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    generation = {
        "id": "T3",
        "agent": "A1",
        "kind": "generation",
        "depends_on": [],
        "inputs": [],
        "outputs": ["extra.md"],
    }
    verification = {
        "id": "T4",
        "agent": "A2",
        "kind": "verification",
        "depends_on": ["T1"],
        "inputs": ["extra.md"],
        "outputs": ["verification/EXTRA_REPORT.md"],
    }
    manifest["tasks"].extend([generation, verification])
    manifest["tasks"][1]["depends_on"] = ["T3"]
    save_manifest(tmp_path, manifest)
    assert "missing_verification_dependency" in issue_codes(tmp_path)


REQUIRED_AGENT_CARD_HEADINGS = (
    "Роль",
    "Задача",
    "Профиль способностей",
    "Обязательные скиллы",
    "Опциональные скиллы",
    "Разрешённые действия",
    "Вход",
    "Выход",
    "Definition of Done",
    "Требования проверки",
    "Условия отката",
)


@pytest.mark.parametrize("heading", REQUIRED_AGENT_CARD_HEADINGS)
def test_agent_card_rejects_each_missing_required_section(tmp_path, heading):
    write_minimal_package(tmp_path)
    text = agent_card("A1", "generation")
    text = re.sub(
        rf"^##\s+{re.escape(heading)}\s*$\n.*?(?=^##\s+|\Z)",
        "",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    (tmp_path / "agents" / "A1_generator" / "AGENT.md").write_text(text, encoding="utf-8")
    assert "invalid_agent_card" in issue_codes(tmp_path)


def test_agent_card_role_must_match_manifest(tmp_path):
    write_minimal_package(tmp_path)
    text = agent_card("A1", "generation").replace("## Роль\ngenerator", "## Роль\nverifier")
    (tmp_path / "agents" / "A1_generator" / "AGENT.md").write_text(text, encoding="utf-8")
    assert "agent_role_mismatch" in issue_codes(tmp_path)


@pytest.mark.parametrize(
    "open_findings",
    [
        "P2: локальное замечание; P3: неизвестная критичность",
        "P2: локальное замечание; замечание без критичности",
    ],
)
def test_done_with_p2_rejects_non_p2_among_all_open_findings(tmp_path, open_findings):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["status"] = "done_with_p2"
    save_manifest(tmp_path, manifest)
    write_done_evidence(tmp_path, open_findings)
    assert "unexpected_open_finding" in issue_codes(tmp_path)


GOLDEN_CRITERIA_REVISION = "19343b9103d53983ed27026ef6c961eb8f6c61d14be29c257a9147af5107f60c"


def golden_manifest() -> dict:
    return {
        "scope": {"acceptance_criteria": ["Готово"]},
        "implementation": {"scope": "результат"},
        "verification": {
            "enabled": True,
            "level": "small",
            "small_profile": "М1",
            "full_profiles": [],
        },
    }


def test_criteria_for_revision_returns_canonical_object():
    assert validator.criteria_for_revision(golden_manifest()) == {
        "scope": {"acceptance_criteria": ["Готово"]},
        "implementation_scope": "результат",
        "verification": {
            "enabled": True,
            "level": "small",
            "small_profile": "М1",
            "full_profiles": [],
        },
    }


def test_criteria_revision_matches_golden_sha256():
    assert validator.criteria_revision(golden_manifest()) == GOLDEN_CRITERIA_REVISION


def test_criteria_revision_cli_prints_only_golden_sha256(tmp_path):
    (tmp_path / "MANIFEST.yaml").write_text(
        yaml.safe_dump(golden_manifest(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    script = Path(__file__).parents[1] / "scripts" / "validate_package.py"
    result = subprocess.run(
        [sys.executable, str(script), "--criteria-revision", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == GOLDEN_CRITERIA_REVISION + "\n"
    assert result.stderr == ""


@pytest.mark.parametrize("status", ["done", "done_with_p2"])
def test_completion_without_required_evidence_field_is_accepted(tmp_path, status):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["status"] = status
    save_manifest(tmp_path, manifest)
    write_done_evidence(tmp_path, "P2: локальное улучшение" if status == "done_with_p2" else "нет")
    assert "completion" not in manifest
    assert validate_package(tmp_path) == []


@pytest.mark.parametrize("status", ["done", "done_with_p2"])
def test_completion_rejects_missing_declared_evidence(tmp_path, status):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["status"] = status
    manifest["completion"] = {"required_evidence": ["verification/COMPLETION.md"]}
    save_manifest(tmp_path, manifest)
    write_done_evidence(tmp_path, "P2: локальное улучшение" if status == "done_with_p2" else "нет")
    assert "missing_evidence" in issue_codes(tmp_path)


@pytest.mark.parametrize("status", ["done", "done_with_p2"])
def test_completion_accepts_valid_declared_evidence(tmp_path, status):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["status"] = status
    manifest["completion"] = {"required_evidence": ["verification/COMPLETION.md"]}
    save_manifest(tmp_path, manifest)
    write_done_evidence(tmp_path, "P2: локальное улучшение" if status == "done_with_p2" else "нет")
    (tmp_path / "verification" / "COMPLETION.md").write_text(evidence_text(), encoding="utf-8")
    assert validate_package(tmp_path) == []


@pytest.mark.parametrize("status", ["done", "done_with_p2"])
def test_completion_rejects_unsafe_declared_evidence_path(tmp_path, status):
    write_minimal_package(tmp_path)
    manifest = load_manifest(tmp_path)
    manifest["status"] = status
    manifest["completion"] = {"required_evidence": ["../outside.md"]}
    save_manifest(tmp_path, manifest)
    write_done_evidence(tmp_path, "P2: локальное улучшение" if status == "done_with_p2" else "нет")
    assert "unsafe_path" in issue_codes(tmp_path)
