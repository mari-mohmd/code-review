"""Show the normalised bodies compared by each structural-divergence item."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import EVAL, WORK, TOOL  # noqa: E402
import ast
import json
import re
import subprocess
import sys

REPOS = {"dk": f"{WORK}/dronekit-python",
         "pp": f"{WORK}/pandapower"}


def norm(node):
    body = list(node.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    return "\n".join(ast.unparse(s) for s in body)


def main():
    out = []
    for proj in ("dk", "pp"):
        rows = json.load(open(f"{EVAL}/{proj}_items.json"))
        for r in rows:
            if r["category"] != "structural":
                continue
            m = re.search(r"SD\((\w+), (\w+)\)", r["detail"])
            a, b = m.groups()
            la, lb = map(int, re.findall(r"\(line (\d+)\)", r["detail"])[:2])
            raw = json.load(open(f"{EVAL}/{proj}_raw.json"))
            cands_files = [p for p in raw[r["commit_idx"]]["py"]
                           if p.split("/")[-1] == r["file"].split("/")[-1]]
            nodes = {}
            for fpath in cands_files:
                src = subprocess.run(["git", "-C", REPOS[proj], "show",
                                      f"{r['sha']}:{fpath}"],
                                     capture_output=True, text=True).stdout
                tree = ast.parse(src)
                names = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
                if a in names and b in names:
                    r["file"] = fpath
                    for n in ast.walk(tree):
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            nodes[(n.name, n.lineno)] = n
                    break
            def pick(name, ln):
                cands = [(abs(k[1] - ln), v) for k, v in nodes.items() if k[0] == name]
                return min(cands, key=lambda t: t[0])[1]
            na, nb = pick(a, la), pick(b, lb)
            ba, bb = norm(na), norm(nb)
            out.append({"id": r["id"], "a": a, "b": b,
                        "kind_a": type(na).__name__, "kind_b": type(nb).__name__,
                        "body_a": ba, "body_b": bb})
    json.dump(out, open(f"{EVAL}/sd_bodies.json", "w"), indent=1)
    for o in out:
        if len(o["body_a"]) > 12 or len(o["body_b"]) > 12:
            print(o["id"], o["a"], o["b"], o["kind_a"], o["kind_b"])
            print("   A:", o["body_a"][:300].replace("\n", " | "))
            print("   B:", o["body_b"][:300].replace("\n", " | "))
    import collections
    print(collections.Counter((o["body_a"], o["body_b"]) for o in out
                              if len(o["body_a"]) <= 12 and len(o["body_b"]) <= 12))
    print("cross-kind pairs:", sum(o["kind_a"] != o["kind_b"] for o in out))


main()
