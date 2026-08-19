import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd


SEARCH_TERM = "Python Developer"
LOCATION = "Remote"
RESULTS_WANTED = 10
HOURS_OLD = 48
SITES = ["linkedin", "indeed"]
COUNTRY_INDEED = "usa"

DATABASE = Path(__file__).resolve().parent / "local_jobs.db"


def configure_geocoder():
    geocoder = MagicMock()
    ip_result = MagicMock()
    ip_result.country = COUNTRY_INDEED
    geocoder.ip.return_value = ip_result
    sys.modules["geocoder"] = geocoder


def initialize_database():
    connection = sqlite3.connect(DATABASE)

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS seen_jobs (
            job_url TEXT PRIMARY KEY,
            title TEXT,
            company TEXT,
            found_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    connection.commit()
    return connection


def job_seen(connection, job_url):
    return connection.execute(
        "SELECT 1 FROM seen_jobs WHERE job_url = ?",
        (job_url,),
    ).fetchone() is not None


def save_job(connection, job_url, title, company):
    connection.execute(
        """
        INSERT OR IGNORE INTO seen_jobs
        (job_url, title, company)
        VALUES (?, ?, ?)
        """,
        (job_url, title, company),
    )
    connection.commit()


def scrape_site(site, connection):
    from jobspy import scrape_jobs

    print(f"\nSearching {site}...")

    try:
        jobs: pd.DataFrame = scrape_jobs(
            site_name=site,
            search_term=SEARCH_TERM,
            location=LOCATION,
            results_wanted=RESULTS_WANTED,
            hours_old=HOURS_OLD,
            country_indeed=COUNTRY_INDEED,
        )
    except Exception as error:
        print(f"{site} failed: {error}")
        return 0

    if jobs is None or jobs.empty:
        print(f"No jobs found on {site}.")
        return 0

    new_jobs = 0

    for _, row in jobs.iterrows():
        job_url = str(row.get("job_url", "")).strip()

        if not job_url or job_seen(connection, job_url):
            continue

        title = str(row.get("title", "N/A"))
        company = str(row.get("company", "N/A"))
        location = str(row.get("location", "N/A"))

        print(f"\n[{site.capitalize()}] {title}")
        print(f"Company: {company}")
        print(f"Location: {location}")
        print(f"URL: {job_url}")

        save_job(connection, job_url, title, company)
        new_jobs += 1

    return new_jobs


def scrape():
    print(
        f"Searching for '{SEARCH_TERM}' "
        f"in '{LOCATION}'..."
    )

    connection = initialize_database()
    total_new_jobs = 0

    try:
        for site in SITES:
            total_new_jobs += scrape_site(site, connection)
    finally:
        connection.close()

    print(f"\nFinished. Found {total_new_jobs} new jobs.")


if __name__ == "__main__":
    configure_geocoder()
    scrape()
