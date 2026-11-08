import re
from datetime import datetime, timedelta

import scraper


def test_normalize_url_strips_tracking_and_fragment():
    url = "HTTPS://Example.COM/Job/123/?utm_source=x&gclid=y&id=7#apply"

    assert scraper.normalize_url(url) == "https://example.com/Job/123?id=7"


def test_normalize_url_leaves_non_absolute_urls_alone():
    assert scraper.normalize_url("  /job/1  ") == "/job/1"


def test_job_key_normalizes_title_and_company():
    assert scraper.job_key("Senior  AML-Analyst", "ACME Sp. z o.o.") == "senior aml analyst acme sp z o o"


def test_keep_job_accepts_relevant_remote_eu_role():
    row = {
        "title": "AML Analyst",
        "location": "Poland",
        "description": "Remote role open to EU candidates.",
        "is_remote": True,
        "eu_hint": True,
    }

    assert scraper.keep_job(row) is True


def test_keep_job_rejects_us_only_role():
    row = {
        "title": "AML Analyst",
        "location": "United States",
        "description": "Remote role. US-only, must reside in the US.",
        "is_remote": True,
        "eu_hint": False,
    }

    assert scraper.keep_job(row) is False


def test_keep_job_rejects_off_topic_title():
    row = {
        "title": "Software Engineer",
        "location": "Poland",
        "description": "Remote role.",
        "is_remote": True,
        "eu_hint": True,
    }

    assert scraper.keep_job(row) is False


def test_parse_offers_extracts_one_job_per_offer_link():
    html = (
        '<div class="card">'
        '<a href="/job-offer/abc-123?utm_source=x">Senior Translator</a>'
        '<span class="company">ACME</span>'
        "</div>"
    )
    cfg = {"offer_re": re.compile(r"/job-offer/[\w-]+"), "remote_in_url": False}

    rows = scraper.parse_offers(html, "https://justjoin.it/", cfg, "JustJoin.it")

    assert len(rows) == 1
    assert rows[0]["job_url"] == "https://justjoin.it/job-offer/abc-123"
    assert rows[0]["title"] == "Senior Translator"


def test_write_csv_dry_run_dedupes_and_does_not_write(tmp_path, monkeypatch):
    monkeypatch.setattr(scraper, "CSV_FILE", tmp_path / "jobs.csv")
    job = {
        "found_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "title": "AML Analyst",
        "company": "ACME",
        "location": "Poland",
        "site": "Indeed",
        "date_posted": "2026-01-01",
        "job_url": "https://example.com/job/1?utm_source=a",
    }

    total = scraper.write_csv([job, dict(job)], dry_run=True)

    assert total == 1
    assert not (tmp_path / "jobs.csv").exists()


def test_seconds_until_next_run_is_positive():
    assert scraper.seconds_until_next_run() > 0


def test_recent_rows_drops_old_and_unparseable_rows():
    now = datetime.now()
    rows = [
        {"found_at": (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M")},
        {"found_at": (now - timedelta(days=10)).strftime("%Y-%m-%d %H:%M")},
        {"found_at": ""},
    ]

    assert len(scraper.recent_rows(rows, days=7)) == 1
