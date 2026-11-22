"""Compare what patches *produce*, not only what their diff text says.

No operations in this module alter the inspected repository, its Git index,
HEAD, refs, or worktrees. Candidate changes live under TemporaryDirectory.
"""

from __future__ import annotations

import difflib
import hashlib
import math
import os
import pathlib
import re
import stat
import subprocess
import tempfile
import time
import unicodedata
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from typing import IO

from .models import (
    ChangedFile,
    ChangeKind,
    CommandEvidence,
    ComparisonEvidence,
    PatchMetadata,
    Verdict,
    VerificationChecks,
)

MAX_ARCHIVE_BYTES = 2 * 1024**3
MAX_SYMLINK_BYTES = 4096
MAX_TREE_ENTRY_BYTES = 16384
MAX_TREE_ENTRIES = 100_000
MAX_TREE_PATH_BYTES = 64 * 1024**2
MAX_PORTABLE_PATH_COMPONENTS = 1_000_000
MAX_FILE_BYTES = 512 * 1024**2
MAX_DIFF_TEXT_BYTES = 2 * 1024**2
MAX_DIFF_TEXT_LINES = 10_000
MAX_INVENTORY_PREVIEW_BYTES = 64 * 1024**2
MAX_DIFF_LINES = 16000
MAX_DIFF_OUTPUT_BYTES = 8 * 1024**2
MAX_COMMAND_OUTPUT_BYTES = 64 * 1024**2
MAX_GIT_CAPTURE_BYTES = 16 * 1024**2


