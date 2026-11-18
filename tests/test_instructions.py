from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]
INSTRUCTIONS = ROOT / "instructions"
REVISED = ROOT / "instructions"


def test_core_is_small_and_does_not_embed_registries():
    text = (INSTRUCTIONS / "AGENTS.md").read_text(encoding="utf-8")
    assert len(text) <= 6000
    assert "П14" not in text
    assert "a3-system" not in text
    assert "ПРОМТ –" in text


def test_adapters_have_distinct_execution_boundaries():
    work = (INSTRUCTIONS / "adapters" / "work.md").read_text(encoding="utf-8")
    code = (INSTRUCTIONS / "adapters" / "kimi-code.md").read_text(encoding="utf-8")
    assert "не исполняет оркестрацию" in work
    assert "15 минут" in work
    assert "ready_for_kimi_code" in work
    assert "сразу начать реализацию" in code
    assert "verification_pending" in code
    assert "PREFLIGHT.json" in code


def test_start_authorization_is_distinct_from_decision_checkpoints():
    core = (INSTRUCTIONS / "AGENTS.md").read_text(encoding="utf-8")
    work = (INSTRUCTIONS / "adapters" / "work.md").read_text(encoding="utf-8")
    assert "Содержательный чек-поинт не является повторным разрешением" in core
    assert "стартовое согласование пользователя" in work
    assert "Независимая проверка пакета выполняется только по отдельному явному запросу" in work


def test_verification_registry_is_complete():
    data = yaml.safe_load((INSTRUCTIONS / "registries" / "verification-profiles.yaml").read_text(encoding="utf-8"))
    assert {item["id"] for item in data["small"]} == {"М1", "М2", "М3", "М4", "М5"}
    assert {item["id"] for item in data["full"]} == {f"П{number}" for number in range(1, 15)}
    assert all(item["mechanisms"] for item in data["small"] + data["full"])


def test_implementation_text_files_do_not_use_em_dash():
    paths = [ROOT / "README.md"]
    for directory in (INSTRUCTIONS, ROOT / "scripts", ROOT / "tests"):
        paths.extend(
            path
            for path in directory.rglob("*")
            if path.is_file() and path.suffix in {".md", ".py", ".yaml"}
        )
    for path in paths:
        assert chr(0x2014) not in path.read_text(encoding="utf-8"), path


def test_design_registry_preserves_a3_gate_order():
    data = yaml.safe_load((INSTRUCTIONS / "registries" / "design-skills.yaml").read_text(encoding="utf-8"))
    assert data["routes"]["a3"] == ["a3-system", "a3-build", "print-verify", "visual-review"]
    assert "print-verify" in data["skills"]
    assert "visual-review" in data["skills"]
    assert data["blocking_exit_severities"] == ["P0", "P1"]


def test_template_has_schema3_team_execution_and_separate_states():
    manifest = yaml.safe_load((INSTRUCTIONS / "templates" / "task-package" / "MANIFEST.yaml").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 3
    assert manifest["execution"]["owner"] == "kimi_code"
    assert manifest["execution"]["mode"] == "team"
    assert manifest["execution"]["implementation_authorized"] is False
    assert manifest["execution"]["continue_after_preflight"] is True
    assert manifest["implementation"]["status"] == "not_started"
    assert manifest["verification"]["status"] == "not_started"
    assert manifest["decision_checkpoints"] == []
    assert manifest["permissions"]["max_parallel"] == 1
    assert manifest["model_profile"]["name"] == "code-example"
    assert all(task["model"] and task["effort"] and task["reason"] for task in manifest["tasks"])


def test_template_has_sequential_generation_then_verification():
    manifest = yaml.safe_load((INSTRUCTIONS / "templates" / "task-package" / "MANIFEST.yaml").read_text(encoding="utf-8"))
    tasks = {task["id"]: task for task in manifest["tasks"]}
    assert tasks["T1"]["depends_on"] == []
    assert tasks["T2"]["depends_on"] == ["T1"]
    assert tasks["T2"]["agent"] != tasks["T1"]["agent"]


def test_revised_skill_uses_the_same_instructions_as_root():
    root_files = {path.relative_to(INSTRUCTIONS) for path in INSTRUCTIONS.rglob("*") if path.is_file()}
    revised_files = {path.relative_to(REVISED) for path in REVISED.rglob("*") if path.is_file()}
    assert root_files == revised_files
    for relative in root_files:
        assert (INSTRUCTIONS / relative).read_bytes() == (REVISED / relative).read_bytes(), relative


def test_schema3_instructions_preserve_team_models_and_review_contract():
    core = (INSTRUCTIONS / "core" / "orchestration.md").read_text(encoding="utf-8")
    agents = (INSTRUCTIONS / "AGENTS.md").read_text(encoding="utf-8")
    for text in (core, agents):
        assert "team" in text
        assert "solo" in text
        assert "явного выбора пользователя" in text
    for required in (
        "runtime_alias",
        "SHA-256",
        "Скрытый fallback",
        "model reviewer",
        "discretionary",
        "K3.1 low",
        "K2.8 Preview",
        "package_checker",
    ):
        assert required in core


def test_code_package_creation_session_stops_before_execution():
    agents = (INSTRUCTIONS / "AGENTS.md").read_text(encoding="utf-8")
    code = (INSTRUCTIONS / "adapters" / "kimi-code.md").read_text(encoding="utf-8")
    core = (INSTRUCTIONS / "core" / "orchestration.md").read_text(encoding="utf-8")
    launch = (INSTRUCTIONS / "templates" / "task-package" / "LAUNCH.md").read_text(encoding="utf-8")
    assert "не разрешает исполнение созданного пакета в той же Code-сессии" in agents
    assert "В создавшей пакет сессии запрещено проводить pre-flight" in code
    assert "implementation_authorized" in core
    assert "continue_after_preflight" in core
    assert "Если пакет создан в текущей сессии, не выполняй его" in launch


def test_code_adapter_requires_new_session_and_blocks_model_fallback():
    code = (INSTRUCTIONS / "adapters" / "kimi-code.md").read_text(encoding="utf-8")
    assert "новой основной Code-сессии" in code
    assert "создающая сессия не исполняет" in code
    assert "Скрытый fallback" in code
    assert "runtime_alias" in code
    assert "model reviewer" in code


def test_work_adapter_applies_session_defaults_to_all_roles():
    work = (INSTRUCTIONS / "adapters" / "work.md").read_text(encoding="utf-8")
    assert "Standard -> low" in work
    assert "Advanced -> high" in work
    assert "Extreme -> max" in work
    assert "включая verifier и `package_checker`" in work
    assert "разные session effort" in work


def test_verification_revision_rules_apply_to_schema2_and_schema3():
    verification = (INSTRUCTIONS / "core" / "verification.md").read_text(encoding="utf-8")
    assert "схем 2 и 3" in verification
    assert "Code и Work" in verification
    assert "package_checker" in verification
