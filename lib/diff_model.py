"""
===============================================================================
 Project    : A Lightweight Methodology for Verifying Intended
                       Logic During Code Review
 File       : diff_model.py
 Author(s)  : Mohammad Mari, Lian Wen
 Affiliation: School of ICT, Griffith University
 License    : MIT License (see LICENSE file for details)
 Description: Hunk-level model of a unified diff.

   * splits a diff into per-file hunks, keeping context so that old- and
     new-side text can be compared in order (detects moved lines);
   * relocates hunks whose line numbers are stale (as `patch` does);
   * reconstructs the pre-change source of a file;
   * classifies every hunk as
        cosmetic  - token streams identical (whitespace / layout only)
        noncode   - only comments, blank lines or docstrings changed
        code      - anything else
     so that a function is only treated as "formatting-only" when every
     hunk touching it is cosmetic.
===============================================================================
"""
import ast
import io
import keyword
import re
import textwrap
import tokenize
from dataclasses import dataclass, field

_HUNK_RE = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
# INDENT/DEDENT are kept: indentation is syntax in Python, so re-indenting a
# block into an `if` is a logic change, not a layout change.
_SKIP_TOKENS = {tokenize.NL, tokenize.NEWLINE, tokenize.ENDMARKER, tokenize.ENCODING}
_KEYWORDS = set(keyword.kwlist) | {"self", "cls", "True", "False", "None"}


@dataclass
class Hunk:
    old_start: int
    new_start: int
    old_lines: list = field(default_factory=list)   # context + removed, in order
    new_lines: list = field(default_factory=list)   # context + added, in order
    added: dict = field(default_factory=dict)       # new line no -> text
    removed: dict = field(default_factory=dict)     # old line no -> text
    del_points: list = field(default_factory=list)  # new line no *before which* lines were removed
    kind: str = "code"


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------
def split_files(diff_text: str) -> dict:
    """Return {new_path: [body lines]} for every file in a unified diff.
    Deleted files (+++ /dev/null) are omitted."""
    files, cur = {}, None
    for line in diff_text.splitlines():
        if line.startswith("diff --git") or line.startswith("--- "):
            continue
        if line.startswith("+++ "):
            path = line[4:].strip().split("\t")[0]
            if path == "/dev/null":
                cur = None
                continue
            if path.startswith("b/"):
                path = path[2:]
            cur = files.setdefault(path, [])
            continue
        if cur is not None:
            cur.append(line)
    return files


def parse_hunks(body: list) -> list:
    hunks, cur, o, n = [], None, 0, 0
    for line in body:
        if line.startswith("@@"):
            m = _HUNK_RE.match(line)
            if not m:
                cur = None
                continue
            cur = Hunk(int(m.group(1)), int(m.group(3)))
            o, n = cur.old_start, cur.new_start
            hunks.append(cur)
            continue
        if cur is None or line.startswith("\\"):
            continue
        tag, text = (line[:1], line[1:]) if line else (" ", "")
        if tag == "+":
            cur.new_lines.append(text)
            cur.added[n] = text
            n += 1
        elif tag == "-":
            cur.old_lines.append(text)
            cur.removed[o] = text
            if not cur.del_points or cur.del_points[-1] != n:
                cur.del_points.append(n)
            o += 1
        elif tag == " ":
            cur.old_lines.append(text)
            cur.new_lines.append(text)
            o += 1
            n += 1
        # any other line (e.g. "index ...", "new file mode") is ignored
    return hunks


def relocate(hunks: list, new_source: str) -> list:
    """If a hunk's new-side text is not found at its stated position in the
    file on disk, search for it (exact match) and shift the hunk.  Hunks that
    cannot be located are left unchanged."""
    def fuzzy(l):
        return " ".join(l.split("#", 1)[0].split())

    exact = [l.rstrip() for l in new_source.splitlines()]
    loose = [fuzzy(l) for l in new_source.splitlines()]
    for h in hunks:
        block = [l.rstrip() for l in h.new_lines]
        if not block:
            continue
        s = h.new_start - 1
        if exact[s:s + len(block)] == block:
            continue
        hits = [i for i in range(len(exact) - len(block) + 1)
                if exact[i:i + len(block)] == block]
        if not hits:   # tolerate comment / whitespace drift, like `patch` fuzz
            fb = [fuzzy(l) for l in block]
            hits = [i for i in range(len(loose) - len(fb) + 1)
                    if loose[i:i + len(fb)] == fb]
        if not hits:
            continue
        best = min(hits, key=lambda i: abs(i - s))
        shift = best - s
        h.new_start += shift
        h.added = {k + shift: v for k, v in h.added.items()}
        h.del_points = [p + shift for p in h.del_points]
    return hunks


