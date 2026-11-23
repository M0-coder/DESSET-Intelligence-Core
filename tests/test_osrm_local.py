"""Loopback HTTP contract tests. The test server is NOT an OSRM road engine."""

import json
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from desset_core import (
    Courier,
    MatrixInputError,
    Order,
    RoadPoint,
    dispatch,
    fetch_local_osrm_table,
)


@contextmanager
def fake_server(payload, status=200, encoding=None):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            raw = encoding if encoding is not None else json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


C = [RoadPoint("R1", -77.605, -11.110), RoadPoint("R2", -77.606, -11.111)]
O = [RoadPoint("P1", -77.607, -11.112), RoadPoint("P2", -77.608, -11.113)]


def response(c=C, o=O, durations=None):
    return {
        "code": "Ok", "durations": durations or [[5, 10], [8, 6]],
        "sources": [
            {"location": [p.longitude, p.latitude], "distance": 0} for p in c
        ],
        "destinations": [
            {"location": [p.longitude, p.latitude], "distance": 0} for p in o
        ],
    }


def query(url, c=C, o=O, **kwargs):
    return fetch_local_osrm_table(
        c, o, dataset_ref="SYNTHETIC-HTTP-ONLY", transport_profile="test-profile",
        base_url=url, **kwargs,
    )


class LocalOsrmTests(unittest.TestCase):
    def test_full_http_contract_dispatch_and_source_indices(self):
        with fake_server(response()) as (url, requests):
            result = query(url)
            outcome = dispatch(
                [Courier("R1", 1), Courier("R2", 1)],
                [Order("P1", 1), Order("P2", 1)],
                result.matrix.pickup_seconds,
            )
        self.assertEqual(len(outcome.assignments), 2)
        self.assertEqual(outcome.total_estimated_pickup_seconds, 11)
        self.assertEqual(len(result.request_sha256), 64)
        self.assertFalse(result.matrix.provenance.dataset_verified)
        self.assertTrue(requests[0].startswith("/table/v1/driving/-77.6050000,-11.1100000;"))
        self.assertIn("sources=0;1&destinations=2;3&annotations=duration", requests[0])
        self.assertEqual(result.snap_distances_meters, (0, 0, 0, 0))

    def test_asymmetry_and_missing_routes(self):
        with fake_server(response(durations=[[None, 9.1], [40, 3.01]])) as (url, _):
            result = query(url)
        self.assertNotIn(("R1", "P1"), result.matrix.pickup_seconds)
        self.assertEqual(result.matrix.pickup_seconds[("R2", "P2")], 4)

    def test_untrusted_snap_rejected_even_if_server_reports_zero(self):
        payload = response()
        payload["sources"][0]["location"] = [-77.5, -11.11]
        with (
            fake_server(payload) as (url, _),
            self.assertRaisesRegex(MatrixInputError, "snapped too far"),
        ):
            query(url)

    def test_excessive_reported_snap_rejected(self):
        payload = response()
        payload["destinations"][0]["distance"] = 500
        with (
            fake_server(payload) as (url, _),
            self.assertRaisesRegex(MatrixInputError, "snapped too far"),
        ):
            query(url)

    def test_missing_waypoint_binding_rejected(self):
        payload = response()
        payload.pop("sources")
        with (
            fake_server(payload) as (url, _),
            self.assertRaisesRegex(MatrixInputError, "cannot bind"),
        ):
            query(url)

    def test_wrong_waypoint_order_rejected(self):
        payload = response()
        payload["destinations"] = list(reversed(payload["destinations"]))
        with (
            fake_server(payload) as (url, _),
            self.assertRaisesRegex(MatrixInputError, "snapped too far"),
        ):
            query(url)

    def test_fallback_cells_rejected(self):
        payload = response()
        payload["fallback_speed_cells"] = [[0, 1]]
        with (
            fake_server(payload) as (url, _),
            self.assertRaisesRegex(MatrixInputError, "fallback"),
        ):
            query(url)

    def test_http_errors_are_fail_closed(self):
        with (
            fake_server({"code": "Error"}, status=503) as (url, _),
            self.assertRaisesRegex(MatrixInputError, "503"),
        ):
            query(url)
        with (
            fake_server({}, status=302) as (url, _),
            self.assertRaisesRegex(MatrixInputError, "302"),
        ):
            query(url)
        with (
            fake_server({}, encoding=b"<html>not JSON</html>") as (url, _),
            self.assertRaisesRegex(MatrixInputError, "valid JSON"),
        ):
            query(url)

    def test_invalid_coordinates_or_duplicate_ids(self):
        for c in ([RoadPoint("A", 181, -11)], [RoadPoint("A", float("nan"), -11)],
                  [RoadPoint("A", -77, -11), RoadPoint("A", -77, -11)],
                  [RoadPoint("A", True, -11)]):
            with self.subTest(c=c), self.assertRaises(MatrixInputError):
                fetch_local_osrm_table(c, O, dataset_ref="x", transport_profile="x")

    def test_external_hosts_never_allowed(self):
        for url in ("http://example.com:5000", "https://127.0.0.1:5000",
                    "http://127.0.0.1:5000/anything", "http://127.0.0.1:5000@evil.test:5000",
                    "http://127.0.0.1:abc", "http://127.0.0.1:5000/?x=1"):
            with self.subTest(url=url), self.assertRaises(MatrixInputError):
                query(url)

    def test_limit_and_bad_timeout(self):
        for opts in ({"timeout_seconds": -1}, {"max_snap_meters": 501},
                     {"timeout_seconds": float("inf")}):
            with self.subTest(opts=opts), self.assertRaises(MatrixInputError):
                query("http://127.0.0.1:5000", **opts)
        many = [RoadPoint(f"R{i}", -77.6, -11.11) for i in range(100)]
        with self.assertRaisesRegex(MatrixInputError, "location limit"):
            fetch_local_osrm_table(many, O, dataset_ref="x", transport_profile="x")

    def test_request_digest_changes_with_coordinate(self):
        with fake_server(response()) as (url, _):
            a = query(url)
            shifted = [RoadPoint("R1", -77.6050001, -11.110), C[1]]
            b = query(url, c=shifted)
        self.assertNotEqual(a.request_sha256, b.request_sha256)

    def test_reject_unbounded_coordinate_integer(self):
        with self.assertRaises(MatrixInputError):
            fetch_local_osrm_table(
                [RoadPoint("R1", 10**400, -11)], O,
                dataset_ref="SYNTHETIC", transport_profile="car",
            )

    def test_request_digest_binds_identifiers_not_only_coordinates(self):
        with fake_server(response()) as (url, _):
            a = query(url)
            relabelled = [RoadPoint("OTHER", C[0].longitude, C[0].latitude), C[1]]
            b = query(url, c=relabelled)
        self.assertNotEqual(a.request_sha256, b.request_sha256)

    def test_row_vs_column_permutation_is_rejected_when_waypoints_mismatch(self):
        payload = response()
        payload["sources"] = list(reversed(payload["sources"]))
        with (
            fake_server(payload) as (url, _),
            self.assertRaisesRegex(MatrixInputError, "snapped too far"),
        ):
            query(url)


if __name__ == "__main__":
    unittest.main()
