
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
 Description: A graph builder module bsed on the defined formal method:
              P = (F, C, L)  where F = Y ∪ S.
 Usage      : Supplementary file. see review.py
===============================================================================
"""
import ast
from pathlib import Path
from dataclasses import dataclass, field
import os


@dataclass
class ProgramModel:
    """P = (F, C, L)  where F = Y ∪ S."""
    python_files: list = field(default_factory=list)
    supplementary_files: list = field(default_factory=list)
    content: dict = field(default_factory=dict)
    linkages: dict = field(default_factory=dict)

class DependencyGraphBuilder:
    def build(self, project_dir: str, should_ignore_test) -> ProgramModel:
        model = ProgramModel()
        root = Path(project_dir)
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            rel = str(path.relative_to(root))
            if path.suffix == ".py":
                if should_ignore_test and "test" in rel:
                    continue
                model.python_files.append(rel)
            elif path.suffix in (".json", ".md", ".txt", ".yaml", ".yml",
                                  ".cfg", ".ini", ".toml", ".csv", ".log"):
                model.supplementary_files.append(rel)
        for rel in model.python_files:
            full = root / rel
            try:
                source = full.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source, filename=rel)
                model.content[rel] = source
                deps = self._deps(tree, model.python_files, model.supplementary_files)
                if deps:
                    model.linkages[rel] = deps
            except SyntaxError:
                pass
        return model

    def _deps(self, tree, py_files, supp_files):
        deps = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        c = a.name.split(".")[0] + ".py"
                        if c in py_files and c not in deps:
                            deps.append(c)
                elif node.module:
                    c = node.module.split(".")[0] + ".py"
                    if c in py_files and c not in deps:
                        deps.append(c)
            if isinstance(node, ast.Call):
                func = node.func
                is_open = (isinstance(func, ast.Name) and func.id == "open") or \
                          (isinstance(func, ast.Attribute) and func.attr == "open")
                if is_open and node.args:
                    first = node.args[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        fname = os.path.basename(first.value)
                        if fname in supp_files and fname not in deps:
                            deps.append(fname)
        return deps
