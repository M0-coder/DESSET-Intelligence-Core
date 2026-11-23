"""Exact routing oracle and adversarial checks on SYNTHETIC travel times."""

import itertools
import random
import unittest

from desset_core import (
    DeliveryJob,
    NoFeasibleRouteError,
    RouteInputError,
    optimize_multistop,
)


def complete_matrix(nodes, default=100):
    return {(a, b): default for a in nodes for b in nodes if a != b}


def oracle(start, capacity, jobs, times):
    """Intentionally independent enumerator: use only for at most 3 jobs."""
    choices = tuple((job.id, action, node, job.load_units) for job in jobs
                    for action, node in (("pickup", job.pickup_node),
                                         ("delivery", job.delivery_node)))
    best = None
    for sequence in itertools.permutations(choices):
        picked = set()
        delivered = set()
        onboard = 0
        location = start
        cost = 0
        for job_id, action, node, units in sequence:
            if action == "pickup":
                if onboard + units > capacity:
                    break
                picked.add(job_id)
                onboard += units
            else:
                if job_id not in picked or job_id in delivered:
                    break
                delivered.add(job_id)
                onboard -= units
            if (location, node) not in times:
                break
            cost += times[(location, node)]
            location = node
        else:
            if len(delivered) == len(jobs) and (best is None or cost < best):
                best = cost
    return best


