"""CLI: national-scope spot checks against an independently operated local OSRM."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from desset_core.graph_evidence import verify_staged_peru_graph
from desset_core.national import NationalProbeError, load_probes, run_national_probes, verify_local_pbf


def _safe_output(output: Path, graph_dir: Path | None) -> Path:
    """Reject existing targets, including dangling symlinks, before any HTTP."""
    if output.exists() or output.is_symlink():
        raise NationalProbeError("report output must not exist")
    target = output.parent.resolve(strict=True) / output.name
    if not target.parent.is_dir():
        raise NationalProbeError("report parent must be an existing directory")
    if graph_dir is not None and target.is_relative_to(graph_dir.resolve(strict=True)):
        raise NationalProbeError("report output must be outside graph staging")
    if target.name.endswith(".pbf") or ".osrm" in target.name:
        raise NationalProbeError("report output cannot use a map/graph filename")
    return target


def _write_report(output: Path, report: dict[str, object]) -> None:
    """Publish complete JSON exclusively; a racing existing file is untouched."""
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent,
                                     prefix=".probe-report-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(report, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
            os.link(temporary, output)
        finally:
            temporary.unlink()


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
        output = _safe_output(args.output, args.graph_dir)
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
    except (NationalProbeError, OSError, RuntimeError) as exc:
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
    try:
        _write_report(output, report)
    except OSError as exc:
        print(f"report publication failed: {exc}", file=sys.stderr)
        return 2
    return 0 if report["route_query_control_result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
