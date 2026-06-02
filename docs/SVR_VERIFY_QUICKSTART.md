# SVR Verify Quickstart

Verify any Signed Verification Receipt in three steps.

## Install

```
pip install svr-verify
```

One dependency (pynacl). Python 3.9+. MIT license.

## Verify a receipt

```
svr-verify receipt.svr.json
```

Output is `VALID` or `INVALID`. That is the entire interface.

If you have the issuer's public key file:

```
svr-verify receipt.svr.json --pubkey issuer_pubkey.txt
```

## Verify from Python

```python
from svr_verify import verify

result = verify("receipt.svr.json")
print("Signature valid:", result["signature_valid"])
print("Structure valid:", result["structure_valid"])
print("Verdict:", result["receipt"].get("verdict"))
```

## What the verifier checks

- Ed25519 signature against the public key
- Receipt structure conformance (all required fields present)
- Count invariant (items_checked = items_passed + items_failed + items_excluded)
- Hash chain integrity

## What the verifier does NOT check

- Whether the verification result is correct (that requires the engine)
- Whether the source material is authentic
- Transport-layer security

The verifier answers one question: is this receipt authentic and
unmodified? If VALID, the receipt was issued by the holder of the
signing key and has not been tampered with since issuance.

## No account required

No API key. No login. No internet connection after install. The
verification is a local cryptographic check using the public key
embedded in the receipt.

## Links

- PyPI: https://pypi.org/project/svr-verify/
- Source: https://github.com/Jasonleonardvolk/svr-verify
- Full guide: [How to Read an SVR](https://github.com/Jasonleonardvolk/svr-verify/blob/main/HOW_TO_READ_AN_SVR.md)
- SVR Spec: [SVR_SPEC_v1.txt](https://github.com/Jasonleonardvolk/sigma/blob/main/satya/spec/SVR_SPEC_v1.txt)
- Sample receipt: [SVR_RECEIPT_EXAMPLE.json](SVR_RECEIPT_EXAMPLE.json)
