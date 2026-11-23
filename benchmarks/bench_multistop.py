"""Synthetic wall-clock benchmark; no real Peru routing/ETA evidence."""

from __future__ import annotations

import json
import platform
import random
import statistics
import time
from pathlib import Path

from desset_core import DeliveryJob, optimize_multistop


def run() -> dict:
    samples = []
    for jobs_count in (2, 4, 7):
        rng = random.Random(20261123 + jobs_count)
        jobs = [DeliveryJob(f"J{i}", f"P{i}", f"D{i}", 1)
                for i in range(jobs_count)]
        nodes = ["S"] + [node for job in jobs
                         for node in (job.pickup_node, job.delivery_node)]
        directed = {(a, b): rng.randint(15, 1800) for a in nodes for b in nodes if a != b}
        elapsed = []
        for _ in range(10):
            start = time.perf_counter_ns()
            result = optimize_multistop("S", 3, jobs, directed)
            elapsed.append((time.perf_counter_ns() - start) / 1_000_000)
        samples.append({"jobs": jobs_count, "median_wall_ms": round(statistics.median(elapsed), 3),
                        "min_wall_ms": round(min(elapsed), 3),
                        "max_wall_ms": round(max(elapsed), 3),
                        "total_estimated_travel_seconds": result.total_estimated_travel_seconds})
    return {"input_kind": "synthetic_deterministic", "seed_base": 20261123,
            "python": platform.python_version(), "platform": platform.platform(),
            "limitation": "no real network, OSRM, traffic, ETA, or production SLA",
            "runs_per_size": 10, "samples": samples}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
