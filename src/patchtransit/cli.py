"""Command-line interface with explicit execution consent."""

from __future__ import annotations

import argparse
import pathlib
import shlex
import sys

from . import __version__
from .core import PatchTransitError, evaluate, patch_metadata
from .report import atomic_write, html_report, json_report


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


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.action == "inspect":
            result = patch_metadata(args.patch.resolve())
            if args.json:
                atomic_write(args.json, json_report(result))
            print(f"Patch SHA256 : {result['sha256']}")
            print(
                f"Files: {len(result['files'])}  Hunks: {result['hunks']}  Lines: +{result['added_lines']} -{result['removed_lines']}"
            )
            for name in result["files"]:
                print(f"  {name}")
            return 0
        if args.timeout <= 0:
            raise PatchTransitError("--timeout must be positive")
        if args.execute and not args.command:
            raise PatchTransitError("--execute requires --command")
        if args.command and not args.execute:
            raise PatchTransitError(
                "Execution is opt-in: provide --execute to run --command"
            )
        command = shlex.split(args.command) if args.command else None
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
            print(f"  {item['change']:<8} {item['path']}")
        if outcome.get("checks"):
            old_check = outcome["checks"]["old"]
            new_check = outcome["checks"]["new"]
            print(
                f"Checks: old={old_check.get('exit_code')} new={new_check.get('exit_code')}"
            )
        if args.json:
            atomic_write(args.json, json_report(outcome))
            print(f"JSON evidence: {args.json}")
        if args.html:
            atomic_write(args.html, html_report(outcome))
            print(f"HTML report: {args.html}")
        if args.diff:
            atomic_write(args.diff, outcome["effective_diff"])
            print(f"Effective diff: {args.diff}")
        return 1 if outcome["verdict"] == "regression" else 0
    except (PatchTransitError, ValueError, OSError) as exc:
        print(f"patchtransit: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
