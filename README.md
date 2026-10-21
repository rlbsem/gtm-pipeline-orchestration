# GTM Pipeline Orchestration

**Connect account intelligence to an owned sales action—and trace what happens afterward.**

Prospecting, qualification, CRM routing and engagement often operate in separate tools. This engine connects them in one inspectable SDR workflow: discover an account, resolve identity, explain fit and intent, route an inquiry, review an action, enroll it safely, and follow reply, meeting and opportunity feedback into an account-level experiment.

The Python application and independent HTTP engagement destination **execute locally** with durable databases. All companies, contacts, requests and outcomes are synthetic. No customer communications, live CRM connection or commercial uplift is claimed. The optional authenticated local LLM adapter is implemented and contract-tested; **fresh model inference has not been executed for this repository**.

![Actual pipeline overview, independent receipts and account-level treatment comparison](docs/images/pipeline-overview.png)

*Captured from the running application. [Screenshot provenance and browser execution](docs/images/provenance.json).*

## Run the complete loop

Use Python **3.12** from the repository root:

```text
python -m venv .venv
```

Activate `.venv\Scripts\Activate.ps1` in Windows PowerShell, or `source .venv/bin/activate` on macOS/Linux. Then:

```text
python -m pip install -r requirements.lock
python -m pip install --no-deps --no-build-isolation -e .
gtm demo --workspace .local/demo
gtm serve --workspace .local/demo
```

Open **http://127.0.0.1:8560/**. The demo writes real HTTP requests and separate control/engagement databases. Existing workspaces are preserved. Use a fresh workspace name to reproduce the original scenario; interactive changes remain in the workspace you use.

1. Inspect an account's sources, score contributions, owner and cohort.
2. In **Account workbench**, choose the eligible treatment account marked **not enrolled**.
3. Prepare a review and approve its exact owner, contact, sequence and content.
4. Open the failure controls and arm a lost acknowledgement. Dispatch, then reconcile: one durable remote enrollment remains.
5. Record a positive reply, qualified meeting and accepted opportunity. Each feedback event crosses HTTP and is read back before admission.
6. Submit an inquiry in **Inbound routing**, or investigate blocked actions in **Execution & recovery**.

The operator clock starts January 21, after the scenario's previously recorded feedback. The mature comparison separately reports through February 2. Future source events are rejected at admission; reporting also checks outcome time and receipt/knowledge cutoffs. Both dates are synthetic scenario coordinates.

## One action, with evidence at every boundary

![Actual account research, exact review, independent receipt and downstream feedback](docs/images/account-workbench.png)

The first treatment account in the fixture receives a pricing inquiry. Its verified brand/account reference and synthetic contact resolve to the existing CRM owner. Separate fit and intent rules qualify it. The seller approves one finite discovery sequence. The destination commits enrollment, then deliberately closes its HTTP connection before acknowledging it. A fresh worker reads back the original content and receipt rather than sending again. Subsequent synthetic reply, meeting and accepted-opportunity events retain that action lineage.

Other accounts demonstrate owner changes, opt-out, rate limiting, a service inquiry, an unverified discovery and an ambiguous shared domain. Inspect the [executed action journal and routing records](docs/evidence/demo.json) or [failure contracts](docs/operations.md).

```mermaid
flowchart LR
  S[CRM, enrichment, web signals] --> I[Versioned admission and brand identity]
  I --> Q[Explainable fit and decayed intent]
  Q --> C[Frozen account cohort]
  Q --> R[Inbound owner or exception queue]
  C --> H[Human review and exact approval]
  R --> H
  A[Advisory research or optional LLM] -. no execution authority .-> H
  H --> W[Durable dispatch and current authorization]
  W --> D[Independent HTTP engagement destination]
  D --> V[Exact receipt read-back]
  D --> F[Reply, meeting and CRM opportunity feedback]
  F --> M[Account-level SQL measurement]
  C --> M
  V --> W
```

