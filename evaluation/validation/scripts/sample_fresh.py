"""Fresh sample: same population as sample.py, seed 2027, excluding commits
already used in the first evaluation."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
from _paths import EVAL, WORK, TOOL, VAL, RATER  # noqa: E402
import json, random, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
from sample import population
repo, prev, out = sys.argv[1:4]
used = {c["sha"] for c in json.load(open(prev))["sample"]}
pop = sorted((c for c in population(repo) if c["sha"] not in used), key=lambda c: c["sha"])
s = random.Random(2027).sample(pop, 50)
s.sort(key=lambda c: c["date"])
json.dump({"repo": repo, "population": len(pop), "seed": 2027, "excluded": len(used), "sample": s}, open(out, "w"), indent=1)
print(repo, len(pop), "->", len(s), s[0]["date"], s[-1]["date"])
