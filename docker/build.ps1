# docker/build.ps1
# Build the SIGMA Guard Docker image.
#
# This script copies the required SIGMA core files into the Docker
# build context, builds the image, and cleans up.
#
# The SIGMA core source is NOT committed to the public repo.
# It is copied into the build context only during image construction.
#
# Usage:
#   cd C:\Dev\kha\sigma\github\sigma-guard
#   .\docker\build.ps1
#
# May 2026 | Invariant Research

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$SigmaCore = "C:\Dev\kha\sigma\core"
$BuildContext = Join-Path $RepoRoot "docker\build_context"

Write-Host ""
Write-Host "SIGMA Guard Docker Build"
Write-Host "========================"
Write-Host ""

# Verify SIGMA core exists
if (-not (Test-Path $SigmaCore)) {
    Write-Host "ERROR: SIGMA core not found at $SigmaCore"
    exit 1
}

# Clean previous build context
if (Test-Path $BuildContext) {
    Remove-Item -Recurse -Force $BuildContext
}
New-Item -ItemType Directory -Path $BuildContext | Out-Null

Write-Host "Assembling build context..."

# Copy sigma_guard (the public integration layer)
Copy-Item -Recurse (Join-Path $RepoRoot "sigma_guard") (Join-Path $BuildContext "sigma_guard")

# Copy datasets
Copy-Item -Recurse (Join-Path $RepoRoot "datasets") (Join-Path $BuildContext "datasets")

# Copy pyproject.toml
Copy-Item (Join-Path $RepoRoot "pyproject.toml") (Join-Path $BuildContext "pyproject.toml")

# Create sigma/core package (the engine, NOT committed to repo)
$EngineDir = Join-Path $BuildContext "sigma"
$CoreDir = Join-Path $EngineDir "core"
New-Item -ItemType Directory -Path $CoreDir | Out-Null

# sigma/__init__.py
Set-Content -Path (Join-Path $EngineDir "__init__.py") -Value ""

# Copy core files
$CoreFiles = @("__init__.py", "graph.py", "sheaf.py", "cohomology.py", "laplacian.py")
foreach ($f in $CoreFiles) {
    $src = Join-Path $SigmaCore $f
    if (Test-Path $src) {
        Copy-Item $src (Join-Path $CoreDir $f)
        Write-Host "  Copied sigma/core/$f"
    } else {
        Write-Host "  WARNING: $src not found"
    }
}

# Copy Dockerfile into build context
Copy-Item (Join-Path $RepoRoot "docker\Dockerfile.engine") (Join-Path $BuildContext "Dockerfile")

Write-Host ""
Write-Host "Building Docker image..."
Write-Host ""

# Build the image
Push-Location $BuildContext
docker build -t invariant/sigma-guard:latest -t invariant/sigma-guard:0.1.0 .
$buildResult = $LASTEXITCODE
Pop-Location

# Clean up build context (contains proprietary core)
Write-Host ""
Write-Host "Cleaning build context..."
Remove-Item -Recurse -Force $BuildContext

if ($buildResult -eq 0) {
    Write-Host ""
    Write-Host "SUCCESS: invariant/sigma-guard:latest built"
    Write-Host ""
    Write-Host "Test it:"
    Write-Host "  docker run invariant/sigma-guard demo supply_chain"
    Write-Host "  docker run invariant/sigma-guard info"
    Write-Host "  docker run -p 8400:8400 invariant/sigma-guard serve"
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "FAILED: Docker build exited with code $buildResult"
    exit $buildResult
}
