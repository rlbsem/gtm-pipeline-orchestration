# Enterprise USD v2 demonstration

The current scenario has 120 synthetic accounts and five accepted-opportunity events totaling **USD $3,460,000**. These are new fictional USD scope estimates, not converted CAD or real-world revenue. Segmentation, outcome account selection, account allocation and authority controls are preserved.

| Illustrative 12-month scope | Sites | Synthetic USD per site | Synthetic USD opportunity |
|---|---:|---:|---:|
| Regional pilot | 6 | $30,000 | $180,000 |
| Enterprise integration | 10 | $45,000 | $450,000 |
| Strategic consolidation | 20 | $50,000 | $1,000,000 |
| Cross-region expansion | 14 | $45,000 | $630,000 |
| Global modernization | 24 | $50,000 | $1,200,000 |
| **Total** | | | **$3,460,000** |

The [versioned specification](../../../src/gtm/enterprise-scenario.json) defines currency, locale, population and economics. Each fresh workspace pins the full specification before event generation. Existing unpinned CAD enterprise workspaces are rejected, and changed specifications require a fresh workspace. No database or historical artifact is relabeled. The original small fixture remains implicit CAD and retains its exact complete export.

Enterprise outcomes explicitly carry `data.currency`. Admission rejects missing or mismatched currency. SQL selects the same currency and fails closed on mixed/missing source denomination. The [independent financial audit](demo.json) traverses admitted source records, rereads feedback over HTTP and compares counts and integer-cent totals by arm with SQL. Currency is carried into API results and ledger rows. Browser formatting and labels use pinned metadata (`USD`, `en-US`); no frontend total or foreign-exchange calculation exists.

[Verification](verification.json) runs the full suite and four independent HTTP demos: two enterprise USD and two original CAD fixtures. Each pair matches exactly; the small replay also equals its historical oracle. [JUnit](tests.xml) · [Fixture replay](fixture-demo.json) · [Diagrams](diagrams.json) · [Actual Chromium captures and provenance](../../images/enterprise-usd/provenance.json).

Baseline screenshots show five opportunities and USD $3.46M. The browser walkthrough then creates one additional synthetic opportunity through local HTTP feedback; its segment-based USD value and post-interaction total are recorded separately in provenance. Native Salesforce and Qwen panes display existing evidence only. No new vendor, model or cloud execution occurred for this correction.

Treatment retains 66 accounts, three opportunities and USD $2.65M; holdout retains 54 accounts, two opportunities and USD $810,000. Outcomes remain independent of allocation. These are synthetic arithmetic observations, not causal lift, customer results, revenue, bookings or ARR. [Historical CAD and native evidence](../archive.md).
