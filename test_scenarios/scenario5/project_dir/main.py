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
 Description: Scenario for detecting lifecycle completeness
 Usage      : Execute the "run.sh" file included within the project
===============================================================================
"""

class Executor:
    def __enter__(self):
        self.start()
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    def start(self):
        # do something
        pass

    def stop(self):
        # stop
        pass


e = Executor()
e.start()
# BUG: Lifecycle is not complete. 'e.stop()' was never called!!
