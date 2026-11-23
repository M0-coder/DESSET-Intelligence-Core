"""Independent small-instance oracle for multi-vehicle routing; synthetic only."""

import itertools
import random
import unittest

from desset_core import DeliveryJob, FleetVehicle, RouteInputError, optimize_fleet


def complete_matrix(nodes, default=100):
    return {(a, b): default for a in nodes for b in nodes if a != b}


def independent_route(start, capacity, jobs, times, limit=None):
    """Exhaust all 2n-stop orders (n <= 3); deliberately not using fleet DP."""
    if not jobs:
        return 0
    steps = [(j.id, "P", j.pickup_node, j.load_units) for j in jobs]
    steps += [(j.id, "D", j.delivery_node, j.load_units) for j in jobs]
    best = None
    for sequence in itertools.permutations(steps):
        picked = set()
        delivered = set()
        onboard = 0
        at = start
        cost = 0
        for job_id, action, node, units in sequence:
            if action == "P":
                if onboard + units > capacity:
                    break
                picked.add(job_id)
                onboard += units
            else:
                if job_id not in picked or job_id in delivered:
                    break
                delivered.add(job_id)
                onboard -= units
            leg = times.get((at, node))
            if leg is None:
                break
            cost += leg
            at = node
        else:
            if len(delivered) == len(jobs) and (limit is None or cost <= limit):
                if best is None or cost < best:
                    best = cost
    return best


def independent_fleet(vehicles, jobs, times):
    best = (0, 0)
    for choices in itertools.product(range(-1, len(vehicles)), repeat=len(jobs)):
        total = 0
        count = 0
        for index, vehicle in enumerate(vehicles):
            selected = [job for job, chosen in zip(jobs, choices, strict=True) if chosen == index]
            route_cost = independent_route(
                vehicle.start_node,
                vehicle.capacity_units,
                selected,
                times,
                vehicle.max_total_seconds,
            )
            if route_cost is None:
                break
            total += route_cost
            count += len(selected)
        else:
            if count > best[0] or (count == best[0] and total < best[1]):
                best = (count, total)
    return best


