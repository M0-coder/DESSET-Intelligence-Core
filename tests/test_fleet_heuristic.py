"""Synthetic regression and adversarial controls for the fleet insertion heuristic."""

import random
import unittest

from desset_core import (
    DeliveryJob,
    FleetVehicle,
    RouteInputError,
    optimize_fleet,
    optimize_fleet_adaptive,
    optimize_fleet_insertion,
)


def complete_matrix(nodes, cost=10):
    return {(a, b): cost for a in nodes for b in nodes if a != b}


class FleetInsertionTests(unittest.TestCase):
    def test_single_job_and_empty_cases(self):
        vehicle = FleetVehicle("V", "S", 1)
        job = DeliveryJob("J", "P", "D", 1)
        plan = optimize_fleet_insertion([vehicle], [job], {("S", "P"): 3, ("P", "D"): 7})
        self.assertEqual((plan.served_job_count, plan.total_estimated_travel_seconds), (1, 10))
        self.assertEqual([(v.job_id, v.action) for v in plan.routes[0].route.visits],
                         [("J", "pickup"), ("J", "delivery")])
        self.assertEqual(optimize_fleet_insertion([vehicle], [], {}).routes, ())
        self.assertEqual(optimize_fleet_insertion([], [job], {}).unassigned_job_ids, ("J",))

    def test_capacity_never_exceeded_even_when_batched_pickups_are_shorter(self):
        vehicle = FleetVehicle("V", "S", 1)
        jobs = [DeliveryJob("A", "AP", "AD", 1), DeliveryJob("B", "BP", "BD", 1)]
        times = complete_matrix(["S", "AP", "AD", "BP", "BD"], 100)
        times.update({("S", "AP"): 1, ("AP", "BP"): 1,
                      ("BP", "AD"): 1, ("AD", "BD"): 1,
                      ("AP", "AD"): 3, ("AD", "BP"): 4,
                      ("BP", "BD"): 3})
        plan = optimize_fleet_insertion([vehicle], jobs, times)
        self.assertEqual(plan.served_job_count, 2)
        visits = plan.routes[0].route.visits
        self.assertTrue(all(0 <= stop.onboard_units_after <= 1 for stop in visits))
        self.assertEqual(visits[-1].onboard_units_after, 0)
        self.assertEqual(len(visits), 4)

    def test_scarce_vehicle_preferred_when_possible(self):
        vehicles = [FleetVehicle("A", "SA", 1), FleetVehicle("B", "SB", 2)]
        jobs = [DeliveryJob("large", "LP", "LD", 2), DeliveryJob("small", "SP", "SD", 1)]
        matrix = complete_matrix(["SA", "SB", "LP", "LD", "SP", "SD"], 10)
        plan = optimize_fleet_insertion(vehicles, jobs, matrix)
        self.assertEqual(plan.served_job_count, 2)
        self.assertEqual({job for route in plan.routes for job in route.job_ids},
                         {"large", "small"})
        self.assertEqual(next(r.vehicle_id for r in plan.routes if "large" in r.job_ids), "B")

    def test_rechecks_job_after_initially_unreachable_origin(self):
        vehicles = [FleetVehicle("V", "S", 1)]
        jobs = [DeliveryJob("A", "AP", "AD", 1), DeliveryJob("B", "BP", "BD", 1)]
        # B is unreachable directly from S but reachable after completing A.
        times = {("S", "AP"): 1, ("AP", "AD"): 1,
                 ("AD", "BP"): 1, ("BP", "BD"): 1}
        plan = optimize_fleet_insertion(vehicles, jobs, times)
        self.assertEqual(plan.served_job_count, 2)
        self.assertEqual(plan.total_estimated_travel_seconds, 4)

    def test_fail_closed_missing_arcs_and_route_budget(self):
        job = DeliveryJob("A", "AP", "AD", 1)
        vehicles = [FleetVehicle("V", "S", 1, 9)]
        plan = optimize_fleet_insertion(vehicles, [job], {("S", "AP"): 4, ("AP", "AD"): 6})
        self.assertEqual(plan.served_job_count, 0)
        self.assertEqual(plan.unassigned_job_ids, ("A",))
        plan = optimize_fleet_insertion(vehicles, [job], {("S", "AP"): 4})
        self.assertEqual(plan.served_job_count, 0)

    def test_large_batch_exceeds_exact_limits(self):
        vehicles = [FleetVehicle(f"V{i}", f"S{i}", 4) for i in range(6)]
        jobs = [DeliveryJob(f"J{i}", f"P{i}", f"D{i}", 1) for i in range(12)]
        nodes = [v.start_node for v in vehicles]
        nodes += [node for job in jobs for node in (job.pickup_node, job.delivery_node)]
        times = complete_matrix(nodes, 10)
        result = optimize_fleet_insertion(vehicles, jobs, times)
        self.assertEqual(result.served_job_count, 12)
        self.assertEqual(result.unassigned_job_ids, ())
        self.assertEqual(len({j for r in result.routes for j in r.job_ids}), 12)
        with self.assertRaises(RouteInputError):
            optimize_fleet(vehicles, jobs, times)

    def test_deterministic_permutation(self):
        vehicles = [FleetVehicle("Z", "SZ", 2), FleetVehicle("A", "SA", 2)]
        jobs = [DeliveryJob(f"J{i}", f"P{i}", f"D{i}", 1) for i in range(5)]
        nodes = [v.start_node for v in vehicles]
        nodes += [node for job in jobs for node in (job.pickup_node, job.delivery_node)]
        times = complete_matrix(nodes, 6)
        a = optimize_fleet_insertion(vehicles, jobs, times)
        b = optimize_fleet_insertion(list(reversed(vehicles)), list(reversed(jobs)),
                                     dict(reversed(list(times.items()))))
        self.assertEqual(a, b)

    def test_known_greedy_gap_exposed_and_adaptive_uses_exact(self):
        vehicles = [FleetVehicle("V1", "S1", 2), FleetVehicle("V2", "S2", 1)]
        jobs = [DeliveryJob("J0", "P0", "D0", 1),
                DeliveryJob("J1", "P1", "D1", 1)]
        # J1 has no feasible standalone route, but it can be served after
        # picking up J0 on V1. The insertion heuristic commits J0 to V2.
        times = {("S2", "P0"): 1, ("P0", "D0"): 1,
                 ("S1", "P1"): 1, ("P1", "P0"): 1,
                 ("P0", "D1"): 1, ("D1", "D0"): 1}
        greedy = optimize_fleet_insertion(vehicles, jobs, times)
        exact = optimize_fleet(vehicles, jobs, times)
        adaptive = optimize_fleet_adaptive(vehicles, jobs, times)
        self.assertEqual(greedy.served_job_count, 1)
        self.assertEqual(exact.served_job_count, 2)
        self.assertEqual(adaptive, exact)
        self.assertNotEqual(greedy.algorithm_version, adaptive.algorithm_version)

    def test_adaptive_large_fleet_dispatches_to_insertion_heuristic(self):
        vehicles = [FleetVehicle(f"V{i}", f"S{i}", 2) for i in range(5)]
        jobs = [DeliveryJob(f"J{i}", f"P{i}", f"D{i}", 1) for i in range(7)]
        nodes = [v.start_node for v in vehicles] + [n for j in jobs
                                                       for n in (j.pickup_node,
                                                                 j.delivery_node)]
        times = complete_matrix(nodes, 2)
        adapted = optimize_fleet_adaptive(vehicles, jobs, times)
        self.assertEqual(adapted, optimize_fleet_insertion(vehicles, jobs, times))
        self.assertEqual(adapted.served_job_count, 7)

    def test_validation(self):
        vehicle = FleetVehicle("V", "S", 1)
        job = DeliveryJob("J", "P", "D", 1)
        cases = [
            ("invalid", [job], {}),
            ([vehicle], "invalid", {}),
            ([vehicle], [job], None),
            ([FleetVehicle("V", "S", True)], [job], {}),
            ([FleetVehicle("V", "S", 1, -1)], [job], {}),
            ([vehicle, vehicle], [job], {}),
            ([vehicle], [job, job], {}),
            ([vehicle], [DeliveryJob("J", "P", "P", 1)], {}),
            ([vehicle], [DeliveryJob("J", "S", "D", 1)], {}),
            ([vehicle], [DeliveryJob("J", "P", "D", True)], {}),
            ([vehicle], [job], {("S", "P"): -1}),
            ([vehicle], [job], {("S", "P"): True}),
            ([vehicle], [job], {("S", "BAD"): 1}),
            ([vehicle], [job], {("S",): 1}),
            ([FleetVehicle(str(i), f"S{i}", 1) for i in range(25)], [], {}),
            ([vehicle], [DeliveryJob(str(i), f"P{i}", f"D{i}", 1)
                         for i in range(81)], {}),
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(RouteInputError):
                optimize_fleet_insertion(*case)

    def test_small_instances_are_compared_to_exact_not_claimed_optimal(self):
        rng = random.Random(20261123)
        gaps = []
        for n in (1, 2, 3):
            for trial in range(12):
                vehicles = [FleetVehicle("V1", "S1", rng.randint(1, 3)),
                            FleetVehicle("V2", "S2", rng.randint(1, 3))]
                jobs = [DeliveryJob(f"J{i}", f"P{i}", f"D{i}", rng.randint(1, 3))
                        for i in range(n)]
                nodes = ["S1", "S2"] + [node for job in jobs
                                         for node in (job.pickup_node, job.delivery_node)]
                times = {(a, b): rng.randint(0, 60) for a in nodes for b in nodes
                         if a != b and rng.random() < 0.8}
                exact = optimize_fleet(vehicles, jobs, times)
                heuristic = optimize_fleet_insertion(vehicles, jobs, times)
                with self.subTest(n=n, trial=trial):
                    self.assertLessEqual(heuristic.served_job_count, exact.served_job_count)
                    if heuristic.served_job_count == exact.served_job_count:
                        self.assertGreaterEqual(heuristic.total_estimated_travel_seconds,
                                                exact.total_estimated_travel_seconds)
                    seen = [j for r in heuristic.routes for j in r.job_ids]
                    self.assertEqual(len(seen), len(set(seen)))
                    self.assertEqual(len(seen), heuristic.served_job_count)
                    for assignment in heuristic.routes:
                        onboard = [v.onboard_units_after for v in assignment.route.visits]
                        self.assertTrue(all(0 <= units <= assignment.route.vehicle_capacity_units
                                            for units in onboard))
                gaps.append(exact.served_job_count - heuristic.served_job_count)
        self.assertEqual(len(gaps), 36)


if __name__ == "__main__":
    unittest.main()
