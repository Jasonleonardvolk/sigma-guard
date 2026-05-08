# sigma_guard/verdict.py
# Data structures for SIGMA verification verdicts.
#
# Verdict: full graph verification result
# Contradiction: a single detected structural contradiction
# WriteCheckResult: result of checking a single proposed write
#
# May 2026 | Invariant Research | Patent Pending

import json
import time
import hashlib
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple


@dataclass
class Contradiction:
    """A single structural contradiction detected by SIGMA."""

    severity: str               # CRITICAL | HIGH | MODERATE | LOW
    location: Tuple[str, str]   # (vertex_label_a, vertex_label_b)
    edge_index: int             # index in the graph's edge list
    energy: float               # Dirichlet energy at this edge
    energy_fraction: float      # fraction of total obstruction energy
    explanation: str            # human-readable explanation
    proof_id: str               # cryptographic proof reference

    def to_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity,
            "location": list(self.location),
            "edge_index": self.edge_index,
            "energy": round(self.energy, 6),
            "energy_fraction": round(self.energy_fraction, 4),
            "explanation": self.explanation,
            "proof_id": self.proof_id,
        }

    def __str__(self) -> str:
        return (
            "[%s] %s <-> %s (energy=%.4f, %.1f%%)"
            % (
                self.severity,
                self.location[0],
                self.location[1],
                self.energy,
                self.energy_fraction * 100,
            )
        )


@dataclass
class Verdict:
    """Full graph verification result."""

    has_contradictions: bool
    contradiction_count: int
    contradictions: List[Contradiction]
    h1_dimension: int           # dimension of obstruction space
    spectral_gap: float         # graph health metric (0 to 1)
    total_energy: float         # total Dirichlet energy
    elapsed_ms: float           # verification time in milliseconds
    proof_id: str               # root proof ID for the full verdict
    certificate: Dict[str, Any] # full signed certificate
    graph_stats: Dict[str, Any] # vertex count, edge count, etc.

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": "INCONSISTENT" if self.has_contradictions else "CONSISTENT",
            "contradiction_count": self.contradiction_count,
            "contradictions": [c.to_dict() for c in self.contradictions],
            "h1_dimension": self.h1_dimension,
            "spectral_gap": round(self.spectral_gap, 4),
            "total_energy": round(self.total_energy, 6),
            "elapsed_ms": round(self.elapsed_ms, 3),
            "proof_id": self.proof_id,
            "certificate": self.certificate,
            "graph_stats": self.graph_stats,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def summary(self) -> str:
        lines = [
            "SIGMA Graph Guard v0.1.0",
            "=" * 40,
            "Graph: %d vertices, %d edges"
            % (
                self.graph_stats.get("vertices", 0),
                self.graph_stats.get("edges", 0),
            ),
            "H^1 dimension: %d" % self.h1_dimension,
            "Spectral gap: %.4f" % self.spectral_gap,
            "Total energy: %.6f" % self.total_energy,
            "",
        ]

        if not self.has_contradictions:
            lines.append("Verdict: CONSISTENT")
            lines.append("No structural contradictions detected.")
        else:
            lines.append("Contradictions found: %d" % self.contradiction_count)
            lines.append("")
            for i, c in enumerate(self.contradictions):
                lines.append(
                    "[%s] Contradiction #%d" % (c.severity, i + 1)
                )
                lines.append(
                    '  Location: "%s" <-> "%s"'
                    % (c.location[0], c.location[1])
                )
                lines.append("  Energy: %.4f" % c.energy)
                if c.explanation:
                    lines.append("  %s" % c.explanation)
                lines.append("  Certificate: %s" % c.proof_id)
                lines.append("")
            lines.append("Verdict: INCONSISTENT")

        lines.append("Proof ID: %s" % self.proof_id)
        lines.append("Elapsed: %.2fms" % self.elapsed_ms)
        return "\n".join(lines)


@dataclass
class WriteCheckResult:
    """Result of checking a single proposed write operation."""

    creates_contradiction: bool
    severity: Optional[str] = None          # CRITICAL | HIGH | etc.
    conflicting_nodes: List[str] = field(default_factory=list)
    energy_delta: float = 0.0               # energy increase from this write
    explanation: str = ""
    proof_id: str = ""
    elapsed_us: float = 0.0                 # microseconds

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "creates_contradiction": self.creates_contradiction,
            "elapsed_us": round(self.elapsed_us, 1),
        }
        if self.creates_contradiction:
            result["severity"] = self.severity
            result["conflicting_nodes"] = self.conflicting_nodes
            result["energy_delta"] = round(self.energy_delta, 6)
            result["explanation"] = self.explanation
            result["proof_id"] = self.proof_id
        return result


def generate_proof_id(data: bytes) -> str:
    """Generate a deterministic proof ID from input data."""
    h = hashlib.sha256(data).hexdigest()
    return "sigma:proof:%s-%s-%s-%s-%s" % (
        h[:8], h[8:12], h[12:16], h[16:20], h[20:32]
    )
