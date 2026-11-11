# Code structure

How the project is organised, what each file does, and which library or API
each part relies on. Read the [README](README.md) first for what the system
does and how to run it.

## The idea in one paragraph

The pipeline is a chain of small stages. Every stage reads creators from one
SQLite table, adds a few columns, and saves them back. Nothing is passed
between stages in memory, so any stage can be run on its own, re-run safely,
or continued after a quota error. The command line simply calls the stages in
order.

```
discover -> measure -> filter -> classify -> enrich -> messages -> export -> queue -> sync
 YouTube    YouTube    rules     Gemini      text,     Gemini      CSV       Sheet     Sheet
 search     videos                           website,                        (Zapier   (results
                                             Apify                           sends)    back)
```

| Assignment step | Stage(s) | File |
| --- | --- | --- |
| 1. Influencer discovery | `discover`, `measure` | `discovery.py`, `youtube.py`, `metrics.py` |
| 2. Filtering and classification | `filter`, `classify` | `filtering.py`, `classify.py` |
| 3. Profile enrichment | `enrich` | `enrichment.py` |
| 4. Message personalisation | `messages` | `messages.py`, `llm.py` |
| 5. Sending layer | `queue`, `sync` + the Zap | `sending.py`, `sheets.py`, `docs/zapier-setup.md` |
| 7. Outputs | `export` | `export.py` |

## Folder layout

```
influencer-discovery/
├── .env                    your API keys (git-ignored, never committed)
├── .env.example            the same file without secrets
├── requirements.txt        Python packages
├── README.md               what the system does, setup, results, limitations
├── CODE_STRUCTURE.md       this file
├── config/
│   ├── niche.yaml          the niche, search queries, filter thresholds
│   └── brand.yaml          the demo brand and its collaboration offers
├── credentials/            Google service-account key (git-ignored)
├── outreach/               the Python package (one file per job)
├── tests/                  unit tests for the logic
├── docs/
│   └── zapier-setup.md     how to build the Zap that sends the emails
└── data/
    ├── outreach.db         SQLite database (git-ignored, rebuilt by the pipeline)
    ├── influencers.csv     deliverable: the influencer dataset
    ├── messages.csv        deliverable: email pitch + Instagram DM per creator
    └── outreach_tracker.csv deliverable: the outreach log
```

## The `outreach` package, file by file

### `cli.py`: the command line
Parses `python -m outreach <command>` with `argparse`. `STAGES` maps each
command to its function, and `FULL_RUN` lists the order used by `run`.
`run_stage` wraps every stage so that a used-up YouTube or Gemini quota stops
that stage with a clear message instead of a crash. `show_status` prints how
many creators reached each stage.

### `config.py`: settings
`load_settings()` reads `.env` with `python-dotenv` and the two YAML files with
`PyYAML`, and returns one `Settings` object that every stage receives. It also
holds the two labels used for missing data, `NOT_FOUND` and `NOT_AVAILABLE`,
and it refuses to start with `SEND_MODE=live` while the brand is marked as a
demo.

### `db.py`: storage
One table, `creators`, with one row per YouTube channel. `COLUMNS` lists every
column grouped by the stage that fills it, which doubles as documentation of
the data model.

- `add_creator` inserts a new channel and ignores one that is already stored.
  This is the first duplicate guard.
- `save_creator` updates named columns. `get_creators` returns dictionaries.
- List values (recent videos, filter reasons, content themes) are stored as
  JSON text and converted automatically.
- A second small table, `searches`, remembers which search queries were already
  run, so a re-run does not spend search quota twice.
- A `NULL` always means "not collected". It is turned into `Not Found` or
  `Not Available` only when the outputs are written.

### `youtube.py`: YouTube Data API client
Plain `requests` calls to four endpoints of the official API:

| Function | Endpoint | Used for |
| --- | --- | --- |
| `search_videos` | `search.list` | recent videos matching a niche query |
| `get_channels` | `channels.list` | name, subscribers, description, country, topics (50 channels per call) |
| `get_recent_videos` | `playlistItems.list` + `videos.list` | the last 10 uploads with views, likes, comments |

`call_api` adds retries for temporary errors and raises `QuotaExceeded` when the
daily quota is used up. `parse_channel` and `parse_video` convert the raw JSON
into the stored fields. A hidden subscriber or like count is stored as `None`,
never as zero.

### `metrics.py`: engagement maths
- `video_engagement`: `(likes + comments) / views` for one video, as a percentage.
- `summarise`: the channel's engagement rate is the **median** of its last 10
  videos, so one unusual video cannot distort it. With fewer than three
  measurable videos the rate is `None` ("Not Available").
