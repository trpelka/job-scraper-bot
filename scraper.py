import csv
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

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "local_jobs.db"
CSV_FILE = BASE_DIR / "jobs.csv"


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
            location TEXT,
            site TEXT,
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


def save_job(connection, job_url, title, company, location, site):
    connection.execute(
        """
        INSERT OR IGNORE INTO seen_jobs
        (job_url, title, company, location, site)
        VALUES (?, ?, ?, ?, ?)
        """,
        (job_url, title, company, location, site),
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
        return []

    if jobs is None or jobs.empty:
        print(f"No jobs found on {site}.")
        return []

    new_jobs = []

    for _, row in jobs.iterrows():
        job_url = str(row.get("job_url", "")).strip()

        if not job_url or job_seen(connection, job_url):
            continue

        title = str(row.get("title", "N/A")).strip()
        company = str(row.get("company", "N/A")).strip()
        location = str(row.get("location", "N/A")).strip()
        site_name = str(row.get("site", site)).strip().capitalize()

        save_job(
            connection,
            job_url,
            title,
            company,
            location,
            site_name,
        )

        new_jobs.append(
            {
                "title": title,
                "company": company,
                "location": location,
                "site": site_name,
                "job_url": job_url,
            }
        )

        print(f"\n[{site_name}] {title}")
        print(f"Company: {company}")
        print(f"Location: {location}")
        print(f"URL: {job_url}")

    return new_jobs


def write_csv(jobs):
    fieldnames = [
        "title",
        "company",
        "location",
        "site",
        "job_url",
    ]

    existing_jobs = []

    if CSV_FILE.exists():
        with CSV_FILE.open(
            "r",
            newline="",
            encoding="utf-8",
        ) as file:
            reader = csv.DictReader(file)
            existing_jobs = list(reader)

    existing_urls = {
        job.get("job_url", "")
        for job in existing_jobs
    }

    all_jobs = existing_jobs

    for job in jobs:
        if job["job_url"] not in existing_urls:
            all_jobs.append(job)
            existing_urls.add(job["job_url"])

    with CSV_FILE.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )

        writer.writeheader()
        writer.writerows(all_jobs)

    print(f"\nCSV saved: {CSV_FILE}")
    print(f"Total jobs in CSV: {len(all_jobs)}")


def scrape():
    print(
        f"Searching for '{SEARCH_TERM}' "
        f"in '{LOCATION}'..."
    )

    connection = initialize_database()
    all_new_jobs = []

    try:
        for site in SITES:
            new_jobs = scrape_site(
                site,
                connection,
            )
            all_new_jobs.extend(new_jobs)
    finally:
        connection.close()

    write_csv(all_new_jobs)

    print(
        f"\nFinished. "
        f"Found {len(all_new_jobs)} new jobs."
    )


if __name__ == "__main__":
    configure_geocoder()
    scrape()
