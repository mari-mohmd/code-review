# IntentCheck — 100-commit evaluation and accuracy fixes

This document reports an evaluation of IntentCheck on 100 randomly sampled
commits from two open-source Python projects, the accuracy problems it
exposed, the fixes made in response (branch `accuracy-fixes`), and a
re-evaluation of the fixed tool on the **same** commits.

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
| Runtime / commit, median – max (s) | 0.13 – 2.61 | 0.11 – 1.12 | 1.07 – 8.41 | 1.28 – 9.72 |

Of the 63 baseline actionable items, 45 are still reported, 18 are no longer
reported (all by design; see §5.3), and 17 new actionable items appear. All
six findings that the projects' developers later fixed themselves are still
detected, and a seventh — a cross-file API breakage in pandapower — is newly
detected by the repaired linkage checker (§5.4).

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
| 13 | Regression risk | 23 unit tests, one per failure mode above (`tests/test_accuracy.py`); the six demo scenarios still produce their documented findings (scenario 5 no longer reports two empty `pass` methods as duplicates) | `tests/` |

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
* **Runtime** for pandapower rose from 1.07 s to 1.28 s median (max 9.7 s)
  because the dependency graph now also records attribute usage for reverse
  linkage. The graph is rebuilt on every run; caching it would remove most of
  this cost.
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
