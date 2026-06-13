# SIGMA Reviewer Responses

Author: Jason Leonard Volk, Invariant Research
Scope: theoretical and systems questions raised by reviewers of the SIGMA
sheaf framework (arXiv:2606.04227 and related work).
Stance: every answer separates what is proven from what is measured from
what is currently conjectured. Where a question exposes a real seam, the
seam is named rather than deflected.

## How to read these

The reviewer raised roughly nineteen questions across two passes. They look
independent but they collapse onto a small number of load-bearing axes:

1. What a cohomological contradiction actually is. (Grounded, low risk.)
2. Whether the sheaf is essential or weaker machinery would do. (Existential
   for the program.)
3. Consistency debt, percolation, amortization, adversarial updates, and how
   often flushes are unavoidable. (One question asked five ways. Make or
   break.)
4. Partition stability over long streams and whether partition maintenance
   eventually dominates. (The same percolation risk aimed at the partitioner.)
5. Drift detection before explicit contradiction. (Promising, easy to
   overclaim.)
6. Hierarchical or recursive flush. (Right architecture, inherits axis 3.)
7. Higher-dimensional sheaves. (Genuinely new; the honest answer is partial.)
8. Spectral and pathological cases where locality breaks. (Axis 3 in spectral
   language.)

The two that decide whether this is a deeper framework or a clever dynamic
algorithm are axis 2 and axis 3. Everything else is downstream of those two.

## Implementation scope note (2026-06-10)

Two distinct computations are referred to as "flush" in places below, and
they have different cost structures. Verified against deployed source:

- Deployed streaming flush (IncrementalUpdater.flush_dirty_cells): a
  sequential per-cell loop that recomputes each dirty cell's local H^1
  proxy (h0 - beta_0) from that cell's own sheaf. Cost is
  O(|dirty_cells| * v_max^3 * s^3), conductance-blind, and caller-driven
  (no trigger policy exists). Measured insensitive to dirty-region
  boundary structure on 2026-06-10.
- True assembly (MayerVietoris.compute_recursive_mv): exact global sheaf
  H^1 via recursive pairwise merges with rho-rank SVDs over boundary
  stalks. This is where separator size and conductance enter the cost.
  Correct by construction; not called by the streaming loop or the scale
  demo.

Where an answer below invokes separators, conductance, Cheeger constants,
or elimination fill as a flush cost driver, that applies to the assembly
path (or a future engine that assembles at flush time), not to the
deployed per-cell flush. INTERFLUSH_LOWER_BOUND.md carries the same
correction in detail.

## 1. What a cohomological contradiction means

For a cellular sheaf F on a graph, H^0(F) is the space of global sections,
that is, the assignments to stalks that agree across every restriction map.
H^1(F) is the obstruction to gluing locally consistent data into a single
global section. A contradiction is a nonzero class in H^1: local data that is
pairwise fine but cannot be reconciled globally. The class is not just a
yes or no flag. It localizes, in the sense that it identifies which cycle of
restriction maps carries the obstruction, which is exactly the region a user
or an agent needs to inspect.

The one honest caveat: whether every contradiction a human cares about maps to
a cohomology class is a modeling assumption about the encoding, not a theorem.
The framework guarantees that obstructions of this algebraic form are detected
exactly. It does not guarantee that an arbitrary semantic disagreement has been
encoded into the sheaf in the first place. That gap is an encoding
responsibility, and it should be stated plainly rather than hidden inside the
exactness claim.

## 2. Is the sheaf essential, or would weaker machinery suffice

This is the question the program most needs a crisp, demonstrable answer to,
because it is also the falsifier (see the reviewer's "what would falsify the
direction" and "minimal structure required" questions, which are the same
question wearing different hats).

The whole apparatus is justified only by contradictions that are provably
invisible to any pairwise or purely local check. The canonical shape is a loop
with nonzero holonomy. Take three claims: A is north of B, B is north of C,
C is north of A. Every individual edge is locally consistent. There is no
single edge you can point to as wrong. The inconsistency lives only in the
composition around the cycle, and it is exactly a nonzero holonomy, that is, a
nonzero H^1 class. No pairwise checker, no union-find connectivity test, and no
local constraint propagator sees it, because each of them only ever examines
one edge or one local neighborhood at a time.

The concrete instance that carries this burden in our own results is the Z2
holonomy-for-negation construction in ContractNLI. A chain of individually
plausible entailments whose signs compose, around a cycle, to a contradiction
is precisely a holonomy-only obstruction. That is the load-bearing example and
it should be presented as such, because it is what answers "why not something
weaker."

The honest converse, which doubles as the falsifier: if on realistic workloads
essentially every contradiction that matters is local, then a cheaper mechanism
(union-find for connectivity, a constraint propagator for the rest) catches it,
and the sheaf machinery is elegant decoration rather than necessary
infrastructure. The program lives or dies on demonstrating that higher-order,
holonomy-only contradictions occur in real systems and matter, not just that
they can be constructed.

