import json
import heapq
import networkx as nx
import matplotlib.pyplot as plt
from collections import defaultdict
from ipaddress import IPv4Network, IPv4Address
import sys
import math
import os
import glob


class OSPFRouter:
    def __init__(self, router_id, name):
        self.router_id = router_id
        self.name = name
        self.router_type = "internal"
        self.interfaces = {}
        self.areas = set()


class OSPFInterface:
    def __init__(self, name, ip_address, network, cost, area):
        self.name = name
        self.ip_address = IPv4Address(ip_address)
        self.network = IPv4Network(network)
        self.cost = cost
        self.area = area
        self.connected_router = None
        self.neighbor_ip = None


class OSPFTopology:
    def __init__(self, config_file):
        self.routers = {}
        self.areas = {}
        self.topology_type = "unknown"
        self.graph = nx.Graph()
        self.config = {}
        self.load_configuration(config_file)
        self.detect_topology_type()
        self.build_topology()

    def load_configuration(self, config_file):
        try:
            with open(config_file, 'r') as f:
                self.config = json.load(f)
        except FileNotFoundError:
            print(f"Error: File '{config_file}' not found")
            sys.exit(1)
        except json.JSONDecodeError:
            print(f"Error: Invalid JSON in '{config_file}'")
            sys.exit(1)

        self.areas = self.config.get('areas', {})

        for router_name, router_config in self.config['routers'].items():
            router = OSPFRouter(router_config['router_id'], router_name)
            router.router_type = router_config.get('router_type', 'internal')

            for intf_name, intf_config in router_config['interfaces'].items():
                ip_address = self._get_interface_ip(intf_config)
                network = intf_config.get('network', self._derive_network(ip_address))
                cost = intf_config.get('cost', 1)
                area = intf_config.get('area', 0)

                interface = OSPFInterface(intf_name, ip_address, network, cost, area)
                router.areas.add(area)

                connected_to = intf_config.get('connected_to')
                if connected_to:
                    if isinstance(connected_to, dict):
                        interface.connected_router = connected_to.get('router')
                        interface.neighbor_ip = connected_to.get('ip')
                    elif isinstance(connected_to, str):
                        interface.connected_router = connected_to

                router.interfaces[intf_name] = interface

            self.routers[router_name] = router

        self._resolve_neighbor_ips()

    def _get_interface_ip(self, intf_config):
        ip_keys = ['ip_address', 'ip', 'IP', 'address']
        for key in ip_keys:
            if key in intf_config:
                return intf_config[key]
        raise KeyError(f"No IP address found. Available keys: {list(intf_config.keys())}. Expected keys: {ip_keys}")

    def _derive_network(self, ip_address):
        ip = IPv4Address(ip_address)
        if str(ip).startswith('192.168'):
            return f"{str(ip).rsplit('.', 1)[0]}.0/24"
        elif str(ip).startswith('10.'):
            return f"{str(ip).split('.', 1)[0]}.0.0.0/8"
        else:
            return f"{str(ip).rsplit('.', 1)[0]}.0/24"

    def _resolve_neighbor_ips(self):
        for router_name, router in self.routers.items():
            for intf_name, interface in router.interfaces.items():
                if interface.connected_router and not interface.neighbor_ip:
                    neighbor_router = self.routers.get(interface.connected_router)
                    if neighbor_router:
                        for neighbor_intf in neighbor_router.interfaces.values():
                            if neighbor_intf.connected_router == router_name and neighbor_intf.network == interface.network:
                                interface.neighbor_ip = str(neighbor_intf.ip_address)
                                break

    def detect_topology_type(self):
        metadata = self.config.get('topology_metadata', {})
        if 'type' in metadata:
            self.topology_type = metadata['type']
            return
        total_areas = len(self.areas)
        has_area_0 = '0' in self.areas
        abr_count = sum(1 for router in self.routers.values() if len(router.areas) > 1)
        if total_areas <= 1:
            if len(self.routers) == 4:
                self.topology_type = "single_area_ring"
            else:
                self.topology_type = "single_area"
        elif has_area_0 and abr_count > 0:
            self.topology_type = "multi_area"
        else:
            self.topology_type = "single_area"
        print(f"Auto-detected topology: {self.topology_type}")

    def build_topology(self):
        for router_name, router in self.routers.items():
            self.graph.add_node(router_name, router_id=router.router_id, router_type=router.router_type, areas=list(router.areas))
        processed_links = set()
        for router_name, router in self.routers.items():
            for intf_name, intf in router.interfaces.items():
                if intf.connected_router:
                    link = tuple(sorted([router_name, intf.connected_router]))
                    link_key = f"{link}_{intf.area}"
                    if link_key not in processed_links:
                        self.graph.add_edge(router_name, intf.connected_router, weight=intf.cost, area=intf.area, network=str(intf.network))
                        processed_links.add(link_key)

    def dijkstra_multi_path(self, source):
        distances = {node: float('inf') for node in self.graph.nodes()}
        distances[source] = 0
        paths = defaultdict(list)
        paths[source] = [[source]]
        pq = [(0, source)]
        while pq:
            dist, node = heapq.heappop(pq)
            if dist > distances[node]:
                continue
            for neighbor in self.graph.neighbors(node):
                edge_weight = self.graph[node][neighbor]['weight']
                new_dist = dist + edge_weight
                if new_dist < distances[neighbor]:
                    distances[neighbor] = new_dist
                    paths[neighbor] = [path + [neighbor] for path in paths[node]]
                    heapq.heappush(pq, (new_dist, neighbor))
                elif new_dist == distances[neighbor]:
                    paths[neighbor].extend([path + [neighbor] for path in paths[node]])
        return distances, dict(paths)

    def determine_route_type(self, source_router, dest_router, dest_area):
        if self.topology_type in ["single_area", "single_area_ring"]:
            return "O"
        source_areas = source_router.areas
        if dest_area in source_areas:
            return "O"
        else:
            return "O IA"

    def generate_routing_table(self, router_name):
        router = self.routers[router_name]
        distances, all_paths = self.dijkstra_multi_path(router_name)
        ospf_routes = []
        processed_networks = set()
        for dest_router_name, dest_router in self.routers.items():
            if dest_router_name != router_name:
                for intf_name, interface in dest_router.interfaces.items():
                    network_str = str(interface.network)
                    if network_str in processed_networks:
                        continue
                    is_directly_connected = False
                    for src_intf in router.interfaces.values():
                        if str(src_intf.network) == network_str:
                            is_directly_connected = True
                            break
                    if is_directly_connected:
                        continue
                    processed_networks.add(network_str)
                    if dest_router_name in all_paths:
                        paths_to_dest = all_paths[dest_router_name]
                        next_hop_paths = defaultdict(list)
                        for path in paths_to_dest:
                            if len(path) > 1:
                                next_hop = path[1]
                                next_hop_paths[next_hop].append(path)
                        for next_hop_router, paths_list in next_hop_paths.items():
                            path_cost = distances[dest_router_name]
                            total_cost = path_cost + interface.cost
                            route_type = self.determine_route_type(router, dest_router, interface.area)
                            next_hop_ip = self.find_next_hop_ip(router_name, next_hop_router)
                            outbound_interface = self.find_outbound_interface(router_name, next_hop_router)
                            if next_hop_ip and outbound_interface:
                                route_entry = {'network': network_str, 'next_hop': next_hop_ip, 'cost': int(total_cost), 'via_interface': outbound_interface, 'route_type': route_type}
                                ospf_routes.append(route_entry)
        return ospf_routes

    def find_next_hop_ip(self, source_router, next_hop_router):
        source = self.routers[source_router]
        for intf_name, interface in source.interfaces.items():
            if interface.connected_router == next_hop_router:
                return interface.neighbor_ip
        return None

    def find_outbound_interface(self, source_router, next_hop_router):
        source = self.routers[source_router]
        for intf_name, interface in source.interfaces.items():
            if interface.connected_router == next_hop_router:
                return intf_name
        return None

    def print_routing_table(self, router_name):
        ospf_routes = self.generate_routing_table(router_name)
        router = self.routers[router_name]
        print(f"\n=== Routing Table for {router_name} (Router ID: {router.router_id}) ===")
        print(f"Topology: {self.topology_type.replace('_', ' ').title()}")
        if len(router.areas) > 1:
            print(f"Router Type: {router.router_type.upper()} (Areas: {sorted(list(router.areas))})")
        else:
            print(f"Router Type: {router.router_type.upper()} (Area: {list(router.areas)[0] if router.areas else 0})")
        print()
        if not ospf_routes:
            print("No routes found.")
            return
        routes_by_network = defaultdict(list)
        for route in ospf_routes:
            routes_by_network[route['network']].append(route)
        for network, routes in routes_by_network.items():
            routes.sort(key=lambda r: (r['cost'], r['via_interface']))
            first_route = routes[0]
            route_type = first_route.get('route_type', 'O')
            print(f"{route_type:4} {network} [110/{first_route['cost']}] via {first_route['next_hop']}, {first_route['via_interface']}")
            for route in routes[1:]:
                if route['cost'] == first_route['cost']:
                    print(f"                [110/{route['cost']}] via {route['next_hop']}, {route['via_interface']}")

    def visualize_topology(self):
        plt.figure(figsize=(14, 10))
        n = len(self.routers)
        if self.topology_type == "single_area_ring" or "ring" in self.topology_type.lower():
            pos = {}
            for i, router_name in enumerate(sorted(self.routers.keys())):
                angle = 2 * math.pi * i / n
                pos[router_name] = (2 * math.cos(angle), 2 * math.sin(angle))
        elif n <= 4:
            pos = nx.spring_layout(self.graph, k=3, iterations=50)
        else:
            pos = nx.spring_layout(self.graph, k=4, iterations=100)
        colors = []
        for router_name in self.graph.nodes():
            router = self.routers[router_name]
            if router.router_type == "abr":
                colors.append("orange")
            elif router.router_type == "asbr":
                colors.append("red")
            else:
                colors.append("lightblue")
        nx.draw_networkx_nodes(self.graph, pos, node_color=colors, node_size=2500, alpha=0.8)
        if self.topology_type == "multi_area":
            area_colors = {0: "red", 1: "blue", 2: "green", 3: "purple", 4: "brown"}
            for edge in self.graph.edges():
                area = self.graph[edge[0]][edge[1]].get("area", 0)
                color = area_colors.get(area, "gray")
                nx.draw_networkx_edges(self.graph, pos, edgelist=[edge], edge_color=color, width=3)
        else:
            nx.draw_networkx_edges(self.graph, pos, edge_color="red", width=3)
        labels = {}
        for router_name, router in self.routers.items():
            if len(router.areas) > 1:
                labels[router_name] = f"{router_name}\n({router.router_id})\nAreas: {sorted(router.areas)}"
            else:
                labels[router_name] = f"{router_name}\n({router.router_id})\nArea: {list(router.areas)[0] if router.areas else 0}"
        nx.draw_networkx_labels(self.graph, pos, labels, font_size=8, font_weight="bold")
        edge_labels = {}
        for edge in self.graph.edges():
            edge_labels[edge] = f"Cost: {self.graph.get_edge_data(*edge)['weight']}"
        nx.draw_networkx_edge_labels(self.graph, pos, edge_labels, font_size=8)
        legend_elements = []
        if self.topology_type == "multi_area":
            area_colors = {0: "red", 1: "blue", 2: "green", 3: "purple", 4: "brown"}
            for area_id in sorted(self.areas.keys()):
                area_num = int(area_id)
                legend_elements.append(plt.Line2D([0], [0], color=area_colors.get(area_num, "gray"), lw=3, label=f"Area {area_id}"))
        else:
            legend_elements.append(plt.Line2D([0], [0], color="red", lw=3, label="OSPF Links"))
        legend_elements.extend([
            plt.Line2D([0], [0], marker="o", color="orange", lw=0, markersize=10, label="ABR Router"),
            plt.Line2D([0], [0], marker="o", color="red", lw=0, markersize=10, label="ASBR Router"),
            plt.Line2D([0], [0], marker="o", color="lightblue", lw=0, markersize=10, label="Internal Router")
        ])
        plt.legend(handles=legend_elements, loc="upper right")
        plt.title(f"{self.topology_type.replace('_', ' ').title()} OSPF Topology", size=16, weight="bold")
        plt.axis("off")
        plt.tight_layout()
        plt.show()


