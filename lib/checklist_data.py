"""
===============================================================================
 Project    : A Lightweight Methodology for Verifying Intended
                       Logic During Code Review
 File       : main.py
 Author(s)  : Mohammad Mari, Lian Wen
 Affiliation: School of ICT, Griffith University
 Contact    : mohammad.mari@griffithuni.edu.au
 Created    : 2026
 License    : MIT License (see LICENSE file for details)
 Description: Checklist data structure
 Usage      : Supplementary file. see review.py
===============================================================================
"""
from dataclasses import dataclass
from typing import Optional

@dataclass
class ChecklistItem:
    category: str   # linkage  | lifecycle | structural | etc
    message: str
    detail: str = ""
    line: Optional[int] = None
    score: Optional[float] = None