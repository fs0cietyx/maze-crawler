import json
from kaggle_environments import make

def run_benchmark():
    print("Initializing local benchmark against 'random' baseline...")
    env = make("crawl", debug=True, configuration={"randomSeed": 42})
    
    # Run the match
    env.run(["../main.py", "random"])
    
    # Analyze results
    final_state = env.steps[-1]
    p1_reward = final_state[0].reward
    p2_reward = final_state[1].reward
    p1_status = final_state[0].status
    p2_status = final_state[1].status
    
    print("\n--- BENCHMARK RESULTS ---")
    print(f"Agent Status: {p1_status} | Reward: {p1_reward}")
    print(f"Opponent Status: {p2_status} | Reward: {p2_reward}")
    
    if p1_reward > p2_reward:
        print("RESULT: VICTORY")
    elif p1_reward < p2_reward:
        print("RESULT: DEFEAT")
    else:
        print("RESULT: DRAW")
        
    print("\nSaving replay to replay.json...")
    with open("replay.json", "w") as f:
        json.dump(env.toJSON(), f)
    print("Done. You can upload replay.json to Kaggle's visualizer to review the match.")

if __name__ == "__main__":
    run_benchmark()
