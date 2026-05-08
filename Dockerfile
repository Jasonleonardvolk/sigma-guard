# Dockerfile (adapter layer only, no engine)
#
# This image contains the sigma_guard integration layer, parsers,
# adapters, and standalone verifier. It does NOT contain the SIGMA
# core engine. Use it for independent verification of proof receipts
# and as a base for custom integrations.
#
# For the full engine image:
#   docker pull invariant/sigma-guard
#
# Build:
#   docker build -t sigma-guard-adapter .

FROM python:3.11-slim

WORKDIR /opt/sigma-guard

COPY pyproject.toml .
RUN pip install --no-cache-dir numpy scipy

COPY sigma_guard/ sigma_guard/
COPY datasets/ datasets/

RUN pip install --no-cache-dir -e .

ENTRYPOINT ["python", "-m", "sigma_guard.standalone_verifier"]
CMD ["--help"]
