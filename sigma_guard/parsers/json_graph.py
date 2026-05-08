# sigma_guard/parsers/json_graph.py
# Parse JSON graph files into SIGMA's internal format.
#
# Expected JSON format:
#   {
#     "vertices": [
#       {"id": "v1", "label": "Supplier_A", "claims": {"sole_source": true}},
#       ...
#     ],
#     "edges": [
#       {"source": "v1", "target": "v2", "relation": "supplies"},
#       ...
#     ]
#   }
#
# Also supports node-link format (NetworkX compatible):
#   {
#     "nodes": [{"id": "v1", ...}],
#     "links": [{"source": "v1", "target": "v2", ...}]
#   }

import json
from typing import Any, Dict


def parse_json_graph(path: str) -> Dict[str, Any]:
    """Parse a JSON graph file."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Normalize to our internal format
    vertices = data.get("vertices", data.get("nodes", []))
    edges = data.get("edges", data.get("links", []))

    # Ensure each vertex has an "id" and "label"
    normalized_vertices = []
    for v in vertices:
        nv = dict(v)
        if "id" not in nv:
            nv["id"] = nv.get("label", nv.get("name", str(len(normalized_vertices))))
        if "label" not in nv:
            nv["label"] = nv.get("name", nv.get("id", ""))
        if "claims" not in nv:
            # Treat all non-id/label/name fields as claims
            claims = {
                k: v for k, v in nv.items()
                if k not in ("id", "label", "name")
            }
            nv["claims"] = claims
        normalized_vertices.append(nv)

    # Ensure each edge has "source" and "target"
    normalized_edges = []
    for e in edges:
        ne = dict(e)
        if "source" not in ne:
            ne["source"] = ne.get("from", ne.get("src", ""))
        if "target" not in ne:
            ne["target"] = ne.get("to", ne.get("tgt", ne.get("dst", "")))
        if "relation" not in ne:
            ne["relation"] = ne.get("type", ne.get("label", ""))
        normalized_edges.append(ne)

    return {"vertices": normalized_vertices, "edges": normalized_edges}
