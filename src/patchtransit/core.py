"""Compare what patches *produce*, not only what their diff text says.

No operations in this module alter the inspected repository, its Git index,
HEAD, refs, or worktrees. Candidate changes live under TemporaryDirectory.
"""

from __future__ import annotations

import difflib
import hashlib
import os
import pathlib
import re
import subprocess
import tempfile
import time
from collections.abc import Iterator
from typing import IO, Any

MAX_ARCHIVE_BYTES = 2 * 1024**3
MAX_SYMLINK_BYTES = 4096
MAX_TREE_ENTRY_BYTES = 16384
MAX_FILE_BYTES = 512 * 1024**2
MAX_DIFF_TEXT_BYTES = 2 * 1024**2
MAX_DIFF_LINES = 16000
MAX_DIFF_OUTPUT_BYTES = 8 * 1024**2
MAX_COMMAND_OUTPUT_BYTES = 64 * 1024**2


class PatchTransitError(Exception):
    """A preflight, patch, or environment failure."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(
    args: list[str],
    *,
    cwd: pathlib.Path | None = None,
    timeout: int = 120,
    input_data: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            args,
            input=input_data,
            capture_output=True,
            cwd=cwd,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise PatchTransitError(f"Required executable not found: {args[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise PatchTransitError(f"Command timed out ({timeout}s): {args[0]}") from exc


def git(args: list[str], cwd: pathlib.Path, *, timeout: int = 120) -> bytes:
    completed = run(["git", *args], cwd=cwd, timeout=timeout)
    if completed.returncode:
        message = completed.stderr.decode("utf-8", "replace").strip()
        raise PatchTransitError(
            f"Git command failed: git {' '.join(args[:4])}: {message[:2000]}"
        )
    return completed.stdout


def repository(path: pathlib.Path, revision: str) -> tuple[pathlib.Path, str]:
    root_output = git(["rev-parse", "--show-toplevel"], path)
    if not root_output.endswith(b"\n"):
        raise PatchTransitError("Git returned an invalid repository root")
    root_bytes = root_output[:-1]
    if os.name == "nt" and root_bytes.endswith(b"\r"):
        root_bytes = root_bytes[:-1]
    root = pathlib.Path(os.fsdecode(root_bytes)).resolve()
    if not root.is_dir():
        raise PatchTransitError("Repository root is not a directory")
    # All candidates begin at the SAME immutable tree, even if the worktree is dirty.
    tree = (
        git(["rev-parse", "--verify", "--end-of-options", f"{revision}^{{tree}}"], root)
        .decode()
        .strip()
    )
    if not re.fullmatch(r"[a-fA-F0-9]{40,64}", tree):
        raise PatchTransitError("Could not resolve a Git tree for the base revision")
    return root, tree


_WINDOWS_DEVICE = re.compile(
    r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$", re.IGNORECASE
)


def _portable_name(name: str) -> bool:
    """Reject path spellings that can escape or alias paths on Windows."""
    if not name or "\\" in name or ":" in name or "\x00" in name:
        return False
    for component in pathlib.PurePosixPath(name).parts:
        if component in ("", ".", ".."):
            continue
        if (
            component.casefold() == ".git"
            or component.endswith((" ", "."))
            or _WINDOWS_DEVICE.fullmatch(component)
        ):
            return False
    return True


def _member_path(name: str) -> pathlib.PurePosixPath:
    item = pathlib.PurePosixPath(name)
    if (
        item.is_absolute()
        or not item.parts
        or ".." in item.parts
        or not _portable_name(name)
        or any(part.casefold() == ".git" for part in item.parts)
    ):
        raise PatchTransitError(f"Unsafe path in Git tree: {name!r}")
    return item


def _safe_target(parent: pathlib.PurePosixPath, linkname: str) -> None:
    if not _portable_name(linkname):
        raise PatchTransitError(f"Git symlink has unsafe target: {linkname!r}")
    if pathlib.PurePosixPath(linkname).is_absolute():
        raise PatchTransitError(f"Git symlink has absolute target: {linkname!r}")
    depth = 0
    for component in (*parent.parts, *pathlib.PurePosixPath(linkname).parts):
        if component == "..":
            depth -= 1
        elif component not in ("", "."):
            depth += 1
        if depth < 0:
            raise PatchTransitError(f"Git symlink escapes checkout: {linkname!r}")


def _nul_records(stream: IO[bytes]) -> Iterator[bytes]:
    pending = bytearray()
    while block := stream.read(8192):
        pending.extend(block)
        while (separator := pending.find(0)) >= 0:
            yield bytes(pending[:separator])
            del pending[: separator + 1]
        if len(pending) > MAX_TREE_ENTRY_BYTES:
            raise PatchTransitError("Git tree has an oversized path entry")
    if pending:
        raise PatchTransitError("Truncated Git tree listing")


def export_tree(repo: pathlib.Path, tree: str, target: pathlib.Path) -> None:
    """Copy exact tracked Git blobs into a bounded temporary candidate tree."""
    tree_proc = subprocess.Popen(
        ["git", "ls-tree", "-r", "-z", "--full-tree", tree],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    proc = subprocess.Popen(
        ["git", "cat-file", "--batch"],
        cwd=repo,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert tree_proc.stdout is not None
    assert proc.stdin is not None and proc.stdout is not None
    total = 0
    links: list[tuple[pathlib.Path, str]] = []
    try:
        for record in _nul_records(tree_proc.stdout):
            if not record:
                continue
            heading, separator, path = record.partition(b"\t")
            parts = heading.split(b" ")
            if not separator or len(parts) != 3:
                raise PatchTransitError("Invalid Git tree entry")
            mode_bytes, kind, oid = parts
            item = _member_path(os.fsdecode(path))
            if mode_bytes == b"160000" and kind == b"commit":
                raise PatchTransitError(f"Git submodules are unsupported: {item}")
            if mode_bytes not in (b"100644", b"100755", b"120000") or kind != b"blob":
                raise PatchTransitError(f"Unsupported Git tree entry: {item}")
            if not re.fullmatch(rb"[0-9a-fA-F]{40,64}", oid):
                raise PatchTransitError(f"Invalid Git blob ID: {item}")
            mode = mode_bytes.decode("ascii")
            proc.stdin.write(oid + b"\n")
            proc.stdin.flush()
            header = proc.stdout.readline().rstrip(b"\n")
            parts = header.split(b" ")
            if len(parts) != 3 or parts[0] != oid or parts[1] != b"blob":
                raise PatchTransitError(f"Cannot read Git blob: {item}")
            try:
                size = int(parts[2])
            except ValueError as exc:
                raise PatchTransitError(f"Invalid Git blob size: {item}") from exc
            total += size
            if size < 0 or size > MAX_FILE_BYTES or total > MAX_ARCHIVE_BYTES:
                raise PatchTransitError("Git tree exceeds default safety size limit")
            destination = target.joinpath(*item.parts)
            if mode == "120000":
                if size > MAX_SYMLINK_BYTES:
                    raise PatchTransitError(f"Git symlink target is too long: {item}")
                link_data = proc.stdout.read(size)
                if len(link_data) != size:
                    raise PatchTransitError(f"Truncated Git symlink blob: {item}")
                linkname = os.fsdecode(link_data)
                _safe_target(item.parent, linkname)
                links.append((destination, linkname))
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("xb") as output:
                    remaining = size
                    while remaining:
                        chunk = proc.stdout.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise PatchTransitError(f"Truncated Git blob: {item}")
                        output.write(chunk)
                        remaining -= len(chunk)
                destination.chmod(0o755 if mode == "100755" else 0o644)
            if proc.stdout.read(1) != b"\n":
                raise PatchTransitError(f"Invalid Git blob framing: {item}")
        if tree_proc.wait(timeout=10):
            message = (
                tree_proc.stderr.read(2000).decode("utf-8", "replace")
                if tree_proc.stderr
                else ""
            )
            raise PatchTransitError(f"git ls-tree failed: {message}")
        proc.stdin.close()
        error = proc.stderr.read(2000).decode("utf-8", "replace") if proc.stderr else ""
        if proc.wait(timeout=10):
            raise PatchTransitError(f"git cat-file failed: {error}")
        for destination, linkname in links:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() or destination.is_symlink():
                raise PatchTransitError(
                    f"Git tree has duplicate target: {destination.name}"
                )
            destination.symlink_to(linkname)
    finally:
        for process in (tree_proc, proc):
            if process.poll() is None:
                process.kill()
                process.wait()
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe and not pipe.closed:
                    pipe.close()


def _path_safe(filename: str) -> bool:
    if not _portable_name(filename):
        return False
    path = pathlib.PurePosixPath(filename)
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and not any(part.casefold() == ".git" for part in path.parts)
    )


def patch_metadata(filename: pathlib.Path | None) -> dict[str, Any]:
    if filename is None:
        return {
            "sha256": None,
            "bytes": 0,
            "files": [],
            "added_lines": 0,
            "removed_lines": 0,
            "hunks": 0,
        }
    try:
        data = filename.read_bytes()
    except OSError as exc:
        raise PatchTransitError(f"Cannot read patch {filename}: {exc}") from exc
    if len(data) > MAX_ARCHIVE_BYTES:
        raise PatchTransitError("Patch exceeds maximum accepted size")
    # Extract paths from git's -z output; no shell, no guesswork about quoting.
    stat = run(["git", "apply", "--numstat", "-z", str(filename)])
    if stat.returncode:
        raise PatchTransitError(
            "Invalid patch syntax: " + stat.stderr.decode("utf-8", "replace")[:600]
        )
    entries = stat.stdout.split(b"\x00")
    touched: list[str] = []
    added = removed = 0
    for entry in entries:
        if not entry:
            continue
        if b"\t" not in entry:
            # Some Git versions encode complex renames as a second NUL field.
            # Fail explicitly instead of guessing paths or trusting framing.
            raise PatchTransitError(
                "Unsupported patch rename format; use a normal git diff"
            )
        a, b, name = entry.split(b"\t", 2)
        decoded = os.fsdecode(name)
        if not _path_safe(decoded):
            raise PatchTransitError(f"Patch contains an unsafe path: {decoded!r}")
        touched.append(decoded)
        added += int(a) if a.isdigit() else 0
        removed += int(b) if b.isdigit() else 0
    return {
        "sha256": sha256_bytes(data),
        "bytes": len(data),
        "files": touched,
        "added_lines": added,
        "removed_lines": removed,
        "hunks": sum(1 for line in data.splitlines() if line.startswith(b"@@ ")),
    }


def apply_patch(path: pathlib.Path, patch: pathlib.Path | None) -> None:
    if patch is None:
        return
    for action in ("--check", None):
        cmd = ["git", "apply", "--whitespace=nowarn"]
        if action:
            cmd.append(action)
        cmd.append(str(patch))
        response = run(cmd, cwd=path)
        if response.returncode:
            raise PatchTransitError(
                "Patch did not apply to the selected base tree: "
                + response.stderr.decode("utf-8", "replace")[:1000]
            )


def inventory(root: pathlib.Path) -> dict[str, tuple[str, bytes | str]]:
    items: dict[str, tuple[str, bytes | str]] = {}
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        for name in list(dirs):
            path = pathlib.Path(current) / name
            if path.is_symlink():
                files.append(name)
                dirs.remove(name)
        for name in files:
            path = pathlib.Path(current) / name
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                items[rel] = ("link", os.readlink(path))
            elif path.is_file():
                # Store digests instead of loading huge binary assets into RAM.
                # Ordinary source remains in-memory for readable unified diffs.
                # Git tracks the executable bit. A mode-only patch is a real
                # change, even when the file's SHA-256 stays identical.
                suffix = "+x" if path.stat().st_mode & 0o111 else ""
                if path.stat().st_size > MAX_DIFF_TEXT_BYTES:
                    digest = hashlib.sha256()
                    with path.open("rb") as source:
                        for block in iter(lambda: source.read(1024 * 1024), b""):
                            digest.update(block)
                    items[rel] = ("filehash" + suffix, digest.hexdigest())
                else:
                    items[rel] = ("file" + suffix, path.read_bytes())
    return items


def _digest(value: tuple[str, bytes | str] | None) -> str | None:
    """Raw SHA-256 for regular files; namespaced SHA-256 for symlink targets."""
    if value is None:
        return None
    kind, data = value
    if kind.startswith("filehash"):
        # Already streamed and hashed from raw on-disk bytes.
        assert isinstance(data, str)
        return data
    if kind.startswith("file"):
        assert isinstance(data, bytes)
        return sha256_bytes(data)
    assert kind == "link" and isinstance(data, str)
    return sha256_bytes(b"symlink\x00" + data.encode("utf-8", "surrogateescape"))


def _lf_lines(text: str) -> list[str]:
    """Split on LF only; str.splitlines() also splits valid text at VT/FF/NEL."""
    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def _git_path(path: str) -> str:
    """Git's C-style pathname quoting for unified patch headers."""
    data = path.encode("utf-8", "surrogateescape")
    if all(32 <= byte <= 126 and byte not in (34, 92) for byte in data):
        return path
    escaped: list[str] = []
    controls = {9: r"\t", 10: r"\n", 13: r"\r"}
    for byte in data:
        if byte in (34, 92):
            escaped.append("\\" + chr(byte))
        elif byte in controls:
            escaped.append(controls[byte])
        elif 32 <= byte <= 126:
            escaped.append(chr(byte))
        else:
            escaped.append(f"\\{byte:03o}")
    return '"' + "".join(escaped) + '"'


