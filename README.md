# SIGMA Guard

Pre-commit contradiction detection for graph databases.

> Note: This project is unrelated to SigmaHQ detection rules. SIGMA Guard is a graph consistency verification layer from [Invariant Research](https://invariant.pro).

SIGMA Guard is not a schema validator and not an ML judge. It checks
whether graph claims can form one globally consistent structure under
a configured sheaf model.

- Deterministic structural verification
- No ML judge, no probabilistic scoring
- No GPU required
- Cryptographic proof receipts
- File, Memgraph, and Neo4j adapter layer
- Free local tier up to 10,000 vertices

```
pip install sigma-guard
```

```
sigma-guard verify datasets/supply_chain.json
```

```
SIGMA Guard v0.1.0
========================================
Graph: 12 vertices, 18 edges
H^1 dimension: 54
Spectral gap: 1.0000
Total energy: 522.501789

Contradictions found: 7

[CRITICAL] Contradiction #1
  Location: "Component_Y" <-> "Delivery_Plan"
  Energy: 269.7760
  Structural contradiction between 'Component_Y' and 'Delivery_Plan'.
  Certificate: sigma:proof:acb3baee...

[CRITICAL] Contradiction #2
  Location: "Component_Y" <-> "Production_Q2"
  Energy: 229.3921
  Structural contradiction between 'Component_Y' and 'Production_Q2'.
  Certificate: sigma:proof:8c219ff1...

[LOW] Contradiction #6
  Location: "Factory_East" <-> "Factory_West"
  Structural contradiction: disagree on capacity_utilization, surge_capacity.
  Certificate: sigma:proof:6e606d28...

[LOW] Contradiction #7
  Location: "Procurement" <-> "Risk_Register"
  Structural contradiction: disagree on single_source_risk.
  Certificate: sigma:proof:ded498c1...

Verdict: INCONSISTENT
Elapsed: 4.70ms

========================================
Incremental write checks:
========================================

1. Factory_West -> Supplier_A
   Creates contradiction: False
   Elapsed: 455.3 us

2. Procurement -> Quality_Board
   Creates contradiction: True
   Conflict: approved_vendors_component_x
   Elapsed: 459.8 us
```

The demo graph contains planted supply-chain contradictions. SIGMA
catches the dominant timeline conflicts as critical, identifies
lower-energy structural inconsistencies, and distinguishes a safe
write from a contradictory write in under one millisecond.

## Why now

Graph databases are increasingly used as operational memory for AI agents,
security systems, compliance workflows, supply chains, and enterprise
knowledge graphs. Those systems do not just need faster retrieval. They
need a deterministic consistency gate before corrupted graph state becomes
trusted state.

## What this does

Every graph database in production has **silent graph corruption**:
contradictory facts coexist and no system flags them. Schema validation
(SHACL, constraints, triggers) catches missing fields and type errors.
It cannot catch two facts that are individually valid but structurally
incompatible.

SIGMA uses **sheaf cohomology** (specifically, H^1 obstructions over
cellular decompositions) to detect structural contradictions. When two
nodes in your graph make claims that cannot coexist, SIGMA finds them,
locates them, measures their severity, and produces a cryptographic
proof receipt.

No ML confidence scores. No probabilistic judge. A graph is either
consistent under the configured sheaf constraints or it is not.

## What SIGMA does not do

SIGMA does not replace database schema validation. It does not check
whether a field is missing, whether a type is invalid, or whether a
Cypher query is well formed.

SIGMA checks a different failure mode: facts that are individually
valid but globally incompatible.

It does not use an LLM to judge correctness. The verdict is produced
by deterministic graph verification against the configured consistency
model.

## Architecture boundary

This repository contains the open integration layer:

- CLI
- File parsers (JSON, GraphML, edge list)
- Graph database adapters (Memgraph, Neo4j, generic base class)
- Example datasets with planted contradictions
- Proof receipt schemas

The SIGMA verification engine runs behind a local binary or Docker
boundary. The public adapter layer calls the engine and receives
deterministic verdicts and proof receipts. The engine internals are
not included in this repository.

## Quick start

### Verify a graph file

```
# JSON graph
sigma-guard verify my_graph.json

# GraphML
sigma-guard verify my_graph.graphml

# Edge list (TSV: source, target, relation, value)
sigma-guard verify my_graph.edges

# Output as JSON
sigma-guard verify my_graph.json --json

# With cryptographic signing
sigma-guard verify my_graph.json --sign
```

### Use as a Python library

```python
from sigma_guard import SigmaGuard

guard = SigmaGuard()

# Load a graph
guard.load_json("my_graph.json")

# Check for contradictions
verdict = guard.verify()

if verdict.has_contradictions:
    for c in verdict.contradictions:
        print(f"[{c.severity}] {c.location}")
        print(f"  {c.explanation}")
        print(f"  Energy: {c.energy}")
        print(f"  Proof: {c.proof_id}")

# Incremental: check a single write before committing
result = guard.check_write(
    source="Supplier_A",
    target="Component_X",
    relation="sole_source",
    value=True,
)

if result.creates_contradiction:
    print("BLOCKED: This write would create a contradiction")
    print(f"  Conflicts with: {result.conflicting_nodes}")
    print(f"  Proof: {result.proof_id}")
```

### Memgraph integration

SIGMA can be installed as a Memgraph before-commit verification hook.
In block mode, writes that create configured structural contradictions
are rejected before commit.

```python
from sigma_guard.adapters.memgraph import MemgraphGuard

# Connect to Memgraph and install the trigger
mg = MemgraphGuard(host="localhost", port=7687)
mg.install_trigger()

# Every CREATE and SET operation now passes through SIGMA.
# Contradictory writes are rejected with a proof receipt.
```

Or register the trigger manually via Cypher:

```
CALL mg.create_trigger(
    "sigma_guard",
    "BEFORE COMMIT",
    "CALL sigma_guard.verify_transaction($createdVertices, $createdEdges, $setVertexProperties)"
) YIELD *;
```

See [examples/memgraph_trigger.py](examples/memgraph_trigger.py) for the
full working example with Docker Compose.

### Neo4j integration

The Neo4j adapter runs as a guarded write wrapper. Instead of sending
writes directly to Neo4j, route writes through `Neo4jGuard.execute()`
so SIGMA can verify the proposed change before commit.

```python
from sigma_guard.adapters.neo4j import Neo4jGuard

guard = Neo4jGuard(uri="bolt://localhost:7687", auth=("neo4j", "password"))

guard.execute("""
    CREATE (:Supplier {name: $name, sole_source: true})
""", name="Supplier_A")
```

Native Neo4j transaction listeners require a JVM plugin. That deeper
integration is planned separately.

See [examples/neo4j_hook.py](examples/neo4j_hook.py) for the full example.

### Docker

```
# Run SIGMA as a verification service
docker run -p 8400:8400 invariant/sigma-guard

# Full stack: Memgraph + SIGMA Guard
docker compose up
```

## How it works

SIGMA constructs a **cellular sheaf** over your graph:

1. Each node gets a **stalk** (a vector space representing its claims)
2. Each edge gets a **restriction map** (a linear map expressing how
   adjacent claims should relate)
3. The **coboundary operator** measures disagreement across all edges
4. **H^1 cohomology** (the cokernel of the coboundary) identifies
   structural contradictions that no local fix can resolve

When H^1 is non-trivial, the graph contains contradictions under the
configured consistency model. The **Dirichlet energy** on each edge
localizes exactly where they are. The **spectral gap** of the sheaf
Laplacian measures overall graph health.

This is not heuristic pattern matching. This is algebraic topology
applied to data consistency. Every detected contradiction is a provable
mathematical obstruction, not a statistical guess.

## Performance

| Metric | Value |
|---|---|
| Latency per write (incremental) | 63 microseconds |
| Latency per query | 13 microseconds |
| Scaling exponent | 0.19 (sub-linear) |
| Validated scale | 1,000,000 vertices |
| Speedup vs full recomputation | 10,504x |
| ML required | None |
| GPU required | None |

Benchmark context:

- Hardware: Intel i9-13900H, 64 GB RAM, no GPU used
- Baseline: full sheaf cohomology recomputation (O(n^3) dense SVD) on
  every graph mutation. SIGMA's cellular incremental architecture
  achieves O(n) by localizing recomputation to affected cells.
- Dataset: synthetic cellular graph workloads plus Enron email corpus
  (639 cells, 30.3s full run)
- Scaling validated across seeds 42, 137, 2718 with drift=0
- Sub-linear scaling (exponent 0.19): the cost per edit grows slower
  than the graph. At 1M vertices, each edit touches only the affected
  cell in the cellular decomposition, not the full graph.
- Benchmark reproduction scripts are being prepared for `benchmarks/`

## Proof receipt shape

```json
{
  "verdict": "INCONSISTENT",
  "proof_id": "sigma:proof:a3f8c2d1-7b4e-4f9a-b8c3-1d2e3f4a5b6c",
  "engine": "sigma-guard-0.1.0",
  "algorithm": "sheaf_cohomology_h1",
  "deterministic": true,
  "graph": {
    "vertices": 12,
    "edges": 18
  },
  "h1_dimension": 3,
  "spectral_gap": 0.393,
  "total_energy": 2.4891,
  "contradictions": [
    {
      "severity": "CRITICAL",
      "location": ["Supplier_A", "Supplier_B"],
      "energy": 0.9412,
      "energy_fraction": 0.378,
      "explanation": "Structural contradiction (H^1 obstruction): 'Supplier_A' and 'Supplier_B' disagree on: sole_source_component_x."
    }
  ],
  "signature": {
    "algorithm": "Ed25519",
    "public_key": "a1b2c3d4...",
    "value": "9a8b7c6d..."
  }
}
```

## Independent verification

SIGMA ships a standalone verifier that recomputes sheaf cohomology
from scratch using only numpy and scipy. It does not import the
SIGMA engine. You do not need to trust SIGMA to verify a SIGMA verdict.

The standalone verifier is released under Apache 2.0 (not BSL) so
anyone can audit it without license concerns.

```
# Compute cohomology independently (no SIGMA engine)
sigma-verify --graph datasets/supply_chain.json

# Verify a proof receipt against independent recomputation
sigma-verify --graph datasets/supply_chain.json --receipt verdict.json
```

```
SIGMA Independent Verifier
========================================
Graph: datasets/supply_chain.json
Receipt: verdict.json

  [OK] h1_dimension: receipt=3, independent=3
  [OK] has_contradictions: receipt=True, independent=True
  [OK] total_energy: receipt=2.4891, independent=2.4891
  [OK] spectral_gap: receipt=0.393, independent=0.393

VERIFIED: Independent computation matches the receipt.
```

The verifier rebuilds the coboundary matrix, runs SVD, computes H^0
and H^1 dimensions, Dirichlet energy, and spectral gap. If any value
disagrees with the receipt, it reports MISMATCH.

Source: [sigma_guard/standalone_verifier.py](sigma_guard/standalone_verifier.py)

## CLI exit codes

| Code | Meaning |
|---|---|
| 0 | Graph verified consistent |
| 1 | Contradiction detected |
| 2 | Input, parser, engine, or configuration error |

## CI usage

Use SIGMA as a graph consistency gate in CI:

```yaml
# GitHub Actions
- name: Graph consistency check
  run: |
    pip install sigma-guard
    sigma-guard verify graph_snapshot.json --quiet
```

```
# PowerShell
sigma-guard verify .\datasets\supply_chain.json --quiet
if ($LASTEXITCODE -ne 0) {
    throw "Graph contradiction check failed."
}
```

```
# Bash
sigma-guard verify datasets/supply_chain.json --quiet || exit 1
```

## Datasets

The `datasets/` folder contains example graphs with planted contradictions:

- `supply_chain.json` - 12 vertices, 18 edges, 3 planted contradictions
  (sole-source conflict, timeline conflict, capacity conflict)
- `cybersecurity.json` - 12 vertices, 15 edges, 4 planted contradictions
  (attribution conflict, timeline conflict, infrastructure conflict, IOC conflict)
- `knowledge_graph.json` - 10 vertices, 12 edges, 3 planted contradictions
  (CEO status conflict, HQ location conflict, ownership conflict)

Each dataset includes a `ground_truth` block with descriptions of every
planted contradiction so you can verify SIGMA catches them.

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
verdict.h1_dimension             # int (dim of obstruction space)
verdict.spectral_gap             # float (graph health, 0-1)
verdict.elapsed_ms               # float
verdict.proof_id                 # str (cryptographic proof ID)
verdict.certificate              # dict (full signed certificate)
```

### Contradiction

```python
c.severity          # "CRITICAL" | "HIGH" | "MODERATE" | "LOW"
c.location          # (vertex_label_a, vertex_label_b)
c.edge_index        # int
c.energy            # float (Dirichlet energy at this edge)
c.energy_fraction   # float (fraction of total obstruction energy)
c.explanation       # str (human-readable)
c.proof_id          # str
```

## Custom adapters

Write your own adapter for any graph database:

```python
from sigma_guard.adapters.base import GraphDatabaseAdapter

class MyDatabaseAdapter(GraphDatabaseAdapter):
    def connect(self, **kwargs):
        # Connect to your database
        ...

    def install_trigger(self):
        # Register SIGMA as a pre-commit hook
        ...

    def on_write(self, vertices, edges, properties):
        # Called before each write. Return False to reject.
        verdict = self.guard.check_write(vertices, edges, properties)
        if verdict.creates_contradiction:
            raise ContradictionError(verdict)
        return True
```

## License

Business Source License 1.1 (BSL-1.1).

Free to use for evaluation, development, and production workloads
up to 10,000 vertices. Above 10,000 vertices, contact
[Invariant Research](https://invariant.pro) for a commercial license.

The core SIGMA engine is patent-pending (U.S. App# 19/649,080).

## About

Built by [Invariant Research](https://invariant.pro).

Related work: SATYA applies the same deterministic verification
philosophy to hallucination detection in legal, compliance, and
citation-audit workflows.
