# Sample documents (for trying the dashboard flow)

Drag these into the dashboard's **Upload Documents** page to see the full flow
and every outcome. They exercise the real pipeline — nothing is mocked.

| File | Plane | Expected outcome |
|---|---|---|
| `data_governance_policy.txt` | content | **allow** — policy document, no violation |
| `pii_employee_record.txt` | content | **flag** — PII detected (review) |
| `access_events.jsonl` | access | a normal read (**allow**), a bulk-download of PII (**block**), and a privilege change (**alert**) |

After uploading, you're taken to **Analysis Results**; the **Alerts** page then
shows the block/alert items in red. (Add a `.pdf` of your own to try PDF text
extraction — text-based PDFs only; scanned/image PDFs report "no extractable
text".)
