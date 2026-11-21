# Changelog

## 0.1.1 — maintenance and quality checks

- Detect executable permission changes in resulting patch states on POSIX filesystems, including mode-only patches.
- Add strict Pyrefly type checking and Renovate configuration for dev tools and Actions updates.
- Expand the CI matrix to Python 3.14 and 3.15, for 15 OS/interpreter combinations.
- Correctly include file kind and mode in whole-tree state fingerprints.

## 0.1.0 — initial development snapshot

- Comparison of standalone patch revisions against the same immutable Git tree.
- Safe temporary copies, path checks and isolated patch application.
- Per-file checksums, text/binary change handling and effective unified diffs.
- Opt-in command execution against both candidate trees with timing and exit-code evidence.
- Standalone HTML and JSON reports, full offline operation and automated tests.