- `days_since`: days since the last upload, for the activity check.

### `discovery.py`: stages `discover` and `measure`
- `discover` runs each query from `niche.yaml`, stores the channel behind every
  video found, then fetches channel details in batches of 50.
- `measure` fetches recent videos only for channels inside the follower range.
  The others fail the filter anyway, and skipping them saves two API calls each.

### `filtering.py`: stage `filter`
Seven small check functions. Each returns `(passed, explanation)`, for example
`(False, "Engagement: 0.8% is below the 2.0% minimum")`.

| Check | Data it uses |
| --- | --- |
| `check_followers` | subscriber count vs. the 5,000-100,000 range |
| `check_activity` | date of the last upload, number of public videos |
| `check_engagement` | measured engagement rate vs. the minimum |
| `check_country` | channel country vs. an optional allow-list |
| `check_keywords` | niche keywords in the description, topics and video titles |
| `check_niche` | Gemini's niche classification and its confidence |
| `check_brand_fit` | Gemini's 0-10 brand-fit score |

`decide` runs the checks in order of cost and returns the status plus the list
of reasons: `PASS`, `FAIL`, or `PENDING` (still waiting for `measure` or
`classify`). The cheap checks come first, so a creator who fails one is never
sent to the AI model. `apply_filters` recalculates every creator, so changing a
threshold in `niche.yaml` and running `filter` again is all it takes.

### `llm.py`: Gemini wrapper
One class, `Gemini`, with one public method: `ask(prompt, schema, system)`.
It calls the Gemini Interactions API through the `google-genai` SDK, asks for
JSON that matches a Pydantic model, and returns the validated object.

- A minimum gap between calls keeps it under the free tier's per-minute limit.
- If a model answers "rate limited" (429) or "overloaded" (5xx), the call is
  retried after 20 and then 60 seconds. If it still fails, the next model in
  the list takes over.
- The free tier allows only about 20 requests per day for each model. When the
  API says the wait is hours long (`retry_after_seconds`), that model is
  dropped at once instead of being retried.
- When no model is left it raises `LLMQuotaExhausted`, the stage stops, and
  running it again later continues where it left off.

Because requests are so scarce, both AI stages send many creators in one
request and record which model answered (`classified_by`, `written_by`).

### `classify.py`: stage `classify`
Sends channels to Gemini twenty at a time. For each channel the prompt contains
only real data: name, subscribers, country, YouTube topic labels, description
and recent video titles. The answer per channel (the `Verdict` model) is: niche,
sub-niche, confidence, the evidence used, content themes, tone, brand-fit score
and its reason. The verdict is saved and `filtering.decide` turns it into the
final `PASS` or `FAIL`.

### `enrichment.py`: stage `enrich`
Runs for shortlisted (`PASS`) creators only.

- `find_emails`, `find_instagram`, `find_tiktok`, `find_website`: regular
  expressions over text the creator wrote. Emails are validated with
  `email-validator`; image names and platform addresses are discarded.
- `repeated_in_videos`: an email or handle found in video descriptions is used
  only if it appears in at least two videos. A one-off address is usually a
  sponsor's.
- `shared_letters` and `own_handle`: the ownership check. Video descriptions
  also credit musicians, shops and friends in every video, so a repeated handle
  is accepted only if it shares at least four letters in a row with the
  channel's name or YouTube handle, and the closest match wins. In the test run
  this rejected handles such as a credited musician and a beauty salon.
- `email_from_website`: if the channel description links to the creator's own
  site, that page and `/contact` are read with `requests` and `BeautifulSoup`.
  `fetch_page` checks `robots.txt` first. A link counts as the creator's site
  only if its address shares six letters in a row with the channel name, which
  keeps sponsor and affiliate links out.
- `fetch_instagram_profiles`: one Apify run (`apify/instagram-profile-scraper`)
  for all handles found, returning public follower counts and recent posts.
  `instagram_engagement` computes the Instagram engagement rate from them.

The email search order is: channel description, repeated video descriptions,
creator website, Instagram bio. The source is saved next to the email. If all
four are empty the email stays empty and is exported as `Not Found`.

### `messages.py`: stage `messages`
- `choose_angle` picks the collaboration (ambassador, sponsorship, barter,
  affiliate, paid placement or UGC) from the rules in `brand.yaml`.
- `build_prompt` gives Gemini the brand, the offer, and for each creator the
  niche, tone, themes and three most recent video titles. `OPENINGS` hands each
  creator a different way to start the email, so a batch does not read like one
  template.
