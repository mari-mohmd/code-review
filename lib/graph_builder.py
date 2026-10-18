"""
===============================================================================
 Project    : A Lightweight Methodology for Verifying Intended
                       Logic During Code Review
 File       : graph_builder.py
 Author(s)  : Mohammad Mari, Lian Wen
 Affiliation: School of ICT, Griffith University
 Contact    : mohammad.mari@griffithuni.edu.au
 Created    : 2026
 License    : MIT License (see LICENSE file for details)
 Description: A graph builder module based on the defined formal method:
              P = (F, C, L)  where F = Y ∪ S.

              L_import is resolved package-aware:
                * 'import a.b.c' / 'from a.b import c' map to a/b/c.py,
                  a/b/c/__init__.py or (for 'from') a/b.py / a/b/__init__.py
                * relative imports ('from .x import y') are resolved against
                  the importing file's package
                * src/-style layouts are supported by suffix matching when
                  the match is unambiguous
              L_open resolves string literals passed to open() against the
              project root and the opening file's directory.

              The model also records which names each file uses from each
              project module, so that files depending on a changed
              definition can be found (reverse linkage).
 Usage      : Supplementary file. see IntentCheck.py
===============================================================================
"""
import ast
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

_TEST_RE = re.compile(r"(^|/)tests?(/|_)|test_|_test\.py$")
_SKIP_DIRS = {".git", ".hg", ".svn", "__pycache__", ".tox", ".venv", "venv",
              "build", "dist", "node_modules", ".eggs"}


@dataclass
class ProgramModel:
    """P = (F, C, L)  where F = Y ∪ S."""
    python_files: list = field(default_factory=list)
    supplementary_files: list = field(default_factory=list)
    content: dict = field(default_factory=dict)
    linkages: dict = field(default_factory=dict)       # file -> [linked files]
    uses: dict = field(default_factory=dict)           # file -> {target file: {names}}
    unparseable: dict = field(default_factory=dict)    # file -> error message


class DependencyGraphBuilder:
    def build(self, project_dir: str, should_ignore_test) -> ProgramModel:
        model = ProgramModel()
        root = Path(project_dir)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fn in filenames:
                path = Path(dirpath) / fn
                rel = path.relative_to(root).as_posix()
                if path.suffix == ".py":
                    if should_ignore_test and _TEST_RE.search(rel):
                        continue
                    model.python_files.append(rel)
                elif path.suffix in (".json", ".md", ".txt", ".yaml", ".yml",
                                     ".cfg", ".ini", ".toml", ".csv", ".log"):
                    model.supplementary_files.append(rel)
        model.python_files.sort()
        self._index(model.python_files)
        self._supp = set(model.supplementary_files)
        self._supp_by_base = defaultdict(list)
        for s in model.supplementary_files:
            self._supp_by_base[s.rsplit("/", 1)[-1]].append(s)

        for rel in model.python_files:
            try:
                source = (root / rel).read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source, filename=rel)
            except SyntaxError as e:
                model.unparseable[rel] = f"{e.msg} (line {e.lineno})"
                continue
            except OSError:
                continue
            model.content[rel] = source
            deps, uses = self._deps(tree, rel)
            if deps:
                model.linkages[rel] = deps
            if uses:
                model.uses[rel] = uses
        return model

    # ------------------------------------------------------------------
    def _index(self, py_files):
        self._exact = {}
        self._suffix = defaultdict(set)
        for rel in py_files:
            parts = rel[:-3].split("/")
            if parts[-1] == "__init__":
                parts = parts[:-1]
            if not parts:
                continue
            self._exact.setdefault(".".join(parts), rel)
            for k in range(1, len(parts)):
                self._suffix[".".join(parts[k:])].add(rel)

    def resolve(self, dotted: str):
        """Return the project file implementing module `dotted`, or None."""
        if not dotted:
            return None
        if dotted in self._exact:
            return self._exact[dotted]
        cands = self._suffix.get(dotted, set())
        if len(cands) == 1 and "." in dotted:
            return next(iter(cands))
        return None

    @staticmethod
    def _package_of(rel: str) -> list:
        parts = rel[:-3].split("/")
        return parts[:-1]  # for pkg/__init__.py this is ['pkg'], i.e. the package itself

    def _deps(self, tree, rel):
        deps: list = []
        uses: dict = defaultdict(set)
        aliases: dict = {}          # local name -> target file (module objects)

        def add(target):
            if target and target != rel and target not in deps:
                deps.append(target)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    target = self.resolve(a.name)
                    add(target)
                    if target:
                        aliases[a.asname or a.name] = target
                        if a.asname is None:  # 'import a.b' binds 'a'
                            aliases.setdefault(a.name, target)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = self._package_of(rel)
                    if node.level > 1:
                        base = base[:len(base) - (node.level - 1)]
                    mod = ".".join(base + (node.module.split(".") if node.module else []))
                else:
                    mod = node.module or ""
                for a in node.names:
                    sub = self.resolve(f"{mod}.{a.name}") if a.name != "*" else None
                    if sub:                                  # importing a submodule
                        add(sub)
                        aliases[a.asname or a.name] = sub
                        continue
                    target = self.resolve(mod)
                    add(target)
                    if target:
                        uses[target].add(a.name)
            elif isinstance(node, ast.Call):
                func = node.func
                is_open = (isinstance(func, ast.Name) and func.id == "open") or \
                          (isinstance(func, ast.Attribute) and func.attr == "open")
                if is_open and node.args:
                    first = node.args[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        add(self._resolve_open(first.value, rel))

        # attribute usage through module aliases: alias.name
        if aliases:
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    chain = []
                    cur = node
                    while isinstance(cur, ast.Attribute):
                        chain.append(cur.attr)
                        cur = cur.value
                    if isinstance(cur, ast.Name) and cur.id in aliases:
                        uses[aliases[cur.id]].add(chain[-1])
        return deps, dict(uses)

    def _resolve_open(self, value: str, rel: str):
        v = value.replace("\\", "/").lstrip("./")
        here = rel.rsplit("/", 1)[0] if "/" in rel else ""
        for cand in (v, f"{here}/{v}" if here else v):
            if cand in self._supp:
                return cand
        base = v.rsplit("/", 1)[-1]
        hits = self._supp_by_base.get(base, [])
        return hits[0] if len(hits) == 1 else None