class PatchTransitError(Exception):
    """A preflight, patch, or environment failure."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_env() -> dict[str, str]:
    """Keep caller Git overrides from redirecting read-only repository operations."""
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment["GIT_NO_LAZY_FETCH"] = "1"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    return environment


def run(
    args: list[str],
    *,
    cwd: pathlib.Path | None = None,
    timeout: int = 120,
    input_data: bytes | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    if not args or not args[0]:
        raise PatchTransitError("Command must specify an executable")
    # Git output should not be held in unlimited subprocess.run buffers.
    # Anonymous temporary files also prevent pipe inheritance from stalling
    # the parent if a command launches a descendant with the same handles.
    timeout_seconds = _timeout_seconds(timeout)
    if cwd is not None and not os.path.isdir(cwd):
        raise PatchTransitError(f"Working directory is not a directory: {cwd}")
    if args and args[0] == "git" and env is None:
        env = _git_env()
    try:
        with (
            tempfile.TemporaryFile(mode="w+b") as stdout,
            tempfile.TemporaryFile(mode="w+b") as stderr,
            tempfile.TemporaryFile(mode="w+b") as stdin,
        ):
            if input_data is not None:
                stdin.write(input_data)
                stdin.seek(0)
            with subprocess.Popen(
                args,
                cwd=cwd,
                env=env,
                stdin=stdin if input_data is not None else subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
            ) as process:
                deadline = time.monotonic() + timeout_seconds
                while True:
                    if (
                        os.fstat(stdout.fileno()).st_size > MAX_GIT_CAPTURE_BYTES
                        or os.fstat(stderr.fileno()).st_size > MAX_GIT_CAPTURE_BYTES
                    ):
                        if process.poll() is None:
                            process.kill()
                            process.wait()
                        raise PatchTransitError(
                            f"Command output exceeds safety limit: {args[0]}"
                        )
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        if process.poll() is None:
                            process.kill()
                            process.wait()
                        raise PatchTransitError(
                            f"Command timed out ({timeout}s): {args[0]}"
                        )
                    try:
                        returncode = process.wait(timeout=min(remaining, 0.1))
                        break
                    except subprocess.TimeoutExpired:
                        continue
                if (
                    os.fstat(stdout.fileno()).st_size > MAX_GIT_CAPTURE_BYTES
                    or os.fstat(stderr.fileno()).st_size > MAX_GIT_CAPTURE_BYTES
                ):
                    raise PatchTransitError(
                        f"Command output exceeds safety limit: {args[0]}"
                    )
            stdout.seek(0)
            stderr.seek(0)
            return subprocess.CompletedProcess(
                args, returncode, stdout.read(), stderr.read()
            )
    except OSError as exc:
        if (
            cwd is not None
            and isinstance(exc, (FileNotFoundError, NotADirectoryError))
            and not os.path.isdir(cwd)
        ):
            raise PatchTransitError(
                f"Working directory is not a directory: {cwd}"
            ) from exc
        if isinstance(exc, FileNotFoundError):
            raise PatchTransitError(
                f"Required executable not found: {args[0]}"
            ) from exc
        raise PatchTransitError(f"Cannot run executable {args[0]}: {exc}") from exc


def git(args: list[str], cwd: pathlib.Path, *, timeout: int = 120) -> bytes:
    # Partial clones can fetch missing commits/trees implicitly during
    # rev-parse or cat-file. This tool must never cause a network fetch.
    completed = run(
        ["git", *args],
        cwd=cwd,
        timeout=timeout,
        env=_git_env(),
    )
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
    try:
        git(["cat-file", "-e", f"{tree}^{{tree}}"], root)
    except PatchTransitError as exc:
        raise PatchTransitError(
            "Base Git tree is not available locally (offline mode)"
        ) from exc
    return root, tree


_WINDOWS_DEVICE = re.compile(
    r"^(?:con|conin\$|conout\$|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])(?:\..*)?$",
    re.IGNORECASE,
)


def _portable_name(name: str) -> bool:
    """Reject path spellings that can escape or alias paths on Windows."""
    if not name or "\\" in name or ":" in name or "\x00" in name:
        return False
    for component in pathlib.PurePosixPath(name).parts:
        if any(char in '<>"|?*' for char in component):
            return False
        if os.name == "nt" and any(ord(char) < 32 for char in component):
            return False
        if component in ("", ".", ".."):
            continue
        if (
            component.casefold() == ".git"
            or component.endswith((" ", "."))
            or _WINDOWS_DEVICE.fullmatch(component)
        ):
            return False
    return True


def _canonical_git_path(name: str) -> bool:
    """Git object paths cannot contain empty, current or parent components."""
    return bool(name) and all(part not in ("", ".", "..") for part in name.split("/"))


class _PortablePathNode:
    def __init__(self) -> None:
        self.children: dict[str, tuple[str, _PortablePathNode]] = {}
        self.is_file = False


class _PortablePathRegistry:
    """Track distinct path components in linear time, including aliases."""

    def __init__(self) -> None:
        self.root = _PortablePathNode()
        self.node_count = 0

    def register(self, name: str) -> None:
        node = self.root
        parts = name.split("/")
        for index, component in enumerate(parts):
            key = unicodedata.normalize("NFC", component.casefold())
            child = node.children.get(key)
            if child is None:
                if self.node_count >= MAX_PORTABLE_PATH_COMPONENTS:
                    raise PatchTransitError(
                        "Candidate tree exceeds path component limit"
                    )
                next_node = _PortablePathNode()
                node.children[key] = (component, next_node)
                self.node_count += 1
            else:
                previous, next_node = child
                if previous != component:
                    left = "/".join([*parts[:index], previous])
                    right = "/".join(parts[: index + 1])
                    raise PatchTransitError(
                        f"Git paths collide on portable filesystems: {left!r} and {right!r}"
                    )
            terminal = index == len(parts) - 1
            if next_node.is_file or (terminal and next_node.children):
                raise PatchTransitError(f"Git file/directory targets collide: {name!r}")
            if terminal:
                next_node.is_file = True
            node = next_node


def _member_path(name: str) -> pathlib.PurePosixPath:
    item = pathlib.PurePosixPath(name)
    if (
        item.is_absolute()
        or not _canonical_git_path(name)
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


def _safe_resolved_symlink(root: pathlib.Path, link: pathlib.Path) -> None:
    """Reject indirect escapes through otherwise safe in-tree symlink chains."""
    try:
        resolved_root = root.resolve()
        resolved_target = link.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise PatchTransitError(
            f"Cannot resolve candidate symlink: {link.name!r}"
        ) from exc
    if not resolved_target.is_relative_to(resolved_root):
        raise PatchTransitError(f"Git symlink chain escapes checkout: {link.name!r}")
    # strict=False may leave a cyclic link unresolved on Python 3.13+.
    # A dangling target is fine, but an actual symlink loop is not.
    try:
        link.resolve(strict=True)
    except FileNotFoundError:
        pass
    except (OSError, RuntimeError) as exc:
        raise PatchTransitError(
            f"Cannot resolve candidate symlink: {link.name!r}"
        ) from exc


def _nul_records(stream: IO[bytes]) -> Iterator[bytes]:
    pending = bytearray()
    while block := stream.read(8192):
        pending.extend(block)
        while (separator := pending.find(0)) >= 0:
            if separator > MAX_TREE_ENTRY_BYTES:
                raise PatchTransitError("Git tree has an oversized path entry")
            yield bytes(pending[:separator])
            del pending[: separator + 1]
        if len(pending) > MAX_TREE_ENTRY_BYTES:
            raise PatchTransitError("Git tree has an oversized path entry")
    if pending:
        raise PatchTransitError("Truncated Git tree listing")


def export_tree(repo: pathlib.Path, tree: str, target: pathlib.Path) -> None:
    """Copy exact tracked Git blobs into a bounded temporary candidate tree."""
    # Partial clones may lazily fetch missing blobs. Treat them as unavailable
    # instead of allowing Git to make an implicit network request.
    git_env = _git_env()
    tree_proc = subprocess.Popen(
        ["git", "ls-tree", "-r", "-z", "--full-tree", tree],
        cwd=repo,
        env=git_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    proc = subprocess.Popen(
        ["git", "cat-file", "--batch"],
        cwd=repo,
        env=git_env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert tree_proc.stdout is not None
    assert proc.stdin is not None and proc.stdout is not None
    total = 0
    count = 0
    path_bytes = 0
    links: list[tuple[pathlib.Path, str]] = []
    portable_names = _PortablePathRegistry()
    try:
        for record in _nul_records(tree_proc.stdout):
            count += 1
            if count > MAX_TREE_ENTRIES:
                raise PatchTransitError("Git tree exceeds maximum entry count")
            heading, separator, path = record.partition(b"\t")
            path_bytes += len(path)
            if path_bytes > MAX_TREE_PATH_BYTES:
                raise PatchTransitError(
                    "Git tree exceeds cumulative pathname size limit"
                )
            parts = heading.split(b" ")
            if not separator or len(parts) != 3:
                raise PatchTransitError("Invalid Git tree entry")
            mode_bytes, kind, oid = parts
            item = _member_path(os.fsdecode(path))
            portable_names.register(item.as_posix())
            if mode_bytes == b"160000" and kind == b"commit":
                raise PatchTransitError(f"Git submodules are unsupported: {item}")
            if mode_bytes not in (b"100644", b"100755", b"120000") or kind != b"blob":
                raise PatchTransitError(f"Unsupported Git tree entry: {item}")
            if not re.fullmatch(rb"[0-9a-fA-F]{40,64}", oid):
                raise PatchTransitError(f"Invalid Git blob ID: {item}")
            mode = mode_bytes.decode("ascii")
            proc.stdin.write(oid + b"\n")
            proc.stdin.flush()
            header_line = proc.stdout.readline()
            if not header_line.endswith(b"\n"):
                raise PatchTransitError(f"Invalid Git blob header: {item}")
            parts = header_line[:-1].split(b" ")
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
        # Validate after creating *all* links; a link may traverse another
        # link that has not yet been materialized when the first one is added.
        for destination, _ in links:
            _safe_resolved_symlink(target, destination)
    finally:
        for process in (tree_proc, proc):
            if process.poll() is None:
                process.kill()
                process.wait()
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe and not pipe.closed:
                    pipe.close()


def _path_safe(filename: str) -> bool:
    if not _canonical_git_path(filename) or not _portable_name(filename):
        return False
    path = pathlib.PurePosixPath(filename)
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and not any(part.casefold() == ".git" for part in path.parts)
    )


@contextmanager
def _regular_patch_stream(filename: pathlib.Path) -> Generator[IO[bytes], None, None]:
    """Open patch inputs without blocking on FIFOs or reading device streams."""
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(filename, flags)
    except OSError as exc:
        raise PatchTransitError(f"Cannot open patch {filename}: {exc}") from exc
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode):
            raise PatchTransitError(f"Patch input must be a regular file: {filename}")
        if details.st_size > MAX_ARCHIVE_BYTES:
            raise PatchTransitError("Patch exceeds maximum accepted size")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            yield stream
    except OSError as exc:
        raise PatchTransitError(f"Cannot read patch {filename}: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _patch_numstat(
    filename: pathlib.Path, *, reverse: bool = False
) -> list[tuple[str, int, int]]:
    """Read and validate Git's NUL-delimited affected paths in one direction."""
    command = ["git", "apply"]
    if reverse:
        command.append("--reverse")
    command.extend(("--numstat", "-z", "--", str(filename.absolute())))
    result = run(command)
    if result.returncode:
        raise PatchTransitError(
            "Invalid patch syntax: " + result.stderr.decode("utf-8", "replace")[:600]
        )
    entries: list[tuple[str, int, int]] = []
    for entry in result.stdout.split(b"\x00"):
        if not entry:
            continue
        if b"\t" not in entry:
            # Fail explicitly on unsupported framing; never guess patch paths.
            raise PatchTransitError(
                "Unsupported patch rename format; use a normal git diff"
            )
        a, b, name = entry.split(b"\t", 2)
        decoded = os.fsdecode(name)
        if not _path_safe(decoded):
            raise PatchTransitError(f"Patch contains an unsafe path: {decoded!r}")
        entries.append(
            (decoded, int(a) if a.isdigit() else 0, int(b) if b.isdigit() else 0)
        )
    return entries


