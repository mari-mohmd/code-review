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
import re
import ast
from pathlib import Path

from pandas.io.sas.sas_constants import header_size_offset

from .graph_builder import DependencyGraphBuilder
from .checklist_data import ChecklistItem
from .checkers import LifecycleChecker, NameSimilarityChecker, DeadImportChecker, MagicNumberChecker, \
    StructuralDivergenceChecker, PathCoherenceChecker, HardcodedPathChecker, InjectionRiskChecker, ConcurrencyChecker, \
    ShellInjectionChecker, InputChecker
from .static_checklist import StaticChecklistLoader


# Diff Parser

def parse_unified_diff(diff_text: str, should_ignore_test: bool) -> dict[str, str]:
    """
    Return {filename: added_lines_only} for backward compatibility with
    generate_from_files and linkage checking.

    The added_lines_only string contains only the + lines (leading + stripped),
    joined by newlines.  This is still used by generate_from_diff to know
    which files changed; the actual analysis is now done by DiffScopeAnalyser.
    """
    changed: dict[str, str] = {}
    cur   = None
    lines = []
    for line in diff_text.splitlines():
        if line.startswith("+++ b/") or (line.startswith("+++ ")
                                          and not line.startswith("+++ b/")):
            if should_ignore_test and "test" in line:
                continue
            if cur and lines:
                changed[cur] = "\n".join(lines)
            cur   = line[6:].strip() if line.startswith("+++ b/") \
                    else line[4:].strip()
            lines = []
        elif line.startswith("+") and not line.startswith("+++"):
            lines.append(line[1:])
    if cur and lines:
        changed[cur] = "\n".join(lines)
    return changed


# ─── Diff Scope Analyser ──────────────────────────────────────────────────────

