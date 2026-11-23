"""CI contracts for the optional nationwide OSRM preparation runner."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "scripts" / "build_peru_osrm.sh"


@contextmanager
def synthetic_local_osrm():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            coords = urlsplit(self.path).path.split("/driving/", 1)[1].split(";")
            locations = [[float(s) for s in location.split(",")] for location in coords]
            payload = {
                "code": "Ok",
                "durations": [[120.01]],
                "sources": [{"location": locations[0], "distance": 0}],
                "destinations": [{"location": locations[1], "distance": 0}],
            }
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
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


class NationalRunnerContractTests(unittest.TestCase):
    def test_instrumented_cli_mock_never_claims_national_coverage(self):
        with tempfile.TemporaryDirectory() as folder, synthetic_local_osrm() as url:
            root = Path(folder)
            pbf = root / "peru-261122.osm.pbf"
            fake_bytes = bytes([0, 0, 0, 9]) + b"OSMHeader"
            pbf.write_bytes(fake_bytes)
            out = root / "probe-result.json"
            env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
            command = [
                sys.executable, str(ROOT / "scripts" / "probe_peru_osrm.py"),
                "--scenarios", str(ROOT / "scenarios" / "peru-national-probes.json"),
                "--pbf", str(pbf),
                "--pbf-sha256", hashlib.sha256(fake_bytes).hexdigest(),
                "--dataset-ref", "TEST_ONLY_NOT_OSM",
                "--profile", "SYNTHETIC",
                "--base-url", url, "--output", str(out),
            ]
            result = subprocess.run(command, check=False, capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(report["counts"]["queries_pass"], 10)
            self.assertEqual(report["nationwide_coverage_control_result"], "NOT_VERIFIED")
            self.assertFalse(report["network_provenance_verified"])
            self.assertEqual(report["candidate_decision"], "BLOCKED")

    def test_script_syntax(self):
        subprocess.run(["bash", "-n", str(BUILD)], check=True, capture_output=True)

    def test_build_requires_pinned_image_and_network_isolation(self):
        source = BUILD.read_text(encoding="utf-8")
        self.assertIn("ghcr.io/project-osrm/osrm-backend@sha256:", source)
        self.assertIn("--network none", source)
        self.assertIn("--pull never", source)
        self.assertIn("docker image inspect", source)
        self.assertIn("refusing overwrite", source)
        self.assertNotIn("docker push", source)

    def test_build_with_no_parameters_fails_before_docker(self):
        done = subprocess.run(["bash", str(BUILD)], check=False, capture_output=True, text=True)
        self.assertEqual(done.returncode, 2)
        self.assertIn("usage:", done.stderr)


if __name__ == "__main__":
    unittest.main()
