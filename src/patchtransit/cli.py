"""Command-line interface with explicit execution consent."""

from __future__ import annotations

import argparse
import os
import pathlib
import shlex
import sys
import unicodedata
from collections.abc import Mapping
from typing import Any

from . import __version__
from .core import PatchTransitError, _timeout_seconds, evaluate, git, inspect_patch
from .report import (
    _expand_user_path,
    atomic_write,
    html_report,
    json_report,
    resolve_output_path,
)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="patchtransit",
        description="Compare the actual effects of two patch revisions.",
    )
    p.add_argument("--version", action="version", version=f"PatchTransit {__version__}")
    sub = p.add_subparsers(dest="action", required=True)
    for name in ("inspect", "compare", "verify"):
        c = sub.add_parser(
            name,
            help={
                "inspect": "Statically inspect one patch",
                "compare": "Compare two patches on the same Git tree",
                "verify": "Compare one patch with the unpatched base",
            }[name],
        )
        if name == "compare":
            c.add_argument("old", type=pathlib.Path)
            c.add_argument("new", type=pathlib.Path)
        else:
            c.add_argument("patch", type=pathlib.Path)
        c.add_argument(
            "--repo",
            type=pathlib.Path,
            default=pathlib.Path("."),
            help="Git repository (default: .)",
        )
        c.add_argument(
            "--base", default="HEAD", help="Git base revision (default: HEAD)"
        )
        c.add_argument(
            "--json",
            type=pathlib.Path,
            metavar="FILE",
            help="Write machine-readable evidence JSON",
        )
        if name != "inspect":
            c.add_argument(
                "--html",
                type=pathlib.Path,
                metavar="FILE",
                help="Write standalone HTML report",
            )
            c.add_argument(
                "--diff",
                type=pathlib.Path,
                metavar="FILE",
                help="Write effective unified diff",
            )
            c.add_argument(
                "--command",
                metavar="CMD",
                help="Optional test command as argv (no shell)",
            )
            c.add_argument(
                "--execute",
                action="store_true",
                help="Explicitly allow running command against both copies",
            )
            c.add_argument("--timeout", type=int, default=120, metavar="SECONDS")
    return p


