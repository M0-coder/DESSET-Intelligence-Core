"""INT-010: independent invariants for bounded ejection-and-repair; synthetic inputs."""

import random
import unittest

from desset_core import DeliveryJob, FleetVehicle, optimize_fleet_adaptive, optimize_fleet_insertion
from desset_core.fleet_repair import optimize_fleet_repaired


def gap_case(with_fillers=0):
    vehicles = [FleetVehicle("V1", "S1", 2), FleetVehicle("V2", "S2", 1)]
    jobs = [DeliveryJob("J0", "P0", "D0", 1), DeliveryJob("J1", "P1", "D1", 1)]
    times = {("S2", "P0"): 1, ("P0", "D0"): 1,
             ("S1", "P1"): 1, ("P1", "P0"): 1,
             ("P0", "D1"): 1, ("D1", "D0"): 1}
    for i in range(with_fillers):
        vehicles.append(FleetVehicle(f"W{i}", f"T{i}", 1))
        jobs.append(DeliveryJob(f"X{i}", f"XP{i}", f"XD{i}", 1))
        times[(f"T{i}", f"XP{i}")] = 2
        times[(f"XP{i}", f"XD{i}")] = 2
    return vehicles, jobs, times


def check_plan(test, vehicles, jobs, times, plan):
    by_vehicle = {v.id: v for v in vehicles}
    by_job = {j.id: j for j in jobs}
    served = []
    fleet_seconds = 0
    for assignment in plan.routes:
        vehicle = by_vehicle[assignment.vehicle_id]
        test.assertEqual(assignment.route.start_node, vehicle.start_node)
        test.assertEqual(assignment.route.vehicle_capacity_units, vehicle.capacity_units)
        test.assertEqual(len(assignment.job_ids), len(set(assignment.job_ids)))
        picked = set()
        delivered = set()
        at = vehicle.start_node
        onboard = 0
        seconds = 0
        for visit in assignment.route.visits:
            job = by_job[visit.job_id]
            if visit.action == "pickup":
                test.assertNotIn(job.id, picked)
                picked.add(job.id)
                onboard += job.load_units
                node = job.pickup_node
            else:
                test.assertIn(job.id, picked)
                test.assertNotIn(job.id, delivered)
                delivered.add(job.id)
                onboard -= job.load_units
                node = job.delivery_node
            test.assertEqual(visit.node, node)
            test.assertTrue(0 <= onboard <= vehicle.capacity_units)
            test.assertEqual(visit.onboard_units_after, onboard)
            test.assertIn((at, node), times)
            test.assertEqual(visit.incoming_seconds, times[(at, node)])
            seconds += visit.incoming_seconds
            at = node
        test.assertEqual(picked, delivered)
        test.assertEqual(picked, set(assignment.job_ids))
        test.assertEqual(onboard, 0)
        test.assertEqual(seconds, assignment.route.total_estimated_travel_seconds)
        if vehicle.max_total_seconds is not None:
            test.assertLessEqual(seconds, vehicle.max_total_seconds)
        fleet_seconds += seconds
        served.extend(assignment.job_ids)
    test.assertEqual(len(set(served)), len(served))
    test.assertEqual(len(served), plan.served_job_count)
    test.assertEqual(fleet_seconds, plan.total_estimated_travel_seconds)
    test.assertEqual(set(served) | set(plan.unassigned_job_ids), set(by_job))
    test.assertFalse(set(served) & set(plan.unassigned_job_ids))


