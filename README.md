# TDM Circuit Allocator for a Mesh NoC

An educational Python implementation of circuit allocation for a circuit-switched Network-on-Chip (NoC) with a two-dimensional mesh topology.

The program receives a mesh configuration and a set of communication flows. For every flow, it tries to reserve the requested number of TDM slots along a source-to-destination circuit. The allocator accepts as many flows as the available slot tables and links allow, while recording successful and failed allocations.

This project was developed for the CA assignment on TDM slot allocation and is conceptually related to the circuit-setup approach described in *Integrated circuit-packet switching NoC with efficient circuit setup mechanism*. It is a lightweight simulation for the assignment; it is not intended to be a cycle-accurate implementation of a complete NoC RTL design.

## Features

- Rectangular 2D mesh topology with configurable width and height.
- Configurable number of TDM slots per slot table.
- Multiple cyclic slot tables selected according to the requested setup delay.
- A simulated control network that forwards circuit-setup requests to a root controller.
- Bit-mask representation of occupied slots for every node and direction.
- Breadth-first propagation of feasible slot masks from source to destination.
- Time-slot rotation at every hop to model the temporal progression of a circuit.
- Bidirectional reservation of every used link entry.
- Flow ordering by requested slot count, favoring smaller flows first.
- Random selection among feasible slots to distribute allocations across available slots.
- JSON input and output files plus a detailed execution log.
- Destination traffic accounting and hotspot warnings.

## Requirements

- Python 3.9 or newer
- No third-party Python packages

The implementation uses only the Python standard library (`json`, `random`, `uuid`, `collections`, `contextlib`, and `sys`).

## Quick start

Run without an input file to generate a random configuration and allocate its flows:

```bash
python tdm_circuit_allocator.py
```

Run with a user-defined configuration:

```bash
python tdm_circuit_allocator.py generated_flows.json
```

or:

```bash
python tdm_circuit_allocator.py path/to/my_config.json
```

The script does not print the normal trace to the terminal. It writes the trace to `output_log.txt` and writes the allocation summary to `allocation_results.json`.

When the script is run without an input file, it also generates `generated_flows.json`. These generated output files are overwritten on subsequent runs.

## Configuration format

The input is a JSON object containing the mesh parameters and a `flows` array:

```json
{
    "width": 4,
    "height": 4,
    "num_slots": 8,
    "num_tables": 2,
    "table_lifetime": 50,
    "root_node": [0, 0],
    "max_flows": 10,
    "max_delay": 1000,
    "hotspot_threshold": 10,
    "flows": [
        {
            "src": [0, 0],
            "dst": [3, 3],
            "slots": 2,
            "delay": 0
        },
        {
            "src": [3, 0],
            "dst": [0, 2],
            "slots": 3,
            "delay": 75
        }
    ]
}
```

### Configuration fields

| Field | Meaning |
|---|---|
| `width` | Number of columns in the mesh. Must be positive. |
| `height` | Number of rows in the mesh. Must be positive. |
| `num_slots` | Number of cyclic TDM slots in each table. Must be positive. |
| `num_tables` | Number of slot tables maintained by the controller. Must be positive. |
| `table_lifetime` | Number of time units represented by one table interval. Must be positive. |
| `root_node` | `[x, y]` coordinate of the control-network root. |
| `max_flows` | Upper bound used by random-flow generation and configuration validation. |
| `max_delay` | Upper bound used by random-flow generation and configuration validation. |
| `hotspot_threshold` | Destination traffic threshold after which a warning is logged. |
| `flows` | List of communication-flow objects to allocate. |

Each flow has the following fields:

| Field | Meaning |
|---|---|
| `src` | Source coordinate `[x, y]`. |
| `dst` | Destination coordinate `[x, y]`; it must differ from `src`. |
| `slots` | Number of slots requested by the flow, from `1` through `num_slots`. |
| `delay` | Non-negative delay used to select the slot table. |

Coordinates use zero-based indexing. `x` increases toward the east and `y` increases toward the south. The supported directions are `E`, `W`, `N`, and `S`.

## Allocation algorithm

The main allocation procedure is implemented by `RootController.allocate()` in `tdm_circuit_allocator.py`.

1. **Flow ordering**  
   The input flows are sorted in ascending order of `slots`. This is a simple heuristic intended to increase the number of flows that can be accepted; it does not guarantee an optimal solution.

