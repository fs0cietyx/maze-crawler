import logging
import random
import heapq
import sys
import numpy as np
from typing import Dict, List, Tuple, Set, Optional, Any

# ==========================================
# 1. TELEMETRY & HARDENING (Zero Print)
# ==========================================
logger = logging.getLogger("maze_crawler_ultra")
logger.setLevel(logging.WARNING)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter('%(levelname)s - Step:%(step)s - %(message)s'))
if not logger.handlers: logger.addHandler(handler)

class StepFilter(logging.Filter):
    def __init__(self): self.step = 0
    def filter(self, record):
        record.step = self.step
        return True
step_filter = StepFilter()
logger.addFilter(step_filter)

# ==========================================
# 2. TYPE DEFINITIONS & CONSTANTS
# ==========================================
Coord = Tuple[int, int]
RobotUID = str
WallBitfield = int

NORTH, EAST, SOUTH, WEST = 1, 2, 4, 8
ACTION_NORTH, ACTION_SOUTH, ACTION_EAST, ACTION_WEST, ACTION_IDLE = "NORTH", "SOUTH", "EAST", "WEST", "IDLE"
TYPE_FACTORY, TYPE_SCOUT, TYPE_WORKER, TYPE_MINER = 0, 1, 2, 3

CRUSH_HIERARCHY = {TYPE_FACTORY: 4, TYPE_MINER: 3, TYPE_WORKER: 2, TYPE_SCOUT: 1}

# ==========================================
# 3. HIGH-PERFORMANCE STATE ENGINE
# ==========================================
class RobotData:
    __slots__ = ['uid', 'rtype', 'col', 'row', 'energy', 'owner', 'move_cd', 'jump_cd', 'build_cd', 'power']
    def __init__(self, uid: str, data: List[int]):
        self.uid = uid
        self.rtype = data[0]
        self.col, self.row = data[1], data[2]
        self.energy = data[3]
        self.owner = data[4]
        self.move_cd, self.jump_cd = data[5], data[6]
        self.build_cd = data[7] if len(data) > 7 else 0
        self.power = CRUSH_HIERARCHY.get(self.rtype, 0)
        
    @property
    def pos(self) -> Coord: return (self.col, self.row)

class GameState:
    def __init__(self, config: Any):
        self.config = config
        self.width, self.height = config.width, config.height
        self.walls: Dict[Coord, WallBitfield] = {}
        self.persistent_mining_nodes: Set[Coord] = set()
        self.mines: Dict[Coord, List[int]] = {}
        self.crystals: Dict[Coord, int] = {}
        self.my_robots: Dict[RobotUID, RobotData] = {}
        self.enemy_robots: Dict[RobotUID, RobotData] = {}
        self.step, self.player, self.south_bound, self.north_bound = 0, 0, 0, 0

    def update(self, obs: Any):
        self.step = obs.step
        step_filter.step = self.step
        self.player, self.south_bound, self.north_bound = obs.player, obs.southBound, obs.northBound
        
        # Sparse Update Logic
        self.crystals.clear()
        self.my_robots.clear()
        self.enemy_robots.clear()

        # Vectorized-style Parsing (Simulated with efficient dicts)
        for row in range(self.south_bound, self.north_bound + 1):
            s_idx = (row - self.south_bound) * self.width
            row_walls = obs.walls[s_idx : s_idx + self.width]
            for col, w in enumerate(row_walls):
                if w != -1: self.walls[(col, row)] = w
        
        for p_str, energy in obs.crystals.items():
            c, r = map(int, p_str.split(','))
            self.crystals[(c, r)] = energy

        for p_str, _ in obs.miningNodes.items():
            c, r = map(int, p_str.split(','))
            self.persistent_mining_nodes.add((c, r))

        for p_str, data in obs.mines.items():
            c, r = map(int, p_str.split(','))
            self.mines[(c, r)] = data

        for uid, data in obs.robots.items():
            robot = RobotData(uid, data)
            if robot.owner == self.player: self.my_robots[uid] = robot
            else: self.enemy_robots[uid] = robot

