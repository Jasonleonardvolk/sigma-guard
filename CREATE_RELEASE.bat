@echo off
REM ============================================================
REM Create GitHub Release for sigma-guard v0.3.1
REM Run from C:\Dev\kha\sigma\github\sigma-guard
REM Requires: gh CLI authenticated (gh auth login)
REM ============================================================

cd /d C:\Dev\kha\sigma\github\sigma-guard

echo [1/4] Staging all changed and new files...
git add README.md
git add CHANGELOG.md
git add CITATION.cff
git add llms.txt
git add pyproject.toml
git add smithery.yaml

REM Clean up the temp badge reference file (content is now in README)
if exist README_BADGES.md del README_BADGES.md

echo [2/4] Committing...
git commit -m "v0.3.1: badges, CHANGELOG, CITATION.cff, fix llms.txt URL, expand pyproject.toml keywords/classifiers"

echo [3/4] Pushing to main...
git push origin main

echo [4/4] Creating GitHub Release...
gh release create v0.3.1 --title "v0.3.1 - Structural verification for graph databases" --notes-file CHANGELOG.md

echo.
echo ============================================================
echo  Release created successfully.
echo ============================================================
echo.
echo  Verify at:
echo    https://github.com/Jasonleonardvolk/sigma-guard/releases
echo.
echo  What changed in this commit:
echo    - README.md: added PyPI/Python/License/arXiv badges
echo    - CHANGELOG.md: full release notes for v0.3.1
echo    - CITATION.cff: GitHub "Cite this repository" metadata
echo    - llms.txt: fixed broken GitHub URL
echo    - pyproject.toml: added falkordb/graph-consistency/formal-verification/ai-safety
echo      keywords, Science/Research audience, Security topic, Changelog URL
echo.
echo  Remaining manual steps:
echo    1. Verify Docker image: docker pull jasonvolk/sigma-guard
echo    2. Check Smithery listing: https://smithery.ai
echo    3. Submit to Google Search Console for invariant.pro
echo    4. Post Show HN (C:\Dev\kha\sigma\social\SHOW_HN_DRAFT.md)
echo    5. Post LinkedIn (C:\Dev\kha\sigma\social\LINKEDIN_SIGMA_GUARD_LAUNCH.md)
echo    6. Submit awesome-list PRs (C:\Dev\kha\sigma\social\AWESOME_LIST_TARGETS.md)
echo    7. Rebuild and re-publish to PyPI with updated metadata:
echo       cd C:\Dev\kha\sigma\github\sigma-guard
echo       python -m build
echo       twine upload dist/sigma_guard-0.3.2*
echo       (bump version to 0.3.2 in pyproject.toml first)
echo ============================================================
