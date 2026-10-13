"""For each sampled commit, check whether each changed .py file parses with
the running Python's ast (IntentCheck silently skips files that do not)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import EVAL, WORK, TOOL  # noqa: E402
import ast
import json
import subprocess
import sys
import warnings

warnings.filterwarnings("ignore")


def main(raw_path, repo):
    data = json.load(open(raw_path))
    for c in data:
        res = {}
        for f in c["py"]:
            src = subprocess.run(["git", "-C", repo, "show", f"{c['sha']}:{f}"],
                                 capture_output=True, text=True,
                                 errors="replace").stdout
            try:
                ast.parse(src)
                res[f] = True
            except SyntaxError:
                res[f] = False
        c["parse"] = res
    json.dump(data, open(raw_path, "w"), indent=1)
    n_files = sum(len(c["parse"]) for c in data)
    n_bad = sum(not v for c in data for v in c["parse"].values())
    n_commit_allbad = sum(all(not v for v in c["parse"].values()) for c in data)
    n_commit_anybad = sum(any(not v for v in c["parse"].values()) for c in data)
    print(raw_path, "files", n_files, "unparseable", n_bad,
          "commits all-unparseable", n_commit_allbad,
          "commits any-unparseable", n_commit_anybad)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
