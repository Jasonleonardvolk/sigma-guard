# NSA MCP Security Guidance: Implementation Alignment

## sigma-guard / SVR as a Verification Pattern for MCP Output Pipelines

**Date:** June 2, 2026
**Author:** Jason Volk / sigma-guard project
**Contact:** jason@invariant.pro
**Affiliation:** Independent / Invariant Research

This document does not claim NSA endorsement, certification, approval,
or recommendation. It is an implementation-oriented technical response
mapping public NSA guidance to a working MCP verification pattern.

---

## 1. Problem Identified by NSA and CoSAI

The NSA Cybersecurity Information Sheet "Model Context Protocol (MCP):
Security Design Considerations for AI-Driven Automation"
(U/OO/6030316-26, May 20, 2026) identifies a structural problem in
MCP deployments: agent outputs are consumed by downstream systems
without independent verification.

The guidance names three risk categories:

- **Dynamic tool invocation:** agents call tools at runtime without
  verifying the tool's output is structurally sound.
- **Implicit trust:** one agent's output is assumed valid by another
  without explicit verification.
- **Context misalignment:** long-lived or overlapping context windows
  can produce outputs that are internally inconsistent.

The CSI recommends (page 12) extending MCP with cryptographic
signatures directly within the JSON payload and cryptographically
binding requests to time and context to prevent tampering, intentional
replay techniques, and unintended re-execution.

The CoSAI MCP security white paper reinforces the same direction
through MCP-T6, "Missing Integrity/Verification Controls," which
identifies the absence of cryptographic integrity verification for
message authenticity, configuration immutability, behavioral
attestation, reproducible builds, and tamper-evident logging as a
core MCP threat class.

---

## 2. What sigma-guard / SVR Contributes

sigma-guard is a deterministic structural verification engine exposed
as an MCP server (FastMCP, Streamable HTTP transport). It verifies
whether a set of claims, relationships, or constraints is internally
consistent by computing the first sheaf cohomology group (H^1) of a
cellular sheaf built from the input. A non-trivial H^1 class is a
structural contradiction: a set of local assertions that cannot be
made globally consistent.

**Key properties:**

- **Zero learned parameters.** The verification is deterministic: the
  same input always produces the same result. No model, no training
  data, no GPU, no probabilistic output.

- **Microsecond per-edit cost.** Incremental updates run at 35
  microseconds median per edit at 5,000,000 vertices on a single CPU
  core.

- **Cryptographically signed receipts.** Every verification result is
  packaged as an SVR (Structural Verification Receipt) in JSON format,
  signed with Ed25519. The receipt binds the verification result to the
  input hash, graph hash, decomposition hash, engine version, timestamp,
  replay seed, and configuration. The signature is independently
  verifiable with a public key and the open-source svr-verify tool.

- **IANA media type (pending).** The SVR format uses the proposed media
  type `application/vnd.svr.receipt+json`. Registration was submitted
  on May 18, 2026 and should be described as pending until formally
  accepted.

- **MCP-native.** sigma-guard runs as an MCP server. Any MCP client
  can call it to verify agent outputs before downstream reliance.

**Packages:**

- `sigma-guard` (v0.3.1, BSL-1.1): MCP verification server and
  structural verification engine. The standards-facing contribution
  is the receipt format, canonicalization rules, verification semantics,
  and reference validation workflow. Production-scale engine licensing
  is separate from the open specification contribution.
- `svr-verify` (MIT): Standalone receipt verifier. Single dependency
  (pynacl, Apache-2.0).

---

## 3. NSA Requirement Mapping

### 3.1 Cryptographic signatures in JSON payloads (page 12)

**NSA:** Recommends extending MCP with cryptographic signatures
directly within the JSON payload.

**sigma-guard:** Every SVR receipt is a JSON document containing an
Ed25519 signature over the canonical JSON representation of the
verification result. The signature field is part of the payload, not a
transport-layer wrapper. Any recipient with the public key can verify
the receipt without contacting the issuing server.

### 3.2 Binding requests to time and context (page 12)

**NSA:** Recommends cryptographically binding requests to time and
context to prevent tampering, replay, and unintended re-execution.

**sigma-guard:** The signed payload includes the timestamp, the input
hash (SHA-256 of the source material), the graph hash (SHA-256 of the
constructed knowledge graph), the decomposition hash (SHA-256 of the
cellular decomposition), the engine version, and the replay seed.
Tampered receipts fail signature verification; replayed receipts can
be rejected by freshness, context, and hash-binding policy. The
binding is end-to-end: from the source document through the graph
construction through the cohomology computation to the signed output.

### 3.3 Implicit trust between agents (pages 5-6)

**NSA:** Identifies implicit trust relationships where one agent's
output is assumed valid by another without explicit verification.

**sigma-guard:** The verification layer sits between agent output and
downstream reliance. The agent proposes; the sheaf verifies. The
receipt is the evidence that verification occurred, what was verified,
and what the result was. Downstream systems check the receipt (and its
signature) rather than trusting the upstream agent's claim.

### 3.4 Output filtering and verification (page 11)

**NSA:** Recommends filtering outgoing proxy and output filtering for
MCP connections.

**sigma-guard:** Functions as a verification filter in the MCP pipeline.
An orchestrator calls sigma-guard before passing agent output to
downstream tools or storage. If H^1 > 0 (structural contradiction
detected), the receipt reports the contradiction with severity and the
specific conflicting claims.

### 3.5 Idempotency and determinism (page 9)

