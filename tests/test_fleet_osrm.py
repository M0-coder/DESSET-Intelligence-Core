"""HTTP boundary exercise with fake OSRM Table; NOT real street routing."""

import json
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from desset_core import (
    DeliveryJob,
    FleetVehicle,
    RoadPoint,
    fetch_local_osrm_table,
    optimize_fleet,
)


@contextmanager
def fake_osrm(payload):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            data = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


class FleetOsrmIntegration(unittest.TestCase):
    def test_all_to_all_matrix_to_fleet_exact(self):
        # Invented points/seconds, with all waypoint identities echoed by mock.
        pts = [
            RoadPoint("S1", -77.001, -12.001),
            RoadPoint("S2", -77.002, -12.002),
            RoadPoint("P", -77.003, -12.003),
            RoadPoint("D", -77.004, -12.004),
        ]
        n = len(pts)
        durations = [[0 if i == j else 40 for j in range(n)] for i in range(n)]
        durations[0][2] = 2
        durations[1][2] = 10
        durations[2][3] = 3
        waypoints = [{"location": [p.longitude, p.latitude], "distance": 0} for p in pts]
        payload = {
            "code": "Ok",
            "durations": durations,
            "sources": waypoints,
            "destinations": waypoints,
        }
        with fake_osrm(payload) as url:
            road = fetch_local_osrm_table(
                pts, pts, dataset_ref="SYNTHETIC-TEST-ONLY",
                transport_profile="unverified", base_url=url,
            )
        plan = optimize_fleet(
            [FleetVehicle("A", "S1", 1), FleetVehicle("B", "S2", 1)],
            [DeliveryJob("J", "P", "D", 1)], road.matrix.pickup_seconds,
        )
        self.assertEqual(plan.served_job_count, 1)
        self.assertEqual(plan.routes[0].vehicle_id, "A")
        self.assertEqual(plan.total_estimated_travel_seconds, 5)
        self.assertEqual(len(road.request_sha256), 64)
        self.assertFalse(road.matrix.provenance.dataset_verified)


if __name__ == "__main__":
    unittest.main()
