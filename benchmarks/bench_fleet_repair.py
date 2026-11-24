"""Reproducible synthetic quality-and-runtime comparison. NOT a road/traffic SLA."""

import json
import platform
import random
import statistics
import time

from desset_core import (
    DeliveryJob,
    FleetVehicle,
    optimize_fleet_insertion,
    optimize_fleet_repaired,
)


def case(seed, n_vehicles, n_jobs, probability):
    rng = random.Random(seed)
    vehicles = [FleetVehicle(f"V{i:03d}", f"S{i:03d}", rng.randint(1, 3),
                             rng.choice([None, 80, 150]))
                for i in range(n_vehicles)]
    jobs = [DeliveryJob(f"J{i:03d}", f"P{i:03d}", f"D{i:03d}", rng.randint(1, 3))
            for i in range(n_jobs)]
    nodes = [v.start_node for v in vehicles]
    nodes.extend(n for j in jobs for n in (j.pickup_node, j.delivery_node))
    arcs = {(a, b): rng.randint(1, 25) for a in nodes for b in nodes
            if a != b and rng.random() < probability}
    return vehicles, jobs, arcs


def measured(fn, vehicles, jobs, arcs):
    tic = time.perf_counter()
    result = fn(vehicles, jobs, arcs)
    return result, round((time.perf_counter() - tic) * 1000, 3)


def run():
    records = []
    for n_vehicles, n_jobs, probability, seeds in [
        (3, 7, 0.65, list(range(101, 111))),
        (6, 16, 0.60, list(range(201, 211))),
        (10, 32, 0.55, list(range(301, 305))),
    ]:
        deltas = []
        time_base, time_repair = [], []
        improvements = 0
        total_base, total_repair = 0, 0
        for seed in seeds:
            vehicles, jobs, arcs = case(seed, n_vehicles, n_jobs, probability)
            a, ms_a = measured(optimize_fleet_insertion, vehicles, jobs, arcs)
            b, ms_b = measured(optimize_fleet_repaired, vehicles, jobs, arcs)
            if b.served_job_count < a.served_job_count:
                raise AssertionError("repair lost served jobs")
            if (b.served_job_count == a.served_job_count and
                    b.total_estimated_travel_seconds > a.total_estimated_travel_seconds):
                raise AssertionError("repair raised cost without serving more jobs")
            delta = b.served_job_count - a.served_job_count
            improvements += delta > 0
            deltas.append(delta)
            total_base += a.served_job_count
            total_repair += b.served_job_count
            time_base.append(ms_a)
            time_repair.append(ms_b)
        records.append({
            "vehicles": n_vehicles, "jobs": n_jobs, "arc_probability": probability,
            "seeds": seeds, "samples": len(seeds),
            "baseline_served_sum": total_base, "repaired_served_sum": total_repair,
            "scenarios_with_more_served": improvements,
            "served_delta_values": deltas,
            "baseline_wallclock_median_ms": statistics.median(time_base),
            "repair_wallclock_median_ms": statistics.median(time_repair),
            "paired_runtime_median_ratio": round(statistics.median(
                [b / max(a, 0.001) for a, b in zip(time_base, time_repair, strict=True)]), 3),
        })
    return {"python": platform.python_version(), "data": "synthetic_sparse_directed_fixed_seeds",
            "metric": "per_instance_wallclock_sequential_no_warmup_not_SLA",
            "quality": "served_priority_then_total_travel_seconds_only",
            "not_verified": ["real_peru_roads", "ETA", "production_load", "p95_p99"],
            "records": records}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
