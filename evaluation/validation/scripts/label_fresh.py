"""Labels for the fresh 100-commit sample (fixed tool).

Manual decisions are listed in MANUAL with their reason; formatting and
linkage items are verified automatically with the same methods as the first
evaluation (AST comparison without docstrings; independent import check and
breaking-signature rule)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
from _paths import EVAL, WORK, TOOL, VAL, RATER  # noqa: E402
import ast, json, re, subprocess, sys, collections
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
REPOS = {"dk": f"{WORK}/dronekit-python", "pp": f"{WORK}/pandapower"}
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts", "verify_linkage.py")).read().split("\ndef main():")[0]
exec(src)  # imports_module, opens_file, sig, breaking, top_defs, show

A_MAGIC = {"pp3-02-001": "gencost column index 5 (PYPOWER cost-column constants exist)",
           "pp3-02-002": "loss weighting factor 1000",
           "pp3-08-006": "solver code alg == 3", "pp3-08-007": "solver code alg == 4",
           "pp3-08-008": "solver code alg == 3", "pp3-08-009": "solver code alg == 4",
           "pp3-09-007": "gencost column index 5", "pp3-09-008": "gencost column index 5",
           "pp3-09-009": "gencost column index 4", "pp3-09-010": "gencost column index 4",
           "pp3-23-009": "bus_pq column index 4", "pp3-23-010": "bus_pq column index 3",
           "pp3-23-011": "bus_pq column index 5"}
MANUAL = {
    "dk3-19-003": ("A", "mkstemp()[1] discards an open file descriptor (line added in this commit)"),
    "dk3-19-004": ("A", "Popen added in this commit"),
    "dk3-19-005": ("A", "Popen added in this commit"),
    "dk3-21-000": ("A", "mkstemp()[1] discards an open file descriptor (line modified in this commit)"),
    "dk3-21-001": ("N", "unchanged Popen in modified function"),
    "dk3-21-002": ("N", "unchanged Popen in modified function"),
    "dk3-21-003": ("A", "Popen modified in this commit"),
    "dk3-21-004": ("N", "unchanged; Windows 'start' requires a shell"),
    "dk3-49-008": ("A", "listening socket on port 5760 never closed; still present on master"),
    "dk3-49-009": ("R", "LC summary restates dk3-49-008"),
    "pp3-26-001": ("N", "fixtures differ in the intended parameter (sn_mva 2 vs 200)"),
    "pp3-27-001": ("N", "similar test functions; intentional variants"),
    "pp3-39-002": ("N", "fixtures differ in the intended parameter ('GL' vs 'DL')"),
    "pp3-48-000": ("A", "file contains an unresolved merge-conflict marker (b64d992b, removed 11 min later in 8b20d8ee)"),
}


def strip_doc(source):
    t = ast.parse(source)
    for n in ast.walk(t):
        b = getattr(n, "body", None)
        if isinstance(b, list):
            n.body = [s for s in b if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
                                           and isinstance(s.value.value, str))] or [ast.Pass()]
    return ast.dump(t)


def main():
    R = json.load(open(f"{VAL}/items.json"))
    out = []
    for r in R:
        p = r["project"]
        raw = json.load(open(f"{VAL}/{p}_raw.json"))[r["commit_idx"]]
        repo, sha, parent = REPOS[p], raw["sha"], raw["parent"]
        if r["id"] in MANUAL:
            lab, why = MANUAL[r["id"]]
        elif r["category"] == "magic":
            lab, why = ("A", A_MAGIC[r["id"]]) if r["id"] in A_MAGIC else ("N", "unit conversion / plotting / evident from context")
        elif r["category"] == "parse":
            lab, why = "N", "correct: Python 2 or pre-3.7 syntax ('await' as a name); file not analysed"
        elif r["category"] == "formatting":
            path = re.search(r"in (\S+)$", r["message"]).group(1)
            same = strip_doc(show(repo, parent, path)) == strip_doc(show(repo, sha, path))
            lab, why = ("N", "verified: ASTs equal without docstrings") if same else ("F", "AST differs")
        elif r["category"] == "linkage":
            path = re.search(r"Linked files to '([^']+)'", r["message"]).group(1)
            fsrc = show(repo, sha, path)
            fwd, rev, mode = [], [], None
            for line in r["detail"].splitlines():
                if line.startswith("Files using"): mode = "rev"; continue
                if line.startswith("Files this file"): mode = "fwd"; continue
                m = re.match(r"\s+- (\S+)(?:\s+\(uses (.*)\))?$", line)
                if m:
                    (rev if mode == "rev" else fwd).append((m.group(1), [n.strip() for n in (m.group(2) or "").split(",") if n.strip()]))
            bad = [f for f, _ in fwd if not (imports_module(fsrc, path, f) if f.endswith(".py") else opens_file(fsrc, f))]
            new_defs, old_defs = top_defs(fsrc), top_defs(show(repo, parent, path) or "")
            brk = {n for n, node in old_defs.items() if n not in new_defs or breaking(sig(node), sig(new_defs[n]))}
            hits = []
            for u, names in rev:
                usrc = show(repo, sha, u) or ""
                if not imports_module(usrc, u, path):
                    bad.append(u); continue
                bad += [f"{u}:{n}" for n in names if not re.search(rf"\b{re.escape(n)}\b", usrc)]
                if set(names) & brk:
                    hits.append((u, sorted(set(names) & brk)))
            if bad:
                lab, why = "F", f"incorrect entries {bad}"
            elif hits:
                lab, why = "A", f"callers of breaking signature change: {hits}"
            else:
                lab, why = "N", "reverse users, signatures unchanged" if rev else "forward dependencies only"
            r["n_rev"] = len(rev)
        else:
            raise SystemExit("unlabelled " + r["id"])
        out.append({**{k: r.get(k) for k in ("id", "project", "sha", "file", "category", "message", "line", "code", "n_rev")},
                    "label": lab, "reason": why})
    json.dump(out, open(f"{VAL}/labels.json", "w"), indent=1)
    for p in ("dk", "pp"):
        sub = [o for o in out if o["project"] == p]
        print(p, len(sub), dict(collections.Counter(o["label"] for o in sub)))
        t = collections.defaultdict(collections.Counter)
        for o in sub: t[o["category"]][o["label"]] += 1
        for k, v in sorted(t.items(), key=lambda kv: -sum(kv[1].values())): print("   ", k, sum(v.values()), dict(v))
    for o in out:
        if o["category"] == "linkage" and o["label"] != "N": print(o["id"], o["label"], o["reason"][:200])


main()
