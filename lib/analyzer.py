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
 Description: AST-based code analysis. Imports checkers and perform analysis
 Author      : Mohammad Mari, Lian Wen
 Usage      : Supplementary file. see review.py
===============================================================================

Logic Verifier - AST-based code analysis for intended logic verification.
Implements the methodology from Mari & Wen (2026).

Formal models implemented:
  P  = (F, C, L)                     - program representation
  LC(y) = (R_y, O_y, U_y)           - lifecycle completeness
  SD(B_i,B_j) = 2|LCS|/(|Bi|+|Bj|) - structural divergence score
  DI(y) = I_y ∖ U_y                  - dead import set
"""


import os
from pathlib import Path
from .graph_builder import DependencyGraphBuilder
from .checklist_data import ChecklistItem
from .checkers import LifecycleChecker, NameSimilarityChecker, DeadImportChecker, MagicNumberChecker, \
    StructuralDivergenceChecker, PathCoherenceChecker, HardcodedPathChecker, InjectionRiskChecker, ConcurrencyChecker, \
    ShellInjectionChecker, InputChecker


# Diff Parser
def parse_unified_diff(diff_text: str) -> dict:
    changed = {}
    cur = None
    lines = []
    for line in diff_text.splitlines():
        if line.startswith("+++ b/") or (line.startswith("+++ ") and not line.startswith("+++ b/")):
            if cur and lines:
                changed[cur] = "\n".join(lines)
            cur = line[6:].strip() if line.startswith("+++ b/") else line[4:].strip()
            lines = []
        elif line.startswith("+") and not line.startswith("+++"):
            lines.append(line[1:])
    if cur and lines:
        changed[cur] = "\n".join(lines)
    return changed


class ChecklistGenerator:
    """
    Full pipeline:
      1. Build P = (F, C, L)         - dependency graph for the project
      2. Parse diff or accept file list
      3. For each target file:
           a. Linkage items           - L_import ∪ L_open dependencies
           b. All registered checkers - in declaration order
      4. Return sorted checklist      - warnings before info
    """

    def __init__(self, project_dir: str):
        self.project_dir = Path(project_dir)
        self.dep_builder = DependencyGraphBuilder()
        self.checkers = [
            NameSimilarityChecker(),
            DeadImportChecker(),
            MagicNumberChecker(),
            LifecycleChecker(),
            StructuralDivergenceChecker(),
            InjectionRiskChecker(),
            ConcurrencyChecker(),
            InputChecker(),
            HardcodedPathChecker(),
            ShellInjectionChecker(),
            PathCoherenceChecker(),
        ]

    def generate_from_diff(self, diff_text: str) -> list:
        model = self.dep_builder.build(str(self.project_dir))
        changed = parse_unified_diff(diff_text)
        items = []
        for filename, new_content in changed.items():
            base = os.path.basename(filename)
            items += self._linkage(base, filename, model)
            source = self._read(filename, new_content)
            for c in self.checkers:
                items += c.check(source, base)
        return _sort(items)

    def generate_from_files(self, filenames: list) -> list:
        model = self.dep_builder.build(str(self.project_dir))
        items = []
        for filename in filenames:
            base = os.path.basename(filename)
            items += self._linkage(base, filename, model)
            full = self.project_dir / filename
            if full.exists():
                try:
                    source = full.read_text(encoding="utf-8", errors="replace")
                    for c in self.checkers:
                        items += c.check(source, base)
                except Exception:
                    pass
        return _sort(items)

    def generate_from_project(self) -> list:
        """Scan every Python file in the project - no diff or file list required."""
        model = self.dep_builder.build(str(self.project_dir))
        return self.generate_from_files(model.python_files)

    def _linkage(self, base, filename, model):
        linked = model.linkages.get(base, model.linkages.get(filename, []))
        if not linked:
            return []
        return [ChecklistItem(
            category="linkage",
            message=f"Linked files to '{base}' - have they been checked?",
            detail="  - " + "\n  - ".join(linked),
        )]

    def _read(self, filename, fallback):
        full = self.project_dir / filename
        if full.exists():
            try:
                return full.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
        return fallback


def _sort(items: list) -> list:
    """Warnings before info; within each severity preserve insertion order."""
    order = {"warning": 0, "info": 1}
    return sorted(items, key=lambda i: order.get(i.category, 9))
