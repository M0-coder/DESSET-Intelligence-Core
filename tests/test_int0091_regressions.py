"""READ-ONLY/negative controls for AUD-001 blockers; synthetic fixtures only."""

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_osrm_local import fake_server, response

from desset_core import MatrixInputError, RoadPoint, fetch_local_osrm_table
from desset_core.national import NationalProbeError, parse_national_probes

ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "scripts" / "build_peru_osrm.sh"
SCENARIOS = ROOT / "scenarios" / "peru-national-probes.json"
IMAGE = "ghcr.io/project-osrm/osrm-backend@sha256:" + "a" * 64

# Fake Docker backend: never runs containers or touches non-temporary files.
DOCKER_STUB = '''#!/usr/bin/env python3
import os
import sys
from pathlib import Path

args = sys.argv[1:]
with open(os.environ["TEST_DOCKER_LOG"], "a", encoding="utf-8") as f:
    f.write(" ".join(args) + "\\n")
if args[:2] == ["image", "inspect"]:
    sys.exit(0)
if args and args[0] == "run":
    mount = next(a for a in args if a.startswith("type=bind,src="))
    root = Path(mount.split("src=", 1)[1].split(",dst=/data", 1)[0])
    base = root / "peru-261123.osrm"
    if "osrm-extract" in args:
        base.write_bytes(b"SYNTHETIC-MOCK-GRAPH")
        (root / "peru-261123.osrm.ebg").write_bytes(b"SYNTHETIC-MOCK-EDGES")
    elif "osrm-partition" in args:
        (root / "peru-261123.osrm.partition").write_bytes(b"SYNTHETIC-MOCK-PARTITION")
    elif "osrm-customize" in args:
        (root / "peru-261123.osrm.cells").write_bytes(b"SYNTHETIC-MOCK-CELLS")
    sys.exit(0)
sys.exit(3)
'''


