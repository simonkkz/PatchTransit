# Changelog

## 0.1.1 — maintenance and quality checks

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
