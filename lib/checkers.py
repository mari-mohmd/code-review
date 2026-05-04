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
 Description: A set of checkers run on the AST of the target code
 Usage      : Supplementary file. see IntentCheck.py
===============================================================================
"""

import ast
import re
from difflib import SequenceMatcher
from typing import Optional

from .checklist_data import ChecklistItem


class LifecycleChecker:
    """
    Formal model:  LC(y) = (R_y, O_y, U_y)

      R_y  — resource handles declared in python file (y).
              Captured from TWO sources:

              (a) KNOWN resource constructors: open(), socket(), connect(),
                  urlopen(), mkstemp(), TemporaryFile(), etc.  These are
                  stdlib calls that always require explicit lifecycle management
                  regardless of whether the class is visible in the file.

              (b) ANY class whose constructor is called and whose class
                  definition implements __enter__ + __exit__ — detected
                  either from class definitions in the same file OR from
                  classes imported into the file (via import or from-import).
                  This covers user-defined context managers, third-party
                  library resources (e.g. requests.Session, sqlite3.Connection),
                  and any other class that signals managed lifecycle through
                  the context manager protocol.

              In both cases, if the call already appears as the context
              expression of a 'with' statement it goes straight into O_y.

      O_y  — handles properly released:
               r ∈ O_y  iff  bound inside a 'with' statement
                             OR an explicit release method is called on it
                             (.close() / .shutdown() / .stop() / .release()
                              / .terminate() / .disconnect() / .__exit__())

      U_y  — handles assigned but never subsequently read (dead resource).

    Lifecycle completeness score:
               LC_score(y) = |O_y| / |R_y|        (1.0 = fully managed)

    Otherwise raise a checklist item
    """

    # Stdlib resource constructors (always tracked, no class def needed)
    RESOURCE_CALLS = {
        "open", "socket", "connect", "urlopen",
        "mkstemp", "TemporaryFile", "NamedTemporaryFile", "SpooledTemporaryFile",
    }

    #  Methods that constitute an explicit release
    RELEASE_METHODS = {
        "close", "shutdown", "terminate", "release",
        "stop", "disconnect", "detach", "__exit__",
    }

    def _cm_class_names(self, tree) -> set[str]:
        """
        Return all class names visible in this file that implement the
        context manager protocol (__enter__ AND __exit__).

        Two sources are checked:

        1. Classes DEFINED in this file — walk all ClassDef nodes and
           collect those with both __enter__ and __exit__ methods.

        2. Classes IMPORTED into this file — for every import statement,
           record the local name.  We cannot inspect the imported module's
           source at analysis time, so we use a heuristic: any name that
           is imported AND subsequently called with the result assigned to
           a variable AND that variable is also used as a 'with' target
           elsewhere in the codebase is a likely context manager.

           A simpler and more reliable heuristic used here: if the file
           contains 'import X' or 'from Y import X', record X as a
           *candidate*.  Then, if X() appears bare (outside a 'with') and
           the file also contains at least one 'with X()' elsewhere, we
           know X is a context manager and can flag the bare usage.

           For the common case where the same class is used both ways in
           the same file this is exact.  For classes used only bare, we
           fall back to flagging all imported names that are called and
           whose local usage pattern matches resource-like assignment
           (single assignment, no subsequent mutation of the result).

        In practice the most reliable signal is source-local: if the class
        is defined in the same file with __enter__/__exit__, the detection
        is exact.  For imported classes the with-usage cross-reference
        provides a strong secondary signal with no false positives.
        """
        cm_names: set[str] = set()

        # 1. Classes defined in this file
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            methods = {
                n.name for n in ast.walk(node)
                if isinstance(n, ast.FunctionDef)
            }
            if "__enter__" in methods and "__exit__" in methods:
                cm_names.add(node.name)

        # 2. Imported names that appear as 'with X(...)' context exprs
        # If a name is used inside a 'with' statement anywhere in the file,
        # it IS a context manager — detect its bare usages as unmanaged.
        with_called: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.With):
                for item in node.items:
                    call_name = self._expr_call_name(item.context_expr)
                    if call_name:
                        with_called.add(call_name)

        # Collect all imported local names (bare or aliased)
        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_names.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported_names.add(alias.asname or alias.name)

        # Any imported name used inside a 'with' is confirmed as a CM
        cm_names |= imported_names & with_called

        return cm_names

    def _expr_call_name(self, expr) -> str:
        """
        Extract the constructor name from a context expression.
        Handles:  X()  ->  'X'
                  mod.X()  ->  'X'
                  X(args)  ->  'X'
        Returns '' if the expression is not a simple call.
        """
        if isinstance(expr, ast.Call):
            return self._call_name(expr)
        return ""

    def _with_managed_lines(self, tree) -> set[int]:
        """Lines of Call nodes that are context expressions of 'with' statements."""
        lines: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.With):
                for item in node.items:
                    for child in ast.walk(item.context_expr):
                        if isinstance(child, ast.Call):
                            ln = getattr(child, "lineno", None)
                            if ln:
                                lines.add(ln)
        return lines

    def _collect_resources(self, tree, cm_names: set[str],
                           with_lines: set[int]) -> dict:
        """
        Build R_y: variable_name -> (lineno, call_name, in_with)

        A variable is a resource if it is assigned from:
          • A call in RESOURCE_CALLS  (stdlib, always tracked), OR
          • A call to any name in cm_names  (any class with CM protocol)
        """
        resources: dict = {}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Assign)
                    and isinstance(node.value, ast.Call)):
                continue

            cn = self._call_name(node.value)
            if not cn:
                continue

            is_resource = cn in self.RESOURCE_CALLS or cn in cm_names
            if not is_resource:
                continue

            ln      = getattr(node, "lineno", 0)
            in_with = ln in with_lines

            for t in node.targets:
                if isinstance(t, ast.Name):
                    resources[t.id] = (ln, cn, in_with)

        return resources

    def _collect_closed(self, tree) -> set[str]:
        """Variables on which an explicit release method is called."""
        closed: set[str] = set()
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Expr)
                    and isinstance(node.value, ast.Call)):
                continue
            call = node.value
            if (isinstance(call.func, ast.Attribute)
                    and call.func.attr in self.RELEASE_METHODS
                    and isinstance(call.func.value, ast.Name)):
                closed.add(call.func.value.id)
        return closed

    def check(self, source: str, filename: str) -> list:
        items = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return items

        cm_names   = self._cm_class_names(tree)
        with_lines = self._with_managed_lines(tree)
        resources  = self._collect_resources(tree, cm_names, with_lines)

        closed  = self._collect_closed(tree)
        managed = {
            v for v, (ln, cn, iw) in resources.items()
            if iw or v in closed
        }
        unmanaged = {v: d for v, d in resources.items() if v not in managed}

        r_count  = len(resources)
        o_count  = len(managed)
        lc_score = o_count / r_count if r_count > 0 else 1.0

        # unmanaged resources
        for var, (ln, cn, _) in unmanaged.items():
            in_cm_names = cn in cm_names and cn not in self.RESOURCE_CALLS
            if in_cm_names:
                detail = (
                    f"'{cn}' at line {ln} implements the context manager protocol\n"
                    f"(__enter__ / __exit__) but '{var}' is assigned bare rather\n"
                    f"than used in a 'with' block.  The __exit__ teardown will not\n"
                    f"run unless an explicit release method is called.\n"
                    f"Prefer:  with {cn}(...) as {var}:\n"
                    f"             ...  (guarantees __exit__ runs even on exceptions)"
                )
            else:
                detail = (
                    f"Handle from '{cn}()' at line {ln} is never explicitly closed.\n"
                    f"Use 'with {cn}(...) as {var}:' or call '{var}.close()'."
                )
            items.append(ChecklistItem(
                category="lifecycle",
                message=f"Unmanaged resource '{var}' in {filename}",
                detail=detail,
                line=ln, score=lc_score,
            ))

        # Warnings: dead handles (U_y)
        for var, (ln, cn, _) in resources.items():
            load_count = sum(
                1 for node in ast.walk(tree)
                if isinstance(node, ast.Name)
                and node.id == var
                and isinstance(node.ctx, ast.Load)
            )
            if load_count == 0:
                items.append(ChecklistItem(
                    category="lifecycle",
                    message=f"Resource '{var}' created but never used in {filename}",
                    detail=(
                        f"'{cn}()' result assigned to '{var}' at line {ln} "
                        f"but '{var}' is never read after assignment.\n"
                        f"Verify intentionality — the resource may be leaking silently."
                    ),
                    line=ln, score=lc_score,
                ))

        # Info: LC score summary
        if r_count > 0 and lc_score < 1.0:
            items.append(ChecklistItem(
                category="lifecycle",
                message=f"Lifecycle completeness: {lc_score:.0%} in {filename}",
                detail=(
                    f"LC_score = |O| / |R| = {o_count} / {r_count} = {lc_score:.2f}\n"
                    f"  R (declared resources): {list(resources)}\n"
                    f"  O (properly managed):   {list(managed)}\n"
                    f"  Unmanaged:              {list(unmanaged)}"
                ),
                score=lc_score,
            ))

        return items

    @staticmethod
    def _call_name(node: ast.Call) -> str:
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            return node.func.attr
        return ""
# ------------------------------------------------------------------------------------------------

class NameSimilarityChecker:
    """
    Detects naming inconsistencies such as user_id vs userId vs userID.

    Normalisation key: strip underscores, lowercase.
    A collision is flagged when:
      - ≥ 2 distinct surface forms share the same key
      - key length > 4 characters (avoids false positives on short names)
      - the key is not in the skip-list of common words that legitimately
        appear in multiple styles (e.g. 'True' vs 'true')
      - at least one variant contains an underscore OR mixed case
        (i.e. the variants represent genuinely different naming conventions,
        not just a local vs. imported spelling)
    """

    # Common Python builtins and keywords - normalised - that should never be
    # flagged even if two spellings collide (e.g. 'self' vs 'Self').
    _NAMING_SKIP = {
        "self", "cls", "true", "false", "none", "args", "kwargs",
        "print", "range", "list", "dict", "tuple", "type", "open",
        "input", "output", "result", "value", "values", "data",
        "error", "errors", "name", "names", "path", "paths", "item",
        "items", "index", "count", "total", "length", "size", "key",
        "keys", "node", "nodes", "text", "line", "lines", "file",
        "files", "base", "root", "tree", "test", "tests", "config",
        "source", "target", "temp", "tmp", "ret", "res", "resp",
    }

    # Name kind labels
    _VAR = "variable"
    _FUNC = "function"
    _CLASS = "class"

    def _collect(self, tree) -> dict:
        """
        Return {normalised_key: [(surface_name, lineno, kind), ...]}
        collecting only user-defined names with their kind tag.
        """
        names: dict = {}

        for node in ast.walk(tree):
            candidates = []

            if isinstance(node, ast.arg):
                candidates.append((node.arg, node.lineno, self._VAR))

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                candidates.append((node.name, node.lineno, self._FUNC))

            elif isinstance(node, ast.ClassDef):
                candidates.append((node.name, node.lineno, self._CLASS))

            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        candidates.append((t.id, node.lineno, self._VAR))

            for name, ln, kind in candidates:
                if len(name) <= 2:
                    continue
                key = re.sub(r"_", "", name).lower()
                names.setdefault(key, []).append((name, ln, kind))

        return names

    def _build_items(self, names: dict, filename: str,
                     diff_names: set = None) -> list:
        """
        Compare collected names and emit checklist items.

        diff_names — if provided, at least one surface name in a flagged
                     pair must appear in this set (diff-aware mode).
        """
        items = []
        reported: set = set()

        for key, entries in names.items():
            # Group by kind — only compare within the same kind
            by_kind: dict = {}
            for name, ln, kind in entries:
                by_kind.setdefault(kind, []).append((name, ln))

            for kind, kind_entries in by_kind.items():
                unique = list(dict.fromkeys(e[0] for e in kind_entries))
                if len(unique) < 2:
                    continue
                if len(key) <= 4:
                    continue
                if key in self._NAMING_SKIP:
                    continue
                has_style_diff = any(
                    "_" in v or (v != v.lower() and v != v.upper())
                    for v in unique
                )
                if not has_style_diff:
                    continue

                frozen = frozenset(unique)
                if frozen in reported:
                    continue

                # Diff-aware gate: skip if neither name was in the diff
                if diff_names is not None:
                    if not any(n in diff_names for n in unique):
                        continue

                reported.add(frozen)
                ln = next((e[1] for e in kind_entries if e[1]), None)
                items.append(ChecklistItem(
                    category="naming",
                    message=f"Name inconsistency ({kind}) in {filename}",
                    detail=(
                        f"Did you mean '{unique[0]}' or '{unique[1]}'?\n"
                        f"Both are {kind} names with the same normalised key "
                        f"'{key}'.\n"
                        f"Found {len(unique)} variant(s): {', '.join(unique)}"
                    ),
                    line=ln,
                ))
        return items

    def check(self, source: str, filename: str) -> list:
        """Full-file mode."""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []
        return self._build_items(self._collect(tree), filename,
                                 diff_names=None)

    def check_diff(self, source: str, filename: str,
                   diff_names: set) -> list:
        """
        Diff-aware mode: only report pairs where at least one name
        appears in the set of identifiers touched by the diff.
        """
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []
        return self._build_items(self._collect(tree), filename,
                                 diff_names=diff_names)


# ------------------------------------------------------------------------------------------------

class DeadImportChecker:
    """
    Formal model:  DI(y) = I_y ∖ U_y

      I_y  - set of names introduced by import statements in file y
      U_y  - set of names actually referenced (Load context) anywhere in y

    An import is dead if its bound name never appears as a Load node.
    Only top-level simple names are tracked (not 'import a.b as c' aliases
    where 'a' is the bound name but 'a.b' is the usage pattern - those are
    common and should not be flagged).

    Severity: INFO (the import may be intentional for side effects).
    """

    # Modules commonly imported for side effects - never flag these
    _SIDE_EFFECT = {"__future__", "antigravity", "this", "readline",
                    "sitecustomize", "usercustomize", "logging", "warnings"}

    def check(self, source: str, filename: str) -> list:
        items = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return items

        # Collect imported names: (bound_name, module, lineno)
        imported: list[tuple[str, str, int]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    bound = alias.asname if alias.asname else alias.name.split(".")[0]
                    mod = alias.name
                    if mod.split(".")[0] not in self._SIDE_EFFECT:
                        imported.append((bound, mod, node.lineno))
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod.split(".")[0] not in self._SIDE_EFFECT:
                    for alias in node.names:
                        if alias.name == "*":
                            continue  # star imports always assumed used
                        bound = alias.asname if alias.asname else alias.name
                        imported.append((bound, f"{mod}.{alias.name}", node.lineno))

        if not imported:
            return items

        # Collect all Load-context name references in the file
        used: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                used.add(node.id)
            # Attribute access: os.path -> 'os' is used
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                used.add(node.value.id)

        for bound, mod, ln in imported:
            if bound not in used:
                items.append(ChecklistItem(
                    category="deadimport",
                    message=f"Unused import '{bound}' in {filename}",
                    detail=(f"'{mod}' imported at line {ln} but '{bound}' is never referenced.\n"
                            f"Remove if not needed, or add a comment if imported for side effects."),
                    line=ln,
                ))
        return items

# ------------------------------------------------------------------------------------------------

class MagicNumberChecker:
    """
    Detects bare numeric literals used directly in expressions - "magic numbers"
    - whose meaning is not self-evident from context.

    A literal is flagged when:
      - It is an integer or float constant
      - It is NOT 0, 1, -1, 2, or 100 (universally understood sentinels)
      - It is NOT the sole value in a simple assignment  (x = 42  is fine;
        the name provides context)
      - It appears inside an expression: comparison, arithmetic, function call
        argument, return value, or list/dict/set literal

    In safety-critical code, magic numbers make intent opaque and make the
    code fragile to specification changes.  Named constants (MAX_RETRIES = 5)
    or enum members are the preferred alternative.

    Severity: INFO (not always wrong, but always worth a reviewer glance).
    """

    # Numeric values so common they carry obvious meaning everywhere
    _TRIVIAL = {0, 1, -1, 2, 100, 0.0, 1.0, -1.0, 0.5}

    def check(self, source: str, filename: str) -> list:
        items = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return items

        # Build set of line numbers that are simple named assignments (x = <literal>)
        simple_assign_lines: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                if (len(node.targets) == 1
                        and isinstance(node.targets[0], ast.Name)
                        and isinstance(node.value, ast.Constant)
                        and isinstance(node.value.value, (int, float))):
                    simple_assign_lines.add(node.lineno)
            # Also exempt augmented assignments: x += 1
            elif isinstance(node, ast.AugAssign):
                if isinstance(node.value, ast.Constant):
                    simple_assign_lines.add(node.lineno)

        seen_lines: set[int] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant):
                continue
            val = node.value
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                continue
            if val in self._TRIVIAL:
                continue
            ln = getattr(node, "lineno", None)
            if ln is None or ln in simple_assign_lines or ln in seen_lines:
                continue
            seen_lines.add(ln)
            items.append(ChecklistItem(
                category="magic",
                message=f"Magic number {val!r} in {filename}",
                detail=(f"Bare literal {val!r} - intent is not self-evident.\n"
                        f"Named constants improve readability and make future changes safer."),
                line=ln,
            ))
        return items

# ------------------------------------------------------------------------------------------------

class StructuralDivergenceChecker:
    """
    Formal model:  SD(B_i, B_j) = 2 * |LCS(tokens_i, tokens_j)| / (|B_i| + |B_j|)

      B_i, B_j  - normalised token sequences (AST unparse of body, docstring stripped)
      LCS       - longest common subsequence (Ratcliff/Obershelp via SequenceMatcher)
      2*        - normalises the result so the score sits between 0.0 and 1.0
      SD(·) ∈ [0, 1];  1.0 = structurally identical

    Thresholds:
      SD ≥ 0.95  -> WARNING  ("almost identical - is this intended?")

    Two comparison modes:

      check()          — compares all pairs in the file (used by --files / --all)
      check_diff()     — only compares pairs where at least one block was
                         touched by the diff (used by --diff). Pre-existing
                         pairs that are both outside the diff are suppressed.

    """

    WARN_THRESHOLD = 1
    INFO_THRESHOLD = 0.97
    NAMING_SKIP = ["__init__", "__str__", "__repr__"]

    def check(self, source: str, filename: str) -> list:
        items = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return items

        blocks = self._extract(tree)
        seen: set = set()

        for i, (na, ta, la, ka) in enumerate(blocks):
            for j, (nb, tb, lb, kb) in enumerate(blocks):
                if i >= j:
                    continue
                pair = (i, j)
                if pair in seen:
                    continue
                seen.add(pair)
                score = self._sd(ta, tb)
                if score >= self.WARN_THRESHOLD:
                    items.append(ChecklistItem(
                        category="structural",
                        message=f"Almost identical {ka}s in {filename}",
                        detail=(
                            f"SD({na}, {nb}) = {score:.2f}  "
                            f"'{na}' (line {la}) and '{nb}' (line {lb}) "
                            f"are {score*100:.0f}% structurally identical.\n"
                            f"These two blocks of code are almost identical - "
                            f"is this the intended design?\n"
                            f"Consider extracting shared logic into a single reusable function."
                        ),
                        line=la, score=score,
                    ))
                elif score >= self.INFO_THRESHOLD:
                    items.append(ChecklistItem(
                        category="structural",
                        message=f"High structural similarity in {filename}",
                        detail=(
                            f"SD({na}, {nb}) = {score:.2f}  "
                            f"(info threshold ≥ {self.INFO_THRESHOLD})\n"
                            f"'{na}' (line {la}) and '{nb}' (line {lb}) "
                            f"share {score*100:.0f}% structural similarity.\n"
                            f"Verify whether the divergence is intentional."
                        ),
                        line=la, score=score,
                    ))
        return items

    def _extract(self, tree):
        blocks = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                if node.name not in self.NAMING_SKIP:
                    blocks.append((node.name, self._normalise(node), node.lineno, kind))
        return blocks

    @staticmethod
    def _normalise(node) -> str:
        body = list(node.body) if hasattr(node, "body") else []
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]
        try:
            return "\n".join(ast.unparse(s) for s in body)
        except Exception:
            return ""

    @staticmethod
    def _sd(a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        return SequenceMatcher(None, a, b).ratio()

# ------------------------------------------------------------------------------------------------

class InjectionRiskChecker:
    RISKY = {"eval", "exec", "compile", "__import__", "pickle", "loads"}

    def check(self, source: str, filename: str) -> list:
        items = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return items
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = None
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                if name in self.RISKY:
                    items.append(ChecklistItem(
                        category="injection",
                        message=f"Runtime evaluation risk in {filename}",
                        detail=(f"Call to '{name}()' at line {getattr(node,'lineno','?')} "
                                f"introduces potential code injection or deserialisation risk. \n"
                                f"Verify that no potential security risks are introduced here"),
                        line=getattr(node, "lineno", None),
                    ))
        return items

# ------------------------------------------------------------------------------------------------

class ConcurrencyChecker:
    """
    Detects concurrency and subprocess constructs that require explicit
    reviewer scrutiny for thread-safety, deadlocks, and process isolation.

    Two categories are checked:

    1. CONCURRENCY constructs - threading, multiprocessing, asyncio primitives.
       Flagged as INFO: correct usage is common, but the reviewer must verify
       absence of data races, deadlocks, and improper shared-state access.

    2. SUBPROCESS constructs - subprocess.run(), subprocess.Popen(),
       subprocess.call(), subprocess.check_output(), os.fork(), os.exec*().
       Flagged as WARNING: spawning child processes introduces additional
       concerns beyond those caught by the ShellInjectionChecker:
         * Resource leaks if the child process is not properly waited on
         * Signal-handling interactions with the parent process
         * File-descriptor inheritance (stdout/stderr left open)
         * Blocking behaviour when communicate() / wait() is absent
         * Race conditions between parent and child on shared resources

    The two categories carry different severities because subprocess usage
    introduces process-level resource and synchronisation risks that are
    architecturally more impactful than typical intra-process concurrency.
    """

    # Intra-process concurrency primitives
    _CONCURRENCY = {
        "Thread", "ThreadPoolExecutor",
        "Process", "ProcessPoolExecutor",
        "asyncio",
        "Lock", "RLock", "Semaphore", "BoundedSemaphore",
        "Event", "Condition", "Barrier", "Queue",
    }

    # Subprocess-spawning calls
    # These are attribute names (the right-hand side of subprocess.<name>)
    # and also bare names that resolve to subprocess functions when imported
    # with `from subprocess import ...`.
    _SUBPROCESS_ATTRS = {
        "run", "Popen", "call", "check_call",
        "check_output", "getoutput", "getstatusoutput",
    }
    # os-level process spawning (os.fork, os.execv, os.execve, os.spawnl, …)
    _OS_PROCESS_ATTRS = {
        "fork", "execv", "execve", "execvp", "execvpe",
        "spawnl", "spawnle", "spawnlp", "spawnlpe",
        "spawnv", "spawnve", "spawnvp", "spawnvpe",
    }

    # Detail templates
    _SUBPROCESS_DETAIL = (
        "Subprocess spawned via '{name}' at line {ln}.\n"
        "Review:\n"
        "  * Is the child process always waited on (communicate() / wait())\n"
        "    to prevent zombie processes?\n"
        "  * Are stdout/stderr explicitly handled or closed to prevent\n"
        "    file-descriptor leaks?\n"
        "  * Could a race condition exist between the parent and child on\n"
        "    any shared resource (files, sockets, signals)?\n"
        "  * Is shell=False? (or is shell=True justified and reviewed\n"
        "    by the ShellInjectionChecker)?"
    )

    _OS_FORK_DETAIL = (
        "Low-level process primitive '{name}' at line {ln}.\n"
        "Review:\n"
        "  * os.fork() duplicates file descriptors and threads - verify\n"
        "    that the child closes inherited resources it does not need.\n"
        "  * os.exec*() replaces the current process image - verify that\n"
        "    all open handles are closed or marked O_CLOEXEC beforehand.\n"
        "  * Consider subprocess.run() for higher-level, safer process control."
    )

    _CONCURRENCY_DETAIL = (
        "Concurrency construct '{name}' at line {ln}.\n"
        "Verify thread-safety and absence of deadlocks:\n"
        "  * Are all shared variables accessed under the appropriate lock?\n"
        "  * Is lock acquisition order consistent to prevent deadlock?\n"
        "  * Are daemon threads explicitly joined or their lifecycle managed?"
    )

    def _call_name(self, node: ast.Call):
        """Return (qualifier, attr) for a Call node, or (None, None)."""
        if isinstance(node.func, ast.Name):
            return (None, node.func.id)
        if isinstance(node.func, ast.Attribute):
            qual = None
            if isinstance(node.func.value, ast.Name):
                qual = node.func.value.id
            return (qual, node.func.attr)
        return (None, None)

    def check(self, source: str, filename: str) -> list:
        items = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return items

        seen: set[tuple] = set()  # deduplicate (category, line)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            qual, name = self._call_name(node)
            if name is None:
                continue

            ln = getattr(node, "lineno", "?")
            key = (name, ln)
            if key in seen:
                continue

            # subprocess.*
            is_subprocess_qual = qual in ("subprocess", "sp", "sub")
            is_subprocess_name = name in self._SUBPROCESS_ATTRS

            if is_subprocess_name and (is_subprocess_qual or qual is None):
                seen.add(key)
                items.append(ChecklistItem(
                    category="concurrency",
                    message=f"Subprocess spawned in {filename}",
                    detail=self._SUBPROCESS_DETAIL.format(name=name, ln=ln),
                    line=getattr(node, "lineno", None),
                ))
                continue

            # os.fork / os.exec* / os.spawn*
            is_os_qual = qual in ("os",)
            if is_os_qual and name in self._OS_PROCESS_ATTRS:
                seen.add(key)
                items.append(ChecklistItem(
                    category="concurrency",
                    message=f"Low-level process primitive in {filename}",
                    detail=self._OS_FORK_DETAIL.format(name=name, ln=ln),
                    line=getattr(node, "lineno", None),
                ))
                continue

            # threading / multiprocessing / asyncio primitives
            if name in self._CONCURRENCY:
                seen.add(key)
                items.append(ChecklistItem(
                    category="concurrency",
                    message=f"Concurrency construct in {filename}",
                    detail=self._CONCURRENCY_DETAIL.format(name=name, ln=ln),
                    line=getattr(node, "lineno", None),
                ))

        return items
# ------------------------------------------------------------------------------------------------

class InputChecker:
    """
    Detects calls to the built-in input() function and emits ONE checklist
    item per call site that consolidates all reviewer concerns:

      * Validation    - input() always returns str; type/injection risks
      * Blocking      - freezes event loops, async tasks, GUI threads
      * Encoding      - terminal locale mismatch -> UnicodeDecodeError / mojibake
      * Echo/secrecy  - plain-text echo; getpass.getpass() for secrets

    Severity escalates from INFO to WARNING if any secret-hint keyword is
    detected in the prompt string (password, token, key, pin, …).

    Detection covers:
      * input(...)           bare call (builtin)
      * builtins.input(...)  explicit module-qualified call
    """

    _SECRET_HINTS = {
        "password", "passwd", "pwd", "secret", "token",
        "api_key", "apikey", "key", "pin", "passphrase",
        "credential", "auth", "otp", "code",
    }

    def _is_input_call(self, node: ast.Call) -> bool:
        f = node.func
        if isinstance(f, ast.Name) and f.id == "input":
            return True
        if (isinstance(f, ast.Attribute)
                and f.attr == "input"
                and isinstance(f.value, ast.Name)
                and f.value.id == "builtins"):
            return True
        return False

    def _prompt_text(self, node: ast.Call) -> str:
        """Extract the prompt literal, or '' if dynamic/absent."""
        if not node.args:
            return ""
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
        return ""

    def _prompt_looks_secret(self, prompt: str) -> bool:
        lower = prompt.lower()
        return any(kw in lower for kw in self._SECRET_HINTS)

    def check(self, source: str, filename: str) -> list:
        items = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return items

        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and self._is_input_call(node)):
                continue

            ln     = getattr(node, "lineno", "?")
            prompt = self._prompt_text(node)
            is_secret = self._prompt_looks_secret(prompt)

            prompt_line = (
                f'  Prompt: "{prompt}"\n'
                if prompt else
                "  Prompt: (dynamic or absent - could not be statically extracted)\n"
            )
            secret_note = (
                f"  *** Prompt appears to request secret data - replace input() with\n"
                f"  *** getpass.getpass() which suppresses echo at the OS level.\n"
            ) if is_secret else ""

            detail = (
                f"Review:\n"
                f"  - Validation:  input() always returns a raw str.\n"
                f"        Has the value been validated before use?\n"
                f"        * Cast to expected type (int/float/…) inside try/except\n"
                f"          to catch ValueError / TypeError?\n"
                f"        * If passed to a shell command, SQL query, file path,\n"
                f"          or eval(), is it sanitised against injection?\n"
                f"        * Are length and character-set constraints enforced?\n"
                f"\n"
                f"  - Blocking:  input() blocks the calling thread indefinitely.\n"
                f"        Is there a risk of blocking behaviour here?\n"
                f"        * Reachable from an asyncio coroutine, a tkinter/Qt main\n"
                f"          thread, or a server request handler?\n"
                f"        * If so, delegate to a thread (loop.run_in_executor) or\n"
                f"          use an async readline (asyncio.StreamReader).\n"
                f"\n"
                f"  - Encoding:  input() decodes stdin via the terminal locale\n"
                f"        (sys.stdin.encoding: UTF-8 on Linux, cp1252 on Windows).\n"
                f"        Has a possible encoding issue been handled?\n"
                f"        * Non-ASCII prompt or input may cause UnicodeDecodeError\n"
                f"          or silent mojibake on mismatched terminals.\n"
                f"        * Consider try/except UnicodeDecodeError, or enforce\n"
                f"          PYTHONIOENCODING=utf-8 / sys.stdin.reconfigure().\n"
                f"\n"
                f"  - Echo:  characters typed are echoed in plain text.\n"
                f"        Ensure no secret data is entered here.\n"
                f"{secret_note}"
                f"        * For passwords, tokens, PINs or any secret use\n"
                f"          getpass.getpass() to suppress terminal echo.\n"
                f"        * Verify the terminal session is not being recorded\n"
                f"          (CI log capture, 'script' command, etc.)."
            )

            items.append(ChecklistItem(
                category="input",
                message=f"input() call - review required in {filename}",
                detail=detail,
                line=getattr(node, "lineno", None),
            ))

        return items
# ------------------------------------------------------------------------------------------------

class HardcodedPathChecker:
    """
    Detects absolute paths hardcoded as string literals in the AST.

    A path string p is flagged when:
      * p starts with a Unix absolute pattern (/Users/, /home/, /tmp/, /var/, /etc/)
      * p matches a Windows drive path (C:\\ or C:/)
      * p is passed to a filesystem call (os.makedirs, os.mkdir, open, shutil.*)
        OR appears as any string literal ≥ 3 path components long

    Recommended alternatives: os.path.join(), pathlib.Path(),
    environment variables, or a configuration file.
    """

    _ABS_UNIX = re.compile(r"^(/Users/|/home/|/root/|/tmp/|/var/|/etc/|/opt/|/srv/)")
    _ABS_WIN  = re.compile(r"^[A-Za-z]:[/\\]")
    _MULTI_COMPONENT = re.compile(r"^/[^/]+/[^/]+/")  # ≥ 3 components

    def check(self, source: str, filename: str) -> list:
        items = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return items

        seen_lines: set[int] = set()
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            val = node.value
            if not (self._ABS_UNIX.match(val) or self._ABS_WIN.match(val)
                    or self._MULTI_COMPONENT.match(val)):
                continue
            ln = getattr(node, "lineno", None)
            if ln in seen_lines:
                continue
            seen_lines.add(ln)
            items.append(ChecklistItem(
                category="portability",
                message=f"Hardcoded absolute path in {filename}",
                detail=(
                    f"Path '{val}' at line {ln} is hardcoded and maybe machine specific.\n"
                    f"Review this path to ensure it has been defined according to the intended design.\n"
                ),
                line=ln,
            ))
        return items

# ------------------------------------------------------------------------------------------------

class ShellInjectionChecker:
    """
    Detects calls to os.system(), os.popen(), subprocess with shell=True,
    and similar shell-spawning patterns.

    Risks:
      * Shell injection when any part of the command is externally influenced
      * Non-portable shell commands (touch, mkdir, rm) that embed hardcoded paths
      * No structured error handling (exit codes silently ignored in os.system)

    Preferred alternative: subprocess.run([...], check=True) with an explicit
    argument list, which avoids shell expansion entirely.
    """

    SHELL_CALLS = {"system", "popen", "getoutput", "getstatusoutput",
                   "spawnl", "spawnle", "spawnlp", "spawnlpe",
                   "spawnv", "spawnve", "spawnvp", "spawnvpe"}

    def check(self, source: str, filename: str) -> list:
        items = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return items

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            name = None
            if isinstance(node.func, ast.Attribute):
                name = node.func.attr
            elif isinstance(node.func, ast.Name):
                name = node.func.id

            if name in self.SHELL_CALLS:
                cmd_preview = ""
                if node.args and isinstance(node.args[0], ast.Constant):
                    cmd_preview = f"\n  Command: '{node.args[0].value}'"
                ln = getattr(node, "lineno", None)
                items.append(ChecklistItem(
                    category="shell",
                    message=f"Shell command execution in {filename}",
                    detail=(
                        f"Call to '{name}()' at line {ln} spawns a shell process.{cmd_preview}\n"
                        f"Risks: shell injection, non-portable commands, silent error suppression.\n"
                        f"Prefer subprocess.run([...], check=True) with an explicit argument list."
                    ),
                    line=ln,
                ))

            if name in ("call", "run", "Popen", "check_output", "check_call"):
                for kw in node.keywords:
                    if kw.arg == "shell" and isinstance(kw.value, ast.Constant) \
                            and kw.value.value is True:
                        ln = getattr(node, "lineno", None)
                        items.append(ChecklistItem(
                            category="shell",
                            message=f"subprocess with shell=True in {filename}",
                            detail=(
                                f"'{name}(..., shell=True)' at line {ln} enables shell expansion (e.g command injection).\n"
                                f"Pass a list of arguments instead and remove shell=True."
                            ),
                            line=ln,
                        ))
        return items

# ------------------------------------------------------------------------------------------------

class PathCoherenceChecker:
    """
    Detects mismatches between paths passed to directory-creation calls
    (os.makedirs, os.mkdir, Path.mkdir) and paths passed to file-operation
    calls (open, os.system, subprocess, shutil.*) within the same file.

    Algorithm - Longest Common Path Prefix (LCPP) divergence:

      Given a set of directory paths D = {d₁, d₂, …} and a set of file
      paths F = {f₁, f₂, …} extracted from the AST:

      For each pair (dᵢ, fⱼ):
        1.  Normalise both to POSIX component lists:
              C(p) = p.split('/')  stripped of empty parts
        2.  Compute LCPP length:
              lcpp(dᵢ, fⱼ) = |longest common prefix of C(dᵢ) and C(fⱼ)|
        3.  Divergence score DS = 1 − lcpp / max(|C(dᵢ)|, |C(fⱼ)|)
              DS = 0.0  ->  identical paths  (no flag)
              DS ≤ threshold_info  ->  INFO  (file is inside the directory)
              DS > threshold_warn  ->  WARNING  (file is *outside* the directory)

      A file path fⱼ is "expected inside" dᵢ when C(dᵢ) is a prefix of C(fⱼ).
      If this is NOT the case, and the paths share a common root (lcpp ≥ 1),
      we emit a WARNING: the code creates a directory but then operates on a
      file that is NOT in that directory - almost certainly a copy-paste or
      rename error.

    Example (the motivating bug):
      os.makedirs("/Users/mohammadmari/Downloads/logs")   -> D component: logs
      os.system("touch /Users/mohammadmari/Downloads/x.log") -> file not under logs/

      C(dir)  = ['Users','mohammadmari','Downloads','logs']
      C(file) = ['Users','mohammadmari','Downloads','x.log']
      LCPP = 3  ('Users','mohammadmari','Downloads' match)
      The 4th component differs: 'logs' vs 'x.log' - file is a *sibling*
      of the directory, not a child.  -> WARNING.
    """

    # Calls that create directories
    _DIR_CALLS  = {"makedirs", "mkdir"}
    # Calls whose first positional argument is a file path
    _FILE_CALLS = {"open", "system", "popen", "getoutput", "getstatusoutput",
                   "copyfile", "copy", "copy2", "move", "rename"}

    # If file IS under the dir but the shared prefix is short (< 2 components),
    # emit INFO rather than silence - it may still be accidental.
    _WARN_NOT_CHILD  = True   # always warn when file is NOT under the dir

    @staticmethod
    def _components(path: str) -> list[str]:
        """Split a path into normalised components, ignoring empty parts."""
        import posixpath
        # Normalise Windows separators
        p = path.replace("\\", "/")
        parts = [c for c in p.split("/") if c]
        return parts

    @staticmethod
    def _lcpp(a: list, b: list) -> int:
        """Longest Common Path Prefix length."""
        n = 0
        for x, y in zip(a, b):
            if x == y:
                n += 1
            else:
                break
        return n

    def _extract_paths(self, tree) -> tuple[list, list]:
        """Return (dir_paths, file_paths) as lists of (path_str, lineno)."""
        dir_paths  = []
        file_paths = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            # Resolve function name
            name = None
            if isinstance(node.func, ast.Attribute):
                name = node.func.attr
            elif isinstance(node.func, ast.Name):
                name = node.func.id

            if name is None:
                continue

            # Extract first positional string argument
            path_val = None
            if node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str):
                path_val = node.args[0].value

            if path_val is None:
                continue

            ln = getattr(node, "lineno", None)

            if name in self._DIR_CALLS:
                dir_paths.append((path_val, ln))
            elif name in self._FILE_CALLS:
                # For os.system / os.popen, the argument is a shell command -
                # try to extract the last quoted or unquoted path-like token
                if name in ("system", "popen", "getoutput", "getstatusoutput"):
                    # Pull the last space-separated token that looks like a path
                    tokens = path_val.split()
                    for tok in reversed(tokens):
                        # strip common shell quoting
                        tok = tok.strip("'\"")
                        if "/" in tok or "\\" in tok:
                            file_paths.append((tok, ln))
                            break
                    # If the whole string looks like a path, use it directly
                    else:
                        if "/" in path_val or "\\" in path_val:
                            file_paths.append((path_val, ln))
                else:
                    file_paths.append((path_val, ln))

        return dir_paths, file_paths

    def check(self, source: str, filename: str) -> list:
        items = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return items

        dir_paths, file_paths = self._extract_paths(tree)

        if not dir_paths or not file_paths:
            return items

        reported: set = set()

        for dir_val, dir_ln in dir_paths:
            dc = self._components(dir_val)
            if len(dc) < 2:
                continue  # too short to be meaningful

            for file_val, file_ln in file_paths:
                fc = self._components(file_val)
                if len(fc) < 2:
                    continue

                lc = self._lcpp(dc, fc)
                if lc == 0:
                    continue  # completely unrelated paths - skip

                # Is the file path a child of the directory?
                file_is_child = (fc[:len(dc)] == dc)

                if file_is_child:
                    continue  # correct - file lives inside the directory

                # File is NOT inside the directory, but shares a common root
                # Compute what the file's path *would be* if it were inside
                suggested = dir_val.rstrip("/") + "/" + fc[-1]

                pair_key = (dir_val, file_val)
                if pair_key in reported:
                    continue
                reported.add(pair_key)

                # Show the divergence point
                if lc < len(dc):
                    dir_diverges_at  = dc[lc] if lc < len(dc)  else "(end)"
                    file_diverges_at = fc[lc] if lc < len(fc) else "(end)"
                else:
                    dir_diverges_at  = "(end)"
                    file_diverges_at = fc[lc] if lc < len(fc) else "(end)"

                shared = "/" + "/".join(dc[:lc]) if lc else "(none)"

                items.append(ChecklistItem(
                    category="pathcoherence",
                    message=f"Directory/file path mismatch in {filename}",
                    detail=(
                        f"A directory is created at:  '{dir_val}'  (line {dir_ln})\n"
                        f"But a file is operated on:  '{file_val}'  (line {file_ln})\n"
                        f"\n"
                        f"  Shared prefix:  {shared}\n"
                        f"  Directory ends: …/{dir_diverges_at}\n"
                        f"  File ends:      …/{file_diverges_at}\n"
                        f"\n"
                        f"The file is a SIBLING of the directory, not inside it.\n"
                        f"If the file should live inside '{dir_val}/', consider:\n"
                        f"  -> '{suggested}'"
                    ),
                    line=file_ln,
                ))

        return items