"""Exact small-batch pickup-and-delivery routing for one vehicle.

The caller supplies a *directed* matrix of estimated road travel times; this
module never creates road paths or measures travel time. Every job must be
picked up before it is delivered. This is not a nationwide routing service.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache

from .routing_matrix import MAX_DURATION_SECONDS

MAX_JOBS = 7  # Exact DP; deliberate complexity guard, not operational capacity.
ALGORITHM_VERSION = "multistop-exact-v0.1"


class RouteInputError(ValueError):
    """Invalid contract for a multi-stop optimization request."""


class NoFeasibleRouteError(ValueError):
    """No route visits every required pickup and delivery under constraints."""


@dataclass(frozen=True)
class DeliveryJob:
    id: str
    pickup_node: str
    delivery_node: str
    load_units: int


@dataclass(frozen=True)
class RouteVisit:
    job_id: str
    action: str  # 'pickup' or 'delivery'
    node: str
    incoming_seconds: int
    onboard_units_after: int


@dataclass(frozen=True)
class MultiStopPlan:
    algorithm_version: str
    start_node: str
    vehicle_capacity_units: int
    visits: tuple[RouteVisit, ...]
    total_estimated_travel_seconds: int


def _nonempty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise RouteInputError(f"{label} must be a nonempty string up to 256 characters")
    return value


def _positive(value: object, label: str) -> int:
    if type(value) is not int or not 1 <= value <= MAX_DURATION_SECONDS:
        raise RouteInputError(f"{label} must be a positive bounded integer")
    return value


def optimize_multistop(
    start_node: str,
    vehicle_capacity_units: int,
    jobs: Sequence[DeliveryJob],
    travel_seconds: Mapping[tuple[str, str], int],
    *,
    max_total_seconds: int | None = None,
) -> MultiStopPlan:
    """Minimize total travel time subject to precedence and onboard capacity.

    All jobs are mandatory: an absent directed road arc is not guessed or
    replaced with a straight-line estimate. Stops are unique (including the
    vehicle origin) so origin/waypoint binding stays unambiguous. The tour does
    not return to the origin; neither service times nor time windows apply.

    For a batch of at most 7 jobs, an exact memoized dynamic program evaluates
    feasible pickup/delivery sequences. Equal-cost solutions break ties by
    job ID, then stop action. Results are independent of input job order.
    """
    origin = _nonempty(start_node, "start_node")
    capacity = _positive(vehicle_capacity_units, "vehicle_capacity_units")
    if not isinstance(jobs, (list, tuple)) or len(jobs) > MAX_JOBS:
        raise RouteInputError(f"jobs must be a list/tuple of up to {MAX_JOBS} jobs")
    if not isinstance(travel_seconds, Mapping):
        raise RouteInputError("travel_seconds must be a mapping")
    if max_total_seconds is not None and (
        type(max_total_seconds) is not int or not 0 <= max_total_seconds <= MAX_DURATION_SECONDS
    ):
        raise RouteInputError("max_total_seconds must be a bounded nonnegative integer or null")
    seen_ids: set[str] = set()
    nodes = {origin}
    for job in jobs:
        if not isinstance(job, DeliveryJob):
            raise RouteInputError("jobs must contain DeliveryJob records")
        job_id = _nonempty(job.id, "job id")
        pickup = _nonempty(job.pickup_node, "pickup_node")
        delivery = _nonempty(job.delivery_node, "delivery_node")
        units = _positive(job.load_units, "load_units")
        if job_id in seen_ids:
            raise RouteInputError("duplicate job ID")
        if pickup in nodes or delivery in nodes or pickup == delivery:
            raise RouteInputError("all origin, pickup and delivery nodes must be distinct")
        if units > capacity:
            raise NoFeasibleRouteError("a job exceeds vehicle capacity")
        seen_ids.add(job_id)
        nodes.add(pickup)
        nodes.add(delivery)
    for pair, seconds in travel_seconds.items():
        if (
            not isinstance(pair, tuple)
            or len(pair) != 2
            or not all(isinstance(node, str) and node in nodes for node in pair)
            or type(seconds) is not int
            or not 0 <= seconds <= MAX_DURATION_SECONDS
        ):
            raise RouteInputError("matrix contains invalid directed arc, node or duration")
    ordered = tuple(sorted(jobs, key=lambda job: job.id))
    n = len(ordered)
    done_mask = (1 << n) - 1
    loads = tuple(job.load_units for job in ordered)
    pickup_nodes = tuple(job.pickup_node for job in ordered)
    delivery_nodes = tuple(job.delivery_node for job in ordered)

    @lru_cache(maxsize=None)
    def solve(picked: int, delivered: int, at: str) -> tuple[int, tuple[tuple[int, int], ...]] | None:
        if delivered == done_mask:
            return (0, ())
        onboard = sum(
            loads[i] for i in range(n)
            if picked & (1 << i) and not delivered & (1 << i)
        )
        best: tuple[int, tuple[tuple[int, int], ...]] | None = None
        for index in range(n):
            bit = 1 << index
            if not picked & bit:
                if onboard + loads[index] > capacity:
                    continue
                target, next_picked, next_delivered, action = (
                    pickup_nodes[index], picked | bit, delivered, 0
                )
            elif not delivered & bit:
                target, next_picked, next_delivered, action = (
                    delivery_nodes[index], picked, delivered | bit, 1
                )
            else:
                continue
            leg = travel_seconds.get((at, target))
            if leg is None:
                continue
            suffix = solve(next_picked, next_delivered, target)
            if suffix is None:
                continue
            proposal = (leg + suffix[0], ((index, action),) + suffix[1])
            if best is None or proposal < best:
                best = proposal
        return best

    solution = solve(0, 0, origin)
    if solution is None or (
        max_total_seconds is not None and solution[0] > max_total_seconds
    ):
        raise NoFeasibleRouteError("no feasible complete route with supplied travel times")
    visits: list[RouteVisit] = []
    at = origin
    onboard = 0
    for index, action in solution[1]:
        job = ordered[index]
        node = job.pickup_node if action == 0 else job.delivery_node
        onboard += job.load_units if action == 0 else -job.load_units
        visits.append(RouteVisit(
            job_id=job.id,
            action="pickup" if action == 0 else "delivery",
            node=node,
            incoming_seconds=travel_seconds[(at, node)],
            onboard_units_after=onboard,
        ))
        at = node
    return MultiStopPlan(
        algorithm_version=ALGORITHM_VERSION,
        start_node=origin,
        vehicle_capacity_units=capacity,
        visits=tuple(visits),
        total_estimated_travel_seconds=solution[0],
    )
