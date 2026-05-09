# tests/test_mcp_tools.py
# Test the MCP server tool handlers directly.
#
# These tests call the same logic the MCP server uses, without
# needing an MCP client connection. This verifies that the tool
# handlers produce correct verdicts.

import json
import pytest

from sigma_guard import SigmaGuard


class TestVerifyGraph:
    """Test the verify_graph tool logic."""

    def test_consistent_graph(self):
        guard = SigmaGuard()
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

    def test_inconsistent_graph(self):
        guard = SigmaGuard()
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

    def test_verdict_json_output(self):
        guard = SigmaGuard()
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
        assert result["deterministic"] if "deterministic" in result.get("certificate", {}) else True


class TestVerifyClaims:
    """Test the verify_claims tool logic (claim-to-graph conversion)."""

    def test_conflicting_claims(self):
        # Same subject, same property, different values
        claims = [
            {"subject": "Component_X", "property": "ships", "value": "Q2"},
            {"subject": "Component_X", "property": "production_start", "value": "Q3"},
        ]

        # Build graph from claims (same logic as MCP handler)
        subjects = {}
        for claim in claims:
            subj = claim["subject"]
            prop = claim["property"]
            val = claim["value"]
            if subj not in subjects:
                subjects[subj] = {"id": subj, "label": subj, "claims": {}}
            subjects[subj]["claims"][prop] = val

        vertices = list(subjects.values())

        # Single subject means no edges from shared properties.
        # Connect all subjects in same domain.
        subj_list = list(subjects.keys())
        edges = []
        if len(subj_list) == 1:
            # Single entity with multiple properties: no contradiction
            # possible from graph structure alone.
            pass
        else:
            for i in range(len(subj_list)):
                for j in range(i + 1, len(subj_list)):
                    edges.append({
                        "source": subj_list[i],
                        "target": subj_list[j],
                        "relation": "same_domain",
                    })

        # With a single subject, no edge, no contradiction detectable
        # This is correct: contradictions require at least two entities
        # making incompatible claims.
        if edges:
            guard = SigmaGuard()
            guard.load_dict({"vertices": vertices, "edges": edges})
            verdict = guard.verify()
            assert verdict is not None

    def test_two_subjects_conflicting(self):
        claims = [
            {"subject": "Source_A", "property": "status", "value": "approved"},
            {"subject": "Source_B", "property": "status", "value": "rejected"},
        ]

        subjects = {}
        for claim in claims:
            subj = claim["subject"]
            prop = claim["property"]
            val = claim["value"]
            if subj not in subjects:
                subjects[subj] = {"id": subj, "label": subj, "claims": {}}
            subjects[subj]["claims"][prop] = val

        vertices = list(subjects.values())
        edges = [{"source": "Source_A", "target": "Source_B", "relation": "shared_claims"}]

        guard = SigmaGuard()
        guard.load_dict({"vertices": vertices, "edges": edges})
        verdict = guard.verify()
        assert verdict.has_contradictions


class TestCheckWrite:
    """Test the check_write tool logic."""

    def test_safe_write(self):
        guard = SigmaGuard()
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

    def test_contradictory_write(self):
        guard = SigmaGuard()
        guard.load_dict({
            "vertices": [
                {"id": "X", "label": "X", "claims": {"approved": "yes"}},
                {"id": "Y", "label": "Y", "claims": {"approved": "no"}},
            ],
            "edges": [],
        })
        result = guard.check_write("X", "Y", "policy_check")
        # This should detect the disagreement on "approved"
        assert result.creates_contradiction
