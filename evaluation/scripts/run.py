"""Run IntentCheck on each sampled commit and store raw output."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import EVAL, WORK, TOOL  # noqa: E402
import json
import os
import subprocess
import sys
import time

EMPTY = f"{EVAL}/empty_checklist.json"


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True,
                          text=True, errors="replace", check=True).stdout


def main(sample_path, out_path):
    d = json.load(open(sample_path))
    repo = d["repo"]
    results = []
    for c in d["sample"]:
        sha = c["sha"]
        parents = git(repo, "rev-list", "--parents", "-n1", sha).split()[1:]
        git(repo, "checkout", "-q", "-f", sha)
        if parents:
            diff = git(repo, "diff", parents[0], sha)
        else:  # root commit: diff against empty tree
            diff = git(repo, "show", "--format=", sha)
        dpath = f"{EVAL}/cur.diff"
        open(dpath, "w").write(diff)
        t0 = time.perf_counter()
        p = subprocess.run([sys.executable, TOOL, "--project", repo,
                            "--diff", dpath, "--json", "--checklist", EMPTY],
                           capture_output=True, text=True, cwd=f"{EVAL}")
        dt = time.perf_counter() - t0
        try:
            items = json.loads(p.stdout)
        except Exception:
            items = None
        stat = git(repo, "diff", "--numstat", parents[0], sha) if parents else ""
        add = rem = 0
        for ln in stat.splitlines():
            a, r, *_ = ln.split("\t")
            if a.isdigit():
                add += int(a); rem += int(r)
        results.append({**c, "parent": parents[0] if parents else None,
                        "seconds": round(dt, 3), "returncode": p.returncode,
                        "stderr": p.stderr[-2000:], "added": add,
                        "removed": rem, "items": items})
        print(sha[:8], f"{dt:5.2f}s", p.returncode,
              len(items) if items is not None else "ERR", flush=True)
    json.dump(results, open(out_path, "w"), indent=1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
