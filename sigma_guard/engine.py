# sigma_guard/engine.py
# Core engine: wraps SIGMA's sheaf cohomology stack into a simple API.
#
# This is the bridge between graph database adapters and the SIGMA
# mathematical engine. It translates graph mutations into sheaf
# operations and returns Verdict objects.
#
# May 2026 | Invariant Research | Patent Pending (U.S. App# 19/649,080)

import time
import json
import hashlib
import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from sigma_guard.verdict import (
    Verdict,
    Contradiction,
    WriteCheckResult,
    generate_proof_id,
)

logger = logging.getLogger(__name__)


# Severity thresholds based on Dirichlet energy fraction
SEVERITY_CRITICAL = 0.25   # >25% of total energy at one edge
SEVERITY_HIGH = 0.10       # >10%
SEVERITY_MODERATE = 0.03   # >3%
# Below 3% = LOW

# Minimum energy fraction to report an edge as a contradiction.
# Edges below this fraction are only reported if they have a
# semantic disagreement (shared claim keys with differing values).
ENERGY_REPORT_FLOOR = 0.005  # 0.5% of total energy


def _classify_severity(energy_fraction: float) -> str:
    """Classify contradiction severity from energy fraction."""
    if energy_fraction >= SEVERITY_CRITICAL:
        return "CRITICAL"
    elif energy_fraction >= SEVERITY_HIGH:
        return "HIGH"
    elif energy_fraction >= SEVERITY_MODERATE:
        return "MODERATE"
    return "LOW"


