# Decision Log - Maze Crawler

## 2026-06-07
### Use Python & `kaggle-environments`
- **Decision:** Use the standard Python stack recommended by Kaggle.
- **Rationale:** Native support, easy testing, and rich library ecosystem (NumPy, etc.).
- **Revisit:** Not planned.

### Survival First Strategy
- **Decision:** Prioritize Factory movement and energy collection over aggressive combat.
- **Rationale:** The competition is a 1v1 survival game where the "ground vanishes." Survival is the primary win condition.
- **Revisit:** After achieving a stable top-tier survival rank on the leaderboard.

### Modular Agent Design
- **Decision:** Structure the agent code into `ObservationProcessor`, `Pathfinder`, and `ActionGenerator`.
- **Rationale:** Eases testing and allows swapping logic (e.g., different pathfinding algorithms).
- **Revisit:** During the first major refactor.
