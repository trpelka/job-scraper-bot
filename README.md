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

SQLite (`local_jobs.db`) keeps two tables:

- `seen_jobs` — normalized `job_url` primary key, plus title/company/location/site/found_at
- `seen_keys` — normalized `title + company` keys, used to catch re-posts under a new URL

Delete both files to start with a clean slate.

`reports/latest.md` summarises the latest run (mode, new-job count, per-source table, up to 25 new listings). It is git-ignored and uploaded as a workflow artifact; the contents are also appended to the GitHub Actions step summary.

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
| `RUN_TIMES` | `08:00,18:00` |
| `JOBSPY_PROXIES` | empty |

Filters are regexes (`RELEVANT`, `TOPICAL`, `BLOCKED_PLACE`, `BLOCKED_ELIGIBILITY`) and can be edited the same way.

## Automation

`.github/workflows/run.yml` runs at `06:00` and `16:00` UTC (08:00 / 18:00 Warsaw summer time), commits `jobs.csv` and `local_jobs.db` back to the repo, writes a step summary, uploads the report and can be started manually from the **Actions** tab.

After the October DST change, switch the cron to `0 7,17 * * *` for the same local times.

`ci.yml` runs linting and the test suite on every push and pull request. Dependabot keeps Python and GitHub Actions dependencies up to date.

## Development

```bash
pip install -r requirements-dev.txt
ruff check .
pytest
```

The tests cover URL normalization, title/company keys, eligibility filtering, HTML offer parsing, dry-run CSV behaviour and daemon timing. They do not touch the network.

## Limitations

- Public HTML scraping is best-effort: selectors and URL patterns can change without notice.
- LinkedIn/Glassdoor results are unreliable from cloud IPs; use a proxy or run locally.
- Only remote roles are kept by design.
- Descriptions are truncated before filtering to keep the run fast.
- The CSV grows forever; prune it or move to a proper database if you need long-term analytics.
- `jobs.csv` and `local_jobs.db` are committed to the repository. For long-term use, move them to an actions cache or a separate data branch.