def reconstruct_old(new_source: str, hunks: list) -> str:
    """Rebuild the pre-change file by replacing each hunk's new-side text
    with its old-side text (processing bottom-up)."""
    lines = new_source.splitlines()
    for h in sorted(hunks, key=lambda h: h.new_start, reverse=True):
        s = h.new_start - 1 if h.new_lines else h.new_start
        lines[s:s + len(h.new_lines)] = h.old_lines
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------
def string_statement_lines(tree) -> set:
    """Line numbers covered by bare string statements (docstrings and
    string 'comments')."""
    spans = set()
    if tree is None:
        return spans
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            spans.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return spans


def is_comment_or_blank(text: str) -> bool:
    s = text.strip()
    return not s or s.startswith("#")


def _tokens(lines: list):
    text = textwrap.dedent("\n".join(lines))
    try:
        out = []
        for t in tokenize.generate_tokens(io.StringIO(text + "\n").readline):
            if t.type in _SKIP_TOKENS:
                continue
            s = t.string
            if t.type == tokenize.COMMENT:
                s = " ".join(s.split())
            elif t.type == tokenize.STRING:
                s = "\n".join(part.rstrip() for part in s.split("\n"))
            out.append((t.type, s))
        return out
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # fragment cannot be tokenised on its own: keep each line's relative
        # indentation so that re-indentation is never mistaken for layout
        # (indentation only matters at the start of a statement, not on
        #  continuation lines inside brackets or after a backslash)
        out, depth, cont = [], 0, False
        for line in text.splitlines():
            if not line.strip():
                continue
            starts_stmt = depth == 0 and not cont
            indent = len(line) - len(line.lstrip()) if starts_stmt else None
            out.append((indent, " ".join(line.split())))
            code = re.sub(r"\"(\\.|[^\"\\])*\"|'(\\.|[^'\\])*'", "", line).split("#", 1)[0]
            depth = max(0, depth + sum(code.count(c) for c in "([{") - sum(code.count(c) for c in ")]}"))
            cont = code.rstrip().endswith("\\")
        return out


def classify_hunk(h: Hunk, new_doc: set, old_doc: set) -> str:
    if not h.added and not h.removed:
        return "cosmetic"
    if _tokens(h.old_lines) == _tokens(h.new_lines):
        return "cosmetic"
    if all(is_comment_or_blank(t) or ln in new_doc for ln, t in h.added.items()) and \
            all(is_comment_or_blank(t) or ln in old_doc for ln, t in h.removed.items()):
        return "noncode"
    return "code"


def code_identifiers(text: str) -> set:
    """Identifiers on a line of code, ignoring string literals and comments."""
    s = re.sub(r"('''|\"\"\").*?(\1|$)", " ", text)
    s = re.sub(r"\"(\\.|[^\"\\])*\"|'(\\.|[^'\\])*'", " ", s)
    s = s.split("#", 1)[0]
    return set(re.findall(r"\b[A-Za-z_]\w*\b", s)) - _KEYWORDS


# --------------------------------------------------------------------------
# AST safety net
# --------------------------------------------------------------------------
def _strip_docs(node) -> str:
    """ast.dump of `node` with docstrings / bare string statements removed."""
    import copy
    node = copy.deepcopy(node)
    for n in ast.walk(node):
        body = getattr(n, "body", None)
        if isinstance(body, list):
            kept = [s for s in body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
                                            and isinstance(s.value.value, str))]
            n.body = kept or [ast.Pass()]
    return ast.dump(node)


def _qualified_scopes(tree) -> dict:
    """{qualified name: node} for every function / class, e.g. 'A.f'."""
    out = {}

    def walk(node, prefix):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                q = f"{prefix}.{ch.name}" if prefix else ch.name
                out.setdefault(q, ch)
                walk(ch, q)
            else:
                walk(ch, prefix)
    walk(tree, "")
    return out


def _innermost(scopes: dict, lines: list):
    best = None
    for q, n in scopes.items():
        start = min([n.lineno] + [d.lineno for d in getattr(n, "decorator_list", [])])
        end = getattr(n, "end_lineno", n.lineno)
        if all(start <= l <= end for l in lines):
            if best is None or n.lineno > scopes[best].lineno:
                best = q
    return best


def confirm_non_functional(hunks: list, tree, old_tree) -> None:
    """Demote 'cosmetic'/'noncode' hunks to 'code' unless the AST proves the
    enclosing scope is unchanged.  Errs on the side of 'code'."""
    if old_tree is None:
        for h in hunks:
            h.kind = "code"
        return
    if _strip_docs(tree) == _strip_docs(old_tree):
        return  # whole file unchanged apart from layout/comments/docstrings
    new_scopes, old_scopes = _qualified_scopes(tree), _qualified_scopes(old_tree)
    for h in hunks:
        if h.kind == "code":
            continue
        lines = list(h.added) or [p for p in h.del_points if p > 0]
        q = _innermost(new_scopes, lines) if lines else None
        if q is None or q not in old_scopes or \
                _strip_docs(new_scopes[q]) != _strip_docs(old_scopes[q]):
            h.kind = "code"
