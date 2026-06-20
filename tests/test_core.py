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
# Engine (standalone verifier path)
# ------------------------------------------------------------------

class TestEngine:
    def test_import(self):
        """Test that SigmaGuard can be imported."""
        from sigma_guard import SigmaGuard
        guard = SigmaGuard(stalk_dim=4, seed=42)
        assert guard.stalk_dim == 4

    def test_load_dict(self):
        """Test loading a graph from dict and verifying."""
        from sigma_guard import SigmaGuard
        guard = SigmaGuard(stalk_dim=4, seed=42)
        guard.load_dict({
            "vertices": [
                {"id": "a", "label": "A", "claims": {"x": "yes"}},
                {"id": "b", "label": "B", "claims": {"x": "no"}},
            ],
            "edges": [
                {"source": "a", "target": "b", "relation": "linked"},
            ],
        })
        verdict = guard.verify()
        assert isinstance(verdict.h1_dimension, int)
        assert isinstance(verdict.elapsed_ms, float)

    def test_no_constraints_no_contradictions(self):
        """Unconstrained relations produce zero contradictions."""
        from sigma_guard import SigmaGuard
        guard = SigmaGuard(constraints={})
        guard.load_dict({
            "vertices": [
                {"id": "A", "label": "A", "claims": {"x": "1"}},
                {"id": "B", "label": "B", "claims": {"x": "2"}},
            ],
            "edges": [
                {"source": "A", "target": "B", "relation": "linked"},
            ],
        })
        verdict = guard.verify()
        assert not verdict.has_contradictions

    def test_acyclic_cycle_detected(self):
        """Cycles in acyclic relations are detected."""
        from sigma_guard import SigmaGuard
        guard = SigmaGuard(constraints={
            "SUPPLIES": {"acyclic": True},
        })
        guard.load_dict({
            "vertices": [
                {"id": "A", "label": "A"},
                {"id": "B", "label": "B"},
                {"id": "C", "label": "C"},
            ],
            "edges": [
                {"source": "A", "target": "B", "relation": "SUPPLIES"},
                {"source": "B", "target": "C", "relation": "SUPPLIES"},
                {"source": "C", "target": "A", "relation": "SUPPLIES"},
            ],
        })
        verdict = guard.verify()
        assert verdict.has_contradictions
        assert verdict.contradiction_count >= 1
        assert any(c.severity == "CRITICAL" for c in verdict.contradictions)

    def test_symmetric_violation_detected(self):
        """Missing reciprocal edges in symmetric relations are detected."""
        from sigma_guard import SigmaGuard
        guard = SigmaGuard(constraints={
            "BORDERS": {"symmetric": True},
        })
        guard.load_dict({
            "vertices": [
                {"id": "X", "label": "X"},
                {"id": "Y", "label": "Y"},
            ],
            "edges": [
                {"source": "X", "target": "Y", "relation": "BORDERS"},
                # Missing Y -> X
            ],
        })
        verdict = guard.verify()
        assert verdict.has_contradictions
        assert any("Symmetry" in c.explanation for c in verdict.contradictions)

    def test_functional_violation_detected(self):
        """Multiple targets for functional relations are detected."""
        from sigma_guard import SigmaGuard
        guard = SigmaGuard(constraints={
            "HAS_CAPITAL": {"functional": True},
        })
        guard.load_dict({
            "vertices": [
                {"id": "SA", "label": "South_Africa"},
                {"id": "P", "label": "Pretoria"},
                {"id": "CT", "label": "Cape_Town"},
            ],
            "edges": [
                {"source": "SA", "target": "P", "relation": "HAS_CAPITAL"},
                {"source": "SA", "target": "CT", "relation": "HAS_CAPITAL"},
            ],
        })
        verdict = guard.verify()
        assert verdict.has_contradictions
        assert any("Functional" in c.explanation or "unique" in c.explanation
                    for c in verdict.contradictions)

    def test_agree_on_violation_detected(self):
        """Property disagreements on agree_on edges are detected."""
        from sigma_guard import SigmaGuard
        from sigma_guard.engine import RelationConstraint
        guard = SigmaGuard(constraints={
            "governs": RelationConstraint(agree_on={"vendor"}),
        })
        guard.load_dict({
            "vertices": [
                {"id": "Policy", "label": "Policy", "claims": {"vendor": "A"}},
                {"id": "Procurement", "label": "Procurement", "claims": {"vendor": "B"}},
            ],
            "edges": [
                {"source": "Policy", "target": "Procurement", "relation": "governs"},
            ],
        })
        verdict = guard.verify()
        assert verdict.has_contradictions
        assert verdict.contradiction_count >= 1


# ------------------------------------------------------------------
# check_write parity tests
#
# These verify that check_write() uses the SAME validators
# as verify(). If verify() catches a cycle/symmetry/cardinality
# violation, check_write() must catch the same write.
# ------------------------------------------------------------------

class TestCheckWriteParity:
    def test_check_write_acyclic_blocked(self):
        """check_write blocks a write that would create a cycle."""
        from sigma_guard import SigmaGuard
        guard = SigmaGuard(constraints={
            "SUPPLIES": {"acyclic": True},
        })
        guard.load_dict({
            "vertices": [
                {"id": "A", "label": "A"},
                {"id": "B", "label": "B"},
                {"id": "C", "label": "C"},
            ],
            "edges": [
                {"source": "A", "target": "B", "relation": "SUPPLIES"},
                {"source": "B", "target": "C", "relation": "SUPPLIES"},
            ],
        })
        # This write would close A->B->C->A
        result = guard.check_write("C", "A", "SUPPLIES")
        assert result.creates_contradiction
        assert result.severity == "CRITICAL"

    def test_check_write_functional_blocked(self):
        """check_write blocks a write that would violate functional."""
        from sigma_guard import SigmaGuard
        guard = SigmaGuard(constraints={
            "HAS_CAPITAL": {"functional": True},
        })
        guard.load_dict({
            "vertices": [
                {"id": "France", "label": "France"},
                {"id": "Paris", "label": "Paris"},
                {"id": "Lyon", "label": "Lyon"},
            ],
            "edges": [
                {"source": "France", "target": "Paris", "relation": "HAS_CAPITAL"},
            ],
        })
        # France already has Paris as capital; adding Lyon violates functional
        result = guard.check_write("France", "Lyon", "HAS_CAPITAL")
        assert result.creates_contradiction

    def test_check_write_symmetric_blocked(self):
        """check_write detects that a symmetric write is one-directional."""
        from sigma_guard import SigmaGuard
        guard = SigmaGuard(constraints={
            "BORDERS": {"symmetric": True},
        })
        guard.load_dict({
            "vertices": [
                {"id": "A", "label": "A"},
                {"id": "B", "label": "B"},
            ],
            "edges": [],
        })
        # Adding A BORDERS B without B BORDERS A is a symmetry violation
        result = guard.check_write("A", "B", "BORDERS")
        assert result.creates_contradiction

    def test_check_write_safe(self):
        """check_write allows a safe write."""
        from sigma_guard import SigmaGuard
        guard = SigmaGuard(constraints={
            "SUPPLIES": {"acyclic": True},
        })
        guard.load_dict({
            "vertices": [
                {"id": "A", "label": "A"},
                {"id": "B", "label": "B"},
            ],
            "edges": [],
        })
        # A->B alone is not a cycle
        result = guard.check_write("A", "B", "SUPPLIES")
        assert not result.creates_contradiction


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
