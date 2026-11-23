"""National Peru routing smoke checks. Never claim national coverage from a sample.

Each scenario uses declared, approximate public coordinates. Routes are queried
only through the separately-operated loopback OSRM endpoint; no network download.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .osrm_local import RoadPoint, fetch_local_osrm_table
from .routing_matrix import MatrixInputError

# 24 departments plus the Constitutional Province of Callao. This is a coverage
# register, not a claim that an OSRM graph was successfully validated in each.
PERU_JURISDICTIONS = frozenset({
    "Amazonas", "Áncash", "Apurímac", "Arequipa", "Ayacucho", "Cajamarca",
    "Callao", "Cusco", "Huancavelica", "Huánuco", "Ica", "Junín",
    "La Libertad", "Lambayeque", "Lima", "Loreto", "Madre de Dios",
    "Moquegua", "Pasco", "Piura", "Puno", "San Martín", "Tacna",
    "Tumbes", "Ucayali",
})
HASH = re.compile(r"^[0-9a-f]{64}$")
DATED_PBF_NAME = re.compile(r"^peru-[0-9]{6}\.osm\.pbf$")


class NationalProbeError(ValueError):
    """Invalid coverage probe or missing reproducibility requirement."""


@dataclass(frozen=True)
class NationalProbe:
    id: str
    kind: str
    regions: tuple[str, ...]
    origin: RoadPoint
    destination: RoadPoint
    coordinate_evidence: str


@dataclass(frozen=True)
class NationalProbeResult:
    id: str
    kind: str
    regions: tuple[str, ...]
    control_result: str
    duration_seconds: int | None
    reason: str | None
    request_sha256: str | None
    response_sha256: str | None


def _location(value: object, label: str) -> RoadPoint:
    if not isinstance(value, dict) or set(value) != {"id", "longitude", "latitude"}:
        raise NationalProbeError(f"{label} requires id, longitude, latitude")
    try:
        # The OSRM client independently validates the numerical ranges.
        return RoadPoint(value["id"], value["longitude"], value["latitude"])
    except (KeyError, TypeError) as exc:
        raise NationalProbeError(f"invalid {label}") from exc


def parse_national_probes(value: object) -> tuple[NationalProbe, ...]:
    """Validate a small sample; it cannot establish comprehensive coverage."""
    if not isinstance(value, dict) or value.get("country_code") != "PE":
        raise NationalProbeError("country_code must be PE")
    if value.get("coordinate_accuracy") != "APPROXIMATE_UNVERIFIED":
        raise NationalProbeError("probe coordinates must be explicitly unverified")
    if not isinstance(value.get("jurisdictions"), list) or len(value["jurisdictions"]) != 25 or any(not isinstance(s, str) for s in value["jurisdictions"]):
        raise NationalProbeError("jurisdiction register must have 25 entries")
    if set(value["jurisdictions"]) != PERU_JURISDICTIONS:
        raise NationalProbeError("jurisdiction register must contain all 25 Peru entries")
    items = value.get("probes")
    if not isinstance(items, list) or not items or len(items) > 100:
        raise NationalProbeError("probes must contain 1..100 entries")
    found = set()
    probes = []
    for item in items:
        if not isinstance(item, dict):
            raise NationalProbeError("probe must be a JSON object")
        probe_id = item.get("id")
        kind = item.get("kind")
        regions = item.get("regions")
        if not isinstance(probe_id, str) or not probe_id or len(probe_id) > 80:
            raise NationalProbeError("invalid probe id")
        if probe_id in found:
            raise NationalProbeError("duplicate probe id")
        found.add(probe_id)
        if kind not in ("urban", "interprovincial", "interregional"):
            raise NationalProbeError("invalid probe kind")
        if not isinstance(regions, list) or not 1 <= len(regions) <= 2:
            raise NationalProbeError("invalid probe regions")
        if any(not isinstance(region, str) or region not in PERU_JURISDICTIONS
               for region in regions):
            raise NationalProbeError("unknown Peru jurisdiction")
        if len(set(regions)) != len(regions):
            raise NationalProbeError("duplicate probe region")
        if kind == "urban" and len(regions) != 1:
            raise NationalProbeError("urban probe must reference one region")
        if kind == "interregional" and len(regions) != 2:
            raise NationalProbeError("interregional probe must reference two regions")
        if item.get("coordinate_evidence") != "NOT_VERIFIED":
            raise NationalProbeError("coordinate evidence must be NOT_VERIFIED")
        probes.append(NationalProbe(
            id=probe_id,
            kind=kind,
            regions=tuple(regions),
            origin=_location(item.get("origin"), "origin"),
            destination=_location(item.get("destination"), "destination"),
            coordinate_evidence="NOT_VERIFIED",
        ))
    return tuple(probes)


def verify_local_pbf(pbf: Path, *, expected_sha256: str) -> dict[str, object]:
    """Verify exact PBF bytes against an externally supplied expected digest.

    This confirms byte equality only. It cannot authenticate who set the digest,
    certify OSM licensing, or prove routing graph quality.
    """
    if not isinstance(expected_sha256, str) or not HASH.fullmatch(expected_sha256):
        raise NationalProbeError("a 64-character lowercase SHA-256 is mandatory")
    if not pbf.is_file() or not DATED_PBF_NAME.fullmatch(pbf.name):
        raise NationalProbeError("expected existing dated peru-YYMMDD.osm.pbf")
    # Cheap structural preflight, NOT a full protobuf/OSM parser. OSRM must
    # still parse the complete file before it can be considered a usable map.
    with pbf.open("rb") as file:
        header_prefix = file.read(4)
        if len(header_prefix) != 4:
            raise NationalProbeError("PBF missing blob header")
        header_length = int.from_bytes(header_prefix, "big")
        if not 1 <= header_length <= 65536:
            raise NationalProbeError("PBF invalid blob header length")
        blob_header = file.read(header_length)
        if len(blob_header) != header_length or b"OSMHeader" not in blob_header:
            raise NationalProbeError("PBF OSMHeader marker missing")
    digest = hashlib.sha256()
    total = 0
    with pbf.open("rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
            total += len(chunk)
    if digest.hexdigest() != expected_sha256:
        raise NationalProbeError("PBF SHA-256 mismatch: fail closed")
    return {"filename": pbf.name, "bytes": total, "sha256": digest.hexdigest(),
            "control_result": "PASS", "limitation": "byte equality and initial header marker only; map and source not authenticated"}


def run_national_probes(
    probes: tuple[NationalProbe, ...],
    *,
    dataset_ref: str,
    transport_profile: str,
    base_url: str = "http://127.0.0.1:5000",
    max_snap_meters: float = 500.0,
) -> dict[str, object]:
    """Run geographic *spot checks*. Report every gap and failed probe.

    A pass in this routine never means nationwide coverage. The local OSRM
    operator and PBF source have to be independently verified.
    """
    if not probes:
        raise NationalProbeError("at least one probe is required")
    results = []
    for probe in probes:
        try:
            response = fetch_local_osrm_table(
                [probe.origin], [probe.destination],
                dataset_ref=dataset_ref,
                transport_profile=transport_profile,
                base_url=base_url,
                max_snap_meters=max_snap_meters,
            )
            duration = response.matrix.pickup_seconds.get((probe.origin.id, probe.destination.id))
            if duration is None:
                result = NationalProbeResult(probe.id, probe.kind, probe.regions, "FAIL", None,
                                             "NO_ROUTE_OR_UNREACHABLE", response.request_sha256,
                                             response.matrix.provenance.response_sha256)
            else:
                result = NationalProbeResult(probe.id, probe.kind, probe.regions, "PASS", duration,
                                             None, response.request_sha256,
                                             response.matrix.provenance.response_sha256)
        except MatrixInputError as exc:
            result = NationalProbeResult(probe.id, probe.kind, probe.regions, "FAIL", None,
                                         str(exc), None, None)
        results.append(result)
    attempted_regions = {reg for probe in probes for reg in probe.regions}
    covered_by_success = {reg for item in results if item.control_result == "PASS"
                          for reg in item.regions}
    return {
        "country_code": "PE",
        "probe_results": [item.__dict__ for item in results],
        "jurisdictions_total": len(PERU_JURISDICTIONS),
        "jurisdictions_with_probe": sorted(attempted_regions),
        "jurisdictions_without_probe": sorted(PERU_JURISDICTIONS - attempted_regions),
        "jurisdictions_with_passing_probe": sorted(covered_by_success),
        "counts": {"probes_total": len(results),
                   "queries_pass": sum(item.control_result == "PASS" for item in results),
                   "queries_fail": sum(item.control_result == "FAIL" for item in results)},
        "route_query_control_result": "PASS" if all(item.control_result == "PASS" for item in results) else "FAIL",
        "nationwide_coverage_control_result": "NOT_VERIFIED",
        "eta_accuracy_control_result": "NOT_VERIFIED",
        "road_data_quality_control_result": "NOT_VERIFIED",
        "candidate_decision": "BLOCKED",
        "candidate_decision_reason_codes": ["required_control_not_verified", "missing_required_capability"],
        "warning": "Illustrative approximate coordinates; sample does not establish national coverage",
    }


def load_probes(path: Path) -> tuple[NationalProbe, ...]:
    try:
        return parse_national_probes(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, UnicodeError) as exc:
        raise NationalProbeError("invalid national scenario file") from exc
