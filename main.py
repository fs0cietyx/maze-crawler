import logging
import random
import heapq
import sys
from typing import Dict, List, Tuple, Set, Optional, Any

# ==========================================
# 1. TELEMETRY & LOGGING (Zero Print Statements)
# ==========================================
logger = logging.getLogger("maze_crawler_engine")
logger.setLevel(logging.WARNING) # Set to INFO or DEBUG for local trace
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter('%(levelname)s - Step:%(step)s - %(message)s'))
if not logger.handlers:
    logger.addHandler(handler)

# Inject step into logs
class StepFilter(logging.Filter):
    def __init__(self):
        self.step = 0
    def filter(self, record):
        record.step = self.step
        return True
step_filter = StepFilter()
logger.addFilter(step_filter)


# ==========================================
# 2. TYPE SAFETY & SCHEMAS
# ==========================================
Coord = Tuple[int, int]
RobotUID = str
WallBitfield = int

NORTH = 1
EAST = 2
SOUTH = 4
WEST = 8

ACTION_NORTH = "NORTH"
ACTION_SOUTH = "SOUTH"
ACTION_EAST = "EAST"
ACTION_WEST = "WEST"
ACTION_IDLE = "IDLE"

TYPE_FACTORY = 0
TYPE_SCOUT = 1
TYPE_WORKER = 2
TYPE_MINER = 3

class RobotData:
    __slots__ = ['uid', 'rtype', 'col', 'row', 'energy', 'owner', 'move_cd', 'jump_cd', 'build_cd']
    def __init__(self, uid: str, data: List[int]):
        self.uid = uid
        self.rtype = data[0]
        self.col = data[1]
        self.row = data[2]
        self.energy = data[3]
        self.owner = data[4]
        self.move_cd = data[5]
        self.jump_cd = data[6]
        self.build_cd = data[7] if len(data) > 7 else 0
        
    @property
    def pos(self) -> Coord:
        return (self.col, self.row)

# ==========================================
# 3. GAME STATE ENGINE
# ==========================================
class GameState:
    def __init__(self, config: Any):
        self.config = config
        self.width: int = config.width
        self.height: int = config.height
        self.walls: Dict[Coord, WallBitfield] = {}
        self.mines: Dict[Coord, List[int]] = {}
        self.crystals: Dict[Coord, int] = {}
        self.mining_nodes: Set[Coord] = set()
        self.persistent_mining_nodes: Set[Coord] = set()
        self.my_robots: Dict[RobotUID, RobotData] = {}
        self.enemy_robots: Dict[RobotUID, RobotData] = {}
        self.step: int = 0
        self.player: int = 0
        self.south_bound: int = 0
        self.north_bound: int = 0

    def update(self, obs: Any):
        self.step = obs.step
        step_filter.step = self.step
        self.player = obs.player
        self.south_bound = obs.southBound
        self.north_bound = obs.northBound
        
        # Clear ephemeral state
        self.crystals.clear()
        self.mining_nodes.clear()
        self.my_robots.clear()
        self.enemy_robots.clear()

        # Parse Walls (Permanent)
        for row in range(self.south_bound, self.north_bound + 1):
            for col in range(self.width):
                idx = (row - self.south_bound) * self.width + col
                if 0 <= idx < len(obs.walls) and obs.walls[idx] != -1:
                    self.walls[(col, row)] = obs.walls[idx]
        
        # Parse Ephemerals
        for pos_str, energy in obs.crystals.items():
            c, r = map(int, pos_str.split(','))
            self.crystals[(c, r)] = energy

        for pos_str, _ in obs.miningNodes.items():
            c, r = map(int, pos_str.split(','))
            self.mining_nodes.add((c, r))
            self.persistent_mining_nodes.add((c, r))

        for pos_str, data in obs.mines.items():
            c, r = map(int, pos_str.split(','))
            self.mines[(c, r)] = data

        # Parse Units
        for uid, data in obs.robots.items():
            robot = RobotData(uid, data)
            if robot.owner == self.player:
                self.my_robots[uid] = robot
            else:
                self.enemy_robots[uid] = robot


