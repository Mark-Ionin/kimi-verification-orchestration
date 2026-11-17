from __future__ import annotations

import copy
import hashlib
import json
import re
import shlex
from pathlib import Path

import yaml


PERMISSION_VALUES = {"ask", "allow", "deny"}
PACKAGE_CHECK_STATUSES = {"not_started", "pending", "passed", "failed", "stale"}
READY_STATUSES = {"ready_for_kimi_code", "ready_for_work"}
EXECUTION_STATUSES = {
    "ready_for_work",
    "running",
    "verification_pending",
    "result_verified",
    "done_with_p2",
    "done",
    "cancelled",
    "interrupted",
}
RESULT_STATUSES = {"result_verified", "done_with_p2", "done"}
FRONT_MATTER_PATTERN = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def canonical_revision(value: object) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def safe_path(root: Path, relative: object) -> Path | None:
    if not isinstance(relative, str) or not relative.strip() or Path(relative).is_absolute():
        return None
    resolved = (root / relative).resolve()
    return resolved if resolved.is_relative_to(root.resolve()) else None


def package_revision(manifest: dict, root: Path) -> str:
    static = copy.deepcopy(manifest)
    static.pop("status", None)
    static.pop("package_check", None)
    implementation = static.get("implementation")
    if isinstance(implementation, dict):
        implementation.pop("status", None)
        implementation.pop("draft_outputs", None)
    verification = static.get("verification")
    if isinstance(verification, dict):
        for field in ("status", "open_p0", "open_p1", "open_p2"):
            verification.pop(field, None)
    files = {"MANIFEST.yaml": canonical_revision(static)}
    relative_files = {"00_ORCHESTRATOR.md", "LAUNCH.md", "verification/PLAN.md"}
    agents = manifest.get("agents")
    if not isinstance(agents, list):
        agents = []
    relative_files.update(
        agent["path"]
        for agent in agents
        if isinstance(agent, dict) and isinstance(agent.get("path"), str)
    )
    model_profile = manifest.get("model_profile")
    if manifest.get("schema_version") == 3 and isinstance(model_profile, dict):
        profile_path = model_profile.get("path")
        if isinstance(profile_path, str):
            relative_files.add(profile_path)
    for relative in sorted(relative_files):
        path = safe_path(root, relative)
        if path is None or not path.is_file():
            continue
        files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return canonical_revision(files)


