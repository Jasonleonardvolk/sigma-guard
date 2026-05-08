# tests/test_core.py
# Basic tests for SIGMA Graph Guard.
#
# Run: pytest tests/

import os
import sys
import json
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sigma_guard.verdict import (
    Verdict, Contradiction, WriteCheckResult, generate_proof_id,
)
from sigma_guard.parsers.json_graph import parse_json_graph
from sigma_guard.parsers.edge_list import parse_edge_list


# ------------------------------------------------------------------
# Verdict data structures
# ------------------------------------------------------------------

class TestContradiction:
    def test_to_dict(self):
        c = Contradiction(
            severity="HIGH",
            location=("Node_A", "Node_B"),
            edge_index=0,
            energy=0.85,
            energy_fraction=0.42,
            explanation="Test contradiction",
            proof_id="sigma:proof:test",
        )
        d = c.to_dict()
        assert d["severity"] == "HIGH"
        assert d["location"] == ["Node_A", "Node_B"]
        assert d["energy"] == 0.85

    def test_str(self):
        c = Contradiction(
            severity="CRITICAL",
            location=("A", "B"),
            edge_index=0,
            energy=0.9,
            energy_fraction=0.5,
            explanation="",
            proof_id="",
        )
        s = str(c)
        assert "CRITICAL" in s
        assert "A" in s
        assert "B" in s


class TestWriteCheckResult:
    def test_safe_write(self):
        r = WriteCheckResult(creates_contradiction=False, elapsed_us=42.0)
        d = r.to_dict()
        assert d["creates_contradiction"] is False
        assert "severity" not in d

    def test_blocked_write(self):
        r = WriteCheckResult(
            creates_contradiction=True,
            severity="HIGH",
            conflicting_nodes=["X", "Y"],
            energy_delta=0.5,
            explanation="conflict",
            proof_id="sigma:proof:abc",
            elapsed_us=63.0,
        )
        d = r.to_dict()
        assert d["creates_contradiction"] is True
        assert d["severity"] == "HIGH"
        assert d["conflicting_nodes"] == ["X", "Y"]


class TestProofId:
    def test_deterministic(self):
        data = b"test data"
        id1 = generate_proof_id(data)
        id2 = generate_proof_id(data)
        assert id1 == id2
        assert id1.startswith("sigma:proof:")

    def test_different_data(self):
        id1 = generate_proof_id(b"data1")
        id2 = generate_proof_id(b"data2")
        assert id1 != id2


# ------------------------------------------------------------------
# Parsers
# ------------------------------------------------------------------

class TestJsonParser:
    def test_parse_supply_chain(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "datasets", "supply_chain.json",
        )
        if not os.path.exists(path):
            pytest.skip("Dataset not found")

        data = parse_json_graph(path)
        assert "vertices" in data
        assert "edges" in data
        assert len(data["vertices"]) == 12
        assert len(data["edges"]) == 18

    def test_parse_cybersecurity(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "datasets", "cybersecurity.json",
        )
        if not os.path.exists(path):
            pytest.skip("Dataset not found")

        data = parse_json_graph(path)
        assert len(data["vertices"]) == 12
        assert len(data["edges"]) == 15

    def test_parse_knowledge_graph(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "datasets", "knowledge_graph.json",
        )
        if not os.path.exists(path):
            pytest.skip("Dataset not found")

        data = parse_json_graph(path)
        assert len(data["vertices"]) == 10
        assert len(data["edges"]) == 12


# ------------------------------------------------------------------
# Engine (requires SIGMA core)
# ------------------------------------------------------------------

class TestEngine:
    def test_import(self):
        """Test that SigmaGuard can be imported."""
        from sigma_guard import SigmaGuard
        guard = SigmaGuard(stalk_dim=4, seed=42)
        assert guard.stalk_dim == 4

    def test_load_dict(self):
        """Test loading a graph from dict (requires SIGMA core)."""
        try:
            from sigma_guard import SigmaGuard
            guard = SigmaGuard(stalk_dim=4, seed=42)
            guard.load_dict({
                "vertices": [
                    {"id": "a", "label": "A", "claims": {"x": True}},
                    {"id": "b", "label": "B", "claims": {"x": False}},
                ],
                "edges": [
                    {"source": "a", "target": "b", "relation": "contradicts"},
                ],
            })
            verdict = guard.verify()
            assert isinstance(verdict.h1_dimension, int)
            assert isinstance(verdict.elapsed_ms, float)
        except ImportError:
            pytest.skip("SIGMA core not installed")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
