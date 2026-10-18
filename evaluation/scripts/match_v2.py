"""Match v2 items to baseline-labelled items; list the unmatched ones."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import EVAL, WORK, TOOL  # noqa: E402
import json
import re
import collections

base = json.load(open(f"{EVAL}/labels.json"))
idx = collections.defaultdict(list)
for b in base:
    m = re.search(r"^(.*) in (\S+)$", b["message"])
    stem = m.group(1) if m else b["message"]
    idx[(b["sha"], b["category"], (b["file"] or "").split("/")[-1], stem, b["line"])].append(b)

rows = []
for proj in ("dk", "pp"):
    raw = json.load(open(f"{EVAL}/{proj}_raw_v2.json"))
    for ci, c in enumerate(raw):
        for ii, it in enumerate(c["items"]):
            m = re.search(r"^(.*) in (\S+)$", it["message"])
            stem, path = (m.group(1), m.group(2)) if m else (it["message"], None)
            if path is None:
                m2 = re.search(r"'([^']+\.py)'|: (\S+\.py)", it["message"])
                path = (m2.group(1) or m2.group(2)) if m2 else None
            key = (c["sha"], it["category"], (path or "").split("/")[-1], stem, it["line"])
            hit = idx.get(key)
            row = {"id": f"{proj}2-{ci:02d}-{ii:03d}", "project": proj, "sha": c["sha"],
                   "commit_idx": ci, "file": path, **it,
                   "base_id": hit[0]["id"] if hit else None,
                   "label": hit[0]["label"] if hit else None,
                   "reason": hit[0]["reason"] if hit else None}
            rows.append(row)
json.dump(rows, open(f"{EVAL}/v2_items.json", "w"), indent=1)
un = [r for r in rows if r["label"] is None]
print("total", len(rows), "matched", len(rows) - len(un), "unmatched", len(un))
print(collections.Counter((r["project"], r["category"]) for r in un))
