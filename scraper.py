"""
Remote OSINT / AML-KYC / language-analyst job scraper, EU-eligible roles only.

Sources (each can be switched off in SOURCES):
  jobspy    LinkedIn, Indeed (12 EU countries incl. Poland), Glassdoor (8 EU countries), HelloWork (France)
  adzuna    API, needs free key  -> env ADZUNA_APP_ID, ADZUNA_APP_KEY   (indexes many Polish portals)
  jooble    API, needs free key  -> env JOOBLE_API_KEY                  (aggregates many Polish portals)
  arbeitnow API, no key (Germany/EU, remote flag)
  remotive  API, no key (remote jobs, max 4 calls/day per Remotive's rules)

Run once:      python job_scraper.py
Run 2x daily:  python job_scraper.py --daemon        (08:00 and 18:00 local time)
or cron:       0 8,18 * * *  /usr/bin/python3 /path/to/job_scraper.py
Windows:       Task Scheduler, two daily triggers running the same command.

pip install -U python-jobspy pandas requests
"""
import argparse
import csv
import os
import random
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import requests

# ---------------------------------------------------------------- settings
SOURCES = ["jobspy", "adzuna", "jooble", "arbeitnow", "remotive"]

# JobSpy boolean queries (one call covers many terms)
BOOLEAN_QUERIES = [
    '"OSINT" OR "open source intelligence" OR "intelligence analyst" OR "investigator"',
    '"AML" OR "KYC" OR "KYB" OR "due diligence" OR "financial crime" OR "sanctions" OR "compliance analyst"',
    '"language analyst" OR "linguist" OR "multilingual analyst" OR "translator"',
]
# Polish/other-language queries for the country boards
LOCAL_QUERIES = {
    "poland": ['"analityk OSINT" OR "analityk AML" OR "specjalista KYC" OR "analityk ds. compliance" OR "weryfikacja klienta"',
               '"tłumacz" OR "lingwista" OR "analityk językowy" OR "analityk wywiadu"'],
    "germany": ['"Geldwäsche" OR "Compliance Analyst" OR "Sanktionen" OR "Ermittler"'],
    "france": ['"analyste LCB-FT" OR "analyste conformité" OR "KYC" OR "analyste renseignement"'],
}
# Plain keyword list for APIs without boolean support (Jooble)
SIMPLE_TERMS = ["OSINT analyst", "AML analyst", "KYC analyst", "due diligence analyst",
                "sanctions analyst", "financial crime analyst", "language analyst",
                "analityk OSINT", "analityk AML", "specjalista KYC", "tłumacz zdalnie"]

LINKEDIN_LOCATIONS = ["European Union", "Poland", "Germany", "Netherlands", "Ireland", "Spain"]
INDEED_COUNTRIES = ["poland", "germany", "netherlands", "ireland", "spain", "france",
                    "belgium", "austria", "portugal", "italy", "czech republic", "romania"]
GLASSDOOR_COUNTRIES = ["germany", "netherlands", "ireland", "spain", "france", "belgium", "austria", "italy"]
ADZUNA_COUNTRIES = ["pl", "de", "nl", "fr", "es", "it", "at", "be"]   # check pl at developer.adzuna.com
JOOBLE_LOCATIONS = ["Poland"]

RESULTS_WANTED = 25
HOURS_OLD = 36                  # >24h so a missed run loses nothing; DB de-duplicates
SLEEP_RANGE = (4, 9)            # seconds between requests
RUN_TIMES = ["08:00", "18:00"]  # used by --daemon
HTTP_TIMEOUT = 30

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "local_jobs.db"
CSV_FILE = BASE_DIR / "jobs.csv"

