"""AUD-002 regressions. Files and HTTP responses are synthetic, not real OSRM."""

import hashlib
import json
import os
import runpy
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_graph_evidence import BASE, IMAGE, NAME, make_staging
from test_national_runner_contract import synthetic_local_osrm
from test_osrm_local import fake_server, response

from desset_core.graph_evidence import verify_staged_peru_graph
from desset_core.national import (
    NationalProbeError,
    load_probes,
    parse_national_probes,
    run_national_probes,
)

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / 'scenarios/peru-national-probes.json'


class Audit002Tests(unittest.TestCase):
    def test_output_cannot_overwrite_pbf_or_existing_alias(self):
        with tempfile.TemporaryDirectory() as tmp, synthetic_local_osrm() as url:
            directory = Path(tmp)
            pbf = directory / NAME
            data = bytes([0, 0, 0, 9]) + b'OSMHeader'
            pbf.write_bytes(data)
            alias = directory / 'alias.json'
            alias.symlink_to(pbf)
            hardlink = directory / 'hardlink.json'
            hardlink.hardlink_to(pbf)
            prior = directory / 'prior.json'
            prior.write_bytes(b'prior evidence')
            for target in (pbf, alias, hardlink, prior):
                with self.subTest(target=target):
                    pbf.write_bytes(data)
                    prior.write_bytes(b'prior evidence')
                    command = [sys.executable, str(ROOT / 'scripts/probe_peru_osrm.py'),
                               '--scenarios', str(SCENARIOS), '--pbf', str(pbf),
                               '--pbf-sha256', hashlib.sha256(data).hexdigest(),
                               '--dataset-ref', 'TEST', '--base-url', url,
                               '--output', str(target)]
                    result = subprocess.run(command, capture_output=True, text=True, check=False)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(pbf.read_bytes(), data)
                    self.assertEqual(prior.read_bytes(), b'prior evidence')

    def test_output_cannot_create_file_inside_staging(self):
        with tempfile.TemporaryDirectory() as tmp, synthetic_local_osrm() as url:
            directory, digest, _ = make_staging(Path(tmp))
            alias = Path(tmp) / 'alias'
            alias.symlink_to(directory, target_is_directory=True)
            out = alias / 'result.json'
            result = subprocess.run([
                sys.executable, str(ROOT / 'scripts/probe_peru_osrm.py'),
                '--scenarios', str(SCENARIOS), '--pbf', str(directory / NAME),
                '--pbf-sha256', digest, '--dataset-ref', 'TEST', '--base-url', url,
                '--graph-dir', str(directory), '--image-reference', IMAGE, '--output', str(out),
            ], capture_output=True, text=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(out.exists())

    def test_consistent_but_incomplete_or_empty_mld_rejected(self):
        for empty in (False, True):
            with self.subTest(empty=empty), tempfile.TemporaryDirectory() as tmp:
                directory, digest, manifest = make_staging(Path(tmp))
                for item in manifest['artifacts']:
                    (directory / item['name']).unlink()
                artifact = directory / f'{BASE}.osrm'
                data = b'' if empty else b'NOT A GRAPH'
                artifact.write_bytes(data)
                manifest['artifacts'] = [{'name': artifact.name, 'bytes': len(data),
                                          'sha256': hashlib.sha256(data).hexdigest()}]
                (directory / f'{BASE}.osrm-build-manifest.json').write_text(json.dumps(manifest))
                with self.assertRaises(NationalProbeError):
                    verify_staged_peru_graph(directory, expected_pbf_sha256=digest,
                                             expected_image_reference=IMAGE)

    def test_classification_separates_null_and_unavailable(self):
        probe = load_probes(SCENARIOS)[0]
        payload = response(c=[probe.origin], o=[probe.destination], durations=[[None]])
        with fake_server(payload) as (url, _):
            report = run_national_probes((probe,), dataset_ref='TEST', transport_profile='TEST', base_url=url)
        self.assertEqual(report['probe_results'][0]['route_outcome'], 'NO_ROUTE')
        self.assertEqual(report['probe_results'][0]['control_result'], 'FAIL')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            url = f'http://127.0.0.1:{sock.getsockname()[1]}'
            report = run_national_probes((probe,), dataset_ref='TEST', transport_profile='TEST', base_url=url)
        self.assertEqual(report['probe_results'][0]['route_outcome'], 'INFRA_FAILURE')
        self.assertEqual(report['route_query_control_result'], 'INFRA_FAILURE')

    def test_declared_no_route_expectation_does_not_claim_road_coverage(self):
        obj = json.loads(SCENARIOS.read_text())
        obj['probes'] = obj['probes'][:1]
        obj['probes'][0]['expected_outcome'] = 'NO_ROUTE'
        probe = parse_national_probes(obj)[0]
        payload = response(c=[probe.origin], o=[probe.destination], durations=[[None]])
        with fake_server(payload) as (url, _):
            report = run_national_probes((probe,), dataset_ref='TEST', transport_profile='TEST', base_url=url)
        self.assertEqual(report['route_query_control_result'], 'PASS')
        self.assertEqual(report['jurisdictions_with_passing_probe'], [])
        self.assertEqual(report['candidate_decision'], 'BLOCKED')
        obj['probes'][0]['expected_outcome'] = 'INVALID'
        with self.assertRaises(NationalProbeError):
            parse_national_probes(obj)

    def test_required_artifact_empty_even_with_consistent_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory, digest, manifest = make_staging(Path(tmp))
            artifact = directory / f'{BASE}.osrm.partition'
            artifact.write_bytes(b'')
            entry = next(item for item in manifest['artifacts'] if item['name'] == artifact.name)
            entry.update(bytes=0, sha256=hashlib.sha256(b'').hexdigest())
            (directory / f'{BASE}.osrm-build-manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(NationalProbeError, 'empty'):
                verify_staged_peru_graph(directory, expected_pbf_sha256=digest,
                                         expected_image_reference=IMAGE)

    def test_racing_output_creation_never_overwrites_existing_file(self):
        publish = runpy.run_path(str(ROOT / 'scripts/probe_peru_osrm.py'))['_write_report']
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'report.json'
            original_link = os.link

            def racing_link(source, destination):
                Path(destination).write_bytes(b'other writer evidence')
                original_link(source, destination)

            with patch('os.link', side_effect=racing_link), self.assertRaises(FileExistsError):
                publish(target, {'candidate_decision': 'BLOCKED'})
            self.assertEqual(target.read_bytes(), b'other writer evidence')
            self.assertEqual(list(Path(tmp).iterdir()), [target])

    def test_invalid_response_and_unexpected_route_are_not_infrastructure_failure(self):
        obj = json.loads(SCENARIOS.read_text())
        obj['probes'] = obj['probes'][:1]
        obj['probes'][0]['expected_outcome'] = 'NO_ROUTE'
        probe = parse_national_probes(obj)[0]
        payload = response(c=[probe.origin], o=[probe.destination], durations=[[20]])
        with fake_server(payload) as (url, _):
            report = run_national_probes((probe,), dataset_ref='TEST', transport_profile='TEST', base_url=url)
        self.assertEqual(report['probe_results'][0]['reason'], 'UNEXPECTED_ROUTE')
        self.assertEqual(report['route_query_control_result'], 'FAIL')
        with fake_server({'code': 'Ok'}) as (url, _):
            report = run_national_probes((probe,), dataset_ref='TEST', transport_profile='TEST', base_url=url)
        self.assertEqual(report['probe_results'][0]['route_outcome'], 'INVALID_INPUT_OR_RESPONSE')
        self.assertEqual(report['route_query_control_result'], 'FAIL')
