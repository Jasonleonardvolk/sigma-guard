# CREATE_RELEASE.ps1
# Run from C:\Dev\kha\sigma\github\sigma-guard
# Requires: gh CLI authenticated (gh auth login)

Set-Location C:\Dev\kha\sigma\github\sigma-guard

Write-Host "[1/4] Staging all changed and new files..." -ForegroundColor Cyan
git add README.md
git add CHANGELOG.md
git add CITATION.cff
git add llms.txt
git add pyproject.toml
git add smithery.yaml

if (Test-Path README_BADGES.md) { Remove-Item README_BADGES.md }

Write-Host "[2/4] Committing..." -ForegroundColor Cyan
git commit -m "v0.3.1: badges, CHANGELOG, CITATION.cff, fix llms.txt URL, expand pyproject.toml keywords/classifiers"

Write-Host "[3/4] Pushing to main..." -ForegroundColor Cyan
git push origin main

Write-Host "[4/4] Creating GitHub Release..." -ForegroundColor Cyan
gh release create v0.3.1 --title "v0.3.1 - Structural verification for graph databases" --notes-file CHANGELOG.md

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " Release created. Verify at:" -ForegroundColor Green
Write-Host " https://github.com/Jasonleonardvolk/sigma-guard/releases" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
