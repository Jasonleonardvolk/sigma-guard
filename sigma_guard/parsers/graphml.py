# sigma_guard/parsers/graphml.py
# Parse GraphML files into SIGMA's internal format.

import xml.etree.ElementTree as ET
from typing import Any, Dict


def parse_graphml(path: str) -> Dict[str, Any]:
    """Parse a GraphML file into SIGMA's internal format."""
    tree = ET.parse(path)
    root = tree.getroot()

    # Handle GraphML namespace
    ns = {"gml": "http://graphml.graphstruct.org/xmlns"}
    # Try to detect namespace from root tag
    tag = root.tag
    if "{" in tag:
        ns_uri = tag[tag.index("{") + 1:tag.index("}")]
        ns = {"gml": ns_uri}

    # Parse key definitions (attribute names)
    keys = {}
    for key_elem in root.findall(".//gml:key", ns):
        kid = key_elem.get("id", "")
        kname = key_elem.get("attr.name", kid)
        kfor = key_elem.get("for", "all")
        keys[kid] = {"name": kname, "for": kfor}

    # If no namespace worked, try without namespace
    if not keys:
        for key_elem in root.iter():
            if key_elem.tag.endswith("key"):
                kid = key_elem.get("id", "")
                kname = key_elem.get("attr.name", kid)
                kfor = key_elem.get("for", "all")
                keys[kid] = {"name": kname, "for": kfor}

    # Parse vertices
    vertices = []
    for node in root.iter():
        if not node.tag.endswith("node"):
            continue
        nid = node.get("id", "")
        claims = {}
        label = nid
        for data in node:
            if data.tag.endswith("data"):
                key = data.get("key", "")
                value = data.text or ""
                if key in keys:
                    attr_name = keys[key]["name"]
                else:
                    attr_name = key
                # Try to parse value as bool/int/float
                parsed = _parse_value(value)
                if attr_name == "label":
                    label = value
                else:
                    claims[attr_name] = parsed
        vertices.append({"id": nid, "label": label, "claims": claims})

    # Parse edges
    edges = []
    for edge in root.iter():
        if not edge.tag.endswith("edge"):
            continue
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        props = {}
        for data in edge:
            if data.tag.endswith("data"):
                key = data.get("key", "")
                value = data.text or ""
                if key in keys:
                    attr_name = keys[key]["name"]
                else:
                    attr_name = key
                props[attr_name] = _parse_value(value)
        relation = props.pop("relation", props.pop("label", ""))
        edges.append({
            "source": src,
            "target": tgt,
            "relation": relation,
            "value": props if props else None,
        })

    return {"vertices": vertices, "edges": edges}


def _parse_value(s: str):
    """Try to parse a string as bool, int, float, or leave as string."""
    if not s:
        return ""
    lower = s.lower().strip()
    if lower in ("true", "yes", "1"):
        return True
    if lower in ("false", "no", "0"):
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