def compare_inventories(
    left: dict[str, tuple[str, bytes | str]], right: dict[str, tuple[str, bytes | str]]
) -> tuple[list[dict[str, Any]], str]:
    changes: list[dict[str, Any]] = []
    diff_lines: list[str] = []
    rendered_bytes = 0
    truncated = False

    def append_diff(line: str) -> None:
        nonlocal rendered_bytes, truncated
        if truncated:
            return
        size = len(line.encode("utf-8", "surrogateescape"))
        if (
            len(diff_lines) >= MAX_DIFF_LINES
            or rendered_bytes + size > MAX_DIFF_OUTPUT_BYTES
        ):
            truncated = True
            return
        diff_lines.append(line)
        rendered_bytes += size

    for filename in sorted(left.keys() | right.keys()):
        a = left.get(filename)
        b = right.get(filename)
        if a == b:
            continue
        state = "added" if a is None else "deleted" if b is None else "modified"
        changes.append(
            {
                "path": filename,
                "change": state,
                "before_sha256": _digest(a),
                "after_sha256": _digest(b),
                "before_executable": a[0].endswith("+x")
                if a and a[0].startswith("file")
                else None,
                "after_executable": b[0].endswith("+x")
                if b and b[0].startswith("file")
                else None,
            }
        )
        # The text preview is bounded, but the JSON evidence must be exhaustive.
        if truncated:
            continue
        if (
            a
            and b
            and a[0].startswith("file")
            and b[0].startswith("file")
            and a[0].endswith("+x") != b[0].endswith("+x")
        ):
            old_mode = "100755" if a[0].endswith("+x") else "100644"
            new_mode = "100755" if b[0].endswith("+x") else "100644"
            for line in (
                f"diff --git {_git_path(f'a/{filename}')} {_git_path(f'b/{filename}')}\n",
                f"old mode {old_mode}\n",
                f"new mode {new_mode}\n",
            ):
                append_diff(line)
        if truncated:
            continue
        # A large file is represented by its hash. Never pretend a size or
        # kind transition is an addition/deletion from an *empty* text file.
        if (a and a[0] not in ("file", "file+x")) or (
            b and b[0] not in ("file", "file+x")
        ):
            append_diff(
                f"--- {filename}: binary/large file, symlink or metadata "
                "changed (hashes in JSON)\n"
            )
            continue
        aa = a[1] if a else b""
        bb = b[1] if b else b""
        assert isinstance(aa, bytes) and isinstance(bb, bytes)
        if (
            len(aa) > MAX_DIFF_TEXT_BYTES
            or len(bb) > MAX_DIFF_TEXT_BYTES
            or b"\x00" in aa
            or b"\x00" in bb
        ):
            append_diff(
                f"--- {filename}: binary/large contents differ (hashes in JSON)\n"
            )
            continue
        try:
            a_lines = _lf_lines(aa.decode("utf-8"))
            b_lines = _lf_lines(bb.decode("utf-8"))
        except UnicodeDecodeError:
            append_diff(f"--- {filename}: non-UTF-8 contents differ (hashes in JSON)\n")
            continue
        if a is None or b is None:
            append_diff(
                f"diff --git {_git_path(f'a/{filename}')} {_git_path(f'b/{filename}')}\n"
            )
            if a is None:
                append_diff(
                    f"new file mode {'100755' if b and b[0].endswith('+x') else '100644'}\n"
                )
            else:
                append_diff(
                    f"deleted file mode {'100755' if a[0].endswith('+x') else '100644'}\n"
                )
        if truncated:
            continue
        for line in difflib.unified_diff(
            a_lines,
            b_lines,
            fromfile="/dev/null" if a is None else _git_path(f"old/{filename}"),
            tofile="/dev/null" if b is None else _git_path(f"new/{filename}"),
            n=3,
        ):
            append_diff(line if line.endswith("\n") else line + "\n")
            # difflib omits the EOF marker; without it, the diff can falsely
            # add trailing newlines and even fail to apply to the old file.
            if not line.endswith("\n") and not truncated:
                append_diff("\\ No newline at end of file\n")
            if truncated:
                break
    if truncated:
        diff_lines.append("\n... diff truncated; JSON manifest remains complete ...\n")
    return changes, "".join(diff_lines)


