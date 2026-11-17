# GitHub pre-release and manual publication

This repository includes a local pre-release gate. It checks the distributable tree and runs the existing tests and template validator. It does not create a Git repository or perform any publication step.

## Local pre-release check

From the repository root, with the development requirements already available, run:

```bash
PYTHONDONTWRITEBYTECODE=1 python scripts/pre_release.py
```

On PowerShell, set the environment flag for the process before running the same script:

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
python scripts/pre_release.py
```

The script writes one JSON object to standard output. A passing result has `status: "passed"`, `exit_code: 0`, no findings, and two successful entries in `checks`:

1. `python -m pytest -q -p no:cacheprovider`
2. `python scripts/validate_package.py instructions/templates/task-package`

Both commands receive `PYTHONDONTWRITEBYTECODE=1`. The inventory rejects missing required files, unexpected top-level content, caches, denied directories, symlinks, installers, GitHub Actions workflows, personal Windows paths, and configured secret patterns. Findings identify a pattern and path without copying a possible secret value. Child output is limited to short tails in the JSON result.

A nonzero exit code means that publication should remain stopped until the reported findings or failed checks are resolved. The pre-release harness does not publish. It does not run Git or GitHub CLI commands, create commits, tags, releases, remotes, or GitHub Actions.

## Accepted limitations and release risks

The following remain **accepted release risks**, not confirmed capabilities:

- Code pilot status: PARTIAL. The available Agent interface accepted `model` and `subagent_type` but had no `effort` argument. A real model call and runtime alias were observed, but effort: low was not passed or confirmed. No fallback or inferred effort is claimed.
- No human interactive launch was performed. Agent-started non-interactive CLI processes do not satisfy the manual-launch requirement, so that requirement remains unverified.
- Real Work pilot: not performed in this revision.
- Static tests and this local gate do not replace a complete Code pilot, actual effort assignment, a human interactive launch, a Work pilot, or independent verification.

The user accepted these limitations as noncritical for this release. The harness does not hide or resolve them.

## Manual publication with Git and GitHub CLI

The commands below are instructions for a user to run manually after reviewing the repository and obtaining permission to publish. They are not executed by the harness.

```bash
git init
git add .
git commit -m "Initial public release"
git branch -M main
gh repo create <owner>/<repository> --public --source=. --remote=origin --push
```

Review the created repository and its contents in GitHub. Create any later GitHub release manually and only as a separately authorized action.

## Manual publication through the GitHub web UI

As an alternative, create an empty public repository through the GitHub web UI without adding a README, license, or `.gitignore`. Then run the following commands manually, replacing the example repository URL:

```bash
git init
git add .
git commit -m "Initial public release"
git branch -M main
git remote add origin https://github.com/<owner>/<repository>.git
git push -u origin main
```

Confirm the uploaded files and repository settings in the web UI. No commit, remote creation, push, tag, release, or other publication action has been performed by this source package.