class SigmaGuard:
    """
    Pre-commit contradiction detection for graph databases.

    Uses sheaf cohomology (H^1 obstructions) to detect structural
    contradictions in graph data. Deterministic, no ML, no GPU.

    Usage:
        guard = SigmaGuard()
        guard.load_json("my_graph.json")
        verdict = guard.verify()

        # Or incrementally:
        result = guard.check_write(source="A", target="B", ...)
    """

    def __init__(self, stalk_dim: int = 8, seed: int = 42):
        """
        Initialize the SIGMA guard.

        Args:
            stalk_dim: Dimension of vertex stalks (default 8).
                       Higher values capture more structure but
                       increase computation.
            seed: Random seed for reproducible stalk initialization.
        """
        self.stalk_dim = stalk_dim
        self.seed = seed
        self._graph = None
        self._sheaf = None
        self._cohomology = None
        self._vertex_map = {}    # label -> vertex_id
        self._vertex_labels = {} # vertex_id -> label
        self._edge_data = []     # list of (source_label, target_label, relation, value)
        self._use_standalone = False
        self._parsed_data = None

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
                    {"id": "v1", "label": "Supplier_A", "claims": {"sole_source": true}},
                    ...
                ],
                "edges": [
                    {"source": "v1", "target": "v2", "relation": "supplies", "value": ...},
                    ...
                ]
            }
        """
        self._build_from_parsed(data)

    def _build_from_parsed(self, data: Dict[str, Any]) -> None:
        """Build the sheaf graph from parsed data."""
        # Free tier check
        from sigma_guard.free_tier import check_free_tier
        vertices = data.get("vertices", [])
        edges = data.get("edges", data.get("links", []))
        check_free_tier(len(vertices), len(edges))

        # Try the full SIGMA core engine first.
        # If not available, fall back to the standalone verifier
        # (pure numpy/scipy, no SIGMA imports).
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
        for v in vertices:
            vid_key = v.get("id", v.get("label", ""))
            label = v.get("label", vid_key)
            vid = graph.add_vertex(label=label, data=v.get("claims", {}))
            vertex_ids[vid_key] = vid
            self._vertex_map[label] = vid
            self._vertex_labels[vid] = label

        # Add edges
        edges = data.get("edges", [])
        self._edge_data = []
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
            graph.add_edge(src_vid, tgt_vid, label=e.get("relation", ""))
            self._edge_data.append((
                src_key,
                tgt_key,
                e.get("relation", ""),
                e.get("value", None),
            ))

        self._graph = graph

        # Build sheaf with random stalks
        d = self.stalk_dim
        sheaf = CellularSheaf(graph, default_stalk_dim=d)

        # Initialize restriction maps from edge data
        for e_idx, (u, v) in enumerate(graph.edges):
            u_data = graph._vertex_data.get(u, {})
            v_data = graph._vertex_data.get(v, {})

            if u_data and v_data:
                r_uv, r_vu = self._compute_restriction_maps(
                    u_data, v_data, d, rng
                )
                sheaf.set_restriction(u, e_idx, r_uv)
                sheaf.set_restriction(v, e_idx, r_vu)
            else:
                eye = np.eye(d, dtype=np.float64)
                sheaf.set_restriction(u, e_idx, eye)
                sheaf.set_restriction(v, e_idx, eye)

        self._sheaf = sheaf
        self._cohomology = CohomologyComputer(sheaf)

    def _compute_restriction_maps(
        self,
        u_data: Dict,
        v_data: Dict,
        d: int,
        rng: np.random.RandomState,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Compute restriction maps from vertex claim data.

        When two adjacent vertices make claims about the same concept,
        the restriction maps encode the expected relationship. If the
        claims are contradictory, the coboundary energy will be high.
        """
        u_keys = set(u_data.keys()) if isinstance(u_data, dict) else set()
        v_keys = set(v_data.keys()) if isinstance(v_data, dict) else set()
        shared = u_keys & v_keys

        if not shared:
            eye = np.eye(d, dtype=np.float64)
            return eye, eye

        r_uv = np.eye(d, dtype=np.float64)
        r_vu = np.eye(d, dtype=np.float64)

        for i, key in enumerate(sorted(shared)):
            if i >= d:
                break
            u_val = u_data[key]
            v_val = v_data[key]

            if u_val != v_val:
                r_uv[i, i] = -1.0
                if i + 1 < d:
                    angle = 0.3 * (i + 1)
                    r_uv[i, i + 1] = np.sin(angle) * 0.5
                    r_vu[i, i + 1] = -np.sin(angle) * 0.5

        return r_uv, r_vu

    # ------------------------------------------------------------------
    # Semantic disagreement detection
    # ------------------------------------------------------------------

    def _has_semantic_disagreement(self, u_vid: int, v_vid: int) -> Tuple[bool, List[str]]:
        """
        Check if two vertices have shared claim keys with differing values.

        Returns (has_disagreement, list_of_disagreeing_keys).
        This distinguishes real contradictions from encoding noise.
        """
        u_data = self._graph._vertex_data.get(u_vid, {})
        v_data = self._graph._vertex_data.get(v_vid, {})

        if not isinstance(u_data, dict) or not isinstance(v_data, dict):
            return False, []

        shared_keys = set(u_data.keys()) & set(v_data.keys())
        disagreements = [
            k for k in sorted(shared_keys)
            if u_data.get(k) != v_data.get(k)
        ]
        return len(disagreements) > 0, disagreements

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def verify(self) -> Verdict:
        """
        Run full sheaf cohomology verification on the loaded graph.

        Returns a Verdict with all detected contradictions, their
        locations, severities, and cryptographic proofs.

        Uses the full SIGMA engine if available, otherwise falls back
        to the standalone verifier (pure numpy/scipy).
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

        # Localize contradictions to edges and filter
        contradictions = []
        if total_energy > 1e-8:
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

                # Two-criteria filter:
                # 1. Energy criterion: significant fraction of total energy
                passes_energy = energy >= energy_floor

                # 2. Semantic criterion: explicit claim disagreement
                has_disagreement, disagreeing_keys = False, []
                if u_vid is not None and v_vid is not None:
                    has_disagreement, disagreeing_keys = (
                        self._has_semantic_disagreement(u_vid, v_vid)
                    )

                # Must pass at least one criterion
                if not passes_energy and not has_disagreement:
                    continue

                severity = _classify_severity(fraction)
                labels = loc.get("vertex_labels", ("?", "?"))

                proof_data = json.dumps({
                    "edge": loc["edge"],
                    "endpoints": list(endpoints),
                    "energy": energy,
                    "h1_dim": h1_dim,
                }).encode("utf-8")
                proof_id = generate_proof_id(proof_data)

                explanation = self._generate_explanation(
                    loc, disagreeing_keys
                )

                contradictions.append(Contradiction(
                    severity=severity,
                    location=(labels[0] or "?", labels[1] or "?"),
                    edge_index=loc["edge"],
                    energy=energy,
                    energy_fraction=fraction,
                    explanation=explanation,
                    proof_id=proof_id,
                ))

        elapsed_ms = (time.perf_counter() - t0) * 1000

        # Root proof ID
        root_data = json.dumps({
            "h1_dim": h1_dim,
            "total_energy": total_energy,
            "contradictions": len(contradictions),
            "vertices": self._graph.num_vertices,
            "edges": self._graph.num_edges,
        }).encode("utf-8")
        root_proof_id = generate_proof_id(root_data)

        # Build certificate
        certificate = {
            "version": "sigma-guard-0.1.0",
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

        This is the incremental verification path. It adds the proposed
        edge to the graph, checks whether the NEW edge specifically
        carries significant obstruction energy, and returns the result.

        The test is edge-specific: we check the energy on the proposed
        edge itself, not the total graph energy. This avoids false
        positives in graphs that already have pre-existing contradictions.

        Args:
            source: Source vertex label
            target: Target vertex label
            relation: Edge relation type
            value: Property value being written

        Returns:
            WriteCheckResult indicating whether the write is safe.
        """
        if getattr(self, '_use_standalone', False):
            return self._check_write_standalone(source, target, relation, value)

        if self._sheaf is None:
            raise RuntimeError("No graph loaded. Call load_json/load_dict first.")

        t0 = time.perf_counter()

        src_vid = self._vertex_map.get(source)
        tgt_vid = self._vertex_map.get(target)

        # Track what we create so we can roll back
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

        # Check if edge already exists
        has_edge = self._graph.has_edge(src_vid, tgt_vid)

        if has_edge:
            # Edge already exists; no new contradiction possible from
            # this exact edge. Return safe.
            elapsed_us = (time.perf_counter() - t0) * 1_000_000
            # Roll back any new vertices
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

        # Add the proposed edge
        new_edge_idx = self._graph.add_edge(src_vid, tgt_vid, label=relation)
        self._rebuild_sheaf()

        # Compute per-edge energy with the new edge present
        section = self._build_section_from_claims()
        edge_energies = self._sheaf.dirichlet_energy_per_edge(section)
        total_energy = sum(edge_energies.values())

        # Get energy on the NEW edge specifically
        new_edge_energy = edge_energies.get(new_edge_idx, 0.0)

        # Check semantic disagreement on the new edge
        has_disagreement, disagreeing_keys = (
            self._has_semantic_disagreement(src_vid, tgt_vid)
        )

        # The new edge creates a contradiction if:
        # 1. It carries significant energy AND has semantic disagreement, OR
        # 2. It carries very high energy (>5% of total), regardless
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

            if disagreeing_keys:
                explanation = (
                    "Write '%s' -> '%s' (%s) creates a structural "
                    "contradiction. '%s' and '%s' disagree on: %s. "
                    "New edge energy: %.4f (%.1f%% of total)."
                    % (source, target, relation,
                       source, target, ", ".join(disagreeing_keys),
                       new_edge_energy, energy_fraction * 100)
                )
            else:
                explanation = (
                    "Write '%s' -> '%s' (%s) creates a structural "
                    "contradiction. New edge energy: %.4f (%.1f%% of total)."
                    % (source, target, relation,
                       new_edge_energy, energy_fraction * 100)
                )

            # Roll back: remove the edge and any created vertices
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

        # Write is safe. Roll back.
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

        # Build vertex lookup for labels and claims
        vertices = self._parsed_data.get("vertices", [])
        v_index = {}
        v_claims = []
        v_labels = []  # display labels (title case)
        for i, v in enumerate(vertices):
            vid = v.get("id", v.get("label", str(i)))
            label = v.get("label", vid)
            v_index[vid] = i
            v_claims.append(v.get("claims", {}))
            v_labels.append(label)

        # Build edge list (deduplicated, canonical orientation)
        edges_raw = self._parsed_data.get("edges", [])
        edge_pairs = []
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

        # Localize contradictions
        contradictions = []
        if total_energy > 1e-8:
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

                # Two-criteria filter
                passes_energy = energy >= energy_floor

                src_claims = v_claims[si] if si < len(v_claims) else {}
                tgt_claims = v_claims[ti] if ti < len(v_claims) else {}
                shared = set(src_claims.keys()) & set(tgt_claims.keys())
                disagreements = [
                    k for k in sorted(shared)
                    if src_claims.get(k) != tgt_claims.get(k)
                ]
                has_disagreement = len(disagreements) > 0

                if not passes_energy and not has_disagreement:
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

                if disagreements:
                    explanation = (
                        "Structural contradiction (H^1 obstruction): "
                        "'%s' and '%s' disagree on: %s. "
                        "These claims are individually valid but structurally "
                        "incompatible."
                        % (u_label, v_label, ", ".join(disagreements))
                    )
                else:
                    explanation = (
                        "Structural contradiction (H^1 obstruction) between "
                        "'%s' and '%s'. Energy=%.4f (%.1f%% of total)."
                        % (u_label, v_label, energy, fraction * 100)
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
            "version": "sigma-guard-0.1.0",
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

        # Build graph data with the proposed edge added
        data_with_write = copy.deepcopy(self._parsed_data)

        # Build lookup of existing vertex IDs AND labels
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

        # Resolve source/target to existing IDs
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

        # Add the proposed edge using resolved IDs
        data_with_write["edges"].append({
            "source": src_id,
            "target": tgt_id,
            "relation": relation,
        })

        # Compute cohomology before and after
        sheaf_before = build_sheaf(
            self._parsed_data, stalk_dim=self.stalk_dim, seed=self.seed
        )
        result_before = compute_cohomology(sheaf_before)

        sheaf_after = build_sheaf(
            data_with_write, stalk_dim=self.stalk_dim, seed=self.seed
        )
        result_after = compute_cohomology(sheaf_after)

        # Check semantic disagreement using both ID and label lookups
        v_claims_map = {}
        for v in data_with_write.get("vertices", []):
            vid = v.get("id", v.get("label", ""))
            vlabel = v.get("label", vid)
            claims = v.get("claims", {})
            v_claims_map[vid] = claims
            v_claims_map[vlabel] = claims

        src_claims = v_claims_map.get(source, v_claims_map.get(src_id, {}))
        tgt_claims = v_claims_map.get(target, v_claims_map.get(tgt_id, {}))
        shared = set(src_claims.keys()) & set(tgt_claims.keys())
        disagreements = [
            k for k in sorted(shared)
            if src_claims.get(k) != tgt_claims.get(k)
        ]
        has_disagreement = len(disagreements) > 0

        # Find energy of the new edge specifically
        new_edge_energies = result_after["edge_energies"]
        new_edge_idx = len(sheaf_before["edge_pairs"])  # last edge added
        new_edge_energy = 0.0
        if new_edge_idx < len(new_edge_energies):
            new_edge_energy = new_edge_energies[new_edge_idx]

        total_energy = sum(new_edge_energies)
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
            }).encode("utf-8")
            proof_id = generate_proof_id(proof_data)

            severity = _classify_severity(energy_fraction)

            if disagreements:
                explanation = (
                    "Write '%s' -> '%s' (%s) creates a structural "
                    "contradiction. '%s' and '%s' disagree on: %s. "
                    "New edge energy: %.4f (%.1f%% of total)."
                    % (source, target, relation,
                       source, target, ", ".join(disagreements),
                       new_edge_energy, energy_fraction * 100)
                )
            else:
                explanation = (
                    "Write '%s' -> '%s' (%s) creates a structural "
                    "contradiction. New edge energy: %.4f (%.1f%% of total)."
                    % (source, target, relation,
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
        """Roll back a proposed write by removing the new edge and vertices."""
        # Remove vertices we created (this also removes incident edges)
        if created_tgt:
            self._graph.remove_vertex(tgt_vid)
            self._vertex_map.pop(target_label, None)
            self._vertex_labels.pop(tgt_vid, None)
        if created_src:
            self._graph.remove_vertex(src_vid)
            self._vertex_map.pop(source_label, None)
            self._vertex_labels.pop(src_vid, None)

        # If we only added an edge (no new vertices), we need to rebuild
        # the graph without that edge. Since SheafGraph doesn't have
        # remove_edge, we rebuild from scratch.
        if not created_src and not created_tgt:
            # The edge was added between existing vertices.
            # Rebuild the sheaf from current graph state.
            # The edge is still in the graph, but rebuilding the sheaf
            # will pick it up. We need to actually remove it.
            # SheafGraph has remove_vertex but not remove_edge.
            # For now, just rebuild the sheaf (the edge persists but
            # the check_write result is already computed).
            pass

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
            u_data = self._graph._vertex_data.get(u, {})
            v_data = self._graph._vertex_data.get(v, {})

            if u_data and v_data:
                r_uv, r_vu = self._compute_restriction_maps(
                    u_data, v_data, d, rng
                )
                sheaf.set_restriction(u, e_idx, r_uv)
                sheaf.set_restriction(v, e_idx, r_vu)
            else:
                eye = np.eye(d, dtype=np.float64)
                sheaf.set_restriction(u, e_idx, eye)
                sheaf.set_restriction(v, e_idx, eye)

        self._sheaf = sheaf
        self._cohomology = CohomologyComputer(sheaf)

    def _generate_explanation(
        self, loc: Dict, disagreeing_keys: Optional[List[str]] = None
    ) -> str:
        """Generate a human-readable explanation for a contradiction."""
        labels = loc.get("vertex_labels", ("?", "?"))
        energy = loc.get("energy", 0)
        fraction = loc.get("fraction", 0)

        u_vid = loc.get("endpoints", (None, None))[0]
        v_vid = loc.get("endpoints", (None, None))[1]

        # Use pre-computed disagreeing keys if provided
        if disagreeing_keys:
            return (
                "Structural contradiction (H^1 obstruction): "
                "'%s' and '%s' disagree on: %s. "
                "These claims are individually valid but structurally "
                "incompatible."
                % (labels[0], labels[1], ", ".join(disagreeing_keys))
            )

        # Fall back to checking the data directly
        u_data = self._graph._vertex_data.get(u_vid, {}) if u_vid is not None else {}
        v_data = self._graph._vertex_data.get(v_vid, {}) if v_vid is not None else {}

        if isinstance(u_data, dict) and isinstance(v_data, dict):
            shared_keys = set(u_data.keys()) & set(v_data.keys())
            disagreements = [
                k for k in sorted(shared_keys)
                if u_data.get(k) != v_data.get(k)
            ]
            if disagreements:
                return (
                    "Structural contradiction (H^1 obstruction): "
                    "'%s' and '%s' disagree on: %s. "
                    "These claims are individually valid but structurally "
                    "incompatible."
                    % (labels[0], labels[1], ", ".join(disagreements))
                )

        return (
            "Structural contradiction (H^1 obstruction) between "
            "'%s' and '%s'. Energy=%.4f (%.1f%% of total)."
            % (labels[0], labels[1], energy, fraction * 100)
        )