- `find_problems` checks the result in code: email 60-90 words, DM 15-30 words,
  no leftover placeholders.
- `write_messages` works in rounds. Round 1 writes for everyone, ten creators
  per request. Rounds 2 and 3 redo only the rejected messages, telling the
  model what was wrong. A message that still fails is saved with the reason
  and is never queued for sending.

### `export.py`: stage `export`
Builds three tables from the database and writes them with the standard `csv`
module: the influencer dataset (all discovered channels, with status and
reasons), the messages, and the outreach tracker. `shown()` is the single place
where missing values become `Not Found` or `Not Available`.

### `sheets.py`: Google Sheets helpers
Four small functions on top of `gspread`: open the spreadsheet, read a tab,
append rows, replace a tab. Values are written as raw text so that scraped text
can never be interpreted as a spreadsheet formula.

### `sending.py`: stages `queue` and `sync`
- `queue` adds one row per creator to the `Email Queue` tab (and to `DM Queue`
  when an Instagram handle is known). It skips creators without an email,
  creators already queued, and repeated email addresses, and records why.
  In test mode the `send_to` column holds the demo inbox.
- The Zap (see `docs/zapier-setup.md`) sends approved rows and marks them.
- `sync` reads the sheet back, stores the send results, and refreshes the
  `Influencers` and `Outreach Tracker` tabs and the CSV files.

### `doctor.py`: credential check
`python -m outreach doctor` makes one small real call to YouTube, Gemini,
Google Sheets and Apify and prints `OK` or the reason for the failure. The
Gemini check only looks the models up, so it does not use up the daily request
quota. It never prints a key.

## How "no fake data" is enforced in the code

| Rule | Where |
| --- | --- |
| Every number comes from an API response | `youtube.py`, `enrichment.fetch_instagram_profiles` |
| Hidden or missing numbers are `None`, not zero | `youtube.parse_channel`, `youtube.parse_video` |
| Engagement needs at least 3 measurable videos | `metrics.summarise` |
| An email is only ever copied from published text, with its source | `enrichment.enrich_from_text` |
| A one-off email in a single video is not trusted | `enrichment.repeated_in_videos` |
| A handle or website must resemble the channel's own name | `enrichment.own_handle`, `enrichment.shared_letters` |
| Missing values are labelled, never filled in | `export.shown` |
| Audience age, gender and geography are always "Not Available" | `export.influencer_rows` |
| The AI model may only use the facts in the prompt | `SYSTEM` text in `classify.py` and `messages.py` |
| Word limits are verified in code, not assumed | `messages.find_problems` |
| No creator is emailed in the demo | `sending.queue` (`send_to`), `config.load_settings` (live-mode block) |

The only invented things in the repository are the demo brand in
`config/brand.yaml` (labelled as fictional) and the sample creators in
`tests/helpers.py` (used by pytest only; they never reach the database or the
outputs).

## Libraries used

| Library | Used for |
| --- | --- |
| `requests` | YouTube Data API calls, reading creator websites |
| `google-genai` | Gemini API (classification and message writing) |
| `pydantic` | the JSON shape Gemini must return, and validating it |
| `apify-client` | running the Instagram profile actor on Apify |
| `beautifulsoup4` | reading emails out of a creator's website |
| `email-validator` | rejecting strings that only look like an email |
| `gspread` + `google-auth` | reading and writing the Google Sheet |
| `python-dotenv`, `PyYAML` | configuration |
| `sqlite3`, `csv`, `argparse`, `re` (standard library) | storage, exports, command line, text matching |
| `pytest` | tests |

## Tests

`tests/` holds 38 unit tests for the logic that has to be exactly right:
engagement maths, every filter rule and its explanation, email and handle
extraction, the ownership check, word limits, angle selection, duplicate-free
storage, and the
sending layer (demo inbox as recipient, no duplicate queue rows, skipped
creators, tracker update). They use made-up creators from `tests/helpers.py`
and an in-memory stand-in for the Google Sheet, and make no network calls.

```
python -m pytest
```

## Changing things

| To do this | Change this |
| --- | --- |
| Target another niche | `config/niche.yaml`: name, definition, queries, keywords |
| Find more creators (50 to 500+) | add queries to `niche.yaml`, run `discover` again (finished queries are skipped) |
| Loosen or tighten a filter | `filters` in `niche.yaml`, then `python -m outreach filter` |
| Change the brand or its offers | `config/brand.yaml` |
| Use another Gemini model | `GEMINI_MODEL` / `GEMINI_FALLBACK_MODEL` in `.env` |
| Add a platform | a client like `youtube.py` that returns the same fields, called from `discovery.py` |
