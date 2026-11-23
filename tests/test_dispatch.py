"""Reproducible synthetic fixtures: not evidence of DESSET demand or travel time."""

import unittest

from desset_core.dispatch import Courier, Order, dispatch


class DispatchTests(unittest.TestCase):
    def test_empty(self):
        result = dispatch([], [], {})
        self.assertEqual(result.assignments, ())
        self.assertEqual(result.unassigned, ())

    def test_one_eligible_pair(self):
        r = dispatch([Courier("C1", 1)], [Order("O1", 1)], {("C1", "O1"): 300})
        self.assertEqual(r.assignments[0].estimated_pickup_seconds, 300)

    def test_optimal_improves_greedy_on_synthetic_matrix(self):
        riders = [Courier("C1", 1), Courier("C2", 1)]
        orders = [Order("O1", 1), Order("O2", 1)]
        matrix = {
            ("C1", "O1"): 1,
            ("C2", "O1"): 2,
            ("C1", "O2"): 2,
            ("C2", "O2"): 100,
        }
        greedy = dispatch(riders, orders, matrix, strategy="greedy")
        optimal = dispatch(riders, orders, matrix)
        self.assertEqual(greedy.total_estimated_pickup_seconds, 101)
        self.assertEqual(optimal.total_estimated_pickup_seconds, 4)
        self.assertEqual(len(optimal.assignments), 2)

    def test_maximize_assignments_before_cost(self):
        riders = [Courier("C1", 1), Courier("C2", 1)]
        orders = [Order("O1", 1), Order("O2", 1)]
        matrix = {("C1", "O1"): 1, ("C1", "O2"): 100, ("C2", "O1"): 1}
        result = dispatch(riders, orders, matrix)
        self.assertEqual(len(result.assignments), 2)
        self.assertEqual({x.courier_id for x in result.assignments}, {"C1", "C2"})

    def test_unavailable_and_insufficient_capacity(self):
        r = dispatch(
            [Courier("C1", 4, False), Courier("C2", 1)],
            [Order("O1", 3)],
            {("C1", "O1"): 1, ("C2", "O1"): 2},
        )
        self.assertEqual(r.unassigned[0].reason, "no_eligible_courier_or_estimate")

    def test_pickup_window_is_hard_constraint(self):
        r = dispatch([Courier("C1", 3)], [Order("O1", 2, 90)], {("C1", "O1"): 91})
        self.assertEqual(len(r.assignments), 0)

    def test_pickup_window_inclusive(self):
        r = dispatch([Courier("C1", 3)], [Order("O1", 2, 90)], {("C1", "O1"): 90})
        self.assertEqual(len(r.assignments), 1)

    def test_missing_estimates_cannot_be_guessed(self):
        r = dispatch([Courier("C1", 1)], [Order("O1", 1)], {})
        self.assertEqual(len(r.assignments), 0)

    def test_resource_conflict_explained(self):
        r = dispatch(
            [Courier("C1", 2)],
            [Order("O1", 1), Order("O2", 1)],
            {("C1", "O1"): 10, ("C1", "O2"): 20},
        )
        self.assertEqual(len(r.assignments), 1)
        self.assertEqual(r.unassigned[0].reason, "courier_capacity_conflict")

    def test_deterministic_permutation(self):
        c = [Courier("C2", 2), Courier("C1", 2)]
        o = [Order("O2", 1), Order("O1", 1)]
        m = {(courier.id, order.id): 5 for courier in c for order in o}
        a = dispatch(c, o, m)
        b = dispatch(list(reversed(c)), list(reversed(o)), dict(reversed(list(m.items()))))
        self.assertEqual(a, b)

    def test_validate_duplicates(self):
        with self.assertRaisesRegex(ValueError, "duplicate courier"):
            dispatch([Courier("C1", 1), Courier("C1", 1)], [], {})
        with self.assertRaisesRegex(ValueError, "duplicate order"):
            dispatch([], [Order("O1", 1), Order("O1", 1)], {})

    def test_reject_negative_and_non_integer_estimates(self):
        for value in (-1, 1.5, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                dispatch([Courier("C1", 1)], [Order("O1", 1)], {("C1", "O1"): value})

    def test_reject_unknown_matrix_pairs(self):
        with self.assertRaises(ValueError):
            dispatch([Courier("C1", 1)], [Order("O1", 1)], {("C2", "O1"): 2})

    def test_reject_bad_capacities(self):
        with self.assertRaises(ValueError):
            dispatch([Courier("C1", -1)], [], {})
        with self.assertRaises(ValueError):
            dispatch([], [Order("O1", 0)], {})

    def test_reject_bad_strategy(self):
        with self.assertRaises(ValueError):
            dispatch([], [], {}, strategy="random")


if __name__ == "__main__":
    unittest.main()
