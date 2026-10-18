"""Assign an adjudication label to every checklist item.

A = actionable   : claim correct and merits reviewer attention for this change
N = non-actionable: claim correct but no reasonable review action (self-
                    documenting literal, generated code, intentional alias,
                    informational formatting notice, unchanged code)
R = redundant    : restates another item about the same finding
F = false        : claim factually wrong, or item emitted for a non-Python file
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import EVAL, WORK, TOOL  # noqa: E402
import json
import collections

# ---- manual decisions (see notes in the evaluation write-up) --------------
MAGIC_A = set("""pp-04-002 pp-04-003 pp-15-000 pp-15-001 pp-15-002 pp-15-003 pp-18-000
pp-19-000 pp-19-001 pp-21-002 pp-21-003 pp-21-004 pp-25-000 pp-25-001 pp-25-002
pp-25-003 pp-25-004 pp-25-005 pp-36-002 pp-36-003 pp-38-000 pp-38-015 pp-38-030
pp-38-046 pp-38-055 pp-38-095 pp-38-136 pp-38-200 pp-38-287 pp-38-319 pp-38-341
pp-38-342 pp-38-343 pp-42-001 pp-42-003 pp-43-001 pp-43-002 pp-45-003 pp-45-005
pp-45-006 pp-45-018 pp-45-010""".split())

MANUAL = {
    # structural divergence
    "dk-05-002": ("N", "generated protobuf classes"),
    "dk-05-003": ("N", "generated protobuf classes"),
    "dk-12-000": ("N", "documented placeholder (web_connect not implemented)"),
    "dk-28-006": ("N", "intentional alias count/__len__"),
    "pp-04-001": ("A", "duplicate definition of _create_ppc2pd_bus_lookup; removed in b7e5721e"),
    # naming
    "dk-05-000": ("F", "generated protobuf naming convention"),
    "dk-05-001": ("F", "generated protobuf naming convention"),
    "dk-28-000": ("F", "class alias Vehicle vs instance vehicle (PEP 8 convention)"),
    "pp-04-000": ("N", "locals in different functions; no typo"),
    # lifecycle
    "dk-22-002": ("A", "connect() in test never closed"),
    "dk-22-003": ("R", "LC summary of dk-22-002"),
    "dk-23-006": ("A", "connect() in test never closed"),
    "dk-23-007": ("R", "LC summary"),
    "dk-23-008": ("A", "connect() in test never closed"),
    "dk-23-009": ("R", "LC summary"),
    "dk-25-010": ("F", "vehicle.close() at module end (py2 line-level fallback)"),
    "dk-25-011": ("F", "vehicle is used (py2 line-level fallback)"),
    "dk-25-012": ("F", "LC 0% wrong; closed at module end"),
    "dk-25-013": ("F", "vehicle.close() at module end (py2 line-level fallback)"),
    "dk-25-014": ("F", "vehicle is used (py2 line-level fallback)"),
    "dk-25-015": ("F", "LC 0% wrong; closed at module end"),
    "dk-29-001": ("A", "connect() in test never closed"),
    "dk-29-002": ("R", "LC summary"),
    "dk-29-016": ("A", "connect() in test never closed"),
    "dk-42-000": ("F", "vehicle.close() at module end (py2 line-level fallback)"),
    "dk-42-001": ("F", "vehicle is used (py2 line-level fallback)"),
    "dk-42-002": ("F", "LC 0% wrong; closed at module end"),
    "dk-46-000": ("R", "duplicate of dk-46-003 at wrong line (7)"),
    "dk-46-001": ("F", "vehicle is used (vehicle.reboot()); global fragment omits it"),
    "dk-46-002": ("R", "LC summary"),
    "dk-46-003": ("A", "reboot example never closes vehicle, unlike other examples"),
    # concurrency / shell
    "dk-18-000": ("A", "Queue added in this commit"),
    "dk-18-001": ("A", "Thread added in this commit"),
    "dk-18-007": ("N", "unchanged Popen in caller scope"),
    "dk-18-008": ("N", "unchanged Popen in caller scope"),
    "dk-18-009": ("A", "Popen modified in this commit"),
    "dk-18-010": ("N", "unchanged; Windows 'start' requires shell"),
    "dk-28-003": ("A", "Queue in new MAVHandler"),
    "dk-28-004": ("A", "Thread in new MAVHandler"),
    # injection
    "pp-26-009": ("F", "__import__ of a constant module name"),
    "pp-35-005": ("F", "plain json.loads without custom decoder"),
}
for i in ("pp-35-000", "pp-35-001", "pp-35-002", "pp-35-003", "pp-35-004",
          "pp-37-001", "pp-37-002", "pp-37-003", "pp-37-004"):
    MANUAL[i] = ("A", "json.loads with PPJSONDecoder (imports modules named in input); pre-existing")

FMT_FALSE_EXTRA = {"pp-37-000": "star-import reordered, not cosmetic"}
FMT_TRUE_OVERRIDE = {"dk-20-011"}  # whitespace inside a comment


def main():
    magic = {m["id"]: m for m in json.load(open(f"{EVAL}/magic_ctx.json"))}
    fmt = {f["id"]: f for f in json.load(open(f"{EVAL}/fmt_verify2.json"))}
    sd = {s["id"]: s for s in json.load(open(f"{EVAL}/sd_bodies.json"))}
    labelled = []
    for proj in ("dk", "pp"):
        for r in json.load(open(f"{EVAL}/{proj}_items.json")):
            i, cat = r["id"], r["category"]
            if i in MANUAL:
                lab, why = MANUAL[i]
            elif cat == "magic":
                ctx = magic[i]["ctx"]
                if ctx == "nonpy":
                    lab, why = "F", "non-Python file"
                elif ctx == "other":
                    lab, why = ("A", "opaque domain constant") if i in MAGIC_A else ("N", "unit conversion / plotting / example value")
                else:
                    lab, why = "N", f"self-documenting ({ctx})"
            elif cat == "formatting":
                v = fmt[i]["verdict"]
                if i in FMT_FALSE_EXTRA:
                    lab, why = "F", FMT_FALSE_EXTRA[i]
                elif v == "non-python":
                    lab, why = "F", "non-Python file"
                elif v == "claim-true" or i in FMT_TRUE_OVERRIDE:
                    lab, why = "N", "correct formatting notice"
                else:
                    lab, why = "F", "scope contains non-cosmetic change; checkers skipped"
            elif cat == "structural":
                s = sd[i]
                if s["body_a"] in ("pass", "None") and s["body_b"] in ("pass", "None"):
                    lab, why = "F", "empty stub bodies (pass/None)"
                else:
                    raise SystemExit(f"unlabelled SD item {i}")
            else:
                raise SystemExit(f"unlabelled item {i} {cat}")
            on_added = magic[i]["on_added"] if i in magic else None
            labelled.append({**{k: r[k] for k in ("id", "project", "sha", "file", "category",
                                                  "message", "line", "is_test", "parsed")},
                             "label": lab, "reason": why, "on_added_line": on_added})
    json.dump(labelled, open(f"{EVAL}/labels.json", "w"), indent=1)
    for proj in ("dk", "pp"):
        sub = [x for x in labelled if x["project"] == proj]
        print(proj, len(sub), collections.Counter(x["label"] for x in sub))
        tab = collections.defaultdict(collections.Counter)
        for x in sub:
            tab[x["category"]][x["label"]] += 1
        for k, v in sorted(tab.items(), key=lambda kv: -sum(kv[1].values())):
            print("   ", k, sum(v.values()), dict(v))


main()
