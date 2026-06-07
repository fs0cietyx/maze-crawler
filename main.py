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
        self.path_cache: Dict[Tuple[Coord, Coord], List[str]] = {}
        self.risk_matrix = np.zeros((1000, self.width), dtype=np.float32)
        self.enemy_history: Dict[RobotUID, Coord] = {}

    def update(self, obs: Any):
        self.step = obs.step
        step_filter.step = self.step
        self.player, self.south_bound, self.north_bound = obs.player, obs.southBound, obs.northBound
        
        self.crystals.clear()
        self.my_robots.clear()
        self.enemy_robots.clear() # Fix: Must clear every turn
        self.risk_matrix.fill(0)    # Fix: Clear risk matrix every turn
        
        # Track enemy history for velocity prediction
        current_enemies = {}
        for uid, data in obs.robots.items():
            robot = RobotData(uid, data)
            if robot.owner == self.player: self.my_robots[uid] = robot
            else: 
                self.enemy_robots[uid] = robot
                current_enemies[uid] = robot.pos
        
        # Calculate Risk Matrix (Vectorized)
        rows = np.arange(self.south_bound, self.north_bound + 1)
        buffer = 12 + (self.step // 60)
        risk_penalties = np.maximum(0, buffer - (rows - self.south_bound)) ** 2
        # Ensure we don't exceed matrix bounds (though 1000 is usually safe)
        valid_rows = rows[rows < 1000]
        self.risk_matrix[valid_rows, :] = risk_penalties[:len(valid_rows), np.newaxis]
        
        # Add Enemy Proximity Risk
        for en in self.enemy_robots.values():
            if en.rtype == TYPE_FACTORY:
                # Add a Gaussian-like penalty around enemy factory
                r_min, r_max = max(0, en.row - 3), min(999, en.row + 4)
                c_min, c_max = max(0, en.col - 3), min(self.width, en.col + 4)
                for r in range(r_min, r_max):
                    for c in range(c_min, c_max):
                        dist = abs(r - en.row) + abs(c - en.col)
                        if dist <= 3: self.risk_matrix[r, c] += (4 - dist) * 15

        self.enemy_history = current_enemies
        self.path_cache.clear()

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

# ==========================================
# 4. ULTRA-ACCELERATED NAVIGATION
# ==========================================
class NavigationEngine:
    def __init__(self, state: GameState):
        self.state = state

    def get_neighbors(self, pos: Coord, optimistic: bool = False) -> List[Tuple[Coord, str]]:
        c, r = pos
        neighbors = []
        w = self.state.walls.get(pos, -1)
        
        # Optimistic: If unknown cell, assume it's clear
        if w == -1:
            if not optimistic: return []
            w = 0 # Assume no walls
            
        if not (w & NORTH) and r + 1 <= self.state.north_bound: neighbors.append(((c, r + 1), ACTION_NORTH))
        if not (w & EAST) and c + 1 < self.state.width: neighbors.append(((c + 1, r), ACTION_EAST))
        if not (w & SOUTH) and r - 1 > self.state.south_bound: neighbors.append(((c, r - 1), ACTION_SOUTH))
        if not (w & WEST) and c - 1 >= 0: neighbors.append(((c - 1, r), ACTION_WEST))
        return neighbors

    def manhattan_distance(self, p1: Coord, p2: Coord) -> int:
        return abs(p1[0] - p2[0]) + abs(p1[1] - p2[1])

    def find_path(self, start: Coord, goal: Coord, limit: int = 600, optimistic: bool = False) -> Optional[List[str]]:
        if start == goal: return []
        cache_key = (start, goal)
        if not optimistic and cache_key in self.state.path_cache: return self.state.path_cache[cache_key]

        frontier = [(0, start)]
        came_from = {start: None}; actions = {start: None}; cost_so_far = {start: 0}
        evaluated = 0

        while frontier:
            if evaluated > limit: break
            _, curr = heapq.heappop(frontier)
            evaluated += 1
            if curr == goal: break

            for nxt, act in self.get_neighbors(curr, optimistic):
                # O(1) Vectorized Risk Lookup
                risk_penalty = self.state.risk_matrix[nxt[1], nxt[0]] if self.state.step > 50 else 0
                
                new_cost = cost_so_far[curr] + 1 + risk_penalty
                if nxt not in cost_so_far or new_cost < cost_so_far[nxt]:
                    cost_so_far[nxt] = new_cost
                    priority = new_cost + self.manhattan_distance(goal, nxt)
                    heapq.heappush(frontier, (priority, nxt))
                    came_from[nxt] = curr; actions[nxt] = act

        if goal not in came_from: return None
        path, c = [], goal
        while c != start:
            path.append(actions[c]); c = came_from[c]
        path.reverse()
        if not optimistic: self.state.path_cache[cache_key] = path
        return path

# ==========================================
# 5. TACTICAL DISPATCHER (Hyper-Optimized)
# ==========================================
class TacticalDispatcher:
    def __init__(self, state: GameState, nav: NavigationEngine):
        self.state, self.nav = state, nav
        self.reserved: Dict[Coord, RobotUID] = {}

    def is_safe(self, robot: RobotData, action: str, reserved: Set[Coord]) -> Tuple[bool, Coord]:
        c, r = robot.pos
        nxt = (c, r)
        if action == ACTION_NORTH: nxt = (c, r + 1)
        elif action == ACTION_SOUTH: nxt = (c, r - 1)
        elif action == ACTION_EAST: nxt = (c + 1, r)
        elif action == ACTION_WEST: nxt = (c - 1, r)
        elif action.startswith("JUMP"):
            if "NORTH" in action: nxt = (c, r + 2)
            elif "SOUTH" in action: nxt = (c, r - 2)
            elif "EAST" in action: nxt = (c + 2, r)
            elif "WEST" in action: nxt = (c - 2, r)

        # 1. Boundary & Out-of-Bounds (CRITICAL)
        if nxt[1] <= self.state.south_bound or nxt[1] > self.state.north_bound: return False, robot.pos
        if nxt[0] < 0 or nxt[0] >= self.state.width: return False, robot.pos
        
        # 2. Wall Check (Only for simple movement)
        if action in [ACTION_NORTH, ACTION_SOUTH, ACTION_EAST, ACTION_WEST]:
            w = self.state.walls.get(robot.pos, 0)
            if action == ACTION_NORTH and (w & 1): return False, robot.pos
            if action == ACTION_EAST and (w & 2): return False, robot.pos
            if action == ACTION_SOUTH and (w & 4): return False, robot.pos
            if action == ACTION_WEST and (w & 8): return False, robot.pos

        # 3. Collision Matrix Check
        if nxt in reserved: return False, robot.pos
            
        # 4. Enemy Crush Logic
        for en in self.state.enemy_robots.values():
            if en.pos == nxt and robot.power <= en.power: return False, robot.pos

        return True, nxt

    def dispatch(self) -> Dict[RobotUID, str]:
        actions = {}
        reserved_set: Set[Coord] = set()
        intent_reserved: Set[Coord] = set()
        
        # Priority: Factory > Miner > Worker > Scout
        robots = sorted(self.state.my_robots.values(), key=lambda x: -x.power)
        factory = next((r for r in robots if r.rtype == TYPE_FACTORY), None)

        for r in robots:
            chosen_act = ACTION_IDLE
            try:
                if r.rtype == TYPE_FACTORY: chosen_act = self._factory_logic(r)
                elif r.rtype == TYPE_SCOUT: chosen_act = self._scout_logic(r, factory, intent_reserved)
                elif r.rtype == TYPE_WORKER: chosen_act = self._worker_logic(r, factory, intent_reserved)
                elif r.rtype == TYPE_MINER: chosen_act = self._miner_logic(r, intent_reserved)
            except Exception: chosen_act = ACTION_NORTH

            safe, nxt = self.is_safe(r, chosen_act, reserved_set)
            if not safe:
                # Forced Survival/Evasion
                found = False
                # Try all directions (prioritize NORTH)
                for _, act in sorted(self.nav.get_neighbors(r.pos), key=lambda x: 0 if x[1]==ACTION_NORTH else 1):
                    s, n = self.is_safe(r, act, reserved_set)
                    if s:
                        chosen_act = act; nxt = n; found = True
                        break
                
                if not found:
                    # If even neighbors are blocked, try IDLE ONLY if it's boundary-safe
                    s, n = self.is_safe(r, ACTION_IDLE, reserved_set)
                    if s:
                        chosen_act = ACTION_IDLE; nxt = n; found = True
                
                if not found:
                    # Absolute desperation: IDLE and hope for the best
                    chosen_act = ACTION_IDLE; nxt = r.pos

            actions[r.uid] = chosen_act
            reserved_set.add(nxt)
            # For actions that affect a secondary cell (BUILD/REMOVE), we don't strictly reserve the secondary cell
            # because the robot doesn't move there, but we could if we wanted to prevent others moving into the new wall.
            # However, the game allows building a wall even if a robot is moving into that cell.
            
        return actions

    def _factory_logic(self, r: RobotData) -> str:
        # P1: Survival Calculation
        death_distance = r.row - self.state.south_bound
        buffer = 10 + (self.state.step // 50)
        
        if death_distance < buffer:
            # Urgent Northward Movement
            if r.jump_cd == 0:
                for target_row in [r.row + 2, r.row + 1]:
                    if target_row <= self.state.north_bound:
                        for dc in [0, 1, -1, 2, -2]:
                            tc = r.col + dc
                            if 0 <= tc < self.state.width:
                                if target_row == r.row + 2: act = f"JUMP_{'NORTH' if dc==0 else 'EAST' if dc>0 else 'WEST'}"
                                else: act = ACTION_NORTH
                                # Verify safety
                                s, _ = self.is_safe(r, act, set())
                                if s: return act
            
            # Use pathfinding to find a northern escape
            for target_row in range(min(r.row + 10, self.state.north_bound), r.row, -1):
                for dc in [0, 1, -1, 2, -2]:
                    target_pos = (max(0, min(self.state.width - 1, r.col + dc)), target_row)
                    path = self.nav.find_path(r.pos, target_pos, limit=200)
                    if path: return path[0]
            
            return ACTION_NORTH

        # P2: Adversarial Evasion
        for en in self.state.enemy_robots.values():
            if en.rtype == TYPE_FACTORY and self.nav.manhattan_distance(r.pos, en.pos) <= 3:
                # Try to move away from enemy factory
                if r.jump_cd == 0:
                    best_jump = "JUMP_NORTH"
                    max_dist = 0
                    for j_act in ["JUMP_NORTH", "JUMP_EAST", "JUMP_WEST"]:
                        # Simulate jump
                        nc, nr = r.col, r.row
                        if "NORTH" in j_act: nr += 2
                        elif "EAST" in j_act: nc += 2
                        elif "WEST" in j_act: nc -= 2
                        if 0 <= nc < self.state.width and self.state.south_bound < nr <= self.state.north_bound:
                            d = self.nav.manhattan_distance((nc, nr), en.pos)
                            if d > max_dist:
                                max_dist = d; best_jump = j_act
                    return best_jump

        # P3: Economic Budgeting (Strict)
        min_energy = 500 + len(self.state.my_robots) * 50
        if r.energy > min_energy and r.build_cd == 0:
            counts = {t: sum(1 for rob in self.state.my_robots.values() if rob.rtype == t) for t in [1, 2, 3]}
            if counts[3] < 2 and r.energy > 1200: return "BUILD_MINER"
            if counts[2] < 3 and r.energy > 1000: return "BUILD_WORKER"
            if counts[1] < 4 and r.energy > 600: return "BUILD_SCOUT"
            
        # P4: Centering Heuristic
        target_col = self.state.width // 2
        if abs(r.col - target_col) > 1:
            p = self.nav.find_path(r.pos, (target_col, r.row))
            if p: return p[0]

        return ACTION_NORTH if self.state.step % 8 == 0 else ACTION_IDLE

    def _energy_dump(self, r: RobotData, f: Optional[RobotData]) -> Optional[str]:
        if not f: return None
        if self.nav.manhattan_distance(r.pos, f.pos) == 1:
            w = self.state.walls.get(r.pos, 0)
            if f.row > r.row and not (w & 1): return "TRANSFER_NORTH"
            if f.row < r.row and not (w & 4): return "TRANSFER_SOUTH"
            if f.col > r.col and not (w & 2): return "TRANSFER_EAST"
            if f.col < r.col and not (w & 8): return "TRANSFER_WEST"
        return None

    def _scout_logic(self, r: RobotData, f: Optional[RobotData], intent: Set[Coord]) -> str:
        dump = self._energy_dump(r, f)
        if dump: return dump
        
        # Micro-Tactical Kiting
        hostiles = [en for en in self.state.enemy_robots.values() if self.nav.manhattan_distance(r.pos, en.pos) <= 2]
        if hostiles:
            best_move = ACTION_IDLE; max_min_dist = min(self.nav.manhattan_distance(r.pos, h.pos) for h in hostiles)
            for _, act in self.nav.get_neighbors(r.pos):
                safe, nxt = self.is_safe(r, act, set())
                if safe:
                    d = min(self.nav.manhattan_distance(nxt, h.pos) for h in hostiles)
                    if d > max_min_dist: max_min_dist = d; best_move = act
            if best_move != ACTION_IDLE: return best_move

        # Return to base if high energy
        if r.energy > 80 and f:
            p = self.nav.find_path(r.pos, f.pos)
            if p: return p[0]

        if r.energy < 30 and f:
            p = self.nav.find_path(r.pos, f.pos)
            if p: return p[0]
        
        # Collection with Reservation
        available = {pos: e for pos, e in self.state.crystals.items() if pos not in intent}
        if available:
            targets = sorted(available.items(), key=lambda x: -x[1]/(self.nav.manhattan_distance(r.pos, x[0])+1))
            target_pos = targets[0][0]
            intent.add(target_pos)
            p = self.nav.find_path(r.pos, target_pos)
            if p: return p[0]
            
        target_pos = (r.col, min(r.row + 8, self.state.north_bound))
        p = self.nav.find_path(r.pos, target_pos, optimistic=True)
        return p[0] if p else ACTION_NORTH

    def _worker_logic(self, r: RobotData, f: Optional[RobotData], intent: Set[Coord]) -> str:
        dump = self._energy_dump(r, f)
        if dump: return dump
        
        # Advanced: Predictive Wolf-Pack Trapping
        for uid, en in self.state.enemy_robots.items():
            if en.rtype == TYPE_FACTORY:
                # Predict Position
                prev_pos = self.state.enemy_history.get(uid, en.pos)
                dc, dr = en.col - prev_pos[0], en.row - prev_pos[1]
                pred_pos = (max(0, min(self.state.width-1, en.col + dc)), 
                           max(self.state.south_bound + 1, min(self.state.north_bound, en.row + dr)))
                
                # Trap Coordinates (Priority Surround)
                trap_spots = [(pred_pos[0], pred_pos[1]+1), (pred_pos[0], pred_pos[1]-1),
                              (pred_pos[0]+1, pred_pos[1]), (pred_pos[0]-1, pred_pos[1])]
                
                for spot in trap_spots:
                    if 0 <= spot[0] < self.state.width and self.state.south_bound < spot[1] <= self.state.north_bound:
                        if spot not in intent:
                            dist = self.nav.manhattan_distance(r.pos, spot)
                            if dist <= 1:
                                intent.add(spot)
                                # Precise Directional Building towards enemy from trap spot
                                if r.pos == spot:
                                    if r.row == pred_pos[1]+1: return "BUILD_SOUTH"
                                    if r.row == pred_pos[1]-1: return "BUILD_NORTH"
                                    if r.col == pred_pos[0]+1: return "BUILD_WEST"
                                    if r.col == pred_pos[0]-1: return "BUILD_EAST"
                                    return "BUILD_NORTH"
                                # Build from adjacent to trap spot
                                if r.row == spot[1]-1 and r.col == spot[0]: return "BUILD_NORTH"
                                if r.row == spot[1]+1 and r.col == spot[0]: return "BUILD_SOUTH"
                                if r.col == spot[0]-1 and r.row == spot[1]: return "BUILD_EAST"
                                if r.col == spot[0]+1 and r.row == spot[1]: return "BUILD_WEST"
                            elif dist <= 5:
                                # Path to trap spot
                                intent.add(spot)
                                p = self.nav.find_path(r.pos, spot)
                                if p: return p[0]

        # Return to base if high energy
        if r.energy > 250 and f:
            p = self.nav.find_path(r.pos, f.pos)
            if p: return p[0]
        
        # Shortcut / Wall Removal Logic
        if r.energy > 150:
            for dr, dc, act in [(1,0,"REMOVE_NORTH"), (-1,0,"REMOVE_SOUTH"), (0,1,"REMOVE_EAST"), (0,-1,"REMOVE_WEST")]:
                target_pos = (r.col + dc, r.row + dr)
                if target_pos in self.state.crystals or (f and self.nav.manhattan_distance(target_pos, f.pos) < self.nav.manhattan_distance(r.pos, f.pos)):
                    w = self.state.walls.get(r.pos, 0)
                    bit = { "NORTH":1, "EAST":2, "SOUTH":4, "WEST":8 }[act.split("_")[1]]
                    if (w & bit): return act

        if r.energy < 60 and f:
            p = self.nav.find_path(r.pos, f.pos)
            if p: return p[0]

        available = {pos: e for pos, e in self.state.crystals.items() if pos not in intent}
        if available:
            closest = min(available.keys(), key=lambda c: self.nav.manhattan_distance(r.pos, c))
            intent.add(closest)
            p = self.nav.find_path(r.pos, closest)
            if p: return p[0]
        
        target_pos = (r.col, min(r.row + 3, self.state.north_bound))
        p = self.nav.find_path(r.pos, target_pos, optimistic=True)
        return p[0] if p else ACTION_NORTH

    def _miner_logic(self, r: RobotData, intent: Set[Coord]) -> str:
        # P1: Transform if on node
        if r.pos in self.state.persistent_mining_nodes and r.energy >= 100: return "TRANSFORM"
        
        # P2: Seek untransformed nodes with reservation
        targets = [n for n in self.state.persistent_mining_nodes if n not in self.state.mines and n not in intent]
        if targets:
            closest = min(targets, key=lambda n: self.nav.manhattan_distance(r.pos, n))
            intent.add(closest)
            p = self.nav.find_path(r.pos, closest)
            if p: return p[0]
            
        # P3: Stay near factory if no nodes
        factory = next((rob for rob in self.state.my_robots.values() if rob.rtype == TYPE_FACTORY), None)
        if factory and self.nav.manhattan_distance(r.pos, factory.pos) > 3:
            p = self.nav.find_path(r.pos, factory.pos)
            if p: return p[0]
            
        return ACTION_IDLE

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
