"""Exact small-fleet assignment plus pickup/delivery sequencing.

This is a deterministic, bounded offline optimizer. Road times must be supplied;
no traffic, fares, driver's shifts, operational commitments or nationwide
coverage are measured or implied here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .multistop import (
    DeliveryJob,
    MultiStopPlan,
    NoFeasibleRouteError,
    RouteInputError,
    optimize_multistop,
)
from .routing_matrix import MAX_DURATION_SECONDS

ALGORITHM_VERSION = "fleet-exact-v0.1"
MAX_FLEET_VEHICLES = 4
MAX_FLEET_JOBS = 6


@dataclass(frozen=True)
class FleetVehicle:
    id: str
    start_node: str
    capacity_units: int
    max_total_seconds: int | None = None


@dataclass(frozen=True)
class VehicleAssignment:
    vehicle_id: str
    job_ids: tuple[str, ...]
    route: MultiStopPlan


@dataclass(frozen=True)
class FleetPlan:
    algorithm_version: str
    routes: tuple[VehicleAssignment, ...]
    unassigned_job_ids: tuple[str, ...]
    served_job_count: int
    total_estimated_travel_seconds: int


def _label(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise RouteInputError(f"{label} must be a nonempty string up to 256 characters")
    return value


def _validate(
    vehicles: Sequence[FleetVehicle],
    jobs: Sequence[DeliveryJob],
    travel_seconds: Mapping[tuple[str, str], int],
) -> tuple[tuple[FleetVehicle, ...], tuple[DeliveryJob, ...]]:
    if not isinstance(vehicles, (list, tuple)) or len(vehicles) > MAX_FLEET_VEHICLES:
        raise RouteInputError(f"vehicles must be a list/tuple of up to {MAX_FLEET_VEHICLES}")
    if not isinstance(jobs, (list, tuple)) or len(jobs) > MAX_FLEET_JOBS:
        raise RouteInputError(f"jobs must be a list/tuple of up to {MAX_FLEET_JOBS}")
    if not isinstance(travel_seconds, Mapping):
        raise RouteInputError("travel_seconds must be a mapping")

    vehicle_ids: set[str] = set()
    nodes: set[str] = set()
    for vehicle in vehicles:
        if not isinstance(vehicle, FleetVehicle):
            raise RouteInputError("vehicles must contain FleetVehicle records")
        vehicle_id = _label(vehicle.id, "vehicle id")
        origin = _label(vehicle.start_node, "vehicle start_node")
        if vehicle_id in vehicle_ids:
            raise RouteInputError("duplicate vehicle ID")
        if type(vehicle.capacity_units) is not int or not (
            1 <= vehicle.capacity_units <= MAX_DURATION_SECONDS
        ):
            raise RouteInputError("vehicle capacity must be a bounded positive integer")
        if vehicle.max_total_seconds is not None and (
            type(vehicle.max_total_seconds) is not int
            or not 0 <= vehicle.max_total_seconds <= MAX_DURATION_SECONDS
        ):
            raise RouteInputError("vehicle max_total_seconds must be bounded or null")
        vehicle_ids.add(vehicle_id)
        nodes.add(origin)

    job_ids: set[str] = set()
    for job in jobs:
        if not isinstance(job, DeliveryJob):
            raise RouteInputError("jobs must contain DeliveryJob records")
        job_id = _label(job.id, "job id")
        pickup = _label(job.pickup_node, "pickup_node")
        delivery = _label(job.delivery_node, "delivery_node")
        if job_id in job_ids:
            raise RouteInputError("duplicate job ID")
        if pickup == delivery or pickup in nodes or delivery in nodes:
            raise RouteInputError("pickup and delivery nodes must be distinct from all origins/stops")
        if type(job.load_units) is not int or not 1 <= job.load_units <= MAX_DURATION_SECONDS:
            raise RouteInputError("job load must be a bounded positive integer")
        job_ids.add(job_id)
        nodes.update((pickup, delivery))

    for pair, seconds in travel_seconds.items():
        if (
            not isinstance(pair, tuple)
            or len(pair) != 2
            or not all(isinstance(node, str) and node in nodes for node in pair)
            or type(seconds) is not int
            or not 0 <= seconds <= MAX_DURATION_SECONDS
        ):
            raise RouteInputError("matrix contains invalid directed arc, node or duration")
    return (
        tuple(sorted(vehicles, key=lambda vehicle: vehicle.id)),
        tuple(sorted(jobs, key=lambda job: job.id)),
    )


def optimize_fleet(
    vehicles: Sequence[FleetVehicle],
    jobs: Sequence[DeliveryJob],
    travel_seconds: Mapping[tuple[str, str], int],
) -> FleetPlan:
    """Maximize served jobs, then minimize fleet travel seconds (exact, bounded).

    Each job is assigned to at most one vehicle; its pickup must precede
    delivery. A vehicle can carry multiple jobs up to its onboard capacity.
    Missing directed road arcs are treated as infeasible; zero jobs is valid.
    A job may remain unassigned if no complete feasible route exists.

    This is NOT a solution to large-scale VRP, time windows, driver fairness,
    service times, or real ETA. The 4-vehicle/6-job limits are deliberate.
    """
    fleet, ordered = _validate(vehicles, jobs, travel_seconds)
    n = len(ordered)
    if not fleet or not ordered:
        return FleetPlan(
            ALGORITHM_VERSION, (), tuple(j.id for j in ordered), 0, 0
        )

    # Options per vehicle: subset -> exact route, including an idle option.
    options_by_vehicle: list[dict[int, MultiStopPlan | None]] = []
    for vehicle in fleet:
        options: dict[int, MultiStopPlan | None] = {0: None}
        for subset in range(1, 1 << n):
            selected = tuple(job for i, job in enumerate(ordered) if subset & (1 << i))
            if any(job.load_units > vehicle.capacity_units for job in selected):
                continue
            relevant_nodes = {vehicle.start_node}
            for job in selected:
                relevant_nodes.add(job.pickup_node)
                relevant_nodes.add(job.delivery_node)
            matrix = {
                (src, dst): seconds
                for (src, dst), seconds in travel_seconds.items()
                if src in relevant_nodes and dst in relevant_nodes
            }
            try:
                options[subset] = optimize_multistop(
                    vehicle.start_node,
                    vehicle.capacity_units,
                    selected,
                    matrix,
                    max_total_seconds=vehicle.max_total_seconds,
                )
            except NoFeasibleRouteError:
                continue
        options_by_vehicle.append(options)

    # State mask = set of jobs already served. Compare for each mask first by
    # minimum travel time, then prefer earlier vehicles on exact cost ties.
    states: dict[int, tuple[int, tuple[int, ...]]] = {0: (0, ())}
    for options in options_by_vehicle:
        next_states: dict[int, tuple[int, tuple[int, ...]]] = {}
        for used, (base_cost, choices) in states.items():
            for subset, route in options.items():
                if used & subset:
                    continue
                destination = used | subset
                candidate = (
                    base_cost + (route.total_estimated_travel_seconds if route else 0),
                    choices + (subset,),
                )
                previous = next_states.get(destination)
                if previous is None or (
                    candidate[0], tuple(-mask for mask in candidate[1])
                ) < (
                    previous[0], tuple(-mask for mask in previous[1])
                ):
                    next_states[destination] = candidate
        states = next_states

    winning_mask, (total_cost, chosen_masks) = min(
        states.items(),
        key=lambda item: (
            -item[0].bit_count(), item[1][0], tuple(-mask for mask in item[1][1])
        ),
    )
    routes = []
    for vehicle, options, subset in zip(fleet, options_by_vehicle, chosen_masks, strict=True):
        if subset:
            route = options[subset]
            assert route is not None
            routes.append(VehicleAssignment(
                vehicle_id=vehicle.id,
                job_ids=tuple(ordered[i].id for i in range(n) if subset & (1 << i)),
                route=route,
            ))
    return FleetPlan(
        algorithm_version=ALGORITHM_VERSION,
        routes=tuple(routes),
        unassigned_job_ids=tuple(ordered[i].id for i in range(n) if not winning_mask & (1 << i)),
        served_job_count=winning_mask.bit_count(),
        total_estimated_travel_seconds=total_cost,
    )
