"""Compare IntentCheck (fixed) with diff-scoped pyflakes / ruff / pylint.

1. Volume: messages per commit on added lines (diff-quality semantics).
2. Coverage of IntentCheck's actionable items: does a baseline tool report
   anything on the same file+line (a) on added lines only, (b) anywhere in
   the changed file?  Candidate matches are listed for manual judgement.
3. Baseline findings IntentCheck lacks: pyflakes messages on added lines
   and pylint E/W messages, grouped by type, for manual review.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
from _paths import EVAL, WORK, TOOL, VAL, RATER  # noqa: E402
import json, re, collections, statistics as st, sys

SETS = [("first", "dk", f"{EVAL}/dk_raw_v2.json", f"{EVAL}/labels_v2.json", f"{VAL}/bl_first_dk.json"),
        ("first", "pp", f"{EVAL}/pp_raw_v2.json", f"{EVAL}/labels_v2.json", f"{VAL}/bl_first_pp.json"),
        ("fresh", "dk", f"{VAL}/dk_raw.json", f"{VAL}/labels.json", f"{VAL}/bl_fresh_dk.json"),
        ("fresh", "pp", f"{VAL}/pp_raw.json", f"{VAL}/labels.json", f"{VAL}/bl_fresh_pp.json")]
TOOLS = ("pyflakes", "ruff", "pylint")


def item_file(it):
    m = re.search(r" in (\S+)$", it["message"]) or re.search(r"'([^']+\.py)'", it["message"]) or re.search(r": (\S+\.py)", it["message"])
    return m.group(1) if m else None


def main(only=None):
    vol = collections.defaultdict(list)          # tool -> per-commit count on added lines
    vol_all = collections.defaultdict(list)
    secs = collections.defaultdict(list)
    codes = {t: collections.Counter() for t in TOOLS}
    cov_rows = []
    pyflakes_added = []
    for sample, proj, rawp, labp, blp in SETS:
        if only and proj not in only:
            continue
        try:
            bl = {r["sha"]: r for r in json.load(open(blp))}
        except FileNotFoundError:
            print("missing", blp); continue
        raw = json.load(open(rawp))
        labels = [x for x in json.load(open(labp)) if x["project"] == proj]
        lab_by_sha = collections.defaultdict(list)
        for x in labels:
            lab_by_sha[x["sha"]].append(x)
        for c in raw:
            r = bl[c["sha"]]
            ic = len(lab_by_sha[c["sha"]])
            vol["intentcheck"].append(ic)
            for t in TOOLS:
                msgs = r["tools"][t]["messages"]
                vol[t].append(sum(m["on_added"] for m in msgs))
                vol_all[t].append(len(msgs))
                secs[t].append(r["tools"][t]["seconds"])
                for m in msgs:
                    if m["on_added"]:
                        codes[t][m["code"] or m["msg"].split(" ")[0]] += 1
                        if t == "pyflakes":
                            pyflakes_added.append((sample, proj, c["sha"][:8], m["file"], m["line"], m["msg"]))
            for x in lab_by_sha[c["sha"]]:
                if x["label"] != "A":
                    continue
                f, ln = item_file(x), x["line"]
                hit_added, hit_any = {}, {}
                for t in TOOLS:
                    for m in r["tools"][t]["messages"]:
                        if m["file"] == f and ln is not None and m["line"] == ln:
                            hit_any.setdefault(t, []).append(f"{m['code']} {m['msg'][:70]}")
                            if m["on_added"]:
                                hit_added.setdefault(t, []).append(m["code"])
                cov_rows.append({"sample": sample, "id": x["id"], "category": x["category"],
                                 "message": x["message"], "line": ln,
                                 "hit_added": hit_added, "hit_any": hit_any})
    print("== volume on added lines per commit: total / median / mean / max")
    for t in ("intentcheck",) + TOOLS:
        v = vol[t]
        print(f"  {t:12s} {sum(v):6d}  {st.median(v):5}  {st.mean(v):6.2f}  {max(v):5d}   (n={len(v)})")
    print("== whole changed files:", {t: sum(vol_all[t]) for t in TOOLS})
    print("== seconds/commit median, max:", {t: (round(st.median(secs[t]), 2), max(secs[t])) for t in TOOLS})
    for t in TOOLS:
        print("== top codes", t, codes[t].most_common(15))
    json.dump({"cov": cov_rows, "pyflakes_added": pyflakes_added,
               "vol": vol, "vol_all": vol_all, "secs": secs,
               "codes": {t: dict(codes[t]) for t in TOOLS}},
              open(f"{VAL}/compare.json", "w"), indent=1)
    print("== IntentCheck actionable items:", len(cov_rows),
          "any same-line hit (added):", sum(1 for r in cov_rows if r["hit_added"]),
          "(whole file):", sum(1 for r in cov_rows if r["hit_any"]))
    for r in cov_rows:
        if r["hit_any"]:
            print("  ", r["id"], r["category"], r["message"][:60], "L", r["line"], "|", r["hit_any"])


if __name__ == "__main__":
    main(sys.argv[1:] or None)