_GITLINK_MODE_LINE = re.compile(
    rb"(?:"
    rb"(?:old|new|new file|deleted file) mode 160000"
    rb"|index [0-9a-fA-F]{1,64}\.\.[0-9a-fA-F]{1,64} 160000"
    rb")\r?"
)


def patch_metadata(filename: pathlib.Path | None) -> PatchMetadata:
    if filename is None:
        return {
            "sha256": None,
            "bytes": 0,
            "files": [],
            "added_lines": 0,
            "removed_lines": 0,
            "hunks": 0,
        }
    digest = hashlib.sha256()
    size = hunks = 0
    prefix = b""
    in_header = False

    def inspect_line(line: bytes) -> None:
        nonlocal hunks, in_header
        if line.startswith(b"diff --git "):
            in_header = True
        elif line.startswith((b"@@ ", b"GIT binary patch", b"Binary files ")):
            in_header = False
        elif in_header and _GITLINK_MODE_LINE.fullmatch(line):
            raise PatchTransitError("Git submodules are unsupported in patches")
        if line.startswith(b"@@ "):
            hunks += 1

    try:
        with _regular_patch_stream(filename) as source:
            while block := source.read(64 * 1024):
                size += len(block)
                if size > MAX_ARCHIVE_BYTES:
                    raise PatchTransitError("Patch exceeds maximum accepted size")
                digest.update(block)
                # Retain only the header-length prefix of each LF-framed line.
                fragments = block.split(b"\n")
                for line in fragments[:-1]:
                    inspect_line(prefix + line[: 160 - len(prefix)])
                    prefix = b""
                prefix += fragments[-1][: 160 - len(prefix)]
            if prefix:
                inspect_line(prefix)
    except OSError as exc:
        raise PatchTransitError(f"Cannot read patch {filename}: {exc}") from exc
    if size == 0:
        # An empty Git diff is an identity patch. Git apply rejects a zero-byte
        # input by default, so do not invoke it for this exact case. Nonempty
        # garbage or whitespace-only data must still fail normal preflight.
        return {
            "sha256": digest.hexdigest(),
            "bytes": 0,
            "files": [],
            "added_lines": 0,
            "removed_lines": 0,
            "hunks": 0,
        }
    # Forward numstat names the target of a rename, hiding its source path.
    # Reverse numstat exposes the source, so inspect both directions. This
    # also prevents a safe-looking rename destination from hiding an unsafe
    # origin such as `.git/config` during standalone patch inspection.
    forward = _patch_numstat(filename)
    reverse = _patch_numstat(filename, reverse=True)
    touched = [name for name, _, _ in forward]
    seen = set(touched)
    for name, _, _ in reverse:
        if name not in seen:
            touched.append(name)
            seen.add(name)
    added = sum(count for _, count, _ in forward)
    removed = sum(count for _, _, count in forward)
    return {
        "sha256": digest.hexdigest(),
        "bytes": size,
        "files": touched,
        "added_lines": added,
        "removed_lines": removed,
        "hunks": hunks,
    }