class MultiStopTests(unittest.TestCase):
    def test_empty_batch(self):
        plan = optimize_multistop("S", 1, [], {})
        self.assertEqual(plan.visits, ())
        self.assertEqual(plan.total_estimated_travel_seconds, 0)

    def test_one_job_pickup_precedes_delivery(self):
        jobs = [DeliveryJob("A", "AP", "AD", 2)]
        times = {("S", "AP"): 12, ("AP", "AD"): 35}
        plan = optimize_multistop("S", 2, jobs, times)
        self.assertEqual(plan.total_estimated_travel_seconds, 47)
        self.assertEqual([(v.action, v.node, v.onboard_units_after)
                          for v in plan.visits], [("pickup", "AP", 2), ("delivery", "AD", 0)])
        self.assertEqual(plan.visits[1].incoming_seconds, 35)

    def test_interleaving_multiple_pickups_can_be_optimal(self):
        jobs = [DeliveryJob("A", "AP", "AD", 1), DeliveryJob("B", "BP", "BD", 1)]
        nodes = ["S", "AP", "AD", "BP", "BD"]
        times = complete_matrix(nodes)
        times.update({("S", "AP"): 1, ("AP", "BP"): 1,
                      ("BP", "AD"): 1, ("AD", "BD"): 1})
        plan = optimize_multistop("S", 2, jobs, times)
        self.assertEqual(plan.total_estimated_travel_seconds, 4)
        self.assertEqual([(v.job_id, v.action) for v in plan.visits],
                         [("A", "pickup"), ("B", "pickup"),
                          ("A", "delivery"), ("B", "delivery")])
        cap_one = optimize_multistop("S", 1, jobs, times)
        self.assertGreater(cap_one.total_estimated_travel_seconds, 4)
        self.assertTrue(all(0 <= v.onboard_units_after <= 1 for v in cap_one.visits))

    def test_missing_directed_arcs_are_not_invented(self):
        job = [DeliveryJob("A", "AP", "AD", 1)]
        with self.assertRaises(NoFeasibleRouteError):
            optimize_multistop("S", 1, job, {("AP", "S"): 1, ("AD", "AP"): 1})
        plan = optimize_multistop("S", 1, job, {("S", "AP"): 5, ("AP", "AD"): 6})
        self.assertEqual(plan.total_estimated_travel_seconds, 11)

    def test_capacity_and_total_budget(self):
        job = [DeliveryJob("A", "AP", "AD", 2)]
        with self.assertRaises(NoFeasibleRouteError):
            optimize_multistop("S", 1, job, {})
        times = {("S", "AP"): 4, ("AP", "AD"): 7}
        with self.assertRaises(NoFeasibleRouteError):
            optimize_multistop("S", 2, job, times, max_total_seconds=10)
        self.assertEqual(optimize_multistop("S", 2, job, times,
                                            max_total_seconds=11).total_estimated_travel_seconds, 11)

    def test_deterministic_for_job_and_matrix_permutations(self):
        jobs = [DeliveryJob("Z", "ZP", "ZD", 1), DeliveryJob("A", "AP", "AD", 1)]
        matrix = complete_matrix(["S", "ZP", "ZD", "AP", "AD"], default=1)
        first = optimize_multistop("S", 2, jobs, matrix)
        second = optimize_multistop("S", 2, list(reversed(jobs)),
                                    dict(reversed(list(matrix.items()))))
        self.assertEqual(first, second)

    def test_malformed_contract_is_rejected(self):
        good = [DeliveryJob("A", "AP", "AD", 1)]
        invalid = [
            ("", 1, good, {}), ("S", 0, good, {}),
            ("S", True, good, {}), ("S", 1, "job", {}),
            ("S", 1, [object()], {}),
            ("S", 1, [good[0], good[0]], {}),
            ("S", 1, [DeliveryJob("A", "S", "AD", 1)], {}),
            ("S", 1, [DeliveryJob("A", "AP", "AP", 1)], {}),
            ("S", 1, [DeliveryJob("A", "AP", "AD", True)], {}),
            ("S", 1, good, {("S", "AP"): -1}),
            ("S", 1, good, {("S", "AP"): 1.5}),
            ("S", 1, good, {("S", "UNKNOWN"): 1}),
            ("S", 1, good, {("S",): 1}),
            ("S", 1, good, None),
        ]
        for case in invalid:
            with self.subTest(case=case), self.assertRaises(RouteInputError):
                optimize_multistop(*case)
        with self.assertRaises(RouteInputError):
            optimize_multistop("S", 1, good, {}, max_total_seconds=True)
        with self.assertRaises(RouteInputError):
            optimize_multistop("S", 1, [DeliveryJob(str(i), f"P{i}", f"D{i}", 1)
                                         for i in range(8)], {})

    def test_oracle_randomized_directed_and_incomplete_inputs(self):
        rng = random.Random(20261123)
        for n in range(1, 4):
            jobs = [DeliveryJob(f"J{i}", f"P{i}", f"D{i}", rng.randint(1, 3))
                    for i in range(n)]
            nodes = ["S"] + [node for job in jobs
                             for node in (job.pickup_node, job.delivery_node)]
            for iteration in range(45):
                capacity = rng.randint(max(j.load_units for j in jobs), 5)
                times = {(a, b): rng.randint(0, 70) for a in nodes for b in nodes
                         if a != b and rng.random() < 0.80}
                expected = oracle("S", capacity, jobs, times)
                with self.subTest(n=n, iteration=iteration, capacity=capacity):
                    if expected is None:
                        with self.assertRaises(NoFeasibleRouteError):
                            optimize_multistop("S", capacity, jobs, times)
                    else:
                        plan = optimize_multistop("S", capacity, jobs, times)
                        self.assertEqual(plan.total_estimated_travel_seconds, expected)
                        self.assertEqual(len(plan.visits), 2 * n)
                        self.assertTrue(all(0 <= v.onboard_units_after <= capacity
                                            for v in plan.visits))
                        self.assertEqual(sum(v.incoming_seconds for v in plan.visits),
                                         plan.total_estimated_travel_seconds)

    def test_seven_jobs_are_bounded(self):
        jobs = [DeliveryJob(f"J{i}", f"P{i}", f"D{i}", 1) for i in range(7)]
        nodes = ["S"] + [n for j in jobs for n in (j.pickup_node, j.delivery_node)]
        matrix = complete_matrix(nodes, default=1)
        plan = optimize_multistop("S", 7, jobs, matrix)
        self.assertEqual(len(plan.visits), 14)
        self.assertEqual(plan.total_estimated_travel_seconds, 14)
        self.assertEqual(plan.visits[-1].onboard_units_after, 0)


if __name__ == "__main__":
    unittest.main()
