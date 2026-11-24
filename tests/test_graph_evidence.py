"""Independent fail-closed checks; fake PBF/files do NOT establish road coverage."""

import hashlib
import json
import subprocess
import threading
import sys
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from desset_core.graph_evidence import verify_staged_peru_graph
from desset_core.national import NationalProbeError

IMAGE = "ghcr.io/project-osrm/osrm-backend@sha256:" + "a" * 64
NAME = "peru-261123.osm.pbf"
BASE = "peru-261123"


def make_staging(root):
    data = root / "stage"
    data.mkdir()
    pbf = data / NAME
    # This is ONLY a structural placeholder; a real OSM parser would reject it.
    fake_blob = b"OSMHeader\x00TEST-ONLY\x00"
    pbf.write_bytes(len(fake_blob).to_bytes(4, "big") + fake_blob)
    digest = hashlib.sha256(pbf.read_bytes()).hexdigest()
    a = data / f"{BASE}.osrm"
    b = data / f"{BASE}.osrm.nodes"
    a.write_bytes(b"not-an-osrm-graph")
    b.write_bytes(b"not-osrm-nodes")
    artifacts = [{"name": item.name, "bytes": item.stat().st_size,
                  "sha256": hashlib.sha256(item.read_bytes()).hexdigest()}
                 for item in (a, b)]
    manifest = {
        "country_code": "PE", "pbf_name": NAME, "pbf_sha256": digest,
        "image_reference": IMAGE, "osrm_algorithm": "MLD",
        "osrm_profile_declared": "/opt/car.lua", "preprocess_control_result": "PASS",
        "nationwide_coverage_control_result": "NOT_VERIFIED", "candidate_decision": "BLOCKED",
        "artifacts": artifacts,
    }
    (data / f"{BASE}.osrm-build-manifest.json").write_text(json.dumps(manifest))
    return data, digest, manifest


