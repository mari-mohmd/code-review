import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import EVAL, WORK, TOOL  # noqa: E402
import json
import statistics as st
import collections

B = json.load(open(f"{EVAL}/labels.json"))
V = json.load(open(f"{EVAL}/labels_v2.json"))
out = {}
for proj in ("dk", "pp"):
    raw1 = json.load(open(f"{EVAL}/{proj}_raw.json"))
    raw2 = json.load(open(f"{EVAL}/{proj}_raw_v2.json"))
    res = {}
    for tag, L, raw in (("before", B, raw1), ("after", V, raw2)):
        sub = [x for x in L if x["project"] == proj]
        lab = collections.Counter(x["label"] for x in sub)
        per = collections.Counter(x["sha"] for x in sub)
        counts = [per.get(c["sha"], 0) for c in raw]
        n = len(sub)
        res[tag] = dict(
            items=n, A=lab["A"], N=lab["N"], R=lab["R"], F=lab["F"],
            pct_A=round(100 * lab["A"] / n, 1), pct_F=round(100 * lab["F"] / n, 1),
            pct_correct=round(100 * (n - lab["F"]) / n, 1),
            commits_with_items=sum(1 for k in counts if k),
            commits_with_A=len({x["sha"] for x in sub if x["label"] == "A"}),
            median_items=st.median(counts), max_items=max(counts),
            sec_median=round(st.median(c["seconds"] for c in raw), 2),
            sec_max=round(max(c["seconds"] for c in raw), 2),
            by_cat={k: dict(collections.Counter(x["label"] for x in sub if x["category"] == k))
                    for k in sorted({x["category"] for x in sub})},
        )
    out[proj] = res
for tag, L in (("before", B), ("after", V)):
    lab = collections.Counter(x["label"] for x in L)
    out.setdefault("total", {})[tag] = dict(items=len(L), **{k: lab[k] for k in "ANRF"},
                                            pct_A=round(100 * lab["A"] / len(L), 1),
                                            pct_F=round(100 * lab["F"] / len(L), 1))
kept = {x["base_id"] for x in V if x["base_id"]}
out["baseline_A_kept"] = sum(1 for b in B if b["label"] == "A" and b["id"] in kept)
out["baseline_A_lost"] = sum(1 for b in B if b["label"] == "A" and b["id"] not in kept)
out["new_A"] = sum(1 for v in V if v["label"] == "A" and not v["base_id"])
out["baseline_F_removed"] = sum(1 for b in B if b["label"] == "F" and b["id"] not in kept)
json.dump(out, open(f"{EVAL}/summary_v2.json", "w"), indent=1)
print(json.dumps(out, indent=1))
