# job-scraper-bot

A lightweight, self-hosted scraper for remote **OSINT, AML/KYC and language-analyst** roles that are actually open to candidates in the EU.

Powered by `python-jobspy`, public job-board pages and two public APIs. No accounts, no API keys, no paid services. Results are de-duplicated in SQLite and appended to a CSV that survives between runs.

## Why this exists

Most remote-job feeds are full of US-only listings and reposted duplicates. This scraper filters for:

- **Relevant titles** — OSINT, intelligence, investigations, AML, KYC/KYB, due diligence, financial crime, sanctions, compliance, fraud, linguist, translator, multilingual analyst (English plus Polish, German and French phrasings)
- **Remote work** — from the board's flag, the location or the description
- **EU eligibility** — EU/EEA countries, "Europe", "EMEA", "worldwide", or a country hint in the query
- **No blocked locations** — US, UK, Canada, India, Philippines, Singapore, Brazil, Mexico, Australia, APAC, LATAM and US-state patterns are rejected
- **No US/UK-only eligibility language** — "US-only", "must reside in the US", "security clearance", etc.

It also rejects jobs it has already seen, both by normalized URL and by a normalized `title + company` key, so cross-posted listings do not create noise.

## Sources

| Source | Notes |
| --- | --- |
| `jobspy` | Indeed (12 EU countries), LinkedIn (Poland / EU / Germany), optional Glassdoor and HelloWork |
| `portals_pl` | Pracuj.pl, JustJoin.it, RocketJobs.pl, Jooble.pl public search pages |
| `arbeitnow` | public job-board API, Germany/EU, remote flag |
| `remotive` | public remote-jobs API, one request per run to respect their limits |

LinkedIn and Glassdoor frequently block datacenter IPs (HTTP 429/403), especially on GitHub Actions. The scraper detects a board returning nothing repeatedly and skips it for the rest of the run instead of hammering it. HTTP calls retry transient failures with exponential backoff. Set proxies to improve results:

```bash
# Windows PowerShell
$env:JOBSPY_PROXIES="user:pass@host:port,user:pass@host2:port2"
python scraper.py
```

## Quick start

```bash
git clone https://github.com/trpelka/job-scraper-bot.git
cd job-scraper-bot
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
python scraper.py
```

Run once, print new matches, append them to `jobs.csv` and store them in `local_jobs.db`.

### Command line

```bash
python scraper.py --dry-run                     # collect and report, change nothing
python scraper.py --sources arbeitnow,remotive  # run only selected adapters
python scraper.py --max-runtime 10              # hard stop after 10 minutes
```

Adapter keys: `jobspy`, `portals_pl`, `arbeitnow`, `remotive`.

### Run it twice a day

```bash
python scraper.py --daemon
```

The daemon scrapes at `08:00` and `18:00` local time. On Windows, two Task Scheduler triggers running `python scraper.py` achieve the same thing; on Linux use cron:

```cron
0 8,18 * * * /usr/bin/python3 /path/to/scraper.py
```

## Output

`jobs.csv` columns:

```text
found_at, title, company, location, site, date_posted, job_url
```

The CSV is a rolling **7-day** feed (`CSV_RETENTION_DAYS`, default `7`). Rows older than the window — and legacy rows without a usable `found_at` — are dropped on every run.

SQLite (`local_jobs.db`) keeps the full de-duplication history and lives on the `data` branch, not in `main`:

- `seen_jobs` — normalized `job_url` primary key, plus title/company/location/site/found_at
- `seen_keys` — normalized `title + company` keys, used to catch re-posts under a new URL

Delete `local_jobs.db` locally or delete the `data` branch to start with a clean slate.

`reports/latest.md` summarises the latest run (mode, new-job count, per-source table, up to 25 new listings). It is git-ignored and uploaded as a workflow artifact; the contents are also appended to the GitHub Actions step summary.

## Data and storage

Two files are deliberately separated:

| Data | Where | Size (typical) | Why |
| --- | --- | --- | --- |
| `jobs.csv` | `main`, rolling 7 days | ~9 KB | Human-readable feed, cheap to commit |
| `local_jobs.db` | `data` branch, single rolling commit | ~0.3 MB | Full de-duplication history without growing `main` |

The `data` branch is rewritten with `git push --force` on every run, so it always contains exactly one commit and one database file. Its storage footprint is the size of the current database, not its history.

Why not Actions cache? The cache is limited to **10 GB per repository**, entries are evicted after **7 days without access**, and there is no API to seed it. The rolling `data` branch has no eviction, survives pauses in the schedule, and is inspectable.

For reference, on GitHub Free:

- **Actions minutes and storage are free for public repositories** (2,000 minutes/month and 500 MB storage are the private-repo allowances).
- **Actions cache:** 10 GB per repository, entries expire after 7 days unused.
- **Artifacts:** 90-day default retention; here only the tiny Markdown report is uploaded.
- **Repository:** GitHub recommends staying under 1 GB; files over 100 MB trigger a warning and pushes over 2 GB are blocked.

Old blobs already in `main` history are not reclaimed by deleting the file now; that would require a history rewrite, which is not done here.

## Configuration

Constants live near the top of `scraper.py`:

| Constant | Purpose |
| --- | --- |
| `SOURCES` | Which adapters to run |
| `BOOLEAN_QUERIES` | JobSpy search queries |
| `LOCAL_QUERIES` | Local-language queries per country |
| `JOBSPY_SITES` | Boards JobSpy should use |
| `RESULTS_WANTED`, `HOURS_OLD` | Result count and lookback window |
| `MAX_RUNTIME_MIN` | Hard stop for the whole run (default 25 min) |
| `SLEEP_RANGE`, `LINKEDIN_SLEEP` | Delay between requests |
| `RUN_TIMES` | Times used by `--daemon` |
| `HTTP_TIMEOUT` | Per-request timeout |

Several of them can be overridden without editing code:

| Variable | Default |
| --- | --- |
| `SOURCES` | `jobspy,portals_pl,arbeitnow,remotive` |
| `MAX_RUNTIME_MIN` | `25` |
| `RESULTS_WANTED` | `25` |
| `HOURS_OLD` | `36` |
| `HTTP_TIMEOUT` | `30` |
| `CSV_RETENTION_DAYS` | `7` |
| `RUN_TIMES` | `08:00,18:00` |
| `JOBSPY_PROXIES` | empty |

Filters are regexes (`RELEVANT`, `TOPICAL`, `BLOCKED_PLACE`, `BLOCKED_ELIGIBILITY`) and can be edited the same way.

## Automation

`.github/workflows/run.yml` runs at `06:00` and `16:00` UTC (08:00 / 18:00 Warsaw summer time). It restores `local_jobs.db` from the `data` branch, commits the rolling 7-day `jobs.csv` to `main`, force-pushes the updated database back to `data`, writes a step summary, uploads the report and can be started manually from the **Actions** tab.

After the October DST change, switch the cron to `0 7,17 * * *` for the same local times.

`ci.yml` runs linting and the test suite on every push and pull request. Dependabot keeps Python and GitHub Actions dependencies up to date.

## Development

```bash
pip install -r requirements-dev.txt
ruff check .
pytest
```

The tests cover URL normalization, title/company keys, eligibility filtering, HTML offer parsing, 7-day CSV retention, dry-run CSV behaviour and daemon timing. They do not touch the network.

## Limitations

- Public HTML scraping is best-effort: selectors and URL patterns can change without notice.
- LinkedIn/Glassdoor results are unreliable from cloud IPs; use a proxy or run locally.
- Only remote roles are kept by design.
- Descriptions are truncated before filtering to keep the run fast.
- The 7-day CSV is a feed, not an archive; use the `data` branch database if you need long-term analytics.
- `local_jobs.db` grows with every new URL. It is kept out of `main`, but the `data` branch will grow over years; prune `seen_jobs` if that ever matters.