# ---------------------------------------------------------------- filters
RELEVANT = re.compile(
    r"\b(osint|open[- ]source intelligence|intelligence analyst|investigator|investigations?|"
    r"aml|kyc|kyb|know your (customer|business)|anti[- ]money|money laundering|due diligence|financial crime|"
    r"sanctions?|compliance analyst|fraud analyst|risk analyst|"
    r"language analyst|linguist|multilingual|translator|translation|"
    r"tłumacz\w*|lingwist\w*|praniu pieni\w+|weryfikacj\w+ klient\w*|"
    r"geldwäsche|sanktion\w*|ermittler\w*|"
    r"lcb-ft|blanchiment|conformité|renseignement)\b",
    re.I,
)
# Titles that match RELEVANT only through generic "analityk" etc. need a topical word too:
TOPICAL = re.compile(
    r"(osint|intelligence|aml|kyc|kyb|money laundering|due diligence|financial crime|sanction|compliance|"
    r"fraud|investigat|risk|linguist|language|translat|multilingual|tłumacz|lingwist|pran|wywiad|"
    r"zgodno|weryfikacj|geldwäsche|ermittl|blanchiment|conformité|renseignement)",
    re.I,
)

GENERIC_TITLE = re.compile(r"(analy[sz]t|analityk|researcher|specialist|specjalist|investigator|officer|consultant)", re.I)
STRONG = re.compile(r"(osint|\baml\b|\bkyc\b|\bkyb\b|due diligence|sanctions|financial crime|money laundering|"
                    r"praniu pieni|geldwäsche|blanchiment)", re.I)

BLOCKED_PLACE = re.compile(
    r"(united states|\busa\b|\bu\.s\.a?\.?|\bnorth america\b|\bcanada\b|\bindia\b|\bphilippines\b|\bsingapore\b|"
    r"\bbrazil\b|\bmexico\b|\baustralia\b|united kingdom|\bengland\b|\bscotland\b|\bwales\b|\blatam\b|\bapac\b)",
    re.I,
)
BLOCKED_US_CAPS = re.compile(r"\b(US|U\.S\.|USA)\b")          # case-sensitive on purpose ("join us")
BLOCKED_ELIGIBILITY = re.compile(
    r"(\bUS[- ]only\b|\bUS[- ]based\b|\bU\.S\.[- ]based\b|\bUK[- ]based\b|\bUK only\b|"
    r"(must|should) (be|reside|live|be located) (in|within) the (US|U\.S\.|United States|UK)|"
    r"(us|u\.s\.) citizen|security clearance|"
    r"(authori[sz]ed|eligible|legally entitled) to work in the (us|u\.s\.|united states|uk)|"
    r"(united states|u\.s\.) (residents?|candidates) only)",
    re.I,
)
US_STATE = re.compile(r",\s*(A[LKZR]|C[AOT]|D[CE]|FL|GA|HI|I[ADLN]|K[SY]|LA|M[ADEINOST]|N[CDEHJMVY]|"
                      r"O[HKR]|PA|RI|S[CD]|T[NX]|UT|V[AT]|W[AIVY])\b")

EU_PLACES = (
    "european union|europe|emea|eu\\b|eea|poland|polska|germany|deutschland|netherlands|ireland|spain|france|"
    "belgium|austria|portugal|italy|czech|romania|sweden|denmark|finland|greece|hungary|bulgaria|croatia|"
    "slovakia|slovenia|lithuania|latvia|estonia|luxembourg|malta|cyprus|worldwide|anywhere"
)
EU_SIGNAL = re.compile(rf"\b({EU_PLACES})", re.I)
REMOTE_WORDS = re.compile(
    r"(\bremote|work from home|home[- ]?office|telecommut|zdaln|praca z domu|homeoffice|mobiles arbeiten|télétravail|teletrabajo)",
    re.I,
)


def is_remote(row):
    if row.get("is_remote") is True or str(row.get("is_remote")).lower() == "true":
        return True
    text = f"{row.get('title','')} {row.get('location','')} {str(row.get('description',''))[:3000]}"
    return bool(REMOTE_WORDS.search(text))


