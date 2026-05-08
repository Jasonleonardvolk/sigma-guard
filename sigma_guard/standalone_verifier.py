# sigma_guard/standalone_verifier.py
# Independent verification of SIGMA proof receipts.
#
# This file uses ONLY numpy and scipy. It does NOT import the SIGMA
# engine. The entire point is that you do not need to trust SIGMA
# to verify a SIGMA verdict. You recompute the math yourself.
#
# Usage:
#   python -m sigma_guard.standalone_verifier \
#       --graph datasets/supply_chain.json \
#       --receipt verdict.json
#
# Or as a library:
#   from sigma_guard.standalone_verifier import verify_receipt
#   result = verify_receipt("graph.json", "verdict.json")
#   print(result["match"])  # True if independent computation agrees
#
# May 2026 | Invariant Research
# This file is released under Apache 2.0 (not BSL) so anyone can
# audit it without license concerns.

"""
Standalone verifier for SIGMA proof receipts.

Recomputes sheaf cohomology (H^0, H^1) from scratch using only
numpy and scipy. Compares the result to a SIGMA verdict to confirm
the verdict is mathematically correct.

No SIGMA engine imports. No trust required.
"""

import json
import sys
import hashlib
import argparse
from typing import Any, Dict, List, Tuple

import numpy as np
import scipy.sparse as sp


# ------------------------------------------------------------------
# Step 1: Parse the graph
# ------------------------------------------------------------------

