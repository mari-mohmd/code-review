"""Flatten raw results into one row per checklist item, attributing each item
to the file it concerns and to the commit."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import EVAL, WORK, TOOL  # noqa: E402
import json
import re
import sys

MSG_FILE = [
    re.compile(r" in (\S+)$"),                       # "... in foo.py"
    re.compile(r"Linked files to '([^']+)'"),         # linkage
    re.compile(r"Formatting-only change in (\S+)$"),
]


def file_of(msg):
    for rx in MSG_FILE:
        m = rx.search(msg)
        if m:
            return m.group(1)
    return None


def main(raw, out, proj):
    data = json.load(open(raw))
    rows = []
    for ci, c in enumerate(data):
        import subprocess
        repo = {"dk": f"{WORK}/dronekit-python", "pp": f"{WORK}/pandapower"}[proj]
        names = subprocess.run(["git", "-C", repo, "diff", "--name-only", c["parent"], c["sha"]],
                               capture_output=True, text=True).stdout.split()
        c["diff_files"] = names
        base_to_path = {}
        for p in c["py"] + names:
            base_to_path.setdefault(p.split("/")[-1], p)
        for ii, it in enumerate(c["items"] or []):
            base = file_of(it["message"])
            path = base_to_path.get(base, base)
            parsed = c.get("parse", {}).get(path)
            rows.append({
                "id": f"{proj}-{ci:02d}-{ii:03d}", "project": proj,
                "sha": c["sha"], "commit_idx": ci, "file": path,
                "is_test": bool(path and re.search(r"(^|/)tests?(/|_)|test_|_test\.py$", path)),
                "is_py": bool(path and path.endswith(".py")),
                "parsed": parsed,
                **it,
            })
    json.dump(rows, open(out, "w"), indent=1)
    print(proj, len(rows), "items")


if __name__ == "__main__":
    main(*sys.argv[1:])
