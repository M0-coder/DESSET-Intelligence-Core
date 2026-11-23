"""Property-based checks; only activated when the pinned Hypothesis is installed.

All generated objects are artificial. These checks cannot validate real ETAs.
"""

import itertools
import unittest

from desset_core.dispatch import Courier, Order, dispatch

try:
    from hypothesis import given, settings, strategies as st
except ImportError:
    class RequiresHypothesis(unittest.TestCase):
        @unittest.skip("Hypothesis not installed; required in CI")
        def test_hypothesis_dependency_unavailable(self):
            pass
else:
    class DispatchProperties(unittest.TestCase):
        @settings(max_examples=100, derandomize=True, deadline=None)
        @given(data=st.data(), n=st.integers(0, 4), m=st.integers(0, 4))
        def test_cardinality_cost_and_permutation(self, data, n, m):
            couriers = [Courier(f"C{i}", 1) for i in range(n)]
            orders = [Order(f"O{i}", 1) for i in range(m)]
            times = data.draw(st.lists(
                st.one_of(st.none(), st.integers(0, 100)),
                min_size=n * m, max_size=n * m,
            ))
            matrix = {
                (courier.id, order.id): seconds
                for (courier, order), seconds in zip(
                    itertools.product(couriers, orders), times, strict=True
                )
                if seconds is not None
            }
            result = dispatch(couriers, orders, matrix)
            self.assertEqual(len({a.courier_id for a in result.assignments}),
                             len(result.assignments))
            self.assertEqual(len({a.order_id for a in result.assignments}),
                             len(result.assignments))
            self.assertTrue(all(
                a.estimated_pickup_seconds == matrix[(a.courier_id, a.order_id)]
                for a in result.assignments
            ))
            self.assertEqual(
                result,
                dispatch(list(reversed(couriers)), list(reversed(orders)),
                         dict(reversed(list(matrix.items())))),
            )

            best = (0, 0)
            for count in range(1, min(n, m) + 1):
                for selected_orders in itertools.combinations(orders, count):
                    for selected_couriers in itertools.permutations(couriers, count):
                        pairs = list(zip(selected_couriers, selected_orders, strict=True))
                        if all((c.id, o.id) in matrix for c, o in pairs):
                            cost = sum(matrix[(c.id, o.id)] for c, o in pairs)
                            if count > best[0] or (count == best[0] and cost < best[1]):
                                best = (count, cost)
            self.assertEqual(
                (len(result.assignments), result.total_estimated_pickup_seconds),
                best,
            )
