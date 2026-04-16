# expenses_automation

Small automation that scans Gmail for billing emails and appends detected amounts into a Google Sheet.

- Config is in `expenses_automation/main.py`:
  - `TARGET_SENDER` — email address to process (default: `noreply@billing.coned.com`).
  - `LABEL_NAME` — Gmail label added to messages after they are processed to avoid re-processing.

The script now only processes messages from `TARGET_SENDER` and labels processed messages with `LABEL_NAME`.
