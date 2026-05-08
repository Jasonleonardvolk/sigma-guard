param(
    [ValidateSet("setup", "test", "demo", "clean", "verify")]
    [string]$Task = "demo"
)

$ErrorActionPreference = "Stop"

switch ($Task) {
    "setup" {
        python -m venv .venv
        .\.venv\Scripts\python.exe -m pip install --upgrade pip
        .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
        Write-Host "Setup complete. Activate with: .\.venv\Scripts\Activate.ps1"
    }

    "test" {
        python -m pytest tests -v
    }

    "demo" {
        Write-Host ""
        python examples\tiny_contradiction.py
        Write-Host ""
        python examples\basic_usage.py
    }

    "verify" {
        python -m sigma_guard.standalone_verifier --graph datasets\supply_chain.json
    }

    "clean" {
        Get-ChildItem -Recurse -Force -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
        Get-ChildItem -Recurse -Force -Directory -Filter .pytest_cache | Remove-Item -Recurse -Force
        Get-ChildItem -Recurse -Force -Filter *.pyc | Remove-Item -Force
        Get-ChildItem -Recurse -Force -Filter desktop.ini | Remove-Item -Force
        Write-Host "Cleaned."
    }
}
