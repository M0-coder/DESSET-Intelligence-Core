"""Loopback-only OSRM Table client with coordinate binding and explicit failure.

This module can query an OSRM instance supplied and operated separately. It
never downloads OSM data, operates a routing engine, or verifies road accuracy.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

from .routing_matrix import MatrixInputError, PickupMatrix, parse_osrm_table

MAX_POINTS = 100  # OSRM's usual default table location limit; not a performance SLA.
MAX_RESPONSE_BYTES = 2_000_000


@dataclass(frozen=True)
class RoadPoint:
    id: str
    longitude: float
    latitude: float


@dataclass(frozen=True)
class LocalRoadMatrix:
    matrix: PickupMatrix
    request_sha256: str
    snap_distances_meters: tuple[float, ...]


def _number(value: object, name: str, lower: float, upper: float) -> float:
    if type(value) not in (int, float):
        raise MatrixInputError(f"{name} must be finite and numeric")
    try:
        finite = math.isfinite(value)
    except (OverflowError, ValueError):
        raise MatrixInputError(f"{name} must be finite and numeric") from None
    if not finite:
        raise MatrixInputError(f"{name} must be finite and numeric")
    if not lower <= value <= upper:
        raise MatrixInputError(f"{name} outside permitted range")
    return float(value)


def _points(items: Sequence[RoadPoint], label: str) -> tuple[RoadPoint, ...]:
    if not isinstance(items, (tuple, list)) or not items:
        raise MatrixInputError(f"{label} must be a nonempty list of RoadPoint")
    if len(items) > MAX_POINTS:
        raise MatrixInputError(f"{label} exceeds configured location limit")
    result: list[RoadPoint] = []
    used: set[str] = set()
    for point in items:
        if not isinstance(point, RoadPoint):
            raise MatrixInputError(f"{label} must contain RoadPoint objects")
        if not isinstance(point.id, str) or not point.id.strip() or len(point.id) > 256:
            raise MatrixInputError(f"{label} IDs must be nonempty (max 256 characters)")
        if point.id in used:
            raise MatrixInputError(f"{label} contains duplicate IDs")
        used.add(point.id)
        result.append(RoadPoint(
            point.id,
            _number(point.longitude, "longitude", -180, 180),
            _number(point.latitude, "latitude", -90, 90),
        ))
    return tuple(result)


def _loopback_port(base_url: str) -> int:
    if not isinstance(base_url, str):
        raise MatrixInputError("base_url must be a loopback URL")
    try:
        url = urlsplit(base_url)
        port = url.port
    except ValueError as exc:
        raise MatrixInputError("invalid OSRM URL or port") from exc
    if (url.scheme != "http" or url.hostname != "127.0.0.1"
            or url.username is not None or url.password is not None
            or url.path not in ("", "/") or url.query or url.fragment
            or port is None or not 1 <= port <= 65535):
        raise MatrixInputError("OSRM endpoint must be http://127.0.0.1:<port>")
    return port


def _haversine_meters(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = p2 - p1
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 6_371_000 * 2 * math.atan2(math.sqrt(a), math.sqrt(max(0, 1 - a)))


def _waypoints(response: dict, name: str, expected: Sequence[RoadPoint], limit: float) -> list[float]:
    values = response.get(name)
    if not isinstance(values, list) or len(values) != len(expected):
        raise MatrixInputError(f"OSRM {name} missing or wrong length; cannot bind coordinates")
    distances = []
    for index, (value, point) in enumerate(zip(values, expected, strict=True)):
        if not isinstance(value, dict):
            raise MatrixInputError("OSRM waypoint must be an object")
        location = value.get("location")
        if not isinstance(location, list) or len(location) != 2:
            raise MatrixInputError("OSRM waypoint location must be [lon, lat]")
        lon = _number(location[0], "snapped longitude", -180, 180)
        lat = _number(location[1], "snapped latitude", -90, 90)
        reported = _number(value.get("distance"), "OSRM snapping distance", 0, 1e8)
        computed = _haversine_meters(point.longitude, point.latitude, lon, lat)
        if max(reported, computed) > limit:
            raise MatrixInputError("OSRM waypoint snapped too far from requested coordinate")
        # Within snap tolerance, a returned waypoint could correspond to more
        # than one submitted ID. The response carries no authenticated ID, so
        # fail closed instead of silently binding an incorrect duration.
        # Compare within the source/destination side only: square matrices
        # intentionally repeat the same positions across both sides.
        if any(
            other_index != index
            and _haversine_meters(other.longitude, other.latitude, lon, lat) <= limit
            for other_index, other in enumerate(expected)
        ):
            raise MatrixInputError("OSRM waypoint identity ambiguous within snap tolerance")
        distances.append(computed)
    return distances


def fetch_local_osrm_table(
    couriers: Sequence[RoadPoint],
    pickups: Sequence[RoadPoint],
    *,
    dataset_ref: str,
    transport_profile: str,
    base_url: str = "http://127.0.0.1:5000",
    timeout_seconds: float = 3.0,
    max_snap_meters: float = 75.0,
) -> LocalRoadMatrix:
    """Query a locally-operated OSRM Table service and bind IDs to coordinates.

    Does not prove map source, profile correctness, ETA accuracy, or suitability
    for motorcycles. Raises MatrixInputError on fail-closed conditions.
    """
    sources = _points(couriers, "couriers")
    destinations = _points(pickups, "pickups")
    if len(sources) + len(destinations) > MAX_POINTS:
        raise MatrixInputError("OSRM table exceeds configured location limit")
    timeout = _number(timeout_seconds, "timeout_seconds", 0.1, 15)
    snap_limit = _number(max_snap_meters, "max_snap_meters", 0, 500)
    port = _loopback_port(base_url)
    # The local daemon has exactly one pre-built profile; URL 'driving' does
    # not select or verify a vehicle profile. Caller metadata is declarative.
    coordinates = ";".join(
        f"{p.longitude:.7f},{p.latitude:.7f}" for p in (*sources, *destinations)
    )
    source_indices = ";".join(str(i) for i in range(len(sources)))
    dest_indices = ";".join(str(i) for i in range(len(sources), len(sources) + len(destinations)))
    request_path = (
        f"/table/v1/driving/{coordinates}?sources={source_indices}"
        f"&destinations={dest_indices}&annotations=duration"
    )
    # Include IDs: geometry alone is insufficient to trace which courier/pickup
    # each index represented. This fingerprint does NOT authenticate the server.
    request_identity = {
        "method": "GET",
        "path": request_path,
        "courier_ids": [p.id for p in sources],
        "pickup_ids": [p.id for p in destinations],
    }
    try:
        identity_bytes = json.dumps(
            request_identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
    except UnicodeError as exc:
        raise MatrixInputError("request identity is not valid Unicode") from exc
    request_sha256 = hashlib.sha256(identity_bytes).hexdigest()
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request("GET", request_path, headers={"Accept": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            raise MatrixInputError(f"local OSRM HTTP returned {response.status}")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise MatrixInputError("OSRM response too large")
    except (OSError, TimeoutError, http.client.HTTPException) as exc:
        raise MatrixInputError("local OSRM unavailable or malformed HTTP response") from exc
    finally:
        connection.close()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise MatrixInputError("OSRM response is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise MatrixInputError("OSRM response must be a JSON object")
    matrix = parse_osrm_table(
        payload,
        courier_ids=[p.id for p in sources],
        order_ids=[p.id for p in destinations],
        dataset_ref=dataset_ref,
        transport_profile=transport_profile,
    )
    snaps = _waypoints(payload, "sources", sources, snap_limit)
    snaps.extend(_waypoints(payload, "destinations", destinations, snap_limit))
    return LocalRoadMatrix(matrix, request_sha256, tuple(snaps))