# ==========================================
# 4. ULTRA-ACCELERATED NAVIGATION
# ==========================================
class NavigationEngine:
    def __init__(self, state: GameState):
        self.state = state

    def get_neighbors(self, pos: Coord) -> List[Tuple[Coord, str]]:
        c, r = pos
        neighbors = []
        w = self.state.walls.get(pos, -1)
        if w == -1: return neighbors
        if not (w & NORTH) and r + 1 <= self.state.north_bound: neighbors.append(((c, r + 1), ACTION_NORTH))
        if not (w & EAST) and c + 1 < self.state.width: neighbors.append(((c + 1, r), ACTION_EAST))
        if not (w & SOUTH) and r - 1 > self.state.south_bound: neighbors.append(((c, r - 1), ACTION_SOUTH))
        if not (w & WEST) and c - 1 >= 0: neighbors.append(((c - 1, r), ACTION_WEST))
        return neighbors

    def find_path(self, start: Coord, goal: Coord, limit: int = 500) -> Optional[List[str]]:
        if start == goal: return []
        frontier = [(0, start)]
        came_from = {start: None}; actions = {start: None}; cost_so_far = {start: 0}
        evaluated = 0

        while frontier:
            if evaluated > limit: break
            _, curr = heapq.heappop(frontier)
            evaluated += 1
            if curr == goal: break

            for nxt, act in self.get_neighbors(curr):
                # Exponential Boundary Risk Weighting
                dist_to_death = nxt[1] - self.state.south_bound
                risk_penalty = max(0, 15 - dist_to_death) ** 2 if self.state.step > 100 else 0
                
                new_cost = cost_so_far[curr] + 1 + risk_penalty
                if nxt not in cost_so_far or new_cost < cost_so_far[nxt]:
                    cost_so_far[nxt] = new_cost
                    priority = new_cost + abs(goal[0]-nxt[0]) + abs(goal[1]-nxt[1])
                    heapq.heappush(frontier, (priority, nxt))
                    came_from[nxt] = curr; actions[nxt] = act

        if goal not in came_from: return None
        path, c = [], goal
        while c != start:
            path.append(actions[c]); c = came_from[c]
        path.reverse()
        return path