## Measure the denominator, not just the success stories

The executed fixture has **28 accounts**, including **24 assigned eligible accounts**, seven independently verified enrollments, two blocked actions and one treatment account left available for interactive review. Five qualified meetings and five accepted opportunities produce **CAD28,000 of synthetic qualified pipeline**. These values come from the [executed sources and receipts](docs/evidence/demo.json), not a frontend formula.

| Mature 30-day comparison | Treatment | Holdout |
|---|---:|---:|
| Assigned accounts | 10 | 14 |
| Enrolled accounts | 7 | 0 |
| Accounts with qualified meetings | 2 | 3 |
| Meeting rate | 20.0% | 21.4% |
| Accepted opportunities | 2 | 3 |
| Pipeline per assigned account | CAD1,000 | CAD1,285.71 |

The synthetic treatment does **not** outperform holdout on meeting rate. Outcomes are explicit fixture inputs; this is a demonstration of calculation and exclusion rules, not estimated commercial uplift. Assignment is deterministic; all assigned accounts stay in the denominator even if never enrolled or subsequently opted out. Shared domains across operating units receive the same arm without merging identities. Preexisting opportunity creation dates, late knowledge, outcome windows, immature cohorts and leakage have dedicated tests. [Definitions and limitations](docs/measurement.md) · [SQL implementation](src/gtm/pipeline.sql).

## Controls that change execution behavior

| Failure | Executed behavior |
|---|---|
| Distinct CRM records share a domain | Retain separate records; ambiguous inbound and eligibility require review |
| Enrichment disagrees with CRM | Preserve CRM fields and append conflict evidence |
| Repeated or stale intent | One contribution per signal type, with explicit decay and expiry |
| Owner or consent changes after review | Block new enrollment; retain the approved payload and reason |
| Receiver commits but response disappears | Reconcile full content and receipt before considering another POST |
| Worker dies after remote commit | Durable attempt survives; a restarted worker finds the existing effect |
| Receiver rate limits | Persist exponential backoff and a three-attempt write budget |
| Remote effect survives loss of local intent | Independent reconciliation returns `remote_ahead_missing_intent`, `safe_to_resume=false` |

![Actual recovery console and durable action journal](docs/images/execution-recovery.png)

These controls assume a trusted local operator, received CRM authority and the receiver's idempotent-content contract. They do not guarantee global exactly-once delivery or discover source-system changes that have not arrived. [Architecture and trust boundaries](docs/architecture.md).

## Verification and integration status

```text
python -m playwright install chromium
python scripts/verify.py --output work/review-evidence
python scripts/capture.py --workspace work/browser-review --output work/review-images
python scripts/check_evidence.py
python scripts/publication.py --package
```

Use a fresh workspace for each browser reproduction. Verification runs regression tests and two independent end-to-end HTTP demos, compares the complete output, checks source hashes, audits public content and checks local Markdown targets. The package is reopened and each file hash verified. [Recorded verification](docs/evidence/verification.json) · [JUnit results](docs/evidence/tests.xml) · [Hosted CI](https://github.com/rlbsem/gtm-pipeline-orchestration/actions).

| Boundary | Status |
|---|---|
| Browser, API, local orchestration and independent HTTP effects | Executed with synthetic data |
| Process-death recovery, permissions, duplicates, backoff and experiment exclusions | Local regression tests |
| Optional authenticated local LLM | Implemented and software-contract-tested; fresh inference unexecuted |
| Salesforce Task mapping | Scoped mapper tests only; no native requests or metadata deployment |
| Clay / sales-engagement vendors | Source/adapter interfaces only; no native integration claimed |
| Cloud infrastructure / public application deployment | Not executed |

[Scope alongside the existing portfolio](docs/scope.md) · [Local operator and integration procedure](docs/operations.md). A non-root container definition and loopback-published Compose configuration are included; the CI container job builds it and runs the same synthetic workflow. Neither container configuration is a public hosting authorization.