class RepairTests(unittest.TestCase):
    def test_red_known_gap_both_jobs_inseparable_as_standalone(self):
        fleet, jobs, times = gap_case()
        before = optimize_fleet_insertion(fleet, jobs, times)
        after = optimize_fleet_repaired(fleet, jobs, times)
        self.assertEqual(before.served_job_count, 1)
        self.assertEqual(after.served_job_count, 2)
        self.assertEqual(after.unassigned_job_ids, ())
        self.assertEqual(after.total_estimated_travel_seconds, 4)
        self.assertEqual(after.algorithm_version, "fleet-repair-v0.1")
        check_plan(self, fleet, jobs, times, after)

    def test_red_gap_larger_than_exact_limits(self):
        fleet, jobs, times = gap_case(with_fillers=5)
        baseline = optimize_fleet_insertion(fleet, jobs, times)
        repaired = optimize_fleet_repaired(fleet, jobs, times)
        self.assertEqual((baseline.served_job_count, repaired.served_job_count), (6, 7))
        check_plan(self, fleet, jobs, times, repaired)
        self.assertEqual(optimize_fleet_adaptive(fleet, jobs, times), repaired)

    def test_no_regression_when_all_jobs_served(self):
        fleet = [FleetVehicle("A", "SA", 2), FleetVehicle("B", "SB", 2)]
        jobs = [DeliveryJob(f"J{i}", f"P{i}", f"D{i}", 1) for i in range(7)]
        nodes = [v.start_node for v in fleet] + [n for j in jobs for n in (j.pickup_node, j.delivery_node)]
        times = {(a, b): 1 + abs(i - k) for i, a in enumerate(nodes)
                 for k, b in enumerate(nodes) if a != b}
        expected = optimize_fleet_insertion(fleet, jobs, times)
        self.assertEqual(expected.served_job_count, 7)
        self.assertEqual(optimize_fleet_repaired(fleet, jobs, times), expected)

    def test_random_sparse_nonregression_and_invariants(self):
        rng = random.Random(2026112310)
        for trial in range(40):
            n_vehicles = rng.randint(2, 6)
            n_jobs = rng.randint(7, 11)
            fleet = [FleetVehicle(f"V{i}", f"S{i}", rng.randint(1, 3),
                                  rng.choice([None, 80])) for i in range(n_vehicles)]
            jobs = [DeliveryJob(f"J{i}", f"P{i}", f"D{i}", rng.randint(1, 3))
                    for i in range(n_jobs)]
            nodes = [v.start_node for v in fleet] + [n for j in jobs for n in (j.pickup_node, j.delivery_node)]
            times = {(a, b): rng.randint(1, 17) for a in nodes for b in nodes
                     if a != b and rng.random() < 0.62}
            baseline = optimize_fleet_insertion(fleet, jobs, times)
            repaired = optimize_fleet_repaired(fleet, jobs, times)
            with self.subTest(trial=trial):
                self.assertGreaterEqual(repaired.served_job_count, baseline.served_job_count)
                if repaired.served_job_count == baseline.served_job_count:
                    self.assertLessEqual(repaired.total_estimated_travel_seconds,
                                         baseline.total_estimated_travel_seconds)
                check_plan(self, fleet, jobs, times, repaired)
                self.assertEqual(repaired, optimize_fleet_repaired(
                    list(reversed(fleet)), list(reversed(jobs)),
                    dict(reversed(list(times.items())))))

    def test_two_rounds_recover_two_orders_without_degrading_constraints(self):
        # Independent fixture analogous to seed 104 in the benchmark. The
        # initial insertion gets stuck at two; two repairs recover two more.
        from benchmarks.bench_fleet_repair import case

        fleet, jobs, times = case(104, 3, 7, 0.65)
        baseline = optimize_fleet_insertion(fleet, jobs, times)
        repaired = optimize_fleet_repaired(fleet, jobs, times)
        self.assertEqual((baseline.served_job_count, repaired.served_job_count), (2, 4))
        check_plan(self, fleet, jobs, times, repaired)

    def test_mutation_disabling_repair_would_fail_quality_regression(self):
        from unittest.mock import patch

        fleet, jobs, times = gap_case(with_fillers=5)
        expected = optimize_fleet_repaired(fleet, jobs, times)
        with patch("desset_core.fleet_repair._exact_receiver", return_value=None):
            disabled = optimize_fleet_repaired(fleet, jobs, times)
        self.assertEqual(expected.served_job_count, 7)
        self.assertEqual(disabled.served_job_count, 6)
        self.assertNotEqual(expected, disabled)

    def test_empty_vehicles_and_invalid_inputs_preserve_original_contract(self):
        fleet, jobs, times = gap_case()
        self.assertEqual(optimize_fleet_repaired([], jobs, {}).served_job_count, 0)
        self.assertEqual(optimize_fleet_repaired(fleet, [], {}).routes, ())
        with self.assertRaises(ValueError):
            optimize_fleet_repaired(fleet, jobs, {("S2", "P0"): -1})


if __name__ == "__main__":
    unittest.main()
