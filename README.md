# SIGMA Guard

**Structural verification for graph databases.**

Your graph can pass every schema check and still contradict itself.
SIGMA Guard catches that before the write commits.

**5M vertices. 35 microseconds per edit. Zero drift. Zero ML.**

> Note: This project is unrelated to SigmaHQ detection rules.
> SIGMA Guard is a graph consistency verification layer from
> [Invariant Research](https://invariant.pro).

## Quickstart

```
pip install sigma-guard
```

### Scan a Neo4j graph

```
pip install sigma-guard[neo4j]
```

```python
from sigma_guard.adapters.neo4j import Neo4jGuard

guard = Neo4jGuard(
    uri="bolt://localhost:7687",
    auth=("neo4j", "password"),
    constraints={
        "SUPPLIES": {"acyclic": True},       # cycles = contradiction
        "BORDERS": {"symmetric": True},       # A->B requires B->A
        "HAS_CAPITAL": {"functional": True},   # at most one target
    },
)
guard.connect()
result = guard.verify_current_graph()

print("Contradictions:", result.contradiction_count)
for c in result.contradictions:
    print(" [%s] %s" % (c.severity, c.explanation))
```

### Scan a Memgraph graph

```
pip install sigma-guard[memgraph]
```

```python
from sigma_guard.adapters.memgraph import MemgraphGuard

guard = MemgraphGuard(
    host="localhost", port=7687,
    constraints={"DEPENDS_ON": {"acyclic": True}},
)
guard.connect()
result = guard.verify_current_graph()
```

### Scan a JSON graph (no database needed)

```python
from sigma_guard.engine import SigmaGuard

guard = SigmaGuard(constraints={"REPORTS_TO": {"acyclic": True}})
guard.load_json("my_graph.json")
result = guard.verify()
print(result.summary())
```

## Real-world proof: Wikidata

We scanned Wikidata for every sovereign state, its capitals, and
its border relationships. 197 countries. 204 cities. 999 edges.

Two constraints:
- BORDERS must be symmetric (if A borders B, B borders A)
- HAS_CAPITAL must be functional (each country has one capital)

Results:

| Finding | Count |
|---|---|
| Asymmetric borders (e.g., Taiwan BORDERS China but not reverse) | 59 |
| Multi-capital countries (e.g., South Africa has 3) | 6 |
| **Total contradictions** | **65** |
| False positives | **0** |
| Elapsed | **0.37 seconds** |
| ML or GPU used | **None** |

Every finding is a real data quality issue that a Wikidata editor
would confirm. No false positives. No ML. No GPU. Deterministic.

## The problem no one else solves

Schema validators check shape. Constraint engines check rules.
Neither one checks whether the graph tells one consistent story.

Two nodes can individually pass every validation and still
contradict each other. In a knowledge graph, that is a
hallucination waiting to happen. In a compliance graph, that
is a regulatory finding. In an agent memory graph, that is
a wrong answer your users will see.

SIGMA Guard detects structural contradictions using sheaf
cohomology: a mathematical framework that proves whether
local claims can glue into one globally consistent assignment.
If they cannot, you get the exact edges where the contradiction
lives, a severity ranking, and a deterministic proof receipt.

Not a probability. Not a confidence score. A proof.

## Constraint configuration (v0.3.0)

Declare rules per relationship type. The engine uses three
independent detection mechanisms:

```python
from sigma_guard.engine import SigmaGuard, RelationConstraint

guard = SigmaGuard(constraints={
    # Sheaf cohomology (H^1): detects cycles
    "SUPPLIES": {"acyclic": True},
    "DEPENDS_ON": {"acyclic": True},
    "REPORTS_TO": {"acyclic": True},

    # Direct graph check: A->B requires B->A
    "BORDERS": {"symmetric": True},
    "ADJACENT_TO": {"symmetric": True},

    # Direct graph check: at most one target per source
    "HAS_CAPITAL": {"functional": True},
    "HAS_CEO": {"functional": True},

    # Property check: named keys must agree across edge
    "SAME_ORG": RelationConstraint(agree_on={"country"}),
})
```

**How the three mechanisms work:**

| Mechanism | Constraint types | What it catches |
|---|---|---|
| H^1 cohomology | acyclic | Circular dependencies in supply chains, reporting hierarchies, dependency graphs |
| Direct graph inspection | symmetric, functional | Missing reciprocal edges, duplicate targets |
| Property comparison | agree_on | Specific property mismatches across edges that require agreement |

**Design rules:**
- If H^1 = 0, zero structural contradictions are reported (the sheaf is the authority)
- If constraints = {}, nothing is flagged (the user said "no rules")
- Each mechanism runs independently; agree_on works on trees where H^1 is always 0
- Constraint configuration replaces defaults when explicitly provided

## Why this matters now

Every AI system that builds or mutates a graph needs this.

- **GraphRAG pipelines** retrieve contradictory facts into the same
  context window. SIGMA Guard catches that before retrieval.
- **Agentic systems** accumulate state across tool calls, memory
  writes, and dependency insertions. SIGMA Guard verifies each
  mutation before commit.
- **Legal and compliance AI** must prove their outputs are
  structurally sound. SIGMA Guard produces cryptographic
  verification receipts on every check.
- **Knowledge graph ETL** merges data from multiple sources that
  may disagree. SIGMA Guard finds the disagreements that schema
  validation misses.

Colorado SB 24-205 and EU AI Act Article 15 require documentation
of AI system reliability. A SIGMA Guard receipt is a compliance
artifact.

## Performance

This is not a research prototype. This is production infrastructure.

| Metric | Value |
|---|---|
| Per-edit latency (median) | **35 microseconds at 5M vertices** |
| Per-query latency | 13 microseconds at 1M vertices |
| Validated scale | **5,000,000 vertices** |
| Cells at 5M | 25,473 |
| Scaling exponent | 0.19 (sub-linear, R^2 0.975, 8 seeds) |
| Cohomology drift | **0 (verified by full recompute at 5M)** |
| RestrictionStore memory at 5M | 0.50 MB (1,025 unique maps) |
| ML required | None |
| GPU required | None |
| Training data required | None |

Latency note: the 35 microsecond per-edit median is measured at
5,000,000 vertices. The 13 microsecond per-query figure is measured at
1,000,000 vertices with the nerve-tree lookup path; it is reported at 1M,
not 5M. Drift is verified to be exactly zero by full independent
recomputation at 5,000,000 vertices (incremental H^1 = 103,690 equals
batch recomputation H^1 = 103,690, verified June 1, 2026).

Single machine. Intel i9-13900H, 64 GB RAM. No cluster. No cloud
dependency. Cellular Mayer-Vietoris streaming architecture reduces
per-edit verification from O(n^3) to O(1) amortized. Every edit
touches only the bounded local cell, not the global graph.

That is not an approximation. That is a theorem.

## Database adapters

### Neo4j

```
pip install sigma-guard[neo4j]
```

```python
from sigma_guard.adapters.neo4j import Neo4jGuard

guard = Neo4jGuard(
    uri="bolt://localhost:7687",
    auth=("neo4j", "password"),
    constraints={"SUPPLIES": {"acyclic": True}},
)
guard.connect()

# Scan entire graph
result = guard.verify_current_graph()

# Or intercept writes
guard.execute("CREATE (a:Node)-[:SUPPLIES]->(b:Node)")
```

### Memgraph

```
pip install sigma-guard[memgraph]
```

```python
from sigma_guard.adapters.memgraph import MemgraphGuard

mg = MemgraphGuard(
    host="localhost", port=7687,
    constraints={"DEPENDS_ON": {"acyclic": True}},
)
mg.connect()
result = mg.verify_current_graph()
```

Memgraph also supports a BEFORE COMMIT trigger for automatic
write verification. See
[examples/memgraph_trigger.py](examples/memgraph_trigger.py).

### FalkorDB

```
pip install sigma-guard[falkordb]
```

```python
from sigma_guard.adapters.falkordb import FalkorDBGuard

guard = FalkorDBGuard(
    host="localhost", port=6379, graph="knowledge",
    constraints={"IsA": {"acyclic": True}},
)
guard.connect()
result = guard.verify_current_graph()
```

### Custom adapters

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

## Standalone verification (no database)

### From a JSON file

Create `my_graph.json`:

```json
{
  "vertices": [
    {"id": "A", "label": "HQ", "claims": {"country": "US"}},
    {"id": "B", "label": "Branch", "claims": {"country": "US"}},
    {"id": "C", "label": "Lab", "claims": {"country": "DE"}}
  ],
  "edges": [
    {"source": "A", "target": "B", "relation": "SAME_ORG"},
    {"source": "B", "target": "C", "relation": "SAME_ORG"}
  ]
}
```

```
python -m sigma_guard.standalone_verifier --graph my_graph.json
```

### From the repo examples

```
git clone https://github.com/Jasonleonardvolk/sigma-guard.git
cd sigma-guard
pip install -e .
python examples/tiny_contradiction.py
python examples/basic_usage.py
```

See [docs/graph_format.md](docs/graph_format.md) for the full format
reference.

## What is sheaf cohomology doing here?

Imagine every node in a graph holds a small piece of a story.
Each edge says how two pieces of the story should agree. If all
local stories agree, the graph can be glued into one global story.
If they cannot, the graph has a structural contradiction.

SIGMA Guard detects that failure:

1. Each node gets a **stalk** (a vector space representing its claims)
2. Each edge gets a **restriction map** (how adjacent claims relate)
3. The **coboundary operator** measures disagreement across all edges
4. **H^1 cohomology** identifies contradictions no local fix can resolve

The **Dirichlet energy** on each edge tells you exactly where the
contradiction lives. Every detected contradiction is a provable
mathematical obstruction, not a statistical guess.

## When not to use SIGMA Guard

- Simple schema validation (use database constraints)
- Checking required fields (use SHACL or JSON Schema)
- Fuzzy semantic similarity (use embeddings)
- LLM answer grading (use an evaluation framework)
- Generic data cleaning (use a data quality tool)

Use SIGMA Guard when graph facts are individually valid but may be
globally inconsistent.

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
      "explanation": "Circular dependency: 'Gamma' and 'Acme' are
        connected via 'SUPPLIES', which is declared acyclic."
    }
  ]
}
```

## MCP server

SIGMA Guard runs as an MCP (Model Context Protocol) server.
Any MCP-compatible agent can call it as a verification tool.

```
pip install sigma-guard[mcp]
sigma-guard-mcp
```

Tools exposed: `verify_graph`, `verify_claims`, `check_write`.

```json
{
    "mcpServers": {
        "sigma-guard": {
            "command": "sigma-guard-mcp",
            "args": []
        }
    }
}
```

Works with Claude Desktop and any MCP-compatible framework.
See [docs/mcp_server.md](docs/mcp_server.md).

## API reference

### SigmaGuard

```python
from sigma_guard.engine import SigmaGuard, RelationConstraint

