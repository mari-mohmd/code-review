"""Independent verification and labelling of v2 linkage items.

Correctness: every listed file is checked against the *source text* of the
importing file (regex over import statements / open() literals), not via
the tool's resolver.
  forward entry  f  : the changed file imports module(f) or opens f
  reverse entry  u  : u imports the changed module and mentions each used name
Actionability: A if some reverse entry uses a definition whose signature
changed (parameters of a function / of a class __init__) or that was removed
in the commit; N otherwise.  Any incorrect entry makes the item F.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import EVAL, WORK, TOOL  # noqa: E402
import ast
import json
import re
import subprocess

REPOS = {"dk": f"{WORK}/dronekit-python", "pp": f"{WORK}/pandapower"}


def show(repo, rev, path):
    p = subprocess.run(["git", "-C", repo, "show", f"{rev}:{path}"], capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else None


def module_names(path):
    parts = path[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return parts


def imports_module(src, importer, target):
    """Does `importer` (text src) import module `target` (path)?"""
    tparts = module_names(target)
    dotted = ".".join(tparts)
    last = tparts[-1]
    parent = ".".join(tparts[:-1])
    pats = [
        rf"^\s*import\s+[\w., ]*\b{re.escape(dotted)}\b",
        rf"^\s*from\s+{re.escape(dotted)}\s+import\b",
        rf"^\s*from\s+{re.escape(parent)}\s+import\s+[\w, ()\\\n]*\b{re.escape(last)}\b" if parent else None,
        rf"^\s*from\s+\.+{re.escape(last)}\s+import\b",
        rf"^\s*from\s+\.+[\w.]*\.{re.escape(last)}\s+import\b",
        rf"^\s*from\s+\.+\s+import\s+[\w, ()\\\n]*\b{re.escape(last)}\b",
        rf"^\s*from\s+\.+{re.escape('.'.join(tparts[-2:]))}\s+import\b" if len(tparts) > 1 else None,
    ]
    # src/ layouts or partial package names: allow suffix matches of >= 2 parts
    for k in range(1, len(tparts) - 1):
        suf = ".".join(tparts[k:])
        pats.append(rf"^\s*(from|import)\s+{re.escape(suf)}\b")
    return any(p and re.search(p, src, re.M) for p in pats)


def opens_file(src, target):
    base = target.rsplit("/", 1)[-1]
    return re.search(r"open\(\s*['\"][^'\"]*" + re.escape(base) + r"['\"]", src) is not None


def sig(node):
    """(positional names, number required, keyword-only names, required kw-only)."""
    if isinstance(node, ast.ClassDef):
        inits = [b for b in node.body if isinstance(b, ast.FunctionDef) and b.name == "__init__"]
        if not inits:
            return ((), 0, (), ())
        node = inits[0]
    a = node.args
    pos = [x.arg for x in a.posonlyargs + a.args]
    req = len(pos) - len(a.defaults)
    kwreq = [x.arg for x, d in zip(a.kwonlyargs, a.kw_defaults) if d is None]
    return (tuple(pos), req, tuple(x.arg for x in a.kwonlyargs), tuple(kwreq))


def breaking(old, new):
    """Can a call valid against `old` fail or change meaning against `new`?"""
    op, oreq, okw, _ = old
    np_, nreq, nkw, nkwreq = new
    if list(np_[:len(op)]) != list(op):        # positional parameter renamed/removed/reordered
        return True
    if nreq > oreq:                            # new required positional parameter
        return True
    if set(okw) - set(nkw) - set(np_):         # keyword-only parameter removed
        return True
    if set(nkwreq) - set(okw):                 # new required keyword-only parameter
        return True
    return False


def top_defs(src):
    try:
        t = ast.parse(src)
    except SyntaxError:
        return {}
    return {n.name: n for n in t.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}


def main():
    R = json.load(open(f"{EVAL}/v2_items.json"))
    out = {}
    for r in R:
        if r["category"] != "linkage":
            continue
        raw = json.load(open(f"{EVAL}/{r['project']}_raw_v2.json"))[r["commit_idx"]]
        repo, sha, parent = REPOS[r["project"]], raw["sha"], raw["parent"]
        path = re.search(r"Linked files to '([^']+)'", r["message"]).group(1)
        src = show(repo, sha, path)
        fwd, rev, mode = [], [], None
        for line in r["detail"].splitlines():
            if line.startswith("Files using"):
                mode = "rev"; continue
            if line.startswith("Files this file"):
                mode = "fwd"; continue
            m = re.match(r"\s+- (\S+)(?:\s+\(uses (.*)\))?$", line)
            if m:
                (rev if mode == "rev" else fwd).append((m.group(1), [n.strip() for n in (m.group(2) or "").split(",") if n.strip()]))
        bad = []
        for f, _ in fwd:
            ok = imports_module(src, path, f) if f.endswith(".py") else opens_file(src, f)
            if not ok:
                bad.append(("fwd", f))
        new_defs, old_defs = top_defs(src), top_defs(show(repo, parent, path) or "")
        sig_changed = set()
        for name, node in old_defs.items():
            if name not in new_defs:
                sig_changed.add(name)
            elif breaking(sig(node), sig(new_defs[name])):
                sig_changed.add(name)
        actionable_uses = []
        for u, names in rev:
            usrc = show(repo, sha, u) or ""
            if not imports_module(usrc, u, path):
                bad.append(("rev-import", u)); continue
            for n in names:
                if not re.search(rf"\b{re.escape(n)}\b", usrc):
                    bad.append(("rev-name", u, n))
            hit = sorted(set(names) & sig_changed)
            if hit:
                actionable_uses.append((u, hit))
        label = "F" if bad else ("A" if actionable_uses else "N")
        reason = (f"incorrect entries: {bad}" if bad else
                  f"callers of breaking signature change: {actionable_uses}" if actionable_uses else
                  ("reverse users of changed definitions (signatures unchanged)" if rev else "forward dependencies only"))
        out[r["id"]] = {"label": label, "reason": reason, "n_fwd": len(fwd), "n_rev": len(rev),
                        "sig_changed": sorted(sig_changed)}
    json.dump(out, open(f"{EVAL}/linkage_v2.json", "w"), indent=1)
    import collections
    print(collections.Counter((k[:2], v["label"]) for k, v in out.items()))
    for k, v in out.items():
        if v["label"] != "N":
            print(k, v["label"], v["reason"][:220])
    print("items with reverse entries:", sum(1 for v in out.values() if v["n_rev"]))


main()
