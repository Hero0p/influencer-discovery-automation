# Automated Micro-Influencer Outreach System

EDXSO AI Engineer Intern, Assignment 1. A pipeline that discovers Lifestyle
micro-influencers on YouTube, filters and classifies them with reasons,
enriches their profiles, writes a personalised email pitch and Instagram DM for
each one, and sends the emails through a Zapier workflow with a review step,
duplicate protection and an outreach tracker.

```
Discovery -> Data Collection -> Filtering -> Enrichment -> AI Personalisation -> Review -> Sending -> Tracking
 YouTube      YouTube videos     rules +      email, site,    Gemini               Google    Zapier +   Sheet +
 search                          Gemini       Instagram                             Sheet     Gmail      CSV
```

**Niche:** Lifestyle. **Platform:** YouTube. **Brand:** "Demo Brand", a
fictional brand defined in `config/brand.yaml`.

> **No fake data.** Every influencer, number and email comes from an API or from
> text the creator published. Missing values are written as `Not Found` or
> `Not Available`, never guessed. Because the brand is fictional, every email
> the workflow sends goes to one demo inbox, never to a creator.

## Results of the test run (2026-11-10)

| Stage | Result |
| --- | --- |
| Discovery | 24 searches, **826 distinct channels** |
| Follower range (5,000-100,000) | 304 channels |
| **Shortlist** | **163 creators pass all 7 checks** (median 19,000 subscribers, median engagement 3.64%) |
| Contact email | found for 115; **48 marked `Not Found`** |
| Instagram | handle found for 84, follower count for 81 |
| Messages | 163 emails (61-90 words) and 163 DMs (22-30 words) |

## Deliverables

| Output | Where |
| --- | --- |
| Working system | `python -m outreach run` + the Zap in `docs/zapier-setup.md` |
| Influencer dataset | `data/influencers.csv` (all 826 channels, PASS/FAIL with reasons) |
| Personalised messages | `data/messages.csv` (email pitch + Instagram DM) |
| Outreach tracker | `data/outreach_tracker.csv` and the `Outreach Tracker` sheet tab |
| Code documentation | `CODE_STRUCTURE.md` |

## Technology stack and APIs

| Tool | Used for |
| --- | --- |
| Python 3.11+, SQLite, CSV | pipeline, storage, exports |
| YouTube Data API v3 | discovery, subscriber counts, video statistics |
| Gemini API (`google-genai`) | niche and brand-fit classification, message writing |
| Apify `instagram-profile-scraper` | Instagram followers and engagement |
| Google Sheets (`gspread`) | review queue and tracker |
| Zapier + Gmail | sending the emails and writing the status back |
| `requests` + `BeautifulSoup` | reading a contact email from a creator's own website |
| pytest | 38 unit tests |

## Discovery and data sources

1. `config/niche.yaml` lists 24 niche search phrases ("day in my life vlog",
   "slow living vlog", ...). Each is one YouTube search for videos from the
   last 60 days, so every channel found is active.
2. Each channel is stored once, then its details (subscribers, country,
   description, topics) are fetched 50 channels per call.
3. For channels in the follower range, the last 10 videos are fetched.

**Engagement rate** = median of `(likes + comments) / views` over the last 10
videos. With fewer than 3 measurable videos it is `Not Available`.

Contact emails and handles come from the channel description, video
descriptions and the creator's own website; Instagram numbers come from the
public profile through Apify.

## Filtering logic

| # | Check | Rule (in `config/niche.yaml`) |
| --- | --- | --- |
| 1 | Followers | 5,000 to 100,000 subscribers |
| 2 | Activity | at least 3 videos, last upload within 60 days |
| 3 | Engagement | at least 2.0% |
| 4 | Geography | optional country allow-list (off by default) |
| 5 | Content relevance | at least 3 niche keywords in description, topics and titles |
| 6 | Niche (Gemini) | classified as Lifestyle with confidence of 0.6 or more |
| 7 | Brand fit (Gemini) | score of 6/10 or more |

