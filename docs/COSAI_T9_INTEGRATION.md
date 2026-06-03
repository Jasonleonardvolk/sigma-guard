# Implementation Note: SVR Receipt Verification at the T4/T9 Trust Boundary

## Where in the call path does receipt verification happen?

The cosai-mcp CoSAIStack enforces checks at three points:

```
[startup]
  check_manifest()       T4 tool poisoning, T11 supply chain

[per request]
  check_tool_call()      T3 validation -> T2 authz -> T7 session -> T12 audit

[after tool returns]
  check_response()       T4/T9 injection detection
                         ^^^ SVR verification inserts HERE
```

The T4/T9 trust boundary is `check_response()`. This is the moment
between "tool produced output" and "output is chained downstream."

The existing check runs `ResponseBoundaryGuard`
(`cosai_mcp/middleware/boundary.py`): regex-based injection pattern
scanning (prompt overrides, system tokens, exfiltration markers). It
flags injection attempts; it does not sanitize content or strip
control characters. (cosai-mcp provides a separate
`LLMOutputSanitizer` in `trust.py` for character-level sanitization,
but that class is not wired into `check_response()`.)

SVR adds claim-level verification: are the assertions in the output
structurally consistent?

## Two sides: produce and consume

### Produce side (the MCP server that issues receipts)

An MCP server wraps sigma-guard as a verification step before returning
tool output. The flow:

```
Client calls tool
  -> Tool generates output
  -> sigma-guard.verify_claims(output)
  -> Engine returns SVR receipt (signed JSON)
  -> Server returns output + receipt to client
```

The server adds the receipt to its response. Two options for wire format:

**Option A: receipt in response metadata**
```json
{
  "content": [{"type": "text", "text": "...tool output..."}],
  "_meta": {
    "svr_receipt": { ... receipt JSON ... }
  }
}
```

**Option B: receipt as separate resource**
The server exposes a `get_receipt` tool that returns the receipt for
a given verification run, referenced by receipt_id.

Option A is simpler for chained verification. The receipt travels with
the output.

### Consume side (the downstream agent or orchestrator)

Before chaining the upstream output into the next tool call or LLM
context, the consumer verifies the receipt:

```
Receive output + receipt
  -> SVRTrustGate.verify_before_chain(receipt, tool_output)
  -> Check 1: structure valid (required fields present)
  -> Check 2: signature valid (Ed25519, using issuer's public key)
  -> Check 3: input_hash matches SHA-256(tool_output)
  -> Check 4: safe_to_rely == True
  -> All pass: chain continues
  -> Any fail: quarantine, reject, or flag for human review
```

The consumer needs only `svr-verify` (MIT, 1 dependency). It does
not need the sigma-guard engine. Verification is a local cryptographic
check.

## Integration with CoSAIStack

The integration adds an optional `svr_gate` parameter to CoSAIStack:

```python
from cosai_mcp.middleware import CoSAIStack
from cosai_svr_gate import SVRTrustGate

stack = CoSAIStack(
    audit_logger=AuditLogger("/var/log/cosai/audit.jsonl"),
    # ... existing middleware ...
)

# Add SVR gate to the check_response path
gate = SVRTrustGate(
    pubkey_hex="<issuer-public-key>",
    require_safe_verdict=True,
    require_input_hash_match=True,
)
```

The modified check_response flow:

```
check_response(body, session_id, receipt)
  1. ResponseBoundaryGuard.check(body)       # existing: injection patterns
  2. SVRTrustGate.verify_before_chain(       # new: structural verification
         receipt, tool_output=body
     )
  3. If SVR gate fails:
       - Log to AuditLogger (T12) with receipt_id, verdict, reason
       - Return SVRGateResult(safe=False, ...)
       - Caller decides: quarantine, reject, or flag
  4. If SVR gate passes:
       - Receipt is valid evidence of verification
       - Chain continues
       - Receipt travels with output to next consumer
```

Note: check_response() does not raise exceptions. It logs findings
and returns. The caller decides how to handle a flagged result. The
SVR gate follows this same pattern: it returns an SVRGateResult
rather than raising, preserving the existing non-blocking contract.

## Conformance test: "receipt validates before chain continues"

The falsifiable test Rags requested. Five assertions:

| Test | Input | Expected |
|---|---|---|
| Valid receipt | Correct structure, correct hash, safe_to_rely=True | Gate passes, chain continues |
| Tampered receipt | Missing required fields | Gate blocks, chain stops |
| Wrong input hash | Receipt hash does not match tool output | Gate blocks, chain stops |
| Unsafe verdict | safe_to_rely=False | Gate blocks, chain stops |
| Empty receipt | No fields at all | Gate blocks, chain stops |

