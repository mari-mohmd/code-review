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
 Description: Scenario for detecting structural divergence
 Usage      : Execute the "run.sh" file included within the project
===============================================================================
"""

class Sensor:
    # Common sensor properties
    pass

class LightSensor(Sensor):
    type = "Light"

    def __str__(self):
        return self.type

class HeatSensor(Sensor):
    type = "Light"  # Simulated copy and paste mistake.

    def __str__(self):
        return self.type


def main():
    ls = LightSensor()
    hs = HeatSensor()
    print(ls)
    print(hs)


main()