def apply_patch(path: pathlib.Path, patch: pathlib.Path | None) -> None:
    if patch is None:
        return
    patch = patch.absolute()
    # Validate standalone use as well as evaluate()'s private snapshots.
    # A FIFO may have st_size==0 but is not an empty regular Git patch.
    with _regular_patch_stream(patch) as source:
        if os.fstat(source.fileno()).st_size == 0:
            return
    for action in ("--check", None):
        cmd = ["git", "-c", "core.autocrlf=false", "apply", "--whitespace=nowarn"]
        if action:
            cmd.append(action)
        cmd.extend(("--", str(patch)))
        response = run(cmd, cwd=path)
        if response.returncode:
            raise PatchTransitError(
                "Patch did not apply to the selected base tree: "
                + response.stderr.decode("utf-8", "replace")[:1000]
            )


def inventory(root: pathlib.Path) -> dict[str, tuple[str, bytes | str]]:
    items: dict[str, tuple[str, bytes | str]] = {}
    total_bytes = 0
    path_bytes = 0
    preview_bytes = 0
    portable_names = _PortablePathRegistry()

    def fail_on_walk_error(error: OSError) -> None:
        # os.walk silently skips unreadable directories unless onerror is set.
        # That could produce false "identical" evidence for an incomplete tree.
        raise PatchTransitError(
            f"Cannot inspect candidate directory: {error}"
        ) from error

    for current, dirs, files in os.walk(
        root, topdown=True, onerror=fail_on_walk_error, followlinks=False
    ):
        for name in list(dirs):
            path = pathlib.Path(current) / name
            if path.is_symlink():
                files.append(name)
                dirs.remove(name)
        # Give both candidates a deterministic order when deciding which
        # readable files get included in the in-memory diff preview budget.
        dirs.sort()
        for name in sorted(files):
            if len(items) >= MAX_TREE_ENTRIES:
                raise PatchTransitError("Candidate tree exceeds maximum entry count")
            path = pathlib.Path(current) / name
            rel = path.relative_to(root).as_posix()
            path_bytes += len(rel.encode("utf-8", "surrogateescape"))
            if path_bytes > MAX_TREE_PATH_BYTES:
                raise PatchTransitError(
                    "Candidate tree exceeds cumulative pathname size limit"
                )
            _member_path(rel)
            portable_names.register(rel)
            if path.is_symlink():
                target = os.readlink(path)
                link_bytes = len(os.fsencode(target))
                if link_bytes > MAX_SYMLINK_BYTES:
                    raise PatchTransitError(
                        f"Candidate symlink target is too long: {rel!r}"
                    )
                total_bytes += link_bytes
                _safe_target(pathlib.PurePosixPath(rel).parent, target)
                _safe_resolved_symlink(root, path)
                items[rel] = ("link", target)
            elif path.is_file():
                size = path.stat().st_size
                if size > MAX_FILE_BYTES:
                    raise PatchTransitError(
                        f"Candidate file exceeds size limit: {rel!r}"
                    )
                total_bytes += size
                # Store digests instead of loading huge binary assets into RAM.
                # Ordinary source remains in-memory for readable unified diffs.
                # Git tracks the executable bit. A mode-only patch is a real
                # change, even when the file's SHA-256 stays identical.
                suffix = "+x" if path.stat().st_mode & 0o111 else ""
                if (
                    size > MAX_DIFF_TEXT_BYTES
                    or preview_bytes + size > MAX_INVENTORY_PREVIEW_BYTES
                ):
                    digest = hashlib.sha256()
                    with path.open("rb") as source:
                        for block in iter(lambda: source.read(1024 * 1024), b""):
                            digest.update(block)
                    items[rel] = ("filehash" + suffix, digest.hexdigest())
                else:
                    items[rel] = ("file" + suffix, path.read_bytes())
                    preview_bytes += size
            else:
                # Candidate trees only contain regular Git blobs and links.
                # Do not silently omit a FIFO, socket, device, or vanished file
                # and then claim the inventory is complete or identical.
                raise PatchTransitError(f"Unsupported candidate entry: {rel!r}")
            if total_bytes > MAX_ARCHIVE_BYTES:
                raise PatchTransitError(
                    "Candidate tree exceeds total safety size limit"
                )
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