Running the conformance test:

```
python examples/cosai_svr_gate.py
```

Output:
```
valid_receipt_passes: PASS
tampered_receipt_blocked: PASS
wrong_hash_blocked: PASS
unsafe_verdict_blocked: PASS
empty_receipt_blocked: PASS
conformance: PASS
```

This test uses no network, no engine, and no ML. It verifies the
gate logic: does the trust boundary enforce receipt validity before
allowing chain continuation?

For scanner-side conformance (cosai-mcp black-box probe), a T9
probe could:

1. Call a target MCP server's tool
2. Check if the response includes an SVR receipt (in `_meta` or
   as a separate field)
3. If yes: verify the receipt with svr-verify
4. If no: report T4/T9 finding "no verification receipt on output"

This maps to the existing T4/T9 coverage model: passive detection
(does the server produce receipts?) plus middleware enforcement
(does the pipeline reject unchained output?).

## How SVR receipts complement the existing T12 audit chain

cosai-mcp's AuditLogger produces hash-chained entries with
params_digest (SHA-256 of call parameters). SVR receipts add a
second evidence layer:

| Audit artifact | What it proves | Tamper evidence |
|---|---|---|
| AuditLogger entry | This call happened at this time with these params | SHA-256 hash chain |
| SVR receipt | This output was structurally verified with this result | Ed25519 signature |

The two are complementary. The audit chain proves the call happened.
The SVR receipt proves the output was verified. Together they
provide end-to-end forensic evidence from invocation to verification.

An AuditLogger entry for an SVR-gated response would include
the receipt_id as a cross-reference:

```json
{
  "entry_id": "...",
  "method": "check_response:svr_gate",
  "params_digest": "sha256(receipt_id + verdict + safe)",
  "chain_hash": "..."
}
```

## Threat categories addressed

| CoSAI Category | How SVR contributes |
|---|---|
| T6 (Integrity/Verification) | Receipt is a signed integrity artifact |
| T9 (Trust Boundary) | Gate enforces "verify before chain" at the trust boundary. This is the deterministic verification gate absent in the PocketOS compound failure (T2+T9+T12; see THREAT_CATALOG.md "Compound Threat Patterns"). |
| T12 (Logging/Auditability) | Receipt is independently verifiable audit evidence |

## Claim boundaries

SVR receipts verify structural consistency of represented claims.
They do not replace:

- T1 (Authentication): SVR does not authenticate MCP clients
- T2 (Access Control): SVR does not enforce RBAC
- T3 (Input Validation): SVR does not sanitize inputs
- T4 (Data/Control Boundary): SVR does not detect prompt injection
- T5 (Data Protection): SVR does not encrypt data in transit
- ResponseBoundaryGuard injection scanning: SVR does not replace
  the existing regex-based injection detection in check_response()

SVR is additive. It fills the gap between "output has no injection
patterns" (existing T4/T9 via ResponseBoundaryGuard) and "output is
structurally consistent claim-by-claim" (SVR).

## Shared Ed25519 key infrastructure

cosai-mcp uses Ed25519 for three signing operations:

- Catalog signing (`cosai_mcp/signing.py`): signs threat definition JSON files
- Scorecard signing (`cosai_mcp/scorecard/signing.py`): signs scan result scorecards
- Inventory signing (`cosai_mcp/inventory/signing.py`): signs tool inventory snapshots

All three use the same key management pattern:

- Deterministic seed derivation from a 32-byte seed
- Per-installation keyring storage via the `keyring` package
- Environment variable override for fleet/CI deployment
  (`COSAI_SIGNING_SEED`, `COSAI_SIGNING_KEY_FILE`)

SVR receipts use the same Ed25519 primitive (`pynacl` / `cryptography`
library). An SVR-producing MCP server can reuse the existing
cosai-mcp key infrastructure:

```
# Same seed signs catalog, scorecards, inventories, AND SVR receipts
export COSAI_SIGNING_SEED="<base64-encoded-32-byte-seed>"
```

This means zero additional key management for anyone already
running cosai-mcp. No new secrets to distribute. No new key
rotation procedures. The consuming side (`svr-verify`) accepts
any Ed25519 public key, so it works with cosai-mcp's existing
key distribution.

## Files

- Integration code: `examples/cosai_svr_gate.py`
- Receipt format and proof shape: `README.md` ("Proof receipt shape")
- Receipt verifier: `pip install svr-verify` (MIT)
- Sample receipt: `docs/SVR_RECEIPT_EXAMPLE.json`
- Verification quickstart: `docs/SVR_VERIFY_QUICKSTART.md`

## Contact

Jason Volk / sigma-guard / SVR
jason@invariant.pro
https://invariant.pro