def read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def read_report_metadata(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    match = FRONT_MATTER_PATTERN.match(text)
    if not match:
        return None
    try:
        value = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None
    return value if isinstance(value, dict) else None


def check_workflow_extensions(manifest: dict, root: Path) -> list[tuple[str, str, str]]:
    findings: list[tuple[str, str, str]] = []

    def issue(code: str, message: str) -> None:
        findings.append(("P1", code, message))

    execution = manifest.get("execution", {})
    implementation = manifest.get("implementation", {})
    verification = manifest.get("verification", {})
    if not isinstance(execution, dict):
        return findings
    if not isinstance(implementation, dict):
        implementation = {}
    if not isinstance(verification, dict):
        verification = {}
    status = manifest.get("status")
    if not isinstance(status, str):
        return findings
    owner = execution.get("owner")
    if owner not in {"kimi_code", "kimi_work"}:
        return findings
    stop_policy = execution.get("stop_policy")
    if owner == "kimi_work" and stop_policy != "cooperative":
        issue("invalid_stop_policy", "kimi_work требует execution.stop_policy=cooperative")
    if owner == "kimi_code" and stop_policy is not None:
        issue("invalid_stop_policy", "kimi_code требует отсутствие stop_policy или null")

    permissions = manifest.get("permissions")
    if permissions is None:
        if owner == "kimi_work":
            issue("invalid_manifest", "kimi_work требует отдельные permissions")
        permissions = {}
    if not isinstance(permissions, dict):
        issue("invalid_manifest", "permissions должен быть объектом")
        return findings
    for field in ("subagents", "verifier_subagent", "swarm"):
        value = permissions.get(field, "ask")
        if value not in PERMISSION_VALUES:
            issue("invalid_permission", f"{field} принимает ask, allow или deny")

    agents = manifest.get("agents")
    if not isinstance(agents, list):
        agents = []
    agent_by_id = {
        agent.get("id"): agent
        for agent in agents
        if isinstance(agent, dict) and isinstance(agent.get("id"), str)
    }
    approved = permissions.get("approved_agents", [])
    if not isinstance(approved, list) or any(not isinstance(item, str) for item in approved):
        issue("invalid_manifest", "approved_agents должен быть списком строк")
        approved = []
    if len(set(approved)) != len(approved):
        issue("invalid_manifest", "approved_agents не должен содержать дубликаты")
    for agent_id in approved:
        if agent_id not in agent_by_id:
            issue("unknown_approved_agent", f"Неизвестный согласованный агент: {agent_id}")
    approved_set = set(approved)
    max_parallel = permissions.get("max_parallel", 1)
    if not isinstance(max_parallel, int) or isinstance(max_parallel, bool) or max_parallel < 1:
        issue("invalid_parallelism", "max_parallel должен быть целым числом не меньше 1")
        max_parallel = 1
    if max_parallel > 1 and permissions.get("swarm") != "allow":
        issue("invalid_parallelism", "max_parallel больше 1 требует swarm=allow")

    evidence_path = safe_path(root, permissions.get("evidence", "RUN_LOG.md"))
    evidence_text = ""
    if evidence_path is None or not evidence_path.is_file():
        if any(permissions.get(field) == "allow" for field in ("subagents", "verifier_subagent", "swarm")):
            issue("missing_permission_evidence", "allow требует файл фактических разрешений")
    else:
        try:
            evidence_text = evidence_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            issue("missing_permission_evidence", "Не удалось прочитать доказательства разрешений")
    lowered_evidence = evidence_text.casefold()
    if any(permissions.get(field) == "allow" for field in ("subagents", "verifier_subagent", "swarm")):
        if "стартовое согласование пользователя" not in lowered_evidence:
            issue("missing_permission_evidence", "allow требует фактический ответ пользователя")
        for field, markers in {
            "subagents": ("subagents", "исполнительн"),
            "verifier_subagent": ("verifier_subagent", "верификатор", "проверяющ"),
            "swarm": ("swarm",),
        }.items():
            if permissions.get(field) == "allow" and not any(marker in lowered_evidence for marker in markers):
                issue("missing_permission_evidence", f"В журнале не подтверждена область {field}")

    schema3_team_code = (
        manifest.get("schema_version") == 3
        and owner == "kimi_code"
        and execution.get("mode", "team") == "team"
    )
    if (owner == "kimi_work" or schema3_team_code) and status in EXECUTION_STATUSES:
        tasks = manifest.get("tasks")
        if not isinstance(tasks, list):
            tasks = []
        generation_agents = {
            task.get("agent")
            for task in tasks
            if isinstance(task, dict) and task.get("kind") == "generation"
        }
        if generation_agents and permissions.get("subagents") != "allow":
            issue("missing_subagent_permission", "Team-исполнение требует разрешения исполнительных субагентов")
        for agent_id in sorted(generation_agents - approved_set):
            issue("unapproved_agent", f"Исполнительный агент не согласован: {agent_id}")

    verifier_id = verification.get("verifier")
    if verification.get("enabled") and permissions.get("verifier_subagent") == "allow":
        if verifier_id not in approved_set and status in EXECUTION_STATUSES | READY_STATUSES:
            issue("unapproved_agent", "Верификатор не входит в approved_agents")

    package_check = manifest.get("package_check")
    if package_check is not None and not isinstance(package_check, dict):
        issue("invalid_manifest", "package_check должен быть объектом")
        package_check = None
    if (owner == "kimi_work" or manifest.get("schema_version") == 3) and package_check is None:
        issue("package_check_required", "Схема 3 и kimi_work требуют package_check")
    if status == "ready_for_work" and execution.get("implementation_authorized") is not True:
        issue("missing_approval", "ready_for_work требует разрешение реализации")
    if status in READY_STATUSES and package_check is not None:
        if package_check.get("status") != "passed":
            issue("package_check_required", "Готовность требует package_check.status=passed")
        if permissions.get("verifier_subagent") != "allow":
            issue("missing_verifier_permission", "Проверка пакета требует verifier_subagent=allow")
        if package_check.get("agent") not in approved_set:
            issue("unapproved_agent", "package_checker не входит в approved_agents")
    if status == "package_check_pending" and package_check is not None:
        if package_check.get("status") == "passed":
            issue("status_mismatch", "package_check_pending несовместим с passed")

    if isinstance(package_check, dict):
        if package_check.get("status") not in PACKAGE_CHECK_STATUSES:
            issue("invalid_package_check_status", "Неизвестный package_check.status")
        if package_check.get("status") == "passed":
            check_package_evidence(manifest, root, package_check, agent_by_id, issue)

    drafts = implementation.get("draft_outputs", [])
    if not isinstance(drafts, list) or any(safe_path(root, item) is None for item in drafts):
        issue("invalid_manifest", "draft_outputs должен быть списком безопасных путей")
        drafts = []
    if drafts and status in RESULT_STATUSES | {"verification_pending"}:
        issue("draft_outputs_not_final", "Черновые выходы не могут входить в завершённую реализацию")

    if status in RESULT_STATUSES and verification.get("enabled") and permissions:
        if permissions.get("verifier_subagent") != "allow":
            issue("missing_verifier_permission", "Независимый результат требует verifier_subagent=allow")
        if verifier_id not in approved_set:
            issue("unapproved_agent", "Верификатор результата не согласован")
        metadata = read_report_metadata(root / "verification" / "REPORT.md")
        if metadata is not None:
            invocation_id = metadata.get("invocation_id")
            if (
                metadata.get("verifier_agent") != verifier_id
                or not isinstance(invocation_id, str)
                or not invocation_id.strip()
                or invocation_id not in evidence_text
                or str(verifier_id) not in evidence_text
            ):
                issue("missing_subagent_trace", "Нет согласованного следа реального субагента-верификатора")
            declared_files = metadata.get("result_files", {})
            if isinstance(declared_files, dict):
                for name in declared_files:
                    if any(name == draft or name.startswith(draft.rstrip("/") + "/") for draft in drafts):
                        issue("draft_in_result", f"Черновой файл включён в результат: {name}")

    if status in {"cancelled", "interrupted"}:
        if owner != "kimi_work":
            issue("status_mismatch", f"{status} применяется только к kimi_work")
        if implementation.get("status") == "implemented":
            issue("status_mismatch", f"{status} не является завершённой реализацией")
    if status == "cancelled" and not (
        "контролируемая остановка между завершёнными вызовами" in lowered_evidence
        and "новые ветки не запускались" in lowered_evidence
    ):
        issue("invalid_cancellation_evidence", "cancelled требует подтверждённую остановку между вызовами")
    if status == "interrupted" and not (
        "целостность не подтверждена" in lowered_evidence
        and "автоматическое продолжение запрещено" in lowered_evidence
    ):
        issue("invalid_interruption_evidence", "interrupted требует неподтверждённую целостность и запрет продолжения")
    interruption_position = lowered_evidence.rfind("-> interrupted")
    if interruption_position >= 0 and status != "interrupted":
        decision_position = lowered_evidence.find("решение пользователя:", interruption_position)
        if decision_position < 0:
            issue("automatic_resume", "После interrupted требуется явное решение пользователя")
    return findings


def check_package_evidence(manifest: dict, root: Path, package_check: dict, agent_by_id: dict, issue) -> None:
    agent_id = package_check.get("agent")
    agent = agent_by_id.get(agent_id)
    if not agent or agent.get("role") != "package_checker":
        issue("invalid_package_checker", "package_check.agent должен ссылаться на package_checker")
    result_path = safe_path(root, package_check.get("result"))
    log_path = safe_path(root, package_check.get("log"))
    if result_path is None or log_path is None or not result_path.is_file() or not log_path.is_file():
        issue("invalid_package_check_evidence", "Нет машиночитаемого результата или журнала package_checker")
        return
    record = read_json(result_path)
    if record is None:
        issue("invalid_package_check_evidence", "Результат package_checker должен быть JSON-объектом")
        return
    trace = record.get("trace")
    invocation_id = trace.get("invocation_id") if isinstance(trace, dict) else None
    if (
        record.get("record_type") != "actual_validator_run"
        or not isinstance(record.get("command"), (str, list))
        or record.get("exit_code") != 0
        or not isinstance(record.get("stdout"), str)
        or not isinstance(record.get("stderr"), str)
        or not isinstance(invocation_id, str)
        or not invocation_id.strip()
    ):
        issue("invalid_package_check_evidence", "Недостаточно фактических полей запуска валидатора")
        return
    command = record["command"]
    try:
        tokens = shlex.split(command) if isinstance(command, str) else command
    except ValueError:
        tokens = []
    validator_path = record.get("validator_path")
    if (
        not isinstance(validator_path, str)
        or not validator_path.strip()
        or not Path(validator_path).is_absolute()
        or Path(validator_path).name != "validate_package.py"
        or not tokens
        or any(not isinstance(token, str) for token in tokens)
    ):
        issue("invalid_package_check_evidence", "Нужен абсолютный validator_path и корректная команда")
        return
    declared_validator = Path(validator_path).resolve()
    package_root = root.resolve()
    if not any(
        Path(token).is_absolute() and Path(token).resolve() == declared_validator
        for token in tokens
    ):
        issue("invalid_package_check_evidence", "Команда не использует согласованный абсолютный validator_path")
        return
    if not any(
        Path(token).is_absolute() and Path(token).resolve() == package_root
        for token in tokens
    ):
        issue("invalid_package_check_evidence", "Команда должна содержать абсолютный путь пакета, а не путь от cwd")
        return
    declared_revision = record.get("package_revision")
    if not isinstance(declared_revision, str) or not SHA256_PATTERN.fullmatch(declared_revision):
        issue("invalid_package_check_evidence", "package_revision должен быть SHA-256")
    elif declared_revision != package_revision(manifest, root):
        issue("stale_package_check", "Проверяемые файлы пакета изменились после проверки")
    try:
        log_text = log_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        issue("invalid_package_check_evidence", "Не удалось прочитать журнал package_checker")
        return
    if invocation_id not in log_text or "код выхода: 0" not in log_text.casefold():
        issue("invalid_package_check_evidence", "Журнал не связан с фактическим вызовом валидатора")
