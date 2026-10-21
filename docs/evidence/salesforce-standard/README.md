# Native standard-object Salesforce acceptance

Executed October 21, 2026, in the existing approved, pinned Developer Edition. No customer data, prospect communications, paid resources or OAuth changes were used.

| Evidence boundary | Actual result |
|---|---|
| [Initial identity/license/object diagnosis](diagnosis.json) | Administrator saw all five standard objects in v65.0 and v68.0; restricted identities lacked effective access |
| [Native REST acceptance](acceptance.json) | 140 authenticated requests; all 21 checks passed; one Task and its atomic unique receipt |
| [Native deployment tests and response details](native-details.json) | Three Apex tests passed; exact sanitized errors, effective field grants and hashed record relationships |
| [Independent post-cleanup run](post-cleanup.json) | 20 fresh read-only requests; original grants restored, completed Task unchanged, blocker Opportunity closed lost |
| [Current local regression](local/verification.json) | Software tests and four independent local HTTP workflows; no vendor or model calls |
| [Current browser captures](../../images/salesforce-standard/provenance.json) | Actual Chromium execution; recorded native evidence displayed read-only |

The successful native run resolved the marked Account and Contact through unique external keys, checked association, owner, active scope, consent and no open opportunity, and created an internal SDR Task. Its successful acknowledgement was deliberately discarded on the client. A fresh dispatcher independently recovered the committed Task and exact receipt without another POST. An explicit duplicate POST failed in the native receipt trigger with nested `DUPLICATE_VALUE`; the additional Task rolled back. The independent Task inventory remained one.

Changed owner, revoked consent, wrong Contact association, disabled synthetic scope and a newly created open Opportunity blocked new Tasks in both the client and native guard. Account/Contact updates, Task mutation, reviewer creation and direct receipt creation were rejected. A generic `CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY` is not classified as permission evidence by itself: effective describes, exact rejected messages and independently verified state are retained together. Historical receipt reconciliation still succeeded after new-action consent was revoked.

Cleanup retained only newly created synthetic audit records. The Task was completed, Contact opted out, Account disabled and blocker Opportunity closed lost. Three temporary permission-set assignments and one entitlement assignment were removed. The separate read-only run confirmed the original assignment inventories and custom-review permission boundary were restored. Unassigned metadata remains for reproduction. Earlier failed attempts are recorded in the diagnosis; their private journals remain private, their temporary assignments were removed, and no Task was created in those attempts.

## Provenance

The native REST report is byte-preserved at executed checkpoint `c54503f00e65ad4195a74c0bacf2ce003add091c`; the independent post-cleanup report is bound to `36fd314015812f2114d5e96a0cbbaee24b17b2e4`. `scripts/check_evidence.py` verifies their executed source against those Git objects. The supplemental detail is derived from response digests in the native report; hashed IDs demonstrate equality and separation without exposing raw organization/user/record identifiers. These hashes are maintainer evidence, not vendor signatures.

Subsequent current-source changes make required-field failures explicit, prevent adoption of unjournaled existing records, and ensure a failed lifecycle cleanup cannot skip attempts to retire temporary grants. Those additions are locally regression-tested against the recorded native field contract; they are not described as another live Salesforce run. Current regression and screenshot provenance bind the final source separately. Original 73-test, custom-review/Qwen, 117-test and 127-test enterprise artifacts remain unchanged.

The CAD3.46M enterprise pipeline is still generated from local synthetic CRM outcome events. The native Task and blocker Opportunity are not counted as commercial pipeline, native engagement or new inference. No authorized Outreach/Salesloft test environment exists. [Operator procedure and limitations](../../native-standard-crm.md).
