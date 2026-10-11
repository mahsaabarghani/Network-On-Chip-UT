import sys
import json
from collections import deque
import random
import uuid
from contextlib import contextmanager

# Context manager for redirecting print output to a file
@contextmanager
def redirect_stdout_to_file(filename):
    original_stdout = sys.stdout
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            sys.stdout = f
            yield
    finally:
        sys.stdout = original_stdout

# Directions and coordinate deltas
DIRECTIONS = {'E': (1,0), 'W':(-1,0), 'N':(0,-1), 'S':(0,1)}
OPPOSITE = {'E':'W', 'W':'E', 'N':'S', 'S':'N'}

class ControlNetwork:
    """Simulates a lightweight control network for sending circuit setup requests."""
    def __init__(self, width, height, root_node):
        self.width = width
        self.height = height
        self.root_node = root_node
        self.request_queue = deque()
        self.cycle_count = 0

    def send_request(self, src, dst, slots, delay):
        """Simulate sending a request to the root node with latency."""
        latency = abs(src[0] - self.root_node[0]) + abs(src[1] - self.root_node[1]) + 1
        request = {'src': src, 'dst': dst, 'slots': slots, 'delay': delay, 'arrival_cycle': self.cycle_count + latency}
        self.request_queue.append(request)
        print(f"ControlNetwork: Request from {src} to {dst} queued, arrives at cycle {request['arrival_cycle']}")
        return latency

    def process_requests(self, root_controller, table_lifetime):
        """Process queued requests at the current cycle."""
        results = []
        while self.request_queue and self.request_queue[0]['arrival_cycle'] <= self.cycle_count:
            req = self.request_queue.popleft()
            print(f"ControlNetwork: Processing request from {req['src']} to {req['dst']}")
            res = root_controller.allocate(req['src'], req['dst'], req['slots'], 
                                          self.cycle_count, req['delay'], table_lifetime)
            results.append((req, res))
        self.cycle_count += 1
        return results

    def get_packet_switched_slots(self, table_id, node, direction, root_controller):
        """Return available slots for packet-switched data."""
        return root_controller._free_mask(table_id, node, direction)

