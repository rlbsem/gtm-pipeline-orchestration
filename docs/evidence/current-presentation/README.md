# Current presentation verification

This record separates fresh software regression and real Chromium rendering from the unchanged historical Salesforce and model executions.

- [Software verification](local/verification.json) and [individual tests](local/tests.xml) execute the existing 237-test suite and four deterministic local workflow runs.
- [Application captures](../../images/current-presentation/provenance.json) exercise the synthetic enterprise application and its recovery interactions.
- [Research captures](../../images/current-research/provenance.json) verify five viewport widths, local seller review, accessibility and Mermaid parsing against recorded model responses.

The evidence checker retains the earlier research verification and captures at source revision `b4add9209283e55b095d50f1457ad48e9305b165`. It separately requires fresh regression and browser records to match current source hashes. CI supplies its own newly executed records through explicit arguments rather than treating archived captures as current.

These runs make no Salesforce requests, model calls or prospect communications. The USD $3.46M pipeline is the separate synthetic enterprise scenario, not a result of refreshing the interface.
