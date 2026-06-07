# Decision Log - Maze Crawler

## 2026-06-07 (Hyper-Optimization Strategy)

### 1. Dynamic Weight A* (DWA*)
- **Decision:** Apply an exponential penalty `max(0, 15 - dist_to_death) ** 2` to cell costs near the southern boundary.
- **Rationale:** Linear penalties were insufficient to prevent Factory elimination during late-game scroll ramps. Exponential costs force the agent to prioritize northern movement above all else when risk is high.

### 2. Predictive Destination Reservation
- **Decision:** Finalize a turn-ahead simulation loop for all friendly coordinates.
- **Rationale:** Absolute guarantee of zero friendly fire. By processing units in crush-hierarchy order, we ensure high-value units (Factories/Miners) never lose a turn to low-value unit path blocking.

### 3. Latent Adversarial Evasion
- **Decision:** Factory will prioritize lateral JUMPs (East/West) over northward movement when an enemy Factory is within 2 cells.
- **Rationale:** Prevents mutual annihilation "Factory-crushes" that result in draws, preserving our Factory for a high-reward win.

### 4. Asynchronous Energy Refueling
- **Decision:** Robots will detour to the nearest mine or Factory when energy < 30, but only if they don't have a high-value crystal target.
- **Rationale:** Balances resource acquisition with operational uptime.