def load_graph(path: str) -> Dict[str, Any]:
    """Load a JSON graph file."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    vertices = data.get("vertices", data.get("nodes", []))
    edges = data.get("edges", data.get("links", []))
    return {"vertices": vertices, "edges": edges}


# ------------------------------------------------------------------
# Step 2: Build the sheaf (from scratch, no SIGMA)
# ------------------------------------------------------------------

def build_sheaf(
    graph: Dict[str, Any],
    stalk_dim: int = 8,
    seed: int = 42,
) -> Dict[str, Any]:
    """
    Build a cellular sheaf over the graph.

    Returns the coboundary matrix (delta_0), vertex stalk assignments,
    and a section vector built from vertex claims.

    All computation uses only numpy. No SIGMA imports.
    """
    rng = np.random.RandomState(seed)
    vertices = graph["vertices"]
    edges = graph["edges"]

    n_vertices = len(vertices)
    n_edges = len(edges)
    d = stalk_dim

    # Map vertex IDs to indices
    v_ids = []
    v_index = {}
    v_claims = []
    for i, v in enumerate(vertices):
        vid = v.get("id", v.get("label", str(i)))
        v_ids.append(vid)
        v_index[vid] = i
        claims = v.get("claims", {})
        if not isinstance(claims, dict):
            claims = {}
        v_claims.append(claims)

    # Map edges to (source_idx, target_idx) pairs
    edge_pairs = []
    for e in edges:
        src = e.get("source", e.get("from", ""))
        tgt = e.get("target", e.get("to", ""))
        if src not in v_index or tgt not in v_index:
            continue
        si = v_index[src]
        ti = v_index[tgt]
        if si == ti:
            continue
        # Canonical orientation: smaller index first
        a, b = min(si, ti), max(si, ti)
        if (a, b) not in [(ea, eb) for ea, eb in edge_pairs]:
            edge_pairs.append((a, b))

    n_actual_edges = len(edge_pairs)

    # Total dimensions
    total_vertex_dim = n_vertices * d
    total_edge_dim = n_actual_edges * d

    # Build coboundary matrix delta_0: C^0 -> C^1
    # Shape: (total_edge_dim, total_vertex_dim)
    # For each edge e = (u, v), the coboundary block is:
    #   delta_0[e_block, v_block] = R_v  (restriction map at v)
    #   delta_0[e_block, u_block] = -R_u (restriction map at u, negated)

    delta = np.zeros((total_edge_dim, total_vertex_dim), dtype=np.float64)

    for e_idx, (u_idx, v_idx) in enumerate(edge_pairs):
        e_offset = e_idx * d
        u_offset = u_idx * d
        v_offset = v_idx * d

        u_claims_dict = v_claims[u_idx]
        v_claims_dict = v_claims[v_idx]

        # Build restriction maps from claims
        r_u = np.eye(d, dtype=np.float64)
        r_v = np.eye(d, dtype=np.float64)

        shared_keys = sorted(
            set(u_claims_dict.keys()) & set(v_claims_dict.keys())
        )
        for i, key in enumerate(shared_keys):
            if i >= d:
                break
            if u_claims_dict[key] != v_claims_dict[key]:
                # Disagreement: flip sign on this dimension
                r_u[i, i] = -1.0
                if i + 1 < d:
                    angle = 0.3 * (i + 1)
                    r_u[i, i + 1] = np.sin(angle) * 0.5
                    r_v[i, i + 1] = -np.sin(angle) * 0.5

        # Coboundary: delta(s)(e) = R_v * s(v) - R_u * s(u)
        delta[e_offset:e_offset + d, v_offset:v_offset + d] = r_v
        delta[e_offset:e_offset + d, u_offset:u_offset + d] = -r_u

    # Build section from claims
    section = np.zeros(total_vertex_dim, dtype=np.float64)
    for i, claims in enumerate(v_claims):
        offset = i * d
        if claims:
            for j, (key, val) in enumerate(sorted(claims.items())):
                if j >= d:
                    break
                if isinstance(val, bool):
                    section[offset + j] = 1.0 if val else -1.0
                elif isinstance(val, (int, float)):
                    section[offset + j] = float(val)
                elif isinstance(val, str):
                    h = hashlib.md5(val.encode("utf-8")).hexdigest()
                    section[offset + j] = (int(h[:8], 16) / 2**32) * 2 - 1
                else:
                    section[offset + j] = rng.randn()
        else:
            section[offset:offset + d] = rng.randn(d) * 0.1

    return {
        "delta": delta,
        "section": section,
        "n_vertices": n_vertices,
        "n_edges": n_actual_edges,
        "stalk_dim": d,
        "total_vertex_dim": total_vertex_dim,
        "total_edge_dim": total_edge_dim,
        "edge_pairs": edge_pairs,
        "v_ids": v_ids,
        "v_claims": v_claims,
    }


# ------------------------------------------------------------------
# Step 3: Compute cohomology (from scratch, no SIGMA)
# ------------------------------------------------------------------

def compute_cohomology(
    sheaf: Dict[str, Any],
    tol: float = 1e-8,
) -> Dict[str, Any]:
    """
    Compute H^0 and H^1 dimensions via SVD of the coboundary matrix.

    H^0 = ker(delta_0): global sections (consistent states)
    H^1 = coker(delta_0) = C^1 / im(delta_0): obstructions

    dim(H^0) = total_vertex_dim - rank(delta)
    dim(H^1) = total_edge_dim - rank(delta)

    Uses only numpy.linalg.svd. No SIGMA imports.
    """
    delta = sheaf["delta"]
    section = sheaf["section"]

    if delta.size == 0:
        return {
            "h0_dim": sheaf["n_vertices"],
            "h1_dim": 0,
            "rank": 0,
            "total_energy": 0.0,
            "edge_energies": [],
            "spectral_gap": 1.0,
        }

    # SVD of coboundary matrix
    U, S, Vt = np.linalg.svd(delta, full_matrices=True)

    # Rank with relative tolerance
    s0 = float(S[0]) if len(S) > 0 and S[0] > 0 else 1.0
    rel_tol = tol * max(delta.shape[0], delta.shape[1]) * s0
    rank = int(np.sum(S > rel_tol))

    # Cohomology dimensions
    h0_dim = sheaf["total_vertex_dim"] - rank
    h1_dim = sheaf["total_edge_dim"] - rank

    # Coboundary of the section: delta(s)
    coboundary = delta @ section
    total_energy = float(np.dot(coboundary, coboundary))

    # Per-edge Dirichlet energy
    d = sheaf["stalk_dim"]
    edge_energies = []
    for e_idx in range(sheaf["n_edges"]):
        e_offset = e_idx * d
        edge_vec = coboundary[e_offset:e_offset + d]
        energy = float(np.dot(edge_vec, edge_vec))
        edge_energies.append(energy)

    # Spectral gap of sheaf Laplacian L = delta^T @ delta
    laplacian = delta.T @ delta
    eigvals = np.linalg.eigvalsh(laplacian)
    if len(eigvals) >= 2 and eigvals[-1] > 1e-12:
        lambda_2 = eigvals[1]
        lambda_n = eigvals[-1]
        spectral_gap = float((lambda_n - lambda_2) / lambda_n)
    else:
        spectral_gap = 0.0

    return {
        "h0_dim": h0_dim,
        "h1_dim": h1_dim,
        "rank": rank,
        "total_energy": total_energy,
        "edge_energies": edge_energies,
        "spectral_gap": spectral_gap,
    }


# ------------------------------------------------------------------
# Step 4: Compare to receipt
# ------------------------------------------------------------------

def verify_receipt(
    graph_path: str,
    receipt_path: str,
    stalk_dim: int = 8,
    seed: int = 42,
) -> Dict[str, Any]:
    """
    Independently verify a SIGMA proof receipt.

    Loads the graph, recomputes sheaf cohomology from scratch using
    only numpy/scipy, and compares the result to the receipt.

    Returns a dict with:
        match: bool (True if independent computation agrees)
        details: dict of per-field comparisons
        independent: dict of independently computed values
        receipt: dict of receipt values
    """
    # Load graph
    graph = load_graph(graph_path)

    # Load receipt
    with open(receipt_path, "r", encoding="utf-8") as f:
        receipt = json.load(f)

    # Get parameters from receipt (or use defaults)
    r_stalk_dim = receipt.get("stalk_dim", stalk_dim)
    r_seed = receipt.get("seed", seed)

    # Build sheaf from scratch
    sheaf = build_sheaf(graph, stalk_dim=r_stalk_dim, seed=r_seed)

    # Compute cohomology from scratch
    result = compute_cohomology(sheaf)

    # Compare
    r_h1 = receipt.get("h1_dimension", receipt.get("h1_dim", None))
    r_contradictions = receipt.get("contradiction_count", None)
    r_energy = receipt.get("total_energy", None)
    r_gap = receipt.get("spectral_gap", None)

    comparisons = {}

    if r_h1 is not None:
        comparisons["h1_dimension"] = {
            "receipt": r_h1,
            "independent": result["h1_dim"],
            "match": r_h1 == result["h1_dim"],
        }

    if r_contradictions is not None:
        # Contradictions should be non-zero iff h1 > 0 and energy > 0
        independent_has = result["h1_dim"] > 0 and result["total_energy"] > 1e-8
        receipt_has = r_contradictions > 0
        comparisons["has_contradictions"] = {
            "receipt": receipt_has,
            "independent": independent_has,
            "match": receipt_has == independent_has,
        }

    if r_energy is not None:
        energy_close = abs(r_energy - result["total_energy"]) < 0.01
        comparisons["total_energy"] = {
            "receipt": round(r_energy, 6),
            "independent": round(result["total_energy"], 6),
            "match": energy_close,
        }

    if r_gap is not None:
        gap_close = abs(r_gap - result["spectral_gap"]) < 0.01
        comparisons["spectral_gap"] = {
            "receipt": round(r_gap, 4),
            "independent": round(result["spectral_gap"], 4),
            "match": gap_close,
        }

    all_match = all(c["match"] for c in comparisons.values())

    return {
        "match": all_match,
        "comparisons": comparisons,
        "independent": {
            "h0_dim": result["h0_dim"],
            "h1_dim": result["h1_dim"],
            "rank": result["rank"],
            "total_energy": round(result["total_energy"], 6),
            "spectral_gap": round(result["spectral_gap"], 4),
            "graph_vertices": sheaf["n_vertices"],
            "graph_edges": sheaf["n_edges"],
        },
    }


# ------------------------------------------------------------------
# Step 5: CLI
# ------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="sigma-verify",
        description=(
            "Independent verification of SIGMA proof receipts. "
            "Recomputes sheaf cohomology from scratch using only "
            "numpy and scipy. No SIGMA engine required. No trust required."
        ),
    )
    parser.add_argument(
        "--graph", "-g",
        required=True,
        help="Path to the graph file (JSON)",
    )
    parser.add_argument(
        "--receipt", "-r",
        required=False,
        default=None,
        help="Path to the SIGMA proof receipt (JSON). "
             "If omitted, computes cohomology independently and prints it.",
    )
    parser.add_argument(
        "--stalk-dim", "-d",
        type=int,
        default=8,
        help="Stalk dimension (default: 8)",
    )
    parser.add_argument(
        "--seed", "-s",
        type=int,
        default=42,
        help="Random seed (default: 42)",
    )
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        default=False,
        help="Output as JSON",
    )

    args = parser.parse_args()

    if args.receipt:
        # Verify a receipt
        result = verify_receipt(
            args.graph, args.receipt,
            stalk_dim=args.stalk_dim, seed=args.seed,
        )

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print()
            print("SIGMA Independent Verifier")
            print("=" * 40)
            print("Graph: %s" % args.graph)
            print("Receipt: %s" % args.receipt)
            print()

            for field, comp in result["comparisons"].items():
                status = "OK" if comp["match"] else "MISMATCH"
                print(
                    "  [%s] %s: receipt=%s, independent=%s"
                    % (status, field, comp["receipt"], comp["independent"])
                )

            print()
            if result["match"]:
                print("VERIFIED: Independent computation matches the receipt.")
            else:
                print("MISMATCH: Independent computation disagrees with the receipt.")
            print()

        return 0 if result["match"] else 1

    else:
        # Just compute and print
        graph = load_graph(args.graph)
        sheaf = build_sheaf(graph, stalk_dim=args.stalk_dim, seed=args.seed)
        result = compute_cohomology(sheaf)

        if args.json:
            output = {
                "graph_vertices": sheaf["n_vertices"],
                "graph_edges": sheaf["n_edges"],
                "stalk_dim": sheaf["stalk_dim"],
                "h0_dim": result["h0_dim"],
                "h1_dim": result["h1_dim"],
                "rank": result["rank"],
                "total_energy": round(result["total_energy"], 6),
                "spectral_gap": round(result["spectral_gap"], 4),
                "has_contradictions": result["h1_dim"] > 0 and result["total_energy"] > 1e-8,
            }
            print(json.dumps(output, indent=2))
        else:
            print()
            print("SIGMA Independent Verifier")
            print("=" * 40)
            print("Graph: %s" % args.graph)
            print("Vertices: %d" % sheaf["n_vertices"])
            print("Edges: %d" % sheaf["n_edges"])
            print("Stalk dim: %d" % sheaf["stalk_dim"])
            print()
            print("H^0 dimension: %d (consistent states)" % result["h0_dim"])
            print("H^1 dimension: %d (structural obstructions)" % result["h1_dim"])
            print("Coboundary rank: %d" % result["rank"])
            print("Total Dirichlet energy: %.6f" % result["total_energy"])
            print("Spectral gap: %.4f" % result["spectral_gap"])
            print()

            if result["h1_dim"] > 0 and result["total_energy"] > 1e-8:
                print("Verdict: INCONSISTENT")
                print("This graph contains structural contradictions.")
                # Show top energy edges
                energies = result["edge_energies"]
                total_e = sum(energies)
                if total_e > 0:
                    ranked = sorted(
                        enumerate(energies), key=lambda x: -x[1]
                    )
                    print()
                    print("Top obstruction edges:")
                    for e_idx, energy in ranked[:5]:
                        if energy < 1e-8:
                            break
                        u_idx, v_idx = sheaf["edge_pairs"][e_idx]
                        u_label = sheaf["v_ids"][u_idx]
                        v_label = sheaf["v_ids"][v_idx]
                        frac = energy / total_e
                        print(
                            "  Edge %d: %s <-> %s  energy=%.4f (%.1f%%)"
                            % (e_idx, u_label, v_label, energy, frac * 100)
                        )
            else:
                print("Verdict: CONSISTENT")
                print("No structural contradictions detected.")

            print()

        has_contradictions = result["h1_dim"] > 0 and result["total_energy"] > 1e-8
        return 1 if has_contradictions else 0


if __name__ == "__main__":
    sys.exit(main())
