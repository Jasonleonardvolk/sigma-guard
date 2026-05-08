# sigma_guard/entrypoint.py
# Docker entrypoint for SIGMA Guard.
#
# Modes:
#   sigma-guard verify <file>          - Verify a graph file
#   sigma-guard check <file> --source A --target B  - Check a write
#   sigma-guard serve                  - Start the API server
#   sigma-guard demo [dataset]         - Run a demo on bundled datasets
#   sigma-guard info                   - Print version and tier info
#
# May 2026 | Invariant Research

import sys
import json
import os


def cmd_serve(args):
    """Start the SIGMA Guard API server."""
    try:
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse
        from fastapi.middleware.cors import CORSMiddleware
        import uvicorn
    except ImportError:
        print("FastAPI and uvicorn required for serve mode.")
        print("Install with: pip install fastapi uvicorn")
        return 2

    from sigma_guard import SigmaGuard
    from sigma_guard.free_tier import get_tier_info

    app = FastAPI(
        title="SIGMA Guard API",
        description="Pre-commit contradiction detection for graph databases",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "version": "0.1.0",
            "engine": "sigma-guard",
            "tier": get_tier_info(),
        }

    @app.post("/verify")
    async def verify(request: Request):
        try:
            body = await request.json()
            guard = SigmaGuard(
                stalk_dim=body.get("stalk_dim", 8),
                seed=body.get("seed", 42),
            )

            graph_data = {
                "vertices": body.get("vertices", []),
                "edges": body.get("edges", []),
            }
            guard.load_dict(graph_data)
            verdict = guard.verify()
            return JSONResponse(verdict.to_dict())

        except Exception as exc:
            return JSONResponse(
                {"error": str(exc)},
                status_code=400,
            )

    @app.post("/check")
    async def check_write(request: Request):
        try:
            body = await request.json()
            guard = SigmaGuard(
                stalk_dim=body.get("stalk_dim", 8),
                seed=body.get("seed", 42),
            )

            graph_data = {
                "vertices": body.get("vertices", []),
                "edges": body.get("edges", []),
            }
            guard.load_dict(graph_data)

            result = guard.check_write(
                source=body["source"],
                target=body["target"],
                relation=body.get("relation", ""),
                value=body.get("value"),
            )
            return JSONResponse(result.to_dict())

        except Exception as exc:
            return JSONResponse(
                {"error": str(exc)},
                status_code=400,
            )

    host = os.getenv("SIGMA_HOST", "0.0.0.0")
    port = int(os.getenv("SIGMA_PORT", "8400"))
    print("SIGMA Guard API starting on %s:%d" % (host, port))
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


def cmd_demo(dataset_name):
    """Run a demo on a bundled dataset."""
    from sigma_guard import SigmaGuard

    # Find the dataset
    search_paths = [
        "datasets",
        "/opt/sigma-guard/datasets",
        os.path.join(os.path.dirname(__file__), "..", "datasets"),
    ]

    dataset_file = "%s.json" % dataset_name
    dataset_path = None
    for base in search_paths:
        candidate = os.path.join(base, dataset_file)
        if os.path.exists(candidate):
            dataset_path = candidate
            break

    if dataset_path is None:
        available = []
        for base in search_paths:
            if os.path.isdir(base):
                for f in os.listdir(base):
                    if f.endswith(".json"):
                        available.append(f.replace(".json", ""))
        print("Dataset '%s' not found." % dataset_name)
        if available:
            print("Available: %s" % ", ".join(sorted(set(available))))
        return 2

    print("SIGMA Guard Demo: %s" % dataset_name)
    print("=" * 50)
    print()

    guard = SigmaGuard(stalk_dim=8, seed=42)
    guard.load_json(dataset_path)
    verdict = guard.verify()
    print(verdict.summary())
    return 1 if verdict.has_contradictions else 0


def cmd_info():
    """Print version and tier information."""
    from sigma_guard.free_tier import get_tier_info
    tier = get_tier_info()

    print("SIGMA Guard v0.1.0")
    print("Invariant Research | https://invariant.pro")
    print()
    print("Tier: %s" % tier["tier"])
    if tier["vertex_limit"]:
        print("Vertex limit: %d" % tier["vertex_limit"])
    else:
        print("Vertex limit: unlimited")
    print()

    # Check if engine is available
    try:
        from sigma.core.graph import SheafGraph
        print("Engine: available")
    except ImportError:
        print("Engine: not found")
        print("  The SIGMA core engine is required for full verification.")
        print("  Use the Docker image: docker run invariant/sigma-guard")

    return 0


def main():
    args = sys.argv[1:]

    if not args:
        from sigma_guard.cli import main as cli_main
        return cli_main()

    command = args[0]

    if command == "serve":
        return cmd_serve(args[1:])
    elif command == "demo":
        dataset = args[1] if len(args) > 1 else "supply_chain"
        return cmd_demo(dataset)
    elif command == "info":
        return cmd_info()
    else:
        # Pass through to the regular CLI
        from sigma_guard.cli import main as cli_main
        return cli_main()


if __name__ == "__main__":
    sys.exit(main())
