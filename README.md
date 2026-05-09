# SIGMA Guard

Pre-commit contradiction detection for graph databases.

> Note: This project is unrelated to SigmaHQ detection rules. SIGMA Guard is a graph consistency verification layer from [Invariant Research](https://invariant.pro).

Your graph can pass schema validation and still contradict itself.
SIGMA Guard catches that before the write commits.

SIGMA turns global contradiction detection from an audit into a
write-time primitive.

Runs locally with the included standalone verifier. No Docker, GPU,
API key, or private engine required for the demo path.

## Try it in 60 seconds

```
git clone https://github.com/Jasonleonardvolk/sigma-guard.git
cd sigma-guard
python -m venv .venv
.\.venv\Scripts\Activate.ps1       # Windows
# source .venv/bin/activate        # Mac/Linux
pip install -e .
python examples/tiny_contradiction.py
```

```
Tiny Contradiction Demo
========================================

Graph: 2 vertices, 1 edge
Policy says approved_vendor = Supplier_A
Procurement says approved_vendor = Supplier_B

Verdict: INCONSISTENT

  [CRITICAL] Policy <-> Procurement
  Structural contradiction: 'Policy' and 'Procurement' disagree
  on: approved_vendor. These claims are individually valid but
  structurally incompatible.
  Proof: sigma:proof:a1dc661d...

Elapsed: 0.59ms
```

Then run the full supply-chain demo:

```
python examples/basic_usage.py
```

Detects 7 structural contradictions, separates critical from
low-energy tension, allows a safe write, blocks a contradictory
write in under 1ms, emits proof IDs.

### With Docker

```
docker run jasonvolk/sigma-guard demo supply_chain
docker run jasonvolk/sigma-guard demo cybersecurity
docker run jasonvolk/sigma-guard demo knowledge_graph
```

## What am I looking at?

SIGMA Guard checks whether claims stored in a graph can all be
true together.

A normal schema validator can tell you whether a node has the
right fields. SIGMA Guard checks whether the graph tells one
consistent story.

Example:

- Policy says Component_X must use Supplier_A.
- Procurement says Component_X must use Supplier_B.
- Both claims are valid-looking facts.
- Together, they conflict.

SIGMA Guard detects that structural conflict and returns a verdict.

### Three-minute explanation

Imagine every node in a graph holds a small piece of a story.
Each edge says how two pieces of the story should agree. If all
local stories agree, the graph can be glued into one global story.
If they cannot, the graph has a structural contradiction.

SIGMA Guard detects that failure using sheaf cohomology:

1. Each node gets a **stalk** (a vector space representing its claims)
2. Each edge gets a **restriction map** (how adjacent claims relate)
3. The **coboundary operator** measures disagreement across all edges
4. **H^1 cohomology** identifies contradictions no local fix can resolve

The **Dirichlet energy** on each edge tells you exactly where the
contradiction lives. Every detected contradiction is a provable
mathematical obstruction, not a statistical guess.

## Example use cases

### GraphRAG memory

An agent memory graph says a customer wants annual billing. A later
memory says the same customer rejected annual billing. SIGMA Guard
can flag the contradiction before both memories are retrieved into
the same answer.

### Security graphs

An asset is marked decommissioned, but the traffic graph shows
active outbound connections. SIGMA Guard can flag inconsistent
asset state.

### Compliance graphs

A policy says all admin accounts require MFA. An exception register
says a privileged service account has no MFA. SIGMA Guard can flag
the control contradiction.

### Supply-chain graphs

A component is marked sole-sourced to Supplier_A and also approved
through Supplier_B. SIGMA Guard can flag the operational contradiction.

## Bring your own graph

Create `my_graph.json`:

```json
{
  "vertices": [
    {"id": "A", "claims": {"status": "active"}},
    {"id": "B", "claims": {"status": "inactive"}}
  ],
  "edges": [
    {"source": "A", "target": "B", "relation": "same_entity"}
  ]
}
```

Run:

```
python -m sigma_guard.standalone_verifier --graph my_graph.json
```

See [docs/graph_format.md](docs/graph_format.md) for the full format
reference.

## When not to use SIGMA Guard

SIGMA Guard is not the right tool for:

- Simple schema validation (use database constraints)
- Checking required fields (use SHACL or JSON Schema)
- Fuzzy semantic similarity (use embeddings)
- LLM answer grading (use an evaluation framework)
- Generic data cleaning (use a data quality tool)

Use SIGMA Guard when graph facts are individually valid but may be
globally inconsistent.

## Architecture

This repository contains the open integration layer:

- Standalone verifier (pure numpy/scipy, Apache 2.0)
- File parsers (JSON, GraphML, edge list)
- Graph database adapters (Memgraph, Neo4j, generic base class)
- Example datasets with planted contradictions and ground truth
- Proof receipt schemas
- CLI

### Engine modes

| Mode | Purpose | Availability |
|---|---|---|
| Standalone verifier | Pure numpy/scipy verification for demos, tests, and reproducible examples | Included in this repo |
| Full SIGMA engine | Optimized cellular incremental architecture for production-scale verification | Available via Docker or direct installation |

The public repo is runnable without the full engine. `pip install -e .`
then `python examples/tiny_contradiction.py` works on a clean machine
with only Python, numpy, and scipy.

When the full SIGMA engine is available on the Python path, SIGMA Guard
uses it automatically for faster performance on large graphs.

## Memgraph integration

SIGMA can be installed as a Memgraph before-commit verification hook.
In block mode, writes that create configured structural contradictions
are rejected before commit.

```python
from sigma_guard.adapters.memgraph import MemgraphGuard

mg = MemgraphGuard(host="localhost", port=7687)
mg.install_trigger()
```

See [examples/memgraph_trigger.py](examples/memgraph_trigger.py) for the
full working example with Docker Compose.

## Neo4j integration

The Neo4j adapter runs as a guarded write wrapper. Route writes through
`Neo4jGuard.execute()` so SIGMA can verify before commit.

```python
from sigma_guard.adapters.neo4j import Neo4jGuard

guard = Neo4jGuard(uri="bolt://localhost:7687", auth=("neo4j", "password"))
guard.execute("CREATE (:Supplier {name: $name, sole_source: true})", name="Supplier_A")
```

Native Neo4j transaction listeners require a JVM plugin, planned separately.
See [examples/neo4j_hook.py](examples/neo4j_hook.py).

## Independent verification

The standalone verifier recomputes sheaf cohomology from scratch
using only numpy and scipy. No SIGMA engine. No trust required.

```
python -m sigma_guard.standalone_verifier --graph datasets/supply_chain.json
```

Released under Apache 2.0 so anyone can audit it.
Source: [sigma_guard/standalone_verifier.py](sigma_guard/standalone_verifier.py)

## Performance

| Metric | Value |
|---|---|
| Latency per write (incremental, full engine) | 63 microseconds |
| Latency per query (full engine) | 13 microseconds |
| Scaling exponent | 0.19 (sub-linear) |
| Validated scale | 1,000,000 vertices |
| Speedup vs full recomputation | 10,504x |
| ML required | None |
| GPU required | None |

Benchmark context: Intel i9-13900H, 64 GB RAM, no GPU. Baseline is
global sheaf cohomology recomputation. SIGMA's cellular architecture
localizes recomputation to bounded cells: O(n) batch assembly and
O(1) amortized dirty-cell streaming under bounded-cell assumptions.
Details: [benchmarks/README.md](benchmarks/README.md)

## Proof receipt shape

```json
{
  "verdict": "INCONSISTENT",
  "proof_id": "sigma:proof:a3f8c2d1...",
  "algorithm": "sheaf_cohomology_h1",
  "deterministic": true,
  "contradictions": [
    {
      "severity": "CRITICAL",
      "location": ["Supplier_A", "Supplier_B"],
      "energy": 0.9412,
      "explanation": "disagree on: sole_source_component_x"
    }
  ]
}
```

## CLI exit codes

| Code | Meaning |
|---|---|
| 0 | Graph verified consistent |
| 1 | Contradiction detected |
| 2 | Input, parser, engine, or configuration error |

## CI usage

```yaml
# GitHub Actions
- name: Graph consistency check
  run: |
    docker run -v ${{ github.workspace }}:/data \
      jasonvolk/sigma-guard verify /data/graph_snapshot.json
```

## Datasets

- `datasets/supply_chain.json` - 12 vertices, 18 edges, 3 planted contradiction families
- `datasets/cybersecurity.json` - 12 vertices, 15 edges, 4 planted contradictions
- `datasets/knowledge_graph.json` - 10 vertices, 12 edges, 3 planted contradictions
- `examples/tiny_contradiction.json` - 2 vertices, 1 edge, 1 obvious contradiction

Each dataset includes `ground_truth` with descriptions of every planted contradiction.

## FAQ

### Is this an LLM?

No. SIGMA Guard does not ask a model whether the graph looks right.

### Is this schema validation?

No. Schema validation checks local shape. SIGMA Guard checks global consistency.

### What is sheaf cohomology doing here?

It models whether local claims attached to graph nodes can glue into
one consistent global assignment. If they cannot, SIGMA reports a
structural obstruction.

### Does this prove my real-world data is true?

No. It proves consistency under the configured graph model. Bad
modeling can still produce unhelpful results.

### Do I need the private SIGMA engine?

No for demos and local verification. The repo includes a standalone
verifier path. The full engine is for optimized production-scale
deployment.

### Does this work with Neo4j and Memgraph?

The repo includes adapter examples. Memgraph supports a before-commit
hook path. Neo4j currently uses a guarded write wrapper; a native JVM
plugin is planned separately.

## How SIGMA Guard differs

| Tool type | Checks | Limitation |
|---|---|---|
| Schema validation | Field shape, labels, types | Does not detect global contradiction |
| Database constraints | Local rule violations | Usually local or procedural |
| SHACL | RDF constraint validation | Rule-based, not cohomological |
| LLM judge | Plausibility of output | Probabilistic and prompt-sensitive |
| SIGMA Guard | Structural graph consistency | Depends on configured graph model |

## Known limitations

- The standalone verifier is designed for demos, tests, and small/medium graphs.
- Production-scale cellular incremental verification uses the full SIGMA engine.
- Neo4j native transaction listeners require a JVM plugin; the current adapter uses a guarded write wrapper.
- The quality of results depends on the quality of the configured claims and restrictions.
- Current examples use simple claim keys; richer domain models require richer sheaf construction.

## Roadmap

- [ ] Benchmark reproduction scripts
- [ ] Memgraph block/warn mode demo
- [ ] Native Neo4j JVM plugin
- [ ] NetworkX importer
- [ ] FalkorDB adapter
- [ ] GraphRAG memory contradiction demo
- [ ] Security graph demo
- [ ] Compliance graph demo
- [ ] `--explain` flag for plain-English output
- [ ] `--fail-on` flag for CI severity filtering

## Design principles

1. Verification is not generation.
2. A graph can be valid locally and inconsistent globally.
3. The verifier is deterministic.
4. Every verdict is reproducible.
5. Human-readable explanations matter.
6. The open adapter layer should be easy to inspect.
7. The production engine can be optimized without changing the public interface.

## API reference

### SigmaGuard

```python
guard = SigmaGuard(stalk_dim=8, seed=42)
guard.load_json(path)           # Load JSON graph
guard.load_graphml(path)        # Load GraphML
guard.load_edge_list(path)      # Load edge list
guard.load_dict(data)           # Load from dict
verdict = guard.verify()        # Full verification
result = guard.check_write(...) # Incremental single-write check
```

### Verdict

```python
verdict.has_contradictions       # bool
verdict.contradiction_count      # int
verdict.contradictions           # List[Contradiction]
verdict.h1_dimension             # int
verdict.spectral_gap             # float (0-1)
verdict.elapsed_ms               # float
verdict.proof_id                 # str
verdict.certificate              # dict
```

### Contradiction

```python
c.severity          # "CRITICAL" | "HIGH" | "MODERATE" | "LOW"
c.location          # (vertex_label_a, vertex_label_b)
c.energy            # float
c.energy_fraction   # float
c.explanation       # str
c.proof_id          # str
```

## Custom adapters

```python
from sigma_guard.adapters.base import GraphDatabaseAdapter

class MyDatabaseAdapter(GraphDatabaseAdapter):
    def connect(self, **kwargs):
        ...
    def install_trigger(self):
        ...
    def on_write(self, vertices, edges, properties):
        verdict = self.guard.check_write(vertices, edges, properties)
        if verdict.creates_contradiction:
            raise ContradictionError(verdict)
        return True
```

## LLM agent integration

SIGMA Guard is not just for graph databases. Any LLM that produces
structured claims can be verified before those claims are trusted.

The model does not matter. OpenAI, Anthropic, Google, Meta, Mistral,
Nous/Hermes, or any local model. SIGMA verifies the output, not the model.

See [docs/llm_agent_integration.md](docs/llm_agent_integration.md) for
the full integration guide, code examples, and domain-specific use cases.

## Citation

If you reference SIGMA Guard:

```
Jason Leonard Volk. SIGMA Guard: deterministic structural contradiction
detection for graph databases. Invariant Research, 2026.
```

## License

Business Source License 1.1 (BSL-1.1).

Free local tier: up to 10,000 vertices / 100,000 edges.

Enough to run real proofs of concept, evaluate contradiction detection,
and test SIGMA Guard against your own graph data. No time limit. No
cloud dependency. Unlimited local runs.

Production-scale graphs, optimized incremental verification, enterprise
receipt ledgers, and deployment support require a commercial license.
Contact [Invariant Research](https://invariant.pro/licensing).

| Tier | Vertices | Edges |
|---|---|---|
| Free | 10,000 | 100,000 |
| Pro | 250,000 | 2,500,000 |
| Team | 2,000,000 | 20,000,000 |
| Enterprise | Custom | Custom |

A vertex is any graph node submitted for verification. Edges are
counted separately.

The standalone verifier is released under Apache 2.0.

## About

Built by [Invariant Research](https://invariant.pro).

Related work: SATYA applies the same deterministic verification philosophy
to hallucination detection in legal, compliance, and citation-audit workflows.