def _hash_stream(stream: IO[bytes]) -> str:
    digest = hashlib.sha256()
    stream.seek(0)
    remaining = os.fstat(stream.fileno()).st_size
    while remaining:
        chunk = stream.read(min(64 * 1024, remaining))
        if not chunk:
            break
        digest.update(chunk)
        remaining -= len(chunk)
    return digest.hexdigest()


def execute(command: list[str], cwd: pathlib.Path, timeout: int) -> dict[str, Any]:
    started = time.monotonic()
    try:
        # Anonymous temporary files avoid waiting for pipes inherited by a
        # command's descendants. They are removed on close, not in evidence.
        with (
            tempfile.TemporaryFile(mode="w+b") as stdout,
            tempfile.TemporaryFile(mode="w+b") as stderr,
        ):
            with subprocess.Popen(
                command,
                cwd=cwd,
                stdout=stdout,
                stderr=stderr,
                stdin=subprocess.DEVNULL,
            ) as process:
                deadline = started + timeout
                while True:
                    if (
                        os.fstat(stdout.fileno()).st_size > MAX_COMMAND_OUTPUT_BYTES
                        or os.fstat(stderr.fileno()).st_size > MAX_COMMAND_OUTPUT_BYTES
                    ):
                        if process.poll() is None:
                            process.kill()
                            process.wait()
                        return {
                            "exit_code": None,
                            "error": "OutputLimitExceeded",
                            "duration_ms": round((time.monotonic() - started) * 1000),
                        }
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        if process.poll() is None:
                            process.kill()
                            process.wait()
                        return {
                            "exit_code": None,
                            "timeout": True,
                            "duration_ms": round((time.monotonic() - started) * 1000),
                        }
                    try:
                        code = process.wait(timeout=min(remaining, 0.1))
                        break
                    except subprocess.TimeoutExpired:
                        continue
                if (
                    os.fstat(stdout.fileno()).st_size > MAX_COMMAND_OUTPUT_BYTES
                    or os.fstat(stderr.fileno()).st_size > MAX_COMMAND_OUTPUT_BYTES
                ):
                    return {
                        "exit_code": None,
                        "error": "OutputLimitExceeded",
                        "duration_ms": round((time.monotonic() - started) * 1000),
                    }
            return {
                "exit_code": code,
                "duration_ms": round((time.monotonic() - started) * 1000),
                "stdout_sha256": _hash_stream(stdout),
                "stderr_sha256": _hash_stream(stderr),
            }
    except OSError as exc:
        return {
            "exit_code": None,
            "error": type(exc).__name__,
            "duration_ms": round((time.monotonic() - started) * 1000),
        }


