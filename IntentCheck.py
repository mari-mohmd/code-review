#!/usr/bin/env python3
"""
===============================================================================
 Project    : A Lightweight Methodology for Verifying Intended
                       Logic During Code Review
 File       : main.py
 Author(s)  : Mohammad Mari, Lian Wen
 Affiliation: School of ICT, Griffith University
 Contact    : mohammad.mari@griffithuni.edu.au
 Created    : 2026
 License    : MIT License (see LICENSE file for details)
 Description: Verifies intended logic during code review by generating dynamic,
              context-aware checklists.
 Usage      : python IntentCheck.py -h
   Example  : python IntentCheck.py --project ./test_scenarios/scenario5 --all
"""

import argparse
import json
import sys
from pathlib import Path

from lib.analyzer import ChecklistGenerator
from lib.static_checklist import StaticChecklistLoader

# Terminal colors:
RESET = "\033[0m"
BOLD = "\033[1m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
DIM = "\033[2m"


def render_text(items: list) -> str:
    if not items:
        return f"{GREEN}  No potential issues detected.{RESET}\n"

    lines = [f"\n{BOLD}{'─' * 62}{RESET}", f"{BOLD}  CODE REVIEW CHECKLIST  -  "
                                           f"{len(items)} item(s)  ", f"{BOLD}{'─' * 62}{RESET}\n"]

    for item in items:
        loc = f"  {DIM}line {item.line}{RESET}" if item.line else ""
        score_str = f"  {DIM}score={item.score:.2f}{RESET}" if item.score is not None else ""

        lines.append(f"  {YELLOW}[]  {BOLD}{item.message}{RESET}{loc}{score_str}")
        # Indent each detail line
        for dline in item.detail.splitlines():
            lines.append(f"      {dline}")
        lines.append("")

    lines.append(f"{BOLD}{'─' * 62}{RESET}\n")
    return "\n".join(lines)


def render_json(items: list) -> str:
    return json.dumps(
        [
            {
                "category": it.category,
                "message": it.message,
                "detail": it.detail,
                "line": it.line,
                "score": it.score,
            }
            for it in items
        ],
        indent=2,
    )


def render_summary(items: list) -> str:
    """One-line-per-file summary for --summary mode."""
    from collections import Counter
    by_cat = Counter(i.category for i in items)
    parts = [f"{BOLD}{len(items)} total{RESET}"]
    cat_detail = "  ".join(f"{k}:{v}" for k, v in sorted(by_cat.items()))
    return "\n".join(parts) + f"\n{DIM}{cat_detail}{RESET}\n"


# ------------ Main Method ------------
def main():
    parser = argparse.ArgumentParser(
        description="Generate a dynamic code review checklist (Mari & Wen, 2026).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  # Analyse a git diff
  git diff main > changes.diff
  python IntentCheck.py --project . --diff changes.diff

  # Analyse specific files
  python IntentCheck.py --project . --files src/main.py src/utils.py

  # Scan the whole project
  python IntentCheck.py --project . --all
        """,
    )
    parser.add_argument("--project", "-p", default=None,
                        help="Path to the project root directory.")
    parser.add_argument("--diff", "-d",
                        help="Path to a unified diff file (.diff / .patch).")
    parser.add_argument("--files", "-f", nargs="+",
                        help="Specific Python files to analyse (relative to project root).")
    parser.add_argument("--all", "-a", action="store_true",
                        help="Scan every Python file in the project.")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON instead of human-readable text.")
    parser.add_argument("--summary", action="store_true",
                        help="Print a one-line summary instead of full checklist.")
    parser.add_argument("--ignore-test", action="store_true", default=False,
                        help="ignores test files.")
    parser.add_argument("--category", nargs="+",
                        metavar="CAT",
                        help="Filter to specific categories "
                             "(e.g. lifecycle portability shell naming).")
    parser.add_argument("--checklist", metavar="FILE",
                        help="Path to a checklist.json file of user-defined "
                             "static items to prepend to every review.")
    parser.add_argument("--checklist-init", metavar="FILE", nargs="?",
                        const="checklist.json",
                        help="Write a starter checklist.json template to FILE "
                             "(default: checklist.json) and exit.")

    args = parser.parse_args()

    if args.checklist_init:
        dest = Path(args.checklist_init)
        try:
            StaticChecklistLoader.write_example(dest)
            print(f"Created starter checklist template: {dest}")
        except FileExistsError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    if not args.project:
        parser.print_help()
        sys.exit(1)

    project_dir = Path(args.project)
    if not project_dir.is_dir():
        print(f"Error: '{args.project}' is not a directory.", file=sys.stderr)
        sys.exit(1)

    # Resolve checklist: explicit flag > project root > tool directory
    checklist_path = args.checklist
    if checklist_path is None:
        checklist_path = StaticChecklistLoader.resolve_for_project(project_dir)
    if checklist_path is None:
        checklist_path = StaticChecklistLoader.resolve_for_project(Path(__file__).parent)

    generator = ChecklistGenerator(str(project_dir), checklist_path=checklist_path)

    if args.diff:
        diff_path = Path(args.diff)
        if not diff_path.exists():
            print(f"Error: diff file '{args.diff}' not found.", file=sys.stderr)
            sys.exit(1)
        items = generator.generate_from_diff(
            diff_path.read_text(encoding="utf-8", errors="replace"), should_ignore_test=args.ignore_test
        )

    elif args.files:
        items = generator.generate_from_files(args.files, args.ignore_test)
    elif args.all:
        items = generator.generate_from_project(args.ignore_test)
    else:
        parser.print_help()
        sys.exit(0)

    if args.category:
        allowed = set(args.category)
        items = [i for i in items if i.category in allowed]

    if args.json:
        print(render_json(items))
    elif args.summary:
        print(render_summary(items))
    else:
        print(render_text(items))


if __name__ == "__main__":
    main()
