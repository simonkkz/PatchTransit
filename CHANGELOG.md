# Changelog

## Unreleased

- Stop descendant verification processes when a check times out or exceeds its output limit.

## 1.0.1

- Reap Git subprocess descendants that inherit export pipes when the export deadline expires.
- Inspect all patch paths regardless of the caller's working directory, including unsafe paths outside a nested Git prefix.

## 1.0.0

- Stabilize the documented CLI, Python evidence API and schema-1 compatibility contract under Semantic Versioning.
- Reject patches that touch more than the supported entry limit before applying them to candidate trees.
- Enforce a deadline while streaming Git tree entries and blobs so a stuck subprocess cannot hang candidate export.
- List each affected path once when inspecting an mbox with multiple commits that touch the same file.
- Report an ordinary CLI error for `~user` paths whose home directory cannot be resolved, including report destinations.

## 0.1.5 — verification isolation and safety limits

- Reap the Git tree reader and close its pipes if the blob reader fails to start.
- Preflight compressed Git binary patch sizes, including delta output sizes, before Git can inflate oversized candidate files.
- Set `PWD` to each temporary candidate for optional verification commands instead of inheriting the caller’s working directory.
- Clear inherited `GIT_*` overrides from optional verification commands, preventing accidental Git operations against the caller’s repository instead of a candidate.

## 0.1.4 — direct patch integrity and report safety

- Snapshot direct Python API patch inputs before validating and applying them so later source mutations cannot bypass preflight.
- Expand quoted home-directory (`~/`) paths consistently for CLI patch inputs and repository paths, as with report outputs.
- Reject parent/child report output paths before writing any artifact, including case aliases and directory symlinks.
- Ignore global Git `core.symlinks=false` when applying candidate patches, preserving symlink kind and state hashes across environments.
- Reject report destinations that alias input patches, other outputs or separate Git directories by case or Unicode normalization on portable filesystems.

## 0.1.3 — patch fidelity and cross-platform safety

- Reject Git submodule (gitlink mode `160000`) patches in both comparisons and direct patch application before Git can silently ignore their tracked entries.
- Distinguish missing repository/working-directory paths from missing executables in subprocess failures.
- Reject Windows-reserved punctuation in Git tree entries, patches and symlink targets on all hosts; reject C0 filename controls on Windows before filesystem access.
- Apply patches with LF-preserving Git settings so global `core.autocrlf=true` cannot change candidate files or their hashes.
- Display control and bidirectional formatting characters as explicit escape sequences in HTML evidence, preventing misleading file path rendering.
- Upload coverage for pull requests using OIDC for trusted branches and tokenless uploads for forks, with non-blocking patch-coverage results.
- Emit a separate Git diff header for every content-modified file, so an empty added/deleted file followed by a normal edit remains an applicable effective diff.
- Preserve LF line endings in exported evidence files on Windows, especially the replayable effective diff.
- Check portable Git path aliases with a bounded component trie instead of quadratic prefix-string normalization, including file/directory target collisions.
- Resolve caller-relative patch paths before running Git from a candidate working directory; support the literal filename `-` as an actual file instead of stdin.
- Reject case-insensitive or canonically equivalent file/directory aliases in committed and patched candidate trees, before cross-platform extraction can silently collapse distinct Git paths.
- Validate timeouts for internal Git subprocesses as well as optional test commands, avoiding uncaught integer conversion errors in the Python API.
- Reject empty executable argument vectors in the Python API instead of silently skipping verification or raising an uncaught IndexError.
- Treat hyphen-prefixed patch filenames as operands when invoking Git, not command-line flags.
- Report Codecov upload failures in the separate Coverage workflow instead of masking them.
- Provide a cross-platform Python example script (`examples/demo.py`) with a configurable report directory, retaining the Bash shortcut and documenting Windows PowerShell quickstart commands.
- Bundle the published schema-1 evidence JSON Schema as an offline Python package resource, keeping the wheel/sdist copy byte-for-byte identical to the GitHub Pages schema without adding runtime dependencies.

## 0.1.2 — evidence contracts, compatibility and safety

