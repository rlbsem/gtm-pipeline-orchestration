# Enterprise B2B commercial demonstration

This is a separate local synthetic profile. It preserves the original small deterministic fixture, its source events, CAD28,000 arithmetic and failure-recovery evidence. It does not change authority, approval, allocation, receipts, reconciliation or SQL financial definitions. No additional native vendor or model execution was performed for this commercial upgrade.

## Business assumptions

The [versioned scenario](../../../src/gtm/enterprise-scenario.json) specifies 120 accounts: 48 mid-market (240–950 employees), 48 enterprise (1,800–8,500) and 24 strategic (15,000–60,000), distributed across software, manufacturing and financial services, two fictional operating units and NA/EMEA territories. These are demonstration segments, not an assertion about any employer's segmentation or prices. Existing source authority and qualification policy remain unchanged.

Five pre-specified opportunity scopes generate illustrative 12-month ACV estimates:

| Synthetic scope | Sites | Annual value per site | CRM opportunity amount |
|---|---:|---:|---:|
| Regional multi-site pilot | 6 | CAD30,000 | CAD180,000 |
| Enterprise integration rollout | 10 | CAD45,000 | CAD450,000 |
| Strategic consolidation | 20 | CAD50,000 | CAD1,000,000 |
| Cross-region expansion | 14 | CAD45,000 | CAD630,000 |
| Global modernization | 24 | CAD50,000 | CAD1,200,000 |
| **Total** | | | **CAD3,460,000** |

These are fictional opportunity estimates, not vendor pricing, production revenue, signed bookings, ARR or actual customer results. The fixture does not scale a displayed metric or multiply the old report. It submits each amount inside an actual synthetic CRM `source/v1` outcome event. Those events cross the independent local HTTP feedback service, are read back and admitted, and are aggregated by the unchanged measurement engine.

## Executed proof

[Demo and independent financial audit](demo.json) records the source events, action lineage, business IDs, scope quotes, exact HTTP request journal and SQL results. `financial_audit` independently traverses source events in Python, applies cohort/time/knowledge cutoffs, deduplicates business outcomes, reads back the original CRM feedback over HTTP and compares count and integer-cent totals by arm. Tests separately assert the five literal values and their sum; negative tests reject a one-cent/count discrepancy and missing independent feedback.

The unchanged allocation yields 66 treatment and 54 holdout accounts. There are 63 independently verified enrollments, two blocked actions and one treatment account reserved for browser interaction. Twelve meetings and five opportunities produce CAD2.65M treatment pipeline and CAD810,000 holdout pipeline. Meeting rates are 7/66 and 5/54. Outcomes are pre-specified without reference to allocation; no positive result is targeted. The apparent differences are not causal evidence or model-attributed lift, and a few large deals dominate the values. The same intent-to-treat denominator and holdout safeguards remain in force.

[Verification](verification.json) executes the full suite and **four** independent HTTP workflows: two small and two enterprise. Each pair must match exactly. The small profile's complete exported JSON must also match [the original fixture](../demo.json), not merely produce the same total. [Current small replay](fixture-demo.json) · [JUnit](tests.xml).

## Browser evidence

[Screenshot provenance](../../images/enterprise/provenance.json) binds current code and seven genuine Chromium captures. The overview, commercial ledger, mobile commercial view, account workbench and recovery screen show the pristine CAD3.46M / five-opportunity replay. The later evidence and mobile workbench captures follow a real browser approval, client connection loss, receipt recovery, reply, meeting and additional synthetic CRM opportunity. Its segment-specific illustrative amount is a source event, and the browser runner independently asserts that measured pipeline increased by exactly that amount. The before/after amounts and image phases are recorded explicitly. No image was manually edited or generated.

The native Salesforce / Qwen pane displays the previously executed small-fixture acceptance as historical evidence; it does not imply a new enterprise native run. Existing native/model reports and prior screenshots remain byte-preserved and Git-bound. Current enterprise evidence binds the full current source tree. The diagram parser record is [here](diagrams.json).

## Reproduce

```text
gtm demo --profile enterprise --workspace .local/enterprise-UNIQUE
gtm serve --profile enterprise --workspace .local/enterprise-UNIQUE
python scripts/verify.py --output work/review-evidence
python scripts/capture.py --workspace work/browser-UNIQUE --output work/review-images
python scripts/check_evidence.py
python scripts/publication.py --package
```

Fresh workspaces default to enterprise. An existing workspace retains its original profile; an explicitly conflicting profile is rejected. The Compose deployment uses a new enterprise subdirectory without deleting the old volume contents. Neither profile requires credentials, native vendor access or model inference. Full-history Git source attestation additionally fetches the two pinned prior upgrade revisions in CI, so their records are never silently rebound to new code.
