# OSPF Topology Analyzer and Simulator

An interactive Python tool to parse OSPF topologies from JSON, build an undirected graph, run Dijkstra with equal-cost multipath (ECMP), print Cisco-style routing tables, and visualize the network graphically. Ships with three example topologies: single-area triangle, single-area ring, and multi-area with ABRs.

## Features
- Load topology from JSON (routers, interfaces, areas)
- Auto-detect topology type: single_area, single_area_ring, or multi_area
- Dijkstra-based SPF with equal-cost multipath path tracking
- Route-type classification: O (intra-area) vs O IA (inter-area)
- Cisco-like printout: O and O IA routes with [110/cost], next-hop IP, and outbound interface
- Visualization via NetworkX/matplotlib with area-colored edges in multi-area
- Menu-driven selection of JSON files—no CLI args required

## Quick start
1. Clone and enter the repo:
```
   git clone https://https://github.com/praveensg0/OSPF-Simulator.git
   cd OSPF-Simulator
```

2. Install dependencies:
```
   pip install -r requirements.txt
```

4. Run the analyzer:
```
   python OSPF.py
```
   - The program scans the current directory for *.json (excluding package.json) and shows a numbered menu. Pick 1/2/3/etc. to load a topology.

## Requirements
- Python 3.9+ recommended
- Packages:
  - networkx
  - matplotlib
  - (standard library) json, heapq, collections, ipaddress, sys, math, glob, os


## Project structure
```
├─ OSPF.py                    # Main script with OSPFRouter, OSPFInterface, OSPFTopology, and menu UI
├─ triangle_topology.json     # Single-area triangle example
├─ ring_topology.json         # Single-area ring example (Area 1)
├─ multi_area_topology.json   # Multi-area backbone (Area 0) + Areas 1, 2 with ABRs
├─ requirements.txt
└─ README.md
```
## How it works
- Parsing: OSPFTopology.load_configuration() reads routers, interfaces, and areas from JSON. IPs/networks validated via ipaddress. Neighbor IPs are auto-resolved when not provided, matching links by peer name and shared network.
- Graph: build_topology() adds routers as nodes and router-to-router links as undirected edges with attributes: weight (cost), area, network. Duplicate edges across areas are deduplicated per area.
- SPF: dijkstra_multi_path() computes shortest distances and tracks all equal-cost paths for ECMP.
- Routes: generate_routing_table() aggregates destination networks, skips directly connected ones, derives next hop and exit interface, totals cost (path to router + interface cost), and sets route-type O vs O IA.
- Output: print_routing_table() prints Cisco-like entries, grouping ECMP paths.
- Visualization: visualize_topology() draws nodes colored by router type (internal/lightblue, ABR/orange, ASBR/red) and edges colored per area in multi-area mode; labels include router IDs and areas, edges show “Cost: X”.

## Usage tips
- Add more JSON files to the same directory; they will appear in the menu automatically.
- In multi-area scenarios, ensure Area 0 exists and ABRs connect areas; the analyzer flags type accordingly.
- Interface connected_to can be a string (peer name) or an object with router and ip. If neighbor IP is omitted, it will be auto-resolved if the peer’s interface on the same network is found.

## Example runs
- Triangle (single area): see Area 0 with three routers; routes are O with costs reflecting serial link weights (64) plus destination LAN cost (1).
- Ring (single area ring): four routers in Area 1; ECMP may appear when opposite nodes are reachable via two equal-length paths.
- Multi-area: Areas 0/1/2; R1 and R3 are ABRs; routes appear as O within the same area and O IA across areas; edges colored by area.

## JSON format
```
{
  "topology_metadata": {
    "name": "My_OSPF_Topology",
    "type": "single_area|single_area_ring|multi_area",
    "total_areas": 1,
    "ospf_process_id": 1
  },
  "areas": {
    "0": { "type": "backbone|standard|...", "description": "..." }
  },
  "routers": {
    "R1": {
      "router_id": "192.168.0.1",
      "hostname": "R1",
      "router_type": "internal|abr|asbr",
      "interfaces": {
        "GigabitEthernet0/0": {
          "ip_address": "192.168.0.1",
          "network": "192.168.0.0/24",
          "cost": 1,
          "area": 0,
          "connected_to": null | "R2" | { "router": "R2", "ip": "192.168.0.2" }
        }
      }
    },
    "R2": {
      "router_id": "192.168.0.2",
      "hostname": "R2",
      "router_type": "internal",
      "interfaces": {
        "GigabitEthernet0/0": {
          "ip": "192.168.1.1",
          "network": "192.168.1.0/24",
          "cost": 1,
          "area": 0,
          "connected_to": null
        }
      }
    }
  }
}
```