# ==========================================
# 4. SPATIAL ENGINE (Pathfinding & Topology)
# ==========================================
class SpatialEngine:
    def __init__(self, state: GameState):
        self.state = state

    def get_neighbors(self, pos: Coord) -> List[Tuple[Coord, str]]:
        col, row = pos
        neighbors = []
        wall_val = self.state.walls.get(pos, -1)
        if wall_val == -1: return neighbors # Do not route through fog
        
        if not (wall_val & NORTH): neighbors.append(((col, row + 1), ACTION_NORTH))
        if not (wall_val & EAST): neighbors.append(((col + 1, row), ACTION_EAST))
        if not (wall_val & SOUTH): neighbors.append(((col, row - 1), ACTION_SOUTH))
        if not (wall_val & WEST): neighbors.append(((col - 1, row), ACTION_WEST))
        return neighbors

    def manhattan_distance(self, a: Coord, b: Coord) -> int:
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    def find_path(self, start: Coord, goal: Coord, max_nodes: int = 400) -> Optional[List[str]]:
        if start == goal: return []
        
        frontier = [(0, start)]
        came_from: Dict[Coord, Optional[Coord]] = {start: None}
        action_to_reach: Dict[Coord, Optional[str]] = {start: None}
        cost_so_far: Dict[Coord, int] = {start: 0}
        nodes_evaluated = 0

        while frontier:
            if nodes_evaluated > max_nodes:
                break # Compute Circuit Breaker
            _, current = heapq.heappop(frontier)
            nodes_evaluated += 1

            if current == goal: break

            for next_pos, action in self.get_neighbors(current):
                # Critical Survival: Never route below south bound
                if next_pos[1] <= self.state.south_bound: continue
                    
                new_cost = cost_so_far[current] + 1
                if next_pos not in cost_so_far or new_cost < cost_so_far[next_pos]:
                    cost_so_far[next_pos] = new_cost
                    priority = new_cost + self.manhattan_distance(goal, next_pos)
                    heapq.heappush(frontier, (priority, next_pos))
                    came_from[next_pos] = current
                    action_to_reach[next_pos] = action

        if goal not in came_from: return None

        path = []
        curr = goal
        while curr != start:
            act = action_to_reach[curr]
            if act is not None: path.append(act)
            curr = came_from[curr] # type: ignore
        path.reverse()
        return path


