# Contributing

PatchTransit runs entirely offline with Python's standard library and Git. Please keep changes focused, avoid new runtime dependencies and add a regression test when fixing a bug.

## Setup

Requires Python 3.11+ and Git:

```sh
python -m venv .venv
# Activate on Linux/macOS: . .venv/bin/activate
# Or on Windows (PowerShell): .venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]'
```

## Checks

```sh
python -m ruff check src tests
python -m ruff format --check src tests
python -m pyrefly check
python -m unittest discover -s tests -v
```

CI covers Linux, macOS and Windows on Python 3.11–3.15. Open a PR against `main` and check the full matrix before merging.

## Things to preserve

- Comparisons must not touch the original repository, working tree, index or refs.
- Both candidate patches must use the same immutable base tree.
- Do not run commands or make network requests unless the user explicitly opts in. `--execute` is **not** a sandbox.
- Treat paths, archives, patches and report contents as untrusted. Test unusual filenames, binary data and platform-specific behavior.
- Document any changes to the JSON evidence format, CLI exits or verdicts.

Please don't include build artifacts, credentials, raw test logs or proprietary patches. For security problems, use [private vulnerability reporting](https://github.com/simonkkz/PatchTransit/security/advisories/new) instead of a public issue. See [SECURITY.md](SECURITY.md).
