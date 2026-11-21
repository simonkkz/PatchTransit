# Contributing to PatchTransit

Thanks for helping make patch comparison more reliable. PatchTransit is intentionally a **small, offline, standard-library-only** Python utility. Correctness, reproducibility and clear failure modes matter more than adding dependencies or clever shortcuts.

## Before you start

- Search existing issues and pull requests. Use the GitHub bug report or feature request form for new work.
- For security vulnerabilities, follow [SECURITY.md](SECURITY.md) and GitHub's private vulnerability reporting; **do not** open a public issue containing an exploit, credentials or proprietary patches.
- For a larger change, discuss the intended behavior and trade-offs in an issue before implementing it.

## Development setup

Requires Python 3.11+ and Git. From a fresh clone:

```sh
python -m venv .venv
# Activate the environment (Unix): . .venv/bin/activate
# Activate the environment (PowerShell): .venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]'
```

Run the same checks as CI:

```sh
python -m ruff check src tests
python -m ruff format --check src tests
python -m pyrefly check
python -m unittest discover -s tests -v
bash examples/demo.sh  # optional, on systems with Bash
```

GitHub Actions runs the lint/type checks and test suite on Linux, macOS and Windows, for Python 3.11–3.15. The `main` branch is protected; submit a pull request rather than pushing directly. Do not force-push to `main`.

## Design and testing principles

- A comparison must never mutate the inspected Git repository, index, refs, tracked or untracked working files. Work on disposable candidate trees.
- Apply both patches to the **same immutable base tree**. The effective result, not the textual patch hunks, defines the comparison.
- Keep runtime dependencies at zero and behavior deterministic/offline by default. Do not add telemetry, implicit network calls or shell execution.
- The optional `--execute` command is intentionally unsandboxed and requires explicit consent. Never silently execute patch contents.
- Guard filesystem traversal, symlinks, malformed patch paths, untrusted HTML content and potentially large inputs/outputs.
- Add a regression test for each bug. Cover text and binary files, mode-only changes, files without final LF, unusual path names and malformed input where relevant.
- Changes to the JSON schema, verdicts, exit codes or evidence hashing need explicit compatibility discussion and documentation.
- Avoid committing generated build artifacts, raw test logs, credentials, private patches or source from third-party repositories.

## Pull requests

Keep PRs focused. Describe the root cause, actual change, compatibility impact and tests performed in the [pull request template](.github/PULL_REQUEST_TEMPLATE.md). CI must pass; reviewers may request improvements or smaller PRs. A passing test is evidence, not a guarantee of correctness.