def keep_job(row):
    title = str(row.get("title", ""))
    location = str(row.get("location", ""))
    description = str(row.get("description", "") or "")
    if description.lower() == "nan":
        description = ""
    desc = description[:3000]

    # Title must be on-topic; generic analyst titles also need a strong topical term in title or description.
    if not RELEVANT.search(title):
        if not (GENERIC_TITLE.search(title) and (TOPICAL.search(title) or STRONG.search(desc[:1500]))):
            return False
    if not is_remote(row):
        return False
    if BLOCKED_PLACE.search(location) or BLOCKED_US_CAPS.search(location) or US_STATE.search(location):
        return False
    if BLOCKED_PLACE.search(title) or BLOCKED_US_CAPS.search(title):
        return False
    if BLOCKED_ELIGIBILITY.search(desc):
        return False
    if not (row.get("eu_hint") or EU_SIGNAL.search(location) or EU_SIGNAL.search(desc)):
        return False
    return True


# ---------------------------------------------------------------- database
def configure_geocoder():
    """Keep JobSpy from doing an IP geolocation lookup (original workaround)."""
    geocoder = MagicMock()
    ip_result = MagicMock()
    ip_result.country = "poland"
    geocoder.ip.return_value = ip_result
    sys.modules["geocoder"] = geocoder