guard = SigmaGuard(
    stalk_dim=8,
    seed=42,
    constraints={...},        # per-relation constraint rules
)

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

## Architecture

| Mode | Purpose | Availability |
|---|---|---|
| Standalone verifier | Pure numpy/scipy verification for demos, tests, and reproducible examples | Included (Apache 2.0) |
| Full SIGMA engine | Optimized cellular incremental architecture for production-scale verification | Available via Docker or direct installation |

The public repo is runnable without the full engine. `pip install sigma-guard`
then `python examples/tiny_contradiction.py` works on a clean machine
with only Python, numpy, and scipy.

When the full SIGMA engine is available on the Python path, SIGMA Guard
uses it automatically for faster performance on large graphs.

## How SIGMA Guard differs

| Tool type | Checks | Limitation |
|---|---|---|
| Schema validation | Field shape, labels, types | Does not detect global contradiction |
| Database constraints | Local rule violations | Usually local or procedural |
| SHACL | RDF constraint validation | Rule-based, not cohomological |
| LLM judge | Plausibility of output | Probabilistic and prompt-sensitive |
| SIGMA Guard | Structural graph consistency | Depends on configured graph model |

## CLI

```
sigma-guard verify my_graph.json              # exit 0 = consistent, 1 = contradiction
sigma-guard verify --format graphml data.xml   # GraphML input
```

