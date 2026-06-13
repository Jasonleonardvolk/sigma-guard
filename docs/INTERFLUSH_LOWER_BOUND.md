# SIGMA: Inter-Flush Spacing Lower Bound (Proof Strategy)

Author: Jason Leonard Volk, Invariant Research
Companion to: REVIEWER_RESPONSES.md (axis 3, the make-or-break amortization
claim).
Status of this document: a proof strategy, not a finished formal proof. The
accounting steps are rigorous given two lemmas. One lemma is easy and one is
load-bearing. The load-bearing lemma is stated precisely and the exact
condition under which it holds (and fails) is identified. Read the final two
sections before citing any of this as proven.

## Scope correction (2026-06-10)

This document was drafted against a modeled flush architecture in which
Mayer-Vietoris assembly runs at flush time over the dirty-region separator.
Reading the deployed source end to end (incremental.py, cell.py,
laplacian.py, eigensolver.py, mayer_vietoris.py) shows the deployed engine
does something simpler:

- The deployed flush (IncrementalUpdater.flush_dirty_cells) is a sequential
  per-cell loop: invalidate, then recompute each dirty cell's local H^1
  proxy from that cell's own sheaf. Cost is O(|dirty| * v_max^3 * s^3).
  There is no separator solve, no Schur complement, and no conductance
  term. It is conductance-blind by construction.
- Flush is caller-driven only. No debt threshold T and no conductance
  trigger beta exist in the deployed engine; assumption (A3) describes a
  policy of the modeled architecture, not implemented behavior.
- Separator structure, rho-rank SVDs, and elimination-fill cost live in the
  true-cohomology assembly path (MayerVietoris.compute_recursive_mv), which
  is correct by construction but is not called by the streaming loop or the
  scale demo.

Everything below therefore analyzes the modeled MV-at-flush architecture.
Lemma 1 holds for the deployed engine as well (the dirty set grows by O(D)
per edit). Lemma 2 and the conductance trigger apply to the MV assembly
path, and to any future engine that performs assembly at flush time. The
2026-06-10 adversarial probe confirmed the deployed flush is insensitive to
dirty-region conductance: flush time tracked dirty-cell count, not boundary
structure. See "Empirical support and its limits" below.

## What this argument does and does not claim

It does not prove an unconditional lower bound over truly arbitrary edit
sequences. Such a bound is most likely false, because an adversary who can
drive the dirty region into a high-conductance configuration can force frequent
expensive flushes. Claiming otherwise would be the exact failure mode the
reviewer was braced for.

It proves a conditional lower bound: under bounded geometry and a bounded
dirty-region conductance maintained by the partitioner, inter-flush spacing is
Omega(T / D) edits and amortized per-edit cost is O(1). The whole of the
adversarial risk then concentrates into a single named quantity, the separator
fill factor at flush time, which is measurable and which the partitioner can be
required to bound. Converting "conjectured unconditional bound" into "proven
conditional bound plus the exact condition" is the honest result, and it is
strictly stronger than "measured on benign streams."

## Model and assumptions

(A1) Bounded geometry. The graph has maximum degree D and every stalk has
dimension at most s, with D and s constant. Consequently a single edit (an edge
insertion, deletion, or relabel) directly touches at most O(D) cells, each of
bounded dimension.

(A2) Deferred assembly. The engine does not propagate an edit's consequences
immediately. An edit marks local cells dirty and defers recomputation to
flush time. In the deployed engine the deferred work is the per-cell local
H^1 proxy recompute. In the modeled architecture analyzed here, the deferred
work is global re-gluing (Mayer-Vietoris assembly). Either way, the per-edit
cost question and the flush-cost question are genuinely separate, which is
the architectural choice the framework rests on.

(A3) Lazy flush policy (modeled, not implemented). A flush is triggered only
when one of two conditions holds: the accumulated debt reaches a threshold T,
or the dirty region's boundary-to-volume ratio approaches a conductance
ceiling beta from below. The second trigger fires slightly before beta is
crossed, not after. The reason for the "slightly before" is made precise in
Lemma 2. The deployed engine implements no trigger at all; flush_dirty_cells
runs when the caller invokes it. This assumption specifies the policy the
modeled architecture would need.

## The potential

Define the consistency debt at time t as

  Phi_t = number of cells on the boundary between the dirty region and the
          clean region that are pending re-gluing.

