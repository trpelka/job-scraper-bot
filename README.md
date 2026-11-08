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

It also rejects jobs it has already seen, both by URL and by a normalized `title + company` key, so cross-posted listings do not create noise.

## Sources

| Source | Notes |
| --- | --- |
| `jobspy` | Indeed (12 EU countries), LinkedIn (Poland / EU / Germany), optional Glassdoor and HelloWork |
| `portals_pl` | Pracuj.pl, JustJoin.it, RocketJobs.pl, Jooble.pl public search pages |
| `arbeitnow` | public job-board API, Germany/EU, remote flag |
| `remotive` | public remote-jobs API, one request per run to respect their limits |

LinkedIn and Glassdoor frequently block datacenter IPs (HTTP 429/403), especially on GitHub Actions. The scraper detects a board returning nothing repeatedly and skips it for the rest of the run instead of hammering it. Set proxies to improve results:

```bash
# Windows PowerShell
$env:JOBSPY_PROXIES="user:pass@host:port,user:pass@host2:port2"
python scraper.py
```

## Quick start

```bash
git clone https://github.com/trpelka/job-scraper-bot.git
cd job-scraper-bot
pip install -U python-jobspy pandas requests beautifulsoup4
python scraper.py
```

Run once, print new matches, append them to `jobs.csv` and store them in `local_jobs.db`.

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

- `seen_jobs` — `job_url` primary key, plus title/company/location/site/found_at
- `seen_keys` — normalized `title + company` keys, used to catch re-posts under a new URL

Delete both files to start with a clean slate.

## Configuration

Tunable constants live near the top of `scraper.py`:

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

Filters are regexes (`RELEVANT`, `TOPICAL`, `BLOCKED_PLACE`, `BLOCKED_ELIGIBILITY`) and can be edited the same way.

## Automation

`.github/workflows/run.yml` runs at `06:00` and `16:00` UTC (08:00 / 18:00 Warsaw summer time), commits `jobs.csv` and `local_jobs.db` back to the repo, and can be started manually from the **Actions** tab.

After the October DST change, switch the cron to `0 7,17 * * *` for the same local times.

## Limitations

- Public HTML scraping is best-effort: selectors and URL patterns can change without notice.
- LinkedIn/Glassdoor results are unreliable from cloud IPs; use a proxy or run locally.
- Only remote roles are kept by design.
- Descriptions are truncated before filtering to keep the run fast.
- The CSV grows forever; prune it or move to a proper database if you need long-term analytics.
