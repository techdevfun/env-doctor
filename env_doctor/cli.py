"""Command line interface for env-doctor."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .core import apply_fix, audit


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="env-doctor",
        description="Audit .env files: drift vs .env.example, placeholders, risky secrets, unused vars.",
    )
    p.add_argument("--version", action="version", version=f"env-doctor {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="Audit one .env file.")
    check.add_argument("--env", default=".env", help="Path to .env file (default: .env)")
    check.add_argument("--example", default=".env.example", help="Path to .env.example (default: .env.example)")
    check.add_argument("--no-example", action="store_true", help="Skip the example-file comparison.")
    check.add_argument("--scan", default=None, help="Root dir to scan for referenced vars (optional).")
    check.add_argument("--format", choices=["text", "json"], default="text", help="Output format.")
    check.add_argument("--quiet", action="store_true", help="Only print the summary line.")
    check.add_argument("--fix", action="store_true",
                       help="Add keys missing in the example file as empty placeholders, then re-check. "
                            "Never copies real values from .env.")
    return p


def format_text(result: dict) -> str:
    lines: list[str] = []
    if not result["issues"]:
        lines.append(f"OK: {result['env_file']} looks clean ({len(result['keys'])} keys).")
        return "\n".join(lines)
    for it in result["issues"]:
        mark = "ERROR" if it["severity"] == "error" else "WARN "
        lines.append(f"[{mark}] {it['code']}: {it['message']}")
    lines.append(f"Summary: {result['errors']} error(s), {result['warnings']} warning(s), {len(result['keys'])} key(s).")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "check":
        env_path = Path(args.env)
        example_path = None if args.no_example else Path(args.example)
        scan_root = Path(args.scan) if args.scan else None
        if args.fix and example_path is None:
            print("error: --fix needs an example file (remove --no-example).", file=sys.stderr)
            return 2
        result = audit(env_path, example_path, scan_root)
        fixed: list[str] = []
        if args.fix and example_path is not None:
            fixed = apply_fix(env_path, example_path)
            if fixed:
                # Re-check so the reported result reflects the fixed files.
                result = audit(env_path, example_path, scan_root)
        if args.format == "json":
            out = dict(result)
            if args.fix:
                out["fixed"] = fixed
            print(json.dumps(out, indent=2))
        elif args.quiet:
            if args.fix:
                if fixed:
                    print(f"Fixed: added {len(fixed)} key(s) to {example_path}: {', '.join(fixed)}")
                elif env_path.exists():
                    print("Nothing to fix.")
            print(f"{result['errors']} error(s), {result['warnings']} warning(s), {len(result['keys'])} key(s).")
        else:
            if args.fix:
                if fixed:
                    print(f"Fixed: added {len(fixed)} key(s) to {example_path}: {', '.join(fixed)}")
                elif env_path.exists():
                    print(f"Nothing to fix: {example_path} already covers every key in {env_path}.")
            print(format_text(result))
        return 0 if result["ok"] else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