def _line_count(content: bytes) -> int:
    """Count LF-framed text lines without allocating individual line objects."""
    return content.count(b"\n") + int(bool(content) and not content.endswith(b"\n"))


def _mode_only_change(
    before: tuple[str, bytes | str] | None,
    after: tuple[str, bytes | str] | None,
) -> bool:
    """An executable-bit change alone is applicable without file bytes."""
    return bool(
        before
        and after
        and before[0].startswith("file")
        and after[0].startswith("file")
        and before[0].endswith("+x") != after[0].endswith("+x")
        and _digest(before) == _digest(after)
    )


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
) -> tuple[list[ChangedFile], str]:
    changes: list[ChangedFile] = []
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
        # The inventory may represent a file with inline bytes or a streamed
        # digest. Those are storage choices, not effective file changes.
        if (
            a
            and b
            and a[0].startswith("file")
            and b[0].startswith("file")
            and a[0].endswith("+x") == b[0].endswith("+x")
            and _digest(a) == _digest(b)
        ):
            continue
        state: ChangeKind = (
            "added" if a is None else "deleted" if b is None else "modified"
        )
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
        # Mode changes do not require a readable content diff when the
        # content digests agree. This also works for hash-only large files.
        if _mode_only_change(a, b):
            continue
        # A large file is represented by its hash. Never pretend a size or
        # kind transition is an addition/deletion from an *empty* text file.
        if (a and a[0] not in ("file", "file+x")) or (
            b and b[0] not in ("file", "file+x")
        ):
            append_diff(
                f"--- {_git_path(filename)}: binary/large file, symlink or metadata "
                "changed (hashes in JSON)\n"
            )
            continue
        aa = a[1] if a else b""
        bb = b[1] if b else b""
        assert isinstance(aa, bytes) and isinstance(bb, bytes)
        unsupported_bytes = (
            len(aa) > MAX_DIFF_TEXT_BYTES
            or len(bb) > MAX_DIFF_TEXT_BYTES
            or b"\x00" in aa
            or b"\x00" in bb
        )
        excessive_lines = (
            _line_count(aa) > MAX_DIFF_TEXT_LINES
            or _line_count(bb) > MAX_DIFF_TEXT_LINES
        )
        if unsupported_bytes or excessive_lines:
            reason = "binary/large" if unsupported_bytes else "high-line-count"
            append_diff(
                f"--- {_git_path(filename)}: {reason} contents differ (hashes in JSON)\n"
            )
            continue
        try:
            a_lines = _lf_lines(aa.decode("utf-8"))
            b_lines = _lf_lines(bb.decode("utf-8"))
        except UnicodeDecodeError:
            append_diff(
                f"--- {_git_path(filename)}: non-UTF-8 contents differ (hashes in JSON)\n"
            )
            continue
        # A unified-only hunk after a Git new/deleted-file mode header can
        # be parsed as part of the *previous* file. Start every content
        # change with its own Git diff header, not only additions/deletions.
        if (
            a is None
            or b is None
            or not (a and b and a[0].endswith("+x") != b[0].endswith("+x"))
        ):
            append_diff(
                f"diff --git {_git_path(f'a/{filename}')} {_git_path(f'b/{filename}')}\n"
            )
        if a is None or b is None:
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


