"""Reproducible commit sampling for the IntentCheck evaluation.

Population: non-merge commits on the default branch that add or modify
between 1 and 10 Python (.py) files (pure deletions/renames excluded).
Sample: 50 commits drawn uniformly at random, seed 2026.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import EVAL, WORK, TOOL  # noqa: E402
import json
import random
import subprocess
import sys

SEED = 2026
N = 50
MAX_PY = 10


def population(repo):
    out = subprocess.run(
        ["git", "-C", repo, "log", "--no-merges", "--format=@@%H|%cs|%s",
         "--name-status", "--diff-filter=AM", "HEAD"],
        capture_output=True, text=True, check=True).stdout
    commits, cur = [], None
    for line in out.splitlines():
        if line.startswith("@@"):
            if cur:
                commits.append(cur)
            h, d, s = line[2:].split("|", 2)
            cur = {"sha": h, "date": d, "subject": s, "py": []}
        elif line.strip() and cur is not None:
            parts = line.split("\t")
            if parts[-1].endswith(".py"):
                cur["py"].append(parts[-1])
    if cur:
        commits.append(cur)
    # must have a parent (skip root commit)
    return [c for c in commits if 1 <= len(c["py"]) <= MAX_PY]


def main(repo, out_path):
    pop = population(repo)
    pop.sort(key=lambda c: c["sha"])  # order-independent of git log order
    rng = random.Random(SEED)
    sample = rng.sample(pop, N)
    sample.sort(key=lambda c: c["date"])
    json.dump({"repo": repo, "population": len(pop), "seed": SEED,
               "sample": sample}, open(out_path, "w"), indent=1)
    print(repo, "population", len(pop), "sampled", len(sample))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
