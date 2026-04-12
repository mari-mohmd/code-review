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
 Description: Scenario for detecting hardcoded paths
 Usage      : Execute the "run.sh" file included within the project
===============================================================================
"""
from pathlib import Path

# Create "logs" dir and log file
Log_dir = "/var/logs"
Path(Log_dir).mkdir(parents=True, exist_ok=True)
Path(Log_dir+ "/log_file.log").mkdir()