This is the right potential for the modeled architecture because it is
exactly the quantity that makes an assembly flush expensive. In that
architecture, flush cost is dominated by resolving this dirty boundary (the
separator) via Mayer-Vietoris assembly, not by the interior of the dirty
region, which is re-glued locally. A flush resets Phi to O(1) (a bounded
residual at the new clean boundary). In the deployed engine, by contrast,
flush cost is |dirty| times a constant per-cell eigensolve and does not
depend on Phi's boundary structure at all.

## Lemma 1 (bounded per-edit increment, easy)

For every edit, Phi_{t+1} <= Phi_t + b, where b = O(D).

Proof sketch. By (A1) an edit directly touches at most O(D) cells. By (A2) the
edit does not propagate; it only marks those touched cells dirty and updates the
dirty boundary by at most the cells it touched. So the dirty boundary grows by
at most O(D) per edit. The deferral in (A2) is what makes this trivial: there is
no propagation term because propagation is exactly what is postponed to flush.

This lemma is where deferred assembly pays off. In an eager architecture the
increment would carry a propagation term and could be unbounded; deferral moves
that cost entirely to flush time, which is what Lemma 2 has to control.

## Lemma 2 (flush cost linear in debt, load-bearing)

Let R be the dirty region flushed, with dirty boundary (separator) of size
Phi = |bd(R)|. The flush cost is O(Phi * f), where f is the fill factor of the
separator under sparse elimination. If the separator has bounded conductance,
equivalently bounded treewidth or bounded fill, then f = O(1) and the flush cost
is O(Phi).

Why this is load-bearing. Mayer-Vietoris assembly over a separator is a Schur
complement (block elimination) over that separator. For a separator of size
Phi, dense elimination costs O(Phi^3); sparse elimination costs O(Phi * f),
where f measures fill-in during elimination. Bounded conductance of the dirty
region implies small balanced separators (bounded treewidth of the boundary),
which implies bounded fill, which gives f = O(1) and flush cost O(Phi). High
conductance (an expander-like dirty region, no sparse cut) drives f toward Phi,
flush cost toward Phi^2 or worse, and the linear-cost claim fails.

This is precisely why (A3) flushes slightly before the conductance ceiling
beta. If the engine waited until conductance exceeded beta, f would already have
blown up and the flush it is about to perform would itself be superlinear.
Flushing at the beta boundary keeps f bounded for the flush that clears the
region. This lemma is not free; it is the place where the entire adversarial
risk lives, and the section "What remains to be proven" says what it would take
to make it airtight.

Scope. This cost model describes Mayer-Vietoris assembly, concretely the
rho-rank SVDs over boundary stalks in compute_recursive_mv, whose matrix
sizes grow with separator size. It does not describe the deployed per-cell
flush, which has no separator solve and whose cost is independent of
boundary structure (measured 2026-06-10).

## Lemma 3 (spacing from accounting)

Between two consecutive flushes, Phi starts at O(1) and a flush is not triggered
until Phi >= T (debt trigger) or until the conductance trigger fires. Consider
each trigger.

Debt trigger. By Lemma 1, Phi grows by at most b = O(D) per edit. To reach
Phi >= T therefore requires at least (T - O(1)) / b = Omega(T / D) edits. So
consecutive debt-triggered flushes are at least Omega(T / D) edits apart.

Conductance trigger. To drive a dirty region of size m to the conductance
boundary beta, the adversary must raise its dirty boundary by a fixed fraction
of m. Each edit raises the dirty boundary by at most O(D) (Lemma 1), so this
takes Omega(m / D) edits. So consecutive conductance-triggered flushes of a
size-m region are at least Omega(m / D) edits apart.

## Theorem (conditional amortized bound)

Under (A1), (A2), (A3), and the bounded-fill conclusion of Lemma 2, the
amortized per-edit cost is O(D * f) = O(1).

Proof. Charge each flush to the edits since the previous flush.

Debt-triggered flush: clears debt Theta(T), costs O(T * f) by Lemma 2, and is
preceded by Omega(T / D) edits by Lemma 3. Amortized over those edits:
O(T * f) / Omega(T / D) = O(D * f).