# ==========================================
# 5. TACTICAL DISPATCHER (Hyper-Optimized)
# ==========================================
class TacticalDispatcher:
    def __init__(self, state: GameState, nav: NavigationEngine):
        self.state, self.nav = state, nav
        self.reserved: Dict[Coord, RobotUID] = {}

    def is_safe(self, robot: RobotData, action: str) -> Tuple[bool, Coord]:
        c, r = robot.pos
        nxt = robot.pos
        if action == ACTION_NORTH: nxt = (c, r + 1)
        elif action == ACTION_SOUTH: nxt = (c, r - 1)
        elif action == ACTION_EAST: nxt = (c + 1, r)
        elif action == ACTION_WEST: nxt = (c - 1, r)
        elif action.startswith("JUMP"):
            if "NORTH" in action: nxt = (c, r + 2)
            elif "SOUTH" in action: nxt = (c, r - 2)
            elif "EAST" in action: nxt = (c + 2, r)
            elif "WEST" in action: nxt = (c - 2, r)
        elif action.startswith("BUILD"): nxt = (c, r + 1)

        # 1. Predictive Boundary Check
        if nxt[1] <= self.state.south_bound: return False, robot.pos
        
        # 2. Collision Matrix Check
        if nxt in self.reserved:
            # Hierarchy Check: Can we crush the reserver?
            occupant_uid = self.reserved[nxt]
            occupant = self.state.my_robots.get(occupant_uid)
            if occupant and robot.power > occupant.power:
                return False, robot.pos # Never crush teammates
            return False, robot.pos
            
        # 3. Enemy Crush Logic
        for en in self.state.enemy_robots.values():
            if en.pos == nxt and robot.power <= en.power: return False, robot.pos

        return True, nxt

    def dispatch(self) -> Dict[RobotUID, str]:
        actions = {}
        self.reserved.clear()
        
        # Priority Queue for Action Resolution
        robots = sorted(self.state.my_robots.values(), key=lambda x: -x.power)
        factory = next((r for r in robots if r.rtype == TYPE_FACTORY), None)

        for r in robots:
            try:
                if r.rtype == TYPE_FACTORY: act = self._factory_logic(r)
                elif r.rtype == TYPE_SCOUT: act = self._scout_logic(r, factory)
                elif r.rtype == TYPE_WORKER: act = self._worker_logic(r, factory)
                elif r.rtype == TYPE_MINER: act = self._miner_logic(r)
                else: act = ACTION_IDLE
            except Exception: act = ACTION_NORTH

            safe, nxt = self.is_safe(r, act)
            if safe:
                actions[r.uid] = act; self.reserved[nxt] = r.uid
                if act.startswith("BUILD"): self.reserved[r.pos] = r.uid
            else:
                actions[r.uid] = ACTION_IDLE; self.reserved[r.pos] = r.uid
        return actions

    def _factory_logic(self, r: RobotData) -> str:
        # P1: Survival Calculation
        death_distance = r.row - self.state.south_bound
        buffer = 6 + (self.state.step // 80) # Dynamically widening buffer
        if death_distance < buffer:
            if r.jump_cd == 0 and r.row + 2 <= self.state.north_bound: return "JUMP_NORTH"
            return ACTION_NORTH
            
        # P2: Adversarial Evasion
        for en in self.state.enemy_robots.values():
            if en.rtype == TYPE_FACTORY and self.nav.manhattan_distance(r.pos, en.pos) <= 2:
                if r.jump_cd == 0: return "JUMP_EAST" if r.col < 10 else "JUMP_WEST"
                return ACTION_NORTH

        # P3: Economic Budgeting
        if r.energy > 1000 and r.build_cd == 0:
            counts = {t: sum(1 for rob in self.state.my_robots.values() if rob.rtype == t) for t in [1, 2, 3]}
            if counts[3] < 3 and r.energy > 1500: return "BUILD_MINER"
            if counts[2] < 4 and r.energy > 1200: return "BUILD_WORKER"
            if counts[1] < 6: return "BUILD_SCOUT"
            
        return ACTION_NORTH if self.state.step % 10 == 0 else ACTION_IDLE

    def _energy_dump(self, r: RobotData, f: Optional[RobotData]) -> Optional[str]:
        if not f: return None
        if self.nav.manhattan_distance(r.pos, f.pos) == 1:
            w = self.state.walls.get(r.pos, 0)
            if f.row > r.row and not (w & 1): return "TRANSFER_NORTH"
            if f.row < r.row and not (w & 4): return "TRANSFER_SOUTH"
            if f.col > r.col and not (w & 2): return "TRANSFER_EAST"
            if f.col < r.col and not (w & 8): return "TRANSFER_WEST"
        return None

    def _scout_logic(self, r: RobotData, f: Optional[RobotData]) -> str:
        dump = self._energy_dump(r, f)
        if dump: return dump
        if r.energy < 30 or r.energy > 80:
            if f:
                p = self.nav.find_path(r.pos, f.pos)
                if p: return p[0]
        if self.state.crystals:
            targets = sorted(self.state.crystals.items(), key=lambda x: -x[1]/(self.nav.manhattan_distance(r.pos, x[0])+1))
            p = self.nav.find_path(r.pos, targets[0][0])
            if p: return p[0]
        return self.nav.find_path(r.pos, (r.col, min(r.row + 5, 500)))[0] if self.nav.find_path(r.pos, (r.col, min(r.row + 5, 500))) else ACTION_NORTH

    def _worker_logic(self, r: RobotData, f: Optional[RobotData]) -> str:
        dump = self._energy_dump(r, f)
        if dump: return dump
        
        # Tactical Bottlenecking
        for en in self.state.enemy_robots.values():
            if en.rtype == TYPE_FACTORY and self.nav.manhattan_distance(r.pos, en.pos) < 3:
                if r.energy > 100: return "BUILD_NORTH"
        
        if r.energy < 50 or r.energy > 250:
            if f:
                p = self.nav.find_path(r.pos, f.pos)
                if p: return p[0]
        if self.state.crystals:
            closest = min(self.state.crystals.keys(), key=lambda c: self.nav.manhattan_distance(r.pos, c))
            p = self.nav.find_path(r.pos, closest)
            if p: return p[0]
        return ACTION_NORTH

    def _miner_logic(self, r: RobotData) -> str:
        if r.pos in self.state.persistent_mining_nodes and r.energy >= 100: return "TRANSFORM"
        targets = [n for n in self.state.persistent_mining_nodes if n not in self.state.mines]
        if targets:
            closest = min(targets, key=lambda n: self.nav.manhattan_distance(r.pos, n))
            p = self.nav.find_path(r.pos, closest)
            if p: return p[0]
        return ACTION_NORTH

# ==========================================
# 6. ENTRYPOINT
# ==========================================
_engine: Optional[GameState] = None
def agent(obs: Any, config: Any) -> Dict[str, str]:
    global _engine
    try:
        if _engine is None:
            _engine = GameState(config)
            random.seed(config.randomSeed if hasattr(config, 'randomSeed') and config.randomSeed else 42)
        _engine.update(obs)
        nav = NavigationEngine(_engine)
        return TacticalDispatcher(_engine, nav).dispatch()
    except Exception:
        fallback = {}
        if obs and hasattr(obs, 'robots'):
            for uid, data in obs.robots.items():
                if data[4] == obs.player: fallback[uid] = ACTION_NORTH if data[0] == TYPE_FACTORY else ACTION_IDLE
        return fallback