def _preview_complete(
    changes: list[ChangedFile],
    left: dict[str, tuple[str, bytes | str]],
    right: dict[str, tuple[str, bytes | str]],
    rendered: str,
) -> bool:
    """Whether an effective diff represents every change as applicable text."""
    if rendered.endswith("\n... diff truncated; JSON manifest remains complete ...\n"):
        return False
    for item in changes:
        before = left.get(item["path"])
        after = right.get(item["path"])
        if _mode_only_change(before, after):
            continue
        for state in (before, after):
            if state is None:
                continue
            if state[0] not in ("file", "file+x"):
                return False
            contents = state[1]
            assert isinstance(contents, bytes)
            if (
                len(contents) > MAX_DIFF_TEXT_BYTES
                or b"\x00" in contents
                or _line_count(contents) > MAX_DIFF_TEXT_LINES
            ):
                return False
            try:
                contents.decode("utf-8")
            except UnicodeDecodeError:
                return False
    return True


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


def _timeout_seconds(timeout: int) -> float:
    """Validate a timeout before converting its arbitrary-size Python int."""
    if timeout <= 0:
        raise PatchTransitError("--timeout must be positive")
    try:
        seconds = float(timeout)
    except OverflowError as exc:
        raise PatchTransitError("--timeout exceeds supported numeric range") from exc
    if not math.isfinite(seconds):
        raise PatchTransitError("--timeout exceeds supported numeric range")
    return seconds


def execute(command: list[str], cwd: pathlib.Path, timeout: int) -> CommandEvidence:
    if not command or not command[0]:
        raise PatchTransitError("Verification command must specify an executable")
    timeout_seconds = _timeout_seconds(timeout)
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
                deadline = started + timeout_seconds
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


