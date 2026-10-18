"""Diff-scoped baseline: pyflakes, ruff (default rules) and pylint (default
configuration) on the changed .py files of each sampled commit, keeping only
messages on lines added by the commit (the rule used by diff-quality).

Each commit is materialised as a detached git worktree so that the tools see
the full post-change project (imports resolve as in a real CI run).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
from _paths import EVAL, WORK, TOOL, VAL, RATER  # noqa: E402
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

TOOLS = {
    "pyflakes": [sys.executable, "-m", "pyflakes"],
    "ruff": ["ruff", "check", "--no-cache", "--output-format", "concise", "--isolated"],
    "pylint": [sys.executable, "-m", "pylint", "--output-format=parseable", "--score=n",
               "--persistent=n", "--jobs=1"],
}
LINE_RE = {
    "pyflakes": re.compile(r"^(?P<file>[^:]+):(?P<line>\d+):(?:\d+:?)?\s*(?P<msg>.*)$"),
    "ruff": re.compile(r"^(?P<file>[^:]+):(?P<line>\d+):\d+: (?P<code>\S+) (?P<msg>.*)$"),
    "pylint": re.compile(r"^(?P<file>[^:]+):(?P<line>\d+): \[(?P<code>[A-Z]\d+)[^\]]*\] (?P<msg>.*)$"),
}


def git(repo, *a, check=True):
    return subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True,
                          errors="replace", check=check).stdout


def added_lines(diff):
    res, cur, n = {}, None, 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            p = line[4:].strip()
            cur = p[2:] if p.startswith("b/") else (None if p == "/dev/null" else p)
            if cur:
                res.setdefault(cur, set())
            continue
        if line.startswith("--- ") or line.startswith("diff "):
            continue
        if line.startswith("@@"):
            n = int(re.search(r"\+(\d+)", line).group(1)) - 1
            continue
        if cur is None:
            continue
        if line.startswith("+"):
            n += 1
            res[cur].add(n)
        elif not line.startswith("-") and not line.startswith("\\"):
            n += 1
    return res


def run(raw_path, repo, out_path):
    data = json.load(open(raw_path))
    results = []
    for c in data:
        diff = git(repo, "diff", "-M", c["parent"], c["sha"])
        added = {f: l for f, l in added_lines(diff).items() if f.endswith(".py")}
        wt = tempfile.mkdtemp(prefix="wt_")
        git(repo, "worktree", "add", "--detach", "-f", wt, c["sha"])
        rec = {"sha": c["sha"], "files": sorted(added), "tools": {}}
        try:
            files = [f for f in added if os.path.exists(os.path.join(wt, f))]
            for tool, cmd in TOOLS.items():
                t0 = time.perf_counter()
                msgs = []
                if files:
                    p = subprocess.run(cmd + files, cwd=wt, capture_output=True, text=True,
                                       errors="replace", timeout=900)
                    for line in (p.stdout + "\n" + p.stderr).splitlines():
                        m = LINE_RE[tool].match(line.strip())
                        if not m:
                            continue
                        f = os.path.normpath(m.group("file")).replace(os.sep, "/")
                        if f not in added:
                            continue
                        ln = int(m.group("line"))
                        msgs.append({"file": f, "line": ln,
                                     "code": m.groupdict().get("code") or "",
                                     "msg": m.group("msg")[:200],
                                     "on_added": ln in added[f]})
                rec["tools"][tool] = {"seconds": round(time.perf_counter() - t0, 2), "messages": msgs}
        finally:
            git(repo, "worktree", "remove", "--force", wt, check=False)
            shutil.rmtree(wt, ignore_errors=True)
        results.append(rec)
        print(c["sha"][:8], {t: (len(v["messages"]), sum(m["on_added"] for m in v["messages"]))
                             for t, v in rec["tools"].items()}, flush=True)
    json.dump(results, open(out_path, "w"), indent=1)


if __name__ == "__main__":
    run(*sys.argv[1:])
