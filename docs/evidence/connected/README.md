# Connected signal-to-SDR evidence

- [Preview](preview.json): six real read-only Salesforce requests, one fresh Qwen3 response, synthetic job source and exact review digest. Frozen before live-write approval.
- [Acceptance](acceptance.json): 128 native REST requests, one internal Task, exact independent readback, lost-ack recovery, duplicate/rejection tests and cleanup.
- [Apex](apex.json): actual deployment and five successful native tests.
- [Deployment provenance](apex-deployment-provenance.json): actual start/completion timestamps and private-response fingerprints for both deployments.
- [Contact-owner hardening](apex-owner-hardening.json): five successful native Apex tests after tightening the locked Contact-owner check; [the original continuation revision remains pinned](execution-source.json).
- [Fresh post-cleanup check](post-cleanup.json): 15 authenticated GETs verify exact restored grants, old/new Task content and the unchanged closed-lost opportunity.
- [Current local verification](local/verification.json): full regression suite and four independent local HTTP demos; no new native or model execution occurs in that verifier.
- [Screenshots](../../images/connected/provenance.json): genuine browser capture from the local application displaying recorded evidence.

The `retained_new_synthetic_records` cleanup key is inherited from the original runner. In **this run**, Account/Contact and the association-control Account were retained existing records; only the connected Task was new. The association-control Account was not mutated. The original Task/opportunity were excluded from the writable manifest. Actual flags were read back before grant retirement; permission sets returned to their original baseline.

Raw access tokens, native IDs, organization details, CLI responses, private scopes and databases remain excluded. Published record identities are hashed. Request response hashes support correlation with the private journal; they are not substitutes for public raw credentials or an independent third-party attestation.

See the [execution and failure boundaries](../../connected-sdr.md). The enterprise pipeline figures remain a separate synthetic local measurement scenario.
