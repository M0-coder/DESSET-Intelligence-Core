"""CLI: national-scope spot checks against an independently operated local OSRM."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

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
    args = parser.parse_args(argv)
    try:
        data = verify_local_pbf(args.pbf, expected_sha256=args.pbf_sha256)
        probes = load_probes(args.scenarios)
        report = run_national_probes(
            probes, dataset_ref=args.dataset_ref, transport_profile=args.profile,
            base_url=args.base_url,
        )
    except NationalProbeError as exc:
        print(f"national preflight failed: {exc}", file=sys.stderr)
        return 2
    report["pbf_integrity"] = data
    report["dataset_ref_declared"] = args.dataset_ref
    report["profile_declared"] = args.profile
    report["network_provenance_verified"] = False  # a local endpoint could be mocked
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if report["route_query_control_result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
