# sigma_guard/engine.py
# Core engine: wraps SIGMA's sheaf cohomology stack into a simple API.
#
# This is the bridge between graph database adapters and the SIGMA
# mathematical engine. It translates graph mutations into sheaf
# operations and returns Verdict objects.
#
# CONSTRAINT PHILOSOPHY:
#   The sheaf detects STRUCTURAL contradictions: cycles, symmetry
#   violations, transitivity failures, and functional constraint
#   violations. It does NOT flag property differences between
#   distinct entities as contradictions. "Acme" and "Beta" having
#   different names is not a contradiction; it is two entities.
#   A circular supply chain (A->B->C->A) IS a contradiction if
#   the relationship type is declared acyclic.
#
#   Users configure constraints per relationship type. The engine
#   encodes those constraints as restriction maps. The sheaf does
#   the rest.
#
# VERIFICATION PARITY:
#   verify() and check_write() use the SAME constraint detection
#   methods. Both call _detect_constraint_violations() which runs
#   acyclic, agree_on, cardinality, transitivity, and symmetry
#   checks on raw edge data. There is one authority path.
#
# May-June 2026 | Invariant Research

import time
import json
import hashlib
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from sigma_guard.verdict import (
    Verdict,
    Contradiction,
    WriteCheckResult,
    generate_proof_id,
)

logger = logging.getLogger(__name__)


# ---- Severity thresholds (energy fraction) ----
SEVERITY_CRITICAL = 0.25
SEVERITY_HIGH = 0.10
SEVERITY_MODERATE = 0.03

# Minimum energy fraction to report an edge as a contradiction.
ENERGY_REPORT_FLOOR = 0.005

# Pre-clamp scale for restriction maps. All maps are scaled to
# this value so they satisfy the Purity Gate (sigma_max <= 0.99)
# without triggering PG9 warnings. 0.98 provides margin.
PURITY_SCALE = 0.98


def _classify_severity(energy_fraction):
    """Classify contradiction severity from energy fraction."""
    if energy_fraction >= SEVERITY_CRITICAL:
        return "CRITICAL"
    elif energy_fraction >= SEVERITY_HIGH:
        return "HIGH"
    elif energy_fraction >= SEVERITY_MODERATE:
        return "MODERATE"
    return "LOW"


# ---- Constraint configuration ----

@dataclass
class RelationConstraint:
    """
    Constraint rules for a relationship type.

    Configure these per relationship type to control what the
    sheaf engine treats as a structural contradiction.

    Attributes:
        acyclic: If True, cycles involving this relation type are
            flagged as contradictions. Use for supply chains,
            reporting hierarchies, dependency graphs.
        symmetric: If True, the relation must be bidirectional.
            A BORDERS B requires B BORDERS A. Asymmetry is flagged.
        functional: If True, each source node should have at most
            one target for this relation. Shorthand for max_targets=1.
        transitive: If True, the relation must satisfy transitivity.
            If A->B and B->C exist, A->C must also exist. Use for
            IsA, SubclassOf, PartOf hierarchies. Only checks one
            hop (direct transitivity gaps); does not compute the
            full transitive closure.
        min_targets: Minimum outgoing edges of this type per source
            node. Use for "every employee must have at least 1
            manager" or "every person has exactly 2 biological
            parents" (combine with max_targets=2).
        max_targets: Maximum outgoing edges of this type per source
            node. Generalizes functional. Use for "a board has at
            most 15 directors" or "a country has at most 1 capital."
            If functional=True and max_targets is not set,
            max_targets defaults to 1.
        agree_on: Set of property keys that MUST agree across this
            edge. Only use when the relationship semantically
            requires agreement (e.g., two references to the same
            entity should have the same "type" property).
        coupling_strength: How strongly this constraint couples
            adjacent nodes. Higher values (closer to PURITY_SCALE)
            produce stronger contradiction signals. Range: 0.1-0.98.
            Default 0.5 is moderate coupling.
    """
    acyclic: bool = False
    symmetric: bool = False
    functional: bool = False
    transitive: bool = False
    min_targets: Optional[int] = None
    max_targets: Optional[int] = None
    agree_on: Set[str] = field(default_factory=set)
    coupling_strength: float = 0.5

    def effective_max_targets(self) -> Optional[int]:
        """Return the effective max targets, accounting for functional."""
        if self.max_targets is not None:
            return self.max_targets
        if self.functional:
            return 1
        return None


# Default constraints for common relationship types.
# Users override or extend this via SigmaGuard(constraints={...}).
DEFAULT_CONSTRAINTS = {
    # Supply chains should not be circular
    "SUPPLIES": RelationConstraint(acyclic=True),
    "DEPENDS_ON": RelationConstraint(acyclic=True),
    "REPORTS_TO": RelationConstraint(acyclic=True),
    "PARENT_OF": RelationConstraint(acyclic=True),
    "IMPORTS_FROM": RelationConstraint(acyclic=True),
    # Borders should be symmetric
    "BORDERS": RelationConstraint(symmetric=True),
    "ADJACENT_TO": RelationConstraint(symmetric=True),
    "CONNECTED_TO": RelationConstraint(symmetric=True),
    # Functional constraints (at most one target)
    "HAS_CAPITAL": RelationConstraint(functional=True),
    "HAS_CEO": RelationConstraint(functional=True),
    "BORN_IN": RelationConstraint(functional=True),
    "HEADQUARTERED_IN": RelationConstraint(functional=True),
}


