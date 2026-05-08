# Contributing

Useful contributions:

- New graph parsers (CSV, NetworkX, RDF)
- Demo datasets with planted contradictions
- Adapter examples (FalkorDB, ArangoDB, other graph databases)
- Documentation improvements
- Benchmark reproduction scripts
- Better error messages
- CI integration examples

Please do not submit changes that replace deterministic verification
with LLM judging. This project is intentionally non-probabilistic
at the verification layer.

## Development setup

```
git clone https://github.com/Jasonleonardvolk/sigma-guard.git
cd sigma-guard
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest tests/
```

## Running demos

```
python examples/tiny_contradiction.py
python examples/basic_usage.py
```
