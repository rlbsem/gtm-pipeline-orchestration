# Historical evidence archive

The featured enterprise demonstration is [USD v2](enterprise-usd/README.md). Earlier CAD artifacts remain byte-preserved as historical execution records, not current USD evidence. No exchange rate or retrospective conversion is applied.

| Historical boundary | Preserved artifact | Executed source |
|---|---|---|
| Original 28-account CAD28,000 fixture | [73-test report](verification.json), [complete replay](demo.json) | `601d3865e40c4e62836adafa01e377a1579468ec` |
| Qwen and custom Salesforce review | [16 responses](native-ai/ai-evaluation.json), [29 requests](native-ai/salesforce-acceptance.json) | `4b06935b23edee3045a58553ec9fcdf2fa056084` |
| Earlier local/model UI | [117-test report](native-ai/local/verification.json) | `644065dd561019b351ca7330d2146fd4c10e1d66` |
| Enterprise CAD3.46M v1 | [127-test report](enterprise/verification.json), [replay](enterprise/demo.json), [screenshots](../images/enterprise/provenance.json) | `9f13ea79977dda1b56f25df5ca5c4060ffaf345f` |
| Native standard Salesforce Account/Contact/Task | [140-request acceptance](salesforce-standard/acceptance.json) | `c54503f00e65ad4195a74c0bacf2ce003add091c` |
| Independent Salesforce post-cleanup check | [20 read-only requests](salesforce-standard/post-cleanup.json) | `36fd314015812f2114d5e96a0cbbaee24b17b2e4` |
| Final CAD enterprise UI/native upgrade | [154-test report](salesforce-standard/local/verification.json), [screenshots](../images/salesforce-standard/provenance.json) | `62e48215a3609ba136f4ce581f98cc893e2378d9` |

Older README files and relative source links describe their recorded revision. Consult the named Git revision for its implementation; current source and scenario metadata describe USD v2. The evidence checker verifies historical bytes and source bindings separately from current regression and browser execution. No additional native vendor or model execution is claimed.
