"""Deterministic bounded insertion heuristic for larger pickup/delivery fleets.

This is a feasibility-preserving *heuristic*, not an optimal VRP solver. Directed
travel estimates come from the caller; the optimizer neither routes roads nor
claims business/ETA outcomes. No global optimality guarantee is made.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .fleet import FleetPlan, FleetVehicle, VehicleAssignment
from .multistop import DeliveryJob, MultiStopPlan, RouteInputError, RouteVisit
from .routing_matrix import MAX_DURATION_SECONDS

ALGORITHM_VERSION = "fleet-insertion-v0.1"
MAX_HEURISTIC_VEHICLES = 24
MAX_HEURISTIC_JOBS = 80
MAX_HEURISTIC_JOBS_PER_VEHICLE = 20

# (job ID, 0 for pickup / 1 for delivery)
type _Stop = tuple[str, int]


def _label(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise RouteInputError(f"{field} must be a nonempty string up to 256 characters")
    return value


def _validate(
    vehicles: Sequence[FleetVehicle],
    jobs: Sequence[DeliveryJob],
    times: Mapping[tuple[str, str], int],
) -> tuple[tuple[FleetVehicle, ...], tuple[DeliveryJob, ...]]:
    if not isinstance(vehicles, (tuple, list)) or len(vehicles) > MAX_HEURISTIC_VEHICLES:
        raise RouteInputError("invalid number or type of fleet vehicles")
    if not isinstance(jobs, (tuple, list)) or len(jobs) > MAX_HEURISTIC_JOBS:
        raise RouteInputError("invalid number or type of delivery jobs")
    if not isinstance(times, Mapping):
        raise RouteInputError("times must be a directed-arc mapping")
    vehicle_ids: set[str] = set()
    job_ids: set[str] = set()
    nodes: set[str] = set()
    for vehicle in vehicles:
        if not isinstance(vehicle, FleetVehicle):
            raise RouteInputError("vehicles must be FleetVehicle records")
        ident = _label(vehicle.id, "vehicle id")
        origin = _label(vehicle.start_node, "start node")
        if ident in vehicle_ids:
            raise RouteInputError("duplicate vehicle id")
        if type(vehicle.capacity_units) is not int or not 1 <= vehicle.capacity_units <= MAX_DURATION_SECONDS:
            raise RouteInputError("invalid vehicle capacity")
        if vehicle.max_total_seconds is not None and (
            type(vehicle.max_total_seconds) is not int
            or not 0 <= vehicle.max_total_seconds <= MAX_DURATION_SECONDS
        ):
            raise RouteInputError("invalid vehicle route-duration budget")
        vehicle_ids.add(ident)
        nodes.add(origin)
    for job in jobs:
        if not isinstance(job, DeliveryJob):
            raise RouteInputError("jobs must be DeliveryJob records")
        ident = _label(job.id, "job id")
        pickup = _label(job.pickup_node, "pickup node")
        delivery = _label(job.delivery_node, "delivery node")
        if ident in job_ids:
            raise RouteInputError("duplicate job id")
        if pickup == delivery or pickup in nodes or delivery in nodes:
            raise RouteInputError("all pickup/delivery nodes must differ from origins and stops")
        if type(job.load_units) is not int or not 1 <= job.load_units <= MAX_DURATION_SECONDS:
            raise RouteInputError("invalid job load")
        job_ids.add(ident)
        nodes.update((pickup, delivery))
    for pair, seconds in times.items():
        if (
            not isinstance(pair, tuple)
            or len(pair) != 2
            or any(not isinstance(node, str) or node not in nodes for node in pair)
            or type(seconds) is not int
            or not 0 <= seconds <= MAX_DURATION_SECONDS
        ):
            raise RouteInputError("invalid travel arc or duration")
    return (
        tuple(sorted(vehicles, key=lambda item: item.id)),
        tuple(sorted(jobs, key=lambda item: item.id)),
    )


def _evaluate(
    origin: str,
    capacity: int,
    steps: tuple[_Stop, ...],
    jobs: Mapping[str, DeliveryJob],
    times: Mapping[tuple[str, str], int],
    limit: int | None,
) -> tuple[int, tuple[RouteVisit, ...]] | None:
    at = origin
    onboard = 0
    picked: set[str] = set()
    delivered: set[str] = set()
    total = 0
    visits: list[RouteVisit] = []
    for ident, action in steps:
        job = jobs[ident]
        if action == 0:
            if ident in picked:
                return None
            picked.add(ident)
            onboard += job.load_units
            node = job.pickup_node
        else:
            if ident not in picked or ident in delivered:
                return None
            delivered.add(ident)
            onboard -= job.load_units
            node = job.delivery_node
        if onboard < 0 or onboard > capacity:
            return None
        seconds = times.get((at, node))
        if seconds is None:
            return None
        total += seconds
        if limit is not None and total > limit:
            return None
        visits.append(RouteVisit(
            job_id=ident,
            action="pickup" if action == 0 else "delivery",
            node=node,
            incoming_seconds=seconds,
            onboard_units_after=onboard,
        ))
        at = node
    if picked != delivered or onboard:
        return None
    return total, tuple(visits)


def _insertion_cost(
    vehicle: FleetVehicle,
    steps: tuple[_Stop, ...],
    jobs: Mapping[str, DeliveryJob],
    times: Mapping[tuple[str, str], int],
) -> int | None:
    """Fast feasibility test for insertion-produced (already ordered) steps.

    This is intentionally distinct from _evaluate: expensive visits and
    precedence bookkeeping are constructed only for committed assignments.
    """
    at = vehicle.start_node
    onboard = 0
    total = 0
    for ident, action in steps:
        job = jobs[ident]
        if action == 0:
            onboard += job.load_units
            next_node = job.pickup_node
        else:
            onboard -= job.load_units
            next_node = job.delivery_node
        if onboard < 0 or onboard > vehicle.capacity_units:
            return None
        travel = times.get((at, next_node))
        if travel is None:
            return None
        total += travel
        if vehicle.max_total_seconds is not None and total > vehicle.max_total_seconds:
            return None
        at = next_node
    return total if onboard == 0 else None


def _best_insertion(
    vehicle: FleetVehicle,
    current: tuple[_Stop, ...],
    job: DeliveryJob,
    jobs: Mapping[str, DeliveryJob],
    times: Mapping[tuple[str, str], int],
) -> tuple[int, tuple[_Stop, ...]] | None:
    best: tuple[int, tuple[_Stop, ...]] | None = None
    for pickup_pos in range(len(current) + 1):
        with_pickup = current[:pickup_pos] + ((job.id, 0),) + current[pickup_pos:]
        for delivery_pos in range(pickup_pos + 1, len(with_pickup) + 1):
            proposal = (
                with_pickup[:delivery_pos] + ((job.id, 1),) + with_pickup[delivery_pos:]
            )
            cost = _insertion_cost(vehicle, proposal, jobs, times)
            if cost is not None and (
                best is None or (cost, proposal) < (best[0], best[1])
            ):
                best = (cost, proposal)
    return best


def optimize_fleet_insertion(
    vehicles: Sequence[FleetVehicle],
    jobs: Sequence[DeliveryJob],
    travel_seconds: Mapping[tuple[str, str], int],
) -> FleetPlan:
    """Greedy, deterministic scarce-job-first pickup/delivery insertion.

    Every round chooses a job feasible for the fewest current vehicles, then
    its minimum marginal travel cost. It may lose feasible jobs or take more
    time than exact optimization. Bound is 24 vehicles, 80 jobs total and 20
    jobs per vehicle. A missing directed arc is never estimated.
    """
    fleet, ordered = _validate(vehicles, jobs, travel_seconds)
    if not fleet or not ordered:
        return FleetPlan(ALGORITHM_VERSION, (), tuple(job.id for job in ordered), 0, 0)
    by_id = {job.id: job for job in ordered}
    routes: dict[str, tuple[_Stop, ...]] = {vehicle.id: () for vehicle in fleet}
    costs: dict[str, int] = {vehicle.id: 0 for vehicle in fleet}
    pending = {job.id for job in ordered}
    # Cache feasible insertions per (job, vehicle). Only the route of the
    # assigned vehicle changes; recomputing every other vehicle is redundant.
    # No external source/cache or persisted state participates in the decision.
    fleet_by_id = {vehicle.id: vehicle for vehicle in fleet}

    def candidate_for(job_id: str, vehicle: FleetVehicle):
        job = by_id[job_id]
        if job.load_units > vehicle.capacity_units:
            return None
        current = routes[vehicle.id]
        if len(current) >= 2 * MAX_HEURISTIC_JOBS_PER_VEHICLE:
            return None
        inserted = _best_insertion(vehicle, current, job, by_id, travel_seconds)
        if inserted is None:
            return None
        cost, steps = inserted
        return cost - costs[vehicle.id], steps, cost

    cached: dict[tuple[str, str], tuple[int, tuple[_Stop, ...], int] | None] = {
        (job.id, vehicle.id): candidate_for(job.id, vehicle)
        for job in ordered for vehicle in fleet
    }
    while pending:
        winner: tuple[int, int, str, str, tuple[_Stop, ...]] | None = None
        for job_id in sorted(pending):
            feasible = [
                (value[0], vehicle.id, value[1], value[2])
                for vehicle in fleet
                if (value := cached[(job_id, vehicle.id)]) is not None
            ]
            if feasible:
                delta, vehicle_id, steps, _ = min(feasible)
                option = (len(feasible), delta, job_id, vehicle_id, steps)
                if winner is None or option < winner:
                    winner = option
        if winner is None:
            break
        _, _, job_id, vehicle_id, steps = winner
        chosen = cached[(job_id, vehicle_id)]
        assert chosen is not None
        routes[vehicle_id] = steps
        costs[vehicle_id] = chosen[2]
        pending.remove(job_id)
        # Changed route invalidates only this vehicle's insertions.
        changed_vehicle = fleet_by_id[vehicle_id]
        for other_job_id in pending:
            cached[(other_job_id, vehicle_id)] = candidate_for(other_job_id, changed_vehicle)
    assignments: list[VehicleAssignment] = []
    for vehicle in fleet:
        steps = routes[vehicle.id]
        if not steps:
            continue
        evaluated = _evaluate(
            vehicle.start_node, vehicle.capacity_units, steps,
            by_id, travel_seconds, vehicle.max_total_seconds,
        )
        assert evaluated is not None
        cost, visits = evaluated
        assigned_jobs = tuple(sorted({ident for ident, _ in steps}))
        plan = MultiStopPlan(
            algorithm_version=ALGORITHM_VERSION,
            start_node=vehicle.start_node,
            vehicle_capacity_units=vehicle.capacity_units,
            visits=visits,
            total_estimated_travel_seconds=cost,
        )
        assignments.append(VehicleAssignment(vehicle.id, assigned_jobs, plan))
    return FleetPlan(
        algorithm_version=ALGORITHM_VERSION,
        routes=tuple(assignments),
        unassigned_job_ids=tuple(sorted(pending)),
        served_job_count=len(ordered) - len(pending),
        total_estimated_travel_seconds=sum(costs.values()),
    )


def optimize_fleet_adaptive(
    vehicles: Sequence[FleetVehicle],
    jobs: Sequence[DeliveryJob],
    travel_seconds: Mapping[tuple[str, str], int],
) -> FleetPlan:
    """Select exact small-fleet optimization or the bounded insertion heuristic.

    Small instances are solved exactly under the existing INT-008 contract.
    Larger instances use a heuristic and expose their different algorithm_version.
    Neither path claims road accuracy or an operational performance SLA.
    """
    from .fleet import MAX_FLEET_JOBS, MAX_FLEET_VEHICLES, optimize_fleet

    if (
        isinstance(vehicles, (list, tuple))
        and isinstance(jobs, (list, tuple))
        and len(vehicles) <= MAX_FLEET_VEHICLES
        and len(jobs) <= MAX_FLEET_JOBS
    ):
        return optimize_fleet(vehicles, jobs, travel_seconds)
    from .fleet_repair import optimize_fleet_repaired

    return optimize_fleet_repaired(vehicles, jobs, travel_seconds)
