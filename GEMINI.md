# Maze Crawler - Project Instructions

## Overview
This project is an entry for the Kaggle Maze Crawler competition, a 1v1 strategy simulation.

## Core Mandates
- **Stability First:** All code must be strictly typed and wrapped in error boundaries.
- **Zero Friendly Fire:** Never issue an action that could lead to a self-crush or same-type collision.
- **GitHub-First Workflow:** Every major strategic breakthrough must be committed to the `fs0cietyx/maze-crawler` repository.
- **Telemetry Policy:** Use structured logging instead of `print()` for production-bound code.

## Monitoring Strategy (Active Phase)
1.  **Leaderboard Watch:** Track the $\mu$ (skill) and $\sigma$ (uncertainty) of the active submission.
2.  **Loss Forensics:** When a match is lost, download the `replay.json` and identify if the cause was:
    - **Resource Starvation:** Factory ran out of energy.
    - **Boundary Elimination:** Factory was too slow to move North.
    - **Hostile Trapping:** Opponent workers built walls to block our path.

## Maintenance Gateway
Any modifications to the core engine in `main.py` MUST be verified via `make test` before being committed or submitted to Kaggle.
