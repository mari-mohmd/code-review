"""Hunk-level verification of 'Formatting-only change' items.

For each item, collect every diff hunk whose added lines fall inside the
reported scope (function/class line range in the new file, or the single
reported line).  The claim is TRUE iff, for all those hunks, the Python token
stream of the removed text equals that of the added text (whitespace,
NL/INDENT/DEDENT ignored; comments and strings compared)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import EVAL, WORK, TOOL  # noqa: E402
import ast
import io
import json
import re
import subprocess
import tokenize

REPOS = {"dk": f"{WORK}/dronekit-python",
         "pp": f"{WORK}/pandapower"}
SKIP = {tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT,
        tokenize.ENDMARKER, tokenize.ENCODING}


def toks(text):
    import textwrap
    text = textwrap.dedent(text)
    try:
        return [(t.type, t.string) for t in
                tokenize.generate_tokens(io.StringIO(text + "\n").readline)
                if t.type not in SKIP]
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # fall back to whitespace-insensitive text
        return " ".join(text.split())


def hunks(diff, path):
    """Yield (new_start_line, added_linenos, added_text, removed_text)."""
    out, cur, in_file, nl = [], None, False, 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            in_file = line[6:].strip() == path
            continue
        if line.startswith("--- ") or line.startswith("diff "):
            continue
        if not in_file:
            continue
        if line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            nl = int(m.group(1)) - 1
            cur = {"added_ln": [], "add": [], "rem": []}
            out.append(cur)
            continue
        if cur is None:
            continue
        if line.startswith("+"):
            nl += 1
            cur["added_ln"].append(nl); cur["add"].append(line[1:])
        elif line.startswith("-"):
            cur["rem"].append(line[1:])
        else:
            nl += 1
    return out


def git(repo, *a):
    return subprocess.run(["git", "-C", repo, *a], capture_output=True,
                          text=True, errors="replace").stdout


def scope_range(src, kind, name):
    try:
        tree = ast.parse(src)
    except SyntaxError:
        # python2 file: approximate by indentation from the def line
        lines = src.splitlines()
        kw = "class" if kind == "class" else "def"
        for i, l in enumerate(lines):
            if re.match(rf"\s*{kw}\s+{name}\b", l):
                ind = len(l) - len(l.lstrip())
                j = i + 1
                while j < len(lines) and (not lines[j].strip() or
                                          len(lines[j]) - len(lines[j].lstrip()) > ind):
                    j += 1
                return i + 1, j
        return None
    for n in ast.walk(tree):
        ok = (kind == "class" and isinstance(n, ast.ClassDef)) or \
             (kind != "class" and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
        if ok and n.name == name:
            return n.lineno, n.end_lineno
    return None


out = []
for proj in ("dk", "pp"):
    rows = json.load(open(f"{EVAL}/{proj}_items.json"))
    raw = json.load(open(f"{EVAL}/{proj}_raw.json"))
    for r in rows:
        if r["category"] != "formatting":
            continue
        c = raw[r["commit_idx"]]
        scope = re.search(r"\[scope: ([^\]]+)\]", r["detail"]).group(1)
        res = {"id": r["id"], "file": r["file"], "scope": scope}
        if not r["file"].endswith(".py"):
            res["verdict"] = "non-python"; out.append(res); continue
        diff = git(REPOS[proj], "diff", c["parent"], c["sha"])
        cands = [p for p in c["py"] if p.split("/")[-1] == r["file"].split("/")[-1]]
        verdict = "unresolved"
        for path in cands:
            new = git(REPOS[proj], "show", f"{c['sha']}:{path}")
            m = re.match(r"(function|class|async function):(\w+)", scope)
            if m:
                rng = scope_range(new, "class" if m.group(1) == "class" else "function", m.group(2))
            elif scope.startswith("line:"):
                ln = int(scope[5:]); rng = (ln, ln)
            else:  # global:NAME -> find the line(s) defining it
                rng = None
                name = scope.split(":", 1)[1].split(",")[0]
                for i, l in enumerate(new.splitlines(), 1):
                    if re.match(rf"\s*(from .* import .*\b{re.escape(name)}\b|{re.escape(name)}\s*=)", l):
                        rng = (i, i); break
            if rng is None:
                continue
            hs = [h for h in hunks(diff, path)
                  if any(rng[0] <= ln <= rng[1] for ln in h["added_ln"])]
            if not hs:
                continue
            same = all(toks("\n".join(h["rem"])) == toks("\n".join(h["add"])) for h in hs)
            verdict = "claim-true" if same else "claim-false"
            res["n_hunks"] = len(hs)
            res["first_hunk_cosmetic"] = toks("\n".join(hs[0]["rem"])) == toks("\n".join(hs[0]["add"]))
            break
        res["verdict"] = verdict
        out.append(res)

json.dump(out, open(f"{EVAL}/fmt_verify2.json", "w"), indent=1)
import collections
print(collections.Counter((o["id"][:2], o["verdict"]) for o in out))
for o in out:
    if o["verdict"] == "claim-false":
        print(o)
