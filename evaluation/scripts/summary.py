import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import EVAL, WORK, TOOL  # noqa: E402
import json
import statistics as st
import collections

L = json.load(open(f"{EVAL}/labels.json"))
S = {}
for proj in ("dk", "pp"):
    raw = json.load(open(f"{EVAL}/{proj}_raw.json"))
    sub = [x for x in L if x["project"] == proj]
    per_commit = collections.Counter(x["sha"] for x in sub)
    counts = [per_commit.get(c["sha"], 0) for c in raw]
    lab = collections.Counter(x["label"] for x in sub)
    n = len(sub)
    top4 = sum(sorted(counts, reverse=True)[:4])
    a_commits = len({x["sha"] for x in sub if x["label"] == "A"})
    secs = [c["seconds"] for c in raw]
    py_files = sum(len(c["parse"]) for c in raw)
    unparse = sum(not v for c in raw for v in c["parse"].values())
    allbad = sum(all(not v for v in c["parse"].values()) for c in raw)
    stub_or_nonpy = sum(1 for x in sub if x["label"] == "F" and
                        (x["file"] and not x["file"].endswith(".py") or
                         "empty stub" in json.dumps(x)))
    reasons = collections.Counter(x["reason"] for x in sub if x["label"] == "F")
    nonpy_items = sum(1 for x in sub if x["file"] and not x["file"].endswith(".py"))
    stub = sum(1 for x in sub if x["reason"].startswith("empty stub"))
    F_rest = lab["F"] - nonpy_items - stub
    magic = [x for x in sub if x["category"] == "magic" and x["on_added_line"] is not None]
    S[proj] = dict(
        commits=len(raw), commits_with_items=sum(1 for k in counts if k),
        items=n, median_items=st.median(counts), max_items=max(counts),
        top4_share=round(100 * top4 / n, 1),
        A=lab["A"], N=lab["N"], R=lab["R"], F=lab["F"],
        pct_A=round(100 * lab["A"] / n, 1), pct_F=round(100 * lab["F"] / n, 1),
        pct_correct=round(100 * (n - lab["F"]) / n, 1),
        commits_with_A=a_commits,
        nonpy_items=nonpy_items, stub_items=stub,
        F_after_excl=F_rest, n_after_excl=n - nonpy_items - stub,
        pct_F_after_excl=round(100 * F_rest / (n - nonpy_items - stub), 1),
        magic_items=sum(1 for x in sub if x["category"] == "magic"),
        magic_on_added=sum(1 for x in magic if x["on_added_line"]),
        sec_median=round(st.median(secs), 2), sec_max=round(max(secs), 2),
        sec_total=round(sum(secs), 1),
        py_files=py_files, py_unparseable=unparse, commits_all_unparseable=allbad,
        added_median=st.median(c["added"] for c in raw),
        removed_median=st.median(c["removed"] for c in raw),
        date_min=min(c["date"] for c in raw), date_max=max(c["date"] for c in raw),
        population=json.load(open(f"{EVAL}/{proj}_sample.json"))["population"],
        by_cat={k: dict(collections.Counter(x["label"] for x in sub if x["category"] == k))
                for k in sorted({x["category"] for x in sub})},
        F_reasons=dict(reasons),
    )
tot = {k: S["dk"][k] + S["pp"][k] for k in ("items", "A", "N", "R", "F", "commits_with_A")}
S["total"] = tot
json.dump(S, open(f"{EVAL}/summary.json", "w"), indent=1)
print(json.dumps(S, indent=1))
