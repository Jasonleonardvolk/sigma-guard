# sigma_guard/parsers/edge_list.py
# Parse edge list files (TSV/CSV) into SIGMA's internal format.
#
# Format: source<tab>target<tab>relation<tab>value (optional columns)

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def parse_edge_list(
    path: str,
    delimiter: str = "\t",
    strict: bool = False,
) -> Dict[str, Any]:
    """Parse an edge list file into SIGMA's internal format.

    Args:
        path: Path to the edge list file.
        delimiter: Column delimiter (default: tab).
        strict: If True, raise on malformed rows instead of
            skipping them. Default False.

    Returns:
        Dict with 'vertices' and 'edges' lists.

    Raises:
        ValueError: In strict mode, if a row has fewer than
            two columns.
    """
    vertices_seen = {}
    edges = []
    skipped = 0

    with open(path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue

            parts = line.split(delimiter)
            if len(parts) < 2:
                if strict:
                    raise ValueError(
                        "Line %d: expected at least 2 columns, "
                        "got %d: %r" % (line_num, len(parts), line)
                    )
                skipped += 1
                logger.warning(
                    "Skipping line %d: fewer than 2 columns: %r",
                    line_num, line,
                )
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

    if skipped > 0:
        logger.warning(
            "Skipped %d malformed row(s) in %s", skipped, path
        )

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
