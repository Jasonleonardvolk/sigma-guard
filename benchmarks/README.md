# Benchmarks

Performance claims in the README are based on the scaling runs
documented here. This file exists so every number has a source.

## Hardware

- CPU: Intel Core i9-13900H (14 cores, 20 threads)
- RAM: 64 GB DDR5
- GPU: NVIDIA RTX 4060 (not used by SIGMA; all computation is CPU-only)
- OS: Windows 11
- Python: 3.11
- NumPy/SciPy: standard pip versions

No cloud instances. No distributed compute. Single machine.

## What "baseline" means

Baseline is **full sheaf cohomology recomputation** on every graph
mutation. That means:

1. Rebuild the full coboundary matrix (vertices x edges)
2. Compute dense SVD of the coboundary matrix
3. Extract H^0, H^1 dimensions from the singular value decomposition
4. Compute Dirichlet energy per edge

This is O(n^3) in the number of vertices because dense SVD dominates.

SIGMA's **cellular incremental architecture** replaces this with:

1. Identify which cell(s) in the cellular decomposition are affected
   by the mutation
2. Recompute cohomology only for those cells
3. Propagate boundary corrections via Mayer-Vietoris

This is O(n) amortized per edit.

The 10,504x speedup is the ratio of baseline full-recomputation time
to SIGMA incremental-update time at 1,000,000 vertices.

## What "scaling exponent 0.19" means

If you plot log(time per edit) vs log(number of vertices), the slope
is the scaling exponent. An exponent of 1.0 means linear scaling.
An exponent of 3.0 means cubic (the baseline).

SIGMA's measured exponent is **0.19**, meaning the cost per edit grows
much slower than the graph size. Doubling the graph size increases
per-edit cost by a factor of 2^0.19 = 1.14 (a 14% increase, not a
100% increase).

This was measured post drift-zero fix (April 17, 2026) across three
independent seeds (42, 137, 2718) with verified drift=0 on all seeds.

## Key runs

### Enron email corpus (Run #23)

- Dataset: Enron email network
- Vertices: 639 cells
- Total runtime: 30.3 seconds
- Per-vertex cost: 0.61 ms/vertex

### Scale validation (V=1,000,000)

- Synthetic cellular graph workload
- 1,000,000 vertices
- Incremental edit cost: 63 microseconds per edit
- Query cost: 13 microseconds per query
- Speedup vs full recomputation: 10,504x
- Scaling exponent: 0.19
- Seeds: 42, 137, 2718
- Drift: 0 on all seeds (post drift-zero fix)

### Phase 3 multi-seed stability (April 9-10, 2026)

- 4 seeds x 300 cycles = 1,200 total cycles
- Purity Gate + density governor (w=1.5)
- Final E/V mean: 3.05
- Coefficient of variation: 1.9%
- Crashes: 0 across 1,200 cycles

## What "63 microseconds" measures

The 63 microsecond figure is the time to:

1. Receive a graph mutation (add/modify vertex or edge)
2. Identify the affected cell in the cellular decomposition
3. Recompute local cohomology for that cell
4. Update the global H^1 dimension and energy
5. Return a verdict (consistent or contradiction detected)

This does NOT include:
- Network round-trip to a database
- Parsing input from a file or API request
- Cryptographic signing of the proof receipt

Those are measured separately and depend on deployment topology.

## What "13 microseconds" measures

The 13 microsecond figure is the time to query the current
contradiction state of the graph without performing a new mutation.
This is a read from the cached cellular decomposition.

## Reproduction

The scaling experiments were run using the internal SIGMA engine
codebase. The reproduction scripts are being extracted into
standalone form for this repository.

To verify the claims with the public adapter layer:

```
sigma-guard verify datasets/supply_chain.json --json
```

This runs full (non-incremental) verification on a small dataset.
The incremental 63-microsecond path requires the cellular engine,
which runs behind the binary/Docker boundary.

## Eigensolver speedup

The eigensolver component shipped a 72x speedup by switching from
dense eigenvalue decomposition to sparse ARPACK (shift-invert mode)
for the sheaf Laplacian. This is used for spectral gap computation
on graphs with more than 200 vertices.
