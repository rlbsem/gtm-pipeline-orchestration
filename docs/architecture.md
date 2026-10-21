# Architecture and trust boundaries

## Small deployment, distinct responsibilities

FastAPI serves a local operator UI. Python applies source contracts, identity, scoring, allocation and review policy. SQLite WAL stores durable control state. A separate authenticated HTTP destination owns a different SQLite file containing immutable-key enrollments, exact-content receipts, feedback and a request journal. The default launcher runs that server in a separate thread; it is a separate data/HTTP boundary, **not a separate host, process or security principal**. Process-death tests kill only a dispatch subprocess while the receiver remains alive.

The deployment is intentionally single-host and synthetic-only. `BEGIN IMMEDIATE` serializes admission and holds the local authority lock across a bounded network request. This trades throughput for an understandable consent/ownership boundary. It is not a distributed transaction with a live CRM. A production integration would need authenticated source identities, operational freshness SLAs, a scalable durable store and separately operated receiver infrastructure.

## Identity and source ownership

`source/v1` requires source, immutable event ID, brand, observed time, domain and a closed per-kind field vocabulary. The deduplication key is `(source, brand, source_id)`. Reusing a key with different content fails. Sources and their disposition are append-only.

Accounts are scoped to an operating unit. Discovery from enrichment remains unverified until CRM confirmation. Separate trusted CRM record IDs sharing a domain stay distinct. Without an explicit valid account reference, multiple domain matches quarantine an inbound request. Even explicit reference matching does not promote unresolved same-brand/domain duplicates into the experiment. Cross-brand references fail. Contacts must use the account's synthetic domain; changing the contact requires review.

CRM controls owner, lifecycle, contact and authoritative fit fields. Enrichment may populate missing fit attributes but cannot overwrite a CRM value or establish ownership/consent. A conflict is audited. Out-of-order owner updates cannot regress the current owner. Late opt-out suppresses; stale opt-in cannot restore permission. Source identities in this local demonstration are trusted operator inputs, **not authenticated vendor attestations**.

## Qualification and routing

[The pinned policy](../src/gtm/policy.json) separately scores employee fit, industry and territory, then decays intent over 30 days. Repeated records of the same signal type contribute only their strongest current value. CRM facts and ownership have a 365-day maximum age; enrichment facts expire after 30 days. Stale authoritative CRM fields do not silently fall back to a conflicting enrichment value.

Every qualification record retains the policy hash, contributing source keys, freshness verdicts and exclusion reasons. The cohort admission rechecks its decision under the mutation lock. Inbound requests preserve valid existing owners and route customers/support inquiries to service review. New-business inquiries create a durable seller-review route or named exception. These records are the local CRM review queue; external CRM Task creation is not implied.

## Advice, approval and dispatch

The default research view deterministically indexes actual account evidence. Optional local-model requests use a closed advisory JSON response with exact source quotation checks. No model method has dispatch, approval or downstream credentials. Quotes can be exact yet unsupported in context; no general semantic-grounding claim is made.

Executable `action/v1` content comes from a finite neutral sequence. A trusted local reviewer approves the exact account, brand, owner, contact, content hash, scoring context and experiment. SQL triggers prevent approved-content mutation. New dispatch rechecks current owner, contact permission, account eligibility, policy, selected evidence, experiment window and approval age. Arbitrary personalization remains advisory. The finite sequence is deliberately less expressive than free-form outbound copy.

A persisted attempt precedes the HTTP write. The worker reads all independent receipts and checks recovery consistency, then looks up the action receipt before deciding whether another POST is allowed. Receipt matching checks full payload, hash, action key, receipt identity and timestamp. A found effect can reconcile after opt-out or expiry without initiating a new action. Backoff and write budgets survive worker replacement. A receiver conflict or policy denial is retained as a terminal exception.

## Measurement and lineage

Feedback retains source key, account, action (when sequence-originated), business ID, parent transition, creation time, outcome time and received time. Sequence meetings require a prior positive reply; accepted sequence opportunities require the recorded qualified meeting. Organic holdout outcomes are admitted from synthetic CRM/engagement sources without inventing enrollment.

The account mart aggregates meeting and opportunity grains separately before joining cohorts, preventing a meeting/opportunity fanout. SQL outputs and a separate Python traversal are compared in regression tests. [Measurement contract](measurement.md).

## Security boundary

- Default services bind to loopback. The browser rejects unapproved Host and cross-origin mutations, requires an operator-intent header, applies a strict CSP and renders source text without HTML interpretation.
- Receiver tokens are randomly generated in memory. They do not enter the browser, evidence, package or repository. There are no CRM credentials in the core.
- Destinations and optional models are constrained to bare loopback HTTP origins; redirects are disabled. Only `.example`, `.test` and `.invalid` source domains enter the system.
- The UI's `demo-reviewer` is a **trusted local operator label**, not enterprise login or authorization. Do not expose the service publicly or load client data.
- Hashes and append-only triggers detect ordinary mutation and bind evidence; a host/database administrator is trusted. They are not a signature authority, WORM service or defense against that administrator.

The container permits a bind inside its network namespace only so Compose can publish **127.0.0.1:8560**. Changing this to public hosting requires a different authentication and deployment design.
