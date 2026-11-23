# ADR-003 — Harden the offline Core CI without changing dispatch

**State:** proposal in draft PR. **Normative source:** [ASI Doctrina v3.3 — 00](https://app.notion.com/p/3b3eb559c05c81b5b971ee384164aa10); this ADR does not amend or redefine that doctrine.
**Decision log:** [DESSET Intelligence Core (separate Notion page)](https://app.notion.com/p/421eb559c05c81b0b4d7d4ac13253dda).

## Change budget and scope

- **Work Context:** REPOSITORY `M0-coder/DESSET-Intelligence-Core`.
- **Base candidate identity:** commit `7033227ae38426a226fb275d08948a869ed8a3c9` on draft PR #6, stacked on drafts #5 and #3.
- **Expected changed files:** `.github/workflows/ci.yml`, `tests/test_ci_security_contract.py`, this ADR. No algorithm, API, matrix parsing, user data, payment, other repository, deployment or release change.
- **Reversible by:** revert the isolated commit in its feature branch; no destructive mutation to `main`.

## Risk reproduced before editing

The current workflow references `actions/checkout@v4` and `actions/setup-python@v5`, both mutable *tag* references, and checkout uses its default `persist-credentials: true`. Scope: the test workflow uses read-only `GITHUB_TOKEN` and does not have secrets, but keeping credentials in checked-out Git configuration expands exposure to code executed within the job.

A newly written contract test produced **2 expected failures and 2 passes** on the original workflow, detecting tag usage and missing `persist-credentials: false`. This is **local RED evidence**, not a GitHub CI run.

GitHub official security documentation recommends complete commit SHA pins and checkout credential minimization: [GitHub secure use](https://docs.github.com/en/actions/reference/security/secure-use), [OWASP GitHub Actions Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/GitHub_Actions_Security_Cheat_Sheet.html).

## Minimal remediation

Pin the same action majors to full commits retrieved using GitHub's official Git refs API and validated as existing commit objects on 2026-11-23:

| Action | Reference | Observed commit SHA |
| --- | --- | --- |
| `actions/checkout@v4` | `https://api.github.com/repos/actions/checkout/git/ref/tags/v4` | `11d5960a326750d5838078e36cf38b85af677262` |
| `actions/setup-python@v5` | `https://api.github.com/repos/actions/setup-python/git/ref/tags/v5` | `a26af69be951a213d495a4c3e4e4022e16d87065` |

This pins code identity, **not proof of the action's security or provenance**. Set `persist-credentials: false` for checkout. Preserve read-only workflow permissions, `pull_request` trigger, `feature/**` push trigger, jobs and steps. Keep all existing Python tool versions unchanged.

## Tests and assurance

- Local **GREEN** after change: `python -m unittest discover -s tests -v` on the *isolated contract-test fixture* -> 4 PASS; Python test source compiles.
- CI on the full branch must run all the existing dispatch, routing and property tests. Previous CI result on an older SHA is **STALE_IDENTITY** for this candidate.
- A negative test must detect mutated tag/credential settings. The test itself is editable in a PR and must **not** be represented as a protected oracle.
- No total mutation coverage, package hashes/attestations, branch protection guarantee, independent review or data-source authenticity claim is made.
- Potential remaining risk: `pip install coverage==... hypothesis==... ruff==...` pins versions but not wheel hashes; packaging/dependency supply-chain assurance remains `NOT_VERIFIED` and is a separate, bounded future change.

## Canonical ASI linkage (references; no new norm authority)

- `ASI-NORM-WORK-CONTEXT-001` — context/candidate identity.
- `ASI-NORM-CHANGE-001` — small diff, RED/GREEN, rollback.
- `ASI-NORM-TESTING-001` — test-of-tests / negative checking.
- `ASI-NORM-SUPPLY-CHAIN-001` — action and checkout security.
- `ASI-NORM-CI-001` — CI is evidence, not release authority.
- `ASI-NORM-REPRO-001` — digest/commit/toolchain binding.
- `ASI-NORM-PROOF-001` — proof bundle and limitations.
- `ASI-NORM-DECISION-001` / `ASI-NORM-VERIFIED-DONE-001` — claim-scoped decision; **NO-GO production** until all applicable gates.

## Acceptance and stop conditions

**Claim C1:** only two approved external actions referenced via full 40-character SHA. **C2:** checkout credentials are not persisted. **C3:** workflow retains read-only token, no privileged triggers, no deploy steps. **C4:** all existing functional suites and lint still pass on exact candidate head.

Stop and report `candidate_decision=BLOCKED` for this PR if CI fails or source/workflow evidence is inconsistent. Integration to `main` and any deployment require a separate explicit authorization; this ADR **does not** authorize either. Separate claims about a protected Trust Anchor or ASI distribution are `NOT_VERIFIED`.
