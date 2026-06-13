# Planted-Violation Benchmark: Design

Author: Jason Leonard Volk, Invariant Research
Date: 2026-06-10
Status: design for approval. No code written yet.
Companion to: REVIEWER_RESPONSES.md (axis 2 falsifier, axis 5 drift),
FINDINGS.md in patent/validation/claim_8/proxy_true_gap/ (successor
question), H1_OBSTRUCTION_UPGRADE_PLAN.md (this benchmark is the
synthetic validation of the D1 operator side against known D2-style
transports).

## Purpose

Produce a positive, defensible detection number for the claim SATYA
actually makes: holonomy-class contradictions are detected exactly,
localized to the carrying cycle, with zero false positives on
consistent inputs. The proxy-vs-true measurement (2026-06-10) vacated
the framing that the streaming number approximates H^1; this benchmark
puts a real number where that claim was, on the surface that genuinely
carries the signal.

## Detection surfaces under test (all verified in source, 2026-06-10)

S1. cycle_holonomy (sigma/core/cohomology.py). Builds a deterministic
BFS spanning forest, walks the beta_1 fundamental cycles, composes
per-edge transports T(a->b) = pinv(rho_b) @ rho_a, reports per-cycle
Frobenius residual ||H - I|| with chord_edge / chord_u / chord_v
localization. Basepoint-invariant for orthogonal transports. This is
the primary surface.

S2. Rank-based dimensions (CohomologyComputer.dim_h0 / dim_h1, and
exact_cohomology in mayer_vietoris.py). Frustration raises
rank(delta_0), lowering dim H^0 and dim H^1 in lockstep below the
constant-sheaf golden values (d per component; d x beta_1 from
expected_constant_sheaf_h1). The two deficits must be equal (Euler
identity dim H^0 - dim H^1 = d(V - E) holds by construction), which is
a built-in self-check.

S3. project_nonexact (sigma/core/cohomology.py). The data-cocycle
formulation: an observed per-edge discrepancy 1-cochain projected onto
coker(delta_0); nonzero harmonic norm = obstruction, support of the
nonexact vector = localization. Secondary tier; exercises the
"cokernel for unsupported claims" path.

S4. Streaming observables (tier T2 only): per-cell h1_dim proxy and
exact_h0/exact_h1 after flush, via IncrementalUpdater and
compute_all_eigendata_cpu.

## Ground truth construction (gauge-correct)

Baselines. Two consistent-by-construction nulls:
- B0 constant: rho = c x I on every incidence (the smoke-test builder;
  golden case G2 applies: dim H^1 = d x beta_1, all residuals 0).
- B1 pure gauge: pick a random orthogonal g_x per vertex, set
  rho_(x->e) = c x g_x on every incidence of x. Transport is
  g_b^T g_a, which telescopes to the identity around every closed
  cycle, so all holonomies are exactly I while every map looks
  random. B1 is the load-bearing null: it defeats the objection that
  the consistent baseline is trivially the identity sheaf.

Planting. A violation is an orthogonal twist on one incidence of one
edge: rho' = rho @ R. Orthogonal multiplication preserves singular
values, so the Purity Gate bound is automatically respected. Two twist
families:
- Z2 tier: R = -I (the negation case; matches the sigma_e = -1
  semantics of negation_parity). Predicted residual on a cycle
  carrying one flip: ||(-I) - I||_F = 2 sqrt(d). Exact.
- SO(d) tier: R = Givens rotation by theta in a random 2-plane.
  Predicted residual: 2 sqrt(2) |sin(theta/2)|. The theta sweep is the
  drift-before-contradiction continuum (axis 5) with an analytic curve
  to match.

Gauge correctness. A twist on a spanning-tree edge of the detector's
own forest distributes across every fundamental cycle whose tree path
uses it; a twist on a chord edge appears in exactly one cycle. The
benchmark therefore scores at two tiers:
- Tier A (clean localization): replicate the detector's deterministic
  BFS forest in the generator and plant only on chord edges. Ground
  truth = the k chords. Expected: residual > tol on exactly those k
  cycles, 0 elsewhere.
- Tier B (gauge-invariant, stronger): plant on arbitrary edges,
  compute the PREDICTED holonomy of every fundamental cycle from the
  planted twists it carries, and require measured residual to match
  predicted residual per cycle to numerical precision. This tests the
  detector as an exact instrument, not a binary alarm.

Pairwise-blindness property (axis 2 evidence). Every planted
configuration keeps each single edge locally satisfiable (both maps
invertible), so no per-edge or pairwise check can fire; only the cycle
product detects. The harness asserts per-edge solvability explicitly
on planted runs.

## Scoring

1. False positives: on B0 and B1 at every size, holonomy_residual_max
   < 1e-9 and rank deficits = 0. Target: zero FP, matching the
   Wikidata standard.
2. Detection: every planted cycle's residual exceeds 1e-6 (predicted
   magnitudes are order 1, so the margin is ~6 orders).
3. Localization: precision/recall of {cycles with residual > tol}
   against ground truth (tier A) and max |measured - predicted| per
   cycle (tier B).
4. Rank cross-check: h0_deficit == h1_deficit, Euler identity holds,
   and on the hand-checkable golden graphs the exact predicted
   dimensions match.
5. Counting: number of nontrivial cycles vs k (tier A exact; tier B
   predicted from cycle membership).

## Scale ladder

T0 golden: triangle, theta graph, two disjoint triangles (mirroring
_holonomy_smoke.py), hand-verified expectations, d=3 and d=8.
T1 synthetic: random connected graphs V in {200, 1000, 5000}, average
degree ~6, k in {1, 5, 25}, Z2 and theta-sweep tiers, B0 and B1
baselines, 3 seeds each.
T2 cellular (after T0/T1 pass): Enron 21K partition; plant via
IncrementalUpdater.update_restriction_map (Purity-Gate-checked,
dirty-propagating, verified in incremental.py) on intra-cell edges
only, respecting the lossy-coverage finding; score per-cell
cycle_holonomy on cell.sheaf plus the S4 observables through a flush.
T2 demonstrates the streaming engine carries planted violations to a
detectable per-cell surface; it is explicitly not a claim that the
streaming proxy measures H^1.

## Deliverables and phases

P0 (done 2026-06-10): detector source read end to end
(cohomology.py, _holonomy_smoke.py, test_z2_holonomy.py); this design.
P1: sigma/demo/planted_violation_bench.py implementing T0 + T1, JSON +
txt to sigma/patent/validation/planted_violation/, deterministic
seeds, predicted-vs-measured tables.
P2: runs, FINDINGS.md in the output folder, doc updates (REVIEWER axis
2 status line gains the measured number).
P3: T2 cellular tier.

## What this benchmark does not claim

It does not certify the text-extraction layer (negation_parity has its
own unit tests); it certifies the engine math those parities feed. It
does not change any claim about the streaming proxy. It does not test
the protein connection sheaf itself; it validates the detection
operators that workstream will rely on, with synthetic transports of
known ground truth.
