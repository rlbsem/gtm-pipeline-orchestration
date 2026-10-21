# Native synthetic Account, Contact and SDR Task acceptance

This lane exercises the Salesforce REST API in an explicitly approved, pinned Developer Edition or sandbox. It is separate from the local engagement destination, the earlier custom-object review, recorded Qwen inference and synthetic enterprise pipeline arithmetic. A Task is an internal seller handoff, not an email, meeting, enrollment or opportunity outcome.

## Why standard-object describe returned 404

The same administrator could describe Account, Contact, Lead, Opportunity and Task in API v65.0 and v68.0. The integration identity used the **Salesforce Integration** license and **Minimum Access - API Only Integrations** profile. It had neither standard-object grants nor an assigned **Salesforce API Integration** permission-set license. The reviewer had a full Salesforce license but a minimum-access profile without Account, Contact or Opportunity grants. Its Task describe was readable, with creation denied.

The hidden objects returned HTTP 404, `NOT_FOUND`, “The requested resource does not exist”. This was an effective-access result, not evidence that Salesforce lacked the objects. After the integration entitlement and read grants, Account, Contact and Opportunity became visible; Task also required the separate **Access Activities** system permission. No Lead access is added: this workflow resolves existing Accounts and Contacts.

New custom fields and the Contact opt-out field also required explicit field visibility for the setup administrator. A temporary setup permission set provides only those fields. The original profiles, custom-review permission sets, users and organization-wide sharing defaults are preserved.

Salesforce documents the [integration license and entitlement](https://help.salesforce.com/s/articleView?id=sf.integration_user.htm&language=en_US&type=5), [REST-compatible editions](https://developer.salesforce.com/docs/platform/api-rest/guide/intro-rest-compatible-editions.html), and [unique external-ID behavior](https://help.salesforce.com/s/articleView?id=000385174&language=en_US&type=1). An external ID alone does not establish uniqueness.

## Execution and recovery boundary

The runner resolves Account and Contact through unique, run-scoped external keys, verifies exact manifest IDs, account association, owner, synthetic domain, explicit test activation and opt-out state, and checks for an existing open opportunity. The native Contact has a deterministic per-run fictional email alias; the journal explicitly binds it to the approved local `review@account-04.example` fixture contact through the destination scope. Email alone is never an identity key.

`TaskDispatcher` binds the local approved action, destination pin and finite internal Task envelope in a separate durable `crm_tasks` journal. The Task envelope contains no model-generated prose. A committed attempt reservation precedes the external write. Three attempts and exponential backoff bound retries. A restarted dispatcher reads the independent receipt **before** considering current authorization for a new action. Missing access is not treated as proof of no effect; a previously verified receipt disappearing blocks replacement.

The deployed Apex guard rechecks the marked Account, Contact, owner, consent, envelope and open-opportunity conditions on Task insertion. It locks the parent Account and Contact rows and creates a unique `GTM_Task_Receipt__c` in the **same Salesforce transaction**. A duplicate receipt raises an unhandled DML error and rolls back the additional Task. Activity custom fields are not assumed to support a unique external ID. Both identities have API read-only access to receipt content; the integration identity cannot forge receipts directly.

Protected Task content and receipt content are immutable through the guard. The writer cannot update or delete Tasks despite the broader Edit Tasks system permission required for native creation. The administrator can complete the retained Task without rewriting its identity, association, owner, subject or envelope.

The independent reviewer owns the synthetic Account, Contact and Task, so readback does not rely on administrator privileges. Existing Account/Contact/Opportunity sharing defaults in this test org are broad. These permission sets do **not** claim server-side read isolation to only the test rows. The runner reads exact marked records; the Task guard restricts writes to synthetic scope. It grants no View All Data or Modify All Data.

Parent locks serialize participating guarded actions, not every possible writer in Salesforce. A separate application could create an Opportunity after the last check without following this protocol. This is an isolated acceptance control, not a cross-system transaction or general exactly-once guarantee. Administrator metadata control remains trusted.

## Reproduce only in an approved isolated org

The ordinary core and CI need no Salesforce credentials. Native execution requires an approved organization pin and three already authenticated CLI identities: setup administrator, restricted integration writer and independent reviewer. Never place tokens, CLI authentication exports or raw responses in the repository.

1. Verify the organization ID and environment type using the administrator; reject ordinary production organizations. Confirm the spare API Integration entitlement and the existing identities' licenses. Review the metadata before deployment.
2. From `salesforce/`, validate the bundle with `sf project deploy start --dry-run --source-dir force-app --target-org APPROVED_ADMIN --test-level RunSpecifiedTests --tests GTMTaskGateTest --json`. Deploy the same bundle only with isolated setup authorization. Preserve the private deployment result.
3. Prepare a private configuration containing `instance_url`, `approval` (`org_id`, `environment`, `organization_type`, `approved`), `integration_user_id` and `reviewer_user_id`. For Developer Edition, use `environment: developer_edition`, `organization_type: Developer Edition`, `approved: true`. A sandbox must match its verified type and `IsSandbox=true`.
4. From the repository root run the command below, using a fresh namespace and private workspace. The explicit flag authorizes the bounded setup, synthetic writes, denial probes and cleanup; it is not general production authorization.

```text
python scripts/native_standard.py --config PRIVATE_CONFIG --workspace .local/native-standard-01 --run-id gtm-standard-isolated-demo01 --cli SF_CLI_PATH --admin APPROVED_ADMIN --writer APPROVED_WRITER --reader APPROVED_READER --approved-isolated-writes
```

5. Inspect the private verification report, native response journal and cleanup readbacks. Publish only reviewed sanitized evidence. The lost-acknowledgement fault deliberately discards an actual successful native response; it does not claim a naturally occurring network outage.

The runner uses temporary dedicated assignments and records their IDs before proceeding. It retains the newly created synthetic audit records, completes the Task, opts out the Contact, disables the Account, closes the blocker Opportunity as lost, removes its temporary assignments and restores the original entitlement/permission-set assignments. It does not delete prior acceptance records or change duplicate rules. Unassigned metadata remains for reproduction. Investigate any failed cleanup before another run; never discard the private journal.

No approved Outreach or Salesloft test tenant is configured. Neither native engagement integration nor outbound delivery is claimed.
