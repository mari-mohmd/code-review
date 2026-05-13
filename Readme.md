# IntentCheck — Code Review Assistant

A lightweight, offline tool for generating dynamic, change-specific code review
checklists for Python projects. Implements the methodology from:

> IntentCheck: A Lightweight Tool for Detecting Intent Violations During Code Review
> Mohammad Mari, Lian Wen -- Griffith University, February 2026

---

## Overview

Static analysis tools check that code is syntactically and structurally correct.
IntentCheck goes one step further: it checks whether the code does what the
developer intended. It combines diff-based change detection, Abstract Syntax Tree
(AST) traversal, and inter-file dependency resolution to surface intent violations
that conventional tools such as Pylint and Pyright cannot detect.

The tool runs entirely offline -- no AI inference, no cloud connectivity, no
external services.

---

## Formal Basis

The methodology is grounded in four formal models:

- P = (F, C, L)                               -- program representation
- LC(y) = (Ry, Oy, Uy)                        -- lifecycle completeness
- SD(Bi, Bj) = 2 * |LCS| / (|Bi| + |Bj|)     -- structural divergence
- LCPP(di, fj)                                -- path coherence

---

## Checkers

| No. | Checker              | What It Detects                                        |
|-----|----------------------|--------------------------------------------------------|
| 1   | Linkage              | Linked files missing from the diff                     |
| 2   | Naming               | Identifier variants in the same scope (user_id/userId) |
| 3   | Magic Number         | Bare numeric literals with no named constant           |
| 4   | Lifecycle            | Resources or context managers not properly released    |
| 5   | Structural Divergence| Near-duplicate code blocks                             |
| 6   | Concurrency          | Subprocess, multiprocessing, and threading constructs  |
| 7   | Path Coherence       | File written outside its intended directory            |
| 8   | Shell Execution      | os.system, subprocess with shell=True                  |
| 9   | Input                | input() validation, blocking, encoding, and echo risks |

---

## Project Structure

```
code-review/
    IntentCheck.py                -- main entry
    lib/
        analyzer.py
        checkers.py
        checklist_data
        graph_builder
    test_scenarios/          -- self-contained scenarios for testing and replication
        scenario1/
            project_dir/
            diff.txt
            run.sh
        scenario2/
            project_dir/
            diff.txt
            run.sh
        scenario3/
            project_dir/
            run.sh
        scenario4/
            project_dir/
            run.sh
        scenario5/
            project_dir/
            run.sh
        scenario6/
            project_dir/
            run.sh
```

---

## Requirements

- Python 3.10 or later
- No third-party dependencies -- standard library only

---

## Quick Start

Clone IntentCheck once and run it against any Python project:

```bash
git clone https://github.com/mari-mohmd/code-review.git
cd your-project
git diff main > changes.diff
python /path/to/code-review/IntentCheck.py --project . --diff changes.diff
```

---

## Installation

```bash
git clone https://github.com/mari-mohmd/code-review.git
```

No package installation required. Run directly with Python.

---

## Using IntentCheck on Your Project

IntentCheck is a standalone tool. Clone it once to a convenient location on your
machine, then point it at any Python project using the `--project` flag.

### Step 1 — Clone IntentCheck

```bash
git clone https://github.com/mari-mohmd/code-review.git ~/tools/intentcheck
```

### Step 2 — Analyse your project

Navigate to your project and generate a diff, then run IntentCheck against it:

```bash
cd /path/to/your-project

# Review uncommitted changes against main
git diff main > changes.diff
python ~/tools/intentcheck/IntentCheck.py --project . --diff changes.diff

# Review a specific commit
git diff abc1234~1 abc1234 > changes.diff
python ~/tools/intentcheck/IntentCheck.py --project . --diff changes.diff

# Scan the entire project without a diff
python ~/tools/intentcheck/IntentCheck.py --project . --all
```

### Step 3 — Optional: CI/CD integration

Add IntentCheck to a Git pre-push hook or pull request check so the checklist
is generated automatically whenever a diff is produced:

```bash
# .git/hooks/pre-push  (make executable with chmod +x)
#!/bin/bash
git diff main > /tmp/changes.diff
python ~/tools/intentcheck/IntentCheck.py --project . --diff /tmp/changes.diff
```

---

## Usage

### Analyse a git diff

```bash
git diff main > changes.diff
# or a specific commit:
# git diff 3ee89b7~1 3ee89b7 > changes.diff
python IntentCheck.py --project <target-project-path> --diff changes.diff
```

### Analyse specific files

```bash
python IntentCheck.py --project . --files src/main.py src/utils.py
```

### Scan the entire project

```bash
python IntentCheck.py --project . --all
```

### One-line summary

```bash
python IntentCheck.py --project . --all --summary
```

---

## Static Checklist

In addition to the dynamic, diff-driven checkers, the tool supports a
**static checklist**: a set of user-defined items that are appended to every
review run, regardless of what changed. These represent reviewer obligations
that apply to every commit -- for example, confirming that the CHANGELOG was
updated or that new environment variables are documented.

### Configuration file

Static items are loaded from a JSON file named `checklist.json` placed in the
project directory being reviewed.

```json
{
  "items": [
    {
      "message": "CHANGELOG updated",
      "detail": "Every user-facing change should be recorded in CHANGELOG.md.",
      "category": "manual",
      "enabled": true
    },
    {
      "message": "New environment variables documented",
      "detail": "Ensure new or removed env vars are documented in README or .env.example.",
      "category": "manual",
      "enabled": true
    }
  ]
}
```

| Field      | Type   | Required | Default    | Description                                      |
|------------|--------|----------|------------|--------------------------------------------------|
| `message`  | string | yes      | —          | Short title shown in the checklist output        |
| `detail`   | string | no       | `""`       | Multi-line reviewer guidance                     |
| `category` | string | no       | `"manual"` | Free-form tag (e.g. `"manual"`, `"security"`)    |
| `enabled`  | bool   | no       | `true`     | Set to `false` to skip an item without deleting it |

### Generating a starter config

```bash
python IntentCheck.py --checklist-init
```

This writes a `checklist.json` template with example items into the current
project directory. The command fails if the file already exists.

### Behaviour

- Items with `"enabled": false` are silently skipped.
- Items with an empty or missing `"message"` are skipped.
- If the file cannot be found or parsed, a single error item is emitted so the
  reviewer is notified rather than silently missing items.
- If no `checklist.json` exists and no path is supplied, the static checklist
  is empty and the tool runs normally.

---

## Extending IntentCheck

Additional checkers can be implemented by creating new checker classes in
`lib/checkers.py` and registering them in the `ChecklistGenerator` class within
`lib/analyzer.py`, allowing the checklist to be tailored to project-specific
requirements.

---

## Test Scenarios

The `test_scenarios/` directory contains six self-contained scenarios for testing
and evaluation replication. Each scenario includes a `run.sh` script that executes
the analyser and reproduces checklist output.

To run a scenario:

```bash
cd test_scenarios/scenario1
./run.sh
```

---

## License

MIT License

---

## Reference

If you use this tool in your research, please cite:

```
@article{mari2026lightweight,
  title       = {A Lightweight Methodology for Verifying Intended Logic During Code Review},
  author      = {Mari, Mohammad and Wen, Lian},
  year        = {2026},
  institution = {Griffith University}
}
```
