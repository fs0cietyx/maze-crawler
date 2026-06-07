import random
from pathfinding import Pathfinder

class Memory:
    def __init__(self, width):
        self.width = width
        self.walls = {} # (col, row) -> wall_bitfield
        self.mines = {} # (col, row) -> [energy, maxEnergy, owner]

    def update(self, obs):
        # Update walls
        for row in range(obs.southBound, obs.northBound + 1):
            for col in range(self.width):
                idx = (row - obs.southBound) * self.width + col
                if 0 <= idx < len(obs.walls) and obs.walls[idx] != -1:
                    self.walls[(col, row)] = obs.walls[idx]
        
        # Update mines (they are remembered once discovered)
        for pos_str, mine_data in obs.mines.items():
            col, row = map(int, pos_str.split(','))
            self.mines[(col, row)] = mine_data

    def get_wall(self, col, row):
        return self.walls.get((col, row), -1)

class GoalOrientedAgent:
    def __init__(self, config):
        self.config = config
        self.memory = Memory(config.width)
        self.pf = Pathfinder(config.width, config.height)

    def get_action(self, obs):
        self.memory.update(obs)
        actions = {}
        reserved_cells = set() # (col, row)
        
        my_robots = {
            uid: data for uid, data in obs.robots.items()
            if data[4] == obs.player
        }

        # Priority: Factory > Miner > Worker > Scout (to match crush hierarchy for safety)
        priority_uids = sorted(my_robots.keys(), key=lambda x: my_robots[x][0])

        for uid in priority_uids:
            data = my_robots[uid]
            rtype, col, row, energy, owner, move_cd, jump_cd, build_cd = data
            
            # Get suggested action
            if rtype == 0: # FACTORY
                act = self.handle_factory(uid, data, obs)
            elif rtype == 1: # SCOUT
                act = self.handle_scout(uid, data, obs)
            elif rtype == 2: # WORKER
                act = self.handle_worker(uid, data, obs)
            elif rtype == 3: # MINER
                act = self.handle_miner(uid, data, obs)
            else:
                act = "IDLE"

            # Validate collision
            final_act, next_pos = self.resolve_collision(uid, data, act, reserved_cells, obs)
            actions[uid] = final_act
            reserved_cells.add(next_pos)
                
        return actions

    def resolve_collision(self, uid, data, action, reserved_cells, obs):
        rtype, col, row, energy, owner, move_cd, jump_cd, build_cd = data
        
        # Calculate next position
        next_pos = (col, row)
        if action == "NORTH": next_pos = (col, row + 1)
        elif action == "SOUTH": next_pos = (col, row - 1)
        elif action == "EAST": next_pos = (col + 1, row)
        elif action == "WEST": next_pos = (col - 1, row)
        elif action.startswith("JUMP"):
            # Jumps move 2 cells
            if "NORTH" in action: next_pos = (col, row + 2)
            elif "SOUTH" in action: next_pos = (col, row - 2)
            elif "EAST" in action: next_pos = (col + 2, row)
            elif "WEST" in action: next_pos = (col - 2, row)
        elif action.startswith("BUILD"):
            # Spawning cell is NORTH of factory
            spawn_pos = (col, row + 1)
            if spawn_pos in reserved_cells:
                # Can't build if something is there
                return "IDLE", (col, row)
            # Reserved BOTH factory position and spawn position? 
            # Actually, the factory doesn't move when building.
            # But the new robot will occupy spawn_pos.
            reserved_cells.add(spawn_pos) 
            return action, (col, row)

        # If next_pos is already reserved, try to IDLE
        if next_pos != (col, row) and next_pos in reserved_cells:
            return "IDLE", (col, row)
            
        return action, next_pos

    def handle_factory(self, uid, data, obs):
        rtype, col, row, energy, owner, move_cd, jump_cd, build_cd = data
        
        # 1. Survival: Stay ahead of the southern boundary
        # If we are too close to southBound, move North
        if row < obs.southBound + 4:
            return "NORTH"
            
        # 2. Production: Build units if we have energy
        if energy >= self.config.minerCost and build_cd == 0:
            return "BUILD_MINER"
        if energy >= self.config.workerCost and build_cd == 0:
            return "BUILD_WORKER"
        if energy >= self.config.scoutCost and build_cd == 0:
            return "BUILD_SCOUT"
            
        # 3. Strategy: Move North slowly to explore
        if move_cd == 0:
            return "NORTH"
            
        return "IDLE"

    def handle_scout(self, uid, data, obs):
        rtype, col, row, energy, owner, move_cd, jump_cd, build_cd = data
        factory_pos = self.find_factory_pos(obs)
        
        # 1. Transfer energy to factory if adjacent
        transfer_act = self.get_transfer_action(col, row, factory_pos, obs)
        if transfer_act: return transfer_act

        # 2. Return to factory if low on energy or carrying a lot
        if energy < 20 or energy > 80:
            if factory_pos:
                path = self.pf.find_path((col, row), factory_pos, obs.walls, obs.southBound)
                if path: return path[0]

        # 3. Harvest mines if any are nearby and have energy
        if self.memory.mines:
            closest_mine = self.find_closest_mine_to_harvest(col, row)
            if closest_mine:
                path = self.pf.find_path((col, row), closest_mine, obs.walls, obs.southBound)
                if path: return path[0]

        # 4. Target crystals if visible
        if obs.crystals:
            closest_crystal = self.find_closest(col, row, obs.crystals.keys())
            if closest_crystal:
                path = self.pf.find_path((col, row), closest_crystal, obs.walls, obs.southBound)
                if path: return path[0]
                
        return "NORTH"

    def handle_worker(self, uid, data, obs):
        rtype, col, row, energy, owner, move_cd, jump_cd, build_cd = data
        factory_pos = self.find_factory_pos(obs)

        # 1. Transfer energy to factory if adjacent
        transfer_act = self.get_transfer_action(col, row, factory_pos, obs)
        if transfer_act: return transfer_act

        # 2. Return to factory if low on energy or carrying a lot
        if energy < 50 or energy > 250:
            if factory_pos:
                path = self.pf.find_path((col, row), factory_pos, obs.walls, obs.southBound)
                if path: return path[0]

        # 3. Target crystals if visible
        if obs.crystals:
            closest_crystal = self.find_closest(col, row, obs.crystals.keys())
            if closest_crystal:
                path = self.pf.find_path((col, row), closest_crystal, obs.walls, obs.southBound)
                if path: return path[0]
        return "NORTH"

    def handle_miner(self, uid, data, obs):
        rtype, col, row, energy, owner, move_cd, jump_cd, build_cd = data
        
        # If we are already a mine (though miners are destroyed on TRANSFORM)
        # In the robots dict, we only see robots, not mines. 
        # Mines are in obs.mines.
        
        if obs.miningNodes:
            closest_node = self.find_closest(col, row, obs.miningNodes.keys())
            if closest_node:
                if (col, row) == closest_node:
                    if energy >= self.config.transformCost:
                        return "TRANSFORM"
                path = self.pf.find_path((col, row), closest_node, obs.walls, obs.southBound)
                if path: return path[0]
                
        return "NORTH"

    def find_factory_pos(self, obs):
        for uid, robot in obs.robots.items():
            if robot[4] == obs.player and robot[0] == 0:
                return (robot[1], robot[2])
        return None

    def get_transfer_action(self, col, row, target_pos, obs):
        if not target_pos: return None
        t_col, t_row = target_pos
        dist = abs(col - t_col) + abs(row - t_row)
        if dist == 1:
            # Check for walls between
            idx = (row - obs.southBound) * self.config.width + col
            w = obs.walls[idx]
            if t_row > row and not (w & 1): return "TRANSFER_NORTH"
            if t_row < row and not (w & 4): return "TRANSFER_SOUTH"
            if t_col > col and not (w & 2): return "TRANSFER_EAST"
            if t_col < col and not (w & 8): return "TRANSFER_WEST"
        return None

    def find_closest_mine_to_harvest(self, col, row):
        closest = None
        min_dist = float('inf')
        for pos, data in self.memory.mines.items():
            # data = [energy, maxEnergy, owner]
            if data[2] == _agent_instance.memory.width: # This is a placeholder for owner check
                # Actually, data[2] is obs.player index.
                pass
            
            # Simple dist check for now
            dist = abs(col - pos[0]) + abs(row - pos[1])
            if dist < min_dist and data[0] > 100: # Only go if mine has energy
                min_dist = dist
                closest = pos
        return closest

    def find_closest(self, col, row, targets):
        min_dist = float('inf')
        closest = None
        for t_str in targets:
            t_col, t_row = map(int, t_str.split(','))
            dist = abs(col - t_col) + abs(row - t_row)
            if dist < min_dist:
                min_dist = dist
                closest = (t_col, t_row)
        return closest

# Global agent instance to persist memory
_agent_instance = None

def agent(obs, config):
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = GoalOrientedAgent(config)
    return _agent_instance.get_action(obs)