def find_json_files():
    """Find all JSON files in current directory, excluding package.json"""
    json_files = glob.glob("*.json")
    return [f for f in json_files if f != 'package.json']


def show_menu(json_files):
    """Display numbered menu of available JSON files"""
    print("\n" + "="*60)
    print("         OSPF TOPOLOGY ANALYZER")
    print("="*60)
    print(f"\nFound {len(json_files)} JSON topology file(s):")
    print()
    
    for i, filename in enumerate(json_files, 1):
        if 'triangle' in filename.lower():
            desc = "(Triangle topology)"
        elif 'ring' in filename.lower():
            desc = "(Ring topology)"
        elif 'multi' in filename.lower():
            desc = "(Multi-area topology)"
        else:
            desc = "(Custom topology)"
        
        print(f"{i}. {filename} {desc}")
    
    print(f"{len(json_files) + 1}. Exit")
    print("\n" + "-"*60)


def get_user_choice(max_choice):
    """Get valid user choice with input validation"""
    while True:
        try:
            choice = input(f"\nEnter your choice (1-{max_choice}): ").strip()
            choice_int = int(choice)
            if 1 <= choice_int <= max_choice:
                return choice_int
            else:
                print(f"Invalid choice. Please enter a number between 1 and {max_choice}.")
        except (ValueError, KeyboardInterrupt):
            print(f"Invalid input. Please enter a number between 1 and {max_choice}.")


