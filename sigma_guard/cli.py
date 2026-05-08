# sigma_guard/cli.py
# CLI entry point for sigma-guard.
#
# Usage:
#   sigma-guard verify my_graph.json
#   sigma-guard verify my_graph.graphml --json
#   sigma-guard verify my_graph.edges --sign
#   sigma-guard check --source A --target B --relation supplies my_graph.json
#
# May 2026 | Invariant Research | Patent Pending

import sys
import argparse
import json

from sigma_guard.engine import SigmaGuard


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="sigma-guard",
        description=(
            "SIGMA Graph Guard: Pre-commit contradiction detection "
            "for graph databases. Sheaf cohomology finds structural "
            "contradictions. 63 microseconds. Deterministic. Provable."
        ),
    )
    parser.add_argument(
        "--version", "-v",
        action="version",
        version="sigma-guard 0.1.0",
    )

    subparsers = parser.add_subparsers(dest="command")

    # verify command
    verify_parser = subparsers.add_parser(
        "verify",
        help="Verify a graph file for structural contradictions",
    )
    verify_parser.add_argument(
        "file",
        help="Path to graph file (JSON, GraphML, or edge list)",
    )
    verify_parser.add_argument(
        "--format", "-f",
        choices=["json", "graphml", "edges"],
        default=None,
        help="Input format (auto-detected from extension if omitted)",
    )
    verify_parser.add_argument(
        "--json", "-j",
        action="store_true",
        default=False,
        help="Output full result as JSON",
    )
    verify_parser.add_argument(
        "--sign", "-s",
        action="store_true",
        default=False,
        help="Include cryptographic signature in the verdict",
    )
    verify_parser.add_argument(
        "--stalk-dim", "-d",
        type=int,
        default=8,
        help="Stalk dimension (default: 8)",
    )
    verify_parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        default=False,
        help="Exit code only: 0=consistent, 1=inconsistent, 2=error",
    )

    # check command (single write)
    check_parser = subparsers.add_parser(
        "check",
        help="Check if a proposed write would create a contradiction",
    )
    check_parser.add_argument(
        "file",
        help="Path to existing graph file",
    )
    check_parser.add_argument(
        "--source",
        required=True,
        help="Source vertex label",
    )
    check_parser.add_argument(
        "--target",
        required=True,
        help="Target vertex label",
    )
    check_parser.add_argument(
        "--relation",
        default="",
        help="Edge relation type",
    )
    check_parser.add_argument(
        "--value",
        default=None,
        help="Property value",
    )
    check_parser.add_argument(
        "--json", "-j",
        action="store_true",
        default=False,
        help="Output as JSON",
    )

    return parser


def _detect_format(path):
    """Detect graph file format from extension."""
    lower = path.lower()
    if lower.endswith(".json"):
        return "json"
    elif lower.endswith(".graphml") or lower.endswith(".xml"):
        return "graphml"
    elif lower.endswith(".edges") or lower.endswith(".tsv") or lower.endswith(".csv"):
        return "edges"
    return "json"  # default


def cmd_verify(args):
    """Run the verify command."""
    fmt = args.format or _detect_format(args.file)
    guard = SigmaGuard(stalk_dim=args.stalk_dim)

    try:
        if fmt == "json":
            guard.load_json(args.file)
        elif fmt == "graphml":
            guard.load_graphml(args.file)
        elif fmt == "edges":
            guard.load_edge_list(args.file)
        else:
            print("Unknown format: %s" % fmt, file=sys.stderr)
            return 2
    except FileNotFoundError:
        print("File not found: %s" % args.file, file=sys.stderr)
        return 2
    except Exception as exc:
        print("Error loading graph: %s" % exc, file=sys.stderr)
        return 2

    verdict = guard.verify()

    if args.quiet:
        pass
    elif args.json:
        print(verdict.to_json())
    else:
        print(verdict.summary())

    return 1 if verdict.has_contradictions else 0


def cmd_check(args):
    """Run the check command."""
    fmt = _detect_format(args.file)
    guard = SigmaGuard()

    try:
        if fmt == "json":
            guard.load_json(args.file)
        elif fmt == "graphml":
            guard.load_graphml(args.file)
        elif fmt == "edges":
            guard.load_edge_list(args.file)
    except Exception as exc:
        print("Error loading graph: %s" % exc, file=sys.stderr)
        return 2

    result = guard.check_write(
        source=args.source,
        target=args.target,
        relation=args.relation,
        value=args.value,
    )

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        if result.creates_contradiction:
            print("[BLOCKED] This write would create a contradiction.")
            print("  Severity: %s" % result.severity)
            print("  Conflicts with: %s" % ", ".join(result.conflicting_nodes))
            print("  Energy delta: %.4f" % result.energy_delta)
            print("  %s" % result.explanation)
            print("  Proof: %s" % result.proof_id)
        else:
            print("[OK] Write is safe. No contradiction created.")
        print("  Elapsed: %.1f us" % result.elapsed_us)

    return 1 if result.creates_contradiction else 0


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "verify":
        return cmd_verify(args)
    elif args.command == "check":
        return cmd_check(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