2. **Control-request arrival**  
   Each flow is placed in the simulated control network. Its request reaches the root after:

   ```text
   Manhattan distance(source, root) + 1
   ```

   The flow's `delay` is carried with the request but is used for table selection, not for control-request latency.

3. **Slot-table selection**  
   For a request processed at cycle `current_time`, the selected table is:

   ```text
   table_id = ((current_time + delay) // table_lifetime) % num_tables
   ```

4. **Feasible-slot propagation**  
   The controller starts at the source with the free-slot mask of links that move toward the destination. It then performs a breadth-first search over monotonic mesh paths. A direction is considered only when it reduces the remaining horizontal or vertical distance to the destination.

   For each hop, the feasible mask is intersected with the free mask of the current link, rotated by one slot, and intersected with the free mask at the receiving side of the link. The rotation models the fact that a circuit advances by one time slot at every hop.

5. **Slot selection and backtracking**  
   If the destination has at least `slots` feasible bits, the allocator randomly selects the requested number of slot bits. Each selected bit is backtracked from the destination to the source to recover a path.

6. **Circuit reservation**  
   For a selected destination slot `b`, a path of depth `d` reserves slot:

   ```text
   (b + d) % num_slots
   ```

   on each hop. Both directional entries of the link are marked as occupied, so a circuit reservation is represented consistently at the two neighboring nodes.

7. **Result recording**  
   Successful allocations and failed flow IDs are written to `allocation_results.json`. The complete allocation trace, including masks, paths, and packet-switched free-slot information, is written to `output_log.txt`.

## Output files

### `allocation_results.json`

The result contains two top-level arrays:

```json
{
    "successful_flows": [
        {
            "flow_id": 0,
            "allocation": [
                {
                    "table_id": 0,
                    "slot": 5,
                    "path": [
                        [[2, 0], "W"],
                        [[1, 0], "S"]
                    ]
                }
            ]
        }
    ],
    "failed_flows": []
}
```

- `flow_id` is the index after the program sorts flows by requested slot count; it is not necessarily the original input-array index.
- `table_id` identifies the slot table used for that allocation.
- `slot` is the selected destination slot bit.
- Each path item contains the node at which a hop begins and the direction of that hop.
- A flow with `k` requested slots normally has `k` allocation entries.

### `output_log.txt`

The log contains configuration information, control-request arrival cycles, allocation steps, propagated masks, selected slots, backtracked paths, reservations, packet-switched free-slot masks, and the final allocation summary.

### `generated_flows.json`

This file is created only when no input file is provided. It stores the randomly generated configuration and flows used for that run.

## Example run

The repository includes a sample 4×4 configuration with eight slots per table. A typical run produces a summary similar to:

```text
Summary: Allocated 3/3 flows.
```

Because the allocator uses Python's `random.sample()` without a fixed seed, the exact selected slot numbers and paths can differ between runs. The allocation result is therefore expected to be structurally reproducible, but not byte-for-byte identical.

## Design notes and limitations

- **Monotonic routing only:** the search explores paths that continuously reduce the Manhattan distance to the destination. It does not use detours or arbitrary adaptive routes.
- **Heuristic, not optimal:** sorting flows by requested slot count and randomly choosing feasible slots is a practical heuristic. It does not maximize the number of accepted flows for every possible workload.
- **Fixed processing window:** the main program processes 20 control cycles. For larger meshes or larger control-network latencies, requests arriving after this window may not be processed.
- **No release phase:** the current program allocates slots but does not model circuit teardown or slot reclamation during the run.
- **Random allocation:** no random seed is configured by default, so exact allocations vary between executions.
- **Fixed output names:** output paths are currently hard-coded as `generated_flows.json`, `allocation_results.json`, and `output_log.txt`.
- **Educational simulation:** the control network and slot tables model the allocation logic at a high level. They are not a synthesizable NoC implementation or a full packet-switching simulator.

## Repository layout

```text
.
├── tdm_circuit_allocator.py   # Main allocator and simulation
├── generated_flows.json        # Example/generated input configuration
├── allocation_results.json     # Example/latest allocation result
├── output_log.txt              # Example/latest detailed execution log
└── 810103053.pdf               # Assignment material
```

## Reference

The assignment suggests the following work as a reference for circuit setup in a hybrid circuit/packet NoC:

> Integrated circuit-packet switching NoC with efficient circuit setup mechanism