class RootController:
    def __init__(self, width, height, num_slots, num_tables=1, root_node=(0,0), hotspot_threshold=10):
        self.width = width
        self.height = height
        self.num_slots = num_slots
        self.num_tables = num_tables
        self.slot_mask = (1 << num_slots) - 1
        self.slot_tables = [
            {(x,y):{d:0 for d in DIRECTIONS}
             for x in range(width) for y in range(height)}
            for _ in range(num_tables)
        ]
        self.control_network = ControlNetwork(width, height, root_node)
        self.node_traffic = {(x,y):0 for x in range(width) for y in range(height)}
        self.hotspot_threshold = hotspot_threshold

    def validate_input(self, src, dst, slots, delay):
        """Validate input parameters."""
        if not (0 <= src[0] < self.width and 0 <= src[1] < self.height):
            raise ValueError(f"Invalid source coordinates: {src}")
        if not (0 <= dst[0] < self.width and 0 <= dst[1] < self.height):
            raise ValueError(f"Invalid destination coordinates: {dst}")
        if not (0 < slots <= self.num_slots):
            raise ValueError(f"Invalid number of slots: {slots}, must be between 1 and {self.num_slots}")
        if delay < 0:
            raise ValueError(f"Invalid delay: {delay}, must be non-negative")
        return True

    def allocate(self, src, dst, k, current_time, delay_cycles, table_lifetime):
        print(f"\nAllocating flow src={src}, dst={dst}, slots={k}, delay={delay_cycles}, current_time={current_time}")
        try:
            self.validate_input(src, dst, k, delay_cycles)
        except ValueError as e:
            print(f"Validation error: {e}")
            return None

        # Track traffic for hotspot detection
        self.node_traffic[dst] += k
        if self.node_traffic[dst] > self.hotspot_threshold:
            print(f"Warning: Node {dst} is a potential hotspot (traffic={self.node_traffic[dst]})")

        future = current_time + delay_cycles
        table_id = (future // table_lifetime) % self.num_tables
        print(f"Selected table_id={table_id} (future={future}, lifetime={table_lifetime})")
        n = self.num_slots

        # Initialize free and track
        free = {(x,y):0 for x,y in self.slot_tables[0]}
        track = {coord:{d:0 for d in DIRECTIONS} for coord in free}

        # BFS wave
        sx, sy = src
        dx, dy = dst
        mask0 = 0
        for d in ['E','W','N','S']:
            if self._delta_ok(d, sx, sy, dx, dy):
                m = self._free_mask(table_id, src, d)
                mask0 |= m
                track[src][d] |= m
        free[src] = mask0
        print(f"Initial free[src]={bin(free[src])}")
        q = deque([src])
        step = 0
        while q:
            u = q.popleft()
            print(f"Step {step}, pop node {u}, free={bin(free[u])}")
            merged_prev = free[u]
            for d in ['E','W','N','S']:
                if not self._delta_ok(d, u[0], u[1], dx, dy): continue
                v = (u[0] + DIRECTIONS[d][0], u[1] + DIRECTIONS[d][1])
                if v not in free: continue
                pm = self._free_mask(table_id, u, d)
                merged = merged_prev & pm
                rot = ((merged << 1) & self.slot_mask) | ((merged >> (n-1)) & 1)
                nm = self._free_mask(table_id, v, OPPOSITE[d])
                new = rot & nm & ~free[v]
                if new:
                    free[v] |= new
                    print(f"  Propagate to {v} dir={d}, new={bin(new)}, free[{v}]={bin(free[v])}")
                    for b in range(n):
                        if new & (1 << b): track[v][d] |= (1 << b)
                    q.append(v)
            step += 1
        avail = free[dst]
        print(f"Final available at dst {dst} = {bin(avail)}")
        if bin(avail).count('1') < k:
            print("  Not enough slots available, allocation fails.")
            return None

        # Random slot selection to balance load
        available_slots = [i for i in range(n) if avail & (1 << i)]
        bits = random.sample(available_slots, k) if len(available_slots) >= k else []
        if not bits:
            print("  Not enough slots available after random selection, allocation fails.")
            return None
        print(f"Selected slot bits: {bits}")

        # Backtracking and occupy
        results = []
        for b in bits:
            print(f"Backtracking slot bit={b}")
            path = []
            cur = dst
            bit = b
            while cur != src:
                for d, mask in track[cur].items():
                    if mask & (1 << bit):
                        prev = (cur[0] - DIRECTIONS[d][0], cur[1] - DIRECTIONS[d][1])
                        path.append((prev, d))
                        print(f"  at {cur}, via {d} to {prev}, bit now {(bit-1)%n}")
                        bit = (bit - 1) % n
                        cur = prev
                        break
            path.reverse()
            print(f"  Path for bit {b}: {path}")
            cur = src
            depth = 0
            for _, d in path:
                idx = (b + depth) % n
                print(f"  Occupy at {cur}->{d}, slot {idx}")
                self._occupy(table_id, cur, d, idx)
                nxt = (cur[0] + DIRECTIONS[d][0], cur[1] + DIRECTIONS[d][1])
                self._occupy(table_id, nxt, OPPOSITE[d], idx)
                cur, depth = nxt, depth + 1
            results.append((table_id, b, path))
        print(f"Allocation result: {results}")

        # Report available slots for packet-switched data
        for node in free:
            for d in DIRECTIONS:
                free_slots = self._free_mask(table_id, node, d)
                if free_slots:
                    print(f"Packet-switched slots available at {node}->{d}: {bin(free_slots)}")

        return results

    def _free_mask(self, tid, coord, d):
        return ~self.slot_tables[tid][coord][d] & self.slot_mask

    def _occupy(self, tid, coord, d, slot):
        self.slot_tables[tid][coord][d] |= (1 << slot)

    def _delta_ok(self, d, sx, sy, dx, dy):
        if d == 'E': return dx > sx and sx < self.width - 1
        if d == 'W': return dx < sx and sx > 0
        if d == 'S': return dy > sy and sy < self.height - 1
        if d == 'N': return dy < sy and sy > 0
        return False

def generate_random_flows(width, height, num_slots, max_flows, max_delay):
    """Generate random flows within specified ranges."""
    num_flows = random.randint(1, max_flows)
    flows = []
    for _ in range(num_flows):
        src = [random.randint(0, width-1), random.randint(0, height-1)]
        dst = [random.randint(0, width-1), random.randint(0, height-1)]
        while src == dst:  # Ensure src != dst
            dst = [random.randint(0, width-1), random.randint(0, height-1)]
        slots = random.randint(1, num_slots)
        delay = random.randint(0, max_delay)
        flows.append({"src": src, "dst": dst, "slots": slots, "delay": delay})
    return flows

def save_config_to_file(config, filename="generated_flows.json"):
    """Save configuration with random flows to a JSON file."""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)
        print(f"Configuration saved to {filename}")
    except IOError as e:
        print(f"Error saving configuration: {e}")
        sys.exit(1)

def save_results_to_file(successful_flows, failed_flows, filename="allocation_results.json"):
    """Save allocation results to a JSON file."""
    results = {
        "successful_flows": [
            {"flow_id": flow_id, "allocation": [
                {"table_id": r[0], "slot": r[1], "path": r[2]} for r in res
            ]} for flow_id, res in successful_flows
        ],
        "failed_flows": failed_flows
    }
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=4)
        print(f"Results saved to {filename}")
    except IOError as e:
        print(f"Error saving results: {e}")
        sys.exit(1)

