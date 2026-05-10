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
 Description: Scenario for detecting name similarity issues
 Usage      : Execute the "run.sh" file included within the project
===============================================================================
"""

sensors = []

component_name = ""

if sensors:
    component_name = sensors[0]
else:
    # # BUG: 'component_name' NOT 'componentName'
    componentName = "Not a sensor"
