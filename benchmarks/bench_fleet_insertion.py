"""Synthetic, deterministic local microbenchmark of insertion-cost evaluation.

The slow mode replaces the optimized candidate evaluator with the original
full RouteVisit materialization on each proposal. Both use the SAME insertion
search and selection logic, and their complete FleetPlan outputs must match.
No road map, traffic, OSRM, pricing or production workloads are involved.
"""

import json
import platform
import statistics
import time
from pathlib import Path

from desset_core import FleetVehicle, DeliveryJob, optimize_fleet_insertion
from desset_core import fleet_heuristic


def make_case(vehicle_count: int, job_count: int):
    vehicles = [FleetVehicle(f"V{i:03d}", f"S{i:03d}", 3)
                for i in range(vehicle_count)]
    jobs = [DeliveryJob(f"J{i:03d}", f"P{i:03d}", f"D{i:03d}", 1)
            for i in range(job_count)]
    # Synthetic asymmetric costs. Position indices are NOT geographic.
    nodes = [v.start_node for v in vehicles]
    nodes.extend(node for job in jobs for node in (job.pickup_node, job.delivery_node))
    position = {name: i for i, name in enumerate(nodes)}
    times = {(a, b): 1 + abs(position[a] - position[b]) * 2
             + (7 if position[a] > position[b] else 0)
             for a in nodes for b in nodes if a != b}
    return vehicles, jobs, times


def _slow_evaluator(vehicle, steps, jobs, times):
    result = fleet_heuristic._evaluate(
        vehicle.start_node, vehicle.capacity_units,
        steps, jobs, times, vehicle.max_total_seconds,
    )
    return None if result is None else result[0]


def _measure(vehicles, jobs, times, count):
    elapsed = []
    result = None
    for _ in range(count):
        start = time.perf_counter()
        result = optimize_fleet_insertion(vehicles, jobs, times)
        elapsed.append((time.perf_counter() - start) * 1000)
    return result, elapsed


def run():
    original = fleet_heuristic._insertion_cost
    records = []
    try:
        for n_vehicles, n_jobs in [(4, 8), (6, 16), (8, 24), (10, 32)]:
            vehicles, jobs, times = make_case(n_vehicles, n_jobs)
            fleet_heuristic._insertion_cost = original
            optimized, fast_times = _measure(vehicles, jobs, times, 3)
            fleet_heuristic._insertion_cost = _slow_evaluator
            old, slow_times = _measure(vehicles, jobs, times, 2)
            if old != optimized:
                raise AssertionError("optimized evaluator changed the assignment result")
            baseline_ms = statistics.median(slow_times)
            optimized_ms = statistics.median(fast_times)
            records.append({
                "vehicles": n_vehicles,
                "jobs": n_jobs,
                "served_jobs": optimized.served_job_count,
                "cost_estimated_seconds": optimized.total_estimated_travel_seconds,
                "optimized_median_ms": round(optimized_ms, 3),
                "baseline_median_ms": round(baseline_ms, 3),
                "baseline_to_optimized_speedup": round(baseline_ms / optimized_ms, 2),
                "exact_plan_equivalence": True,
            })
    finally:
        fleet_heuristic._insertion_cost = original
    return {
        "python_version": platform.python_version(),
        "machine": platform.machine(),
        "data_origin": "deterministic_synthetic_non_geographic",
        "measurement": "wall_clock_local_perfcounter_not_SLA",
        "baseline": "same_selection_logic_with_full_candidate_route_materialization",
        "optimized": "same_selection_logic_with_lightweight_candidate_feasibility",
        "not_measured": ["real_peru_roads", "traffic", "ETA", "SLA", "production_load"],
        "records": records,
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
