# Zapier setup: the sending workflow

Zapier is the part of the system that actually sends the emails. Python fills a
Google Sheet; the Zap watches the sheet, sends each approved row through Gmail
and writes the result back. Zaps cannot be created by code, so this one is
built by hand once (about 10 minutes). Field labels in Zapier may differ
slightly from the ones below.

```
Python (queue)  ->  Google Sheet "Email Queue"  ->  you set review_status = Approved
                                                         |
                    Zapier: trigger -> filter -> Gmail send -> update row (sent = Yes)
                                                         |
Python (sync)   <-  Google Sheet "Email Queue"  <--------+
```

## Before you start

1. **Share the Google Sheet with the service account.** Open the sheet, click
   **Share**, add the service-account address as **Editor**. Run
   `python -m outreach doctor`: the Google Sheets line prints the exact address
   to share with, and shows `OK` once access works.
2. **Fill the queue** so Zapier has a sample row to read:
   ```
   python -m outreach queue
   ```
   This creates the tabs `Email Queue` and `DM Queue` and adds one row per
   shortlisted creator who has a contact email.
3. Check the `send_to` column of `Email Queue`. In test mode every row holds the
   demo inbox from `TEST_INBOX`, never the creator's address. The creator's real
   address is kept in `creator_email` for the record only.

## Build the Zap

Create a new Zap named **Influencer outreach: send approved emails**.

### Step 1. Trigger: Google Sheets, "New or Updated Spreadsheet Row"

| Field | Value |
| --- | --- |
| Account | The Google account that owns the sheet |
| Spreadsheet | Your outreach sheet |
| Worksheet | `Email Queue` |
| Trigger Column | `review_status` |

Test the trigger. Zapier should load one of the queued rows.

### Step 2. Filter by Zapier: "Only continue if..."

All three conditions must hold (join them with **And**):

| Field | Condition | Value |
| --- | --- | --- |
| `review_status` | (Text) Exactly matches | `Approved` |
| `send_to` | (Text) Contains | `@` |
| `sent` | (Text) Does not exist | |

This is the review gate and the duplicate guard: a row is sent only after a
person approved it, and never after it has been marked as sent.

### Step 3. Gmail, "Send Email"

| Field | Value |
| --- | --- |
| To | `send_to` from step 1 |
| From | Your Gmail address |
| From Name | `Demo Brand Partnerships Team` |
| Subject | `email_subject` from step 1 |
| Body Type | Plain |
| Body | `email_body` from step 1 |

Map **To** to the `send_to` column, not to `creator_email`. That one choice is
what keeps real creators from being emailed during the demo.

### Step 4. Google Sheets, "Update Spreadsheet Row"

| Field | Value |
| --- | --- |
| Spreadsheet | Your outreach sheet |
| Worksheet | `Email Queue` |
| Row | Custom value: the **Row ID** from step 1 |
| `sent` | `Yes` |
| `sent_at` | `{{zap_meta_human_now}}` |
| `status` | `Sent` |

Leave every other column empty so Zapier keeps its current value.

### Step 5. Test and publish

Test each step, then publish the Zap.

## Run the demo

1. In `Email Queue`, change `review_status` of one row from `Pending review` to
   `Approved` (type it exactly like that).
2. Wait for Zapier to poll the sheet (about two minutes on the trial plan). The
   email arrives in the demo inbox with a subject that starts with
   `[DEMO for <channel name>]`, and the row now shows `sent = Yes`.
3. Pull the result back into the project:
   ```
   python -m outreach sync
   ```
   This updates the `Outreach Tracker` tab and `data/outreach_tracker.csv`.
4. Approve more rows whenever you like. Set a row to `Rejected` to skip it.

To send without the manual review, set `AUTO_APPROVE=true` in `.env` before
running `queue`. New rows are then written as `Approved` and the Zap sends them
on its next poll.

## How duplicates are prevented

- Python adds a creator to the queue once. The `queue_id` column is the
  creator's YouTube channel ID, and `queue` skips IDs that are already there.
- Two channels that share one contact address produce one row; the second is
  logged as skipped.
- The Zap's filter refuses rows where `sent` is already filled.
- Zapier itself fires only once per row for each new value of the trigger column.

## Tips

- Keep the header row of `Email Queue` unchanged, and do not sort or delete rows
  while the Zap is on. Zapier tracks rows by position.
- The trial is needed for this Zap because it has more than two steps and uses a
  filter. Record the demo video or screenshots before the trial ends.
- Instagram DMs are not part of the Zap. See the "Instagram DMs" section of the
  README for the manual workflow in the `DM Queue` tab.
