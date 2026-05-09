# LLM Agent Integration

SIGMA Guard is not just for graph databases. Any system that produces
structured claims can be verified before those claims are trusted.

## The architecture

```
LLM generates answer
        |
        v
Claims / citations / entities extracted
        |
        v
SIGMA Guard builds verification graph
        |
        v
Sheaf cohomology checks structural consistency
        |
        v
Verdict: SAFE / UNSAFE / CONTRADICTORY
        |
        v
Output allowed, blocked, warned, or signed with receipt
```

SIGMA does not replace the LLM. It does not compete with the generator.
It is the gate after generation and before trust.

## Model-agnostic

The verification layer sits behind any model:

- OpenAI (GPT-4, GPT-4o, o1, o3)
- Anthropic (Claude)
- Google (Gemini)
- Meta (Llama)
- Mistral
- Nous/Hermes
- Any local or fine-tuned model

The model does not matter. SIGMA verifies the output, not the model.

## Integration shape

The simplest integration is three steps:

1. LLM produces an answer containing claims
2. Claims are extracted into a graph (vertices = entities, edges = relationships)
3. SIGMA Guard checks whether the claims are structurally consistent

```python
from sigma_guard import SigmaGuard

guard = SigmaGuard()

# Step 1: LLM produced this answer (your existing pipeline)
llm_output = {
    "answer": "Component X ships Q2. Production starts Q3.",
    "claims": [
        {"entity": "Component_X", "property": "ships", "value": "Q2"},
        {"entity": "Component_X", "property": "production_start", "value": "Q3"},
    ]
}

# Step 2: Map claims into a verification graph
guard.load_dict({
    "vertices": [
        {
            "id": "claim_1",
            "label": "Component_X (shipping)",
            "claims": {"timeline": "Q2", "status": "ready_to_ship"}
        },
        {
            "id": "claim_2",
            "label": "Component_X (production)",
            "claims": {"timeline": "Q3", "status": "not_yet_produced"}
        },
    ],
    "edges": [
        {
            "source": "claim_1",
            "target": "claim_2",
            "relation": "same_component_timeline"
        }
    ]
})

# Step 3: Verify
verdict = guard.verify()

if verdict.has_contradictions:
    print("UNSAFE: LLM output contains structural contradictions")
    for c in verdict.contradictions:
        print("  %s: %s" % (c.severity, c.explanation))
    print("  Proof: %s" % verdict.proof_id)
else:
    print("SAFE: claims are structurally consistent")
    print("  Receipt: %s" % verdict.proof_id)
```

## Use cases by domain

### Legal citations

An LLM generates a legal brief citing three cases. SIGMA checks whether
the cited holdings are structurally compatible with the argument. If
Case A limits the scope that Case B establishes, and the brief uses both
as if they agree, SIGMA flags the contradiction.

### SOC 2 / compliance evidence

An LLM generates a compliance narrative. SIGMA extracts the controls
referenced and checks whether the stated controls are structurally
consistent with each other and with the policy graph.

### GraphRAG memory

An agent retrieves memories from a knowledge graph. Before using them
in an answer, SIGMA checks whether the retrieved facts contradict each
other. "Customer prefers annual billing" and "customer rejected annual
billing" are both valid memories. Together, they conflict.

### Security questionnaires

An LLM fills out a vendor security questionnaire. SIGMA checks whether
the answers are internally consistent. "We encrypt all data at rest"
and "backup storage uses unencrypted S3 buckets" cannot both be true.

## For agent frameworks

**Recommended: use the MCP server.** See [docs/mcp_server.md](mcp_server.md).

```
pip install sigma-guard[mcp]
sigma-guard-mcp
```

Three tools: `verify_graph`, `verify_claims`, `check_write`.
Works with Hermes Agent, Claude Desktop, and any MCP-compatible agent.
No code changes to the agent required.

If your agent framework does not support MCP, the integration is
still a single function call:

```python
verdict = guard.verify()
if verdict.has_contradictions:
    # revise, cite sources, block output, or label uncertainty
    ...
```

## Verification receipt

Every verification produces a signed receipt:

```json
{
    "verdict": "INCONSISTENT",
    "safe_to_rely_on": false,
    "claims_checked": 2,
    "contradictions": 1,
    "receipt_id": "sigma:proof:a1dc661d...",
    "algorithm": "sheaf_cohomology_h1",
    "deterministic": true
}
```

This receipt is independently verifiable. The standalone verifier
(pure numpy/scipy, Apache 2.0) can reproduce the result from the
same input graph.

## The positioning

Every AI system needs a generation layer.
Every serious AI system needs a verification layer.

SIGMA is the verification layer.

It does not make LLMs smarter. It makes LLM output safe to rely on.

## Try it

```
git clone https://github.com/Jasonleonardvolk/sigma-guard
cd sigma-guard
pip install -e .
python examples/tiny_contradiction.py
```

No Docker. No GPU. No API key. No private engine required.

For questions about LLM agent integration:
jason@invariant.pro
https://invariant.pro
