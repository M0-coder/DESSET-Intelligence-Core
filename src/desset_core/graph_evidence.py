"""Read-only checksum gate for a staged Peru OSRM graph.

Checks bytes and manifest consistency, never authenticity or live daemon identity.
An untrusted local file can still claim to be a map; do not promote this result
into a national road coverage or vehicle suitability certificate.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .national import HASH, NationalProbeError, verify_local_pbf

IMAGE_REFERENCE = re.compile(r"^ghcr\.io/project-osrm/osrm-backend@sha256:[0-9a-f]{64}$")


# OSRM v6.0.0, default MLD/car profile; storage_config.hpp and storage.cpp.
# This minimum structural gate is not binary parsing or a daemon-readiness test.
REQUIRED_MLD_SUFFIXES = frozenset({
    ".osrm.datasource_names", ".osrm.ebg_nodes", ".osrm.edges", ".osrm.fileIndex",
    ".osrm.geometry", ".osrm.icd", ".osrm.maneuver_overrides", ".osrm.names",
    ".osrm.nbg_nodes", ".osrm.properties", ".osrm.ramIndex", ".osrm.timestamp",
    ".osrm.tld", ".osrm.tls", ".osrm.turn_duration_penalties", ".osrm.turn_weight_penalties",
    ".osrm.cells", ".osrm.cell_metrics", ".osrm.mldgr", ".osrm.partition",
})
NONEMPTY_MLD_SUFFIXES = frozenset({
    ".osrm.fileIndex", ".osrm.ramIndex", ".osrm.properties", ".osrm.cells",
    ".osrm.cell_metrics", ".osrm.mldgr", ".osrm.partition",
})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise NationalProbeError(f"{label} must be a regular file, not a link")


def verify_staged_peru_graph(
    graph_dir: Path, *, expected_pbf_sha256: str, expected_image_reference: str,
) -> dict[str, object]:
    """Verify the inventory and minimum MLD file set of a staging directory from build_peru_osrm.sh.

    PASS means file byte equality against operator-supplied digests only. It does
    not prove the PBF came from Geofabrik, the OSRM image is trustworthy, or the
    independently running HTTP daemon is actually serving these exact bytes.
    """
    if not isinstance(graph_dir, Path) or graph_dir.is_symlink() or not graph_dir.is_dir():
        raise NationalProbeError("graph_dir must be a real existing directory")
    if not isinstance(expected_pbf_sha256, str) or not HASH.fullmatch(expected_pbf_sha256):
        raise NationalProbeError("expected PBF SHA-256 must be lowercase hex")
    if not isinstance(expected_image_reference, str) or not IMAGE_REFERENCE.fullmatch(
        expected_image_reference
    ):
        raise NationalProbeError("OSRM image must be pinned to an immutable SHA-256 digest")

    pbf_files = [p for p in graph_dir.iterdir() if p.name.startswith("peru-")
                 and p.name.endswith(".osm.pbf")]
    if len(pbf_files) != 1:
        raise NationalProbeError("staging requires exactly one dated Peru PBF")
    pbf = pbf_files[0]
    _regular(pbf, "PBF")
    pbf_info = verify_local_pbf(pbf, expected_sha256=expected_pbf_sha256)
    base = pbf.name.removesuffix(".osm.pbf")
    manifest_path = graph_dir / f"{base}.osrm-build-manifest.json"
    _regular(manifest_path, "graph manifest")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError, RecursionError) as exc:
        raise NationalProbeError("invalid OSRM graph manifest") from exc
    if not isinstance(manifest, dict) or any((
        manifest.get("country_code") != "PE",
        manifest.get("pbf_name") != pbf.name,
        manifest.get("pbf_sha256") != expected_pbf_sha256,
        manifest.get("image_reference") != expected_image_reference,
        manifest.get("osrm_algorithm") != "MLD",
        manifest.get("osrm_profile_declared") != "/opt/car.lua",
        manifest.get("preprocess_control_result") != "PASS",
        manifest.get("nationwide_coverage_control_result") != "NOT_VERIFIED",
        manifest.get("candidate_decision") != "BLOCKED",
    )):
        raise NationalProbeError("OSRM manifest identity or safety declarations mismatch")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts or len(artifacts) > 500:
        raise NationalProbeError("OSRM graph artifact inventory missing or oversized")
    expected_names: set[str] = set()
    nonempty_names = {base + suffix for suffix in NONEMPTY_MLD_SUFFIXES}
    verified_bytes = 0
    for entry in artifacts:
        if not isinstance(entry, dict) or set(entry) != {"name", "bytes", "sha256"}:
            raise NationalProbeError("malformed graph artifact inventory entry")
        name, length, digest = entry["name"], entry["bytes"], entry["sha256"]
        if (not isinstance(name, str) or name != Path(name).name
                or not (name == f"{base}.osrm" or name.startswith(f"{base}.osrm."))
                or name in expected_names):
            raise NationalProbeError("invalid, duplicated or foreign graph artifact name")
        if type(length) is not int or length < 0 or not isinstance(digest, str) or not HASH.fullmatch(digest):
            raise NationalProbeError("invalid graph artifact length/hash")
        if name in nonempty_names and length == 0:
            raise NationalProbeError("required MLD artifact is empty")
        expected_names.add(name)
        artifact = graph_dir / name
        _regular(artifact, "graph artifact")
        if artifact.stat().st_size != length or _sha256(artifact) != digest:
            raise NationalProbeError("graph artifact tampered or truncated")
        verified_bytes += length
    # Inventory equality alone cannot establish the minimum required files.
    required_names = {base + suffix for suffix in REQUIRED_MLD_SUFFIXES}
    if not required_names.issubset(expected_names):
        raise NationalProbeError("required OSRM v6 MLD artifacts missing")
    # Inventory must also cover every actual graph by-product.
    actual_names = {p.name for p in graph_dir.iterdir()
                    if p.name == f"{base}.osrm" or p.name.startswith(f"{base}.osrm.")}
    if actual_names != expected_names:
        raise NationalProbeError("OSRM graph inventory differs from staged files")
    if {p.name for p in graph_dir.iterdir()} != expected_names | {pbf.name, manifest_path.name}:
        raise NationalProbeError("unexpected files in private graph staging directory")
    return {
        "graph_artifact_integrity_control_result": "PASS",
        "graph_minimum_inventory_control_result": "PASS",
        "graph_readiness_control_result": "NOT_VERIFIED",
        "pbf_sha256": pbf_info["sha256"],
        "pbf_filename": pbf.name,
        "image_reference_declared": expected_image_reference,
        "artifact_count": len(expected_names),
        "artifact_bytes": verified_bytes,
        "dataset_source_authenticity_control_result": "NOT_VERIFIED",
        "daemon_graph_binding_control_result": "NOT_VERIFIED",
        "map_quality_control_result": "NOT_VERIFIED",
        "candidate_decision": "BLOCKED",
    }