# ==========================================
# 5. ACTION DISPATCHER & COLLISION MATRIX
# ==========================================
class ActionDispatcher:
    def __init__(self, state: GameState, spatial: SpatialEngine):
        self.state = state
        self.spatial = spatial
        self.reserved_cells: Dict[Coord, RobotUID] = {}

    def is_safe(self, uid: RobotUID, current_pos: Coord, action: str) -> Tuple[bool, Coord]:
        col, row = current_pos
        next_pos = current_pos
        if action == ACTION_NORTH: next_pos = (col, row + 1)
        elif action == ACTION_SOUTH: next_pos = (col, row - 1)
        elif action == ACTION_EAST: next_pos = (col + 1, row)
        elif action == ACTION_WEST: next_pos = (col - 1, row)
        elif action.startswith("JUMP"):
            if "NORTH" in action: next_pos = (col, row + 2)
            elif "SOUTH" in action: next_pos = (col, row - 2)
            elif "EAST" in action: next_pos = (col + 2, row)
            elif "WEST" in action: next_pos = (col - 2, row)
        elif action.startswith("BUILD"):
            next_pos = (col, row + 1)

        if next_pos in self.reserved_cells:
            return False, next_pos
        return True, next_pos

    def dispatch(self) -> Dict[RobotUID, str]:
        actions = {}
        self.reserved_cells.clear()
        
        # Order by Crush Hierarchy ensures heavy units get spatial priority
        sorted_robots = sorted(self.state.my_robots.values(), key=lambda r: r.rtype)
        factory_pos = next((r.pos for r in sorted_robots if r.rtype == TYPE_FACTORY), None)

        for robot in sorted_robots:
            try:
                if robot.rtype == TYPE_FACTORY: act = self._decide_factory(robot)
                elif robot.rtype == TYPE_SCOUT: act = self._decide_scout(robot, factory_pos)
                elif robot.rtype == TYPE_WORKER: act = self._decide_worker(robot, factory_pos)
                elif robot.rtype == TYPE_MINER: act = self._decide_miner(robot)
                else: act = ACTION_IDLE
            except Exception as e:
                logger.error(f"Fallback trigged for UID {robot.uid}: {e}")
                act = ACTION_NORTH

            safe, n_pos = self.is_safe(robot.uid, robot.pos, act)
            if safe:
                actions[robot.uid] = act
                self.reserved_cells[n_pos] = robot.uid
                if act.startswith("BUILD"):
                    self.reserved_cells[robot.pos] = robot.uid # Factory doesn't move when building
            else:
                actions[robot.uid] = ACTION_IDLE
                self.reserved_cells[robot.pos] = robot.uid

        return actions

    def _get_tx(self, r: RobotData, t_pos: Optional[Coord]) -> Optional[str]:
        if not t_pos: return None
        if self.spatial.manhattan_distance(r.pos, t_pos) == 1:
            w = self.state.walls.get(r.pos, 0)
            if t_pos[1] > r.row and not (w & NORTH): return "TRANSFER_NORTH"
            if t_pos[1] < r.row and not (w & SOUTH): return "TRANSFER_SOUTH"
            if t_pos[0] > r.col and not (w & EAST): return "TRANSFER_EAST"
            if t_pos[0] < r.col and not (w & WEST): return "TRANSFER_WEST"
        return None

    def _decide_factory(self, r: RobotData) -> str:
        # 0. Defensive Maneuvering: Avoid enemy factories
        enemy_factories = [e for e in self.state.enemy_robots.values() if e.rtype == TYPE_FACTORY]
        for ef in enemy_factories:
            dist = self.spatial.manhattan_distance(r.pos, ef.pos)
            if dist <= 2:
                # Try to move away or jump
                if r.jump_cd == 0:
                    # Jump in opposite direction if safe
                    if ef.col > r.col: return "JUMP_WEST"
                    if ef.col < r.col: return "JUMP_EAST"
                    if ef.row > r.row: return "JUMP_SOUTH"
                    if ef.row < r.row: return "JUMP_NORTH"
                return ACTION_NORTH # Default to pushing north to avoid boundary

        # 1. Escalating Survival Buffer based on ramp speed
        buffer = 5 if self.state.step < 350 else 8

        if r.row < self.state.south_bound + buffer:
            if r.jump_cd == 0 and (self.state.walls.get(r.pos, 0) & NORTH):
                return "JUMP_NORTH"
            return ACTION_NORTH
            
        if r.build_cd == 0:
            miners = sum(1 for rob in self.state.my_robots.values() if rob.rtype == TYPE_MINER)
            workers = sum(1 for rob in self.state.my_robots.values() if rob.rtype == TYPE_WORKER)
            scouts = sum(1 for rob in self.state.my_robots.values() if rob.rtype == TYPE_SCOUT)
            
            if r.energy >= self.state.config.minerCost and miners < 2: return "BUILD_MINER"
            if r.energy >= self.state.config.workerCost and workers < 3: return "BUILD_WORKER"
            if r.energy >= self.state.config.scoutCost and scouts < 5: return "BUILD_SCOUT"
            
        if self.state.step > 350 and r.move_cd == 0: return ACTION_NORTH
        return ACTION_IDLE

    def _decide_scout(self, r: RobotData, f_pos: Optional[Coord]) -> str:
        tx = self._get_tx(r, f_pos)
        if tx: return tx
        if r.energy < 20 or r.energy > 80:
            if f_pos:
                p = self.spatial.find_path(r.pos, f_pos)
                if p: return p[0]
        if self.state.crystals:
            closest = min(self.state.crystals.keys(), key=lambda c: self.spatial.manhattan_distance(r.pos, c))
            p = self.spatial.find_path(r.pos, closest)
            if p: return p[0]
        return ACTION_NORTH

    def _decide_worker(self, r: RobotData, f_pos: Optional[Coord]) -> str:
        tx = self._get_tx(r, f_pos)
        if tx: return tx
        
        # Defensive Wall Clearing
        if f_pos and f_pos[1] < r.row and self.spatial.manhattan_distance(r.pos, f_pos) < 3:
            if (self.state.walls.get(r.pos, 0) & NORTH) and r.energy >= self.state.config.wallRemoveCost:
                return "REMOVE_NORTH"
                
        if r.energy < 50 or r.energy >= 250:
            if f_pos:
                p = self.spatial.find_path(r.pos, f_pos)
                if p: return p[0]
        if self.state.crystals:
            closest = min(self.state.crystals.keys(), key=lambda c: self.spatial.manhattan_distance(r.pos, c))
            p = self.spatial.find_path(r.pos, closest)
            if p: return p[0]
        return ACTION_NORTH

    def _decide_miner(self, r: RobotData) -> str:
        if r.pos in self.state.mining_nodes and r.energy >= self.state.config.transformCost:
            return "TRANSFORM"
        
        # Filter nodes that already have mines
        available_nodes = [n for n in self.state.persistent_mining_nodes if n not in self.state.mines]
        
        if available_nodes:
            closest = min(available_nodes, key=lambda n: self.spatial.manhattan_distance(r.pos, n))
            p = self.spatial.find_path(r.pos, closest)
            if p: return p[0]
        return ACTION_NORTH

# ==========================================
# 6. KAGGLE ENVIRONMENT ENTRYPOINT
# ==========================================
_game_state: Optional[GameState] = None

def agent(obs: Any, config: Any) -> Dict[str, str]:
    global _game_state
    try:
        if _game_state is None:
            _game_state = GameState(config)
            # Absolute determinism lock based on provided seed or universal constant
            random.seed(config.randomSeed if hasattr(config, 'randomSeed') and config.randomSeed else 1337)
            
        _game_state.update(obs)
        spatial = SpatialEngine(_game_state)
        dispatcher = ActionDispatcher(_game_state, spatial)
        return dispatcher.dispatch()
        
    except Exception as e:
        logger.error(f"FATAL ERROR CAUGHT AT ROOT BOUNDARY: {e}", exc_info=True)
        # Ultimate Fallback: Ensure Factory attempts to survive, others IDLE
        fallback = {}
        if obs and hasattr(obs, 'robots'):
            for uid, data in obs.robots.items():
                if data[4] == obs.player:
                    fallback[uid] = ACTION_NORTH if data[0] == TYPE_FACTORY else ACTION_IDLE
        return fallback