def _snapshot_patch(source: pathlib.Path, destination: pathlib.Path) -> pathlib.Path:
    """Freeze patch bytes before parsing or applying them to either candidate."""
    try:
        size = 0
        with (
            _regular_patch_stream(source) as original,
            destination.open("xb") as snapshot,
        ):
            while block := original.read(1024 * 1024):
                size += len(block)
                if size > MAX_ARCHIVE_BYTES:
                    raise PatchTransitError("Patch exceeds maximum accepted size")
                snapshot.write(block)
    except OSError as exc:
        raise PatchTransitError(f"Cannot copy patch {source}: {exc}") from exc
    return destination


def inspect_patch(source: pathlib.Path) -> PatchMetadata:
    """Inspect a single consistent snapshot rather than a mutable path."""
    with tempfile.TemporaryDirectory(prefix="patchtransit-inspect-") as sandbox:
        copy = _snapshot_patch(source, pathlib.Path(sandbox) / "input.patch")
        return patch_metadata(copy)


def evaluate(
    repo_path: pathlib.Path,
    revision: str,
    old_patch: pathlib.Path | None,
    new_patch: pathlib.Path | None,
    *,
    command: list[str] | None = None,
    timeout: int = 120,
) -> ComparisonEvidence:
    if command is not None and (not command or not command[0]):
        raise PatchTransitError("Verification command must specify an executable")
    repo, tree = repository(repo_path, revision)
    old_patch = old_patch.resolve() if old_patch else None
    new_patch = new_patch.resolve() if new_patch else None
    if old_patch is not None and new_patch is not None and old_patch == new_patch:
        raise PatchTransitError(
            "Old and new patch are identical paths; pass different files"
        )
    with tempfile.TemporaryDirectory(prefix="patchtransit-") as sandbox:
        base = pathlib.Path(sandbox)
        old_snapshot = (
            _snapshot_patch(old_patch, base / "old.patch") if old_patch else None
        )
        new_snapshot = (
            _snapshot_patch(new_patch, base / "new.patch") if new_patch else None
        )
        old = patch_metadata(old_snapshot)
        new = patch_metadata(new_snapshot)
        left = base / "old"
        right = base / "new"
        left.mkdir()
        right.mkdir()
        export_tree(repo, tree, left)
        export_tree(repo, tree, right)
        apply_patch(left, old_snapshot)
        apply_patch(right, new_snapshot)
        first = inventory(left)
        second = inventory(right)
        changed, text_diff = compare_inventories(first, second)
        preview_complete = _preview_complete(changed, first, second, text_diff)
        # Candidate state must be fingerprinted BEFORE user-defined tests run:
        # test suites frequently create caches, snapshots and output files.
        # The report describes the patch effect, not test side effects.

        # Digest entire effective state, not just patch hunks.
        def state_hash(items: dict[str, tuple[str, bytes | str]]) -> str:
            h = hashlib.sha256()
            for key, value in sorted(items.items()):
                h.update(key.encode("utf-8", "surrogateescape") + b"\x00")
                # Filehash versus inline file bytes is an implementation
                # choice controlled by the preview size limit, not a change
                # in the underlying Git tree.
                kind = value[0].replace("filehash", "file", 1)
                h.update(kind.encode() + b"\x00")
                h.update((_digest(value) or "").encode() + b"\n")
            return h.hexdigest()

        old_hash = state_hash(first)
        new_hash = state_hash(second)
        checks: VerificationChecks | None = None
        if command:
            checks = {
                "command": command,
                "old": execute(command, left, timeout),
                "new": execute(command, right, timeout),
            }
        verdict: Verdict = "identical" if not changed else "changed"
        if checks is not None:
            before = checks["old"]["exit_code"]
            after = checks["new"]["exit_code"]
            if before == 0 and after != 0:
                verdict = "regression"
            elif after == 0 and before != 0:
                verdict = "improvement"
        report: ComparisonEvidence = {
            "schema": 1,
            "base_tree": tree,
            "old_patch": old,
            "new_patch": new,
            "old_state_sha256": old_hash,
            "new_state_sha256": new_hash,
            "changes": changed,
            "changed_files": len(changed),
            "effective_diff": text_diff,
            "diff_preview_complete": preview_complete,
            "checks": checks,
            "verdict": verdict,
        }
        return report