Checks run cheapest first, so the AI only sees creators who passed checks 1-5.
Every check writes a `PASS` or `FAIL` line with the real numbers into the
`Filter Reasons` column.

## Enrichment process

For shortlisted creators, the email is searched in this order: channel
description, video descriptions (only if repeated in at least 2 videos), the
creator's website (respecting `robots.txt`), Instagram bio. The source is saved
in `Email Source`; if nothing is found the email is `Not Found`.

Handles and websites must resemble the channel's own name, so sponsors and
credited musicians are not mistaken for the creator. Audience age, gender and
geography are private on every platform and reported as `Not Available`.

## AI model and prompts

Gemini (free tier) with `gemini-3.8-flash` first and fallbacks listed in `.env`.
Every answer must match a Pydantic JSON schema and is validated before use.

- **Classification** (`outreach/classify.py`, 20 channels per call): given the
  niche definition, the brand profile and each channel's real data (name,
  subscribers, country, topics, description, recent titles), returns niche,
  sub-niche, confidence, content themes, tone, brand fit (0-10) and a reason
  for each.
- **Messages** (`outreach/messages.py`, 10 creators per call): given the brand,
  the offer and each creator's niche, tone, themes and three latest video
  titles, returns an email subject, email body and Instagram DM. The system
  prompt forbids inventing facts or leaving placeholders.

## Personalisation logic

1. **Collaboration angle** chosen by rules in `config/brand.yaml` from the
   creator's followers, engagement and brand fit: ambassador, sponsorship,
   barter, affiliate, paid placement or UGC.
2. **Signals** given to the model: niche, tone, content themes, recent videos,
   audience size, the offer and the brand's value proposition. Each creator
   gets a different opening style so messages don't read like one template.
3. **Checked in code**: email 60-90 words, DM 15-30 words, no placeholders.
   Rejected messages are rewritten with the reason; ones that still fail are
   never sent.

## Sending mechanism

```
python -m outreach queue   ->  "Email Queue" sheet tab (Pending review)
you set review_status = Approved
Zapier: Sheets trigger -> Filter -> Gmail send -> update row (sent = Yes)
python -m outreach sync    ->  Outreach Tracker tab + data/outreach_tracker.csv
```

- Only creators with an email are queued; the rest are logged as skipped.
- Duplicates are blocked by channel ID, by email address, and by the Zap's
  filter on already-sent rows.
- **Test mode** (default): every email goes to `TEST_INBOX` with a
  `[DEMO for <channel>]` subject. `SEND_MODE=live` is refused while the brand
  is marked as a demo.

Zap setup steps: [docs/zapier-setup.md](docs/zapier-setup.md).

## Setup instructions

```powershell
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env            # macOS/Linux: cp .env.example .env
```

Fill in `.env`:

| Variable | Where to get it |
| --- | --- |
| `YOUTUBE_API_KEY` | Google Cloud Console: enable YouTube Data API v3, create an API key |
| `GEMINI_API_KEY` | https://aistudio.google.com/api-keys |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | Google Cloud: enable Sheets API, create a service account, save its JSON key in `credentials/` |
| `SHEET_ID` | ID from the Google Sheet URL; share the sheet with the service account as Editor |
| `APIFY_TOKEN` | Apify Console > Settings > API & Integrations (optional) |
| `TEST_INBOX` | the inbox that receives every demo email |

```powershell
python -m outreach doctor   # check every key
python -m outreach run      # run the whole pipeline
python -m outreach sync     # after the Zap has sent approved rows
python -m pytest            # run the tests
```

Single stages can also be run on their own: `discover`, `measure`, `filter`,
`classify`, `enrich`, `messages`, `export`, `queue`, `sync`, `status`. Every
stage saves its progress, so a stage stopped by a quota continues where it
left off.

The code is explained file by file in [CODE_STRUCTURE.md](CODE_STRUCTURE.md).