| Exit code | Meaning |
|---|---|
| 0 | Graph verified consistent |
| 1 | Contradiction detected |
| 2 | Input, parser, engine, or configuration error |

### CI usage

```yaml
- name: Graph consistency check
  run: |
    pip install sigma-guard
    sigma-guard verify graph_snapshot.json
```

## Roadmap

- [x] MCP server for agent integration
- [x] Neo4j adapter
- [x] Memgraph adapter
- [x] FalkorDB adapter
- [x] Constraint configuration system (v0.3.0)
- [x] Wikidata real-world demo
- [ ] Benchmark reproduction scripts
- [ ] Native Neo4j JVM plugin
- [ ] NetworkX importer
- [ ] GraphRAG memory contradiction demo
- [ ] `--explain` flag for plain-English output
- [ ] `--fail-on` flag for CI severity filtering

## Known limitations

- The standalone verifier is designed for demos, tests, and small/medium graphs.
- Production-scale cellular incremental verification uses the full SIGMA engine.
- Neo4j native transaction listeners require a JVM plugin; the current adapter
  uses a guarded write wrapper.
- The quality of results depends on the quality of the configured constraints.

## FAQ

**Is this an LLM?**
No. SIGMA Guard does not ask a model whether the graph looks right.

**Is this schema validation?**
No. Schema validation checks local shape. SIGMA Guard checks global consistency.

**Do I need the private SIGMA engine?**
No for demos and local verification. The repo includes a standalone verifier.
The full engine is for production-scale deployment.

**Does this work with Neo4j, Memgraph, and FalkorDB?**
Yes. Adapters for all three ship in the package. Install the database extra
you need: `pip install sigma-guard[neo4j]`.

## License

Business Source License 1.1 (BSL-1.1).

Free local tier: up to 10,000 vertices / 100,000 edges.

| Tier | Vertices | Edges |
|---|---|---|
| Free | 10,000 | 100,000 |
| Pro | 250,000 | 2,500,000 |
| Team | 2,000,000 | 20,000,000 |
| Enterprise | Custom | Custom |

The standalone verifier is released under Apache 2.0.

## Citation

```
Jason Leonard Volk. SIGMA Guard: deterministic structural contradiction
detection for graph databases. Invariant Research, 2026.
```

## About

Built by [Invariant Research](https://invariant.pro).