def _split_windows_command(command: str) -> list[str]:
    """Parse argv according to the Windows C runtime's backslash/quote rules.

    `shlex.split` applies POSIX escaping, so `C:\\Python\\python.exe` loses
    its path separators on Windows. Do not invoke a command shell here.
    """
    arguments: list[str] = []
    index = 0
    length = len(command)
    while index < length:
        while index < length and command[index] in " \t":
            index += 1
        if index == length:
            break
        current: list[str] = []
        quoted = False
        while index < length:
            if command[index] in " \t" and not quoted:
                break
            backslashes = 0
            while index < length and command[index] == "\\":
                backslashes += 1
                index += 1
            if index < length and command[index] == '"':
                current.extend("\\" * (backslashes // 2))
                if backslashes % 2:
                    current.append('"')
                elif quoted and index + 1 < length and command[index + 1] == '"':
                    current.append('"')
                    index += 1
                else:
                    quoted = not quoted
                index += 1
            else:
                current.extend("\\" * backslashes)
                if index < length and (command[index] not in " \t" or quoted):
                    current.append(command[index])
                    index += 1
        arguments.append("".join(current))
    return arguments


def _split_command(command: str) -> list[str]:
    return _split_windows_command(command) if os.name == "nt" else shlex.split(command)


def _terminal_safe(value: object) -> str:
    """Escape control, bidi-format and surrogate codepoints before printing."""
    escaped: list[str] = []
    for char in str(value):
        point = ord(char)
        if 0xDC80 <= point <= 0xDCFF:
            escaped.append(f"\\x{point - 0xDC00:02x}")
        elif unicodedata.category(char) in ("Cc", "Cf", "Cs", "Zl", "Zp"):
            if point <= 0xFF:
                escaped.append(f"\\x{point:02x}")
            elif point <= 0xFFFF:
                escaped.append(f"\\u{point:04x}")
            else:
                escaped.append(f"\\U{point:08x}")
        else:
            escaped.append(char)
    return "".join(escaped)


def _check_status(check: Mapping[str, Any]) -> str:
    if check.get("timeout"):
        return "timeout"
    if error := check.get("error"):
        return f"error:{error}"
    code = check.get("exit_code")
    return str(code) if code is not None else "unknown"


def _git_control_roots(repository: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """Find both worktree-private and shared Git metadata directories."""
    working = repository.expanduser().resolve()

    def read_path(option: str) -> pathlib.Path:
        raw = git(["rev-parse", option], working)
        if not raw.endswith(b"\n"):
            raise PatchTransitError("Git returned an invalid control directory")
        name = raw[:-1]
        if os.name == "nt" and name.endswith(b"\r"):
            name = name[:-1]
        return pathlib.Path(os.fsdecode(name))

    local = read_path("--absolute-git-dir").resolve()
    shared = read_path("--git-common-dir")
    if not shared.is_absolute():
        shared = working / shared
    return local, shared.resolve()


def _portable_output_key(path: pathlib.Path) -> tuple[str, ...]:
    return tuple(unicodedata.normalize("NFC", part.casefold()) for part in path.parts)


def _validate_outputs(args: argparse.Namespace) -> None:
    sources = (args.old, args.new) if args.action == "compare" else (args.patch,)
    outputs = tuple(
        (flag, getattr(args, flag, None)) for flag in ("json", "html", "diff")
    )
    if not any(destination is not None for _, destination in outputs):
        return
    source_paths = {
        _portable_output_key(target)
        for source in sources
        for target in (source.expanduser().resolve(), resolve_output_path(source))
    }
    try:
        protected_roots = _git_control_roots(args.repo)
    except PatchTransitError:
        # Inspecting a standalone patch need not happen inside a Git checkout.
        if args.action != "inspect":
            raise
        protected_roots = ()
    protected_keys = tuple(_portable_output_key(root) for root in protected_roots)
    seen: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
    for flag, output in outputs:
        output = getattr(args, flag, None)
        if output is None:
            continue
        destination = resolve_output_path(output)
        key = _portable_output_key(destination)
        literal_key = _portable_output_key(
            pathlib.Path(os.path.abspath(output.expanduser()))
        )
        # Report destinations should never alter Git's control files or refs,
        # even if a caller accidentally requests --json .git/config.
        if any(part.casefold() == ".git" for part in destination.parts):
            raise PatchTransitError(f"--{flag} cannot target a .git control path")
        if any(key[: len(root)] == root for root in protected_keys):
            raise PatchTransitError(f"--{flag} cannot target a Git control path")
        if key in source_paths:
            raise PatchTransitError(f"--{flag} would overwrite an input patch")
        for previous, previous_key, previous_literal in seen:
            if key == previous_key or literal_key == previous_literal:
                raise PatchTransitError(
                    f"--{flag} and --{previous} have the same output path"
                )
            if (
                key[: len(previous_key)] == previous_key
                or previous_key[: len(key)] == key
                or literal_key[: len(previous_literal)] == previous_literal
                or previous_literal[: len(literal_key)] == literal_key
            ):
                raise PatchTransitError(
                    f"--{flag} and --{previous} have conflicting output paths"
                )
        seen.append((flag, key, literal_key))


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        args.repo = _expand_user_path(args.repo)
        if args.action == "compare":
            args.old = _expand_user_path(args.old)
            args.new = _expand_user_path(args.new)
        else:
            args.patch = _expand_user_path(args.patch)
        _validate_outputs(args)
        if args.action == "inspect":
            result = inspect_patch(args.patch.resolve())
            if args.json:
                atomic_write(args.json, json_report(result))
            print(f"Patch SHA256 : {result['sha256']}")
            print(
                f"Files: {len(result['files'])}  Hunks: {result['hunks']}  Lines: +{result['added_lines']} -{result['removed_lines']}"
            )
            for name in result["files"]:
                print(f"  {_terminal_safe(name)}")
            return 0
        _timeout_seconds(args.timeout)
        if args.execute and not args.command:
            raise PatchTransitError("--execute requires --command")
        if args.command and not args.execute:
            raise PatchTransitError(
                "Execution is opt-in: provide --execute to run --command"
            )
        command = _split_command(args.command) if args.command else None
        if args.command and not command:
            raise PatchTransitError("Empty --command")
        old = args.old if args.action == "compare" else None
        new = args.new if args.action == "compare" else args.patch
        outcome = evaluate(
            args.repo, args.base, old, new, command=command, timeout=args.timeout
        )
        print(
            f"PatchTransit | {outcome['verdict'].upper()} | {outcome['changed_files']} effective files"
        )
        print(f"Base tree: {outcome['base_tree']}")
        for item in outcome["changes"]:
            print(f"  {item['change']:<8} {_terminal_safe(item['path'])}")
        if outcome.get("checks"):
            old_check = outcome["checks"]["old"]
            new_check = outcome["checks"]["new"]
            print(
                f"Checks: old={_terminal_safe(_check_status(old_check))} "
                f"new={_terminal_safe(_check_status(new_check))}"
            )
        if args.json:
            atomic_write(args.json, json_report(outcome))
            print(f"JSON evidence: {_terminal_safe(args.json)}")
        if args.html:
            atomic_write(args.html, html_report(outcome))
            print(f"HTML report: {_terminal_safe(args.html)}")
        if args.diff:
            atomic_write(args.diff, outcome["effective_diff"])
            print(f"Effective diff preview: {_terminal_safe(args.diff)}")
            if not outcome.get("diff_preview_complete", True):
                print(
                    "patchtransit: the diff preview omits some changes; "
                    "use --json for the complete file manifest",
                    file=sys.stderr,
                )
        return 1 if outcome["verdict"] == "regression" else 0
    except (PatchTransitError, ValueError, OSError) as exc:
        print(f"patchtransit: {_terminal_safe(exc)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