Status (2026-06-10): the machinery half of this axis is now measured, not
asserted. The planted-violation benchmark
(sigma/demo/planted_violation_bench.py; results and FINDINGS.md in
sigma/patent/validation/planted_violation/) planted holonomy-only violations
into consistent-by-construction sheaves, including a pure-gauge null where
every map is random but every holonomy provably telescopes to identity.
Across 91 scenarios and 541 checks (three seeds, V up to 5000, beta_1 up to
about 10^4, k up to 25 simultaneous plants, Z2 and rotation twists): zero
false positives (null residuals at machine epsilon, at most 5.1e-15), every
planted violation detected and localized to its carrying cycle with
precision and recall 1.0, measured residuals matching analytic predictions
to 5.1e-15 against a 1e-8 tolerance, and every planted edge individually
satisfiable, so no per-edge or pairwise checker can fire by construction. A
flip planted on a bridge correctly produced no detection and no H^0 change:
ground truth is cycle-level. What remains open on this axis is exactly the
prevalence half, that holonomy-only contradictions occur and matter in real
workloads. The falsifier now rests entirely there.

## 3. Consistency debt, percolation, amortization, adversarial updates, flush frequency

These are one question asked five ways, and it is the make-or-break empirical
claim.

Consistency debt is the right state variable, and the term should be adopted
because it is not a metaphor. Define it precisely as the size of the unresolved
obstruction currently deferred: dirty cells, boundary cells pending re-gluing,
or the dimension of the not-yet-reconciled cokernel and H^1. Once debt is
defined this way, the O(1) amortized claim is exactly the claim that debt is
paid down at a bounded rate per edit and cannot grow without bound short of
triggering a flush.

With debt defined, the percolation question decides everything. There is
presumably a critical edit density or correlation length above which dirty
regions percolate across partition boundaries and force global synchronization.
Below threshold, the streaming story holds and amortization is real. At or
above threshold, the O(1) story degrades into frequent global flushes and the
amortized bound collapses to roughly flush-cost divided by inter-flush
interval.

Adversarial updates are then a precise sub-question: can an adversary cheaply
and repeatedly push the system above the percolation threshold. Amortized
bounds fail in exactly this way, because the adversary controls the inter-flush
interval. What needs to be airtight is not the average case but a proven lower
bound on inter-flush spacing under arbitrary edit sequences. That is a real
theorem. Absent it, "O(1) amortized" is conditional on benign workloads, which
is a strictly weaker claim and a sharp reviewer will downgrade it to exactly
that.

"How often do flushes become unavoidable in practice" is the empirical
companion to the theorem: measure flush frequency on realistic and
adversarial-style streams, not on the benign V=5M benchmark, which by
construction stays below threshold and therefore cannot answer the question it
appears to answer.

Status: the per-edit cost is measured and holds at 5M vertices, and the
zero-drift result at 5M is equality of the lazily maintained proxy against a
full proxy recompute (proxy equals proxy). It is not a comparison of the
proxy against true sheaf H^1. That comparison was run on 2026-06-10 (Enron
21K, sigma/demo/proxy_true_gap.py): proxy 380 versus exact 263,107 on the
within-cell content. The two are different invariants by construction, not
drifted versions of one quantity: exact H^1 per cell equals
8(E_c - V_c) + h0_c as an identity, so on a random-maps benchmark it is
dominated by cycle rank, while the proxy tracks excess global-section
dimension. See patent/validation/claim_8/proxy_true_gap/FINDINGS.md. The
inter-flush spacing lower bound is currently conjectured for the assembly
path, not proven. Both distinctions should be stated in the paper before a
referee states them for us.

## 4. Partition stability over long streams, and whether partition maintenance dominates

This is the percolation axis aimed at the partitioner itself rather than at the
cohomology, and it is a genuine risk, not a formality.

If partition quality drifts over a long edit stream and eventually forces a
global repartition, that repartition is a deferred global cost, not an
eliminated one. The streaming framing survives only if repartition frequency is
bounded or partition quality is self-stabilizing. Either property has to be
demonstrated over long, adversarial-style runs, because a benign stream will
not exercise the drift.

The sharp version of "is partition maintenance eventually dominant": if the
amortized cost of keeping the partition healthy grows with stream length while
the per-edit cohomology work stays flat, then partition maintenance becomes the
real asymptotic cost and the headline bound describes the wrong component. The
defense is a bound on repartition frequency or a self-stabilization argument.
We do not currently have either as a theorem; we have benign-stream stability.
That should be said.

## 5. Drift detection before explicit contradiction

This is promising and it is where overclaiming is easiest, so it gets the
sharpest honesty.

Over a discrete coefficient system such as Z2, H^1 is binary. There is no
"almost a contradiction," so the discrete obstruction alone gives no early
warning by construction. Detecting drift before an explicit contradiction
requires a continuous relaxation: a real-coefficient sheaf whose consistency
equations carry a residual measuring how far the local data is from gluing
exactly. That residual rises continuously before it crosses into hard
inconsistency, which is what makes early warning possible at all.