class DiffScopeAnalyser:
    """
    Analyses a unified diff with precise scope awareness.

    Rather than running checkers against the entire file, this class:

    1. Parses the diff to extract added line numbers and their content.
    2. Parses the full file AST and maps every added line to its enclosing
       scope — either a function/method (local) or module level (global).
    3. For each changed scope:
         - LOCAL  (inside a function or class method):
             Extract the full source of that function/class so checkers
             see the complete local context, then trace all call sites of
             that function/class across the file to assess impact.
         - GLOBAL (module-level assignment, import, top-level statement):
             Extract the name(s) introduced and search for all usages
             across the entire file, since globals are visible everywhere.
    4. Deduplicate scopes so a function changed in multiple hunks is only
       analysed once.
    5. Emit linkage items for any file in L_import | L_open that is
       reachable from any name introduced or modified in the diff.

    The checkers themselves are unchanged — they receive a source string
    and filename, but that source string is now the minimal relevant
    context extracted by scope, not the raw full file.
    """

    def __init__(self, full_source: str, filename: str):
        self.full_source = full_source
        self.filename    = filename
        try:
            self.tree = ast.parse(full_source)
            self.lines = full_source.splitlines()
        except SyntaxError:
            self.tree  = None
            self.lines = full_source.splitlines()

    # ── Step 1: parse the diff into {line_number: added_line_text} ────────
    @staticmethod
    def added_lines(diff_text: str, filename: str) -> dict[int, str]:
        """
        Return {absolute_line_number: line_text} for every added line
        in the diff hunk that belongs to `filename`.

        Unified diff hunk headers look like:
            @@ -old_start,old_count +new_start,new_count @@
        We track the new-file line counter across hunks to get absolute
        line numbers in the post-patch file.
        """
        result: dict[int, str] = {}
        in_file = False
        new_lineno = 0

        for line in diff_text.splitlines():
            # Detect which file this hunk belongs to
            if line.startswith("+++ b/") or line.startswith("+++ "):
                target = line[6:].strip() if line.startswith("+++ b/") \
                         else line[4:].strip()
                in_file = (
                    target == filename
                    or target.endswith("/" + filename)
                    or filename.endswith(target)
                )
                new_lineno = 0
                continue

            if not in_file:
                continue

            # Hunk header: @@ -a,b +c,d @@
            if line.startswith("@@"):
                m = re.search(r"\+(\d+)", line)
                if m:
                    new_lineno = int(m.group(1)) - 1  # will be incremented below
                continue

            if line.startswith("+++") or line.startswith("---"):
                continue

            if line.startswith("+"):
                new_lineno += 1
                result[new_lineno] = line[1:]   # strip the leading +
            elif line.startswith("-"):
                pass                            # deleted lines don't advance new counter
            else:
                new_lineno += 1                 # context lines advance the counter

        return result

    @staticmethod
    def _normalise(text: str) -> str:
        tokens = []
        for line in text.splitlines():
            s = line.strip()
            if s:
                tokens.append(" ".join(s.split()))
        joined = " ".join(tokens)
        joined = re.sub(r'\(\s+', '(', joined)
        joined = re.sub(r'\s+\)', ')', joined)
        joined = re.sub(r'\[\s+', '[', joined)
        joined = re.sub(r'\s+\]', ']', joined)
        joined = re.sub(r'\s+,', ',', joined)
        joined = re.sub(r',(\S)', r', \1', joined)
        return joined

    @staticmethod
    def _hunk_removed_lines(diff_text: str, filename: str) -> dict:
        result: dict = {}
        in_file = False
        hunk_start = 0
        removed_buf: list = []

        def flush():
            if hunk_start and removed_buf:
                result[hunk_start] = "\n".join(removed_buf)

        for line in diff_text.splitlines():
            if line.startswith("+++ b/") or line.startswith("+++ "):
                target = line[6:].strip() if line.startswith("+++ b/") \
                    else line[4:].strip()
                in_file = (
                        target == filename
                        or target.endswith("/" + filename)
                        or filename.endswith(target)
                )
                flush();
                removed_buf = [];
                hunk_start = 0
                continue
            if not in_file:
                continue
            if line.startswith("@@"):
                flush();
                removed_buf = []
                m = re.search(r"\+(\d+)", line)
                hunk_start = int(m.group(1)) if m else 0
                continue
            if line.startswith("+++") or line.startswith("---"):
                continue
            if line.startswith("-"):
                removed_buf.append(line[1:])

        flush()
        return result
    @staticmethod
    def _is_formatting_only(old_text: str, new_text: str) -> bool:
        """
        Return True if old_text and new_text are semantically identical
        after normalising all whitespace — meaning the change is purely
        cosmetic (line splitting, indentation adjustment, trailing space
        removal, etc.) and contains no change to logic or values.

        Strategy:
          1. Strip all leading/trailing whitespace from each line
          2. Remove blank lines
          3. Join into a single whitespace-normalised string
          4. Compare — if equal, the change is formatting only

        This catches:
          - A long line split across multiple lines
          - Indentation reformatted (2-space to 4-space etc.)
          - Trailing whitespace removed
          - Blank lines added or removed between statements

        It does NOT treat as formatting-only:
          - Any change to an identifier name
          - Any change to a literal value
          - Any added or removed statement
          - Any reordering of statements
        """

        def normalise(text: str) -> str:
            tokens = []
            for line in text.splitlines():
                stripped = line.strip()
                if stripped:
                    # Collapse internal whitespace to single space
                    tokens.append(" ".join(stripped.split()))
            return " ".join(tokens)

        return normalise(old_text) == normalise(new_text)

    @staticmethod
    def _old_scope_source(old_source: str, scope_name: str) -> str:
        """
        Extract the source of a named function or class from the
        OLD file source (pre-patch).  Returns empty string if not found.
        """
        try:
            tree = ast.parse(old_source)
        except SyntaxError:
            return ""

        lines = old_source.splitlines()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                if node.name == scope_name:
                    start = node.lineno - 1
                    end = getattr(node, "end_lineno", node.lineno)
                    return "\n".join(lines[start:end])
        return ""

    @staticmethod
    def removed_lines(diff_text: str, filename: str) -> dict:
        """
        Return {absolute_line_number: line_text} for every removed line
        in the diff that belongs to filename, using hunk headers to track
        exact line numbers in the PRE-patch (old) file.
        """
        result: dict = {}
        in_file = False
        old_lineno = 0

        for line in diff_text.splitlines():
            if line.startswith("+++ b/") or line.startswith("+++ "):
                target = line[6:].strip() if line.startswith("+++ b/") \
                    else line[4:].strip()
                in_file = (
                        target == filename
                        or target.endswith("/" + filename)
                        or filename.endswith(target)
                )
                old_lineno = 0
                continue

            if not in_file:
                continue

            if line.startswith("@@"):
                m = re.search(r"-(\d+)", line)
                if m:
                    old_lineno = int(m.group(1)) - 1
                continue

            if line.startswith("+++") or line.startswith("---"):
                continue

            if line.startswith("-"):
                old_lineno += 1
                result[old_lineno] = line[1:]  # strip leading -
            elif line.startswith("+"):
                pass  # added lines don't advance old counter
            else:
                old_lineno += 1  # context lines advance both counters

        return result

    def _extract_removed_names(self, removed_line: str) -> list:
        """
        Extract meaningful names from a removed line by attempting to
        parse it as a Python statement.  Falls back to a token scan if
        the line is not independently parseable (e.g. a fragment inside
        a block).

        Returns a list of names that were removed — these are candidates
        for impact analysis: are they still referenced elsewhere?
        """
        names = []

        # Try parsing the line as a statement
        try:
            tree = ast.parse(removed_line.strip())
            for node in ast.walk(tree):
                # Function or class definition removed
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                     ast.ClassDef)):
                    names.append(node.name)
                # Assignment removed — e.g. x = open(...) or x.close()
                elif isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            names.append(t.id)
                # Import removed
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        names.append(alias.asname or alias.name.split(".")[0])
                # Method call removed — e.g. f.close(), lock.release()
                elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                    call = node.value
                    if isinstance(call.func, ast.Attribute):
                        # e.g. f.close() — flag the object name
                        if isinstance(call.func.value, ast.Name):
                            names.append(call.func.value.id)
                        # also flag the method name — e.g. "close"
                        names.append(call.func.attr)
        except SyntaxError:
            # Line is not a complete statement — tokenise instead
            for tok in re.findall(r'\b([A-Za-z_][A-Za-z0-9_]*)\b',
                                  removed_line):
                if tok not in {'self', 'cls', 'return', 'if', 'else',
                               'for', 'while', 'in', 'not', 'and', 'or',
                               'True', 'False', 'None', 'def', 'class'}:
                    names.append(tok)

        return list(dict.fromkeys(names))  # deduplicate, preserve order

    def _still_referenced(self, name: str) -> list:
        """
        Return all line numbers in the FULL (post-patch) file where
        `name` is still referenced — as a Load, a Call, or an attribute.
        An empty list means the name was removed and is gone; a non-empty
        list means the removal may have broken something.
        """
        if self.tree is None:
            return []
        lines = []
        for node in ast.walk(self.tree):
            ln = getattr(node, "lineno", 0)
            if isinstance(node, ast.Name) and node.id == name:
                lines.append(ln)
            elif isinstance(node, ast.Attribute) and node.attr == name:
                lines.append(ln)
        return sorted(set(lines))

    def removed_impact_sources(self, diff_text: str) -> list:
        """
        For each removed line, determine the impact on the post-patch file:

        1. Extract names that were removed.
        2. For each name, check if it is still referenced in the full
           post-patch file.
           - If YES  → the removal broke something; extract the scope of
             each surviving reference as a fragment to check.
           - If NO   → the name is gone; check whether it was a resource
             release method (close, stop, shutdown…) — if so, extract the
             scope that OWNED that resource to check for lifecycle issues.
        3. Return (fragment, label, removal_note) tuples.

        removal_note is prepended to each checklist item detail so the
        reviewer knows the item was triggered by a REMOVAL not an addition.
        """
        removed = self.removed_lines(diff_text, self.filename)
        if not removed:
            return []

        results = []
        seen_scopes: set = set()

        for lineno, line_text in sorted(removed.items()):
            names = self._extract_removed_names(line_text)

            for name in names:
                still_used = self._still_referenced(name)

                if still_used:
                    # Name removed but still referenced → broken reference
                    removal_note = (
                        f"[REMOVED] '{name}' was removed at line {lineno} "
                        f"of the old file but is still referenced at: "
                        f"{', '.join(f'line {l}' for l in still_used[:5])}\n"
                        f"Verify this removal does not cause a NameError "
                        f"or broken call site."
                    )
                    # Extract the scope of each surviving reference
                    for ref_line in still_used:
                        scope = self._scope_for_line(ref_line)
                        if scope is not None:
                            sid = id(scope)
                            if sid in seen_scopes:
                                continue
                            seen_scopes.add(sid)
                            kind = type(scope).__name__.replace("Def", "").lower()
                            label = f"{kind}:{scope.name} [ref to removed '{name}']"
                            src = self._extract_scope_source(scope)
                            results.append((src, label, removal_note))
                        else:
                            # Reference is at module level
                            idx = ref_line - 1
                            if 0 <= idx < len(self.lines):
                                label = f"line:{ref_line} [ref to removed '{name}']"
                                results.append((self.lines[idx], label, removal_note))

                else:
                    # Name no longer exists — check if it was a release method
                    if name in LifecycleChecker.RELEASE_METHODS:
                        removal_note = (
                            f"[REMOVED] Release call '{name}' was removed "
                            f"at line {lineno} of the old file.\n"
                            f"Verify that the associated resource is still "
                            f"properly released elsewhere — this removal may "
                            f"have introduced a resource leak."
                        )
                        # Find scopes that own resources to re-check lifecycle
                        for node in ast.walk(self.tree) if self.tree else []:
                            if not isinstance(node, (ast.FunctionDef,
                                                     ast.AsyncFunctionDef)):
                                continue
                            sid = id(node)
                            if sid in seen_scopes:
                                continue
                            src = self._extract_scope_source(node)
                            # Only include if the source contains resource calls
                            if any(rc in src for rc in
                                   LifecycleChecker.RESOURCE_CALLS):
                                seen_scopes.add(sid)
                                label = (f"function:{node.name} "
                                         f"[release '{name}' removed]")
                                results.append((src, label, removal_note))

        return results
    # ── Step 2: map each added line to its enclosing scope ───────────────
    def _scope_for_line(self, lineno: int):
        """
        Walk the AST and return the innermost FunctionDef/AsyncFunctionDef
        or ClassDef that contains `lineno`.  Returns None if the line is
        at module level.
        """
        if self.tree is None:
            return None

        best = None
        for node in ast.walk(self.tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                     ast.ClassDef)):
                continue
            start = node.lineno
            end   = getattr(node, "end_lineno", start)
            if start <= lineno <= end:
                # Take the innermost (largest start line)
                if best is None or node.lineno > best.lineno:
                    best = node
        return best

    # ── Step 3a: extract source for a local scope node ────────────────────
    def _extract_scope_source(self, scope_node) -> str:
        """
        Return the source lines for a FunctionDef / ClassDef node,
        including its full body.
        """
        start = scope_node.lineno - 1            # 0-indexed
        end   = getattr(scope_node, "end_lineno", scope_node.lineno)
        return "\n".join(self.lines[start:end])

    # ── Step 3b: find all call sites of a local function/class ───────────
    def _call_sites_of(self, scope_name: str) -> list[int]:
        """
        Return line numbers where `scope_name` is called anywhere in the
        full file.  Used to assess the impact of a changed function/class.
        """
        sites = []
        if self.tree is None:
            return sites
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            name = None
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name == scope_name:
                sites.append(getattr(node, "lineno", 0))
        return sites

    # ── Step 3c: find all usages of a global name ─────────────────────────
    def _global_usage_lines(self, name: str) -> list[int]:
        """
        Return every line number where `name` appears as a Load node —
        i.e. every place the global variable/import is read.
        """
        lines = []
        if self.tree is None:
            return lines
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Name) and node.id == name \
                    and isinstance(node.ctx, ast.Load):
                lines.append(getattr(node, "lineno", 0))
        return lines

    # ── Step 4: names introduced at module level by a line ────────────────
    def _module_level_names(self, lineno: int) -> list[str]:
        """
        If `lineno` is a module-level assignment or import, return the
        names it introduces.  Returns [] for anything else.
        """
        names = []
        if self.tree is None:
            return names
        for node in ast.iter_child_nodes(self.tree):
            if getattr(node, "lineno", -1) != lineno:
                continue
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        names.append(t.id)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    names.append(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                   ast.ClassDef)):
                names.append(node.name)
        return names

    def _usage_scopes_of(self, name: str,
                         already_seen: set) -> list:
        """
        Find every function/method/class in the full file that contains
        a call to `name` (function usage) or an instantiation of `name`
        (class usage), and return those AST nodes.

        Covers:
          name(...)           -- direct call or instantiation
          obj.name(...)       -- method call on an attribute
          x = name(...)       -- result assigned to a variable

        Nodes already in `already_seen` are skipped to avoid
        re-analysing scopes that were themselves changed in the diff.
        """
        if self.tree is None:
            return []

        # Collect line numbers where name is called or instantiated
        usage_lines: set[int] = set()
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            called = None
            if isinstance(node.func, ast.Name):
                called = node.func.id
            elif isinstance(node.func, ast.Attribute):
                called = node.func.attr
            if called == name:
                usage_lines.add(getattr(node, "lineno", 0))

        if not usage_lines:
            return []

        # Map each usage line to its enclosing function/class scope
        result_nodes = []
        seen_node_ids: set = set()

        for lineno in usage_lines:
            enclosing = self._scope_for_line(lineno)
            if enclosing is None:
                # Usage is at module level — build a one-line fragment
                # directly in scoped_sources via the global path
                continue
            node_id = id(enclosing)
            if node_id in already_seen or node_id in seen_node_ids:
                continue
            seen_node_ids.add(node_id)
            result_nodes.append(enclosing)

        return result_nodes

    def scoped_sources(self, diff_text: str) -> list:
        """
        Returns list of (source_fragment, scope_label, formatting_only).

        formatting_only=True when the hunk's added and removed lines are
        semantically identical after whitespace normalisation — i.e. the
        change is purely cosmetic (line splitting, indentation, trailing
        spaces).  The caller emits a single INFO item and skips usage
        tracing and all checker runs for that scope.
        """
        added        = self.added_lines(diff_text, self.filename)
        hunk_removed = self._hunk_removed_lines(diff_text, self.filename)
        if not added:
            return []

        # Map each hunk start → its added lines text for comparison
        # Build per-hunk added text by grouping consecutive added line nos
        # We compare the whole hunk's added vs removed text to detect
        # formatting-only changes at the hunk level.
        #
        # Strategy: for each added lineno, find the hunk it belongs to
        # by picking the largest hunk_start <= lineno.
        hunk_starts = sorted(hunk_removed.keys())

        def hunk_for_lineno(ln: int) -> int:
            """Return the hunk_start that owns this line number."""
            best = 0
            for hs in hunk_starts:
                if hs <= ln:
                    best = hs
            return best

        # Build added text per hunk
        hunk_added: dict = {}
        for ln, text in added.items():
            hs = hunk_for_lineno(ln)
            hunk_added.setdefault(hs, []).append(text)
        hunk_added = {hs: "\n".join(lines) for hs, lines in hunk_added.items()}

        # Determine which hunks are formatting-only
        formatting_hunks: set = set()
        for hs, rem_text in hunk_removed.items():
            add_text = hunk_added.get(hs, "")
            if (add_text and rem_text
                    and self._normalise(add_text) == self._normalise(rem_text)):
                formatting_hunks.add(hs)

        seen_scopes: set = set()
        results = []

        for lineno in sorted(added.keys()):
            scope = self._scope_for_line(lineno)
            hs    = hunk_for_lineno(lineno)
            is_fmt = hs in formatting_hunks

            if scope is not None:
                scope_id = id(scope)
                if scope_id in seen_scopes:
                    continue
                seen_scopes.add(scope_id)

                src    = self._extract_scope_source(scope)
                kind   = (type(scope).__name__
                          .replace("Def", "")
                          .replace("Async", "async ")
                          .lower())
                label  = f"{kind}:{scope.name}"
                # offset = how many lines before this scope in the file
                # checkers produce line numbers relative to the fragment
                # starting at 1; adding offset converts to file line numbers
                offset = scope.lineno - 1
                results.append((src, label, is_fmt, offset))

                if is_fmt:
                    continue

                for usage_node in self._usage_scopes_of(scope.name,
                                                         seen_scopes):
                    seen_scopes.add(id(usage_node))
                    usage_src    = self._extract_scope_source(usage_node)
                    usage_kind   = (type(usage_node).__name__
                                    .replace("Def", "")
                                    .replace("Async", "async ")
                                    .lower())
                    usage_label  = (f"{usage_kind}:{usage_node.name}"
                                    f" [uses {scope.name}]")
                    usage_offset = usage_node.lineno - 1
                    results.append((usage_src, usage_label, False,
                                    usage_offset))

            else:
                names = self._module_level_names(lineno)
                if names:
                    usage_lines: set = set()
                    for name in names:
                        usage_lines.update(self._global_usage_lines(name))
                    relevant = sorted({lineno} | usage_lines)
                    fragment_lines = []
                    for ln in relevant:
                        idx = ln - 1
                        if 0 <= idx < len(self.lines):
                            fragment_lines.append(self.lines[idx])
                    src   = "\n".join(fragment_lines)
                    label = f"global:{','.join(names)}"
                    # Global fragments: first relevant line is the offset
                    offset = (relevant[0] - 1) if relevant else 0
                    results.append((src, label, is_fmt, offset))
                else:
                    idx = lineno - 1
                    if 0 <= idx < len(self.lines):
                        results.append(
                            (self.lines[idx], f"line:{lineno}", is_fmt,
                             lineno - 1)
                        )

        return results




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

    def __init__(self, project_dir: str, checklist_path=None):
        self.project_dir = Path(project_dir)
        self.dep_builder = DependencyGraphBuilder()
        self._static_loader = StaticChecklistLoader(checklist_path)
        self.checkers = [
            NameSimilarityChecker(),
            #DeadImportChecker(),
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

    @staticmethod
    def _changed_names(diff_text: str, filename: str) -> set:
        """
        Extract every identifier name that appears in the added or removed
        lines of the diff for this file.  These are the names that were
        actually touched by the change — used to filter full-file checker
        results to only those relevant to the diff.
        """
        names: set = set()
        in_file = False

        for line in diff_text.splitlines():
            if line.startswith("+++ b/") or line.startswith("+++ "):
                target = line[6:].strip() if line.startswith("+++ b/") \
                    else line[4:].strip()
                in_file = (
                        target == filename
                        or target.endswith("/" + filename)
                        or filename.endswith(target)
                )
                continue
            if not in_file:
                continue
            if line.startswith("@@") or line.startswith("---") \
                    or line.startswith("+++"):
                continue
            if line.startswith("+") or line.startswith("-"):
                # Extract all identifiers from this diff line
                content = line[1:]
                for tok in re.findall(r'\b([A-Za-z_][A-Za-z0-9_]*)\b', content):
                    names.add(tok)

        return names

    @staticmethod
    def _item_touches_changed(item, changed_names: set) -> bool:
        """
        Return True if the checklist item involves at least one name that
        appears in the diff.

        For StructuralDivergenceChecker items: the message contains the
        block names being compared e.g. "SD(LightSensor, HeatSensor)".
        For NameSimilarityChecker items: the message contains the
        conflicting identifier names.

        We check both the message and detail for any token that appears
        in changed_names.
        """
        if not changed_names:
            return False

        text = f"{item.message} {item.detail}"
        tokens = set(re.findall(r'\b([A-Za-z_][A-Za-z0-9_]*)\b', text))
        return bool(tokens & changed_names)

    @staticmethod
    def _reconstruct_old_source(diff_text: str, filename: str,
                                 new_source: str) -> str:
        """
        Reconstruct the pre-patch file source by applying the diff in
        reverse: take the new_source and swap added lines for removed
        lines at the correct positions using hunk headers.

        This gives DiffScopeAnalyser._old_scope_source() something to
        compare against for formatting-only detection.

        If reconstruction fails for any reason, returns empty string
        (formatting-only detection is then simply skipped).
        """
        try:
            lines = new_source.splitlines()
            in_file   = False
            new_lineno = 0
            patches: list = []   # list of (new_lineno, "add"/"remove", text)

            for line in diff_text.splitlines():
                if line.startswith("+++ b/") or line.startswith("+++ "):
                    target = (line[6:].strip()
                              if line.startswith("+++ b/")
                              else line[4:].strip())
                    in_file = (
                        target == filename
                        or target.endswith("/" + filename)
                        or filename.endswith(target)
                    )
                    new_lineno = 0
                    continue

                if not in_file:
                    continue

                if line.startswith("@@"):
                    m = re.search(r"\+(\d+)", line)
                    if m:
                        new_lineno = int(m.group(1)) - 1
                    continue

                if line.startswith("+++") or line.startswith("---"):
                    continue

                if line.startswith("+"):
                    new_lineno += 1
                    patches.append((new_lineno, "added", line[1:]))
                elif line.startswith("-"):
                    patches.append((new_lineno + 1, "removed", line[1:]))
                else:
                    new_lineno += 1

            # Rebuild old source: remove added lines, insert removed lines
            result = list(lines)
            offset = 0
            added_linenos   = {ln for ln, op, _ in patches if op == "added"}
            removed_patches = [(ln, t) for ln, op, t in patches
                               if op == "removed"]

            # Remove added lines (1-indexed → 0-indexed with offset)
            to_delete = sorted(added_linenos, reverse=True)
            for ln in to_delete:
                idx = ln - 1
                if 0 <= idx < len(result):
                    result.pop(idx)

            # Insert removed lines back in order
            for ln, text in sorted(removed_patches):
                idx = ln - 1 + offset
                idx = max(0, min(idx, len(result)))
                result.insert(idx, text)
                offset += 1

            return "\n".join(result)

        except Exception:
            return ""

    def generate_from_diff(self, diff_text: str, should_ignore_test) -> list:
        """
        Scope-aware diff analysis.

        For each changed file:
          1. Run StructuralDivergenceChecker and NameSimilarityChecker
             against the FULL file — these are cross-scope checkers that
             cannot work on fragments (divergence between two classes is
             only visible when both classes are present).
          2. Use DiffScopeAnalyser to extract scoped fragments for all
             other checkers — the enclosing function/class of each changed
             line, plus every function/class that calls or instantiates it.
          3. Run scope-specific checkers against each fragment.
          4. Run linkage against the full dependency graph.
        """
        model = self.dep_builder.build(str(self.project_dir), should_ignore_test)
        changed = parse_unified_diff(diff_text, should_ignore_test)
        items = []

        # Separate checkers into full-file vs scoped
        full_file_checkers = [
            c for c in self.checkers
            if type(c) in (StructuralDivergenceChecker, NameSimilarityChecker)
        ]
        scoped_checkers = [
            c for c in self.checkers
            if type(c) not in (StructuralDivergenceChecker, NameSimilarityChecker)
        ]

        for filename, _added_only in changed.items():
            base = os.path.basename(filename)

            # ── Linkage ───────────────────────────────────────────────
            items += self._linkage(base, filename, model)

            # ── Load full file from disk ───────────────────────────────
            # Try multiple path resolutions in order:
            #   1. project_dir / filename          (e.g. project/main.py)
            #   2. project_dir / basename          (e.g. project/main.py when diff has subdir)
            #   3. filename as absolute/relative   (e.g. ./main.py)
            # Fall back to added-lines-only if none exist on disk.
            full_source = None
            for candidate in [
                self.project_dir / filename,
                self.project_dir / base,
                Path(filename),
            ]:
                if candidate.exists():
                    try:
                        full_source = candidate.read_text(
                            encoding="utf-8", errors="replace"
                        )
                    except Exception:
                        pass
                    break

            if full_source is None:
                # File not on disk — SD and Naming cannot work without
                # the full file so skip those checkers for this file
                full_source = _added_only

            ## Diff-aware structural divergence and naming
            # SD and Naming need the full file, but only report pairs
            # where at least one block was touched by the diff.
            added_line_nos = set(
                DiffScopeAnalyser.added_lines(diff_text, filename).keys()
            )
            changed_names = self._changed_names(diff_text, filename)

            for checker in full_file_checkers:
                if isinstance(checker, StructuralDivergenceChecker):
                    raw = checker.check(full_source, base)
                else:
                    # NameSimilarityChecker: diff-aware + type-filtered
                    raw = checker.check_diff(full_source, base, changed_names)
                items += raw

            #  Scope-aware checkers
            analyser  = DiffScopeAnalyser(full_source, filename)
            fragments = analyser.scoped_sources(diff_text)

            if not fragments:
                continue

            seen_messages: set = set()

            for src_fragment, scope_label, formatting_only, line_offset in fragments:

                if formatting_only:
                    # Emit one INFO item and skip all checker runs
                    items.append(ChecklistItem(
                        category="formatting",
                        message=f"Formatting-only change in {base}",
                        detail=(
                            f"[scope: {scope_label}]\n"
                            f"This change is purely cosmetic (line splitting, "
                            f"indentation, trailing whitespace).\n"
                            f"No logic, identifiers, or values were modified."
                        ),
                    ))
                    continue

                for checker in scoped_checkers:
                    for item in checker.check(src_fragment, base):
                        # Translate fragment-relative line number to file line number
                        if item.line is not None:
                            item.line = item.line + line_offset
                        dedup_key = (item.category, item.message, item.line)
                        if dedup_key in seen_messages:
                            continue
                        seen_messages.add(dedup_key)
                        item.detail = f"[scope: {scope_label}]\n{item.detail}"
                        items.append(item)

        return self._static_loader.load() + _sort(items)

    def generate_from_files(self, filenames: list, should_ignore_test) -> list:
        model = self.dep_builder.build(str(self.project_dir), should_ignore_test)
        items = []
        for filename in filenames:
            if should_ignore_test:
                if "test" in filename:
                    continue
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
        return self._static_loader.load() + _sort(items)

    def generate_from_project(self, should_ignore_test) -> list:
        """Scan every Python file in the project - no diff or file list required."""
        model = self.dep_builder.build(str(self.project_dir), should_ignore_test)
        return self.generate_from_files(model.python_files, should_ignore_test)

    @staticmethod
    def _changed_names(diff_text: str, filename: str) -> set:
        """
        Extract every identifier that appears in the added or removed
        lines of the diff for this file.
        """
        names: set = set()
        in_file = False
        for line in diff_text.splitlines():
            if line.startswith("+++ b/") or line.startswith("+++ "):
                target = line[6:].strip() if line.startswith("+++ b/") \
                    else line[4:].strip()
                in_file = (
                        target == filename
                        or target.endswith("/" + filename)
                        or filename.endswith(target)
                )
                continue
            if not in_file:
                continue
            if line.startswith("@@") or line.startswith("---") \
                    or line.startswith("+++"):
                continue
            if line.startswith("+") or line.startswith("-"):
                for tok in re.findall(r'\b([A-Za-z_][A-Za-z0-9_]*)\b',
                                      line[1:]):
                    names.add(tok)
        return names

    @staticmethod
    def _item_touches_changed(item, changed_names: set) -> bool:
        """
        Return True if the checklist item mentions at least one name
        that appears in the diff.
        """
        if not changed_names:
            return False
        text = f"{item.message} {item.detail}"
        tokens = set(re.findall(r'\b([A-Za-z_][A-Za-z0-9_]*)\b', text))
        return bool(tokens & changed_names)
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
