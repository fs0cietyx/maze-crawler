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
        buffer = 12 + (self.step // 40)
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
            else:
                # Add localized risk for other enemy units to route our swarm around them
                r_min, r_max = max(0, en.row - 1), min(999, en.row + 2)
                c_min, c_max = max(0, en.col - 1), min(self.width, en.col + 2)
                for r in range(r_min, r_max):
                    for c in range(c_min, c_max):
                        self.risk_matrix[r, c] += en.power * 5

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
        if not (w & SOUTH) and r - 1 >= self.state.south_bound: neighbors.append(((c, r - 1), ACTION_SOUTH))
        if not (w & WEST) and c - 1 >= 0: neighbors.append(((c - 1, r), ACTION_WEST))
        return neighbors

    def manhattan_distance(self, p1: Coord, p2: Coord) -> int:
        return abs(p1[0] - p2[0]) + abs(p1[1] - p2[1])

    def find_path(self, start: Coord, goal: Coord, limit: int = 600, optimistic: bool = False) -> Optional[List[str]]:
        if start == goal: return []
        cache_key = (start, goal)
        if not optimistic and cache_key in self.state.path_cache: return self.state.path_cache[cache_key]

        # Dynamic Compute Scaling: Scale search depth based on banked time
        time_factor = max(0.2, min(1.5, self.state.remaining_time / 40.0))
        actual_limit = int(limit * time_factor)

        frontier = [(0, start)]
        came_from = {start: None}; actions = {start: None}; cost_so_far = {start: 0}
        evaluated = 0
        
        best_node = start
        best_dist = self.manhattan_distance(start, goal)

        while frontier:
            if evaluated > actual_limit: break
            _, curr = heapq.heappop(frontier)
            evaluated += 1
            
            # Inline Manhattan for speed tracking best node
            d = abs(curr[0] - goal[0]) + abs(curr[1] - goal[1])
            if d < best_dist:
                best_dist = d
                best_node = curr

            if curr == goal: break

            c, r = curr
            w = self.state.walls.get(curr, -1)
            if w == -1:
                if not optimistic: continue
                w = 0
            
            # Inlined neighbor generation and cost calculation
            for bit, dc, dr, act, m_cost in [(1, 0, 1, ACTION_NORTH, 1), (2, 1, 0, ACTION_EAST, 5), (4, 0, -1, ACTION_SOUTH, 100), (8, -1, 0, ACTION_WEST, 5)]:
                if not (w & bit):
                    nc, nr = c + dc, r + dr
                    if 0 <= nc < self.state.width and self.state.south_bound <= nr <= self.state.north_bound:
                        nxt = (nc, nr)
                        risk_penalty = self.state.risk_matrix[nr, nc] if nr < 1000 else 0
                        new_cost = cost_so_far[curr] + m_cost + risk_penalty
                        if nxt not in cost_so_far or new_cost < cost_so_far[nxt]:
                            cost_so_far[nxt] = new_cost
                            priority = new_cost + abs(goal[0] - nc) + abs(goal[1] - nr)
                            heapq.heappush(frontier, (priority, nxt))
                            came_from[nxt] = curr; actions[nxt] = act

        target_node = goal if goal in came_from else best_node
        if target_node == start: return None
        
        path, c = [], target_node
        while c != start:
            path.append(actions[c]); c = came_from[c]
        path.reverse()
        if not optimistic and target_node == goal: self.state.path_cache[cache_key] = path
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
        if nxt[1] < self.state.south_bound or nxt[1] > self.state.north_bound: return False, robot.pos
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
            
        # 4. Predictive Enemy Crush Logic (O(1) Set Lookup)
        if nxt in self.danger_zones.get(robot.power, set()):
            return False, robot.pos

        return True, nxt

    def dispatch(self) -> Dict[RobotUID, str]:
        actions = {}
        reserved_set: Set[Coord] = set()
        intent_reserved: Set[Coord] = set()
        
        # Pre-calculate predictive danger zones per power level (O(N_enemies) once)
        self.danger_zones: Dict[int, Set[Coord]] = {1: set(), 2: set(), 3: set(), 4: set()}
        for en in self.state.enemy_robots.values():
            for p in range(1, en.power + 1):
                self.danger_zones[p].add(en.pos)
                if en.move_cd == 0:
                    self.danger_zones[p].update([(en.col, en.row+1), (en.col, en.row-1), (en.col+1, en.row), (en.col-1, en.row)])
                if en.rtype == TYPE_FACTORY and en.jump_cd == 0:
                    self.danger_zones[p].update([(en.col, en.row+2), (en.col, en.row-2), (en.col+2, en.row), (en.col-2, en.row)])
        
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
                death_dist = r.row - self.state.south_bound
                # Priority: NORTH > Lateral > IDLE > SOUTH
                sort_order = {ACTION_NORTH: 0, ACTION_EAST: 1, ACTION_WEST: 1, ACTION_IDLE: 2, ACTION_SOUTH: 3}

                # Filter out SOUTH if dangerously close to boundary
                candidates = self.nav.get_neighbors(r.pos)
                if death_dist < 5:
                    candidates = [c for c in candidates if c[1] != ACTION_SOUTH]

                found = False
                for _, act in sorted(candidates, key=lambda x: sort_order.get(x[1], 4)):
                    s, n = self.is_safe(r, act, reserved_set)
                    if s:
                        chosen_act = act; nxt = n; found = True
                        break

                if not found:
                    # Absolute last resort: try IDLE even if marked unsafe
                    chosen_act = ACTION_IDLE; nxt = r.pos

                    s, n = self.is_safe(r, ACTION_IDLE, reserved_set)
                    if s:
                        chosen_act = ACTION_IDLE; nxt = n; found = True
                
                if not found:
                    # Absolute desperation: IDLE and hope for the best
                    chosen_act = ACTION_IDLE; nxt = r.pos

            actions[r.uid] = chosen_act
            reserved_set.add(nxt)
            
        return actions

    def _combat_micro(self, r: RobotData) -> Optional[str]:
        # Priority 1: Offensive Crushing
        for nxt, act in self.nav.get_neighbors(r.pos):
            enemy = next((en for en in self.state.enemy_robots.values() if en.pos == nxt), None)
            if enemy and r.power > enemy.power:
                safe, _ = self.is_safe(r, act, set())
                if safe: return act

        # Priority 2: Tactical Kiting (Run from stronger enemies)
        hostiles = [en for en in self.state.enemy_robots.values() if en.power > r.power and self.nav.manhattan_distance(r.pos, en.pos) <= 2]
        if hostiles:
            best_move = ACTION_IDLE; max_min_dist = min(self.nav.manhattan_distance(r.pos, h.pos) for h in hostiles)
            for _, act in self.nav.get_neighbors(r.pos):
                safe, nxt = self.is_safe(r, act, set())
                if safe:
                    d = min(self.nav.manhattan_distance(nxt, h.pos) for h in hostiles)
                    if d > max_min_dist: max_min_dist = d; best_move = act
            if best_move != ACTION_IDLE: return best_move
        return None

    def _factory_logic(self, r: RobotData) -> str:
        # P1: Survival Calculation
        death_distance = r.row - self.state.south_bound
        buffer = 12 + (self.state.step // 40)
        
        if death_distance < buffer:
            # Urgent Northward Movement
            if r.jump_cd == 0:
                # Prioritize pure North jump, then lateral jumps
                for dc, dr, act in [(0, 2, "JUMP_NORTH"), (2, 0, "JUMP_EAST"), (-2, 0, "JUMP_WEST")]:
                    target_row = r.row + dr
                    tc = r.col + dc
                    if 0 <= tc < self.state.width and target_row <= self.state.north_bound:
                        safe, _ = self.is_safe(r, act, set())
                        if safe: return act
                # Try simple North
                safe, _ = self.is_safe(r, ACTION_NORTH, set())
                if safe: return ACTION_NORTH
            
            # Robust Pathfinding for Escape
            escape_targets = []
            for tr in [r.row + 10, r.row + 5]:
                for tc in [r.col, self.state.width // 2, 0, self.state.width - 1]:
                    target = (max(0, min(self.state.width - 1, tc)), min(self.state.north_bound, tr))
                    if target[1] > r.row: escape_targets.append(target)
            
            for target in escape_targets:
                path = self.nav.find_path(r.pos, target, limit=1000)
                if path and path[0] != ACTION_SOUTH: return path[0]
            
            # Emergency Wall Breaker (Build Worker if trapped)
            if r.energy >= 200 and r.build_cd == 0:
                # If we are trapped (ActionNorth is not safe), build a Worker
                safe_north, _ = self.is_safe(r, ACTION_NORTH, set())
                if not safe_north:
                    return "BUILD_WORKER"
            
            # Panic Fallback: Best Greedy Safe Move (Prohibit SOUTH)
            best_panic = ACTION_NORTH
            max_row = -1
            for _, act in self.nav.get_neighbors(r.pos):
                if act == ACTION_SOUTH: continue # NEVER south in panic
                safe, nxt = self.is_safe(r, act, set())
                if safe and nxt[1] > max_row:
                    max_row = nxt[1]; best_panic = act
            return best_panic

        # P1.5: Offensive Crushing (Prohibit SOUTH)
        if r.jump_cd == 0:
            for j_pos, j_act in [((r.col, r.row+2), "JUMP_NORTH"), 
                                 ((r.col+2, r.row), "JUMP_EAST"), ((r.col-2, r.row), "JUMP_WEST")]:
                if 0 <= j_pos[0] < self.state.width and self.state.south_bound < j_pos[1] <= self.state.north_bound:
                    enemy = next((en for en in self.state.enemy_robots.values() if en.pos == j_pos), None)
                    if enemy and r.power > enemy.power:
                        safe, _ = self.is_safe(r, j_act, set())
                        if safe: return j_act

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
                else:
                    # Walk away if JUMP is on cooldown
                    best_walk = ACTION_IDLE
                    max_dist = self.nav.manhattan_distance(r.pos, en.pos)
                    for _, act in self.nav.get_neighbors(r.pos):
                        safe, nxt = self.is_safe(r, act, set())
                        if safe:
                            d = self.nav.manhattan_distance(nxt, en.pos)
                            if d > max_dist:
                                max_dist = d; best_walk = act
                    if best_walk != ACTION_IDLE: return best_walk

        # P3: Economic Budgeting (Strict Early-Game Build Order)
        counts = {t: sum(1 for rob in self.state.my_robots.values() if rob.rtype == t) for t in [1, 2, 3]}
        if r.build_cd == 0:
            # Phase 1: Core Trifecta (Scout -> Worker -> Miner)
            if counts[1] == 0 and r.energy >= 200: return "BUILD_SCOUT"
            if counts[2] == 0 and r.energy >= 350: return "BUILD_WORKER"
            if counts[3] == 0 and r.energy >= 450: return "BUILD_MINER"
            
            # Phase 2: Dynamic Scaling
            min_energy = min(800, 400 + len(self.state.my_robots) * 50)
            if r.energy > min_energy:
                # Aggressive expansion
                max_miners = 4 if r.energy > 600 else 2
                max_workers = 5 if r.energy > 700 else 3
                max_scouts = 6 if r.energy > 500 else 4
                
                if counts[3] < max_miners and r.energy > 400: return "BUILD_MINER"
                if counts[2] < max_workers and r.energy > 400: return "BUILD_WORKER"
                if counts[1] < max_scouts and r.energy > 200: return "BUILD_SCOUT"
            
        # P4: Centering Heuristic (Only if safe and not in panic)
        if death_distance >= buffer:
            target_col = self.state.width // 2
            if abs(r.col - target_col) > 1:
                p = self.nav.find_path(r.pos, (target_col, r.row))
                if p: return p[0]

        # P5: Constant Progression
        # Move North proactively using pathfinding to avoid getting stuck behind walls
        target_pos = (r.col, min(r.row + 3, self.state.north_bound))
        p = self.nav.find_path(r.pos, target_pos, optimistic=True)
        if p:
            safe, _ = self.is_safe(r, p[0], set())
            if safe: return p[0]

        return ACTION_NORTH if self.state.step % 4 == 0 else ACTION_IDLE

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
        
        combat = self._combat_micro(r)
        if combat: return combat

        # Return to base if high energy or starving
        if (r.energy > 80 or r.energy < 30) and f:
            if self.nav.manhattan_distance(r.pos, f.pos) > 1:
                p = self.nav.find_path(r.pos, f.pos)
                if p: return p[0]
        
        # Collection (Crystals & Mines)
        act = self._collection_logic(r, intent)
        if act: return act
            
        target_pos = (r.col, min(r.row + 8, self.state.north_bound))
        p = self.nav.find_path(r.pos, target_pos, optimistic=True)
        return p[0] if p else ACTION_NORTH

    def _collection_logic(self, r: RobotData, intent: Set[Coord]) -> Optional[str]:
        # Capacity check: Don't harvest if nearly full
        max_energy = 100 if r.rtype == 1 else 300 if r.rtype == 2 else 500
        if r.energy > max_energy * 0.9: return None

        # Priority 1: Crystals in vision
        available = {pos: e for pos, e in self.state.crystals.items() if pos not in intent}
        # Priority 2: Friendly Mines with energy
        mines = {pos: data[0] for pos, data in self.state.mines.items() 
                 if data[2] == self.state.player and data[0] > 0 and pos not in intent}
        
        targets = []
        for pos, e in available.items():
            d = self.nav.manhattan_distance(r.pos, pos)
            targets.append((pos, e / (d * d + 1)))
        for pos, e in mines.items():
            d = self.nav.manhattan_distance(r.pos, pos)
            targets.append((pos, min(e, 100) / (d * d + 1)))
            
        if targets:
            targets.sort(key=lambda x: -x[1])
            best_pos = targets[0][0]
            intent.add(best_pos) # Reserve target
            if r.pos == best_pos: return ACTION_IDLE # Harvest
            p = self.nav.find_path(r.pos, best_pos)
            if p: return p[0]
        
        # Priority 3: Exploration (Undiscovered cells)
        undiscovered = []
        # Focus exploration on NORTH and lateral areas
        for row in range(max(self.state.south_bound + 1, r.row - 2), min(self.state.north_bound + 1, r.row + 10)):
            for col in range(self.state.width):
                if (col, row) not in self.state.walls and (col, row) not in intent:
                    undiscovered.append((col, row))
        if undiscovered:
            # Deterministic but spread out sampling
            undiscovered.sort(key=lambda c: self.nav.manhattan_distance(r.pos, c))
            idx = hash(r.uid) % min(len(undiscovered), 5)
            closest = undiscovered[min(len(undiscovered)-1, idx)] # Spread units
            intent.add(closest)
            p = self.nav.find_path(r.pos, closest, limit=150)
            if p: return p[0]

        return None

    def _worker_logic(self, r: RobotData, f: Optional[RobotData], intent: Set[Coord]) -> str:
        dump = self._energy_dump(r, f)
        if dump: return dump

        combat = self._combat_micro(r)
        if combat: return combat
        
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
                                if r.pos == spot:
                                    if r.row == pred_pos[1]+1: return "BUILD_SOUTH"
                                    if r.row == pred_pos[1]-1: return "BUILD_NORTH"
                                    if r.col == pred_pos[0]+1: return "BUILD_WEST"
                                    if r.col == pred_pos[0]-1: return "BUILD_EAST"
                                    return "BUILD_NORTH"
                            elif dist <= 5:
                                intent.add(spot)
                                p = self.nav.find_path(r.pos, spot)
                                if p: return p[0]

        # Return to base if high energy or starving
        if (r.energy > 250 or r.energy < 60) and f:
            if self.nav.manhattan_distance(r.pos, f.pos) > 1:
                p = self.nav.find_path(r.pos, f.pos)
                if p: return p[0]
        
        # Shortcut / Wall Removal Logic
        if r.energy > 150:
            for dr, dc, act in [(1,0,"REMOVE_NORTH"), (-1,0,"REMOVE_SOUTH"), (0,1,"REMOVE_EAST"), (0,-1,"REMOVE_WEST")]:
                target_pos = (r.col + dc, r.row + dr)
                # Aggressive Path-Clearing for Factory
                is_factory_path = f and f.col == target_pos[0] and target_pos[1] > f.row and target_pos[1] <= f.row + 3
                if is_factory_path or target_pos in self.state.crystals or (f and self.nav.manhattan_distance(target_pos, f.pos) < self.nav.manhattan_distance(r.pos, f.pos)):
                    w = self.state.walls.get(r.pos, 0)
                    bit = { "NORTH":1, "EAST":2, "SOUTH":4, "WEST":8 }[act.split("_")[1]]
                    if (w & bit): return act

        # Collection (Crystals & Mines)
        act = self._collection_logic(r, intent)
        if act: return act
        
        target_pos = (r.col, min(r.row + 3, self.state.north_bound))
        p = self.nav.find_path(r.pos, target_pos, optimistic=True)
        return p[0] if p else ACTION_NORTH

    def _miner_logic(self, r: RobotData, intent: Set[Coord]) -> str:
        combat = self._combat_micro(r)
        if combat: return combat

        # P1: Transform if on node (and it's not already our mine)
        is_our_mine = r.pos in self.state.mines and self.state.mines[r.pos][2] == self.state.player
        if r.pos in self.state.persistent_mining_nodes and not is_our_mine and r.energy >= 100: 
            return "TRANSFORM"
        
        # P2: Seek untransformed nodes with reservation
        targets = [n for n in self.state.persistent_mining_nodes if n not in self.state.mines and n not in intent]
        if targets:
            closest = min(targets, key=lambda n: self.nav.manhattan_distance(r.pos, n))
            intent.add(closest)
            p = self.nav.find_path(r.pos, closest)
            if p: return p[0]
            
        # P3: Harvest existing mines or return energy
        factory = next((rob for rob in self.state.my_robots.values() if rob.rtype == TYPE_FACTORY), None)
        if r.energy > 400 and factory:
            if self.nav.manhattan_distance(r.pos, factory.pos) > 1:
                p = self.nav.find_path(r.pos, factory.pos)
                if p: return p[0]
            else:
                dump = self._energy_dump(r, factory)
                if dump: return dump
            
        act = self._collection_logic(r, intent)
        if act: return act

        # P4: Stay near factory if no nodes
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
