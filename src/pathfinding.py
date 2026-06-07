import heapq

class Pathfinder:
    def __init__(self, width, height):
        self.width = width
        self.height = height

    def get_neighbors(self, col, row, walls, south_bound):
        """
        Returns walkable neighbors for a given cell.
        walls: flat array of wall bitfields.
        """
        neighbors = []
        idx = (row - south_bound) * self.width + col
        
        if idx < 0 or idx >= len(walls) or walls[idx] == -1:
            return neighbors

        wall_bits = walls[idx]
        
        # N=1, E=2, S=4, W=8
        if not (wall_bits & 1): # North
            neighbors.append((col, row + 1, "NORTH"))
        if not (wall_bits & 2): # East
            neighbors.append((col + 1, row, "EAST"))
        if not (wall_bits & 4): # South
            neighbors.append((col, row - 1, "SOUTH"))
        if not (wall_bits & 8): # West
            neighbors.append((col - 1, row, "WEST"))
            
        return neighbors

    def heuristic(self, a, b):
        """Manhattan distance."""
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    def find_path(self, start, goal, walls, south_bound):
        """
        A* algorithm to find the shortest path from start to goal.
        start: (col, row)
        goal: (col, row)
        returns: list of action strings or None
        """
        if start == goal:
            return []

        frontier = []
        heapq.heappush(frontier, (0, start))
        came_from = {start: None}
        actions = {start: None}
        cost_so_far = {start: 0}

        while frontier:
            _, current = heapq.heappop(frontier)

            if current == goal:
                break

            for next_col, next_row, action in self.get_neighbors(current[0], current[1], walls, south_bound):
                next_node = (next_col, next_row)
                
                # Check if next_node is within the visible walls array
                next_idx = (next_row - south_bound) * self.width + next_col
                if next_idx < 0 or next_idx >= len(walls) or walls[next_idx] == -1:
                    continue

                new_cost = cost_so_far[current] + 1
                if next_node not in cost_so_far or new_cost < cost_so_far[next_node]:
                    cost_so_far[next_node] = new_cost
                    priority = new_cost + self.heuristic(goal, next_node)
                    heapq.heappush(frontier, (priority, next_node))
                    came_from[next_node] = current
                    actions[next_node] = action

        if goal not in came_from:
            return None

        # Reconstruct path
        path_actions = []
        curr = goal
        while curr != start:
            path_actions.append(actions[curr])
            curr = came_from[curr]
        
        path_actions.reverse()
        return path_actions
