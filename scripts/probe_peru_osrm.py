"""CLI: national-scope spot checks against an independently operated local OSRM."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from desset_core.graph_evidence import verify_staged_peru_graph
from desset_core.national import NationalProbeError, load_probes, run_national_probes, verify_local_pbf


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run cautious PE route spot checks; not a coverage certificate")
    parser.add_argument("--scenarios", required=True, type=Path)
    parser.add_argument("--pbf", required=True, type=Path)
    parser.add_argument("--pbf-sha256", required=True)
    parser.add_argument("--dataset-ref", required=True)
    parser.add_argument("--profile", default="car-prototype-unverified")
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--graph-dir", type=Path, help="isolated OSRM MLD staging directory")
    parser.add_argument("--image-reference", help="immutable OSRM image digest used to build graph")
    args = parser.parse_args(argv)
    if (args.graph_dir is None) != (args.image_reference is None):
        parser.error("--graph-dir and --image-reference must be supplied together")
    try:
        data = verify_local_pbf(args.pbf, expected_sha256=args.pbf_sha256)
        graph = None
        if args.graph_dir is not None:
            graph = verify_staged_peru_graph(
                args.graph_dir, expected_pbf_sha256=args.pbf_sha256,
                expected_image_reference=args.image_reference,
            )
            if graph["pbf_filename"] != args.pbf.name:
                raise NationalProbeError("staged PBF name mismatches preflight PBF")
        probes = load_probes(args.scenarios)
        report = run_national_probes(
            probes, dataset_ref=args.dataset_ref, transport_profile=args.profile,
            base_url=args.base_url,
        )
    except NationalProbeError as exc:
        print(f"national preflight failed: {exc}", file=sys.stderr)
        return 2
    report["pbf_integrity"] = data
    report["graph_integrity"] = graph
    report["graph_artifact_integrity_control_result"] = (
        graph["graph_artifact_integrity_control_result"] if graph else "NOT_VERIFIED"
    )
    report["daemon_graph_binding_control_result"] = "NOT_VERIFIED"
    report["dataset_ref_declared"] = args.dataset_ref
    report["profile_declared"] = args.profile
    report["network_provenance_verified"] = False  # a local endpoint could be mocked
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if report["route_query_control_result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
