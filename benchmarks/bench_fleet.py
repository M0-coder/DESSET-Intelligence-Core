"""Small-fleet synthetic microbenchmark. NOT a production performance SLA."""

import json
import platform
import statistics
import time

from desset_core import DeliveryJob, FleetVehicle, optimize_fleet


def main():
    rows = []
    for n in range(1, 7):
        vehicles = [FleetVehicle(f"V{i}", f"S{i}", 2) for i in range(3)]
        jobs = [DeliveryJob(f"J{i}", f"P{i}", f"D{i}", 1) for i in range(n)]
        nodes = [v.start_node for v in vehicles] + [
            node for j in jobs for node in (j.pickup_node, j.delivery_node)
        ]
        # In no sense are these real, calibrated or mapped journey seconds.
        matrix = {
            (a, b): 1 + (len(a) * 17 + len(b) * 31) % 13
            for a in nodes for b in nodes if a != b
        }
        times = []
        for _ in range(3):
            start = time.perf_counter()
            plan = optimize_fleet(vehicles, jobs, matrix)
            times.append((time.perf_counter() - start) * 1000)
        rows.append({
            "jobs": n,
            "vehicles": len(vehicles),
            "served": plan.served_job_count,
            "median_ms": round(statistics.median(times), 3),
            "max_ms": round(max(times), 3),
        })
    print(json.dumps({
        "algorithm": "fleet-exact-v0.1", "data": "SYNTHETIC_ONLY",
        "python": platform.python_version(), "results": rows,
        "limitations": ["no real routes", "microbenchmark", "no performance guarantee"],
    }, indent=2))


if __name__ == "__main__":
    main()