def evaluate(
    repo_path: pathlib.Path,
    revision: str,
    old_patch: pathlib.Path | None,
    new_patch: pathlib.Path | None,
    *,
    command: list[str] | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    repo, tree = repository(repo_path, revision)
    old_patch = old_patch.resolve() if old_patch else None
    new_patch = new_patch.resolve() if new_patch else None
    if old_patch is not None and new_patch is not None and old_patch == new_patch:
        raise PatchTransitError(
            "Old and new patch are identical paths; pass different files"
        )
    old = patch_metadata(old_patch)
    new = patch_metadata(new_patch)
    with tempfile.TemporaryDirectory(prefix="patchtransit-") as sandbox:
        base = pathlib.Path(sandbox)
        left = base / "old"
        right = base / "new"
        left.mkdir()
        right.mkdir()
        export_tree(repo, tree, left)
        export_tree(repo, tree, right)
        apply_patch(left, old_patch)
        apply_patch(right, new_patch)
        first = inventory(left)
        second = inventory(right)
        changed, text_diff = compare_inventories(first, second)
        # Candidate state must be fingerprinted BEFORE user-defined tests run:
        # test suites frequently create caches, snapshots and output files.
        # The report describes the patch effect, not test side effects.

        # Digest entire effective state, not just patch hunks.
        def state_hash(items: dict[str, tuple[str, bytes | str]]) -> str:
            h = hashlib.sha256()
            for key, value in sorted(items.items()):
                h.update(key.encode("utf-8", "surrogateescape") + b"\x00")
                h.update(value[0].encode() + b"\x00")
                h.update((_digest(value) or "").encode() + b"\n")
            return h.hexdigest()

        old_hash = state_hash(first)
        new_hash = state_hash(second)
        checks: dict[str, Any] | None = None
        if command:
            checks = {
                "command": command,
                "old": execute(command, left, timeout),
                "new": execute(command, right, timeout),
            }
        report: dict[str, Any] = {
            "schema": 1,
            "base_tree": tree,
            "old_patch": old,
            "new_patch": new,
            "old_state_sha256": old_hash,
            "new_state_sha256": new_hash,
            "changes": changed,
            "changed_files": len(changed),
            "effective_diff": text_diff,
            "checks": checks,
        }
        report["verdict"] = "identical" if not changed else "changed"
        if checks is not None:
            before = checks["old"]["exit_code"]
            after = checks["new"]["exit_code"]
            if before == 0 and after != 0:
                report["verdict"] = "regression"
            elif after == 0 and before != 0:
                report["verdict"] = "improvement"
        return report