def initialize_database():
    connection = sqlite3.connect(DATABASE)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS seen_jobs (
            job_url TEXT PRIMARY KEY, title TEXT, company TEXT, location TEXT, site TEXT,
            found_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute("CREATE TABLE IF NOT EXISTS seen_keys (job_key TEXT PRIMARY KEY)")
    connection.commit()
    return connection


def job_key(title, company):
    return re.sub(r"\W+", " ", f"{title} {company}".lower()).strip()


def job_seen(connection, job_url, key):
    if connection.execute("SELECT 1 FROM seen_jobs WHERE job_url = ?", (job_url,)).fetchone():
        return True
    return connection.execute("SELECT 1 FROM seen_keys WHERE job_key = ?", (key,)).fetchone() is not None


def save_job(connection, job_url, key, title, company, location, site):
    connection.execute(
        "INSERT OR IGNORE INTO seen_jobs (job_url, title, company, location, site) VALUES (?, ?, ?, ?, ?)",
        (job_url, title, company, location, site),
    )
    connection.execute("INSERT OR IGNORE INTO seen_keys (job_key) VALUES (?)", (key,))
    connection.commit()


# ---------------------------------------------------------------- source adapters
# Each adapter yields dicts: title, company, location, site, job_url, date_posted, description,
# is_remote (bool|None), eu_hint (bool: the query itself was an EU country).
def pause():
    time.sleep(random.uniform(*SLEEP_RANGE))


def _clean(value):
    return "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value).strip()


def from_jobspy_frame(frame, site, eu_hint):
    if frame is None or frame.empty:
        return
    for _, row in frame.iterrows():
        yield {
            "title": _clean(row.get("title")), "company": _clean(row.get("company")),
            "location": _clean(row.get("location")),
            "site": _clean(row.get("site") or site).capitalize(),
            "job_url": _clean(row.get("job_url")), "date_posted": _clean(row.get("date_posted")),
            "description": _clean(row.get("description")), "is_remote": row.get("is_remote"),
            "eu_hint": eu_hint,
        }


def src_jobspy():
    from jobspy import scrape_jobs

    def call(label, eu_hint, **kwargs):
        print(f"[jobspy] {label}")
        try:
            frame = scrape_jobs(**kwargs)
        except Exception as error:
            print(f"  failed: {error}")
            pause()
            return
        pause()
        yield from from_jobspy_frame(frame, kwargs["site_name"], eu_hint)

    for term in BOOLEAN_QUERIES:
        for loc in LINKEDIN_LOCATIONS:
            yield from call(f"linkedin {loc}", True, site_name="linkedin", search_term=term, location=loc,
                            is_remote=True, results_wanted=RESULTS_WANTED, hours_old=HOURS_OLD)
        for country in INDEED_COUNTRIES:
            # Indeed: hours_old can't be combined with is_remote, so "remote" goes in the query
            yield from call(f"indeed {country}", True, site_name="indeed", search_term=f"{term} remote",
                            location=country, country_indeed=country,
                            results_wanted=RESULTS_WANTED, hours_old=HOURS_OLD)
        for country in GLASSDOOR_COUNTRIES:
            yield from call(f"glassdoor {country}", True, site_name="glassdoor", search_term=f"{term} remote",
                            location=country, country_indeed=country,
                            results_wanted=RESULTS_WANTED, hours_old=HOURS_OLD)

    for country, queries in LOCAL_QUERIES.items():
        for term in queries:
            yield from call(f"indeed {country} (local language)", True, site_name="indeed",
                            search_term=f"{term} remote", location=country, country_indeed=country,
                            results_wanted=RESULTS_WANTED, hours_old=HOURS_OLD)
    for term in LOCAL_QUERIES.get("france", []):
        yield from call("hellowork france", True, site_name="hellowork", search_term=term,
                        location="France", results_wanted=RESULTS_WANTED, hours_old=HOURS_OLD)


def src_adzuna():
    app_id, app_key = os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        print("[adzuna] skipped: set ADZUNA_APP_ID / ADZUNA_APP_KEY (free key at developer.adzuna.com)")
        return
    for country in ADZUNA_COUNTRIES:
        print(f"[adzuna] {country}")
        words = "osint aml kyc sanctions compliance investigator linguist translator due diligence"
        if country == "pl":
            words += " analityk tłumacz lingwista"
        try:
            resp = requests.get(
                f"https://api.adzuna.com/v1/api/jobs/{country}/search/1",
                params={"app_id": app_id, "app_key": app_key, "what_or": words, "max_days_old": 2,
                        "results_per_page": 50, "sort_by": "date", "content-type": "application/json"},
                headers={"Accept": "application/json"}, timeout=HTTP_TIMEOUT)
            resp.raise_for_status()
            results = resp.json().get("results", [])
        except Exception as error:
            print(f"  failed: {error}")
            pause()
            continue
        pause()
        for r in results:
            yield {
                "title": _clean(r.get("title")), "company": _clean((r.get("company") or {}).get("display_name")),
                "location": _clean((r.get("location") or {}).get("display_name")), "site": "Adzuna",
                "job_url": _clean(r.get("redirect_url")), "date_posted": _clean(r.get("created")),
                "description": _clean(r.get("description")), "is_remote": None, "eu_hint": True,
            }


def src_jooble():
    key = os.getenv("JOOBLE_API_KEY")
    if not key:
        print("[jooble] skipped: set JOOBLE_API_KEY (free key at jooble.org/api/about)")
        return
    for location in JOOBLE_LOCATIONS:
        for term in SIMPLE_TERMS:
            print(f"[jooble] {location}: {term}")
            try:
                resp = requests.post(f"https://jooble.org/api/{key}",
                                     json={"keywords": f"{term} remote", "location": location, "page": 1},
                                     timeout=HTTP_TIMEOUT)
                resp.raise_for_status()
                results = resp.json().get("jobs", [])
            except Exception as error:
                print(f"  failed: {error}")
                pause()
                continue
            pause()
            for r in results:
                yield {
                    "title": _clean(r.get("title")), "company": _clean(r.get("company")),
                    "location": _clean(r.get("location")), "site": "Jooble",
                    "job_url": _clean(r.get("link")), "date_posted": _clean(r.get("updated")),
                    "description": _clean(r.get("snippet")), "is_remote": None, "eu_hint": True,
                }


def src_arbeitnow():
    print("[arbeitnow] page 1-3")
    for page in (1, 2, 3):
        try:
            resp = requests.get("https://www.arbeitnow.com/api/job-board-api", params={"page": page},
                                timeout=HTTP_TIMEOUT)
            resp.raise_for_status()
            results = resp.json().get("data", [])
        except Exception as error:
            print(f"  failed: {error}")
            return
        pause()
        for r in results:
            created = r.get("created_at")
            yield {
                "title": _clean(r.get("title")), "company": _clean(r.get("company_name")),
                "location": _clean(r.get("location")), "site": "Arbeitnow", "job_url": _clean(r.get("url")),
                "date_posted": datetime.fromtimestamp(created).strftime("%Y-%m-%d") if created else "",
                "description": _clean(r.get("description")), "is_remote": bool(r.get("remote")),
                "eu_hint": True,
            }


def src_remotive():
    # Remotive rules: max 4 requests/day, link back to the listing, 24h delay. One call per run is fine.
    print("[remotive] search")
    for term in ("osint", "compliance", "analyst"):
        try:
            resp = requests.get("https://remotive.com/api/remote-jobs", params={"search": term},
                                timeout=HTTP_TIMEOUT)
            resp.raise_for_status()
            results = resp.json().get("jobs", [])
        except Exception as error:
            print(f"  failed: {error}")
            return
        pause()
        for r in results:
            yield {
                "title": _clean(r.get("title")), "company": _clean(r.get("company_name")),
                "location": _clean(r.get("candidate_required_location")), "site": "Remotive",
                "job_url": _clean(r.get("url")), "date_posted": _clean(r.get("publication_date")),
                "description": _clean(r.get("description")), "is_remote": True, "eu_hint": False,
            }
        break   # a single request per run keeps us at 2/day


ADAPTERS = {"jobspy": src_jobspy, "adzuna": src_adzuna, "jooble": src_jooble,
            "arbeitnow": src_arbeitnow, "remotive": src_remotive}


# ---------------------------------------------------------------- pipeline
def process(rows, connection):
    new_jobs = []
    for row in rows:
        url, title, company = row["job_url"], row["title"], row["company"]
        if not url or not title:
            continue
        key = job_key(title, company)
        if job_seen(connection, url, key) or not keep_job(row):
            continue
        save_job(connection, url, key, title, company, row["location"], row["site"])
        job = {"found_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "title": title, "company": company,
               "location": row["location"], "site": row["site"], "date_posted": row["date_posted"],
               "job_url": url}
        new_jobs.append(job)
        print(f"  NEW [{row['site']}] {title} | {company} | {row['location']}\n      {url}")
    return new_jobs


def write_csv(jobs):
    fieldnames = ["found_at", "title", "company", "location", "site", "date_posted", "job_url"]
    existing = []
    if CSV_FILE.exists():
        with CSV_FILE.open("r", newline="", encoding="utf-8") as f:
            existing = list(csv.DictReader(f))
    seen = {j.get("job_url", "") for j in existing}
    for job in jobs:
        if job["job_url"] not in seen:
            existing.append(job)
            seen.add(job["job_url"])
    with CSV_FILE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, restval="")
        writer.writeheader()
        writer.writerows(existing)
    print(f"\nCSV saved: {CSV_FILE} ({len(existing)} total jobs)")


def scrape():
    print(f"=== Run started {datetime.now():%Y-%m-%d %H:%M} ===")
    connection = initialize_database()
    all_new = []
    try:
        for name in SOURCES:
            try:
                all_new += process(ADAPTERS[name](), connection)
            except Exception as error:      # one broken source must not stop the others
                print(f"[{name}] source failed: {error}")
    finally:
        connection.close()
    write_csv(all_new)
    print(f"Finished. {len(all_new)} new jobs.")


def seconds_until_next_run(now=None):
    now = now or datetime.now()
    candidates = []
    for t in RUN_TIMES:
        h, m = map(int, t.split(":"))
        run = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if run <= now:
            run += timedelta(days=1)
        candidates.append(run)
    return (min(candidates) - now).total_seconds()


def daemon():
    while True:
        wait = seconds_until_next_run()
        print(f"Next run in {wait/3600:.1f} h (times: {', '.join(RUN_TIMES)})")
        time.sleep(wait)
        try:
            scrape()
        except Exception as error:
            print(f"Run failed: {error}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--daemon", action="store_true", help="keep running, scrape at RUN_TIMES")
    args = parser.parse_args()
    configure_geocoder()
    daemon() if args.daemon else scrape()
