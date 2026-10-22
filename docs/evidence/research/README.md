# Executed research evidence

- [Combined evaluation](evaluation.json): forty actual responses. Three prompt approaches; original failures retained.
- [Round 1](round1-evaluation.json) · [exact source snapshots](round1-sources.json): direct and skeptical prompts, original fixture.
- [Round 2](round2-evaluation.json) · [exact source snapshots](round2-sources.json): explicit evidence-first prompt, same original fixture.
- [Round 3](round3-evaluation.json) · [exact source snapshots](round3-sources.json): evidence-first prompt, corrected synthetic company names.
- [Reviewer assessment](reviewer-assessment.json): AI-authored qualitative factual-support and usefulness judgments, not a human SDR study.
- [Fresh operator proof](operator-proof.json): additional actual inference after new evidence, exact local review over HTTP, idempotency and unchanged primary pipeline.
- [Public API archive](public-jobs.json): one real unauthenticated GET, selected metadata only. Publication date unknown.

Local regression, browser review and package validation are separate from the above inference executions. No new Salesforce, Clay, Outreach, Salesloft or n8n execution is claimed. Prior native evidence remains byte-identical in [the connected archive](../connected/README.md).

See [architecture and limitations](../../account-intelligence.md) for interpretation, reproduction and authorization boundaries.

The account-intelligence screenshot precedes seller interaction; seller-research-review follows the exact edited approval, and mobile-intelligence follows approval and dismissal. Their counters represent different recorded workflow moments. [Browser provenance](../../images/research/provenance.json).
