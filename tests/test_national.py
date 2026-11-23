"""National smoke tests use a fake routing callback; never claim actual PE roads."""

import hashlib
import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from desset_core.national import (
    PERU_JURISDICTIONS,
    NationalProbeError,
    load_probes,
    parse_national_probes,
    run_national_probes,
    verify_local_pbf,
)
from desset_core.routing_matrix import MatrixInputError

SCENARIOS = Path(__file__).resolve().parents[1] / "scenarios" / "peru-national-probes.json"


@dataclass
class FakeProvenance:
    response_sha256: str = "a" * 64


@dataclass
class FakeMatrix:
    pickup_seconds: dict
    provenance: FakeProvenance


@dataclass
class FakeResponse:
    matrix: FakeMatrix
    request_sha256: str = "b" * 64


class PeruNationalTests(unittest.TestCase):
    def test_all_25_jurisdictions_are_registered(self):
        self.assertEqual(len(PERU_JURISDICTIONS), 25)
        self.assertIn("Callao", PERU_JURISDICTIONS)
        self.assertIn("Loreto", PERU_JURISDICTIONS)

    def test_sample_covers_multiple_cities_not_whole_country(self):
        probes = load_probes(SCENARIOS)
        self.assertEqual(len(probes), 10)
        sampled = {r for probe in probes for r in probe.regions}
        self.assertLess(len(sampled), 25)
        self.assertTrue({"Lima", "Cusco", "Loreto", "Tacna"}.issubset(sampled))

    def test_manifest_requires_explicit_unverified_coordinates(self):
        obj = json.loads(SCENARIOS.read_text())
        obj["coordinate_accuracy"] = "CERTIFIED"
        with self.assertRaises(NationalProbeError):
            parse_national_probes(obj)
        obj = json.loads(SCENARIOS.read_text())
        obj["probes"][0]["coordinate_evidence"] = "PASS"
        with self.assertRaises(NationalProbeError):
            parse_national_probes(obj)

    def test_register_fails_closed_for_missing_region_or_malformed(self):
        obj = json.loads(SCENARIOS.read_text())
        obj["jurisdictions"].pop()
        with self.assertRaises(NationalProbeError):
            parse_national_probes(obj)
        obj = json.loads(SCENARIOS.read_text())
        obj["jurisdictions"][0] = {"bad": "type"}
        with self.assertRaises(NationalProbeError):
            parse_national_probes(obj)
        obj = json.loads(SCENARIOS.read_text())
        obj["probes"][0]["regions"] = ["Nonexistent"]
        with self.assertRaises(NationalProbeError):
            parse_national_probes(obj)

    def test_rejects_duplicated_probe_id(self):
        obj = json.loads(SCENARIOS.read_text())
        obj["probes"][1]["id"] = obj["probes"][0]["id"]
        with self.assertRaises(NationalProbeError):
            parse_national_probes(obj)

    def test_pbf_sha_mismatch_is_rejected_before_routing(self):
        with tempfile.TemporaryDirectory() as tmp:
            pbf = Path(tmp) / "peru-261122.osm.pbf"
            pbf.write_bytes(bytes([0, 0, 0, 9]) + b"OSMHeader")
            with self.assertRaisesRegex(NationalProbeError, "mismatch"):
                verify_local_pbf(pbf, expected_sha256="0" * 64)

    def test_pbf_verified_means_only_equality_of_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            pbf = Path(tmp) / "peru-261122.osm.pbf"
            data = bytes([0, 0, 0, 9]) + b"OSMHeader"
            pbf.write_bytes(data)
            report = verify_local_pbf(pbf, expected_sha256=hashlib.sha256(data).hexdigest())
            self.assertEqual(report["sha256"], hashlib.sha256(data).hexdigest())
            self.assertIn("not authenticated", report["limitation"])

    def test_invalid_digest_never_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            pbf = Path(tmp) / "peru-261122.osm.pbf"
            pbf.write_bytes(b"test")
            for digest in ("", "bad", "G" * 64):
                with self.subTest(digest=digest), self.assertRaises(NationalProbeError):
                    verify_local_pbf(pbf, expected_sha256=digest)

    def test_all_mocked_routes_success_does_not_grant_national_coverage(self):
        probes = load_probes(SCENARIOS)

        def fake_query(sources, destinations, **_):
            return FakeResponse(FakeMatrix({(sources[0].id, destinations[0].id): 42}, FakeProvenance()))

        with patch("desset_core.national.fetch_local_osrm_table", side_effect=fake_query):
            out = run_national_probes(probes, dataset_ref="SYNTHETIC", transport_profile="fake")
        self.assertEqual(out["counts"]["queries_pass"], 10)
        self.assertEqual(out["route_query_control_result"], "PASS")
        self.assertEqual(out["nationwide_coverage_control_result"], "NOT_VERIFIED")
        self.assertEqual(out["candidate_decision"], "BLOCKED")
        self.assertGreater(len(out["jurisdictions_without_probe"]), 0)

    def test_one_failure_is_not_hidden_among_passes(self):
        probes = load_probes(SCENARIOS)[:2]
        calls = 0

        def fake_query(sources, destinations, **_):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise MatrixInputError("no local network")
            return FakeResponse(FakeMatrix({(sources[0].id, destinations[0].id): 33}, FakeProvenance()))

        with patch("desset_core.national.fetch_local_osrm_table", side_effect=fake_query):
            out = run_national_probes(probes, dataset_ref="SYNTHETIC", transport_profile="fake")
        self.assertEqual(out["counts"], {"probes_total": 2, "queries_pass": 1, "queries_fail": 1})
        self.assertEqual(out["route_query_control_result"], "FAIL")
        self.assertEqual(out["probe_results"][1]["reason"], "no local network")

    def test_null_route_is_a_failed_probe_not_fabricated_time(self):
        probes = load_probes(SCENARIOS)[:1]
        with patch("desset_core.national.fetch_local_osrm_table", return_value=FakeResponse(FakeMatrix({}, FakeProvenance()))):
            out = run_national_probes(probes, dataset_ref="SYNTHETIC", transport_profile="fake")
        self.assertEqual(out["counts"]["queries_fail"], 1)
        self.assertEqual(out["probe_results"][0]["reason"], "NO_ROUTE_OR_UNREACHABLE")
        self.assertIsNone(out["probe_results"][0]["duration_seconds"])

    def test_non_pbf_or_unstable_latest_filename_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for filename in ("peru-latest.osm.pbf", "other-261122.osm.pbf"):
                with self.subTest(filename=filename):
                    pbf = Path(tmp) / filename
                    data = bytes([0, 0, 0, 9]) + b"OSMHeader"
                    pbf.write_bytes(data)
                    with self.assertRaises(NationalProbeError):
                        verify_local_pbf(pbf, expected_sha256=hashlib.sha256(data).hexdigest())

    def test_corrupt_pbf_header_rejected_even_with_matching_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            for data in (b"", b"not an OSM PBF", bytes([0, 0, 0, 0])):
                with self.subTest(data=data):
                    pbf = Path(tmp) / "peru-261122.osm.pbf"
                    pbf.write_bytes(data)
                    with self.assertRaises(NationalProbeError):
                        verify_local_pbf(pbf, expected_sha256=hashlib.sha256(data).hexdigest())

    def test_nonexistent_scenario_file_rejected(self):
        with self.assertRaises(NationalProbeError):
            load_probes(Path("/nonexistent/peru-scenario.json"))


if __name__ == "__main__":
    unittest.main()
