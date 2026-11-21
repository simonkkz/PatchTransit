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
- Reports include diff content and paths. They are not automatically sanitized and are not safe to post without review.
- Git is a required external executable. The repository's Git configuration can influence Git operations; use a trusted environment.
- A crafted Git repository may exceed configured resource limits; tree-entry, file and total-size limits prevent some but not all resource-exhaustion cases.
- Git tree paths, symlink targets and patch paths reject Windows drive/UNC spellings, reserved device names, alternate streams and trailing-space/dot aliases, even when run on a POSIX host. Symlinks created by patches are checked after application too; absolute and escaping targets are rejected before optional test execution.
- Only Git patches that `git apply` understands and that pass preflight are accepted. Unrecognized metadata encodings are rejected, not guessed.

## Reporting vulnerabilities

Please use GitHub's private vulnerability reporting for security issues rather than opening public issues with working exploits or secrets. Do not submit personal information or unredacted customer repositories.
