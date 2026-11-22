# Changelog

## 0.1.1 — maintenance and quality checks

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
