"""
===============================================================================
 Project    : A Lightweight Methodology for Verifying Intended
                       Logic During Code Review
 File       : static_checklist.py
 Author(s)  : Mohammad Mari, Lian Wen
 Affiliation: School of ICT, Griffith University
 Contact    : mohammad.mari@griffithuni.edu.au
 Created    : 2026
 License    : MIT License (see LICENSE file for details)
 Description: User-defined static checklist items loaded from a JSON config.
 Usage      : Supplementary file. see review.py
===============================================================================
"""

import json
from pathlib import Path
from typing import Optional

from .checklist_data import ChecklistItem

DEFAULT_CONFIG_NAME = ".checklist.json"

_EXAMPLE_CONFIG = {
    "items": [
        {
            "message": "CHANGELOG updated",
            "detail": (
                "Every user-facing change should be recorded in CHANGELOG.md.\n"
                "Verify that the changelog entry is present and describes the change."
            ),
            "category": "manual",
            "enabled": True,
        },
        {
            "message": "New environment variables documented",
            "detail": (
                "If this change introduces or removes environment variables,\n"
                "ensure they are documented in README.md or .env.example."
            ),
            "category": "manual",
            "enabled": True,
        },
        {
            "message": "Database migration included",
            "detail": (
                "Schema changes require a corresponding migration file.\n"
                "Verify a migration has been created and tested locally."
            ),
            "category": "manual",
            "enabled": False,
        },
    ]
}


class StaticChecklistLoader:
    """
    Loads and returns user-defined static checklist items from a JSON file.

    Items are emitted once per review run, independent of diff content.
    They represent reviewer obligations that apply to every commit
    (e.g. "Was the CHANGELOG updated?", "Are new env vars documented?").

    Config file format  (<project>/.checklist.json):

        {
          "items": [
            {
              "message": "Short title shown in the checklist",
              "detail":  "Longer explanation / guidance for the reviewer.",
              "category": "manual",
              "enabled": true
            }
          ]
        }

    Fields
    ------
    message  : str   — Short title shown in the checklist output.  Required.
    detail   : str   — Multi-line reviewer guidance.  Optional, defaults to "".
    category : str   — Free-form tag (e.g. "manual", "process", "security").
                       Optional, defaults to "manual".
    enabled  : bool  — When false the item is skipped.  Optional, defaults to true.

    Usage
    -----
    loader = StaticChecklistLoader(config_path)
    items  = loader.load()          # -> list[ChecklistItem]

    To generate a starter config in a project:
        StaticChecklistLoader.write_example(Path("my_project/.checklist.json"))
    """

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path: Optional[Path] = (
            Path(config_path) if config_path is not None else None
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def load(self) -> list:
        """
        Parse the config file and return enabled ChecklistItems.

        Returns an empty list when no config path was given and no default
        config exists.  Returns a single error item if the file cannot be
        parsed, so the reviewer is notified rather than silently missing items.
        """
        path = self.config_path
        if path is None:
            return []

        path = Path(path)
        if not path.exists():
            return [self._error(path, f"File not found: '{path}'")]

        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            return [self._error(path, f"JSON parse error — {exc}")]
        except OSError as exc:
            return [self._error(path, f"Could not read file — {exc}")]

        if not isinstance(data, dict) or "items" not in data:
            return [self._error(
                path,
                'Expected a JSON object with an "items" array at the top level.'
            )]

        items = []
        for entry in data.get("items", []):
            if not isinstance(entry, dict):
                continue
            if not entry.get("enabled", True):
                continue
            message = str(entry.get("message", "")).strip()
            if not message:
                continue
            items.append(ChecklistItem(
                category=str(entry.get("category", "manual")).strip(),
                message=message,
                detail=str(entry.get("detail", "")).strip(),
                line=None,
                score=None,
            ))

        return items

    @classmethod
    def write_example(cls, path: Path) -> None:
        """Write a starter .checklist.json to *path*."""
        path = Path(path)
        if path.exists():
            raise FileExistsError(
                f"'{path}' already exists. Remove it or choose a different path."
            )
        path.write_text(
            json.dumps(_EXAMPLE_CONFIG, indent=2) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def resolve_for_project(cls, project_dir: Path) -> Optional[Path]:
        """Return the default config path under *project_dir* if it exists."""
        candidate = Path(project_dir) / DEFAULT_CONFIG_NAME
        return candidate if candidate.exists() else None

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _error(path: Path, reason: str) -> ChecklistItem:
        return ChecklistItem(
            category="manual",
            message=f"Static checklist config error: {path.name}",
            detail=(
                f"Could not load user-defined checklist from '{path}'.\n"
                f"Reason: {reason}\n"
                f"Run  python review.py --checklist-init  to create a valid template."
            ),
        )
