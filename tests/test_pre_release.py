import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import pre_release


def write_minimal_tree(root: Path) -> None:
    for relative in pre_release.REQUIRED_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"minimal {relative}\n", encoding="utf-8")


def make_symlink_or_skip(target: Path, link: Path, *, target_is_directory: bool = False) -> None:
    try:
        os.symlink(target, link, target_is_directory=target_is_directory)
    except OSError:
        pytest.skip("symlink creation requires privileges on this host")


def test_clean_tree_has_no_findings(tmp_path):
    write_minimal_tree(tmp_path)
    assert pre_release.scan_repository(tmp_path) == []


def test_git_metadata_is_ignored(tmp_path):
    write_minimal_tree(tmp_path)
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git_dir / "config").write_text("[core]\nrepositoryformatversion = 0\n", encoding="utf-8")

    assert pre_release.scan_repository(tmp_path) == []


def test_missing_license_is_reported(tmp_path):
    write_minimal_tree(tmp_path)
    (tmp_path / "LICENSE").unlink()
    findings = pre_release.scan_repository(tmp_path)
    assert findings == [{"severity": "P1", "code": "missing_required_file", "path": "LICENSE"}]


def test_pytest_cache_content_is_forbidden(tmp_path):
    write_minimal_tree(tmp_path)
    cache = tmp_path / ".pytest_cache"
    cache.mkdir()
    (cache / "CACHEDIR.TAG").write_text("tag\n", encoding="utf-8")
    findings = pre_release.scan_repository(tmp_path)
    assert {"severity": "P1", "code": "forbidden_directory_content", "path": ".pytest_cache/CACHEDIR.TAG"} in findings


def test_pycache_file_is_reported(tmp_path):
    write_minimal_tree(tmp_path)
    cached = tmp_path / "tests" / "__pycache__" / "test_x.cpython-311.pyc"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"\x00\x01")
    findings = pre_release.scan_repository(tmp_path)
    assert findings == [{"severity": "P1", "code": "cache_file", "path": "tests/__pycache__/test_x.cpython-311.pyc"}]


def test_installer_script_is_reported(tmp_path):
    write_minimal_tree(tmp_path)
    (tmp_path / "scripts" / "install.py").write_text("# installer\n", encoding="utf-8")
    findings = pre_release.scan_repository(tmp_path)
    assert findings == [{"severity": "P1", "code": "installer", "path": "scripts/install.py"}]


def test_file_symlink_is_reported(tmp_path):
    write_minimal_tree(tmp_path)
    make_symlink_or_skip(tmp_path / "LICENSE", tmp_path / "tests" / "linked.md")
    findings = pre_release.scan_repository(tmp_path)
    assert findings == [{"severity": "P1", "code": "symlink", "path": "tests/linked.md"}]


def test_directory_symlink_is_reported(tmp_path):
    write_minimal_tree(tmp_path)
    make_symlink_or_skip(tmp_path / "instructions", tmp_path / "tests" / "linked_dir", target_is_directory=True)
    findings = pre_release.scan_repository(tmp_path)
    assert findings == [{"severity": "P1", "code": "symlink", "path": "tests/linked_dir"}]


def test_windows_user_path_is_reported(tmp_path):
    write_minimal_tree(tmp_path)
    drive, sep = "C:", "/"
    sample = "See " + drive + sep + "Users" + sep + "name/file for details.\n"
    (tmp_path / "README.md").write_text(sample, encoding="utf-8")
    findings = pre_release.scan_repository(tmp_path)
    assert findings == [{"severity": "P1", "code": "windows_user_path", "path": "README.md"}]


def test_github_token_finding_hides_token_value(tmp_path):
    write_minimal_tree(tmp_path)
    token = "ghp_" + "A1b2C3d4E5f6G7h8"
    (tmp_path / "README.md").write_text(f"token = {token}\n", encoding="utf-8")
    findings = pre_release.scan_repository(tmp_path)
    assert [finding["code"] for finding in findings] == ["github_token"]
    serialized = json.dumps(findings, ensure_ascii=False, sort_keys=True)
    assert token not in serialized


