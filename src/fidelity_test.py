import json
from kaggle_environments import make

def run_fidelity_test():
    # Seed 684189691 is from episode-79056770 where the Factory stalled at (14,43)
    fidelity_seeds = [684189691] 
    print(f"Initializing Fidelity Test against historic failure seeds: {fidelity_seeds}")
    
    for seed in fidelity_seeds:
        print(f"\n--- Re-Simulating Historic Failure Scenario (Seed: {seed}) ---")
        env = make("crawl", debug=True, configuration={"randomSeed": seed})
        
        # Run current Apex agent against random baseline
        env.run(["../main.py", "random"])
        
        final_state = env.steps[-1]
        p1_reward = final_state[0].reward
        p2_reward = final_state[1].reward
        p1_status = final_state[0].status
        
        result = "VICTORY" if p1_reward > p2_reward else "DEFEAT" if p1_reward < p2_reward else "DRAW"
        print(f"Historic Scenario Result: {result} | Final Reward: {p1_reward} | Agent Status: {p1_status}")
        
        if result == "DEFEAT":
            print(f"!!! CRITICAL VULNERABILITY: Historic seed {seed} still causes DEFEAT !!!")
        else:
            print(f"Neutralized: Scenario {seed} now results in a DECISIVE VICTORY.")

if __name__ == "__main__":
    run_fidelity_test()
