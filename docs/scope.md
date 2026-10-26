# Scope and inspected portfolio boundaries

The public default branches below were inspected before implementation. Existing repositories were not modified or imported wholesale. This repository owns the **SDR operating loop and account experiment**, with a compact local implementation of the controls needed to make that loop executable.

| Inspected source revision | Existing responsibility | Boundary here |
|---|---|---|
| [Customer Signal & Activation](https://github.com/rlbsem/customer-signal-activation/tree/b667239ac2acd9e661d67a3e90c01e70b4b61273) | Customer signals, reviewed activation, seller workflow, cash lineage and native Salesforce/Snowflake evidence | Account prospecting, sequence feedback and assigned-account pipeline measurement; no imported native claim |
| [Enterprise MarTech / AI Control Plane](https://github.com/rlbsem/enterprise-martech-ai-control-plane/tree/3b9d78457f0e414dd323ef1385f06825c6cca216) | Shared source authority, durable execution and recovery | A narrower single-operator SDR application; no production/cloud architecture replication |
| [Temporal Customer Audiences](https://github.com/rlbsem/temporal-customer-audiences/tree/108f17057ccba9e9ea04bfbe794481c7a8ce5056) | Business/knowledge time, retraction-aware audience membership and coverage | Frozen campaign allocation, outcome windows and late first observations; no general bitemporal audience engine |
| [Revenue Metrics Platform](https://github.com/rlbsem/revenue-metrics-platform/tree/a59ff4eb19ac033e54e66e38009229ba0cef4060) | Dimensional financial metrics, dbt, installed ARR and native warehouse fixture | Accepted pipeline per eligible account; no invoice/cash/ARR modeling or warehouse claim |
| [Prospecting CRM](https://github.com/rlbsem/prospecting-crm/tree/8fc83ac7710a01a0c37790ddfe9a5cee2971d0cf) | README-only at inspection | An executable prospect-to-opportunity workflow |
| [Outreach Tools](https://github.com/rlbsem/outreach-tools/tree/062fb2417d382b0077c7dd717ea0830232b87b52) | README-only outreach-tool description at inspection | Integrated routing, approved engagement, feedback and experiment rather than disconnected utilities |

SQLite and direct SQL keep this bounded operating system executable without a warehouse or new credentials. dbt would add deployment/dependency weight to a single account mart; the existing financial platform already demonstrates that stack. SQL grain tests and an independent Python oracle provide the measurement proof here.
