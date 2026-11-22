# Security policy

PatchTransit is a local developer utility, not a containment boundary. Treat repository files and patch contents as potentially untrusted.

## Expected guarantees

- Comparisons do not alter the inspected repository's branch, index, tracked or untracked working files.
- No patch content or runtime data is uploaded; network access is not required by the application itself.
- JSON evidence omits raw command output and environment variables.
- The optional test command is never run without `--execute`.
- Temporary candidate copies are removed after comparison or error.

## Out of scope / cautions

- `--execute` runs code with the current user's privileges. A test can access the host, network, sensitive files, or other processes. Use a container or VM for untrusted repositories.
- A Git patch can still contain malicious source that a developer later chooses to execute.
- Reports include diff content and paths. They are not automatically sanitized and are not safe to post without review. The HTML report escapes control and bidirectional formatting characters in displayed evidence to prevent misleading visual path names; it does not remove sensitive data.
- Git is a required external executable. Inherited `GIT_*` overrides are cleared for internal Git commands to prevent another repository's worktree, index or objects from being selected unintentionally. Repository/global Git configuration can still influence Git operations; use a trusted environment.
- Candidate tree inventory rejects special filesystem entries (FIFOs, sockets, devices and missing listed files) instead of silently omitting them from evidence. The Git exporter itself materializes regular files and symlinks only.
- A crafted Git repository or patch may exceed configured resource limits. Both extracted base trees and patched candidate inventories enforce per-file, symlink-target, aggregate content byte, 64 MiB cumulative pathname byte and 100,000-entry limits. Compressed Git binary patch headers and delta output sizes are checked before Git inflates them. Post-application checks cannot prevent all temporary disk usage or resource-exhaustion cases.
- Git tree paths, symlink targets and patch paths reject Windows drive/UNC spellings, reserved device names (including COM/LPT superscript-digit aliases and CONIN$/CONOUT$ console handles), alternate streams, reserved punctuation (`<`, `>`, `"`, `|`, `?`, `*`) and trailing-space/dot aliases, even when run on a POSIX host. C0 control characters are rejected on Windows; POSIX hosts retain them for native Git filename compatibility. Symlinks created by patches are checked after application too. Symlink chains are resolved against their candidate root, so a sequence of individually valid relative links cannot escape the checkout; cycles are rejected.
- Raw Git tree and patch paths also reject empty, `.` and `..` slash components before path normalization, preventing ambiguous aliases such as `dir//file` and `dir/./file`. Distinct Git paths that differ only by case or Unicode canonical normalization, including their directory prefixes, are rejected across platforms. Relative symlink targets may still use `.` and `..` when they resolve within the candidate root.
- Portable pathname collision checks use a bounded tree of path components, avoiding quadratic normalization on deeply nested entries and limiting the number of distinct components retained in memory.
- Only Git patches that `git apply` understands and that pass preflight are accepted. Unrecognized metadata encodings are rejected, not guessed. Submodule/gitlink patches are not supported because working-tree Git application does not materialize their tracked commit entries.

## Reporting vulnerabilities

Please use GitHub's private vulnerability reporting for security issues rather than opening public issues with working exploits or secrets. Do not submit personal information or unredacted customer repositories.
