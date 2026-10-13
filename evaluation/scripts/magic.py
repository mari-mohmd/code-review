"""Classify every magic-number item by context and check line accuracy.

Context classes (first match wins):
  nonpy        item on a non-Python file (e.g. .rst)                -> F
  badline      reported line does not contain the literal           -> F
  test         literal in a test file                               -> N
  kwarg        value of a keyword argument in a call or a parameter
               default (the name documents the intent)              -> N
  data         element of a list/tuple/set/dict display holding >=3
               numeric literals (tables, coordinates, coefficients) -> N
  version      comparison with a version tuple / version_info       -> N
  other        bare literal in arithmetic, comparison, positional
               argument, subscript or return in non-test code       -> candidate A
For Python-2 files (unparseable) a text heuristic on the line is used.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import EVAL, WORK, TOOL  # noqa: E402
import ast
import json
import re
import subprocess
import collections

REPOS = {"dk": f"{WORK}/dronekit-python",
         "pp": f"{WORK}/pandapower"}


def git(repo, *a):
    return subprocess.run(["git", "-C", repo, *a], capture_output=True,
                          text=True, errors="replace").stdout


def added_lines(diff, path):
    res, in_file, nl = set(), False, 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            in_file = line[6:].strip() == path; continue
        if line.startswith("--- ") or line.startswith("diff "):
            continue
        if not in_file:
            continue
        if line.startswith("@@"):
            nl = int(re.search(r"\+(\d+)", line).group(1)) - 1; continue
        if line.startswith("+"):
            nl += 1; res.add(nl)
        elif not line.startswith("-"):
            nl += 1
    return res


def parent_map(tree):
    pm = {}
    for n in ast.walk(tree):
        for ch in ast.iter_child_nodes(n):
            pm[ch] = n
    return pm


def classify_ast(tree, pm, ln, val):
    consts = [n for n in ast.walk(tree) if isinstance(n, ast.Constant)
              and getattr(n, "lineno", None) == ln
              and isinstance(n.value, (int, float)) and not isinstance(n.value, bool)
              and n.value == val]
    if not consts:
        return None
    node = consts[0]
    # walk up through unary minus
    p = pm.get(node)
    child = node
    if isinstance(p, ast.UnaryOp):
        child, p = p, pm.get(p)
    # keyword argument or parameter default
    if isinstance(p, ast.keyword):
        return "kwarg"
    if isinstance(p, ast.arguments):
        return "kwarg"
    # data display
    cur, q = child, p
    while q is not None and isinstance(q, (ast.Tuple, ast.List, ast.Set, ast.Dict, ast.UnaryOp)):
        nums = sum(1 for n in ast.walk(q) if isinstance(n, ast.Constant)
                   and isinstance(n.value, (int, float)) and not isinstance(n.value, bool))
        if nums >= 3:
            return "data"
        cur, q = q, pm.get(q)
    # version comparisons
    q = p
    for _ in range(4):
        if q is None:
            break
        if isinstance(q, ast.Compare):
            src = ast.unparse(q)
            if "version" in src.lower():
                return "version"
            break
        q = pm.get(q)
    if isinstance(q, ast.keyword):
        return "kwarg"
    return "other"


def classify_text(line, val):
    s = line.strip()
    if re.search(r"\w+\s*=\s*-?" + re.escape(str(val)) + r"\b", s) and "(" in s:
        return "kwarg"
    if len(re.findall(r"-?\d+\.?\d*", s)) >= 3 and re.search(r"[\[\(\{]", s):
        return "data"
    return "other"


def main():
    allres = []
    for proj in ("dk", "pp"):
        rows = json.load(open(f"{EVAL}/{proj}_items.json"))
        raw = json.load(open(f"{EVAL}/{proj}_raw.json"))
        cache = {}
        for r in rows:
            if r["category"] != "magic":
                continue
            c = raw[r["commit_idx"]]
            val = eval(re.search(r"Magic number (\S+) in", r["message"]).group(1))
            res = {"id": r["id"], "file": r["file"], "line": r["line"], "value": val}
            if not r["file"].endswith(".py"):
                res.update(ctx="nonpy", on_added=None); allres.append(res); continue
            cands = [p for p in c["diff_files"] if p.split("/")[-1] == r["file"].split("/")[-1]]
            ctx, on_added, path_used, text = "badline", False, None, ""
            for path in cands:
                key = (c["sha"], path)
                if key not in cache:
                    src = git(REPOS[proj], "show", f"{c['sha']}:{path}")
                    try:
                        tree = ast.parse(src); pm = parent_map(tree)
                    except SyntaxError:
                        tree = pm = None
                    diff = git(REPOS[proj], "diff", "-M", c["parent"], c["sha"])  # full diff: keeps rename detection
                    cache[key] = (src.splitlines(), tree, pm, added_lines(diff, path))
                lines, tree, pm, added = cache[key]
                ln = r["line"]
                if not ln or ln > len(lines):
                    continue
                text = lines[ln - 1]
                if tree is not None:
                    k = classify_ast(tree, pm, ln, val)
                    if k is None:
                        continue
                else:
                    if not re.search(r"(?<![\w.])" + re.escape(repr(val)).replace(r"\.0", r"(\.0*)?") + r"(?![\w])", text) \
                            and str(val) not in text:
                        continue
                    k = classify_text(text, val)
                ctx, path_used = k, path
                on_added = ln in added
                break
            if ctx != "badline" and r["is_test"]:
                ctx = "test"
            res.update(ctx=ctx, on_added=on_added, path=path_used, text=text.strip()[:160],
                       parsed=r["parsed"])
            allres.append(res)
    json.dump(allres, open(f"{EVAL}/magic_ctx.json", "w"), indent=1)
    for proj in ("dk", "pp"):
        sub = [x for x in allres if x["id"].startswith(proj)]
        print(proj, len(sub), collections.Counter(x["ctx"] for x in sub).most_common(),
              "on_added:", sum(1 for x in sub if x["on_added"]))
        print("   other & on_added:", sum(1 for x in sub if x["ctx"] == "other" and x["on_added"]))


main()
