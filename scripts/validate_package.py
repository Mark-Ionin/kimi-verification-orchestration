from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import yaml


REQUIRED_FILES = (
    "00_ORCHESTRATOR.md",
    "MANIFEST.yaml",
    "LAUNCH.md",
    "verification/PLAN.md",
)
V2_REQUIRED_FILES = (*REQUIRED_FILES, "RUN_LOG.md")
SMALL_PROFILES = {"М1", "М2", "М3", "М4", "М5"}
FULL_PROFILES = {f"П{number}" for number in range(1, 15)}
VALID_STATUSES = {
    "drafted",
    "package_verified",
    "package_check_pending",
    "ready_for_kimi_code",
    "ready_for_work",
    "preflight_passed",
    "running",
    "blocked",
    "cancelled",
    "interrupted",
    "verification_pending",
    "result_verified",
    "done_with_p2",
    "done",
}
VALID_LEVELS = {"none", "small", "full"}
VALID_IMPLEMENTATION_STATUSES = {"not_started", "in_progress", "implemented", "blocked"}
VALID_VERIFICATION_STATUSES = {
    "not_requested",
    "not_started",
    "pending",
    "self_checked",
    "passed",
    "failed",
    "stale",
}
RESULT_STATUSES = {"result_verified", "done_with_p2", "done"}
STATUS_EVIDENCE = {
    "package_verified": ("verification/PACKAGE_REPORT.md",),
    "ready_for_kimi_code": ("RUN_LOG.md",),
    "preflight_passed": ("RUN_LOG.md",),
    "running": ("RUN_LOG.md",),
    "verification_pending": ("RUN_LOG.md",),
    "result_verified": ("RUN_LOG.md", "verification/REPORT.md"),
    "done_with_p2": ("RUN_LOG.md", "verification/REPORT.md"),
    "done": ("RUN_LOG.md", "verification/REPORT.md"),
    "blocked": ("BLOCKERS.md",),
}
AGENT_CARD_HEADINGS = (
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
LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
EVIDENCE_PATTERN = re.compile(
    r"^\s*-\s*(действие|доказательство|итог|открытые замечания)\s*:\s*(.*?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
FRONT_MATTER_PATTERN = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
TEXT_SUFFIXES = {".md", ".yaml", ".yml", ".json", ".py", ".csv", ".txt"}


@dataclass(frozen=True)
class Issue:
    severity: str
    code: str
    message: str


def safe_path(root: Path, base: Path, relative: object) -> Path | None:
    if not isinstance(relative, str) or not relative.strip():
        return None
    candidate = Path(relative)
    if candidate.is_absolute():
        return None
    root = root.resolve()
    resolved = (base / candidate).resolve()
    if not resolved.is_relative_to(root):
        return None
    return resolved


def read_text(path: Path, issues: list[Issue], root: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        issues.append(
            Issue("P1", "file_read_error", f"Ошибка чтения {path.relative_to(root)}: {exc}")
        )
        return None


def card_section(text: str, heading: str) -> str | None:
    match = re.search(
        rf"^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s+|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    return match.group(1).strip() if match else None


def card_skills(text: str, heading: str) -> list[str] | None:
    section = card_section(text, heading)
    if section is None:
        return None
    if section == "нет":
        return []
    return [item.strip().strip("`") for item in section.split(",") if item.strip()]


def check_agent_card(agent: dict, path: Path, root: Path, issues: list[Issue]) -> None:
    text = read_text(path, issues, root)
    if text is None:
        return
    agent_id = agent["id"]
    sections = {heading: card_section(text, heading) for heading in AGENT_CARD_HEADINGS}
    missing = [heading for heading, section in sections.items() if not section]
    if missing:
        issues.append(
            Issue(
                "P1",
                "invalid_agent_card",
                f"Агент {agent_id}: нет разделов или содержимого: {', '.join(missing)}",
            )
        )
        return
    if sections["Роль"] != agent["role"]:
        issues.append(
            Issue("P1", "agent_role_mismatch", f"Агент {agent_id}: роль не совпадает с манифестом")
        )
    if sections["Профиль способностей"] != agent["capability"]:
        issues.append(
            Issue("P1", "agent_profile_mismatch", f"Агент {agent_id}: профиль не совпадает с манифестом")
        )
    for field, heading in (
        ("required_skills", "Обязательные скиллы"),
        ("optional_skills", "Опциональные скиллы"),
    ):
        if card_skills(text, heading) != agent[field]:
            issues.append(
                Issue("P1", "agent_skills_mismatch", f"Агент {agent_id}: скиллы не совпадают с манифестом")
            )


def is_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def check_v2_state(manifest: dict, root: Path, issues: list[Issue]) -> None:
    execution = manifest.get("execution")
    implementation = manifest.get("implementation")
    verification = manifest.get("verification", {})
    checkpoints = manifest.get("decision_checkpoints")
    if not isinstance(execution, dict) or not isinstance(implementation, dict):
        issues.append(Issue("P1", "invalid_manifest", "Схемы 2 и 3 требуют execution и implementation"))
        return
    if execution.get("owner") not in {"kimi_code", "kimi_work"}:
        issues.append(Issue("P1", "invalid_owner", "Основной исполнитель должен быть kimi_code или kimi_work"))
    if not isinstance(execution.get("implementation_authorized"), bool):
        issues.append(Issue("P1", "invalid_authorization", "implementation_authorized должен быть булевым"))
    if execution.get("continue_after_preflight") is not True:
        issues.append(Issue("P1", "extra_launch_gate", "После pre-flight требуется немедленная реализация"))
    implementation_status = implementation.get("status")
    if implementation_status not in VALID_IMPLEMENTATION_STATUSES:
        issues.append(Issue("P1", "invalid_implementation_status", "Неизвестный статус реализации"))
    if not isinstance(implementation.get("scope"), str) or not implementation.get("scope").strip():
        issues.append(Issue("P1", "missing_scope", "Нужен явный implementation.scope"))
    verification_status = verification.get("status")
    if verification_status not in VALID_VERIFICATION_STATUSES:
        issues.append(Issue("P1", "invalid_verification_status", "Неизвестный статус верификации"))
    if not isinstance(verification.get("independent_required"), bool):
        issues.append(Issue("P1", "invalid_manifest", "independent_required должен быть булевым"))
    for field in ("open_p0", "open_p1", "open_p2"):
        if not is_nonnegative_int(verification.get(field)):
            issues.append(Issue("P1", "invalid_finding_count", f"{field} должен быть целым числом не меньше 0"))
    status = manifest.get("status")
    if status == "running" and implementation_status != "in_progress":
        issues.append(Issue("P1", "status_mismatch", "running требует implementation.status=in_progress"))
    if status == "blocked" and implementation_status != "blocked":
        issues.append(Issue("P1", "status_mismatch", "blocked требует implementation.status=blocked"))
    if status == "verification_pending" and (
        implementation_status != "implemented" or verification_status != "pending"
    ):
        issues.append(Issue("P1", "status_mismatch", "verification_pending требует implemented и pending"))
    if isinstance(status, str) and status in RESULT_STATUSES and implementation_status != "implemented":
        issues.append(Issue("P1", "status_mismatch", "Итоговый статус требует implementation.status=implemented"))
    if isinstance(status, str) and status in RESULT_STATUSES and verification.get("enabled") and verification_status != "passed":
        issues.append(Issue("P1", "status_mismatch", "Итоговый статус требует verification.status=passed"))
    if isinstance(status, str) and status in RESULT_STATUSES and not verification.get("enabled") and verification_status != "self_checked":
        issues.append(Issue("P1", "status_mismatch", "Без независимой проверки нужен self_checked"))
    if not isinstance(checkpoints, list):
        issues.append(Issue("P1", "invalid_checkpoint", "decision_checkpoints должен быть списком"))
        return
    task_ids = {
        task.get("id") for task in manifest.get("tasks", []) if isinstance(task, dict)
    }
    checkpoint_ids: set[str] = set()
    for checkpoint in checkpoints:
        if not isinstance(checkpoint, dict):
            issues.append(Issue("P1", "invalid_checkpoint", "Чек-поинт должен быть объектом"))
            continue
        checkpoint_id = checkpoint.get("id")
        if (
            not isinstance(checkpoint_id, str)
            or not checkpoint_id
            or checkpoint_id in checkpoint_ids
        ):
            issues.append(Issue("P1", "invalid_checkpoint", "Недопустимый или повторный ID чек-поинта"))
            continue
        checkpoint_ids.add(checkpoint_id)
        after = checkpoint.get("after")
        if after != "preflight" and after not in task_ids:
            issues.append(Issue("P1", "invalid_checkpoint", f"Неизвестный этап чек-поинта: {after}"))
        if not isinstance(checkpoint.get("question"), str) or not checkpoint.get("question").strip():
            issues.append(Issue("P1", "invalid_checkpoint", f"Чек-поинт {checkpoint_id}: нужен вопрос"))
        if safe_path(root, root, checkpoint.get("output")) is None:
            issues.append(Issue("P1", "invalid_checkpoint", f"Чек-поинт {checkpoint_id}: небезопасный выход"))


def check_v3_models(manifest: dict, root: Path, issues: list[Issue]) -> None:
    profile_ref = manifest.get("model_profile")
    if not isinstance(profile_ref, dict):
        issues.append(Issue("P1", "invalid_model_profile", "Схема 3 требует model_profile"))
        return
    profile_path = safe_path(root, root, profile_ref.get("path"))
    if profile_path is None or not profile_path.is_file():
        issues.append(Issue("P1", "invalid_model_profile", "Нет доступного YAML-профиля моделей"))
        return
    declared_sha = profile_ref.get("sha256")
    if not isinstance(declared_sha, str) or not SHA256_PATTERN.fullmatch(declared_sha):
        issues.append(Issue("P1", "invalid_model_profile", "model_profile.sha256 должен быть SHA-256"))
    else:
        actual_sha = hashlib.sha256(profile_path.read_bytes()).hexdigest()
        if declared_sha != actual_sha:
            issues.append(Issue("P1", "invalid_model_profile", "SHA-256 профиля моделей не совпадает"))
    try:
        profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        issues.append(Issue("P1", "invalid_model_profile", "Некорректный YAML-профиль моделей"))
        return
    if not isinstance(profile, dict) or profile.get("name") != profile_ref.get("name"):
        issues.append(Issue("P1", "invalid_model_profile", "Имя активного профиля не совпадает с YAML"))
        return
    raw_aliases = profile.get("aliases")
    if not isinstance(raw_aliases, list):
        issues.append(Issue("P1", "invalid_model_profile", "Профиль требует список aliases"))
        return
    aliases: dict[tuple[str, str], str] = {}
    for item in raw_aliases:
        if not isinstance(item, dict) or any(
            not isinstance(item.get(field), str) or not item.get(field).strip()
            for field in ("model", "effort", "runtime_alias")
        ):
            issues.append(Issue("P1", "invalid_model_profile", "Каждый alias требует model, effort и runtime_alias"))
            continue
        key = (item["model"], item["effort"])
        if key in aliases:
            issues.append(Issue("P1", "invalid_model_profile", f"Повторная пара model+effort: {key[0]} {key[1]}"))
        aliases[key] = item["runtime_alias"]

    agent_by_id = {
        agent.get("id"): agent
        for agent in manifest.get("agents", [])
        if isinstance(agent, dict) and isinstance(agent.get("id"), str)
    }
    tasks = [task for task in manifest.get("tasks", []) if isinstance(task, dict)]
    task_by_id = {task.get("id"): task for task in tasks if isinstance(task.get("id"), str)}
    execution = manifest.get("execution", {})
    if not isinstance(execution, dict):
        return
    mode = execution.get("mode", "team")
    if not isinstance(mode, str) or mode not in {"team", "solo"}:
        issues.append(Issue("P1", "invalid_execution_mode", "execution.mode должен быть team или solo"))
    if mode == "solo":
        evidence = root / "RUN_LOG.md"
        try:
            text = evidence.read_text(encoding="utf-8").casefold() if evidence.is_file() else ""
        except (OSError, UnicodeError):
            text = ""
        if "явный выбор пользователя: solo" not in text:
            issues.append(Issue("P1", "missing_solo_approval", "Solo требует явного выбора пользователя"))
    status = manifest.get("status")
    if mode == "team" and isinstance(status, str) and status in {
        "running", "verification_pending", "result_verified", "done", "done_with_p2"
    }:
        permissions = manifest.get("permissions", {})
        if not isinstance(permissions, dict) or permissions.get("subagents") != "allow":
            issues.append(Issue("P1", "missing_subagent_permission", "Team требует исполнительных субагентов"))

    session_defaults = execution.get("session_defaults")
    if execution.get("owner") == "kimi_work":
        if not isinstance(session_defaults, dict):
            issues.append(Issue("P1", "session_default_mismatch", "Work требует session_defaults model и effort"))
            session_defaults = {}
    for task in tasks:
        task_id = task.get("id", "<unknown>")
        values = [task.get(field) for field in ("model", "effort", "reason")]
        if any(not isinstance(value, str) or not value.strip() for value in values):
            issues.append(Issue("P1", "invalid_model_assignment", f"Задача {task_id}: нужны model, effort и reason"))
            continue
        pair = (task["model"], task["effort"])
        if pair not in aliases:
            issues.append(Issue("P1", "invalid_model_assignment", f"Задача {task_id}: пары model+effort нет в runtime aliases"))
        source = task.get("assignment_source", "kimi")
        if not isinstance(source, str) or source not in {"kimi", "user_override", "work_session_default", "fixed_policy"}:
            issues.append(Issue("P1", "invalid_model_assignment", f"Задача {task_id}: неизвестный assignment_source"))
        if isinstance(session_defaults, dict) and session_defaults:
            if any(task.get(field) != session_defaults.get(field) for field in ("model", "effort")):
                issues.append(Issue("P1", "session_default_mismatch", f"Задача {task_id}: назначение не совпадает с Work defaults"))
        if task.get("kind") in {"verification", "model_review", "package_check"} or not isinstance(source, str) or source in {"user_override", "work_session_default"}:
            continue
        if task["effort"] not in {"high", "max"}:
            continue
        review_id = task.get("model_review_task")
        review = task_by_id.get(review_id) if isinstance(review_id, str) else None
        reviewer = agent_by_id.get(review.get("agent")) if isinstance(review, dict) else None
        if (
            not isinstance(review, dict)
            or review.get("kind") != "model_review"
            or not isinstance(reviewer, dict)
            or reviewer.get("role") != "model_reviewer"
            or review_id not in task.get("depends_on", [])
        ):
            issues.append(Issue("P1", "missing_model_review", f"Задача {task_id}: discretionary high/max требует предшествующего model reviewer"))


def check_manifest(manifest: dict, root: Path) -> list[Issue]:
    issues: list[Issue] = []
    agents = manifest.get("agents", [])
    tasks = manifest.get("tasks", [])
    verification = manifest.get("verification", {})
    if not isinstance(agents, list) or not isinstance(tasks, list) or not isinstance(verification, dict):
        return [Issue("P1", "invalid_manifest", "agents, tasks и verification имеют неверный тип")]
    if not isinstance(verification.get("enabled"), bool):
        issues.append(Issue("P1", "invalid_manifest", "verification.enabled должен быть булевым"))

    agent_by_id: dict[str, dict] = {}
    for agent in agents:
        if not isinstance(agent, dict):
            issues.append(Issue("P1", "invalid_manifest", "Элемент agents должен быть объектом"))
            continue
        agent_id = agent.get("id")
        if not isinstance(agent_id, str) or not agent_id or agent_id in agent_by_id:
            issues.append(Issue("P1", "duplicate_id", f"Недопустимый ID агента: {agent_id}"))
            continue
        required = ("role", "capability", "required_skills", "optional_skills", "path")
        if any(field not in agent for field in required):
            issues.append(Issue("P1", "invalid_agent", f"Агент {agent_id}: неполная карточка манифеста"))
            continue
        if (
            not all(isinstance(agent[field], str) for field in ("role", "capability", "path"))
            or not all(isinstance(agent[field], list) for field in ("required_skills", "optional_skills"))
            or any(
                not isinstance(skill, str)
                for field in ("required_skills", "optional_skills")
                for skill in agent[field]
            )
        ):
            issues.append(Issue("P1", "invalid_manifest", f"Агент {agent_id}: неверные типы полей"))
            continue
        agent_by_id[agent_id] = agent
        card_path = safe_path(root, root, agent["path"])
        if card_path is None:
            issues.append(Issue("P1", "unsafe_path", f"Агент {agent_id}: небезопасный путь"))
        elif not card_path.is_file():
            issues.append(Issue("P1", "missing_agent_file", f"Нет карточки агента: {agent_id}"))
        else:
            check_agent_card(agent, card_path, root, issues)

    task_by_id: dict[str, dict] = {}
    all_task_ids = {
        task.get("id") for task in tasks if isinstance(task, dict) and isinstance(task.get("id"), str)
    }
    for task in tasks:
        if not isinstance(task, dict):
            issues.append(Issue("P1", "invalid_manifest", "Элемент tasks должен быть объектом"))
            continue
        task_id = task.get("id")
        if not isinstance(task_id, str) or not task_id or task_id in task_by_id:
            issues.append(Issue("P1", "duplicate_id", f"Недопустимый ID задачи: {task_id}"))
            continue
        if not isinstance(task.get("depends_on"), list) or any(
            not isinstance(item, str) for item in task.get("depends_on", [])
        ):
            issues.append(Issue("P1", "invalid_manifest", f"Задача {task_id}: depends_on должен быть списком строк"))
            continue
        if (
            not isinstance(task.get("agent"), str)
            or not isinstance(task.get("inputs"), list)
            or not isinstance(task.get("outputs"), list)
            or any(not isinstance(item, str) for field in ("inputs", "outputs") for item in task[field])
        ):
            issues.append(Issue("P1", "invalid_manifest", f"Задача {task_id}: неверные типы полей"))
            continue
        task_by_id[task_id] = task
        if task["agent"] not in agent_by_id:
            issues.append(Issue("P1", "unknown_task_agent", f"Задача {task_id}: неизвестный агент"))
        for dependency in task["depends_on"]:
            if dependency not in all_task_ids:
                issues.append(Issue("P1", "unknown_dependency", f"Задача {task_id}: нет зависимости {dependency}"))

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> bool:
        if task_id in visiting:
            return True
        if task_id in visited:
            return False
        visiting.add(task_id)
        for dependency in task_by_id[task_id]["depends_on"]:
            if dependency in task_by_id and visit(dependency):
                return True
        visiting.remove(task_id)
        visited.add(task_id)
        return False

    if any(visit(task_id) for task_id in task_by_id):
        issues.append(Issue("P1", "dag_cycle", "DAG содержит цикл"))

    def ancestors(task_id: str) -> set[str]:
        result: set[str] = set()
        pending = list(task_by_id[task_id]["depends_on"])
        while pending:
            dependency = pending.pop()
            if dependency in result or dependency not in task_by_id:
                continue
            result.add(dependency)
            pending.extend(task_by_id[dependency]["depends_on"])
        return result

    generation_tasks = [task for task in task_by_id.values() if task.get("kind") == "generation"]
    for task in task_by_id.values():
        task_ancestors = ancestors(task["id"])
        for relative in task["inputs"]:
            input_path = safe_path(root, root, relative)
            if input_path is None:
                issues.append(Issue("P1", "unsafe_path", f"Задача {task['id']}: небезопасный вход {relative}"))
                continue
            if input_path.exists():
                continue
            producers = [item["id"] for item in generation_tasks if relative in item["outputs"]]
            if not producers:
                issues.append(Issue("P1", "missing_input", f"Задача {task['id']}: нет входа {relative}"))
            elif not any(producer in task_ancestors for producer in producers):
                issues.append(
                    Issue("P1", "missing_input_producer", f"Задача {task['id']}: вход {relative} не производится предком")
                )

    status = manifest.get("status")
    if not isinstance(status, str) or status not in VALID_STATUSES:
        issues.append(Issue("P1", "invalid_status", f"Неизвестный статус: {status}"))

    level = verification.get("level")
    if not isinstance(level, str) or level not in VALID_LEVELS:
        issues.append(Issue("P1", "invalid_level", f"Неизвестный уровень проверки: {level}"))

    if verification.get("enabled"):
        verifier_id = verification.get("verifier")
        verifier = agent_by_id.get(verifier_id) if isinstance(verifier_id, str) else None
        if not verifier or verifier.get("role") != "verifier":
            issues.append(Issue("P1", "invalid_verifier", "Нужен отдельный агент с ролью verifier"))
        for task in task_by_id.values():
            if task.get("agent") == verifier_id and task.get("kind") == "generation":
                issues.append(Issue("P1", "verifier_generates", "Верификатор назначен на генерацию"))
        small_profile = verification.get("small_profile")
        if not isinstance(small_profile, str) or small_profile not in SMALL_PROFILES:
            issues.append(Issue("P1", "invalid_profile", "Неизвестный малый профиль"))
        full_profiles = verification.get("full_profiles", [])
        if not isinstance(full_profiles, list) or any(
            not isinstance(profile, str) or profile not in FULL_PROFILES for profile in full_profiles
        ):
            issues.append(Issue("P1", "invalid_profile", "Неизвестный полный профиль"))
        if level == "full" and not full_profiles:
            issues.append(Issue("P1", "invalid_profile", "Полная проверка требует профиль П1–П14"))

        verification_tasks = [
            task
            for task in task_by_id.values()
            if task.get("agent") == verifier_id and task.get("kind") == "verification"
        ]
        if not verification_tasks:
            issues.append(
                Issue("P1", "missing_verification_task", "Нет задачи verification выбранного верификатора")
            )
        for verification_task in verification_tasks:
            checked_outputs = set(verification_task["inputs"])
            for generation in generation_tasks:
                if not checked_outputs.intersection(generation["outputs"]):
                    continue
                if generation["id"] not in verification_task["depends_on"]:
                    issues.append(
                        Issue(
                            "P1",
                            "missing_verification_dependency",
                            f"Проверка {verification_task['id']} не зависит от генерационной задачи {generation['id']}",
                        )
                    )
    if manifest.get("schema_version") in {2, 3}:
        check_v2_state(manifest, root, issues)
    if manifest.get("schema_version") == 3:
        check_v3_models(manifest, root, issues)
    return issues


def check_evidence(path: Path, root: Path, status: str, issues: list[Issue]) -> None:
    text = read_text(path, issues, root)
    if text is None:
        return
    fields = {match.group(1).lower(): match.group(2) for match in EVIDENCE_PATTERN.finditer(text)}
    if any(not fields.get(field) for field in ("действие", "доказательство", "итог")):
        issues.append(
            Issue("P1", "invalid_evidence", f"Нужны действие, доказательство и итог: {path.relative_to(root)}")
        )
        return
    open_findings = fields.get("открытые замечания")
    if open_findings and re.search(r"\bP[01]\b", open_findings):
        issues.append(Issue("P1", "blocking_finding", "Открытые P0/P1 блокируют готовность"))
        return
    if status not in {"done", "done_with_p2"} or path.name != "REPORT.md":
        return
    if not open_findings:
        issues.append(Issue("P1", "invalid_evidence", "Итоговый отчет требует открытые замечания или нет"))
    elif status == "done" and open_findings.lower() != "нет":
        issues.append(Issue("P1", "unexpected_open_finding", "Статус done требует отсутствие открытых замечаний"))
    elif status == "done_with_p2" and open_findings.lower() != "нет" and any(
        not re.match(r"^\s*P2\s*:\s*\S", finding) for finding in open_findings.split(";")
    ):
        issues.append(Issue("P1", "unexpected_open_finding", "Статус done_with_p2 допускает только открытые P2"))


def read_front_matter(path: Path, root: Path, issues: list[Issue]) -> dict | None:
    text = read_text(path, issues, root)
    if text is None:
        return None
    match = FRONT_MATTER_PATTERN.match(text)
    if not match:
        issues.append(Issue("P1", "invalid_report_metadata", "Схемы 2 и 3 требуют YAML front matter в REPORT.md"))
        return None
    try:
        metadata = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        issues.append(Issue("P1", "invalid_report_metadata", f"Некорректный front matter: {exc}"))
        return None
    if not isinstance(metadata, dict):
        issues.append(Issue("P1", "invalid_report_metadata", "Front matter должен быть объектом"))
        return None
    return metadata


def result_file_hashes(manifest: dict, root: Path, issues: list[Issue]) -> dict[str, str]:
    result: dict[str, str] = {}
    for task in manifest.get("tasks", []):
        if not isinstance(task, dict) or task.get("kind") != "generation":
            continue
        for relative in task.get("outputs", []):
            if relative == "RUN_LOG.md" or relative.startswith("verification/"):
                continue
            path = safe_path(root, root, relative)
            if path is None:
                continue
            paths = sorted(path.rglob("*")) if path.is_dir() else [path]
            for item in paths:
                if not item.is_file():
                    if item == path:
                        issues.append(Issue("P1", "missing_output", f"Нет выхода: {relative}"))
                    continue
                name = item.relative_to(root).as_posix()
                try:
                    result[name] = hashlib.sha256(item.read_bytes()).hexdigest()
                except OSError as exc:
                    issues.append(Issue("P1", "file_read_error", f"Ошибка чтения {name}: {exc}"))
    return result


def canonical_revision(value: object) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def criteria_for_revision(manifest: dict) -> dict:
    verification = manifest.get("verification", {})
    return {
        "scope": manifest.get("scope"),
        "implementation_scope": manifest.get("implementation", {}).get("scope"),
        "verification": {
            field: verification.get(field)
            for field in ("enabled", "level", "small_profile", "full_profiles")
        },
    }


def criteria_revision(manifest: dict) -> str:
    return canonical_revision(criteria_for_revision(manifest))


def check_result_revision(manifest: dict, root: Path, report: Path, issues: list[Issue]) -> None:
    metadata = read_front_matter(report, root, issues)
    if metadata is None:
        return
    if metadata.get("independent") is not True:
        issues.append(Issue("P1", "not_independent", "Отчёт не подтверждает независимость"))
    declared_criteria = metadata.get("criteria_revision")
    if not isinstance(declared_criteria, str) or not SHA256_PATTERN.fullmatch(declared_criteria):
        issues.append(Issue("P1", "invalid_report_metadata", "criteria_revision должен быть SHA-256"))
    elif declared_criteria != criteria_revision(manifest):
        issues.append(Issue("P1", "stale_verification", "Критерии изменились после проверки"))
    declared_files = metadata.get("result_files")
    if not isinstance(declared_files, dict) or any(
        not isinstance(name, str)
        or not isinstance(digest, str)
        or not SHA256_PATTERN.fullmatch(digest)
        for name, digest in declared_files.items()
    ):
        issues.append(Issue("P1", "invalid_report_metadata", "result_files должен содержать SHA-256 файлов"))
        declared_files = None
    actual_files = result_file_hashes(manifest, root, issues)
    if declared_files is not None and declared_files != actual_files:
        issues.append(Issue("P1", "stale_verification", "Файлы результата изменились после проверки"))
    declared_revision = metadata.get("result_revision")
    if not isinstance(declared_revision, str) or not SHA256_PATTERN.fullmatch(declared_revision):
        issues.append(Issue("P1", "invalid_report_metadata", "result_revision должен быть SHA-256"))
    elif declared_revision != canonical_revision(actual_files):
        issues.append(Issue("P1", "stale_verification", "Ревизия результата не совпадает с отчётом"))
    verification = manifest.get("verification", {})
    for field in ("open_p0", "open_p1", "open_p2"):
        value = metadata.get(field)
        if not is_nonnegative_int(value):
            issues.append(Issue("P1", "invalid_report_metadata", f"{field} должен быть целым числом не меньше 0"))
            continue
        if verification.get(field) != value:
            issues.append(Issue("P1", "verification_mismatch", f"{field} не совпадает с манифестом"))
    if any(is_nonnegative_int(metadata.get(field)) and metadata[field] > 0 for field in ("open_p0", "open_p1")):
        issues.append(Issue("P1", "blocking_finding", "Отчёт содержит открытые P0/P1"))
    status = manifest.get("status")
    if status == "done" and any(metadata.get(field) != 0 for field in ("open_p0", "open_p1", "open_p2")):
        issues.append(Issue("P1", "unexpected_open_finding", "done требует нулевые счётчики замечаний"))
    if status == "done_with_p2" and metadata.get("open_p2", 0) < 1:
        issues.append(Issue("P1", "unexpected_open_finding", "done_with_p2 требует открытый P2"))


def check_approval(manifest: dict, root: Path, issues: list[Issue]) -> None:
    if manifest.get("schema_version") not in {2, 3} or manifest.get("status") != "ready_for_kimi_code":
        return
    execution = manifest.get("execution", {})
    if execution.get("implementation_authorized") is not True:
        issues.append(Issue("P1", "missing_approval", "ready_for_kimi_code требует разрешение реализации"))
    approval = execution.get("approval")
    if not isinstance(approval, dict):
        issues.append(Issue("P1", "missing_approval", "Нет execution.approval"))
        return
    if not isinstance(approval.get("approved_at"), str) or not approval.get("approved_at").strip():
        issues.append(Issue("P1", "missing_approval", "Нет approved_at"))
    if approval.get("approved_by") != "user":
        issues.append(Issue("P1", "missing_approval", "approved_by должен быть user"))
    evidence = safe_path(root, root, approval.get("evidence"))
    if evidence is None or not evidence.is_file():
        issues.append(Issue("P1", "missing_approval", "Нет файла доказательства согласования"))
        return
    text = read_text(evidence, issues, root)
    if text is not None and "стартовое согласование пользователя" not in text.lower():
        issues.append(Issue("P1", "missing_approval", "Нет записи стартового согласования пользователя"))


def check_preflight(manifest: dict, root: Path, issues: list[Issue]) -> None:
    if manifest.get("schema_version") not in {2, 3} or manifest.get("status") != "preflight_passed":
        return
    path = root / "verification" / "PREFLIGHT.json"
    if not path.is_file():
        issues.append(Issue("P1", "missing_evidence", "Статус требует файл: verification/PREFLIGHT.json"))
        return
    text = read_text(path, issues, root)
    if text is None:
        return
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        issues.append(Issue("P1", "invalid_preflight", f"Некорректный PREFLIGHT.json: {exc}"))
        return
    if not isinstance(data, dict):
        issues.append(Issue("P1", "invalid_preflight", "PREFLIGHT.json должен быть объектом"))
        return
    required_fields = {
        "checked_at",
        "environment",
        "workspace",
        "python_path",
        "python_version",
        "required_skills",
        "missing_inputs",
        "open_p0",
        "open_p1",
        "open_p2",
        "status",
    }
    missing = sorted(required_fields - set(data))
    if missing:
        issues.append(Issue("P1", "invalid_preflight", f"Нет полей pre-flight: {', '.join(missing)}"))
    for field in ("checked_at", "environment", "workspace"):
        if not isinstance(data.get(field), str) or not data.get(field).strip():
            issues.append(Issue("P1", "invalid_preflight", f"Поле {field} должно быть непустой строкой"))
    if data.get("status") != "passed":
        issues.append(Issue("P1", "invalid_preflight", "preflight_passed требует status=passed"))
    if data.get("missing_inputs") != []:
        issues.append(Issue("P1", "invalid_preflight", "preflight_passed требует пустой missing_inputs"))
    for field in ("open_p0", "open_p1"):
        if data.get(field) != 0:
            issues.append(Issue("P1", "invalid_preflight", f"preflight_passed требует {field}=0"))
    if not is_nonnegative_int(data.get("open_p2")):
        issues.append(Issue("P1", "invalid_preflight", "open_p2 должен быть целым числом не меньше 0"))
    records = data.get("required_skills")
    if not isinstance(records, list):
        issues.append(Issue("P1", "invalid_preflight", "required_skills должен быть списком"))
        records = []
    invoked = {
        record.get("name")
        for record in records
        if isinstance(record, dict) and record.get("invoked") is True and isinstance(record.get("name"), str)
    }
    required = {
        skill
        for agent in manifest.get("agents", [])
        if isinstance(agent, dict)
        for skill in agent.get("required_skills", [])
        if isinstance(skill, str)
    }
    if not required.issubset(invoked):
        issues.append(Issue("P1", "missing_skill_evidence", "Не подтверждён вызов всех обязательных скиллов"))


def check_files_and_evidence(manifest: dict, root: Path) -> list[Issue]:
    issues: list[Issue] = []
    status = manifest.get("status")
    is_result_status = isinstance(status, str) and status in RESULT_STATUSES
    evidence_files = STATUS_EVIDENCE.get(status, ()) if isinstance(status, str) else ()
    if is_result_status and not manifest.get("verification", {}).get("enabled"):
        evidence_files = ("RUN_LOG.md",)
    for relative in evidence_files:
        path = root / relative
        if not path.is_file():
            issues.append(Issue("P1", "missing_evidence", f"Статус требует файл: {relative}"))
        else:
            check_evidence(path, root, status, issues)
    if isinstance(status, str) and status in {"done", "done_with_p2"}:
        completion = manifest.get("completion", {})
        for relative in completion.get("required_evidence", []):
            path = safe_path(root, root, relative)
            if path is None:
                issues.append(Issue("P1", "unsafe_path", f"Небезопасный файл доказательства: {relative}"))
            elif not path.is_file():
                issues.append(Issue("P1", "missing_evidence", f"Нет файла доказательства: {relative}"))
            else:
                check_evidence(path, root, status, issues)
    check_approval(manifest, root, issues)
    check_preflight(manifest, root, issues)
    if (
        manifest.get("schema_version") in {2, 3}
        and is_result_status
        and manifest.get("verification", {}).get("enabled")
        and (root / "verification" / "REPORT.md").is_file()
    ):
        check_result_revision(manifest, root, root / "verification" / "REPORT.md", issues)
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = read_text(path, issues, root)
        if text is None:
            continue
        if chr(0x2014) in text:
            issues.append(Issue("P1", "forbidden_dash", f"Длинное тире: {path.relative_to(root)}"))
        if path.suffix.lower() == ".md":
            for raw_target in LINK_PATTERN.findall(text):
                if raw_target.startswith("#") or "://" in raw_target or raw_target.startswith(("mailto:", "tel:")):
                    continue
                target = raw_target.split("#", 1)[0].strip()
                if not target:
                    continue
                resolved = safe_path(root, path.parent, target)
                if resolved is None:
                    issues.append(Issue("P1", "unsafe_path", f"Небезопасная ссылка {target}: {path.relative_to(root)}"))
                elif not resolved.is_file():
                    issues.append(Issue("P1", "broken_link", f"Битая ссылка {target}: {path.relative_to(root)}"))
    return issues


def validate_package(root: Path) -> list[Issue]:
    root = Path(root).resolve()
    issues: list[Issue] = []
    for relative in REQUIRED_FILES:
        if not (root / relative).is_file():
            issues.append(Issue("P1", "missing_file", f"Нет файла: {relative}"))

    manifest_path = root / "MANIFEST.yaml"
    if not manifest_path.is_file():
        return issues
    manifest_text = read_text(manifest_path, issues, root)
    if manifest_text is None:
        return issues
    try:
        manifest = yaml.safe_load(manifest_text)
    except yaml.YAMLError as exc:
        issues.append(Issue("P1", "invalid_yaml", f"Некорректный YAML: {exc}"))
        return issues
    if not isinstance(manifest, dict):
        issues.append(Issue("P1", "invalid_manifest", "Корень манифеста должен быть объектом"))
        return issues
    if manifest.get("schema_version") in {2, 3}:
        for relative in V2_REQUIRED_FILES:
            if not (root / relative).is_file():
                issues.append(Issue("P1", "missing_file", f"Нет файла: {relative}"))
    issues.extend(check_manifest(manifest, root))
    issues.extend(check_files_and_evidence(manifest, root))
    if manifest.get("schema_version") in {2, 3}:
        from work_subagent_verification import check_workflow_extensions

        for severity, code, message in check_workflow_extensions(manifest, root):
            issues.append(Issue(severity, code, message))
    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("package", type=Path, nargs="?")
    parser.add_argument("--criteria-revision", type=Path, metavar="PACKAGE")
    parser.add_argument("--package-revision", type=Path, metavar="PACKAGE")
    args = parser.parse_args()
    if args.criteria_revision is not None:
        manifest_path = args.criteria_revision / "MANIFEST.yaml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        print(criteria_revision(manifest))
        return 0
    if args.package_revision is not None:
        from work_subagent_verification import package_revision

        manifest_path = args.package_revision / "MANIFEST.yaml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        print(package_revision(manifest, args.package_revision))
        return 0
    if args.package is None:
        parser.error("требуется package")
    issues = validate_package(args.package)
    for issue in issues:
        print(f"{issue.severity} {issue.code}: {issue.message}")
    return 1 if any(issue.severity in {"P0", "P1"} for issue in issues) else 0


if __name__ == "__main__":
    raise SystemExit(main())