- Publish a versioned JSON Schema for comparison evidence on GitHub Pages, with automated validation against current and legacy schema-1 reports.
- Treat genuinely empty (zero-byte) Git patches as valid identity revisions in inspect/compare/verify, while rejecting malformed nonempty data and non-regular inputs.
- Ship the PEP 561 `py.typed` marker inside source and wheel distributions so downstream type checkers can inspect the existing Python API annotations.
- Define typed `PatchMetadata`, `ChangedFile`, `CommandEvidence`, `VerificationChecks` and `ComparisonEvidence` contracts for the existing JSON/Python API without changing the serialized evidence structure.
- Reject FIFOs, Unix sockets, device nodes and other unsupported entries during candidate inventories instead of silently omitting them from comparison evidence.
- Validate arbitrarily large `--timeout` values before launching optional verification commands, returning a normal CLI error rather than an uncaught Python integer-to-float `OverflowError`.
- Bound cumulative tracked pathname bytes to 64 MiB on both committed trees and patched candidates, complementing existing file-size and entry-count limits.
- Add project website, source, issue tracker, releases and changelog links to Python distribution metadata, with explicit Python 3.11–3.15 classifiers.
- Reject Windows `CONIN$` and `CONOUT$` console device paths (including case and extension variants) in Git entries, patches and symlink targets.
- Reject non-canonical empty and dot path components in raw Git tree and patch paths before path-library normalization can hide them.
- Escape terminal control sequences, bidirectional formatting characters and undecodable pathname bytes before printing Git paths, output destinations and errors in the CLI.
- Inspect both directions of a Git patch to include rename/copy source and destination paths and reject unsafe sources concealed by otherwise safe destinations.
- Render executable-mode-only changes in hash-only files as complete Git-applicable mode diffs rather than adding misleading content placeholders.
- Parse `--command` using Windows C-runtime quoting on Windows, preserving absolute executable paths, backslashes and quoted arguments without invoking a shell.
- Bound per-file text diff inputs to 10,000 lines, emitting hash-only evidence for pathological high-line-count files without invoking the expensive diff algorithm.

## 0.1.1 — maintenance and quality checks

- Protect actual Git metadata directories, including separate Git dirs and linked worktree common dirs, from report output overwrites.
- Reject CLI report paths inside `.git` control directories, protecting repository configuration, index and refs from accidental overwrite.
- Isolate internal Git processes from inherited `GIT_*` overrides, preventing foreign worktree/index/object paths from silently changing which repository is inspected.
- Use constant-length temporary filenames for atomic reports so long valid output names do not exceed filesystem `NAME_MAX`.
- Fail explicitly on candidate directory enumeration errors instead of silently omitting inaccessible files from evidence.
- Bound inline text candidate inventories to 64 MiB each and use streamed hashes beyond the preview budget without changing tree fingerprints or manifests.
- Bound Git subprocess stdout/stderr captures to 16 MiB per stream while running, preventing unbounded `git apply --numstat` output from exhausting memory.
- Canonicalize whole-tree fingerprints across inline/filehash representations and avoid false changes when those representations differ.
- Disable lazy Git object fetching during base ref resolution and reject missing trees locally in partial clones.
- Cap committed and patched candidate trees at 100,000 entries, including zero-byte files that do not consume the aggregate byte budget.
- Reject Windows COM/LPT device aliases containing superscript digits ¹, ² and ³ in Git paths and symlink targets.
- Require regular patch inputs, reject FIFOs/devices without blocking, precheck declared sizes, and snapshot inputs in standalone inspection.
- Enforce file, symlink and aggregate byte limits on resulting patched candidate trees, not only the original committed Git tree.
- Validate resolved symlink chains within base and patched candidate trees to catch indirect checkout escapes and cycles.
- Validate symlinks introduced by patch application, not only those present in the base Git tree, before running optional commands.
- Reject colliding report destinations and paths that would overwrite input patch files before producing outputs.
- Snapshot patch inputs before inspection and application to keep SHA-256 evidence consistent even if source patch files change during an evaluation. Stream patch metadata instead of buffering entire patch inputs.
- Distinguish check errors and timeouts from ordinary exit codes in human-readable CLI and HTML evidence; display output hashes in HTML.
- Export candidate trees directly from committed Git blobs rather than `git archive`, preserving tracked paths marked `export-ignore`. Reject unsupported Git submodule links explicitly.
- Detect executable permission changes in resulting patch states on POSIX filesystems, including mode-only patches.
- Add strict Pyrefly type checking and Renovate configuration for dev tools and Actions updates.
- Expand the CI matrix to Python 3.14 and 3.15, for 15 OS/interpreter combinations.
- Correctly include file kind and mode in whole-tree state fingerprints.
- Add end-to-end fixtures for binary patch revisions and Unicode filenames.
- Keep the complete changed-file manifest even when the readable diff preview reaches its line/size limits.
- Avoid misleading text diffs when a file transitions from a large/symlink state to ordinary text.
- Align the CLI version string with the package version.
- Preserve creation and deletion semantics for text and empty-file diffs, including unusual filenames.

## 0.1.0 — initial development snapshot

- Comparison of standalone patch revisions against the same immutable Git tree.
- Safe temporary copies, path checks and isolated patch application.
- Per-file checksums, text/binary change handling and effective unified diffs.
- Opt-in command execution against both candidate trees with timing and exit-code evidence.
- Standalone HTML and JSON reports, full offline operation and automated tests.
