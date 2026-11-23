"""Unit tests for a synthetic OSRM-like payload, not real road evidence."""

import hashlib
import json
import math
import unittest

from desset_core.dispatch import Courier, Order, dispatch
from desset_core.routing_matrix import MatrixInputError, parse_osrm_table


class MatrixTests(unittest.TestCase):
    def build(self, response=None, **kwargs):
        response = response if response is not None else {
            "code": "Ok", "durations": [[0.0, 2.01], [None, 4.0]]
        }
        defaults = {
            "courier_ids": ["C1", "C2"],
            "order_ids": ["O1", "O2"],
            "dataset_ref": "SYNTHETIC_TEST_ONLY",
            "transport_profile": "synthetic-car",
        }
        defaults.update(kwargs)
        return parse_osrm_table(response, **defaults)

    def test_seconds_round_up_and_unreachable_are_not_imputed(self):
        result = self.build()
        self.assertEqual(result.pickup_seconds[("C1", "O1")], 0)
        self.assertEqual(result.pickup_seconds[("C1", "O2")], 3)
        self.assertNotIn(("C2", "O1"), result.pickup_seconds)
        self.assertEqual(result.unreachable_pairs, (("C2", "O1"),))
        self.assertFalse(result.provenance.dataset_verified)

    def test_dispatch_integration_with_unreachable_pair(self):
        matrix = self.build()
        result = dispatch(
            [Courier("C1", 1), Courier("C2", 1)],
            [Order("O1", 1), Order("O2", 1)],
            matrix.pickup_seconds,
        )
        self.assertEqual({a.order_id for a in result.assignments}, {"O1", "O2"})
        self.assertEqual(result.total_estimated_pickup_seconds, 4)

    def test_matrix_mapping_is_read_only(self):
        result = self.build()
        with self.assertRaises(TypeError):
            result.pickup_seconds[("C1", "O1")] = 999

    def test_digest_is_canonical_json_not_source_authentication(self):
        content = {"durations": [[0.0, 2.01], [None, 4.0]], "code": "Ok"}
        result = self.build(content)
        expected = hashlib.sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False).encode("utf-8")
        ).hexdigest()
        self.assertEqual(result.provenance.response_sha256, expected)
        self.assertEqual(result.provenance.response_sha256, self.build().provenance.response_sha256)

    def test_duplicate_source_or_destination_ids(self):
        for field in ("courier_ids", "order_ids"):
            with self.subTest(field=field), self.assertRaises(MatrixInputError):
                self.build(**{field: ["X", "X"]})

    def test_empty_ids_and_bad_label(self):
        for kwargs in (
            {"courier_ids": []}, {"order_ids": [""]},
            {"dataset_ref": " "}, {"transport_profile": " "},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(MatrixInputError):
                self.build(**kwargs)

    def test_malformed_and_failed_osrm_response(self):
        for response in (None, [], {}, {"code": "NoRoute"},
                         {"code": "Ok", "durations": None},
                         {"code": "Ok", "durations": [[]]},
                         {"code": "Ok", "durations": [[0.0, 1.0]]}):
            with self.subTest(response=response), self.assertRaises(MatrixInputError):
                parse_osrm_table(
                    response, courier_ids=["C1", "C2"], order_ids=["O1", "O2"],
                    dataset_ref="SYNTHETIC", transport_profile="car",
                )

    def test_invalid_seconds(self):
        for value in (-1, math.inf, math.nan, "1.3", True, -0.01):
            with self.subTest(value=value), self.assertRaises(MatrixInputError):
                self.build({"code": "Ok", "durations": [[0, value], [1, 2]]})

    def test_bad_fallback_or_malformed_json(self):
        for response in (
            {"code": "Ok", "durations": [[1, 2], [3, 4]],
             "fallback_speed_cells": [[0, 1]]},
            {"code": "Ok", "durations": [[1, 2], [3, 4]],
             "fallback_speed_cells": "false"},
            {"code": "Ok", "durations": [[1, 2], [3, 4]],
             "bad_extra_field": object()},
        ):
            with self.subTest(response=response), self.assertRaises(MatrixInputError):
                self.build(response)

    def test_size_limit(self):
        with self.assertRaisesRegex(MatrixInputError, "size limit"):
            self.build(courier_ids=[f"C{i}" for i in range(101)],
                       order_ids=[f"O{i}" for i in range(100)])

    def test_one_way_asymmetric_estimates_are_preserved(self):
        m = self.build({"code": "Ok", "durations": [[4, 17], [18, 7]]})
        self.assertEqual(m.pickup_seconds[("C1", "O2")], 17)
        self.assertEqual(m.pickup_seconds[("C2", "O1")], 18)


if __name__ == "__main__":
    unittest.main()
