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
# May-June 2026 | Invariant Research

import time
import json
import hashlib
import logging
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
            return

        rng = np.random.RandomState(self.seed)
        graph = SheafGraph()

        # Add vertices
        vertex_ids = {}
        self._vertex_key_labels = {}  # reset on reload
        for v in vertices:
            vid_key = v.get("id", v.get("label", ""))
            label = v.get("label", vid_key)
            vid = graph.add_vertex(label=label, data=v.get("claims", {}))
            vertex_ids[vid_key] = vid
            self._vertex_map[label] = vid
            self._vertex_labels[vid] = label
            self._vertex_key_labels[vid_key] = label

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
        locations, severities, and cryptographic proofs.
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

        # Localize contradictions to edges and filter.
        # KEY RULE 1: if H^1 = 0, the graph has no structural
        # contradictions regardless of energy values.
        # KEY RULE 2: if no constraints are declared, don't report
        # any structural contradictions. The user explicitly said
        # "no rules." H^1 is still in the certificate for transparency.
        contradictions = []
        has_any_acyclic = any(
            c.acyclic for c in self._constraints.values()
        )
        if has_any_acyclic and h1_dim > 0 and total_energy > 1e-8:
            localized = self._cohomology.localize_obstruction(
                section, top_k=50
            )

            energy_floor = total_energy * ENERGY_REPORT_FLOOR

            for loc in localized:
                energy = loc["energy"]
                fraction = loc["fraction"]
                endpoints = loc.get("endpoints", (None, None))
                u_vid = endpoints[0]
                v_vid = endpoints[1]
                e_idx = loc.get("edge", 0)

                # Get relation type for this edge
                relation = ""
                if e_idx < len(self._edge_relations):
                    relation = self._edge_relations[e_idx]

                # ONLY report edges whose relation is declared acyclic.
                # H^1 energy spreads across all edges in a cyclic graph;
                # only the acyclic-declared ones represent real violations.
                constraint = self.get_constraint(relation)
                if not constraint.acyclic:
                    continue

                if energy < energy_floor:
                    continue

                severity = _classify_severity(fraction)
                labels = loc.get("vertex_labels", ("?", "?"))

                proof_data = json.dumps({
                    "edge": e_idx,
                    "endpoints": list(endpoints),
                    "energy": energy,
                    "h1_dim": h1_dim,
                }).encode("utf-8")
                proof_id = generate_proof_id(proof_data)

                explanation = self._generate_explanation(
                    loc, relation, []
                )

                contradictions.append(Contradiction(
                    severity=severity,
                    location=(labels[0] or "?", labels[1] or "?"),
                    edge_index=e_idx,
                    energy=energy,
                    energy_fraction=fraction,
                    explanation=explanation,
                    proof_id=proof_id,
                ))

        elapsed_ms = (time.perf_counter() - t0) * 1000

        # INDEPENDENT CONSTRAINT CHECK: agree_on violations.
        # H^1 detects cycle-based structural contradictions.
        # agree_on, functional, and symmetric constraints are checked
        # as direct graph inspections because they are simpler than
        # what sheaf cohomology is designed for.
        for e_idx, (u, v) in enumerate(self._graph.edges):
            relation = ""
            if e_idx < len(self._edge_relations):
                relation = self._edge_relations[e_idx]

            constraint = self.get_constraint(relation)

            # --- agree_on: property values must match ---
            if constraint.agree_on:
                has_disagreement, disagreeing_keys = (
                    self._has_semantic_disagreement(u, v, relation)
                )
                if has_disagreement:
                    already_reported = any(
                        c.edge_index == e_idx for c in contradictions
                    )
                    if not already_reported:
                        u_label = self._vertex_labels.get(u, "?")
                        v_label = self._vertex_labels.get(v, "?")
                        proof_data = json.dumps({
                            "edge": e_idx,
                            "agree_on_violation": disagreeing_keys,
                        }).encode("utf-8")
                        proof_id = generate_proof_id(proof_data)
                        contradictions.append(Contradiction(
                            severity="HIGH",
                            location=(u_label, v_label),
                            edge_index=e_idx,
                            energy=0.0,
                            energy_fraction=0.0,
                            explanation=(
                                "Constraint violation between '%s' and '%s' (%s): "
                                "disagreement on %s."
                                % (u_label, v_label, relation or "related",
                                   ", ".join(disagreeing_keys))
                            ),
                            proof_id=proof_id,
                        ))

        # --- cardinality: min/max outgoing edges of this type ---
        # Generalizes the old functional check. functional=True is
        # shorthand for max_targets=1. New: min_targets and max_targets
        # support "a board has 5-15 directors" or "exactly 2 parents."
        if self._edge_data:
            from collections import defaultdict
            outgoing_count = defaultdict(list)  # (src_key, rel) -> [target_labels]
            for src_key, tgt_key, relation, value in self._edge_data:
                c = self.get_constraint(relation)
                if c.effective_max_targets() is not None or c.min_targets is not None:
                    tgt_label = self._vertex_key_labels.get(tgt_key, tgt_key)
                    outgoing_count[(src_key, relation)].append(tgt_label)

            for (node_key, rel), targets in outgoing_count.items():
                c = self.get_constraint(rel)
                node_label = self._vertex_key_labels.get(node_key, node_key)
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

            # --- transitive: if (A, B) and (B, C) exist, (A, C) must exist ---
            # Only checks one-hop gaps (A->B->C without A->C).
            # Does not compute the full transitive closure.
            for rel_type, constraint in self._constraints.items():
                if not constraint.transitive:
                    continue
                # Build adjacency for this relation type
                adj = {}       # src_key -> set of tgt_keys
                edge_set = set()  # (src_key, tgt_key) for fast lookup
                for src_key, tgt_key, relation, value in self._edge_data:
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
                                a_label = self._vertex_key_labels.get(a_key, a_key)
                                b_label = self._vertex_key_labels.get(b_key, b_key)
                                c_label = self._vertex_key_labels.get(c_key, c_key)
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

            # --- symmetric: if (A, B) exists, (B, A) must exist ---
            # Use raw edge data to preserve directionality. The SheafGraph
            # may store edges as undirected pairs, which would cause every
            # edge to appear one-directional and produce false positives.
            directed_edges = {}  # (src_key, tgt_key, rel) -> True
            for src_key, tgt_key, relation, value in self._edge_data:
                c = self.get_constraint(relation)
                if c.symmetric:
                    directed_edges[(src_key, tgt_key, relation)] = True

            for (src_key, tgt_key, rel) in directed_edges:
                if (tgt_key, src_key, rel) not in directed_edges:
                    src_label = self._vertex_key_labels.get(src_key, src_key)
                    tgt_label = self._vertex_key_labels.get(tgt_key, tgt_key)
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

        Adds the proposed edge, checks whether the NEW edge carries
        significant obstruction energy, and returns the result.
        """
        if getattr(self, '_use_standalone', False):
            return self._check_write_standalone(source, target, relation, value)

        if self._sheaf is None:
            raise RuntimeError("No graph loaded. Call load_json/load_dict first.")

        t0 = time.perf_counter()

        src_vid = self._vertex_map.get(source)
        tgt_vid = self._vertex_map.get(target)

        created_src = False
        created_tgt = False

        if src_vid is None:
            src_vid = self._graph.add_vertex(label=source)
            self._vertex_map[source] = src_vid
            self._vertex_labels[src_vid] = source
            created_src = True

        if tgt_vid is None:
            tgt_vid = self._graph.add_vertex(label=target)
            self._vertex_map[target] = tgt_vid
            self._vertex_labels[tgt_vid] = target
            created_tgt = True

        has_edge = self._graph.has_edge(src_vid, tgt_vid)

        if has_edge:
            elapsed_us = (time.perf_counter() - t0) * 1_000_000
            if created_tgt:
                self._graph.remove_vertex(tgt_vid)
                del self._vertex_map[target]
                del self._vertex_labels[tgt_vid]
            if created_src:
                self._graph.remove_vertex(src_vid)
                del self._vertex_map[source]
                del self._vertex_labels[src_vid]
            return WriteCheckResult(
                creates_contradiction=False,
                elapsed_us=elapsed_us,
            )

        new_edge_idx = self._graph.add_edge(src_vid, tgt_vid, label=relation)
        self._edge_relations.append(relation)
        self._rebuild_sheaf()

        section = self._build_section_from_claims()
        edge_energies = self._sheaf.dirichlet_energy_per_edge(section)
        total_energy = sum(edge_energies.values())

        new_edge_energy = edge_energies.get(new_edge_idx, 0.0)

        has_disagreement, disagreeing_keys = (
            self._has_semantic_disagreement(src_vid, tgt_vid, relation)
        )

        energy_fraction = new_edge_energy / (total_energy + 1e-12)
        creates_contradiction = (
            (new_edge_energy > 0.5 and has_disagreement)
            or energy_fraction > 0.05
        )

        elapsed_us = (time.perf_counter() - t0) * 1_000_000

        if creates_contradiction:
            proof_data = json.dumps({
                "write_source": source,
                "write_target": target,
                "new_edge_energy": new_edge_energy,
                "energy_fraction": energy_fraction,
            }).encode("utf-8")
            proof_id = generate_proof_id(proof_data)

            severity = _classify_severity(energy_fraction)

            constraint = self.get_constraint(relation)
            if constraint.acyclic:
                explanation = (
                    "Circular dependency detected: '%s' -> '%s' (%s) "
                    "closes a cycle in a relationship declared acyclic. "
                    "Energy: %.4f (%.1f%% of total)."
                    % (source, target, relation or "unknown",
                       new_edge_energy, energy_fraction * 100)
                )
            elif disagreeing_keys:
                explanation = (
                    "Write '%s' -> '%s' (%s) creates a structural "
                    "contradiction. Disagreement on: %s. "
                    "Energy: %.4f (%.1f%% of total)."
                    % (source, target, relation or "unknown",
                       ", ".join(disagreeing_keys),
                       new_edge_energy, energy_fraction * 100)
                )
            else:
                explanation = (
                    "Write '%s' -> '%s' (%s) creates a structural "
                    "contradiction. Energy: %.4f (%.1f%% of total)."
                    % (source, target, relation or "unknown",
                       new_edge_energy, energy_fraction * 100)
                )

            self._rollback_write(
                src_vid, tgt_vid, created_src, created_tgt,
                source, target,
            )

            return WriteCheckResult(
                creates_contradiction=True,
                severity=severity,
                conflicting_nodes=[source, target],
                energy_delta=new_edge_energy,
                explanation=explanation,
                proof_id=proof_id,
                elapsed_us=elapsed_us,
            )

        self._rollback_write(
            src_vid, tgt_vid, created_src, created_tgt,
            source, target,
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
        from collections import defaultdict

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
        edge_energies = result["edge_energies"]

        vertices = self._parsed_data.get("vertices", [])
        v_index = {}
        v_claims = []
        v_labels = []
        for i, v in enumerate(vertices):
            vid = v.get("id", v.get("label", str(i)))
            label = v.get("label", vid)
            v_index[vid] = i
            v_claims.append(v.get("claims", {}))
            v_labels.append(label)

        edges_raw = self._parsed_data.get("edges", [])
        edge_pairs = []
        edge_rels = []
        seen_edges = set()
        for e in edges_raw:
            src = e.get("source", e.get("from", ""))
            tgt = e.get("target", e.get("to", ""))
            if src not in v_index or tgt not in v_index:
                continue
            si = v_index[src]
            ti = v_index[tgt]
            if si == ti:
                continue
            a, b = min(si, ti), max(si, ti)
            if (a, b) not in seen_edges:
                seen_edges.add((a, b))
                edge_pairs.append((src, tgt, a, b))
                edge_rels.append(e.get("relation", ""))

        contradictions = []

        # --- H^1-based detection (acyclic constraints only) ---
        has_any_acyclic = any(
            c.acyclic for c in self._constraints.values()
        )
        if has_any_acyclic and h1_dim > 0 and total_energy > 1e-8:
            energy_floor = total_energy * ENERGY_REPORT_FLOOR

            ranked = sorted(
                enumerate(edge_energies), key=lambda x: -x[1]
            )
            for e_idx, energy in ranked:
                if energy < 1e-8:
                    break
                if e_idx >= len(edge_pairs):
                    continue

                src_label, tgt_label, si, ti = edge_pairs[e_idx]
                fraction = energy / total_energy
                relation = edge_rels[e_idx] if e_idx < len(edge_rels) else ""

                # Only report edges whose relation is declared acyclic
                constraint = self.get_constraint(relation)
                if not constraint.acyclic:
                    continue

                if energy < energy_floor:
                    continue

                severity = _classify_severity(fraction)
                u_label = v_labels[si] if si < len(v_labels) else src_label
                v_label = v_labels[ti] if ti < len(v_labels) else tgt_label

                proof_data = json.dumps({
                    "edge": e_idx,
                    "energy": energy,
                    "h1_dim": h1_dim,
                }).encode("utf-8")
                proof_id = generate_proof_id(proof_data)

                explanation = self._generate_standalone_explanation(
                    u_label, v_label, relation, energy, fraction, [],
                )

                contradictions.append(Contradiction(
                    severity=severity,
                    location=(u_label, v_label),
                    edge_index=e_idx,
                    energy=energy,
                    energy_fraction=fraction,
                    explanation=explanation,
                    proof_id=proof_id,
                ))

        # --- Direct graph checks (same as full engine path) ---

        # agree_on: property values must match across edge
        for e_idx in range(len(edge_pairs)):
            if e_idx >= len(edge_rels):
                break
            relation = edge_rels[e_idx]
            constraint = self.get_constraint(relation)
            if not constraint.agree_on:
                continue
            src_label, tgt_label, si, ti = edge_pairs[e_idx]
            src_claims = v_claims[si] if si < len(v_claims) else {}
            tgt_claims = v_claims[ti] if ti < len(v_claims) else {}
            disagreeing_keys = []
            for key in sorted(constraint.agree_on):
                u_val = src_claims.get(key)
                v_val = tgt_claims.get(key)
                if u_val is not None and v_val is not None and u_val != v_val:
                    disagreeing_keys.append(key)
            if disagreeing_keys:
                u_label = v_labels[si] if si < len(v_labels) else src_label
                v_label = v_labels[ti] if ti < len(v_labels) else tgt_label
                proof_data = json.dumps({
                    "edge": e_idx,
                    "agree_on_violation": disagreeing_keys,
                }).encode("utf-8")
                proof_id = generate_proof_id(proof_data)
                contradictions.append(Contradiction(
                    severity="HIGH",
                    location=(u_label, v_label),
                    edge_index=e_idx,
                    energy=0.0,
                    energy_fraction=0.0,
                    explanation=(
                        "Constraint violation between '%s' and '%s' (%s): "
                        "disagreement on %s."
                        % (u_label, v_label, relation or "related",
                           ", ".join(disagreeing_keys))
                    ),
                    proof_id=proof_id,
                ))

        # functional/cardinality: min/max outgoing edges per source
        outgoing_count = defaultdict(list)
        for e in edges_raw:
            src = e.get("source", e.get("from", ""))
            tgt = e.get("target", e.get("to", ""))
            rel = e.get("relation", "")
            if src not in v_index or tgt not in v_index:
                continue
            c = self.get_constraint(rel)
            if c.effective_max_targets() is not None or c.min_targets is not None:
                si = v_index[src]
                ti = v_index[tgt]
                tgt_label = v_labels[ti] if ti < len(v_labels) else tgt
                outgoing_count[(src, rel)].append(tgt_label)

        for (node_id, rel), targets in outgoing_count.items():
            c = self.get_constraint(rel)
            count = len(targets)
            eff_max = c.effective_max_targets()
            eff_min = c.min_targets
            si = v_index.get(node_id, -1)
            node_label = v_labels[si] if 0 <= si < len(v_labels) else node_id

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

        # symmetric: if (A, B) exists, (B, A) must exist
        directed_edges = {}
        for e in edges_raw:
            src = e.get("source", e.get("from", ""))
            tgt = e.get("target", e.get("to", ""))
            rel = e.get("relation", "")
            if src not in v_index or tgt not in v_index:
                continue
            c = self.get_constraint(rel)
            if c.symmetric:
                directed_edges[(src, tgt, rel)] = True

        for (src, tgt, rel) in directed_edges:
            if (tgt, src, rel) not in directed_edges:
                si = v_index.get(src, -1)
                ti = v_index.get(tgt, -1)
                src_label = v_labels[si] if 0 <= si < len(v_labels) else src
                tgt_label = v_labels[ti] if 0 <= ti < len(v_labels) else tgt
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

        # transitive: if (A, B) and (B, C) exist, (A, C) must exist
        for rel_type, constraint in self._constraints.items():
            if not constraint.transitive:
                continue
            adj = {}
            edge_set = set()
            for e in edges_raw:
                src = e.get("source", e.get("from", ""))
                tgt = e.get("target", e.get("to", ""))
                rel = e.get("relation", "")
                if src not in v_index or tgt not in v_index:
                    continue
                if rel.upper().replace(" ", "_") == rel_type or rel == rel_type:
                    adj.setdefault(src, set()).add(tgt)
                    edge_set.add((src, tgt))

            gaps_found = 0
            max_gaps = 50
            for a_key, b_keys in adj.items():
                if gaps_found >= max_gaps:
                    break
                for b_key in b_keys:
                    if gaps_found >= max_gaps:
                        break
                    c_keys = adj.get(b_key, set())
                    for c_key in c_keys:
                        if c_key == a_key:
                            continue
                        if (a_key, c_key) not in edge_set:
                            gaps_found += 1
                            if gaps_found > max_gaps:
                                break
                            a_si = v_index.get(a_key, -1)
                            b_si = v_index.get(b_key, -1)
                            c_si = v_index.get(c_key, -1)
                            a_label = v_labels[a_si] if 0 <= a_si < len(v_labels) else a_key
                            b_label = v_labels[b_si] if 0 <= b_si < len(v_labels) else b_key
                            c_label = v_labels[c_si] if 0 <= c_si < len(v_labels) else c_key
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
        """Check a write using the standalone verifier."""
        import copy
        from sigma_guard.standalone_verifier import build_sheaf, compute_cohomology

        t0 = time.perf_counter()

        data_with_write = copy.deepcopy(self._parsed_data)

        existing_ids = set()
        id_to_label = {}
        label_to_id = {}
        for v in data_with_write.get("vertices", []):
            vid = v.get("id", v.get("label", ""))
            vlabel = v.get("label", vid)
            existing_ids.add(vid)
            existing_ids.add(vlabel)
            id_to_label[vid] = vlabel
            label_to_id[vlabel] = vid

        src_id = label_to_id.get(source, source)
        tgt_id = label_to_id.get(target, target)

        if src_id not in existing_ids and source not in existing_ids:
            data_with_write["vertices"].append(
                {"id": source, "label": source, "claims": {}}
            )
        if tgt_id not in existing_ids and target not in existing_ids:
            data_with_write["vertices"].append(
                {"id": target, "label": target, "claims": {}}
            )

        data_with_write["edges"].append({
            "source": src_id,
            "target": tgt_id,
            "relation": relation,
        })

        sheaf_after = build_sheaf(
            data_with_write, stalk_dim=self.stalk_dim, seed=self.seed
        )
        result_after = compute_cohomology(sheaf_after)

        new_edge_energies = result_after["edge_energies"]
        sheaf_before_edges = len(self._parsed_data.get("edges", []))
        new_edge_idx = sheaf_before_edges
        new_edge_energy = 0.0
        if new_edge_idx < len(new_edge_energies):
            new_edge_energy = new_edge_energies[new_edge_idx]

        total_energy = sum(new_edge_energies)
        energy_fraction = new_edge_energy / (total_energy + 1e-12)

        # Check agree_on constraints only
        constraint = self.get_constraint(relation)
        disagreements = []
        if constraint.agree_on:
            v_claims_map = {}
            for v in data_with_write.get("vertices", []):
                vid = v.get("id", v.get("label", ""))
                vlabel = v.get("label", vid)
                claims = v.get("claims", {})
                v_claims_map[vid] = claims
                v_claims_map[vlabel] = claims
            src_claims = v_claims_map.get(source, v_claims_map.get(src_id, {}))
            tgt_claims = v_claims_map.get(target, v_claims_map.get(tgt_id, {}))
            for key in sorted(constraint.agree_on):
                u_val = src_claims.get(key)
                v_val = tgt_claims.get(key)
                if u_val is not None and v_val is not None and u_val != v_val:
                    disagreements.append(key)
        has_disagreement = len(disagreements) > 0

        creates_contradiction = (
            (new_edge_energy > 0.5 and has_disagreement)
            or energy_fraction > 0.05
        )

        elapsed_us = (time.perf_counter() - t0) * 1_000_000

        if creates_contradiction:
            proof_data = json.dumps({
                "write_source": source,
                "write_target": target,
                "new_edge_energy": new_edge_energy,
            }).encode("utf-8")
            proof_id = generate_proof_id(proof_data)

            severity = _classify_severity(energy_fraction)

            if constraint.acyclic:
                explanation = (
                    "Circular dependency detected: '%s' -> '%s' (%s) "
                    "closes a cycle in a relationship declared acyclic. "
                    "Energy: %.4f (%.1f%% of total)."
                    % (source, target, relation or "unknown",
                       new_edge_energy, energy_fraction * 100)
                )
            elif disagreements:
                explanation = (
                    "Write '%s' -> '%s' (%s) creates a structural "
                    "contradiction. Disagreement on: %s. "
                    "Energy: %.4f (%.1f%% of total)."
                    % (source, target, relation or "unknown",
                       ", ".join(disagreements),
                       new_edge_energy, energy_fraction * 100)
                )
            else:
                explanation = (
                    "Write '%s' -> '%s' (%s) creates a structural "
                    "contradiction. Energy: %.4f (%.1f%% of total)."
                    % (source, target, relation or "unknown",
                       new_edge_energy, energy_fraction * 100)
                )

            return WriteCheckResult(
                creates_contradiction=True,
                severity=severity,
                conflicting_nodes=[source, target],
                energy_delta=new_edge_energy,
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
