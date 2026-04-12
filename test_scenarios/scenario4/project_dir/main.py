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
 Description: Scenario for detecting input and concurrency issues
 Usage      : Execute the "run.sh" file included within the project
===============================================================================
"""
import subprocess

filename = input("Enter file to create: ")
subprocess.run(f"touch {filename}", shell=True)