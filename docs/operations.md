# Local operation and recovery

## Reproduce

Follow the [README setup](../README.md). Workspaces contain synthetic databases and runtime output and are excluded from Git. Keep the source folder intact; the supported install is editable from this repository. Native/vendor credentials are not needed.

```text
gtm demo --workspace .local/review-01
gtm serve --workspace .local/review-01
```

The initial scenario has one unactivated treatment account for browser review. Select it before testing a new enrollment. Receipt-backed accounts reconcile existing effects instead; approval alone never dispatches. The UI can advance its persisted scenario clock by five seconds to reach a retry deadline. A new workspace reproduces the original experiment without deleting or resetting an existing one.

## Failure investigation

| State | Operator action | Guardrail |
|---|---|---|
| `uncertain` | Read fresh independent receipt; use Dispatch / reconcile | No assumption that a missing acknowledgement means no effect |
| `waiting` | Inspect `next_attempt`, advance scenario clock and retry | Three persisted attempts, exponential delay |
| `blocked` | Inspect owner/permission/context, original approval and audit | No terminal-state reset endpoint; current approval cannot be silently rewritten |
| `exhausted` | Inspect all attempts and receiver requests | A new worker does not restore the write budget |
| Ambiguous inbound | Inspect separate source records and canonical references | No automatic fuzzy merge or wrong-brand reassignment |
| `remote_ahead_missing_intent` | Preserve both stores, investigate restore/source loss | All new dispatch remains blocked; do not clear the receiver to make comparison pass |

For a new campaign after a material change, an operator must deliberately version the experiment/policy and obtain fresh eligible review. This demonstration does not expose an HTTP override or automate terminal exception resolution. Historical receipt reconciliation remains permitted.

The tests execute an actual subprocess death after remote commit and a local SQLite restoration mismatch. These are local recovery proofs; they are not AWS/RDS PITR or native CRM recovery evidence.

## Optional model execution

An already running, explicitly approved authenticated loopback model can be used without changing the default demo:

```text
gtm infer --workspace .local/review-01 --account CANONICAL_ACCOUNT_ID --model-origin http://127.0.0.1:8093 --model MODEL_NAME --model-key-file PRIVATE_LOCAL_KEY_FILE
```

The result stays in the ignored workspace with actual raw text, request/context hashes, model response identity and usage. Failed calls do not become success records. Inspect the provider's model/weights/runtime provenance separately before publishing any such result; this CLI alone cannot attest the actual weights behind an endpoint. The original evidence did not invoke a model. The separate [native/model upgrade](native-ai.md) records fresh local inference without changing the default demo. The model interface tests use explicitly identified software responders. Exact quote checks do not establish complete semantic support.

## Vendor boundary

`EngagementAdapter` defines receipt listing, key lookup and enrollment. The implemented `EngagementClient` is intentionally loopback-only. Feedback crosses its HTTP service and is independently read back before ingestion.

The [Salesforce Task mapper](../src/gtm/adapters.py) requires explicit brand/account and brand/owner mappings and uses `WhatId` for account linkage. Its two proposed custom fields require a separately reviewed metadata deployment. It is not a native sender, permission validator or deployed integration. [Official Task field reference](https://developer.salesforce.com/docs/platform/field-reference/references/field-reference/salesforce-field-reference-task.html).

Native Salesforce, Clay and sales-engagement acceptance requires separately authorized isolated environments, pinned identities, restricted credentials and vendor-effective permissions/read-back. The original core evidence used no vendor environment. The separate native upgrade used an approved existing Salesforce test org for an internal-review acceptance; no Snowflake execution occurred here. A JSON source marked `crm` in the local demo is an operator-supplied synthetic record, not a vendor attestation.

## Container

```text
docker compose up --build
```

Compose publishes only on host loopback and persists both synthetic stores in a named local volume. Stop with `docker compose down`; omit `--volumes` to preserve state. The image is non-root with dropped capabilities. Local Docker execution depends on an available Docker daemon; independent CI builds and runs the container. Check actual workflow results before citing container acceptance. No cloud deployment is configured.
