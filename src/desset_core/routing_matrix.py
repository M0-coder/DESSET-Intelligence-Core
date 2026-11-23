"""Offline adapter for an OSRM Table *response* supplied by the caller.

This module never downloads maps or calls an OSRM server. A verified matrix
requires separate evidence for dataset provenance, travel mode and coverage.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

MAX_MATRIX_CELLS = 10_000


class MatrixInputError(ValueError):
    """Invalid, incomplete, or unsupported matrix payload."""


@dataclass(frozen=True)
class MatrixProvenance:
    source_format: str
    dataset_ref: str
    transport_profile: str
    response_sha256: str
    dataset_verified: bool = False


@dataclass(frozen=True)
class PickupMatrix:
    pickup_seconds: Mapping[tuple[str, str], int]
    unreachable_pairs: tuple[tuple[str, str], ...]
    provenance: MatrixProvenance


def _valid_ids(ids: Sequence[str], label: str) -> tuple[str, ...]:
    if isinstance(ids, (str, bytes)) or not isinstance(ids, (tuple, list)):
        raise MatrixInputError(f"{label} must be a sequence of IDs")
    if not ids or any(not isinstance(value, str) or not value.strip() for value in ids):
        raise MatrixInputError(f"{label} must contain nonempty string IDs")
    if len(ids) != len(set(ids)):
        raise MatrixInputError(f"{label} contains duplicate IDs")
    return tuple(ids)


def _valid_label(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise MatrixInputError(f"{label} must be a nonempty label (max 256 chars)")
    return value


def parse_osrm_table(
    response: Mapping[str, object],
    *,
    courier_ids: Sequence[str],
    order_ids: Sequence[str],
    dataset_ref: str,
    transport_profile: str,
) -> PickupMatrix:
    """Parse OSRM Table durations ordered couriers (rows) -> orders (columns).

    OSRM durations are seconds; positive fractional seconds are rounded UP.
    ``null`` indicates unreachable and is never imputed. Nonempty
    ``fallback_speed_cells`` is rejected because fallback times are not routed.

    ``dataset_ref`` and ``transport_profile`` are caller DECLARATIONS, not proof.
    The SHA-256 identifies response content, not the authenticity of its source.
    """
    sources = _valid_ids(courier_ids, "courier_ids")
    destinations = _valid_ids(order_ids, "order_ids")
    if len(sources) * len(destinations) > MAX_MATRIX_CELLS:
        raise MatrixInputError("matrix exceeds prototype size limit")
    dataset_ref = _valid_label(dataset_ref, "dataset_ref")
    transport_profile = _valid_label(transport_profile, "transport_profile")
    if not isinstance(response, Mapping):
        raise MatrixInputError("OSRM response must be a JSON mapping")
    if response.get("code") != "Ok":
        raise MatrixInputError("OSRM response code is not Ok")
    if response.get("fallback_speed_cells"):
        raise MatrixInputError("OSRM fallback_speed_cells are not routed times")
    if "fallback_speed_cells" in response and not isinstance(
        response["fallback_speed_cells"], list
    ):
        raise MatrixInputError("OSRM fallback_speed_cells must be a list")

    durations = response.get("durations")
    if not isinstance(durations, list) or len(durations) != len(sources):
        raise MatrixInputError("duration row count differs from courier count")

    times: dict[tuple[str, str], int] = {}
    unreachable: list[tuple[str, str]] = []
    for courier_id, row in zip(sources, durations, strict=True):
        if not isinstance(row, list) or len(row) != len(destinations):
            raise MatrixInputError("duration column count differs from order count")
        for order_id, value in zip(destinations, row, strict=True):
            pair = (courier_id, order_id)
            if value is None:
                unreachable.append(pair)
                continue
            if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
                raise MatrixInputError("durations must be finite nonnegative seconds or null")
            times[pair] = math.ceil(value)

    try:
        fingerprint = hashlib.sha256(
            json.dumps(
                response, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
    except (TypeError, ValueError) as exc:
        raise MatrixInputError("OSRM response must be valid JSON data") from exc

    return PickupMatrix(
        pickup_seconds=MappingProxyType(times),
        unreachable_pairs=tuple(unreachable),
        provenance=MatrixProvenance(
            source_format="osrm-table-v1",
            dataset_ref=dataset_ref,
            transport_profile=transport_profile,
            response_sha256=fingerprint,
        ),
    )
