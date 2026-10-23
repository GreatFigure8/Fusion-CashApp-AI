# BI Publisher catalog exports

Catalog exports can only be produced from a pod, so until someone exports them this folder holds
only this register. Export from the dev pod catalog ("More, Export") after deploying the data
models and reports as described in `../README.md`, and commit the files here.

| File | Contents | Status |
|---|---|---|
| `CashAppRelationships.xdmz` | relationships data model | not yet exported |
| `CashAppRelationships.xdoz` | relationships report | not yet exported |
| `CashAppReceiptSignals.xdmz` | receipt-signals data model (optional) | not yet exported |
| `CashAppReceiptSignals.xdoz` | receipt-signals report (optional) | not yet exported |

When a file is committed, change its status to `exported <date> <pod>`. A catalog export of a
pod must not carry customer data: export the definitions only, never a report output.
