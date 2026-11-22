# PatchTransit

[![Tests](https://github.com/simonkkz/PatchTransit/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/simonkkz/PatchTransit/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-5B8CFF)](LICENSE)

**See what changed between two revisions of a patch — in the resulting code, not just in the patch text.**

![PatchTransit HTML report](docs/preview.png)

*Example of the standalone evidence report generated locally from a demo repository.*

A 40-file diff gets updated after review. Did it fix the race, change a test, or accidentally delete part of the API? Comparing the two `.patch` files as text is noisy: hunks shift, context moves, line numbers change. PatchTransit applies **both** revisions to separate copies of the **same Git base tree**, then compares the files that actually result.

```text
               Git tree at HEAD
                /            \
          old.patch        new.patch
              |                |
        candidate A      candidate B
              \                /
                effective diff
                       |
              JSON / HTML proof
```

- Works with Git patch files (`git diff > changes.patch`), including text and binary changes.
- Never checks out, stages, rebases, or modifies your working repository.
- Highlights newly added, removed, and changed effects between patch revisions, including executable-mode changes on POSIX systems.
- Optional test command runs separately on **both** candidate trees, with explicit opt-in.
- Generates standalone HTML and machine-readable JSON evidence plus a bounded effective diff preview.
- No LLM, API key, account, service, telemetry, or runtime Python dependencies.
- Includes PEP 561 `py.typed` metadata so type checkers can read the annotations on the installed Python API.

## 30-second quickstart

Requires **Python 3.11+** and **Git**.

```bash
git clone https://github.com/simonkkz/PatchTransit.git
cd PatchTransit
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .

# Generate a tiny, temporary example repository and report:
bash examples/demo.sh
```

For your own repository:

```bash
patchtransit compare previous.patch revised.patch \
  --repo /path/to/project \
  --base HEAD \
  --html report.html --json evidence.json --diff effective.patch
```

`report.html` opens offline in any browser. It contains no external scripts or tracking pixels.

### Typed Python API

Python integrations can call the comparison directly. The returned ordinary dictionary
has a typed evidence contract in `patchtransit.models` (also exposed to installed
type checkers through the PEP 561 marker):

```python
from pathlib import Path
from patchtransit.core import evaluate
from patchtransit.models import ComparisonEvidence

evidence: ComparisonEvidence = evaluate(Path("."), "HEAD", None, Path("changes.patch"))
print(evidence["verdict"], evidence["changed_files"])
```

### Verify a single patch against a base

```bash
patchtransit verify changes.patch --repo . --base HEAD --html change.html
```

### Run a test against both versions

```bash
patchtransit compare before.patch after.patch --repo . \
  --command 'python -m unittest discover -s tests' --execute \
  --timeout 120 --json proof.json
```

`--execute` is deliberately required. The command is parsed into an argument vector using POSIX quoting on Linux/macOS and native Windows C-runtime quoting on Windows (including preserving `C:\path\to\python.exe` backslashes). For example, on Windows use `--command '"C:\Program Files\Python\python.exe" -m unittest'` in PowerShell. The command is run without an intermediate shell. **It still executes arbitrary repository code under your user account.** Review the repository, its dependencies and the command; use an actual container/VM for untrusted inputs. PatchTransit is *not* a sandbox.

A `regression` verdict means the old command exited successfully and the new command did not. An `improvement` means the new command exited successfully and the old did not. The tool does **not** claim that one successful test is a formal proof of correctness. CLI and HTML summaries distinguish normal exit codes from timeouts and launch/output-limit errors; the HTML report also exposes SHA-256 hashes of captured stdout and stderr without embedding raw logs.

### Inspect patch metadata

```bash
patchtransit inspect before.patch
```

For rename and copy patches, inspection includes both referenced source and destination paths. The added/removed line totals still describe the forward patch, not the reverse inspection pass. Both paths undergo the same portability and safety checks (even though a copy leaves its source file unchanged).

## What is actually compared?

The output is determined by the full file state after applying each patch, not by subtraction of patch text. Executable permission changes are represented as mode metadata on platforms that preserve POSIX file modes; mode-only changes may not be observable on Windows filesystems. For every changed file, the JSON records the path, change type and SHA-256 digest of both versions. Plain UTF-8 changes, including file additions and deletions, appear as Git-applicable unified diffs. Binary/large-file changes are represented by their checksums rather than complete patches. The readable diff preview is capped at 16,000 output lines or 8 MiB. Text inputs with more than 10,000 lines on either side use hash-only evidence instead of constructing a potentially expensive line-by-line diff; the JSON `changes` manifest still includes **every** changed file. The JSON `diff_preview_complete` boolean indicates whether the preview represents all changes as an applicable text patch. If any binary, large, symlink, non-UTF-8 or truncated change is omitted, that flag is `false`; do not use an incomplete preview as a patch to replay the complete comparison. An executable-bit-only change remains a complete applicable patch even when a large or binary file is represented only by its content hash.

The **common base tree matters**. Patches based on different commits should be rebased onto a common base before comparing them. PatchTransit refuses to compare a revision that fails to apply cleanly. Patch inputs must be regular files (not FIFOs or devices). They are copied into temporary snapshots before inspection or comparison, so changing an original `.patch` file midway through an operation cannot change the evaluated revision or invalidate its recorded SHA-256.

`--base HEAD` inspects committed content only, even when your current working tree contains unrelated local changes. Your dirty files and index remain untouched. The tool creates disposable copies under your system temporary directory, so you need enough free disk space for two copies of that Git tree.

## CLI reference

| Command | Purpose |
|---|---|
| `patchtransit inspect PATCH` | Metadata: paths, hunks, additions/deletions, SHA-256 |
| `patchtransit compare OLD NEW` | Compare two patch revisions on the same base |
| `patchtransit verify PATCH` | Compare a patch with unchanged base |
| `--repo DIR` | Repository path (default `.`) |
| `--base REF` | Git revision (default `HEAD`) |
| `--json FILE` | Versioned machine-readable result |
| `--html FILE` | Self-contained dark-mode HTML report |
| `--diff FILE` | Bounded effective diff preview (may not be a complete applicable patch) |
| `--command CMD --execute` | Run the same test command on both candidate directories |
| `--timeout N` | Per-command timeout in seconds (default 120) |

Exit codes: `0` for successful comparison with no confirmed regression, `1` if the old test succeeded but the new test failed, `2` for invalid arguments, inapplicable patches or other errors. Without a test command, a `changed` verdict is informational and exits `0`. Output paths must be distinct and cannot overwrite input patch files or Git control directories, including repositories configured with `--separate-git-dir` or linked worktrees; conflicting destinations are rejected before writing. Ordinary report paths inside the working directory remain supported.

## Security and privacy

- The tool never executes the patch itself. The optional `--execute` runs a command in the patched tree and has **no OS sandbox**.
- Reports contain code paths and **diff contents**. Inspect before sharing for proprietary source, personal data, or secrets. The CLI escapes control characters, invalid pathname bytes and bidirectional formatting characters in terminal output; JSON evidence retains the original path values (encoded safely as needed).
- Whole-tree SHA-256 fingerprints are based on each path, file type/mode and content digest; changing the text-preview threshold does not change the fingerprint of an identical tree. At most 64 MiB of regular-file data is retained inline per candidate for readable diffs, and the sum of tracked path bytes is independently capped at 64 MiB per tree. Other files are represented by streamed digests, so the JSON change manifest remains complete even when the text preview is omitted.
- The JSON records test exit codes, elapsed time and hashes of stdout/stderr. It intentionally does **not** copy raw test logs or environment variables into evidence. Command output is captured in temporary files and hashed in chunks rather than accumulated in process memory. Temporary files are deleted after each check, and each output stream has a 64 MiB safety cap.
- Small Git subprocess outputs are captured through temporary files rather than unbounded pipes, with a 16 MiB per-stream cap. Committed Git blobs are copied directly from the immutable tree with path, symlink, file-size and total-size checks. Git archive `export-ignore` attributes cannot silently omit tracked files. Git submodule entries are currently rejected explicitly, and missing commits, trees or blobs in partial clones cause a local error rather than a network fetch (including during base revision resolution).
- Patch paths undergo safety checks; Git itself validates whether a patch applies. Simple renames work; unusual multi-path encodings that cannot be parsed safely are rejected.
- Every CLI test should be considered a normal execution of project code with your privileges.

See [SECURITY.md](SECURITY.md) for threat model and disclosure instructions.

## Why not `git range-diff`?

[`git range-diff`](https://git-scm.com/docs/git-range-diff) compares **commit series** and is the right tool for iterative commit review. PatchTransit focuses on two standalone `.patch` files applied to a common base, compares their **complete resulting file trees**, and optionally executes the same verification command against each result. It complements rather than replaces Git.

## Continuous integration and maintenance

GitHub Actions runs Ruff lint/format, strict Pyrefly type checks on `src/`, and integration tests on Linux, macOS and Windows across Python 3.11–3.15. The Linux/Python 3.15 matrix job also builds wheel and source distributions and smoke-tests the wheel in a fresh virtual environment. A separate workflow measures branch coverage on `main`, saves the XML report as a GitHub Actions artifact, and attempts an OIDC-authenticated upload to Codecov. Codecov outages do not block the test matrix. Renovate configuration in `renovate.json` tracks Python dev tool versions and GitHub Actions; automated update PRs require enabling the Renovate GitHub App for the repository.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
python -m pip install -e '.[dev]'
ruff check src tests
ruff format --check src tests
pyrefly check
python -m unittest discover -s tests -v
bash examples/demo.sh
```

Python standard library + Git only. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. See [LICENSE](LICENSE).
