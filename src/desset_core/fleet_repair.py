"""Bounded coverage repair atop deterministic fleet insertion.

Eject a served job and solve an exact *small* receiving-route subproblem
containing that job and a pending job. The rest of the fleet is unchanged.
This is local search, NOT a proof of globally optimal coverage or cost.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .fleet import FleetPlan, FleetVehicle, VehicleAssignment
from .fleet_heuristic import _evaluate, optimize_fleet_insertion
from .multistop import (
    DeliveryJob,
    MultiStopPlan,
    NoFeasibleRouteError,
    optimize_multistop,
)

ALGORITHM_VERSION = "fleet-repair-v0.1"
MAX_REPAIR_ROUNDS = 2
MAX_REPAIR_EXACT_CALLS_PER_ROUND = 48
MAX_REPAIR_RECEIVING_JOBS = 5


def _steps(route: VehicleAssignment | None) -> tuple[tuple[str, int], ...]:
    if route is None:
        return ()
    return tuple((visit.job_id, 0 if visit.action == "pickup" else 1)
                 for visit in route.route.visits)


def _make_assignment(
    vehicle: FleetVehicle,
    steps: tuple[tuple[str, int], ...],
    jobs: Mapping[str, DeliveryJob],
    times: Mapping[tuple[str, str], int],
) -> VehicleAssignment | None | bool:
    """False means invalid; None represents an intentionally idle vehicle."""
    if not steps:
        return None
    evaluated = _evaluate(
        vehicle.start_node, vehicle.capacity_units, steps,
        jobs, times, vehicle.max_total_seconds,
    )
    if evaluated is None:
        return False
    cost, visits = evaluated
    route = MultiStopPlan(
        algorithm_version=ALGORITHM_VERSION,
        start_node=vehicle.start_node,
        vehicle_capacity_units=vehicle.capacity_units,
        visits=visits,
        total_estimated_travel_seconds=cost,
    )
    return VehicleAssignment(
        vehicle_id=vehicle.id,
        job_ids=tuple(sorted({ident for ident, _ in steps})),
        route=route,
    )


def _exact_receiver(
    vehicle: FleetVehicle,
    chosen: tuple[DeliveryJob, ...],
    times: Mapping[tuple[str, str], int],
) -> VehicleAssignment | None:
    if len(chosen) > MAX_REPAIR_RECEIVING_JOBS:
        return None
    if any(job.load_units > vehicle.capacity_units for job in chosen):
        return None
    nodes = {vehicle.start_node}
    for job in chosen:
        nodes.update((job.pickup_node, job.delivery_node))
    restricted = {(src, dst): seconds for (src, dst), seconds in times.items()
                  if src in nodes and dst in nodes}
    try:
        route = optimize_multistop(
            vehicle.start_node,
            vehicle.capacity_units,
            chosen,
            restricted,
            max_total_seconds=vehicle.max_total_seconds,
        )
    except NoFeasibleRouteError:
        return None
    return VehicleAssignment(vehicle.id, tuple(sorted(job.id for job in chosen)), route)


def _repair_round(
    initial: FleetPlan,
    fleet: tuple[FleetVehicle, ...],
    jobs: Mapping[str, DeliveryJob],
    times: Mapping[tuple[str, str], int],
) -> FleetPlan | None:
    if not initial.unassigned_job_ids or not initial.routes:
        return None
    active = {route.vehicle_id: route for route in initial.routes}
    by_vehicle = {vehicle.id: vehicle for vehicle in fleet}
    candidates: list[tuple[int, str, str, str, FleetPlan]] = []
    calls = 0
    for pending in initial.unassigned_job_ids:
        for donor_route in initial.routes:
            donor_id = donor_route.vehicle_id
            donor_vehicle = by_vehicle[donor_id]
            donor_steps = _steps(donor_route)
            for displaced in donor_route.job_ids:
                remaining_steps = tuple(s for s in donor_steps if s[0] != displaced)
                # A sparse directed road matrix may not connect the predecessor
                # to the successor after deleting a job: reject such a change.
                remaining = _make_assignment(donor_vehicle, remaining_steps, jobs, times)
                for receiver in fleet:
                    receiver_id = receiver.id
                    if receiver_id != donor_id and remaining is False:
                        continue
                    previous_receiver = active.get(receiver_id)
                    retained = (tuple(ident for ident in donor_route.job_ids
                                      if ident != displaced) if receiver_id == donor_id
                                else (previous_receiver.job_ids if previous_receiver else ()))
                    chosen_ids = tuple(sorted((*retained, displaced, pending)))
                    if len(chosen_ids) > MAX_REPAIR_RECEIVING_JOBS:
                        continue
                    calls += 1
                    new_receiver = _exact_receiver(
                        receiver, tuple(jobs[ident] for ident in chosen_ids), times,
                    )
                    if new_receiver is not None:
                        updated = dict(active)
                        if receiver_id != donor_id:
                            if remaining is None:
                                updated.pop(donor_id, None)
                            else:
                                updated[donor_id] = remaining
                        updated[receiver_id] = new_receiver
                        routes = tuple(updated[vehicle.id] for vehicle in fleet
                                       if vehicle.id in updated)
                        served = tuple(ident for route in routes for ident in route.job_ids)
                        if len(served) != len(set(served)):
                            raise AssertionError("internal repair duplicated a job")
                        if len(served) != initial.served_job_count + 1:
                            raise AssertionError("internal repair lost a served job")
                        cost = sum(route.route.total_estimated_travel_seconds for route in routes)
                        plan = FleetPlan(
                            ALGORITHM_VERSION,
                            routes,
                            tuple(ident for ident in initial.unassigned_job_ids
                                  if ident != pending),
                            len(served),
                            cost,
                        )
                        candidates.append((cost, pending, displaced, receiver_id, plan))
                    if calls >= MAX_REPAIR_EXACT_CALLS_PER_ROUND:
                        break
                if calls >= MAX_REPAIR_EXACT_CALLS_PER_ROUND:
                    break
            if calls >= MAX_REPAIR_EXACT_CALLS_PER_ROUND:
                break
        if calls >= MAX_REPAIR_EXACT_CALLS_PER_ROUND:
            break
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[:4])[4]


def optimize_fleet_repaired(
    vehicles: Sequence[FleetVehicle],
    jobs: Sequence[DeliveryJob],
    travel_seconds: Mapping[tuple[str, str], int],
) -> FleetPlan:
    """Coverage-monotone bounded repair over the insertion heuristic.

    A successful round adds exactly one previously unassigned job, retaining
    every served job. If repair is impossible within its fixed search budget,
    the baseline is returned unchanged. Improving coverage may raise cost;
    this follows the fleet objective's lexicographic priority.
    """
    best = optimize_fleet_insertion(vehicles, jobs, travel_seconds)
    if not best.unassigned_job_ids:
        return best
    by_job = {job.id: job for job in jobs}
    fleet = tuple(sorted(vehicles, key=lambda vehicle: vehicle.id))
    for _ in range(MAX_REPAIR_ROUNDS):
        improved = _repair_round(best, fleet, by_job, travel_seconds)
        if improved is None:
            break
        best = improved
    return best
