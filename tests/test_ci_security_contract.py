"""Guard against regression in the repo's read-only, non-deploy CI.

This guard is source-level. It is NOT an independent protected verifier and
must not be used to claim full supply-chain assurance or branch protection.
"""

from pathlib import Path
import re
import unittest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"
FULL_SHA = re.compile(r"^(actions/(?:checkout|setup-python))@([0-9a-f]{40})$")


class CiSecurityContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = WORKFLOW.read_text(encoding="utf-8")

    def test_external_actions_are_pinned_to_full_commit_sha(self):
        actions = re.findall(r"(?m)^\s*- uses: ([^\s#]+)", self.raw)
        self.assertEqual(len(actions), 2)
        matched = [FULL_SHA.fullmatch(action) for action in actions]
        self.assertTrue(all(matched), f"untrusted/mutable action: {actions!r}")
        self.assertEqual(
            {match.group(1) for match in matched if match},
            {"actions/checkout", "actions/setup-python"},
        )

    def test_checkout_does_not_persist_credentials(self):
        self.assertRegex(
            self.raw,
            r"(?m)^      - uses: actions/checkout@[0-9a-f]{40}(?:[ \t]*\#[^\n]*)?\n"
            r"        with:\s*\n          persist-credentials: false(?:\s|$)",
        )

    def test_workflow_is_read_only_and_has_no_privileged_triggers(self):
        self.assertRegex(self.raw, r"(?m)^permissions:\s*\n  contents: read\s*\n")
        self.assertNotRegex(self.raw, r"(?m)^\s+(?:contents|id-token|packages|actions|checks|pull-requests): write\b")
        self.assertNotIn("pull_request_target:", self.raw)
        self.assertNotIn("workflow_run:", self.raw)
        self.assertNotIn("secrets.", self.raw)
        self.assertRegex(self.raw, r"(?m)^  pull_request:\s*$")

    def test_no_artifact_publish_or_deploy_steps(self):
        self.assertNotRegex(self.raw, r"(?m)^\s*- uses: actions/(?:upload-artifact|deploy-pages)@")
        self.assertNotIn("environment:", self.raw)


if __name__ == "__main__":
    unittest.main()