@pytest.mark.parametrize(
    ("code", "text"),
    [
        ("private_key", "-----BEGIN " + "PRIVATE KEY-----\n"),
        ("oauth_token", "oauth" + "_token: " + "abcdefghijklmnop\n"),
        ("api_key", "api" + "_key = '" + "abcdefghijklmnop'\n"),
        ("generic_secret", "pass" + "word: " + "abcdefghijklmnop\n"),
    ],
)
def test_secret_pattern_finding(tmp_path, code, text):
    write_minimal_tree(tmp_path)
    (tmp_path / "README.md").write_text(text, encoding="utf-8")
    findings = pre_release.scan_repository(tmp_path)
    assert [finding["code"] for finding in findings] == [code]


def test_unexpected_top_level_file_is_reported(tmp_path):
    write_minimal_tree(tmp_path)
    (tmp_path / "notes.md").write_text("notes\n", encoding="utf-8")
    findings = pre_release.scan_repository(tmp_path)
    assert findings == [{"severity": "P1", "code": "unexpected_top_level", "path": "notes.md"}]


def test_github_actions_workflow_is_reported(tmp_path):
    write_minimal_tree(tmp_path)
    workflow = tmp_path / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: ci\n", encoding="utf-8")
    findings = pre_release.scan_repository(tmp_path)
    assert {"severity": "P1", "code": "github_actions", "path": ".github/workflows/ci.yml"} in findings


def test_run_checks_runs_pytest_and_template_validator(tmp_path):
    import subprocess

    calls = []

    def fake_runner(command, **kwargs):
        calls.append((command, kwargs))
        if len(calls) == 1:
            return subprocess.CompletedProcess(command, 1, stdout="pytest stdout\n", stderr="pytest stderr\n")
        return subprocess.CompletedProcess(command, 0, stdout="validator stdout\n", stderr="")

    checks = pre_release.run_checks(tmp_path, "python", runner=fake_runner)
    root = tmp_path.resolve()

    assert [check["id"] for check in checks] == ["public_pytest", "template_validator"]
    assert [command for command, _ in calls] == [
        ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        [
            "python",
            str(root / "scripts" / "validate_package.py"),
            str(root / "instructions" / "templates" / "task-package"),
        ],
    ]
    assert all(command[0] not in {"git", "gh"} for command, _ in calls)
    for _, kwargs in calls:
        assert kwargs["cwd"] == str(root)
        assert kwargs["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["encoding"] == "utf-8"
        assert kwargs["check"] is False
    assert set(checks[0]) == {"id", "command", "cwd", "exit_code", "stdout_tail", "stderr_tail"}
    assert checks[0]["cwd"] == str(root)
    assert checks[0]["exit_code"] == 1
    assert checks[0]["stdout_tail"] == "pytest stdout\n"
    assert checks[0]["stderr_tail"] == "pytest stderr\n"
    assert checks[1]["exit_code"] == 0


def test_run_checks_limits_output_tails(tmp_path):
    import subprocess

    def fake_runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="x" * 5000, stderr="y" * 5000)

    checks = pre_release.run_checks(tmp_path, "python", runner=fake_runner)

    assert checks[0]["stdout_tail"] == "x" * 4000
    assert checks[0]["stderr_tail"] == "y" * 4000


def test_main_suppresses_secret_values_in_failed_child_output(tmp_path, capsys, monkeypatch):
    import subprocess

    github_token = "ghp_" + "A1b2C3d4E5f6G7h8"
    password_value = "abcdefghijklmnop"
    stdout = "x" * 5000 + github_token
    stderr_prefix = "y" * 3995 + "pass" + "word: " + password_value
    stderr = stderr_prefix + "z" * (8000 - len(stderr_prefix))

    def fake_runner(command, **kwargs):
        if "-m" in command:
            return subprocess.CompletedProcess(command, 1, stdout=stdout, stderr=stderr)
        return subprocess.CompletedProcess(command, 0, stdout="validator stdout\n", stderr="")

    real_run_checks = pre_release.run_checks
    monkeypatch.setattr(
        pre_release,
        "run_checks",
        lambda root, python_executable: real_run_checks(root, python_executable, runner=fake_runner),
    )
    write_minimal_tree(tmp_path)

    exit_code = pre_release.main(["--root", str(tmp_path)])
    serialized = capsys.readouterr().out
    result = json.loads(serialized)

    assert exit_code == 1
    assert github_token not in serialized
    assert password_value not in serialized
    assert result["checks"][0]["stdout_tail"] == "[suppressed: sensitive child output]"
    assert result["checks"][0]["stderr_tail"] == "[suppressed: sensitive child output]"
    assert result["checks"][1]["stdout_tail"] == "validator stdout\n"


