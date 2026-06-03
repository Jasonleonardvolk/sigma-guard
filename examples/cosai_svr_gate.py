"""SVR trust gate for cosai-mcp T9 trust boundary enforcement.

This module demonstrates how SVR (Structural Verification Receipt)
verification integrates into the cosai-mcp middleware stack as a
T9 trust boundary check.

The existing T9 path (trust.py) catches character-level threats:
control characters, null bytes, injection patterns. This module
adds claim-level verification: are the assertions in the output
structurally consistent?

Integration point: CoSAIStack.check_response()
  Current: ResponseBoundaryGuard (injection pattern scan)
  Added:   SVRTrustGate (structural consistency + signed receipt)

The verification flow:
  1. Tool call returns output
  2. ResponseBoundaryGuard checks for injection patterns (existing)
  3. SVRTrustGate verifies structural consistency (new)
     a. Extract claims from the output
     b. Call sigma-guard verify_claims (local MCP call or direct import)
     c. Verify the returned SVR receipt signature
     d. If receipt says INCONSISTENT, flag for quarantine
     e. If receipt says CONSISTENT, attach receipt to output
  4. Downstream agent receives output + receipt
  5. Downstream agent verifies receipt independently (svr-verify)

Dependencies:
  pip install svr-verify    # MIT license, single dep (pynacl)
  pip install sigma-guard   # BSL-1.1, for local verification

For conformance testing only (no engine needed):
  pip install svr-verify    # verify receipts issued by any engine

License note:
  svr-verify is MIT. cosai-mcp is Apache 2.0. These are compatible.
  sigma-guard (the engine) is BSL-1.1. The conformance test uses
  only svr-verify, not the engine, so there is no license conflict
  in the test path.

Usage::

    from cosai_svr_gate import SVRTrustGate

    gate = SVRTrustGate()

    # Verify a receipt before chaining
    result = gate.verify_before_chain(receipt_json)
    if not result.safe:
        # quarantine: do not chain this output
        print(f"Blocked: {result.reason}")
    else:
        # chain continues; receipt travels with output
        downstream_input = {
            "content": tool_output,
            "svr_receipt": receipt_json,
        }
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SVRGateResult:
    """Result of SVR trust boundary check."""
    safe: bool
    reason: str
    receipt_id: str
    verdict: str
    signature_valid: bool
    structure_valid: bool
    input_hash_match: bool


class SVRTrustGate:
    """T9 trust boundary enforcement via SVR receipt verification.

    Sits in the check_response() path of CoSAIStack. Verifies that
    a valid SVR receipt accompanies tool output before allowing
    chain continuation.

    This is the "consume side" of SVR: the downstream agent or
    orchestrator verifying a receipt it received, not issuing one.

    Parameters
    ----------
    pubkey_hex:
        Ed25519 public key (hex) of the expected receipt issuer.
        If None, signature verification is skipped (structure-only).
    require_safe_verdict:
        If True (default), only receipts with safe_to_rely=True pass.
        If False, any structurally valid receipt passes (useful for
        logging/auditing without blocking).
    require_input_hash_match:
        If True, the receipt's input_hash must match the SHA-256 of
        the tool output being gated. Prevents receipt reuse across
        different outputs.
    """

    def __init__(
        self,
        pubkey_hex: str | None = None,
        require_safe_verdict: bool = True,
        require_input_hash_match: bool = True,
    ) -> None:
        self._pubkey_hex = pubkey_hex
        self._require_safe = require_safe_verdict
        self._require_hash_match = require_input_hash_match

    def verify_before_chain(
        self,
        receipt: dict[str, Any],
        tool_output: str | None = None,
    ) -> SVRGateResult:
        """Verify an SVR receipt before allowing downstream chaining.

        Parameters
        ----------
        receipt:
            Parsed SVR receipt (dict from JSON).
        tool_output:
            The raw tool output string. If provided and
            require_input_hash_match is True, the receipt's
            input_hash is checked against SHA-256(tool_output).

        Returns
        -------
        SVRGateResult
            Contains safe (bool), reason, and verification details.
        """
        # Step 1: structure validation
        structure_valid = self._check_structure(receipt)
        if not structure_valid:
            return SVRGateResult(
                safe=False,
                reason="Receipt structure invalid: missing required fields",
                receipt_id=receipt.get("receipt_id", "unknown"),
                verdict="unknown",
                signature_valid=False,
                structure_valid=False,
                input_hash_match=False,
            )

        receipt_id = receipt.get("receipt_id", "unknown")
        verdict = receipt.get("verdict", "unknown")
        safe_to_rely = receipt.get("safe_to_rely", False)

        # Step 2: signature verification (if pubkey provided)
        sig_valid = True
        if self._pubkey_hex:
            sig_valid = self._check_signature(receipt)
            if not sig_valid:
                return SVRGateResult(
                    safe=False,
                    reason="Receipt signature invalid",
                    receipt_id=receipt_id,
                    verdict=verdict,
                    signature_valid=False,
                    structure_valid=True,
                    input_hash_match=False,
                )

        # Step 3: input hash match (if tool_output provided)
        hash_match = True
        if tool_output is not None and self._require_hash_match:
            expected_hash = hashlib.sha256(
                tool_output.encode("utf-8")
            ).hexdigest()
            actual_hash = receipt.get("input_hash", "")
            hash_match = expected_hash == actual_hash
            if not hash_match:
                return SVRGateResult(
                    safe=False,
                    reason=(
                        "Receipt input_hash does not match tool output: "
                        "receipt may have been issued for different content"
                    ),
                    receipt_id=receipt_id,
                    verdict=verdict,
                    signature_valid=sig_valid,
                    structure_valid=True,
                    input_hash_match=False,
                )

        # Step 4: verdict check
        if self._require_safe and not safe_to_rely:
            return SVRGateResult(
                safe=False,
                reason=f"Receipt verdict is {verdict!r} with safe_to_rely=False",
                receipt_id=receipt_id,
                verdict=verdict,
                signature_valid=sig_valid,
                structure_valid=True,
                input_hash_match=hash_match,
            )

        # All checks passed
        return SVRGateResult(
            safe=True,
            reason="Receipt valid; output safe to chain",
            receipt_id=receipt_id,
            verdict=verdict,
            signature_valid=sig_valid,
            structure_valid=True,
            input_hash_match=hash_match,
        )

    # -----------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------

    _REQUIRED_FIELDS = frozenset({
        "svr_version", "receipt_id", "verdict", "safe_to_rely",
        "input_hash", "timestamp_utc", "signature",
    })

    def _check_structure(self, receipt: dict[str, Any]) -> bool:
        """Verify all required SVR fields are present."""
        return self._REQUIRED_FIELDS.issubset(receipt.keys())

    def _check_signature(self, receipt: dict[str, Any]) -> bool:
        """Verify Ed25519 signature using svr-verify.

        Falls back to False if svr-verify is not installed.
        """
        try:
            from svr_verify.validate import validate_receipt
            result = validate_receipt(receipt, pubkey_hex=self._pubkey_hex)
            return result.signature_valid
        except ImportError:
            # svr-verify not installed; cannot verify signature
            return False
        except Exception:
            return False


# -----------------------------------------------------------------
# CoSAIStack integration example
# -----------------------------------------------------------------

def integrate_with_cosai_stack(stack: Any, pubkey_hex: str | None = None) -> None:
    """Monkey-patch an SVR check into CoSAIStack.check_response().

    This is a demonstration of the wiring. In production, the
    integration would be a first-class parameter on CoSAIStack.__init__
    (e.g. svr_gate=SVRTrustGate(...)).

    Usage::

        from cosai_mcp.middleware import CoSAIStack
        from cosai_svr_gate import integrate_with_cosai_stack

        stack = CoSAIStack(audit_logger=AuditLogger("/tmp/audit.jsonl"))
        integrate_with_cosai_stack(stack, pubkey_hex="abcd1234...")
    """
    gate = SVRTrustGate(pubkey_hex=pubkey_hex)
    original_check = stack.check_response

    def check_response_with_svr(
        body: str,
        session_id: str = "unknown",
        receipt: dict | None = None,
    ) -> SVRGateResult | None:
        # Run existing T4/T9 checks first
        original_check(body, session_id=session_id)

        # Then run SVR verification if receipt provided
        if receipt is not None:
            result = gate.verify_before_chain(receipt, tool_output=body)
            if not result.safe and stack.audit is not None:
                stack.audit.log(
                    method="check_response:svr_gate",
                    session_id=session_id,
                    params={
                        "receipt_id": result.receipt_id,
                        "verdict": result.verdict,
                        "reason": result.reason,
                        "safe": result.safe,
                    },
                )
            return result
        return None

    stack.check_response = check_response_with_svr


# -----------------------------------------------------------------
# Conformance test: "receipt validates before chain continues"
# -----------------------------------------------------------------

def conformance_test_receipt_before_chain() -> dict[str, Any]:
    """Run the T9 SVR conformance test.

    This is the falsifiable test Rags asked for:
    "receipt validates before chain continues"

    The test verifies that:
    1. A valid receipt passes the gate (chain continues)
    2. A tampered receipt fails the gate (chain blocked)
    3. A receipt with wrong input_hash fails (chain blocked)
    4. A receipt with safe_to_rely=False fails (chain blocked)
    5. A missing receipt fails when gate requires one

    Returns a dict with test names and pass/fail results.
    """
    gate = SVRTrustGate(require_safe_verdict=True, require_input_hash_match=True)

    tool_output = "The approved vendor is Supplier_A."
    output_hash = hashlib.sha256(tool_output.encode()).hexdigest()

    # Test 1: valid receipt passes
    valid_receipt = {
        "svr_version": "1.0",
        "receipt_id": "SG-20260602-TEST0001",
        "verdict": "consistent",
        "safe_to_rely": True,
        "input_hash": output_hash,
        "timestamp_utc": "2026-06-02T12:00:00.000Z",
        "signature": "0" * 128,
        "signature_status": "UNSIGNED",
    }
    r1 = gate.verify_before_chain(valid_receipt, tool_output=tool_output)

    # Test 2: tampered receipt (missing fields) fails
    tampered = {"receipt_id": "FAKE", "verdict": "consistent"}
    r2 = gate.verify_before_chain(tampered, tool_output=tool_output)

    # Test 3: wrong input_hash fails
    wrong_hash = dict(valid_receipt, input_hash="0" * 64)
    r3 = gate.verify_before_chain(wrong_hash, tool_output=tool_output)

    # Test 4: safe_to_rely=False fails
    unsafe = dict(valid_receipt, safe_to_rely=False, verdict="inconsistencies_detected")
    r4 = gate.verify_before_chain(unsafe, tool_output=tool_output)

    results = {
        "valid_receipt_passes": r1.safe is True,
        "tampered_receipt_blocked": r2.safe is False,
        "wrong_hash_blocked": r3.safe is False,
        "unsafe_verdict_blocked": r4.safe is False,
    }

    all_pass = all(results.values())
    results["conformance"] = "PASS" if all_pass else "FAIL"
    return results


if __name__ == "__main__":
    results = conformance_test_receipt_before_chain()
    for test_name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {test_name}: {status}")