class BuildPreflightTests(unittest.TestCase):
    def _fixture(self, root):
        base = Path(root)
        binary = base / "bin"
        binary.mkdir()
        docker = binary / "docker"
        docker.write_text(DOCKER_STUB, encoding="utf-8")
        docker.chmod(0o755)
        pbf = base / "peru-261123.osm.pbf"
        data = bytes([0, 0, 0, 9]) + b"OSMHeader-TEST-NOT-REAL"
        pbf.write_bytes(data)
        log = base / "docker-calls.log"
        env = {**os.environ, "PATH": str(binary) + os.pathsep + os.environ["PATH"],
               "TEST_DOCKER_LOG": str(log)}
        command = ["bash", str(BUILD_SCRIPT), str(pbf), hashlib.sha256(data).hexdigest(), IMAGE]
        return pbf, data, log, env, command

    def test_existing_base_osrm_must_stop_before_docker(self):
        with tempfile.TemporaryDirectory() as folder:
            pbf, _, log, env, command = self._fixture(folder)
            base = pbf.with_suffix("").with_suffix("")  # 'peru-261123'
            graph = base.with_suffix(".osrm")
            graph.write_bytes(b"CRITICAL-EXISTING-ROAD-GRAPH")
            result = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing overwrite", result.stderr)
            self.assertEqual(graph.read_bytes(), b"CRITICAL-EXISTING-ROAD-GRAPH")
            self.assertFalse(log.exists() and "run " in log.read_text())

    def test_existing_manifest_must_stop_before_docker(self):
        with tempfile.TemporaryDirectory() as folder:
            pbf, _, log, env, command = self._fixture(folder)
            manifest = pbf.parent / "peru-261123.osrm-build-manifest.json"
            manifest.write_text("DO-NOT-OVERWRITE", encoding="utf-8")
            result = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing overwrite", result.stderr)
            self.assertEqual(manifest.read_text(), "DO-NOT-OVERWRITE")
            self.assertFalse(log.exists() and "run " in log.read_text())

    def test_existing_partial_graph_or_dangling_symlink_stops_before_docker(self):
        for item_name, symlink in (("peru-261123.osrm.cells", False),
                                   ("peru-261123.osrm", True)):
            with self.subTest(item_name=item_name), tempfile.TemporaryDirectory() as folder:
                pbf, _, log, env, command = self._fixture(folder)
                path = pbf.parent / item_name
                if symlink:
                    path.symlink_to(pbf.parent / "missing-target.osrm")
                else:
                    path.write_bytes(b"PARTIAL-PREVIOUS-BUILD")
                result = subprocess.run(command, env=env, capture_output=True, text=True,
                                        check=False)
                self.assertEqual(result.returncode, 2)
                self.assertIn("refusing overwrite", result.stderr)
                self.assertFalse(log.exists())

    def test_successful_mock_build_is_isolated_and_pbf_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            pbf, data, log, env, command = self._fixture(folder)
            result = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(pbf.read_bytes(), data)
            self.assertFalse((pbf.parent / "peru-261123.osrm").exists())
            self.assertFalse((pbf.parent / "peru-261123.osrm-build-manifest.json").exists())
            dirs = list(pbf.parent.glob("peru-261123.osrm-build.*"))
            self.assertEqual(len(dirs), 1)
            staging = dirs[0]
            self.assertTrue((staging / "peru-261123.osrm").is_file())
            manifest = json.loads((staging / "peru-261123.osrm-build-manifest.json").read_text())
            self.assertEqual(manifest["candidate_decision"], "BLOCKED")
            self.assertEqual(manifest["nationwide_coverage_control_result"], "NOT_VERIFIED")
            self.assertTrue(log.exists())
            calls = log.read_text(encoding="utf-8")
            self.assertEqual(calls.count("run --rm"), 3)
            # Regression: every OSRM writer must use the invoking host identity.
            for call in calls.splitlines():
                if call.startswith("run "):
                    self.assertIn(f"--user {os.getuid()}:{os.getgid()} ", call)
            self.assertIn("--network none", calls)
            self.assertIn(str(staging), calls)


class OsrmWaypointBindingTests(unittest.TestCase):
    def test_too_close_waypoints_swapped_must_fail_closed(self):
        sources = [RoadPoint("A", -77.605, -11.11), RoadPoint("B", -77.6051, -11.11)]
        destinations = [RoadPoint("D", -77.7, -11.2)]
        fake = response(c=sources, o=destinations, durations=[[900], [1]])
        fake["sources"] = list(reversed(fake["sources"]))
        with fake_server(fake) as (url, _), self.assertRaisesRegex(
            MatrixInputError, "ambiguous|overlap|permutation"
        ):
            fetch_local_osrm_table(sources, destinations, dataset_ref="FAKE", transport_profile="FAKE", base_url=url)

    def test_distant_waypoints_remain_accepted(self):
        sources = [RoadPoint("A", -77.605, -11.11), RoadPoint("B", -77.607, -11.11)]
        destinations = [RoadPoint("D", -77.7, -11.2)]
        fake = response(c=sources, o=destinations, durations=[[20], [30]])
        with fake_server(fake) as (url, _):
            out = fetch_local_osrm_table(sources, destinations, dataset_ref="FAKE", transport_profile="FAKE", base_url=url)
        self.assertEqual(out.matrix.pickup_seconds[("A", "D")], 20)


class PeruClassificationTests(unittest.TestCase):
    def test_interprovincial_cannot_use_two_regions(self):
        obj = json.loads(SCENARIOS.read_text())
        obj["probes"][7]["kind"] = "interprovincial"
        with self.assertRaisesRegex(NationalProbeError, "interprovincial"):
            parse_national_probes(obj)

    def test_valid_national_sample_still_parses(self):
        obj = json.loads(SCENARIOS.read_text())
        self.assertEqual(len(parse_national_probes(obj)), 10)


if __name__ == "__main__":
    unittest.main()
