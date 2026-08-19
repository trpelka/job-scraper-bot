import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd


SEARCH_TERM = "Python Developer"
LOCATION = "Remote"
RESULTS_WANTED = 10
HOURS_OLD = 48
SITES = ["linkedin", "indeed", "glassdoor"]
COUNTRY_INDEED = "usa"

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "local_jobs.db"


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


def scrape():
    from jobspy import scrape_jobs

    print(f"Searching {SITES} for '{SEARCH_TERM}' in '{LOCATION}'...")

    jobs: pd.DataFrame = scrape_jobs(
        site_name=SITES,
        search_term=SEARCH_TERM,
        location=LOCATION,
        results_wanted=RESULTS_WANTED,
        hours_old=HOURS_OLD,
        country_indeed=COUNTRY_INDEED,
    )

    if jobs is None or jobs.empty:
        print("No jobs found.")
        return

    connection = initialize_database()
    new_jobs = 0

    try:
        for _, row in jobs.iterrows():
            job_url = str(row.get("job_url", "")).strip()

            if not job_url or job_seen(connection, job_url):
                continue

            title = str(row.get("title", "N/A"))
            company = str(row.get("company", "N/A"))
            location = str(row.get("location", "N/A"))
            site = str(row.get("site", "N/A")).capitalize()

            print(f"\n[{site}] {title}")
            print(f"Company: {company}")
            print(f"Location: {location}")
            print(f"URL: {job_url}")

            save_job(connection, job_url, title, company)
            new_jobs += 1

    finally:
        connection.close()

    print(f"\nFound {new_jobs} new jobs.")


if __name__ == "__main__":
    configure_geocoder()
    scrape()
