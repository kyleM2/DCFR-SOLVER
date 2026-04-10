#!/usr/bin/env python3
"""Inspect a DCFR solve JSON and extract 84o's EVs at IP's first decision."""
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else '/tmp/test_solve.json'

with open(path) as f:
    data = json.load(f)

print(f"Config: {data['config']}")
print(f"Iterations: {data['iterations']}")
print(f"Exploitability: {data['exploitability_pct']:.2f}%")
print(f"OOP EV (avg): {data['oop_ev']:.3f} chips")
print(f"IP EV  (avg): {data['ip_ev']:.3f} chips")
print(f"Sum: {data['oop_ev']+data['ip_ev']:.3f} (pot check)")
print()

# Extract 84o combo hands
combos_84o_set = set()
for c1 in ['8c','8d','8h','8s']:
    for c2 in ['4c','4d','4h','4s']:
        combos_84o_set.add(c1 + c2)
        combos_84o_set.add(c2 + c1)

# List all nodes with IP player at first decision
print("IP first-level nodes (≤ 2 arrow depth):")
ip_nodes = []
for e in data['strategy']:
    if e.get('player') != 'IP':
        continue
    node = str(e.get('node', ''))
    depth = node.count('→')
    if depth <= 1:
        ip_nodes.append(e)
        print(f"  node='{node}' combos={len(e['combos'])} depth={depth}")

print()
print("84o EVs at IP's first decision nodes:")
for e in ip_nodes:
    print(f"\n  Node: '{e['node']}'")
    for c in e['combos']:
        if c['hand'] in combos_84o_set:
            ev = c.get('ev', float('nan'))
            actions_str = ', '.join(f"{a['action']}={a['weight']:.2f}" for a in c['actions'])
            print(f"    {c['hand']}: ev={ev:+.3f}  [{actions_str}]")