**NSA:** Notes that idempotency is not directly enforced by MCP and is
left to the underlying JSON-RPC and message queue.

**sigma-guard:** Deterministic by construction at the
verification-result layer. The same input graph, restriction maps,
engine version, and configuration produce the same structural
verification result. Fresh receipt issuance may produce a different
receipt_id, timestamp, replay metadata, receipt hash, and signature,
but the signed receipt binds those issuance fields to the deterministic
verification result. This separates deterministic verification from
auditable receipt issuance.

### 3.6 Data classification zones (page 11)

**NSA:** Recommends aligning tools and models with data classification
zones.

**sigma-guard:** The verification server can support data-minimization
architectures because it can operate on structural relationships, graph
topology, and constraint maps rather than full source documents. This
does not automatically downgrade classification: graph structure can
still encode sensitive relationships. The operational claim is narrower
and safer: SVR allows deployments to separate source-content handling
from structural verification, while preserving hashes and receipt
evidence that bind the verification result back to the original input
state.

### 3.7 Summary Mapping

| NSA / CoSAI Concern | sigma-guard / SVR Response |
|---|---|
| Message authenticity and integrity | Signed JSON SVR receipt |
| Replay and unintended re-execution | Timestamp, replay metadata, context binding |
| Implicit trust across agent chains | Verification before downstream reliance |
| Poor or missing audit logs | Receipt ledger with input/result hashes |
| Missing integrity/verification controls | Hash-bound verification artifact |
| Output pipeline risk | MCP verification filter before action |
| Non-deterministic model behavior | Deterministic structural verification layer |
| Forensic response | Independently verifiable receipt evidence |

---

## 4. CoSAI MCP-T6 Alignment

CoSAI WS4 (Secure Design Patterns for Agentic Systems) published
principles for secure-by-design agentic systems. sigma-guard aligns
with the following:

- **MCP-T6 (Missing Integrity/Verification Controls):** SVR receipts
  are Ed25519-signed artifacts with full hash chains from input to
  output, providing the cryptographic integrity verification MCP-T6
  identifies as absent.

- **Signed artifacts:** Every verification result is a signed artifact
  in a proposed media type, independently verifiable with open-source
  tooling.

- **Verification before deployment:** sigma-guard is designed to run
  before downstream reliance, not after. The verification step is
  pre-commitment, not post-hoc audit.

- **Open specification candidate:** The SVR format is documented in
  SVR_SPEC_v1.txt, the IANA media type registration is pending, and
  the receipt verifier is available as open-source tooling.

---

## 5. Exact Claim Boundaries

sigma-guard addresses structural consistency of represented
relationships. It does not address:

- **Transport-layer security** (TLS, mTLS). sigma-guard operates at
  the application layer.
- **Authentication and authorization.** sigma-guard does not
  authenticate MCP clients.
- **Sandboxing and isolation.** sigma-guard does not sandbox other
  MCP servers. It verifies outputs, not execution environments.
- **Prompt injection detection.** sigma-guard detects structural
  inconsistency in represented claims, not adversarial prompt content.
- **Extraction quality.** The verification is only as good as the
  knowledge graph construction.

These boundaries are stated because a verification tool that
overstates its coverage is worse than no verification tool at all.

---

## 6. Reproduction Path

```
pip install sigma-guard
pip install svr-verify
```

Run the MCP server:

```
sigma-guard-mcp
sigma-guard-mcp --transport streamable-http --port 8401
```

Benchmarks:
- 35 microseconds median per edit at 5,000,000 vertices (single core)
- 63 microseconds at 1,000,000 vertices (sublinear scaling)
- Zero drift between incremental and batch computation
- Deterministic output across runs

---

## 7. Sample Receipt and Verification

See [SVR_RECEIPT_EXAMPLE.json](SVR_RECEIPT_EXAMPLE.json) for a
complete sample receipt.

See [SVR_VERIFY_QUICKSTART.md](SVR_VERIFY_QUICKSTART.md) for
step-by-step verification instructions.

Verify any SVR receipt:

```
pip install svr-verify
svr-verify receipt.svr.json
```

Output: `VALID` or `INVALID`. No account, no API key, no internet
connection after install.

---

## 8. How to Contribute / Discuss

- **Technical questions:** jason@invariant.pro
- **Source code:** https://github.com/Jasonleonardvolk/sigma-guard
- **PyPI (engine):** https://pypi.org/project/sigma-guard/
- **PyPI (verifier):** https://pypi.org/project/svr-verify/
- **Project site:** https://invariant.pro

Mathematical foundation:
- "Sheaf-Guarded Updates: Streaming Structural Verification for
  Evolving Agent State" (under review, 2026)
- "Incremental Sheaf Cohomology on Cellular Complexes" (preprint)

This document is offered as a technical contribution to the
conversation the NSA CSI and CoSAI WS4 have opened.

---

## 9. Non-Endorsement and License Notes

This document does not claim or imply endorsement, certification,
approval, recommendation, or favoring by the National Security Agency,
the United States Government, OASIS, CoSAI, or any other organization
referenced herein.

References to NSA guidance are citations to a publicly available
Cybersecurity Information Sheet. References to CoSAI materials are
citations to publicly available working-group documents.

- `sigma-guard` (BSL-1.1): MCP verification server and engine. The
  standards-facing contribution is the SVR receipt format,
  canonicalization rules, verification semantics, and reference
  validation workflow. Production-scale engine licensing is separate.
- `svr-verify` (MIT): Standalone receipt verification.
- `SVR_SPEC_v1.txt`: Receipt format specification, offered for
  community review and adoption.
