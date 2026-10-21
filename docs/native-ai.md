# Native review and model execution

This document describes the preserved earlier custom-review/model execution. The subsequent [standard Account/Contact/Task acceptance](native-standard-crm.md) diagnoses its restricted identity's 404s and adds a separately authorized native lane. Statements below about unchanged permissions and unexecuted standard objects apply to the earlier run.

The core SDR workflow is unchanged: synthetic intelligence, deterministic scoring, owned inbound routing, exact local approval, independent HTTP engagement, feedback and assigned-account measurement. The new lanes add evidence at two boundaries; they do not relabel the whole loop as a live CRM integration.

## Salesforce boundary

`src/gtm/salesforce.py` requires an explicitly approved, pinned sandbox or Developer Edition. It independently verifies organization ID, edition and sandbox flag, distinct integration/reviewer identities, effective object/field permissions, unique external key, active synthetic registry and active approved owner. An ordinary production organization fails closed. The administrator client is read-only. HTTPS is restricted to a bare Salesforce organization origin; redirects, environment proxies and implicit retries are disabled.

The native acceptance used the existing deployed `Seller_Action__c` and `Synthetic_Account__c` metadata. No metadata, permission, user or OAuth changes were made. The writer can create/query reviews but cannot update/delete them. The independent reviewer cannot create/delete reviews, can update review status, and cannot change immutable content. [Existing metadata and scoped permission definitions](https://github.com/rlbsem/customer-signal-activation/tree/main/salesforce/force-app/main/default) are a deployment prerequisite, not a deployment performed by this repository.

The explicit synthetic alias mapping binds the local Atlas fixture account to the approved Cedar registry account and owner. These are isolated test-fixture aliases, not real company identity assertions or a cross-brand merge. The mapping, destination identities, action, advisory reference and context are hashed into a durable CRM-review envelope before POST. Salesforce writes use create-only POST rather than an upsert that could overwrite historical content. Recovery independently reads every immutable field before allowing another attempt. The unique external key bounds duplicate effects; a three-attempt durable budget and exponential backoff bound writes. Unknown outcomes remain uncertain; content mismatch blocks execution.

The native review journal is separate from local sequence receipts. A native internal review does not prove native enrollment, outreach, reply, meeting or opportunity creation. The exact-ID standard Account/Contact reader additionally checks owner, account-contact linkage, synthetic marker and synthetic domain; it is contract-tested only. Standard object describe requests returned 404 for the existing integration identity. No broader permissions or administrator writes were used to bypass that boundary.

### Reproduce in an approved isolated organization

Install the Salesforce CLI and authenticate three separate appropriate test identities yourself. Keep their tokens in the CLI's private credential store. Do not export them into evidence or Git. The existing metadata/roles and an active synthetic registry row are prerequisites. Supply a private JSON configuration with this shape (replace placeholders locally):

```json
{
  "instance_url": "https://YOUR-ORG.my.salesforce.com",
  "approval": {"org_id": "PINNED_18_CHAR_ORG_ID", "environment": "developer_edition", "organization_type": "Developer Edition", "approved": true},
  "integration_user_id": "PINNED_18_CHAR_USER_ID",
  "reviewer_user_id": "DIFFERENT_18_CHAR_USER_ID",
  "mappings": [{"brand": "cedar", "account": "account-0012", "owner": "cedar-east", "registry_id": "PINNED_18_CHAR_REGISTRY_ID", "user_id": "PINNED_APPROVED_OWNER_ID"}]
}
```

For sandbox, use `environment: sandbox` and the exact verified `OrganizationType`; `IsSandbox` must be true. Do not put the configuration inside public directories.

```text
python scripts/native_salesforce.py --config PRIVATE_CONFIG --workspace .local/native-01 --run-id gtm-native-UNIQUE-RUN --ai-evidence docs/evidence/native-ai/ai-evaluation.json --output .local/native-01/result.json --cli SF_CLI_EXECUTABLE --admin ADMIN_ALIAS --writer WRITER_ALIAS --reader REVIEWER_ALIAS
```

This is an explicit live-write operation, not a default verification step. Review authorization first. It creates one synthetic review, probes duplicate/restricted operations, verifies exact readback and marks the new record Rejected. It retains that audit record rather than deleting it. A client-side lost acknowledgement is injected only after a real POST 201. Private raw observations and record ID stay in the workspace; the sanitized report contains response-body digests, status/error codes and hashed identifiers. SHA-256 uses canonical JSON serialization, not a signature or independent vendor attestation.

An interrupted run must retain its workspace and run ID. Inspect its checkpoint, durable journal and private responses before continuation; never choose a fresh key to escape an uncertain outcome. The dispatcher itself reconciles by key before any new POST. The acceptance script is intentionally not an unattended cleanup service: if a later probe fails, its operator must independently read the run's exact key and, where permitted, mark only that run's newly created review Rejected. A completed workspace cannot be reused as a new test. No source account or preexisting review may be deleted or changed. Native source changes occurring after the last read remain a cross-system race limitation.

## Actual model lane

The recorded run used an existing authenticated Qwen3-14B Q4_K_M model, llama.cpp build 10809 (`5266f24da`), Vulkan, one slot and an 8192-token context. No model download or paid inference service was needed. [Official model distribution](https://huggingface.co/Qwen/Qwen3-14B-GGUF) · [llama.cpp server](https://github.com/ggml-org/llama.cpp/tree/master/tools/server).

```text
python scripts/evaluate_ai.py --workspace .local/evaluation-UNIQUE --output .local/evaluation-UNIQUE/result.json --origin http://127.0.0.1:8093 --token-file PRIVATE_KEY_FILE --runtime LLAMA_SERVER_EXECUTABLE --weights QWEN_GGUF_FILE
```

The endpoint must already be running and explicitly authorized. The runner records 16 actual responses without replacing invalid results. Each case uses a fresh database. The system treats source documents as untrusted, supplies current qualification and source context, validates a closed JSON schema and exact quotations, and retains raw model text on validation failure. The after-approval tests change owner/consent after inference; they test reauthorization, not the model's ability to predict a future change.

Exact quotes can coexist with unsupported prose. The test suite explicitly demonstrates that limitation. No semantic entailment, human usefulness, statistical reliability or general prompt-injection resistance score is claimed. The independent finite-message executor rejects arbitrary model text even if quotation validation passes. The native review's envelope references the real fresh-inbound request/context hashes, while its executable content remains the independently approved neutral action. `demo-reviewer` is a synthetic local operator label, not evidence of real seller approval.

## Inspect without credentials

Open **Native & AI evidence** in the running local application. Choose any of the 16 responses, including the rejected stale/consent cases. Read the actual text, context, citations, usage and independent policy result. This is a read-only view of committed artifacts: no Salesforce or model call occurs in the browser or CI. The regular local loop remains independently reproducible.

The intent-to-treat comparison keeps all assigned accounts in the denominator, including unactivated accounts and later opt-outs. Local reply/meeting/opportunity inputs are synthetic. The existing fixture's treatment does not outperform holdout; more activity is not presented as incremental pipeline or commercial success.

## Official API contracts

[Salesforce REST resources](https://developer.salesforce.com/docs/platform/api-rest/guide/resources-list.html) · [Read by external ID](https://developer.salesforce.com/docs/platform/api-rest/guide/using-resources-retrieve-with-externalid.html) · [Unique and external-ID attributes](https://help.salesforce.com/s/articleView?id=000385174&language=en_US&type=1). A trigger error name alone is not treated as effective permission evidence; describe results, rejected operations and independent readback/absence are evaluated together.