def main():
    print("Initializing OSPF Analyzer...")
    
    json_files = find_json_files()
    
    if not json_files:
        print("No JSON files found in the current directory!")
        print("Please make sure you have your topology JSON files in the same directory.")
        sys.exit(1)
    
    print(f"Found {len(json_files)} JSON topology file(s)")
    
    while True:
        show_menu(json_files)
        max_choice = len(json_files) + 1
        choice = get_user_choice(max_choice)
        
        if choice == len(json_files) + 1:
            print("\nGoodbye! Thanks for using OSPF Analyzer!")
            sys.exit(0)
        
        config_file = json_files[choice - 1]
        print(f"\nLoading topology from: {config_file}")
        
        try:
            ospf_network = OSPFTopology(config_file)
            print(f"Successfully loaded {len(ospf_network.routers)} routers")
            print(f"Topology Type: {ospf_network.topology_type.replace('_', ' ').title()}")
            
            if ospf_network.areas:
                print(f"Network spans {len(ospf_network.areas)} OSPF area(s)")
                print("\nArea Summary:")
                for area_id, area_info in ospf_network.areas.items():
                    description = area_info.get('description', f'OSPF Area {area_id}')
                    print(f"   - Area {area_id}: {description}")
            
            print("\nRouter Details:")
            for router_name, router in ospf_network.routers.items():
                interface_count = len([intf for intf in router.interfaces.values() if intf.connected_router])
                areas_str = ', '.join(map(str, sorted(router.areas))) if router.areas else '0'
                router_type_str = router.router_type.upper()
                print(f"   - {router_name} ({router_type_str}): Areas [{areas_str}], {interface_count} connections")
            
            for router_name in ospf_network.routers.keys():
                ospf_network.print_routing_table(router_name)
            
            show_viz = input("\nShow network visualization? (y/n): ").lower().strip()
            if show_viz in ['y', 'yes', '']:
                print(f"\nGenerating {ospf_network.topology_type.replace('_', ' ')} topology visualization...")
                ospf_network.visualize_topology()
            
            print("\nAnalysis complete!")
            
            continue_choice = input("\nAnalyze another topology? (y/n): ").lower().strip()
            if continue_choice not in ['y', 'yes', '']:
                print("\nGoodbye! Thanks for using OSPF Analyzer!")
                break
                
        except Exception as e:
            print(f"\nError analyzing topology: {str(e)}")
            print("Please check your JSON file format and try again.")
            
            debug_choice = input("\nShow detailed error information? (y/n): ").lower().strip()
            if debug_choice in ['y', 'yes']:
                import traceback
                traceback.print_exc()


if __name__ == "__main__":
    main()
