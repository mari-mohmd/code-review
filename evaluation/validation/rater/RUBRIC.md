# Rating rubric

Each item is one entry of a code-review checklist produced by a static tool for one git commit.
Assign exactly one label:

- **A (actionable)** – the item's claim is correct AND it merits a reviewer's attention for this change.
- **N (non-actionable)** – the claim is correct but implies no review action. Examples: a numeric literal whose
  meaning is evident (unit conversions such as 1e-3 or 180/pi, plotting offsets/sizes, values in tutorials or
  example scripts); generated code; an intentional alias or intentional variant; a correct notice that a file has
  no functional change; a correct notice that a file could not be parsed because it is legacy Python 2 code;
  a list of files that the changed file imports (forward dependencies) with nothing more.
- **R (redundant)** – the item only restates another item about the same finding in the same commit.
- **F (false)** – the claim is factually wrong.

Category guidance:
- *magic*: A if a named constant would make intent clearer beyond a unit conversion or plotting tweak
  (e.g. opaque status/solver codes like `alg == 3`, opaque column indices, unexplained thresholds/sentinels/timeouts).
- *linkage*: verify the listed files really import/are imported as stated. A only if a listed caller uses a
  definition whose signature changed in a *breaking* way in this commit (parameter removed/renamed/reordered,
  new required parameter, or definition removed); otherwise N.
- *lifecycle / concurrency / shell / injection*: A if the construct is real and is on code added or modified by
  this commit or is a genuine risk in the modified function; N if it is correct but concerns unchanged code that a
  reviewer need not revisit.
- *structural*: A if the near-duplicate looks like unintended duplication; N if the blocks are deliberate variants.
- *parse / formatting / skipped*: check the claim; A only if the notice reveals a real problem in the commit.

Investigate with git yourself (e.g. `git -C <repo> show <commit>:<path>`, `git -C <repo> diff <parent> <commit> -- <path>`).
Do NOT run `git checkout` and do not modify the repositories.