The coherence-map and conditioning (kappa) machinery already in the project is
that continuous route. So the honest answer is: yes, drift can be detected
before contradiction, but only via the continuous relaxation, not from the
discrete obstruction. "Semantic curvature" is defensible only if defined as
that residual or a curvature derived from the real-coefficient consistency
operator, and not introduced as a fresh metaphor with no operator behind it.

## 6. Hierarchical or recursive flush

Local flushes feeding regional flushes feeding global flushes is the right
architecture and is probably necessary to scale. But it inherits the
percolation risk of axis 3 rather than escaping it. A recursive flush helps
only if the cut structure between levels stays sparse. If obstructions
concentrate at high levels, a hierarchical flush has moved global recomputation
up one level, not removed it. So the hierarchy is worth building, but its
benefit is contingent on the same locality property that axis 3 has to
establish, and it should not be presented as an independent escape hatch.

## 7. Higher-dimensional sheaves

This is the one genuinely new question in the second pass, and the honest
answer is partial rather than "yes, identically."

The O(1) per-edit story leans on bounded boundary size: each edit touches a
bounded number of cells, so the local recompute is bounded. In higher
dimensions the coboundary fan-out grows, a single high-dimensional cell can
border many lower cells, and the bounded-boundary assumption weakens. The
framework extends in form, but the constant in the bound and the locality
assumption both degrade with dimension. The correct claim is that the machinery
generalizes structurally while the performance guarantee is dimension
dependent, and the dimension dependence has to be characterized rather than
assumed away. We have not measured the higher-dimensional case; that is future
work, and labeling it as such is more credible than implying parity.

## 8. Spectral and pathological cases where locality breaks down

This is axis 3 stated in spectral language, and the failure mode should be
named directly, with one scope clarification. An expander-like dirty region
(high Cheeger constant) is exactly where TRUE assembly stops being cheap:
expanders have no sparse cuts, so there is no small boundary along which
compute_recursive_mv can reconcile cheaply, and resolving an obstruction in
such a region approaches global cost. That is the spectral signature of
crossing the percolation threshold for the assembly path. The deployed
per-cell flush is not the victim here: it was measured conductance-blind on
2026-06-10 (cost tracks dirty-cell count, not cut structure). The honest
statement is therefore: per-cell proxy maintenance survives adversarial
conductance; exact assembly does not, and adversarial high-conductance edit
patterns are outside the assembly-cost guarantee. The right move is to
characterize the spectral condition (low conductance of dirty regions)
under which cheap assembly holds.

## What would falsify the program

Two concrete, testable conditions, both available to test now:

1. If on realistic workloads a cheaper local mechanism catches essentially
   every contradiction that matters, the sheaf is decoration and axis 2 fails.
2. If flush frequency, or repartition frequency, cannot be bounded on real
   (not merely benign) streams, the O(1) amortized claim fails and the system
   is a clever optimization rather than a continuously maintained streaming
   invariant.

Neither is rhetorical. Both reduce to measurements and one lower-bound proof.

## Claim status summary

Proven or exact: per-edit incremental cost at validated scales up to 5M
vertices; zero-drift equality of the lazily maintained proxy against full
proxy recompute at those scales (proxy equals proxy, not proxy equals true
H^1); exact detection of holonomy-class obstructions given the encoding.

Measured on benign streams: 35 microseconds median per edit, sub-linear
scaling, bounded RestrictionStore memory.

Measured 2026-06-10: the streaming proxy and exact sheaf H^1 are different
invariants, not approximations of each other (Enron 21K: proxy 380,
within-cell exact 263,107; exact H^1 is cycle-rank dominated by the
identity h1 = 8(E - V) + h0 per cell). The build-time decomposition holds
roughly a third of the graph's edges inside cells; exact certification
currently covers that content plus the overlap gluings. See
patent/validation/claim_8/proxy_true_gap/FINDINGS.md.

Measured 2026-06-10 (planted violations): holonomy-only contradictions of
known ground truth are detected, localized, and matched to analytic
predictions at machine precision with zero false positives (91 scenarios,
541 checks; see sigma/patent/validation/planted_violation/FINDINGS.md).
The prevalence of such contradictions in real workloads remains the open
half of axis 2.

Conjectured, not yet proven: inter-flush spacing lower bound under arbitrary
edit sequences (for the assembly path); bounded repartition frequency or
partition self-stabilization; higher-dimensional performance parity;
prevalence and materiality of holonomy-only contradictions in real
workloads (axis 2's surviving falsifier).

Encoding assumption, not a theorem: that the contradictions a user cares about
have been faithfully mapped into the sheaf.

The credibility of the framework rests on converting the three conjectured
items into either theorems or honestly scoped limitations before a referee
does it first.