class GraphEvidenceTests(unittest.TestCase):
    def test_manifest_hash_and_directory_integrity_pass_but_not_real_osrm(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory, digest, _ = make_staging(Path(tmp))
            result = verify_staged_peru_graph(
                directory, expected_pbf_sha256=digest, expected_image_reference=IMAGE,
            )
            self.assertEqual(result["graph_artifact_integrity_control_result"], "PASS")
            self.assertEqual(result["artifact_count"], 2)
            self.assertEqual(result["daemon_graph_binding_control_result"], "NOT_VERIFIED")
            self.assertEqual(result["dataset_source_authenticity_control_result"], "NOT_VERIFIED")
            self.assertEqual(result["candidate_decision"], "BLOCKED")

    def test_tampered_graph_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory, digest, _ = make_staging(Path(tmp))
            (directory / f"{BASE}.osrm.nodes").write_bytes(b"tampered")
            with self.assertRaisesRegex(NationalProbeError, "tampered"):
                verify_staged_peru_graph(
                    directory, expected_pbf_sha256=digest, expected_image_reference=IMAGE,
                )

    def test_uninventoried_graph_file_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory, digest, _ = make_staging(Path(tmp))
            (directory / f"{BASE}.osrm.partition").write_bytes(b"unlisted")
            with self.assertRaisesRegex(NationalProbeError, "inventory differs"):
                verify_staged_peru_graph(
                    directory, expected_pbf_sha256=digest, expected_image_reference=IMAGE,
                )

    def test_manifest_declares_an_inexistent_graph_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory, digest, _ = make_staging(Path(tmp))
            (directory / f"{BASE}.osrm.nodes").unlink()
            with self.assertRaises(NationalProbeError):
                verify_staged_peru_graph(
                    directory, expected_pbf_sha256=digest, expected_image_reference=IMAGE,
                )

    def test_symlinks_rejected_including_graph_dir_and_pbf(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory, digest, _ = make_staging(Path(tmp))
            link = Path(tmp) / "symlink"
            link.symlink_to(directory, target_is_directory=True)
            with self.assertRaises(NationalProbeError):
                verify_staged_peru_graph(
                    link, expected_pbf_sha256=digest, expected_image_reference=IMAGE,
                )
            pbf = directory / NAME
            copy = Path(tmp) / "original.pbf"
            copy.write_bytes(pbf.read_bytes())
            pbf.unlink()
            pbf.symlink_to(copy)
            with self.assertRaisesRegex(NationalProbeError, "regular file"):
                verify_staged_peru_graph(
                    directory, expected_pbf_sha256=digest, expected_image_reference=IMAGE,
                )

    def test_foreign_graph_artifact_injection_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory, digest, manifest = make_staging(Path(tmp))
            manifest["artifacts"][0]["name"] = "../../file.osrm"
            (directory / f"{BASE}.osrm-build-manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(NationalProbeError, "artifact name"):
                verify_staged_peru_graph(
                    directory, expected_pbf_sha256=digest, expected_image_reference=IMAGE,
                )

    def test_manifest_falsified_pass_and_profile_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory, digest, manifest = make_staging(Path(tmp))
            manifest["osrm_profile_declared"] = "/opt/motorcycle.lua"
            (directory / f"{BASE}.osrm-build-manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(NationalProbeError, "declarations"):
                verify_staged_peru_graph(
                    directory, expected_pbf_sha256=digest, expected_image_reference=IMAGE,
                )

    def test_wrong_image_and_pbf_digest_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory, digest, _ = make_staging(Path(tmp))
            for kwargs in (
                {"expected_pbf_sha256": "f" * 64, "expected_image_reference": IMAGE},
                {"expected_pbf_sha256": digest, "expected_image_reference": IMAGE.replace("a" * 64, "b" * 64)},
                {"expected_pbf_sha256": digest, "expected_image_reference": "latest"},
            ):
                with self.subTest(kwargs=kwargs), self.assertRaises(NationalProbeError):
                    verify_staged_peru_graph(directory, **kwargs)

    def test_cli_reports_graph_files_but_never_attests_daemon(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory, digest, _ = make_staging(Path(tmp))
            source = Path(__file__).resolve().parents[1] / "scenarios/peru-national-probes.json"
            original = json.loads(source.read_text(encoding="utf-8"))
            original["probes"] = original["probes"][:1]
            probe = original["probes"][0]
            scenarios = Path(tmp) / "scenarios.json"
            scenarios.write_text(json.dumps(original))
            output = Path(tmp) / "report.json"

            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    payload = {"code": "Ok", "durations": [[12]],
                               "sources": [{"location": [probe["origin"]["longitude"],
                                                        probe["origin"]["latitude"]], "distance": 0}],
                               "destinations": [{"location": [probe["destination"]["longitude"],
                                                             probe["destination"]["latitude"]], "distance": 0}]}
                    raw = json.dumps(payload).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(raw)

                def log_message(self, *args):
                    pass

            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                args = [sys.executable, "scripts/probe_peru_osrm.py", "--scenarios", str(scenarios),
                        "--pbf", str(directory / NAME), "--pbf-sha256", digest,
                        "--dataset-ref", "SYNTHETIC-FIXTURE", "--graph-dir", str(directory),
                        "--image-reference", IMAGE, "--output", str(output),
                        "--base-url", f"http://127.0.0.1:{server.server_port}"]
                process = subprocess.run(args, check=False, capture_output=True, text=True)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
            self.assertEqual(process.returncode, 0, process.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["route_query_control_result"], "PASS")
            self.assertEqual(report["graph_artifact_integrity_control_result"], "PASS")
            self.assertEqual(report["daemon_graph_binding_control_result"], "NOT_VERIFIED")
            self.assertFalse(report["network_provenance_verified"])
            self.assertEqual(report["nationwide_coverage_control_result"], "NOT_VERIFIED")
            self.assertEqual(report["candidate_decision"], "BLOCKED")

    def test_cli_fails_closed_without_verified_graph_before_http_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory, digest, _ = make_staging(Path(tmp))
            pbf = directory / NAME
            badgraph = Path(tmp) / "missing"
            scenarios = Path(__file__).resolve().parents[1] / "scenarios/peru-national-probes.json"
            out = Path(tmp) / "result.json"
            args = [sys.executable, "scripts/probe_peru_osrm.py", "--scenarios", str(scenarios),
                    "--pbf", str(pbf), "--pbf-sha256", digest,
                    "--dataset-ref", "SYNTHETIC", "--graph-dir", str(badgraph),
                    "--image-reference", IMAGE, "--output", str(out)]
            process = subprocess.run(args, check=False, capture_output=True, text=True)
            self.assertEqual(process.returncode, 2)
            self.assertIn("national preflight failed", process.stderr)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