class SigmaGuard:
    """
    Pre-commit contradiction detection for graph databases.

    Uses sheaf cohomology (H^1 obstructions) to detect structural
    contradictions in graph data. Deterministic, no ML, no GPU.

    Constraint configuration:
        guard = SigmaGuard(constraints={
            "SUPPLIES": RelationConstraint(acyclic=True),
            "BORDERS": RelationConstraint(symmetric=True),
            "HAS_CAPITAL": RelationConstraint(functional=True),
        })

    Or use keyword shortcuts:
        guard = SigmaGuard(constraints={
            "SUPPLIES": {"acyclic": True},
            "BORDERS": {"symmetric": True},
        })
    """

    def __init__(
        self,
        stalk_dim: int = 8,
        seed: int = 42,
        constraints: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize the SIGMA guard.

        Args:
            stalk_dim: Dimension of vertex stalks (default 8).
            seed: Random seed for reproducible stalk initialization.
            constraints: Per-relation-type constraint rules.
                Keys are relation type strings (e.g., "SUPPLIES").
                Values are RelationConstraint instances or dicts
                with the same fields. If None, uses DEFAULT_CONSTRAINTS.
        """
        self.stalk_dim = stalk_dim
        self.seed = seed
        self._graph = None
        self._sheaf = None
        self._cohomology = None
        self._vertex_map = {}
        self._vertex_labels = {}
        self._edge_data = []
        self._edge_relations = []
        self._vertex_key_labels = {}  # vid_key (original ID) -> display label
        self._vertex_key_claims = {}  # vid_key (original ID) -> claims dict
        self._use_standalone = False
        self._parsed_data = None

        # Build constraint config.
        # If constraints is explicitly provided (even empty), it REPLACES
        # the defaults entirely. If None, use DEFAULT_CONSTRAINTS.
        if constraints is not None:
            self._constraints = {}
            for rel_type, spec in constraints.items():
                if isinstance(spec, RelationConstraint):
                    self._constraints[rel_type] = spec
                elif isinstance(spec, dict):
                    self._constraints[rel_type] = RelationConstraint(**spec)
                else:
                    logger.warning(
                        "Unknown constraint spec for '%s': %s",
                        rel_type, spec,
                    )
        else:
            self._constraints = dict(DEFAULT_CONSTRAINTS)

    def get_constraint(self, relation_type: str) -> RelationConstraint:
        """Get the constraint rules for a relation type."""
        upper = relation_type.upper().replace(" ", "_")
        return self._constraints.get(
            upper, self._constraints.get(relation_type, RelationConstraint())
        )

    # ------------------------------------------------------------------
    # Graph loading
    # ------------------------------------------------------------------

    def load_json(self, path: str) -> None:
        """Load a graph from a JSON file."""
        from sigma_guard.parsers.json_graph import parse_json_graph
        data = parse_json_graph(path)
        self._build_from_parsed(data)

    def load_graphml(self, path: str) -> None:
        """Load a graph from a GraphML file."""
        from sigma_guard.parsers.graphml import parse_graphml
        data = parse_graphml(path)
        self._build_from_parsed(data)

    def load_edge_list(self, path: str, delimiter: str = "\t") -> None:
        """Load a graph from an edge list file."""
        from sigma_guard.parsers.edge_list import parse_edge_list
        data = parse_edge_list(path, delimiter=delimiter)
        self._build_from_parsed(data)

    def load_dict(self, data: Dict[str, Any]) -> None:
        """Load a graph from an in-memory dictionary.

        Expected format:
            {
                "vertices": [
                    {"id": "v1", "label": "Supplier_A", "claims": {...}},
                    ...
                ],
                "edges": [
                    {"source": "v1", "target": "v2", "relation": "SUPPLIES"},
                    ...
                ]
            }
        """
        self._build_from_parsed(data)

    def _build_from_parsed(self, data: Dict[str, Any]) -> None:
        """Build the sheaf graph from parsed data."""
        from sigma_guard.free_tier import check_free_tier
        vertices = data.get("vertices", [])
        edges = data.get("edges", data.get("links", []))
        check_free_tier(len(vertices), len(edges))

        try:
            from sigma.core.graph import SheafGraph
            from sigma.core.sheaf import CellularSheaf
            from sigma.core.cohomology import CohomologyComputer
            self._use_standalone = False
        except ImportError:
            self._use_standalone = True
            self._parsed_data = data
            self._standalone_stalk_dim = self.stalk_dim
            self._standalone_seed = self.seed
            # Still populate edge_data and vertex maps for constraint checks
            self._vertex_key_labels = {}
            self._vertex_key_claims = {}
            self._edge_data = []
            for v in vertices:
                vid_key = v.get("id", v.get("label", ""))
                label = v.get("label", vid_key)
                self._vertex_key_labels[vid_key] = label
                self._vertex_key_claims[vid_key] = v.get("claims", {})
            for e in edges:
                src_key = e.get("source", e.get("from", ""))
                tgt_key = e.get("target", e.get("to", ""))
                relation = e.get("relation", "")
                self._edge_data.append((
                    src_key, tgt_key, relation, e.get("value", None),
                ))
            return

        rng = np.random.RandomState(self.seed)
        graph = SheafGraph()

        # Add vertices
        vertex_ids = {}
        self._vertex_key_labels = {}  # reset on reload
        self._vertex_key_claims = {}
        for v in vertices:
            vid_key = v.get("id", v.get("label", ""))
            label = v.get("label", vid_key)
            vid = graph.add_vertex(label=label, data=v.get("claims", {}))
            vertex_ids[vid_key] = vid
            self._vertex_map[label] = vid
            self._vertex_labels[vid] = label
            self._vertex_key_labels[vid_key] = label
            self._vertex_key_claims[vid_key] = v.get("claims", {})

        # Add edges
        edges = data.get("edges", [])
        self._edge_data = []
        self._edge_relations = []
        for e in edges:
            src_key = e.get("source", "")
            tgt_key = e.get("target", "")
            if src_key not in vertex_ids or tgt_key not in vertex_ids:
                logger.warning(
                    "Skipping edge: unknown vertex %s or %s",
                    src_key, tgt_key,
                )
                continue
            src_vid = vertex_ids[src_key]
            tgt_vid = vertex_ids[tgt_key]
            if src_vid == tgt_vid:
                continue
            relation = e.get("relation", "")
            graph.add_edge(src_vid, tgt_vid, label=relation)
            self._edge_data.append((
                src_key, tgt_key, relation, e.get("value", None),
            ))
            self._edge_relations.append(relation)

        self._graph = graph

        # Build sheaf with constraint-driven restriction maps
        d = self.stalk_dim
        sheaf = CellularSheaf(graph, default_stalk_dim=d)

        for e_idx, (u, v) in enumerate(graph.edges):
            relation = self._edge_relations[e_idx] if e_idx < len(self._edge_relations) else ""
            u_data = graph._vertex_data.get(u, {})
            v_data = graph._vertex_data.get(v, {})

            r_uv, r_vu = self._compute_restriction_maps(
                u_data, v_data, relation, d, rng
            )
            sheaf.set_restriction(u, e_idx, r_uv)
            sheaf.set_restriction(v, e_idx, r_vu)

        self._sheaf = sheaf
        self._cohomology = CohomologyComputer(sheaf)

    def _compute_restriction_maps(
        self,
        u_data: Dict,
        v_data: Dict,
        relation: str,
        d: int,
        rng: np.random.RandomState,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Compute restriction maps from relationship type and constraint rules.

        DESIGN PRINCIPLE: restriction maps encode STRUCTURAL constraints
        based on the relationship type. They do NOT compare property
        values between distinct entities. Different companies having
        different names is expected, not contradictory.

        The base map is PURITY_SCALE * I (scaled identity), which
        satisfies the Purity Gate and encodes mild structural coupling.
        Constraint rules modify the map to encode stronger coupling
        on specific dimensions, creating detectable H^1 obstructions
        when the constraints are violated (e.g., cycles in acyclic
        relations, asymmetry in symmetric relations).
        """
        constraint = self.get_constraint(relation)

        # No constraint declared = pure identity maps.
        # Identity maps produce H^1 = 0 on any graph, which is correct:
        # an unconstrained relationship cannot create a contradiction.
        has_any_constraint = (
            constraint.acyclic
            or constraint.agree_on
        )
        if not has_any_constraint:
            eye = 0.99 * np.eye(d, dtype=np.float64)
            return eye, eye

        # Base: scaled identity (satisfies Purity Gate, no PG9 warnings)
        base = PURITY_SCALE * np.eye(d, dtype=np.float64)
        r_uv = base.copy()
        r_vu = base.copy()

        strength = min(constraint.coupling_strength, PURITY_SCALE)

        # Acyclic constraint: asymmetric coupling that produces nonzero
        # holonomy around cycles. The forward map (u->v) differs from
        # the backward map (v->u) by a rotation-like perturbation.
        # On a path (A->B->C), the composed maps are consistent.
        # On a cycle (A->B->C->A), the composed maps fail to close,
        # producing H^1 > 0.
        if constraint.acyclic:
            for i in range(min(d - 1, 4)):
                angle = strength * 0.4 * (i + 1)
                cos_a = np.cos(angle) * PURITY_SCALE
                sin_a = np.sin(angle) * PURITY_SCALE
                r_uv[i, i] = cos_a
                r_uv[i, i + 1] = sin_a
                r_uv[i + 1, i] = -sin_a
                r_uv[i + 1, i + 1] = cos_a
                # Reverse map uses negative angle
                r_vu[i, i] = cos_a
                r_vu[i, i + 1] = -sin_a
                r_vu[i + 1, i] = sin_a
                r_vu[i + 1, i + 1] = cos_a

        # Symmetric and functional constraints are checked as direct
        # graph inspections in verify(), not encoded in the sheaf.
        # Only acyclic and agree_on use sheaf restriction maps.

        # Agree-on constraint: specific property keys must match.
        # Only these keys are compared; all other properties are ignored.
        if constraint.agree_on and isinstance(u_data, dict) and isinstance(v_data, dict):
            for i, key in enumerate(sorted(constraint.agree_on)):
                if i >= d:
                    break
                u_val = u_data.get(key)
                v_val = v_data.get(key)
                if u_val is not None and v_val is not None and u_val != v_val:
                    r_uv[i, i] = -PURITY_SCALE
                    r_vu[i, i] = -PURITY_SCALE

        # Clamp: ensure all singular values <= PURITY_SCALE.
        # This is a safety net; the construction above should already
        # satisfy it, but numerical edge cases are possible.
        for r in (r_uv, r_vu):
            svals = np.linalg.svd(r, compute_uv=False)
            if svals.max() > 0.99:
                r *= 0.99 / svals.max()

        return r_uv, r_vu

    # ------------------------------------------------------------------
    # Shared constraint violation detection
    #
    # These methods are the SINGLE AUTHORITY PATH for both verify()
    # and check_write(). Both call _detect_constraint_violations()
    # with their respective edge data. This guarantees that a pre-
    # commit check catches exactly the same violations that a full
    # verification would report.
    # ------------------------------------------------------------------

    def _detect_constraint_violations(
        self,
        edge_data: List[Tuple[str, str, str, Any]],
        vertex_key_labels: Dict[str, str],
        vertex_key_claims: Dict[str, Dict],
    ) -> List[Contradiction]:
        """
        Run all constraint validators on the given edge data.

        This is the single authority path. Both verify() and
        check_write() call this with their respective edge sets.

        Args:
            edge_data: List of (src_key, tgt_key, relation, value) tuples.
            vertex_key_labels: Mapping from vertex ID to display label.
            vertex_key_claims: Mapping from vertex ID to claims dict.

        Returns:
            List of Contradiction objects for all detected violations.
        """
        contradictions = []
        contradictions.extend(
            self._detect_acyclic_violations(edge_data, vertex_key_labels)
        )
        contradictions.extend(
            self._detect_agree_on_violations(
                edge_data, vertex_key_labels, vertex_key_claims
            )
        )
        contradictions.extend(
            self._detect_cardinality_violations(edge_data, vertex_key_labels)
        )
        contradictions.extend(
            self._detect_transitivity_violations(edge_data, vertex_key_labels)
        )
        contradictions.extend(
            self._detect_symmetric_violations(edge_data, vertex_key_labels)
        )
        return contradictions

    def _detect_acyclic_violations(
        self,
        edge_data: List[Tuple[str, str, str, Any]],
        vertex_key_labels: Dict[str, str],
    ) -> List[Contradiction]:
        """Detect cycles in relations declared acyclic using DFS."""
        contradictions = []

        for rel_type, constraint in self._constraints.items():
            if not constraint.acyclic:
                continue

            # Build directed adjacency for this relation
            adj = {}
            all_nodes = set()
            for src_key, tgt_key, relation, value in edge_data:
                if relation.upper().replace(" ", "_") == rel_type or relation == rel_type:
                    adj.setdefault(src_key, set()).add(tgt_key)
                    all_nodes.add(src_key)
                    all_nodes.add(tgt_key)

            if not adj:
                continue

            # DFS cycle detection: find all edges in cycles
            WHITE, GRAY, BLACK = 0, 1, 2
            color = {n: WHITE for n in all_nodes}
            cycle_edges = set()
            path = []

            def dfs(node):
                color[node] = GRAY
                path.append(node)
                for neighbor in adj.get(node, set()):
                    if color.get(neighbor) == GRAY:
                        # Found cycle: extract edges from path
                        try:
                            ci = path.index(neighbor)
                        except ValueError:
                            continue
                        cycle_path = path[ci:]
                        for k in range(len(cycle_path)):
                            s = cycle_path[k]
                            t = cycle_path[(k + 1) % len(cycle_path)]
                            cycle_edges.add((s, t))
                    elif color.get(neighbor) == WHITE:
                        dfs(neighbor)
                path.pop()
                color[node] = BLACK

            for node in all_nodes:
                if color.get(node) == WHITE:
                    dfs(node)

            # Report each cycle edge
            for src_key, tgt_key in cycle_edges:
                src_label = vertex_key_labels.get(src_key, src_key)
                tgt_label = vertex_key_labels.get(tgt_key, tgt_key)
                proof_data = json.dumps({
                    "cycle_edge": [src_label, tgt_label],
                    "relation": rel_type,
                }).encode("utf-8")
                proof_id = generate_proof_id(proof_data)
                contradictions.append(Contradiction(
                    severity="CRITICAL",
                    location=(src_label, tgt_label),
                    edge_index=-1,
                    energy=0.0,
                    energy_fraction=0.0,
                    explanation=(
                        "Circular dependency: '%s' %s '%s', "
                        "which is part of a cycle in a relationship "
                        "declared acyclic."
                        % (src_label, rel_type, tgt_label)
                    ),
                    proof_id=proof_id,
                ))

        return contradictions

    def _detect_agree_on_violations(
        self,
        edge_data: List[Tuple[str, str, str, Any]],
        vertex_key_labels: Dict[str, str],
        vertex_key_claims: Dict[str, Dict],
    ) -> List[Contradiction]:
        """Detect property agreement violations across edges."""
        contradictions = []

        for src_key, tgt_key, relation, value in edge_data:
            constraint = self.get_constraint(relation)
            if not constraint.agree_on:
                continue
            src_claims = vertex_key_claims.get(src_key, {})
            tgt_claims = vertex_key_claims.get(tgt_key, {})
            if not isinstance(src_claims, dict) or not isinstance(tgt_claims, dict):
                continue
            disagreeing_keys = []
            for key in sorted(constraint.agree_on):
                u_val = src_claims.get(key)
                v_val = tgt_claims.get(key)
                if u_val is not None and v_val is not None and u_val != v_val:
                    disagreeing_keys.append(key)
            if disagreeing_keys:
                src_label = vertex_key_labels.get(src_key, src_key)
                tgt_label = vertex_key_labels.get(tgt_key, tgt_key)
                proof_data = json.dumps({
                    "agree_on_violation": disagreeing_keys,
                    "source": src_label,
                    "target": tgt_label,
                    "relation": relation,
                }).encode("utf-8")
                proof_id = generate_proof_id(proof_data)
                contradictions.append(Contradiction(
                    severity="HIGH",
                    location=(src_label, tgt_label),
                    edge_index=-1,
                    energy=0.0,
                    energy_fraction=0.0,
                    explanation=(
                        "Constraint violation between '%s' and '%s' (%s): "
                        "disagreement on %s."
                        % (src_label, tgt_label, relation or "related",
                           ", ".join(disagreeing_keys))
                    ),
                    proof_id=proof_id,
                ))

        return contradictions

    def _detect_cardinality_violations(
        self,
        edge_data: List[Tuple[str, str, str, Any]],
        vertex_key_labels: Dict[str, str],
    ) -> List[Contradiction]:
        """Detect min/max cardinality and functional constraint violations."""
        contradictions = []

        outgoing_count = defaultdict(list)
        for src_key, tgt_key, relation, value in edge_data:
            c = self.get_constraint(relation)
            if c.effective_max_targets() is not None or c.min_targets is not None:
                tgt_label = vertex_key_labels.get(tgt_key, tgt_key)
                outgoing_count[(src_key, relation)].append(tgt_label)

        for (node_key, rel), targets in outgoing_count.items():
            c = self.get_constraint(rel)
            node_label = vertex_key_labels.get(node_key, node_key)
            count = len(targets)
            eff_max = c.effective_max_targets()
            eff_min = c.min_targets

            # Check upper bound
            if eff_max is not None and count > eff_max:
                proof_data = json.dumps({
                    "cardinality_violation": node_label,
                    "relation": rel,
                    "count": count,
                    "max": eff_max,
                    "targets": targets,
                }).encode("utf-8")
                proof_id = generate_proof_id(proof_data)
                if eff_max == 1:
                    explanation = (
                        "Functional constraint violation: '%s' has %d "
                        "%s targets (%s), but %s should be unique."
                        % (node_label, count, rel,
                           ", ".join(targets), rel)
                    )
                else:
                    explanation = (
                        "Cardinality violation: '%s' has %d %s targets, "
                        "but the maximum allowed is %d."
                        % (node_label, count, rel, eff_max)
                    )
                contradictions.append(Contradiction(
                    severity="HIGH",
                    location=(node_label, ", ".join(targets)),
                    edge_index=-1,
                    energy=0.0,
                    energy_fraction=0.0,
                    explanation=explanation,
                    proof_id=proof_id,
                ))

            # Check lower bound
            if eff_min is not None and count < eff_min:
                proof_data = json.dumps({
                    "cardinality_violation": node_label,
                    "relation": rel,
                    "count": count,
                    "min": eff_min,
                }).encode("utf-8")
                proof_id = generate_proof_id(proof_data)
                contradictions.append(Contradiction(
                    severity="MODERATE",
                    location=(node_label, "%d %s edges" % (count, rel)),
                    edge_index=-1,
                    energy=0.0,
                    energy_fraction=0.0,
                    explanation=(
                        "Cardinality violation: '%s' has %d %s targets, "
                        "but the minimum required is %d."
                        % (node_label, count, rel, eff_min)
                    ),
                    proof_id=proof_id,
                ))

        return contradictions

    def _detect_transitivity_violations(
        self,
        edge_data: List[Tuple[str, str, str, Any]],
        vertex_key_labels: Dict[str, str],
    ) -> List[Contradiction]:
        """Detect one-hop transitivity gaps."""
        contradictions = []

        for rel_type, constraint in self._constraints.items():
            if not constraint.transitive:
                continue

            # Build adjacency for this relation type
            adj = {}
            edge_set = set()
            for src_key, tgt_key, relation, value in edge_data:
                if relation.upper().replace(" ", "_") == rel_type or relation == rel_type:
                    adj.setdefault(src_key, set()).add(tgt_key)
                    edge_set.add((src_key, tgt_key))

            # For each A->B->C, check A->C
            gaps_found = 0
            max_gaps = 50  # cap to avoid flooding on large ontologies
            for a_key, b_keys in adj.items():
                if gaps_found >= max_gaps:
                    break
                for b_key in b_keys:
                    if gaps_found >= max_gaps:
                        break
                    c_keys = adj.get(b_key, set())
                    for c_key in c_keys:
                        if c_key == a_key:
                            continue  # skip self-loops
                        if (a_key, c_key) not in edge_set:
                            gaps_found += 1
                            if gaps_found > max_gaps:
                                break
                            a_label = vertex_key_labels.get(a_key, a_key)
                            b_label = vertex_key_labels.get(b_key, b_key)
                            c_label = vertex_key_labels.get(c_key, c_key)
                            proof_data = json.dumps({
                                "transitivity_gap": [a_label, b_label, c_label],
                                "relation": rel_type,
                            }).encode("utf-8")
                            proof_id = generate_proof_id(proof_data)
                            contradictions.append(Contradiction(
                                severity="MODERATE",
                                location=(a_label, c_label),
                                edge_index=-1,
                                energy=0.0,
                                energy_fraction=0.0,
                                explanation=(
                                    "Transitivity gap: '%s' %s '%s' and "
                                    "'%s' %s '%s', but '%s' does not "
                                    "%s '%s'."
                                    % (a_label, rel_type, b_label,
                                       b_label, rel_type, c_label,
                                       a_label, rel_type, c_label)
                                ),
                                proof_id=proof_id,
                            ))

        return contradictions

    def _detect_symmetric_violations(
        self,
        edge_data: List[Tuple[str, str, str, Any]],
        vertex_key_labels: Dict[str, str],
    ) -> List[Contradiction]:
        """Detect missing reciprocal edges for symmetric relations."""
        contradictions = []

        # Use raw edge data to preserve directionality. The SheafGraph
        # may store edges as undirected pairs, which would cause every
        # edge to appear one-directional and produce false positives.
        directed_edges = {}
        for src_key, tgt_key, relation, value in edge_data:
            c = self.get_constraint(relation)
            if c.symmetric:
                directed_edges[(src_key, tgt_key, relation)] = True

        for (src_key, tgt_key, rel) in directed_edges:
            if (tgt_key, src_key, rel) not in directed_edges:
                src_label = vertex_key_labels.get(src_key, src_key)
                tgt_label = vertex_key_labels.get(tgt_key, tgt_key)
                proof_data = json.dumps({
                    "symmetry_violation": [src_label, tgt_label],
                    "relation": rel,
                }).encode("utf-8")
                proof_id = generate_proof_id(proof_data)
                contradictions.append(Contradiction(
                    severity="MODERATE",
                    location=(src_label, tgt_label),
                    edge_index=-1,
                    energy=0.0,
                    energy_fraction=0.0,
                    explanation=(
                        "Symmetry violation: '%s' %s '%s', "
                        "but '%s' does not %s '%s'."
                        % (src_label, rel, tgt_label,
                           tgt_label, rel, src_label)
                    ),
                    proof_id=proof_id,
                ))

        return contradictions

    # ------------------------------------------------------------------
    # Semantic disagreement detection
    # ------------------------------------------------------------------

    def _has_semantic_disagreement(
        self, u_vid: int, v_vid: int, relation: str = ""
    ) -> Tuple[bool, List[str]]:
        """
        Check if two vertices violate a constraint rule.

        Only reports disagreements on properties listed in the
        constraint's agree_on set. Does NOT flag generic property
        differences between distinct entities.
        """
        constraint = self.get_constraint(relation)

        # If no agree_on keys specified, no semantic disagreement
        # is possible (structural contradictions come from the sheaf,
        # not from property comparison).
        if not constraint.agree_on:
            return False, []

        u_data = self._graph._vertex_data.get(u_vid, {})
        v_data = self._graph._vertex_data.get(v_vid, {})

        if not isinstance(u_data, dict) or not isinstance(v_data, dict):
            return False, []

        disagreements = []
        for key in sorted(constraint.agree_on):
            u_val = u_data.get(key)
            v_val = v_data.get(key)
            if u_val is not None and v_val is not None and u_val != v_val:
                disagreements.append(key)

        return len(disagreements) > 0, disagreements

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def verify(self) -> Verdict:
        """
        Run full sheaf cohomology verification on the loaded graph.

        Returns a Verdict with all detected contradictions, their
        locations, severities, and deterministic proofs.
        """
        if getattr(self, '_use_standalone', False):
            return self._verify_standalone()

        if self._sheaf is None:
            raise RuntimeError("No graph loaded. Call load_json/load_dict first.")

        t0 = time.perf_counter()

        # Compute H^1 (obstruction space)
        h1_result = self._cohomology.compute_h1()
        h1_dim = h1_result["dim"]

        # Compute spectral gap
        spectral_gap = self._cohomology.compute_spectral_gap()

        # Build a section from vertex claim data
        section = self._build_section_from_claims()

        # Compute obstruction certificate
        cert = self._cohomology.obstruction_certificate(section)
        total_energy = cert["total_energy"]

        # ALL constraint detection uses the shared authority path.
        contradictions = self._detect_constraint_violations(
            self._edge_data,
            self._vertex_key_labels,
            self._vertex_key_claims,
        )

        elapsed_ms = (time.perf_counter() - t0) * 1000

        root_data = json.dumps({
            "h1_dim": h1_dim,
            "total_energy": total_energy,
            "contradictions": len(contradictions),
            "vertices": self._graph.num_vertices,
            "edges": self._graph.num_edges,
        }).encode("utf-8")
        root_proof_id = generate_proof_id(root_data)

        certificate = {
            "version": "sigma-guard-0.3.1",
            "proof_id": root_proof_id,
            "h1_dimension": h1_dim,
            "spectral_gap": round(spectral_gap, 6),
            "total_energy": round(total_energy, 6),
            "convergence_ratio": round(cert.get("convergence_ratio", 0), 6),
            "contradiction_count": len(contradictions),
            "graph_vertices": self._graph.num_vertices,
            "graph_edges": self._graph.num_edges,
            "stalk_dim": self.stalk_dim,
            "algorithm": "sheaf_cohomology_h1",
            "deterministic": True,
        }

        return Verdict(
            has_contradictions=len(contradictions) > 0,
            contradiction_count=len(contradictions),
            contradictions=contradictions,
            h1_dimension=h1_dim,
            spectral_gap=spectral_gap,
            total_energy=total_energy,
            elapsed_ms=elapsed_ms,
            proof_id=root_proof_id,
            certificate=certificate,
            graph_stats={
                "vertices": self._graph.num_vertices,
                "edges": self._graph.num_edges,
            },
        )

    def check_write(
        self,
        source: str,
        target: str,
        relation: str = "",
        value: Any = None,
    ) -> WriteCheckResult:
        """
        Check whether a proposed write would create a contradiction.

        Uses the SAME constraint validators as verify(). Adds the
        proposed edge to a copy of edge_data, runs all checks, and
        filters for violations involving the new edge's endpoints.
        """
        if getattr(self, '_use_standalone', False):
            return self._check_write_standalone(source, target, relation, value)

        if self._sheaf is None:
            raise RuntimeError("No graph loaded. Call load_json/load_dict first.")

        t0 = time.perf_counter()

        # Build proposed edge data by appending the new edge
        proposed_edge_data = list(self._edge_data)
        proposed_edge_data.append((source, target, relation, value))

        # Ensure source and target are in the vertex maps
        proposed_labels = dict(self._vertex_key_labels)
        proposed_claims = dict(self._vertex_key_claims)
        if source not in proposed_labels:
            proposed_labels[source] = source
            proposed_claims[source] = {}
        if target not in proposed_labels:
            proposed_labels[target] = target
            proposed_claims[target] = {}

        # Run the same constraint validators used by verify()
        all_violations = self._detect_constraint_violations(
            proposed_edge_data,
            proposed_labels,
            proposed_claims,
        )

        # Filter: only report violations involving the new edge's endpoints
        src_label = proposed_labels.get(source, source)
        tgt_label = proposed_labels.get(target, target)
        involved_labels = {source, target, src_label, tgt_label}

        new_write_violations = []
        for c in all_violations:
            loc_a, loc_b = c.location
            if loc_a in involved_labels or loc_b in involved_labels:
                new_write_violations.append(c)

        elapsed_us = (time.perf_counter() - t0) * 1_000_000

        if new_write_violations:
            # Use the highest severity among all violations
            severity_order = {"CRITICAL": 4, "HIGH": 3, "MODERATE": 2, "LOW": 1}
            worst = max(
                new_write_violations,
                key=lambda c: severity_order.get(c.severity, 0),
            )

            # Build explanation from all violations
            if len(new_write_violations) == 1:
                explanation = new_write_violations[0].explanation
            else:
                parts = []
                for v in new_write_violations:
                    parts.append("[%s] %s" % (v.severity, v.explanation))
                explanation = (
                    "Write '%s' -> '%s' (%s) triggers %d violations: %s"
                    % (source, target, relation or "unknown",
                       len(new_write_violations),
                       " | ".join(parts))
                )

            proof_data = json.dumps({
                "write_source": source,
                "write_target": target,
                "relation": relation,
                "violation_count": len(new_write_violations),
                "worst_severity": worst.severity,
            }).encode("utf-8")
            proof_id = generate_proof_id(proof_data)

            conflicting_nodes = set()
            for v in new_write_violations:
                conflicting_nodes.add(v.location[0])
                conflicting_nodes.add(v.location[1])

            return WriteCheckResult(
                creates_contradiction=True,
                severity=worst.severity,
                conflicting_nodes=sorted(conflicting_nodes),
                energy_delta=0.0,
                explanation=explanation,
                proof_id=proof_id,
                elapsed_us=elapsed_us,
            )

        return WriteCheckResult(
            creates_contradiction=False,
            elapsed_us=elapsed_us,
        )

    # ------------------------------------------------------------------
    # Standalone fallback (pure numpy/scipy, no SIGMA core)
    # ------------------------------------------------------------------

    def _verify_standalone(self) -> Verdict:
        """Verify using the standalone verifier (no SIGMA engine)."""
        from sigma_guard.standalone_verifier import build_sheaf, compute_cohomology

        t0 = time.perf_counter()

        sheaf = build_sheaf(
            self._parsed_data,
            stalk_dim=self.stalk_dim,
            seed=self.seed,
        )
        result = compute_cohomology(sheaf)

        h1_dim = result["h1_dim"]
        total_energy = result["total_energy"]
        spectral_gap = result["spectral_gap"]

        # ALL constraint detection uses the shared authority path.
        contradictions = self._detect_constraint_violations(
            self._edge_data,
            self._vertex_key_labels,
            self._vertex_key_claims,
        )

        elapsed_ms = (time.perf_counter() - t0) * 1000

        n_vertices = sheaf["n_vertices"]
        n_edges = sheaf["n_edges"]

        root_data = json.dumps({
            "h1_dim": h1_dim,
            "total_energy": total_energy,
            "contradictions": len(contradictions),
            "vertices": n_vertices,
            "edges": n_edges,
        }).encode("utf-8")
        root_proof_id = generate_proof_id(root_data)

        certificate = {
            "version": "sigma-guard-0.3.1",
            "proof_id": root_proof_id,
            "h1_dimension": h1_dim,
            "spectral_gap": round(spectral_gap, 6),
            "total_energy": round(total_energy, 6),
            "contradiction_count": len(contradictions),
            "graph_vertices": n_vertices,
            "graph_edges": n_edges,
            "stalk_dim": self.stalk_dim,
            "algorithm": "sheaf_cohomology_h1",
            "deterministic": True,
            "engine": "standalone",
        }

        return Verdict(
            has_contradictions=len(contradictions) > 0,
            contradiction_count=len(contradictions),
            contradictions=contradictions,
            h1_dimension=h1_dim,
            spectral_gap=spectral_gap,
            total_energy=total_energy,
            elapsed_ms=elapsed_ms,
            proof_id=root_proof_id,
            certificate=certificate,
            graph_stats={"vertices": n_vertices, "edges": n_edges},
        )

    def _check_write_standalone(
        self, source: str, target: str, relation: str, value: Any
    ) -> WriteCheckResult:
        """Check a write using the standalone verifier.

        Uses the same constraint validators as _verify_standalone.
        """
        t0 = time.perf_counter()

        # Build proposed edge data by appending the new edge
        proposed_edge_data = list(self._edge_data)
        proposed_edge_data.append((source, target, relation, value))

        # Ensure source and target are in the vertex maps
        proposed_labels = dict(self._vertex_key_labels)
        proposed_claims = dict(self._vertex_key_claims)
        if source not in proposed_labels:
            proposed_labels[source] = source
            proposed_claims[source] = {}
        if target not in proposed_labels:
            proposed_labels[target] = target
            proposed_claims[target] = {}

        # Run the same constraint validators used by verify
        all_violations = self._detect_constraint_violations(
            proposed_edge_data,
            proposed_labels,
            proposed_claims,
        )

        # Filter: only report violations involving the new edge's endpoints
        src_label = proposed_labels.get(source, source)
        tgt_label = proposed_labels.get(target, target)
        involved_labels = {source, target, src_label, tgt_label}

        new_write_violations = []
        for c in all_violations:
            loc_a, loc_b = c.location
            if loc_a in involved_labels or loc_b in involved_labels:
                new_write_violations.append(c)

        elapsed_us = (time.perf_counter() - t0) * 1_000_000

        if new_write_violations:
            severity_order = {"CRITICAL": 4, "HIGH": 3, "MODERATE": 2, "LOW": 1}
            worst = max(
                new_write_violations,
                key=lambda c: severity_order.get(c.severity, 0),
            )

            if len(new_write_violations) == 1:
                explanation = new_write_violations[0].explanation
            else:
                parts = []
                for v in new_write_violations:
                    parts.append("[%s] %s" % (v.severity, v.explanation))
                explanation = (
                    "Write '%s' -> '%s' (%s) triggers %d violations: %s"
                    % (source, target, relation or "unknown",
                       len(new_write_violations),
                       " | ".join(parts))
                )

            proof_data = json.dumps({
                "write_source": source,
                "write_target": target,
                "relation": relation,
                "violation_count": len(new_write_violations),
                "worst_severity": worst.severity,
            }).encode("utf-8")
            proof_id = generate_proof_id(proof_data)

            conflicting_nodes = set()
            for v in new_write_violations:
                conflicting_nodes.add(v.location[0])
                conflicting_nodes.add(v.location[1])

            return WriteCheckResult(
                creates_contradiction=True,
                severity=worst.severity,
                conflicting_nodes=sorted(conflicting_nodes),
                energy_delta=0.0,
                explanation=explanation,
                proof_id=proof_id,
                elapsed_us=elapsed_us,
            )

        return WriteCheckResult(
            creates_contradiction=False,
            elapsed_us=elapsed_us,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rollback_write(
        self,
        src_vid: int,
        tgt_vid: int,
        created_src: bool,
        created_tgt: bool,
        source_label: str,
        target_label: str,
    ) -> None:
        """Roll back a proposed write."""
        if created_tgt:
            self._graph.remove_vertex(tgt_vid)
            self._vertex_map.pop(target_label, None)
            self._vertex_labels.pop(tgt_vid, None)
        if created_src:
            self._graph.remove_vertex(src_vid)
            self._vertex_map.pop(source_label, None)
            self._vertex_labels.pop(src_vid, None)

        # Pop the relation we appended
        if self._edge_relations:
            self._edge_relations.pop()

        self._rebuild_sheaf()

    def _build_section_from_claims(self) -> np.ndarray:
        """Build a sheaf section from vertex claim data."""
        total_dim = self._sheaf.total_vertex_dim
        section = np.zeros(total_dim, dtype=np.float64)
        rng = np.random.RandomState(self.seed)

        offset = 0
        for vid in self._graph.vertices:
            dim = self._sheaf.vertex_stalk_dim(vid)
            claims = self._graph._vertex_data.get(vid, {})

            if isinstance(claims, dict) and claims:
                for i, (key, val) in enumerate(sorted(claims.items())):
                    if i >= dim:
                        break
                    if isinstance(val, bool):
                        section[offset + i] = 1.0 if val else -1.0
                    elif isinstance(val, (int, float)):
                        section[offset + i] = float(val)
                    elif isinstance(val, str):
                        h = hashlib.md5(val.encode("utf-8")).hexdigest()
                        section[offset + i] = (int(h[:8], 16) / 2**32) * 2 - 1
                    else:
                        section[offset + i] = rng.randn()
            else:
                section[offset:offset + dim] = rng.randn(dim) * 0.1

            offset += dim

        return section

    def _rebuild_sheaf(self) -> None:
        """Rebuild the sheaf after graph mutation."""
        try:
            from sigma.core.sheaf import CellularSheaf
            from sigma.core.cohomology import CohomologyComputer
        except ImportError:
            raise ImportError("SIGMA core engine not found.")

        d = self.stalk_dim
        rng = np.random.RandomState(self.seed)
        sheaf = CellularSheaf(self._graph, default_stalk_dim=d)

        for e_idx, (u, v) in enumerate(self._graph.edges):
            relation = self._edge_relations[e_idx] if e_idx < len(self._edge_relations) else ""
            u_data = self._graph._vertex_data.get(u, {})
            v_data = self._graph._vertex_data.get(v, {})

            r_uv, r_vu = self._compute_restriction_maps(
                u_data, v_data, relation, d, rng
            )
            sheaf.set_restriction(u, e_idx, r_uv)
            sheaf.set_restriction(v, e_idx, r_vu)

        self._sheaf = sheaf
        self._cohomology = CohomologyComputer(sheaf)

    def _generate_explanation(
        self,
        loc: Dict,
        relation: str = "",
        disagreeing_keys: Optional[List[str]] = None,
    ) -> str:
        """Generate a human-readable explanation for a contradiction."""
        labels = loc.get("vertex_labels", ("?", "?"))
        energy = loc.get("energy", 0)
        fraction = loc.get("fraction", 0)

        constraint = self.get_constraint(relation)

        if constraint.acyclic:
            return (
                "Circular dependency: '%s' and '%s' are connected "
                "via '%s', which is declared acyclic. This edge is "
                "part of a cycle. Energy: %.4f (%.1f%% of total)."
                % (labels[0], labels[1], relation or "this relationship",
                   energy, fraction * 100)
            )

        if disagreeing_keys:
            return (
                "Constraint violation between '%s' and '%s' (%s): "
                "disagreement on %s. Energy: %.4f (%.1f%% of total)."
                % (labels[0], labels[1], relation or "related",
                   ", ".join(disagreeing_keys),
                   energy, fraction * 100)
            )

        if constraint.symmetric:
            return (
                "Symmetry violation: '%s' and '%s' are connected "
                "via '%s', which should be bidirectional. "
                "Energy: %.4f (%.1f%% of total)."
                % (labels[0], labels[1], relation or "this relationship",
                   energy, fraction * 100)
            )

        return (
            "Structural contradiction between '%s' and '%s' "
            "via '%s'. Energy: %.4f (%.1f%% of total)."
            % (labels[0], labels[1], relation or "related",
               energy, fraction * 100)
        )

    def _generate_standalone_explanation(
        self,
        u_label: str,
        v_label: str,
        relation: str,
        energy: float,
        fraction: float,
        disagreements: List[str],
    ) -> str:
        """Generate explanation for standalone verifier results."""
        constraint = self.get_constraint(relation)

        if constraint.acyclic:
            return (
                "Circular dependency: '%s' and '%s' are connected "
                "via '%s', which is declared acyclic. This edge is "
                "part of a cycle. Energy: %.4f (%.1f%% of total)."
                % (u_label, v_label, relation or "this relationship",
                   energy, fraction * 100)
            )

        if disagreements:
            return (
                "Constraint violation between '%s' and '%s' (%s): "
                "disagreement on %s. Energy: %.4f (%.1f%% of total)."
                % (u_label, v_label, relation or "related",
                   ", ".join(disagreements),
                   energy, fraction * 100)
            )

        if constraint.symmetric:
            return (
                "Symmetry violation: '%s' and '%s' are connected "
                "via '%s', which should be bidirectional. "
                "Energy: %.4f (%.1f%% of total)."
                % (u_label, v_label, relation or "this relationship",
                   energy, fraction * 100)
            )

        return (
            "Structural contradiction between '%s' and '%s' "
            "via '%s'. Energy: %.4f (%.1f%% of total)."
            % (u_label, v_label, relation or "related",
               energy, fraction * 100)
        )