def test_main_passes_clean_tree_with_empty_checks(tmp_path, capsys, monkeypatch):
    write_minimal_tree(tmp_path)
    monkeypatch.setattr(pre_release, "run_checks", lambda root, python_executable=None: [])
    exit_code = pre_release.main(["--root", str(tmp_path)])
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert exit_code == 0
    assert set(result) == {"schema_version", "root", "status", "exit_code", "findings", "checks"}
    assert result["schema_version"] == 1
    assert result["root"] == str(tmp_path.resolve())
    assert result["status"] == "passed"
    assert result["exit_code"] == 0
    assert result["findings"] == []
    assert result["checks"] == []


def test_main_fails_on_findings(tmp_path, capsys, monkeypatch):
    write_minimal_tree(tmp_path)
    (tmp_path / "LICENSE").unlink()
    monkeypatch.setattr(pre_release, "run_checks", lambda root, python_executable=None: [])
    exit_code = pre_release.main(["--root", str(tmp_path)])
    result = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert result["status"] == "failed"
    assert result["exit_code"] == 1
    assert result["findings"] == [{"severity": "P1", "code": "missing_required_file", "path": "LICENSE"}]
    assert result["checks"] == []


def test_main_aggregates_failed_child_check(tmp_path, capsys, monkeypatch):
    write_minimal_tree(tmp_path)
    checks = [
        {
            "id": "public_pytest",
            "command": ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"],
            "cwd": str(tmp_path.resolve()),
            "exit_code": 1,
            "stdout_tail": "one failed\n",
            "stderr_tail": "",
        }
    ]
    monkeypatch.setattr(pre_release, "run_checks", lambda root, python_executable: checks)

    exit_code = pre_release.main(["--root", str(tmp_path)])
    result = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert result["status"] == "failed"
    assert result["exit_code"] == 1
    assert result["findings"] == [{"severity": "P1", "code": "check_failed", "path": "public_pytest"}]
    assert result["checks"] == checks


def test_main_internal_error_returns_machine_json_without_traceback(tmp_path, capsys, monkeypatch):
    write_minimal_tree(tmp_path)

    def broken_scan(root):
        raise RuntimeError("boom")

    monkeypatch.setattr(pre_release, "scan_repository", broken_scan)
    monkeypatch.setattr(pre_release, "run_checks", lambda root: [])
    exit_code = pre_release.main(["--root", str(tmp_path)])
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert exit_code == 2
    assert result["status"] == "error"
    assert result["exit_code"] == 2
    assert result["error"] == "internal_error"
    assert "Traceback" not in captured.out


def test_release_documentation_covers_gate_manual_publication_and_accepted_limits():
    root = Path(__file__).resolve().parents[1]
    release_path = root / "RELEASE.md"
    assert release_path.is_file(), "RELEASE.md must document the local gate and manual publication"
    release = release_path.read_text(encoding="utf-8")

    assert "## Local pre-release check" in release
    assert "python scripts/pre_release.py" in release
    assert "## Manual publication with Git and GitHub CLI" in release
    assert "gh repo create" in release
    assert "## Manual publication through the GitHub web UI" in release
    assert "Code pilot status: PARTIAL" in release
    assert "effort: low was not passed or confirmed" in release
    assert "No human interactive launch was performed." in release
    assert "Real Work pilot: not performed in this revision." in release
    assert "accepted release risks" in release
    assert "The pre-release harness does not publish." in release
    assert "[RELEASE.md](RELEASE.md)" in (root / "README.md").read_text(encoding="utf-8")


def test_package_source_has_no_secret_pattern_findings():
    findings = pre_release.scan_repository(Path(__file__).resolve().parents[1])
    secret_codes = set(pre_release.SECRET_PATTERNS)
    secret_findings = [finding for finding in findings if finding["code"] in secret_codes]
    assert secret_findings == []