class FleetTests(unittest.TestCase):
    def test_empty_fleet_and_empty_jobs(self):
        self.assertEqual(optimize_fleet([], [], {}).routes, ())
        jobs = [DeliveryJob("A", "AP", "AD", 1)]
        plan = optimize_fleet([], jobs, {})
        self.assertEqual(plan.unassigned_job_ids, ("A",))
        self.assertEqual(plan.served_job_count, 0)
        self.assertEqual(optimize_fleet([FleetVehicle("V", "S", 1)], [], {}).routes, ())

    def test_multi_vehicle_is_cheaper_than_one_on_separated_clusters(self):
        vehicles = [FleetVehicle("V1", "S1", 1), FleetVehicle("V2", "S2", 1)]
        jobs = [DeliveryJob("A", "AP", "AD", 1), DeliveryJob("B", "BP", "BD", 1)]
        times = complete_matrix(["S1", "S2", "AP", "AD", "BP", "BD"], default=1000)
        times.update({("S1", "AP"): 1, ("AP", "AD"): 1,
                      ("S2", "BP"): 1, ("BP", "BD"): 1})
        result = optimize_fleet(vehicles, jobs, times)
        self.assertEqual(result.served_job_count, 2)
        self.assertEqual(result.unassigned_job_ids, ())
        self.assertEqual(result.total_estimated_travel_seconds, 4)
        self.assertEqual([(r.vehicle_id, r.job_ids) for r in result.routes],
                         [("V1", ("A",)), ("V2", ("B",))])

    def test_one_vehicle_can_service_multiple_jobs(self):
        vehicles = [FleetVehicle("R1", "S", 2), FleetVehicle("R2", "T", 1)]
        jobs = [DeliveryJob("A", "AP", "AD", 1), DeliveryJob("B", "BP", "BD", 1)]
        matrix = complete_matrix(["S", "T", "AP", "AD", "BP", "BD"], 100)
        matrix.update({("S", "AP"): 1, ("AP", "BP"): 1,
                       ("BP", "AD"): 1, ("AD", "BD"): 1})
        result = optimize_fleet(vehicles, jobs, matrix)
        self.assertEqual(result.total_estimated_travel_seconds, 4)
        self.assertEqual(len(result.routes), 1)
        self.assertEqual(result.routes[0].vehicle_id, "R1")
        self.assertEqual([(s.job_id, s.action) for s in result.routes[0].route.visits],
                         [("A", "pickup"), ("B", "pickup"),
                          ("A", "delivery"), ("B", "delivery")])
        self.assertTrue(all(0 <= step.onboard_units_after <= 2
                            for step in result.routes[0].route.visits))

    def test_unreachable_job_is_not_fabricated(self):
        vehicles = [FleetVehicle("V", "S", 1)]
        jobs = [DeliveryJob("A", "AP", "AD", 1), DeliveryJob("B", "BP", "BD", 1)]
        times = {("S", "AP"): 5, ("AP", "AD"): 7}
        result = optimize_fleet(vehicles, jobs, times)
        self.assertEqual(result.served_job_count, 1)
        self.assertEqual(result.unassigned_job_ids, ("B",))
        self.assertEqual(result.total_estimated_travel_seconds, 12)

    def test_maximize_served_before_minimizing_cost(self):
        vehicles = [FleetVehicle("V", "S", 1)]
        jobs = [DeliveryJob("A", "AP", "AD", 1), DeliveryJob("B", "BP", "BD", 1)]
        times = {("S", "AP"): 1, ("AP", "AD"): 1,
                 ("AD", "BP"): 100, ("BP", "BD"): 100,
                 ("S", "BP"): 1}
        result = optimize_fleet(vehicles, jobs, times)
        self.assertEqual(result.served_job_count, 2)
        self.assertEqual(result.total_estimated_travel_seconds, 202)

    def test_budget_can_force_other_vehicle_or_no_assignments(self):
        jobs = [DeliveryJob("A", "AP", "AD", 1)]
        times = {("S1", "AP"): 5, ("S2", "AP"): 1, ("AP", "AD"): 3}
        result = optimize_fleet([
            FleetVehicle("A", "S1", 1, max_total_seconds=4),
            FleetVehicle("B", "S2", 1, max_total_seconds=4),
        ], jobs, times)
        self.assertEqual(result.routes[0].vehicle_id, "B")
        self.assertEqual(result.total_estimated_travel_seconds, 4)
        rejected = optimize_fleet([FleetVehicle("A", "S1", 1, max_total_seconds=7)],
                                  jobs, {k: v for k, v in times.items() if "S2" not in k})
        self.assertEqual(rejected.unassigned_job_ids, ("A",))

    def test_deterministic_permutations_and_tie(self):
        vehicles = [FleetVehicle("A", "S1", 1), FleetVehicle("B", "S2", 1)]
        jobs = [DeliveryJob("Z", "ZP", "ZD", 1), DeliveryJob("X", "XP", "XD", 1)]
        times = complete_matrix(["S1", "S2", "ZP", "ZD", "XP", "XD"], 5)
        a = optimize_fleet(vehicles, jobs, times)
        b = optimize_fleet(list(reversed(vehicles)), list(reversed(jobs)),
                           dict(reversed(list(times.items()))))
        self.assertEqual(a, b)
        one = optimize_fleet(vehicles, [jobs[0]],
                             {k: v for k, v in times.items() if not any(
                                 node in k for node in ("XP", "XD"))})
        self.assertEqual(one.routes[0].vehicle_id, "A")

    def test_strict_validation_and_limits(self):
        valid_jobs = [DeliveryJob("J", "P", "D", 1)]
        valid_vehicles = [FleetVehicle("V", "S", 1)]
        cases = [
            ("no list", valid_jobs, {}),
            (valid_vehicles, "no list", {}),
            ([FleetVehicle("V", "S", True)], valid_jobs, {}),
            ([FleetVehicle("V", "S", 0)], valid_jobs, {}),
            ([FleetVehicle("V", "S", 1, True)], valid_jobs, {}),
            ([FleetVehicle("V", "S", 1, -1)], valid_jobs, {}),
            ([FleetVehicle("V", "S", 1), FleetVehicle("V", "T", 1)], valid_jobs, {}),
            ([FleetVehicle("V", "P", 1)], valid_jobs, {}),
            (valid_vehicles, [DeliveryJob("J", "P", "P", 1)], {}),
            (valid_vehicles, [DeliveryJob("J", "P", "D", 0)], {}),
            (valid_vehicles, [DeliveryJob("J", "P", "D", 1)] * 2, {}),
            (valid_vehicles, [DeliveryJob("J", "P", "D", True)], {}),
            (valid_vehicles, valid_jobs, None),
            (valid_vehicles, valid_jobs, {("S", "P"): float("inf")}),
            (valid_vehicles, valid_jobs, {("S", "P"): -1}),
            (valid_vehicles, valid_jobs, {("S", "P"): True}),
            (valid_vehicles, valid_jobs, {("S", "E"): 1}),
            (valid_vehicles, valid_jobs, {("S",): 1}),
            ([FleetVehicle(str(i), f"S{i}", 1) for i in range(5)], [], {}),
            (valid_vehicles, [DeliveryJob(str(i), f"P{i}", f"D{i}", 1)
                              for i in range(7)], {}),
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(RouteInputError):
                optimize_fleet(*case)

    def test_oracle_randomized_directed_sparse(self):
        rng = random.Random(20261123)
        for n in range(1, 4):
            for iteration in range(16):
                vehicles = [FleetVehicle("V1", "S1", rng.randint(1, 3),
                                         max_total_seconds=rng.choice([None, 50])),
                            FleetVehicle("V2", "S2", rng.randint(1, 3))]
                jobs = [DeliveryJob(f"J{i}", f"P{i}", f"D{i}", rng.randint(1, 3))
                        for i in range(n)]
                nodes = ["S1", "S2"] + [x for j in jobs
                                          for x in (j.pickup_node, j.delivery_node)]
                times = {(a, b): rng.randint(0, 30) for a in nodes for b in nodes
                         if a != b and rng.random() < 0.75}
                expected = independent_fleet(vehicles, jobs, times)
                result = optimize_fleet(vehicles, jobs, times)
                with self.subTest(n=n, iteration=iteration):
                    self.assertEqual((result.served_job_count,
                                      result.total_estimated_travel_seconds), expected)
                    seen = [job for r in result.routes for job in r.job_ids]
                    self.assertEqual(len(seen), len(set(seen)))
                    self.assertEqual(len(seen), result.served_job_count)
                    for assignment in result.routes:
                        self.assertEqual(len(assignment.route.visits), 2 * len(assignment.job_ids))
                        self.assertEqual(assignment.route.visits[-1].onboard_units_after, 0)


if __name__ == "__main__":
    unittest.main()
