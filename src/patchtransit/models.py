"""Static contracts for the JSON-compatible evidence returned by PatchTransit.

These are ordinary dictionaries at runtime, not validation wrappers or new
serialization formats. Import these types when integrating with the Python API.
"""

from typing import Literal, NotRequired, TypedDict

ChangeKind = Literal["added", "deleted", "modified"]
Verdict = Literal["identical", "changed", "regression", "improvement"]


class PatchMetadata(TypedDict):
    sha256: str | None
    bytes: int
    files: list[str]
    added_lines: int
    removed_lines: int
    hunks: int


class ChangedFile(TypedDict):
    path: str
    change: ChangeKind
    before_sha256: str | None
    after_sha256: str | None
    before_executable: bool | None
    after_executable: bool | None


class CommandEvidence(TypedDict):
    exit_code: int | None
    duration_ms: int
    timeout: NotRequired[bool]
    error: NotRequired[str]
    stdout_sha256: NotRequired[str]
    stderr_sha256: NotRequired[str]


class VerificationChecks(TypedDict):
    command: list[str]
    old: CommandEvidence
    new: CommandEvidence


class ComparisonEvidence(TypedDict):
    schema: Literal[1]
    base_tree: str
    old_patch: PatchMetadata
    new_patch: PatchMetadata
    old_state_sha256: str
    new_state_sha256: str
    changes: list[ChangedFile]
    changed_files: int
    effective_diff: str
    diff_preview_complete: bool
    checks: VerificationChecks | None
    verdict: Verdict
