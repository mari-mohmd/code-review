# IntentCheck — 100-commit evaluation and accuracy fixes

This document reports an evaluation of IntentCheck on 100 randomly sampled
commits from two open-source Python projects, the accuracy problems it
exposed, the fixes made in response (branch `accuracy-fixes`), a
re-evaluation of the fixed tool on the **same** commits, and a validation on
**100 fresh commits** with a blind second rater and a comparison against
diff-scoped pyflakes, Ruff and Pylint (§8–§11).

All numbers below are produced by the scripts in `evaluation/scripts/` from
the data in `evaluation/data/` (see [Reproducing](#reproducing)).

---

## 1. Summary

| | Baseline (`843bf00`) | After fixes | Change |
|---|---:|---:|---|
| Checklist items (100 commits) | 1,800 | **249** | −86% |
| Actionable items (A) | 63 (3.5%) | **62 (24.9%)** | precision ×7 |
| False items (F) | 175 (9.7%) | **0** | −175 |
| Redundant items (R) | 6 | 0 | |
| Largest checklist for one commit | 431 | 11 | |
| Commits with ≥1 actionable item | 19 | 22 | +3 |
| Developer-confirmed defects detected | 5 | **6** | +1 cross-file breakage |

Per project:

| | dronekit-python before | after | pandapower before | after |
|---|---:|---:|---:|---:|
| Items | 297 | 78 | 1,503 | 171 |
| Actionable | 11 (3.7%) | 14 (17.9%) | 52 (3.5%) | 48 (28.1%) |
| False | 170 (57.2%) | 0 | 5 (0.3%) | 0 |
| Commits with ≥1 item | 24 | 42 | 34 | 45 |
| Commits with ≥1 actionable | 6 | 6 | 13 | 16 |
| Runtime / commit, median – max (s) | 0.13 – 2.61 | 0.12 – 1.49 | 1.07 – 8.41 | 1.54 – 12.43 |

Of the 63 baseline actionable items, 45 are still reported, 18 are no longer
reported (all by design; see §5.3), and 17 new actionable items appear. All
six findings that the projects' developers later fixed themselves are still
detected, and a seventh — a cross-file API breakage in pandapower — is newly
detected by the repaired linkage checker (§5.4).

**Validation on 100 fresh commits (§8–§11).** The improvement holds but is
smaller than on the tuning sample: 204 items, **20 actionable (9.8%)**, 0
false (after fixing one bug the fresh sample exposed). Excluding
informational notices, 22.9% of findings are actionable (50.8% on the tuning
sample). A blind second rater agreed on 95% of 80 items (Cohen's κ = 0.90).
Against diff-scoped pyflakes / Ruff / Pylint, 77 of IntentCheck's 82
actionable items are reported by none of them, while the linters find a
different set of real defects (undefined names, duplicate definitions) that
IntentCheck misses: the tools are complementary.

---

## 2. Setup

**Tool.** Baseline: `mari-mohmd/code-review` commit `843bf00` (includes the
diff-scoped structural-divergence checker). After fixes: branch
`accuracy-fixes` (this branch).

**Subjects.**

| Project | Domain | Population* | Period |
|---|---|---:|---|
| [pandapower](https://github.com/e2nIEE/pandapower) | power-system modelling | 5,343 commits | 2016–2026 |
| [dronekit-python](https://github.com/dronekit/dronekit-python) | drone control | 587 commits | 2014–2019 |

\* Non-merge commits on the default branch that add or modify between 1 and
10 Python files.

**Sampling.** 50 commits per project drawn uniformly at random
(`random.Random(2026)` over the population sorted by SHA; `scripts/sample.py`).
The 100 commits touch 178 Python files; median 16 (pandapower) and 21.5
(dronekit) added lines per commit.

**Procedure** (`scripts/run.py`). For each commit: check out the post-change
tree, write `git diff <parent> <commit>` (all files, as a CI job would), run

```
python IntentCheck.py --project <repo> --diff <diff> --json --checklist empty_checklist.json
```

and record items and wall time. The empty static checklist suppresses the
tool's bundled "technology transfer" item so that only generated items are
counted. Environment: 2-vCPU Linux container, Python 3.13.

---

## 3. Adjudication protocol

Each item receives exactly one label:

| Label | Meaning |
|---|---|
| **A** actionable | The claim is correct and merits reviewer attention for this change. |
| **N** non-actionable | The claim is correct but implies no review action (self-documenting literal, generated code, intentional alias, correct "no functional change" notice, forward-dependency list). |
| **R** redundant | Restates another item about the same finding. |
| **F** false | The claim is factually wrong, or the item concerns a file the tool cannot analyse (e.g. reStructuredText). |

How each category was checked:

* **Structural divergence** — the two compared bodies were extracted and
  inspected (`scripts/sd_bodies.py`).
* **Formatting-only / "no functional change"** — verified by token comparison
  of every affected hunk (`scripts/fmt_verify2.py`) and, after the fixes, by
  comparing old/new ASTs with docstrings removed.
* **Magic numbers** — each literal classified by AST context
  (`scripts/magic.py`): literals in test files, keyword arguments / parameter
  defaults, numeric data tables (≥3 numbers in one display) and version
  comparisons → N. The remaining 114 baseline items were judged individually:
  A if a named constant would clarify intent beyond a unit conversion or
  plotting offset (e.g. bus-type code `== 3` where `REF` exists). A random
  sample of 45 automatically labelled items agreed with manual judgement in
  all cases.
* **Lifecycle, naming, concurrency, shell, injection** — every item checked
  against the source at that commit.
* **Linkage** — every listed file verified *independently of the tool's
  resolver* by regex over the importing file's import statements / `open()`
  literals (`scripts/verify_linkage.py`; the verifier was negative-tested).
  An item is A if it lists a caller of a definition whose signature changed
  in a **breaking** way (parameter removed, renamed or reordered, new required
  parameter, or definition removed); otherwise N.
* After the fixes, items identical to a baseline item (same commit, checker,
  file, line) inherit the baseline label (`scripts/match_v2.py`); the 178 new
  items were labelled with the same rules (`scripts/label_v2.py` records every
  manual decision with its reason).

Labels were assigned by a single adjudicator; inter-rater agreement has not
been measured. Per-item labels and reasons: `data/labels_baseline.csv`,
`data/labels_after_fixes.csv`.

---

## 4. Baseline results

### 4.1 Items per checker

| Checker | pandapower | dronekit | A | N+R | F |
|---|---:|---:|---:|---:|---:|
| Magic number | 1,460 | 62 | 42 | 1,473 | 7 |
| Formatting-only notice | 30 | 88 | 0 | 75 | 43 |
| Structural divergence | 1 | 114 | 1 | 4 | 110 |
| Lifecycle | 0 | 22 | 6 | 6 | 10 |
| Injection risk | 11 | 0 | 9 | 0 | 2 |
| Concurrency / subprocess | 0 | 7 | 5 | 2 | 0 |
| Naming | 1 | 3 | 0 | 1 | 3 |
| Shell execution | 0 | 1 | 0 | 1 | 0 |
| Linkage, path coherence, input, hard-coded path | 0 | 0 | – | – | – |
| **Total** | 1,503 | 297 | 63 | 1,562 | 175 |

### 4.2 What went wrong

**Noise (pandapower).** 97% of pandapower items are magic-number notices.
85% of these concern literals on lines the commit did not change, because
every checker runs on the whole enclosing function. Four commits that edit
standard-type tables, example grids and test fixtures produce 80% of all
items (431 in one commit).

**False positives (dronekit-python, 57%).**

| Cause | F items |
|---|---:|
| Structural divergence between empty stubs (`pass` / `None` bodies; 33 pairs compare a class with a method), triggered by docstring-only commits because the diff gate matched identifiers inside edited docstrings | 110 |
| reStructuredText files analysed line by line as Python | 47 |
| Python 2 files (35 of 74 changed files) silently skipped or analysed line by line; produced lifecycle items contradicted by `vehicle.close()` later in the file | 9 |
| "Never used" claimed because the module-level fragment omitted later usages | 1 |
| Naming: protobuf-generated `_ACCESSCODE`/`AccessCode`; class alias `Vehicle` vs instance `vehicle` | 3 |

**Silent failures.**

* **Linkage never fired.** The resolver mapped `import a.b` only to a
  top-level `a.py`, so it found 0 links among 585 (pandapower) and 47
  (dronekit) Python files. It only worked for the flat demo scenario.
* **Formatting masked logic changes.** A function was classified by its
  *first* changed hunk. In `pandapower` commits a function whose later hunks
  changed logic (`split_line_at_length` gained a new coordinate computation)
  was reported as "purely cosmetic" and **all other checkers were skipped**
  for it. A moved star-import was also reported as cosmetic.
* **Injection matched names only.** Plain `json.loads` and
  `__import__('pandapower')` were flagged; `re.compile` would have been.
* **Line numbers.** Module-level fragments were built from non-contiguous
  lines, so a reported line could be wrong (dronekit `reboot.py`: line 7
  instead of 29, reported twice).

### 4.3 Developer-confirmed defects (baseline)

| Project | Flagged in | Checker | Defect | Fixed in |
|---|---|---|---|---|
| dronekit | `f352d4f4`, `96dac341` | Lifecycle | `test_timeout` never closes vehicle connection | `b8b7d5e` |
| dronekit | `96dac341` | Lifecycle | `test_goto` never closes vehicle connection | `b8b7d5e` |
| dronekit | `e4201bb9` | Lifecycle | `test_empty_clear` never closes vehicle connection | `b8b7d5e` |
| dronekit | `e4201bb9` | Lifecycle | `test_parameter` never closes vehicle connection | `b8b7d5e` |
| pandapower | `233854cd` | Struct. div. | Duplicate `_create_ppc2pd_bus_lookup` shadows the first definition | `b7e5721e` |

`b8b7d5e` ("Fixes Windows tests by closing connections") added
`vehicle.close()` to exactly the four flagged functions 3–14 days later.
Pylint 4.1.3 (default configuration) reports neither defect type:
`consider-using-with` only knows standard-library resources, and
`function-redefined` is suppressed for `_`-prefixed names by the default
`dummy-variables-rgx` (verified: removing the underscore makes Pylint report
E0102).

---

## 5. Fixes

### 5.1 Changes

| # | Problem observed | Change | Where |
|---|---|---|---|
| 1 | Non-Python files analysed as Python | Only `.py` files in the diff are analysed | `analyzer.generate_from_diff` |
| 2 | Python 2 / unparseable files silently skipped or analysed line by line | One explicit `parse` item per file ("Not analysed: … is not valid Python 3.x"); no line-level fallback | `analyzer` |
| 3 | Generated files (protobuf) produced naming/SD noise | Files with `_pb2.py` names or "Generated by the protocol buffer compiler" / "DO NOT EDIT" / `@generated` headers are reported once as `skipped` | `analyzer._is_generated` |
| 4 | Scope decided by the first changed line; deletions ignored; docstring edits treated as code | New hunk model: hunks keep context, are relocated if stale (exact, then comment/whitespace-insensitive match), and each hunk is classified as *cosmetic* (identical token stream), *noncode* (comments/docstrings only) or *code*. Only code hunks select scopes; deletions inside a function select that function | `lib/diff_model.py` |
| 5 | Formatting notice per scope, could mask logic | One "No functional change" item per file, emitted only when **every** hunk in the file is cosmetic or non-code. Moved lines are detected because the comparison includes context | `diff_model.classify_hunk` |
| 6 | SD compared empty stubs, class vs method, nested blocks; gate fired on docstring mentions | Compare only same-kind, non-nested blocks with ≥2 statements (docstring removed); a pair is reported only if one block contains a changed *code* line | `StructuralDivergenceChecker` |
| 7 | Magic numbers dominated the output | Self-documenting literals exempt (keyword args, parameter defaults, numeric tables, version comparisons, annotated assignments); test files skipped; on unchanged lines of a changed scope only comparison operands are reported | `MagicNumberChecker` |
| 8 | Lifecycle false "never closed / never used" for module-level code; redundant summary | Release calls and usages are looked up in the full module for module-level fragments; returned/yielded/attribute-stored handles count as transferred; LC summary only when >1 resource (score folded into the item otherwise); new check for unbound handles such as `tempfile.mkstemp()[1]` | `LifecycleChecker` |
| 9 | Naming flagged conventions | `_x`/`x` (private/public) and `Vehicle`/`vehicle` (class/instance) pairs not reported | `NameSimilarityChecker` |
| 10 | Injection matched by name | `eval/exec/compile` only as builtins; `__import__`/`import_module` only with computed names; `pickle`-family and unsafe `yaml.load` always; `json.load(s)` only with `cls=`/`object_hook=` | `InjectionRiskChecker` |
| 11 | Linkage found nothing in packaged projects | Package-aware resolution (`a.b.c` → `a/b/c.py` or `a/b/c/__init__.py`, relative imports, unambiguous `src/`-layout suffixes, `open()` paths relative to root or file). Files already in the diff are excluded. **New:** files that use a definition changed in the diff are listed ("reverse linkage") | `graph_builder.py`, `analyzer._linkage` |
| 12 | Wrong line numbers; ambiguous base names | Fragment line numbers (in `item.line` and in detail text) are mapped back to file lines; messages use project-relative paths | `analyzer._translate` |
| 13 | Regression risk | Unit tests, one per failure mode above (`tests/test_accuracy.py`, 25 tests); the six demo scenarios still produce their documented findings (scenario 5 no longer reports two empty `pass` methods as duplicates) | `tests/` |
| 14 | *Found on the fresh sample (§8):* re-indenting a block into an `if` was classified as layout-only, because the hunk comparison ignored indentation tokens | Indentation is part of the comparison (only on lines that start a statement; continuation lines inside brackets are still layout); additionally every hunk judged non-functional must leave the AST of its enclosing scope unchanged, otherwise it is treated as code | `diff_model.classify_hunk`, `confirm_non_functional` |
| 15 | SD message said "100%" for scores just below 1.0 | Scores are truncated, not rounded, and INFO items say "not identical" | `StructuralDivergenceChecker` |

### 5.2 Items per checker after the fixes

| Checker | pandapower | dronekit | A | N | F |
|---|---:|---:|---:|---:|---:|
| Linkage | 99 | 19 | 3 | 115 | 0 |
| Magic number | 49 | 3 | 29 | 23 | 0 |
| Parse failure (new) | 0 | 35 | 0 | 35 | 0 |
| Injection risk | 13 | 0 | 13 | 0 | 0 |
| No functional change | 5 | 5 | 0 | 10 | 0 |
| Concurrency / subprocess | 0 | 7 | 5 | 2 | 0 |
| Lifecycle | 0 | 7 | 7 | 0 | 0 |
| Structural divergence | 5 | 0 | 5 | 0 | 0 |
| Generated file skipped (new) | 0 | 1 | 0 | 1 | 0 |
| Shell execution | 0 | 1 | 0 | 1 | 0 |
| Naming | 0 | 0 | – | – | – |
| **Total** | 171 | 78 | 62 | 187 | 0 |

### 5.3 Findings no longer reported (18)

All follow from the new magic-number scoping rule (literals on unchanged
lines are reported only when they are comparison operands, and literals in
unchanged *caller* functions are not reported):

| Items | Literal and context |
|---:|---|
| 10 | `net.line["endtemp_degree"] = 250` in `example_grids.py` — the commit only **moved** this file, so these lines are unchanged |
| 4 | `else 1e-3` fallback for a zero current rating (unchanged lines) |
| 1 | column index `[:, 10]` (unchanged) |
| 1 | `count < 3 * max_iteration` (unchanged) |
| 1 | `max_iteration = 30 if tdpf else …` (unchanged) |
| 1 | `BUS_TYPE != 3` in an unchanged function that calls a changed one |

This is the main recall/precision trade-off of the fixes: 18 actionable
literals lost against 1,457 non-actionable magic-number items removed.

### 5.4 New findings (17)

| Items | Finding | Corroboration |
|---:|---|---|
| 1 | **Linkage, pandapower `55c50612`:** `create_line_collection(… use_line_geodata …)` was changed to `(… line_geodata, use_bus_geodata …, **kwargs)`; the item lists `plotting/simple_plot.py` as a user of the changed definition. That file (not in the diff) still passed `use_line_geodata=`, which now falls through `**kwargs` into matplotlib's `LineCollection` | **Fixed four days later** in `e3a190e94` "simple plotting parameter fix", which changed exactly that call |
| 2 | Linkage: callers of other breaking signature changes (`assert_net_equal` parameters renamed; `create_transformers_from_parameters` parameters removed) | Callers checked: positional / unaffected keywords — prompts, not defects |
| 4 | Structural divergence: three identical and one 99%-identical example-grid functions (`load_4bus_net`, `load_4bus_net_oc_doc`, `doc_relay_net`, …) | All removed / consolidated in `6d3e8a22a` (Feb 2023) |
| 1 | Lifecycle: `tempfile.mkstemp()[1]` in dronekit's test runner discards an open file descriptor | Line removed in the test-runner rewrite `64a325a` |
| 4 | Injection: `pickle.load` in `from_pickle`; `importlib.import_module` with module names read from JSON input (the root of the `PPJSONDecoder` risk) | — |
| 5 | Magic numbers as comparison operands on unchanged lines: heartbeat timeout `> 5`, batch limit `> 50`, `BUS_TYPE == 3`, solver codes `== 545`, `< 1e10` "unlimited" sentinel | — |

### 5.5 Developer-confirmed defects after the fixes

All five baseline defects (§4.3) are still reported, plus the pandapower
`simple_plot` breakage (`55c50612` → fixed in `e3a190e94`).

---

## 6. Remaining limitations

* **Forward linkage is noisy.** 81 of 118 linkage items only list files the
  changed file imports (all correct, none actionable on its own). They are
  kept because the paper's linkage scenario is a forward dependency.
  Suppressing forward-only items would reduce the output to 168 items (37%
  actionable); this could become an option.
* **Magic-number recall.** See §5.3. A per-project allowlist of known codes,
  or detecting that a named constant with the same value is already in scope,
  would recover some lost items without the noise.
* **Python 2 is not analysed.** Unparseable files are now reported
  explicitly (35 items in dronekit), but not checked.
* **Runtime** for pandapower rose from 1.07 s to about 1.5 s median (max
  12–17 s; medians varied between 1.28 s and 1.68 s across repeated runs on
  the shared 2-vCPU container) because the dependency graph now also records
  attribute usage for reverse linkage. The graph is rebuilt on every run;
  caching it would remove most of this cost.
* **Repeated literals.** The same literal used several times in one function
  produces one item per line; the second rater treated repeats as redundant
  (§9). Grouping them per scope would shorten checklists further.
* **Precision on unseen commits is lower** than on the tuning sample (§8).
* **Validity.** One adjudicator; the A/N boundary involves judgement; the
  after-fix items were labelled by the same person who designed the fixes.
  The evaluation used the same 100 commits that motivated the fixes, so a
  fresh sample is needed to rule out overfitting.

---

## 7. Corrections to earlier reported figures

* The share of pandapower magic-number items on unchanged lines is **85%**,
  not the 63% first computed: the first computation diffed renamed files
  without rename detection, so moved lines counted as added. Labels were not
  affected.


---

## 8. Validation on a fresh sample

**Sample.** 50 new commits per project from the same population definition,
excluding the 100 commits used above (`validation/scripts/sample_fresh.py`,
seed 2027): pandapower 5,293 candidate commits (2016-10-28 – 2025-10-15),
dronekit-python 537 (2014-03-27 – 2018-10-22); 168 changed Python files;
median 9.5 / 7 added lines per commit. The fixed tool was run exactly as in
§2 and every item labelled with the rubric of §3
(`validation/scripts/label_fresh.py`; manual decisions listed in the script).

**Bug found.** On the first run one item was false: pandapower `427e8244`
re-indents six lines of `_make_objective` into the preceding block — a
logic change — and the tool reported "No functional change". The cause was
that hunk comparison ignored indentation tokens. Fixed (§5.1 #14, with a
regression test that fails on the previous code); re-running both samples
changed only that item. The figures below are from the fixed version.

| | dronekit-python | pandapower | Total |
|---|---:|---:|---:|
| Items | 67 | 137 | 204 |
| Actionable (A) | 6 | 14 | **20 (9.8%)** |
| Non-actionable (N) | 60 | 123 | 183 |
| Redundant (R) | 1 | 0 | 1 |
| False (F) | 0 | 0 | **0** |
| Commits with ≥1 item | 39 | 49 | 88 |
| Commits with ≥1 actionable | 3 | 5 | 8 |
| Largest checklist for one commit | 10 | 18 | |
| Runtime / commit, median – max (s) | 0.12 – 1.29 | 1.68 – 16.87 | |

| Checker | Items | A | N / R |
|---|---:|---:|---:|
| Linkage | 96 | 0 | 96 |
| Magic number | 41 | 13 | 28 |
| Parse failure | 40 | 1 | 39 |
| No functional change | 14 | 0 | 14 |
| Concurrency / subprocess | 5 | 3 | 2 |
| Lifecycle | 4 | 3 | 1 R |
| Structural divergence | 3 | 0 | 3 |
| Shell execution | 1 | 0 | 1 |

**Tuning sample vs fresh sample.**

| | Tuning sample (§5) | Fresh sample |
|---|---:|---:|
| Items | 249 | 204 |
| Actionable share, all items | 24.9% | 9.8% |
| Informational notices (parse, no-functional-change, skipped, forward-only linkage) | 127 | 121 |
| Actionable share of the remaining findings | 50.8% | **22.9%** |
| Magic-number items actionable | 56% | 32% |

The fresh-sample figures are the ones to quote. Part of the gap is sample
composition (the tuning sample contained pandapower's JSON/pickle I/O code,
13 actionable injection items; the fresh one has none) and part is the
expected optimism of evaluating on the commits that motivated the fixes.

**Notable fresh-sample findings.**

* *Unresolved merge-conflict marker* — pandapower `create.py` contained
  `<<<<<<< HEAD` (introduced in `b64d992b`, removed 11 minutes later in
  `8b20d8ee`). IntentCheck reports the file as not parseable. Diff-scoped
  linters do **not** report it for the sampled commit, because the broken
  line was not added by that commit (§10).
* *Leaking listening socket* — dronekit `7000397a` ("Properly close Vehicle
  instances after SITL tests") leaves `socket.socket(...)` bound to port
  5760 open in `test_timeout_empty`; still present on `master`.
* `tempfile.mkstemp()[1]` file-descriptor leaks (2) and newly added
  `Popen` calls (3) in dronekit's test runner.
* Opaque solver codes (`alg == 3/4`) and cost/result column indices.

No fresh-sample linkage item listed a caller of a *breaking* signature
change (29 of 96 linkage items listed reverse users; all of those signatures
were compatible).

---

## 9. Second rater

An independent rater labelled 80 items blind: all 20 fresh-sample actionable
items, 30 random other fresh-sample items, and 15 actionable + 15 other
items from the tuning sample, shuffled. The rater had only the rubric
(`validation/rater/RUBRIC.md`), the item list and read-only access to the
git repositories, and investigated each item itself.

| | Value |
|---|---:|
| Raw agreement, 4 labels | 95.0% (76/80) |
| Cohen's κ, 4 labels | **0.90** |
| Cohen's κ, A vs not-A | 0.90 |
| Agreement on "worth attention" (A or R) vs (N or F) | 100% |

All four disagreements are the same question: the same literal repeated in
one function (e.g. `1e-10` three times in `_calc_branch_currents`), which the
rater labelled R and the first rater A. Item-level reasons from both raters:
`validation/rater/agreement.csv`.

**Caveat.** The second rater was an AI agent (Claude) working in a separate
context without access to the first labels; the first rater was also Claude.
This shows the rubric can be applied consistently, but it is not a
substitute for agreement between independent human reviewers.

---

## 10. Comparison with diff-scoped linters

Diff-scoped static analysis is not unique to IntentCheck: diff-quality (part
of diff-cover) reports pyflakes / flake8 / Pylint / Ruff violations on the
changed lines of a diff, reviewdog filters any linter's output to added
lines on pull requests, and SonarQube reports only issues in new code for
pull requests. What differs is *how* the diff is used: those tools analyse
whole files and filter the output by line; IntentCheck uses the diff to
decide what to analyse (enclosing scope of each changed line, hunk
classification) and follows changed definitions to their users outside the
diff (reverse linkage).

**Setup** (`validation/scripts/baseline_linters.py`). For each of the 200
commits, a detached worktree of the post-change tree; pyflakes 4.0.3, Ruff 0.16.8 with its default rule
set (`--isolated`; in 0.16 the default set includes pyflakes, bugbear,
pyupgrade, Pylint ports and more), and Pylint 4.1.3 with its default
configuration, each run on the commit's changed `.py` files; only messages
on lines added by the commit are counted (diff-quality's rule).

**Volume** (200 commits):

| Tool | Messages on added lines | per commit, mean / median / max | on whole changed files | runtime / commit, median – max (s) |
|---|---:|---|---:|---|
| IntentCheck (items) | 453 | 2.3 / 1 / 18 | – | 0.59 – 16.9 |
| pyflakes | 147 | 0.7 / 0 / 72 | 1,063 | 0.06 – 0.28 |
| Ruff | 463 | 2.3 / 0 / 85 | 6,743 | 0.01 – 0.10 |
| Pylint | 2,148 | 10.7 / 1 / 541 | 23,955 | 1.9 – 34.8 |

Most frequent linter messages on added lines: Pylint `C0301` line too long
(620), `C0103` naming (269), `C0303` trailing whitespace (239); Ruff
`invalid-syntax` (142, Python 2 code), `F841` unused variable (49);
pyflakes unused local variables (49) and redefinitions (18).

**Do the linters report IntentCheck's actionable items?** For each of the 82
actionable items (62 tuning + 20 fresh), every linter message on the same
file and line was inspected by hand:

| Overlap | Items |
|---|---:|
| Same issue reported on an added line (Pylint `R1732` consider-using-with on 4 newly added `Popen` calls) | 4 |
| Same issue reported only when linting the whole file (merge-conflict marker: syntax error) | 1 |
| Unrelated message on the same line (line length, protected access, `R1714`, the author's own TODO; on the three `mkstemp()[1]` lines Pylint's `R1732` concerns the `Popen` call, not the leaked descriptor) | 14 |
| Nothing on that line | 63 |
| **Not reported by any linter** | **77 of 82 (94%)** |

**Developer-confirmed defects in the 200 commits** (fixed or removed later
by the projects), and which tool reports them on the flagged commit:

| Defect | Fixed | IntentCheck | pyflakes | Ruff | Pylint |
|---|---|:-:|:-:|:-:|:-:|
| 4 × dronekit SITL tests never close the vehicle connection | `b8b7d5e`, 3–14 days | ✓ | – | – | – |
| `simple_plot.py` still passes a removed keyword (`55c50612`) | `e3a190e9`, 4 days | ✓ (reverse linkage) | – | – | – |
| Merge-conflict marker in `create.py` | `8b20d8ee`, 11 min | ✓ | –* | –* | –* |
| Duplicate `_create_ppc2pd_bus_lookup` | `b7e5721e`, 14 days | ✓ | ✓ | – | – |
| Duplicate `_check_connectivity` (copies differ) | `c5ff6f8b`, same day | – | ✓ | – | – |
| Duplicate `get_line_path` (copies differ) | removed in `77627435` (2025) | – | ✓ | ✓ | ✓ |
| Missing `import time, math` (dronekit `71de7e8a`) | `bf3332b`, 77 min | – | ✓ | ✓ | ✓ |
| Undefined `pp` in `plotly.py` | `70fa9801`, next day | – | ✓ | ✓ | ✓ |
| Undefined `run_powermodels` | `8a16d039`, 6 days | – | ✓ | ✓ | ✓ |
| **Total (12 defects)** | | **7** | **6** | **4** | **4** |

\* reported when the whole file is linted, but not under diff-scoped
filtering, because the marker line was not added by the flagged commit.
Ruff 0.16.8 did not report `F811` for the underscore-prefixed duplicate;
Pylint suppresses `function-redefined` for underscore-prefixed names by
default.

**Reading.** IntentCheck and the linters find almost disjoint sets of
problems: one defect of twelve is found by both. The linters are better at
name-resolution errors (undefined names, redefinitions of non-identical
copies); IntentCheck is better at resource lifecycle in domain APIs,
cross-file effects of a change, and file-level conditions the diff filter
hides. IntentCheck produces fewer messages per commit than Pylint (2.3 vs
10.7) and about as many as Ruff, but a larger share of its output is
review-relevant.

---

## 11. Conclusions

* After the fixes IntentCheck is a low-noise, fast, offline source of
  change-specific review prompts: about 2 items per commit, no false claims
  on 200 commits after the indentation fix, and roughly one item in four
  findings (one in ten items overall) worth a reviewer's attention on unseen
  commits.
* Its strongest distinctive capabilities on real history were reverse
  linkage (callers outside the diff), resource lifecycle for domain APIs,
  and explicit file-level notices; magic-number prompts are the bulk of its
  actionable output but of lower individual value.
* It does not replace a linter: pyflakes alone found five confirmed defects
  IntentCheck missed. The recommended setup is IntentCheck alongside a
  diff-scoped pyflakes/Ruff run.
* "Diff-scoped" should not be claimed as unique; "diff-driven" analysis
  (choosing scopes and following changed definitions) is the defensible
  distinction.

---

## Reproducing

```bash
# clones next to this repository (or set INTENTCHECK_WORK)
git clone https://github.com/e2nIEE/pandapower.git
git clone https://github.com/dronekit/dronekit-python.git
cd code-review/evaluation/scripts

python sample.py ../../../pandapower       ../data/pp_sample.json
python sample.py ../../../dronekit-python  ../data/dk_sample.json
python run.py ../data/pp_sample.json ../data/pp_raw_v2.json   # tool under test: INTENTCHECK_TOOL
python run.py ../data/dk_sample.json ../data/dk_raw_v2.json
python match_v2.py && python verify_linkage.py && python label_v2.py && python summary_v2.py
```

`run.py` checks out each sampled commit in the target clone (restore with
`git checkout develop` / `master` afterwards). The baseline pipeline is
`run.py` → `parse_check.py` → `flatten.py` → `sd_bodies.py`,
`fmt_verify2.py`, `magic.py` → `label.py` → `summary.py`.

| File | Contents |
|---|---|
| `data/{pp,dk}_sample.json` | sampled commits |
| `data/{pp,dk}_raw.json`, `data/{pp,dk}_raw_v2.json` | raw tool output, baseline / after fixes |
| `data/labels_baseline.csv`, `data/labels_after_fixes.csv` | one row per item: label and reason |
| `data/summary.json`, `data/summary_v2.json` | every number in this document |
| `data/linkage_v2.json` | linkage verification per item |
| `validation/data/{pp,dk}_sample.json`, `{pp,dk}_raw.json` | fresh sample and tool output |
| `validation/data/labels.json`, `labels_fresh.csv` | fresh-sample labels |
| `validation/data/bl_{first,fresh}_{dk,pp}.json` | linter messages per commit |
| `validation/data/compare.json` | volume and overlap analysis |
| `validation/rater/` | rubric, blind item list, second-rater labels, agreement table |

Validation pipeline (`evaluation/validation/scripts/`): `sample_fresh.py` →
`../../scripts/run.py` → `dump.py` → `label_fresh.py`;
`baseline_linters.py <raw.json> <repo> <out.json>` → `compare.py`.