Conductance-triggered flush: clears a region of size m at the beta boundary
where f is still bounded, costs O(m * f) by Lemma 2, and is preceded by
Omega(m / D) edits by Lemma 3. Amortized: O(m * f) / Omega(m / D) = O(D * f).

In both cases the amortized cost is O(D * f). Under (A1), D is constant. Under
the Lemma 2 conductance condition, f is constant. Therefore amortized per-edit
cost is O(1). The adversary cannot beat this without either making a single edit
touch more than O(D) cells (violating A1) or driving the flushed region's fill
above bounded (violating the Lemma 2 condition).

## Where the adversary can and cannot attack

Cannot: the adversary cannot win by spacing edits cleverly, by choosing which
cells to dirty, or by alternating regions. Lemma 1 caps the per-edit increment
regardless of edit choice, and the lazy policy (A3) guarantees every
debt-triggered flush clears Theta(T) debt, so the adversary cannot manufacture
frequent cheap-to-trigger but expensive-to-execute flushes.

Can: the adversary's single remaining lever is to drive a dirty region toward
high conductance faster than the partitioner can flush it at the beta boundary,
so that the flush the engine is forced to perform has already blown up f. This
is the entire residual risk. It is not hidden; it is one measurable quantity.

## What remains to be proven

1. The fill bound in Lemma 2 has to be tied to a concrete, enforceable property
   of the partitioner. The clean target is: the partitioner guarantees that
   every dirty region it allows to accumulate has separator treewidth at most w
   for a constant w, which gives f = O(w) and closes the theorem unconditionally
   relative to that guarantee. This shifts the open problem from "bound flushes"
   to "prove the partitioner maintains bounded-treewidth dirty separators under
   adversarial edits," which is a sharper and more standard dynamic-graph
   question.

2. The conductance trigger in (A3) must be shown to be computable incrementally
   and cheaply, otherwise the trigger itself reintroduces global cost. A bounded
   incremental estimator of dirty-region conductance (a boundary-to-volume
   counter updated per edit) is the likely route, and its own update cost has to
   be folded into the O(D * f) accounting.

3. The "slightly before beta" margin in (A3) needs a quantitative form: how far
   below beta must the trigger fire so that the flush completes before f
   degrades. This is a one-parameter calculation once the fill-versus-conductance
   relationship for the actual separator structure is pinned down.

None of these is open-ended. Each reduces to a specific dynamic-graph or
numerical-linear-algebra statement about the existing partitioner and restriction
store.

## Empirical support and its limits

Two measurements exist as of 2026-06-10.

First, the V=5M benign benchmark: per-edit median 35 microseconds with
sub-linear scaling, zero proxy drift (lazy flush equals full proxy
recompute), RestrictionStore steady at 0.50 MB. An earlier draft of this
document cited the bounded RestrictionStore footprint as evidence that
separator fill f stays small. That inference was wrong and is withdrawn: the
RestrictionStore is a content-addressed dedup cache for restriction
matrices, and its size measures the number of unique maps, not elimination
fill. It says nothing about Lemma 2.

Second, the adversarial conductance probe (2026-06-10, V=21K Enron, 2000
cross-cell-maximizing edits): the per-edit hot path held under adversarial
pressure (median around 11 microseconds, p99 29 microseconds, zero errors),
and deployed flush time was insensitive to dirty-region conductance,
tracking dirty-cell count instead (the benign stream dirtied 124 of 609
cells, the adversarial stream 607, with nearly identical boundary cut).
This is the expected result given the scope correction above: the deployed
flush has no separator term to stress. It is NOT evidence about Lemma 2.

The experiment that would test Lemma 2 directly must target the MV assembly
path: drive compute_recursive_mv over dirty regions of equal size but
different boundary structure (compact versus expander-like) and measure the
rho-SVD cost against separator size. That experiment, plus item 1 above, is
what converts this conditional bound into the load-bearing theorem the
framework needs. The prior question of how often true assembly must run
versus trusting the per-cell proxy was answered on 2026-06-10 in an
unexpected way: the proxy and exact H^1 are different invariants, not
approximations of one another (Enron 21K: proxy 380, within-cell exact
263,107, cycle-rank dominated). Assembly is therefore not a more accurate
version of the flush; it computes a different quantity, and the operative
question becomes which invariant the verification layer actually needs.
See patent/validation/claim_8/proxy_true_gap/FINDINGS.md.
