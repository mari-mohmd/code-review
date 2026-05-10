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
 Description: Scenario for detecting path coherence issues
 Usage      : Execute the "run.sh" file included within the project
===============================================================================
"""

import os

# Create 'logs' directory
os.makedirs("/var/logs")
# Create a logfile inside 'logs' directory
# BUG: Log file is created outside the log directory (should be inside!!)
with open("/var/app.log", mode="a") as log:
    pass
