import json
import random
import multiprocessing
from kaggle_environments import make

def run_single_game(seed):
    try:
        env = make("crawl", debug=False, configuration={"randomSeed": seed})
        # Run against random
        env.run(["../main.py", "random"])
        
        final_state = env.steps[-1]
        p1_reward = final_state[0].reward
        p2_reward = final_state[1].reward
        p1_status = final_state[0].status
        
        result = "VICTORY" if p1_reward > p2_reward else "DEFEAT" if p1_reward < p2_reward else "DRAW"
        
        if result == "DEFEAT":
            replay_file = f"failure_seed_{seed}.json"
            with open(replay_file, "w") as f:
                json.dump(env.toJSON(), f)
            return (seed, result, p1_reward, p1_status, replay_file)
        
        return (seed, result, p1_reward, p1_status, None)
    except Exception as e:
        return (seed, "CRASH", 0, str(e), None)

def run_exhaustive_test(num_games=100):
    print(f"Initializing exhaustive stress test: {num_games} parallel games...")
    seeds = [random.randint(0, 1000000) for _ in range(num_games)]
    
    with multiprocessing.Pool(processes=multiprocessing.cpu_count()) as pool:
        results = pool.map(run_single_game, seeds)
    
    victories = [r for r in results if r[1] == "VICTORY"]
    defeats = [r for r in results if r[1] == "DEFEAT"]
    draws = [r for r in results if r[1] == "DRAW"]
    crashes = [r for r in results if r[1] == "CRASH"]
    
    print("\n--- FINAL EXHAUSTIVE SUMMARY ---")
    print(f"Victories: {len(victories)}")
    print(f"Defeats:   {len(defeats)}")
    print(f"Draws:     {len(draws)}")
    print(f"Crashes:   {len(crashes)}")
    
    if defeats:
        print("\nFailure Seeds:")
        for r in defeats:
            print(f"- Seed: {r[0]} | Reward: {r[2]} | Status: {r[3]} | File: {r[4]}")
            
    if crashes:
        print("\nCrash Seeds:")
        for r in crashes:
            print(f"- Seed: {r[0]} | Error: {r[3]}")

if __name__ == "__main__":
    run_exhaustive_test()
