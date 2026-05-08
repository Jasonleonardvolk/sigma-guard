# sigma_guard/parsers/edge_list.py
# Parse edge list files (TSV/CSV) into SIGMA's internal format.
#
# Format: source<tab>target<tab>relation<tab>value (optional columns)

from typing import Any, Dict


def parse_edge_list(path: str, delimiter: str = "\t") -> Dict[str, Any]:
    """Parse an edge list file into SIGMA's internal format."""
    vertices_seen = {}
    edges = []

    with open(path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue

            parts = line.split(delimiter)
            if len(parts) < 2:
                continue

            source = parts[0].strip()
            target = parts[1].strip()
            relation = parts[2].strip() if len(parts) > 2 else ""
            value = parts[3].strip() if len(parts) > 3 else None

            # Track vertices
            if source not in vertices_seen:
                vertices_seen[source] = {"id": source, "label": source, "claims": {}}
            if target not in vertices_seen:
                vertices_seen[target] = {"id": target, "label": target, "claims": {}}

            # If there's a value, add it as a claim on the source vertex
            if value is not None and relation:
                claim_key = "%s_%s" % (relation, target)
                vertices_seen[source]["claims"][claim_key] = _parse_value(value)

            edges.append({
                "source": source,
                "target": target,
                "relation": relation,
                "value": _parse_value(value) if value else None,
            })

    return {
        "vertices": list(vertices_seen.values()),
        "edges": edges,
    }


def _parse_value(s):
    """Try to parse a string as bool, int, float, or leave as string."""
    if s is None:
        return None
    if not isinstance(s, str):
        return s
    lower = s.lower().strip()
    if lower in ("true", "yes"):
        return True
    if lower in ("false", "no"):
        return False
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s