if __name__ == '__main__':
    # Default configuration
    default_config = {
        "width": 4,
        "height": 4,
        "num_slots": 8,
        "num_tables": 2,
        "table_lifetime": 50,
        "root_node": [0, 0],
        "max_flows": 10,
        "max_delay": 1000,
        "hotspot_threshold": 10
    }

    # Redirect all print output to a text file
    with redirect_stdout_to_file("output_log.txt"):
        # Generate random flows if no input file is provided
        if len(sys.argv) == 2:
            try:
                with open(sys.argv[1], encoding='utf-8') as f:
                    cfg = json.load(f)
                print(f"Configuration loaded from {sys.argv[1]}")
            except (IOError, json.JSONDecodeError) as e:
                print(f"Error reading input file: {e}")
                sys.exit(1)
        else:
            print("No flows file provided, generating random flows.")
            cfg = default_config.copy()
            cfg['flows'] = generate_random_flows(
                cfg['width'], cfg['height'], cfg['num_slots'], 
                cfg['max_flows'], cfg['max_delay']
            )
            save_config_to_file(cfg)

        # Validate configuration
        try:
            if not (cfg['width'] > 0 and cfg['height'] > 0):
                raise ValueError("Invalid network dimensions")
            if not (cfg['num_slots'] > 0):
                raise ValueError("Invalid number of slots")
            if not (cfg['num_tables'] > 0):
                raise ValueError("Invalid number of tables")
            if not (cfg['table_lifetime'] > 0):
                raise ValueError("Invalid table lifetime")
            if not (0 <= cfg['root_node'][0] < cfg['width'] and 0 <= cfg['root_node'][1] < cfg['height']):
                raise ValueError(f"Invalid root node coordinates: {cfg['root_node']}")
            if not (0 < cfg.get('max_flows', 1) <= 100):
                raise ValueError(f"Invalid max_flows: {cfg.get('max_flows')}")
            if not (0 <= cfg.get('max_delay', 0) <= 10000):
                raise ValueError(f"Invalid max_delay: {cfg.get('max_delay')}")
            if not (cfg.get('hotspot_threshold', 1) > 0):
                raise ValueError(f"Invalid hotspot_threshold: {cfg.get('hotspot_threshold')}")
        except KeyError as e:
            print(f"Configuration error: Missing key {e}")
            sys.exit(1)
        except ValueError as e:
            print(f"Configuration error: {e}")
            sys.exit(1)

        print(f"Configuration: width={cfg['width']}, height={cfg['height']}, slots={cfg['num_slots']}, "
              f"tables={cfg.get('num_tables',1)}, lifetime={cfg.get('table_lifetime',1)}, "
              f"root_node={cfg.get('root_node')}, max_flows={cfg.get('max_flows')}, "
              f"max_delay={cfg.get('max_delay')}, hotspot_threshold={cfg.get('hotspot_threshold')}")

        root = RootController(cfg['width'], cfg['height'], cfg['num_slots'], 
                             cfg.get('num_tables', 1), cfg.get('root_node', (0,0)), 
                             cfg.get('hotspot_threshold', 10))
        tl = cfg.get('table_lifetime', 1)
        flows = cfg['flows']
        
        # Sort flows by number of slots to maximize allocations
        flows = sorted(flows, key=lambda x: x['slots'])
        print(f"Processing {len(flows)} flows (sorted by slots)...")

        succ = []
        fail = []
        for i, flow in enumerate(flows):
            try:
                src = tuple(flow['src'])
                dst = tuple(flow['dst'])
                k = flow['slots']
                d = flow.get('delay', 0)
                print(f"=== Flow {i}: src={src} dst={dst} slots={k} delay={d} ===")
                root.control_network.send_request(src, dst, k, d)
            except KeyError as e:
                print(f"Flow {i} error: Missing key {e}")
                fail.append(i)
                continue
            except ValueError as e:
                print(f"Flow {i} error: {e}")
                fail.append(i)
                continue

        # Process requests for multiple cycles
        max_cycles = 20
        for cycle in range(max_cycles):
            print(f"\n=== Processing cycle {cycle} ===")
            results = root.control_network.process_requests(root, tl)
            for req, res in results:
                flow_id = next((i for i, f in enumerate(flows) if f['src'] == list(req['src']) and 
                               f['dst'] == list(req['dst']) and f['slots'] == req['slots'] and 
                               f.get('delay', 0) == req['delay']), -1)
                if res:
                    succ.append((flow_id, res))
                else:
                    fail.append(flow_id)

        print(f"Summary: Allocated {len(succ)}/{len(flows)} flows.")
        if succ:
            for i, res in succ:
                print(f"  Flow {i} result: {res}")
        if fail:
            print(f"  Failed flows: {fail}")

        # Save results to JSON file
        save_results_to_file(succ, fail)