"""Bounded public Greenhouse GET sample, no applicants, contacts, credentials or CRM writes."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

ENDPOINT = "https://boards-api.greenhouse.io/v1/boards/cloudflare/jobs"


def capture(output):
    response = httpx.get(ENDPOINT, timeout=30, follow_redirects=False,
                         headers={"User-Agent": "Measurement-Portfolio-Research/1.0"})
    response.raise_for_status()
    data = response.json()
    selected = sorted([r for r in data["jobs"] if "data center" in r["title"].lower()], key=lambda r: r["id"])[:3]
    if not selected:
        raise ValueError("no_relevant_public_jobs")
    record = {"version": "public-jobs-snapshot/v1", "endpoint": ENDPOINT, "http_status": response.status_code,
              "fetched_at": datetime.now(timezone.utc).isoformat(), "response_sha256": hashlib.sha256(response.content).hexdigest(),
              "method": "one unauthenticated GET; selected exact job metadata only", "company": "Cloudflare",
              "crm_identity": "none; real company is not a synthetic CRM target", "published_at": None,
              "publication_date_limit": "API updated_at is not a publication date and does not establish a new hiring event.",
              "records": [{k: r[k] for k in ("id", "title", "updated_at", "absolute_url")} for r in selected],
              "permission_reference": "https://docs.greenhouse.io/job-board", "applicant_data": "not_requested"}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    print(json.dumps(capture(parser.parse_args().output), indent=2))
