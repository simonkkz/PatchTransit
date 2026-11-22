"""Produce sample PatchTransit evidence using disposable Git repositories.

This demonstration works on Linux, macOS and Windows; it never alters the
user's existing Git checkout and runs no untrusted verification commands.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from pathlib import Path

from patchtransit.cli import main as patchtransit_main

PROJECT = Path(__file__).resolve().parents[1]


def demo(output_dir: Path) -> int:
    output_dir = output_dir.expanduser().resolve()
    # Never let inherited GIT_DIR/GIT_WORK_TREE/index overrides redirect the
    # example's Git commands into an unrelated user checkout.
    git_env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    git_env["GIT_TERMINAL_PROMPT"] = "0"
    with tempfile.TemporaryDirectory(prefix="patchtransit-demo-") as directory:
        root = Path(directory)
        repo = root / "repo"
        repo.mkdir()

        def git(*arguments: str) -> bytes:
            return subprocess.run(
                ("git", *arguments), cwd=repo, env=git_env,
                check=True, capture_output=True
            ).stdout

        git("init", "-q")
        git(
            "-c", "user.name=PatchTransit", "-c", "user.email=demo@example.invalid",
            "commit", "--allow-empty", "-qm", "demo base",
        )
        source = repo / "calc.py"
        source.write_text("def calculate():\n    return 1\n", encoding="utf-8")
        git("add", "calc.py")
        git(
            "-c", "user.name=PatchTransit", "-c", "user.email=demo@example.invalid",
            "commit", "-qm", "add example",
        )
        source.write_text("def calculate():\n    return 2\n", encoding="utf-8")
        old_patch = root / "old.patch"
        old_patch.write_bytes(git("diff", "--binary"))
        source.write_text("def calculate():\n    return 3\n", encoding="utf-8")
        new_patch = root / "new.patch"
        new_patch.write_bytes(git("diff", "--binary"))
        git("restore", "calc.py")

        output_dir.mkdir(parents=True, exist_ok=True)
        result = patchtransit_main(
            [
                "compare", str(old_patch), str(new_patch),
                "--repo", str(repo),
                "--html", str(output_dir / "demo.html"),
                "--json", str(output_dir / "demo.json"),
                "--diff", str(output_dir / "demo.diff"),
            ]
        )
    if result == 0:
        print(f"Open in a browser: {output_dir / 'demo.html'}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path, default=PROJECT / "reports",
        help="Where to save the HTML, JSON and diff preview (default: reports/)",
    )
    arguments = parser.parse_args()
    return demo(arguments.output_dir)


if __name__ == "__main__":
    raise SystemExit(main())
