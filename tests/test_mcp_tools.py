# tests/test_mcp_tools.py
# Test the MCP server tool handlers directly.
#
# These tests call the same logic the MCP server uses, without
# needing an MCP client connection. This verifies that the tool
# handlers produce correct verdicts.
#
# All tests use EXPLICIT constraints. Unconstrained relations
# produce zero contradictions by design.

import json
import pytest

from sigma_guard import SigmaGuard
from sigma_guard.engine import RelationConstraint


class TestVerifyGraph:
    """Test the verify_graph tool logic."""

    def test_consistent_graph(self):
        guard = SigmaGuard(constraints={})
        guard.load_dict({
            "vertices": [
                {"id": "A", "label": "A", "claims": {"status": "active"}},
                {"id": "B", "label": "B", "claims": {"status": "active"}},
            ],
            "edges": [
                {"source": "A", "target": "B", "relation": "same_team"},
            ],
        })
        verdict = guard.verify()
        assert not verdict.has_contradictions

    def test_inconsistent_graph_with_agree_on(self):
        """Disagreement on constrained property is detected."""
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

    def test_unconstrained_relation_no_contradiction(self):
        """Different property values on unconstrained relation is NOT a contradiction."""
        guard = SigmaGuard(constraints={})
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
        assert not verdict.has_contradictions

    def test_verdict_json_output(self):
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
        result = verdict.to_dict()
        assert "verdict" in result
        assert "proof_id" in result
        assert "elapsed_ms" in result


class TestVerifyClaims:
    """Test the verify_claims tool logic (claim-to-graph conversion)."""

    def test_single_subject_no_contradiction(self):
        """A single subject with multiple properties is not a graph contradiction."""
        claims = [
            {"subject": "Component_X", "property": "ships", "value": "Q2"},
            {"subject": "Component_X", "property": "production_start", "value": "Q3"},
        ]

        # Build graph from claims
        subjects = {}
        for claim in claims:
            subj = claim["subject"]
            prop = claim["property"]
            val = claim["value"]
            if subj not in subjects:
                subjects[subj] = {"id": subj, "label": subj, "claims": {}}
            subjects[subj]["claims"][prop] = val

        vertices = list(subjects.values())

        # Single subject = no edges
        guard = SigmaGuard(constraints={})
        guard.load_dict({"vertices": vertices, "edges": []})
        verdict = guard.verify()
        assert not verdict.has_contradictions

    def test_two_subjects_agree_on_conflict(self):
        """Two subjects with disagreeing constrained properties are detected."""
        guard = SigmaGuard(constraints={
            "shared_claims": RelationConstraint(agree_on={"status"}),
        })
        guard.load_dict({
            "vertices": [
                {"id": "Source_A", "label": "Source_A", "claims": {"status": "approved"}},
                {"id": "Source_B", "label": "Source_B", "claims": {"status": "rejected"}},
            ],
            "edges": [
                {"source": "Source_A", "target": "Source_B", "relation": "shared_claims"},
            ],
        })
        verdict = guard.verify()
        assert verdict.has_contradictions


class TestCheckWrite:
    """Test the check_write tool logic."""

    def test_safe_write(self):
        guard = SigmaGuard(constraints={})
        guard.load_dict({
            "vertices": [
                {"id": "A", "label": "A", "claims": {"status": "active"}},
                {"id": "B", "label": "B", "claims": {"status": "active"}},
            ],
            "edges": [
                {"source": "A", "target": "B", "relation": "linked"},
            ],
        })
        result = guard.check_write("A", "B", "related_to")
        assert not result.creates_contradiction

    def test_contradictory_write_agree_on(self):
        """check_write detects property disagreement on constrained edges."""
        guard = SigmaGuard(constraints={
            "policy_check": RelationConstraint(agree_on={"approved"}),
        })
        guard.load_dict({
            "vertices": [
                {"id": "X", "label": "X", "claims": {"approved": "yes"}},
                {"id": "Y", "label": "Y", "claims": {"approved": "no"}},
            ],
            "edges": [],
        })
        result = guard.check_write("X", "Y", "policy_check")
        assert result.creates_contradiction

    def test_contradictory_write_cycle(self):
        """check_write detects cycles in acyclic relations."""
        guard = SigmaGuard(constraints={
            "DEPENDS_ON": {"acyclic": True},
        })
        guard.load_dict({
            "vertices": [
                {"id": "A", "label": "A"},
                {"id": "B", "label": "B"},
                {"id": "C", "label": "C"},
            ],
            "edges": [
                {"source": "A", "target": "B", "relation": "DEPENDS_ON"},
                {"source": "B", "target": "C", "relation": "DEPENDS_ON"},
            ],
        })
        result = guard.check_write("C", "A", "DEPENDS_ON")
        assert result.creates_contradiction
        assert result.severity == "CRITICAL"
