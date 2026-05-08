# Dockerfile for SIGMA Graph Guard
# Packages the SIGMA engine as a verification service.
#
# Build: docker build -t invariant/sigma-guard .
# Run:   docker run -p 8400:8400 invariant/sigma-guard

FROM python:3.11-slim

WORKDIR /opt/sigma-guard

# Install dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir numpy scipy

# Copy source
COPY sigma_guard/ sigma_guard/
COPY datasets/ datasets/

# Install the package
RUN pip install --no-cache-dir .

# Expose the API port
EXPOSE 8400

# Default: run the CLI help
CMD ["sigma-guard", "--help"]
