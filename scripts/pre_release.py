"""Local pre-release gate for the public repository.

Inventory checks cover required files, allowed top-level layout, denied caches
and service artifacts, symlinks, installers, GitHub Actions workflows and
secret patterns. Child checks run the public tests and template validator.
Findings carry severity, code and a root-relative path only; matched text is
never copied into findings.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Sequence

SCHEMA_VERSION = 1
SEVERITY = "P1"
REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "SKILL.md",
    "README.md",
    "LICENSE",
    "RELEASE.md",
    ".gitignore",
    "requirements.txt",
    "requirements-dev.txt",
    "instructions/AGENTS.md",
    "instructions/core/orchestration.md",
    "instructions/adapters/kimi-code.md",
    "instructions/adapters/work.md",
    "instructions/templates/task-package/MANIFEST.yaml",
    "instructions/templates/task-package/model-profile.yaml",
    "scripts/validate_package.py",
    "scripts/work_subagent_verification.py",
    "scripts/pre_release.py",
    "tests/test_schema3.py",
    "tests/test_pre_release.py",
]

ALLOWED_TOP_LEVEL = {
    "SKILL.md",
    "README.md",
    "LICENSE",
    "RELEASE.md",
    ".gitignore",
    "requirements.txt",
    "requirements-dev.txt",
    "instructions",
    "scripts",
    "tests",
}

FORBIDDEN_PARTS = {"backups", "pilots", "handoff", "sessions", ".venv", "venv", ".pytest_cache"}

INSTALLER_NAMES = {"install.py", "install.sh", "installer.py", "installer.sh", "setup.py", "setup.sh"}

TEXT_SUFFIXES = {".md", ".py", ".yaml", ".yml", ".json", ".txt", ".gitignore", ""}

SECRET_PATTERNS = {
    "windows_user_path": re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+", re.IGNORECASE),
    "private_key": re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
    "oauth_token": re.compile(r"(?:oauth|access|refresh)[_-]?token\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{12,}", re.IGNORECASE),
    "api_key": re.compile(r"api[_-]?key\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{12,}", re.IGNORECASE),
    "github_token": re.compile(r"(?:ghp|github_pat)_[A-Za-z0-9_]{12,}"),
    "generic_secret": re.compile(r"(?:secret|password)\s*[:=]\s*['\"]?[^\s'\"]{12,}", re.IGNORECASE),
}


def _finding(code: str, path: str) -> dict:
    return {"severity": SEVERITY, "code": code, "path": path}


def scan_repository(root: Path) -> list[dict]:
    root = Path(root)
    findings: list[dict] = []
    for relative in REQUIRED_FILES:
        if not (root / relative).is_file():
            findings.append(_finding("missing_required_file", relative))
    files = sorted(
        path for path in root.rglob("*")
        if ".git" not in path.relative_to(root).parts and path.is_file()
    )
    directories = sorted(
        path for path in root.rglob("*")
        if ".git" not in path.relative_to(root).parts and path.is_dir()
    )
    for path in files:
        relative = path.relative_to(root)
        posix = relative.as_posix()
        if relative.parts[0] not in ALLOWED_TOP_LEVEL:
            findings.append(_finding("unexpected_top_level", posix))
        lowered_parts = {part.casefold() for part in relative.parts}
        if "__pycache__" in lowered_parts or path.suffix in {".pyc", ".pyo"}:
            findings.append(_finding("cache_file", posix))
        if FORBIDDEN_PARTS & lowered_parts:
            findings.append(_finding("forbidden_directory_content", posix))
        if ".github" in lowered_parts and "workflows" in lowered_parts:
            findings.append(_finding("github_actions", posix))
        if path.name.casefold() in INSTALLER_NAMES:
            findings.append(_finding("installer", posix))
        if path.is_symlink():
            findings.append(_finding("symlink", posix))
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                findings.append(_finding(name, posix))
    for path in directories:
        relative = path.relative_to(root)
        posix = relative.as_posix()
        if path.is_symlink():
            findings.append(_finding("symlink", posix))
            continue
        if relative.parts[-1].casefold() in FORBIDDEN_PARTS:
            findings.append(_finding("forbidden_directory", posix))
    return findings


def _safe_output_tail(output: str | None) -> str:
    text = output or ""
    if any(pattern.search(text) for pattern in SECRET_PATTERNS.values()):
        return "[suppressed: sensitive child output]"
    return text[-4000:]


def run_checks(root: Path, python_executable: str, runner=subprocess.run) -> list[dict]:
    root = Path(root).resolve()
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    commands = [
        ("public_pytest", [python_executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]),
        (
            "template_validator",
            [
                python_executable,
                str(root / "scripts" / "validate_package.py"),
                str(root / "instructions" / "templates" / "task-package"),
            ],
        ),
    ]
    checks = []
    for check_id, command in commands:
        completed = runner(
            command,
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        checks.append(
            {
                "id": check_id,
                "command": command,
                "cwd": str(root),
                "exit_code": completed.returncode,
                "stdout_tail": _safe_output_tail(completed.stdout),
                "stderr_tail": _safe_output_tail(completed.stderr),
            }
        )
    return checks


def _build_result(
    root: Path,
    status: str,
    exit_code: int,
    findings: list[dict],
    checks: list[dict],
    error: str | None = None,
) -> dict:
    result = {
        "schema_version": SCHEMA_VERSION,
        "root": str(root),
        "status": status,
        "exit_code": exit_code,
        "findings": findings,
        "checks": checks,
    }
    if error is not None:
        result["error"] = error
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pre_release.py",
        description="Local pre-release gate for the public repository.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repository root to scan (default: the repository containing this script).",
    )
    args = parser.parse_args(argv)
    root = (args.root if args.root is not None else REPO_ROOT).resolve()
    try:
        findings = scan_repository(root)
        checks = run_checks(root, sys.executable)
    except Exception as exc:
        print(f"pre_release: internal error: {type(exc).__name__}", file=sys.stderr)
        result = _build_result(root, "error", 2, [], [], error="internal_error")
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 2
    findings.extend(
        _finding("check_failed", check["id"])
        for check in checks
        if check["exit_code"] != 0
    )
    failed = bool(findings)
    exit_code = 1 if failed else 0
    result = _build_result(root, "failed" if failed else "passed", exit_code, findings, checks)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
