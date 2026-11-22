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
- Git is a required external executable. Inherited `GIT_*` overrides are cleared for internal Git commands to prevent another repository's worktree, index or objects from being selected unintentionally. Repository/global Git configuration can still influence Git operations; use a trusted environment.
- A crafted Git repository or patch may exceed configured resource limits. Both extracted base trees and patched candidate inventories enforce per-file, symlink-target, aggregate byte and 100,000-entry limits. Post-application checks cannot prevent all temporary disk usage or resource-exhaustion cases.
- Git tree paths, symlink targets and patch paths reject Windows drive/UNC spellings, reserved device names (including COM/LPT superscript-digit aliases), alternate streams and trailing-space/dot aliases, even when run on a POSIX host. Symlinks created by patches are checked after application too. Symlink chains are resolved against their candidate root, so a sequence of individually valid relative links cannot escape the checkout; cycles are rejected.
- Only Git patches that `git apply` understands and that pass preflight are accepted. Unrecognized metadata encodings are rejected, not guessed.

## Reporting vulnerabilities

Please use GitHub's private vulnerability reporting for security issues rather than opening public issues with working exploits or secrets. Do not submit personal information or unredacted customer repositories.
