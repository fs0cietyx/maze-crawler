# 🤖 My First Kaggle Competition: Maze Crawler

Welcome! This is my entry for the **Google Maze Crawler** competition on Kaggle. It's an infinite scrolling strategy game where you have to lead a robot expedition through a shifting, fog-shrouded maze.

I built this agent to learn more about AI strategy, pathfinding, and resource management.

---

## 🎮 The Challenge
In this game, the floor is literally disappearing! A southern boundary moves up the map, and if your "Factory" gets caught, it's game over. You have to:
*   **Explore:** Send out Scouts to see through the "Fog of War."
*   **Gather:** Use Workers to pick up energy crystals.
*   **Expand:** Use Miners to build energy mines on special nodes.
*   **Survive:** Keep moving North and avoid crashing into your own robots!

---

## 🧠 My Strategy
For this agent, I focused on a few core ideas to keep it running as long as possible:
*   **A* Pathfinding:** I implemented a pathfinding algorithm to help my robots find the best way around walls and through the maze.
*   **Safety First:** I created a "collision system" so my robots don't accidentally run into each other (friendly fire is real in this game!).
*   **The Survival Buffer:** My Factory always tries to stay a safe distance away from the bottom of the map, especially as the game speeds up.
*   **Energy Management:** Robots will automatically head back to the Factory to deliver energy or refuel when they get low.

---

## 📂 What's Inside?
*   `main.py`: The final version of my agent that I upload to Kaggle.
*   `src/agent.py`: My working "draft" where I test out new ideas.
*   `src/pathfinding.py`: The logic that helps my robots navigate.
*   `src/benchmark.py`: A script I use to test my bot against a "random" opponent on my own computer.
*   `Makefile`: Some handy shortcuts for testing and submitting.

---

## 🚀 How to Try It
If you want to run this locally, you'll need Python and the `kaggle-environments` library.

1.  **Install the environment:**
    ```bash
    pip install kaggle-environments
    ```
2.  **Run a test match:**
    ```bash
    make test
    ```
3.  **Submit to Kaggle:**
    (If you have the Kaggle CLI set up)
    ```bash
    make submit
    ```

---

## 🛡️ A Note on Security
I've set this up so that no private API keys or tokens are stored in this folder. All my Kaggle credentials stay safe on my own machine and are never uploaded to GitHub.

---

## 📈 Next Steps
I'm still learning! My next goals are to:
1.  Make my Workers build walls to trap the opponent.
2.  Improve how my Scouts explore the map more efficiently.

Thanks for checking out my first Kaggle project!
