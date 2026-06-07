from kaggle_environments import make
from agent import agent

def test():
    env = make("crawl", debug=True)
    env.run([agent, agent])
    print(env.render(mode="ansi"))
    
    # Check if there were any errors
    for state in env.state:
        if state.status == "ERROR":
            print(f"Agent error: {state.observation.remainingOverageTime}")

if __name__ == "__main__":
    test()
