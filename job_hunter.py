#!/usr/bin/env python3
"""
Daily remote-job finder + human-approved outreach sender.

Sources:
  - Remotive public API
  - Remote OK public JSON feed
  - Arbeitnow public job-board API

LinkedIn:
  Do not scrape logged-in LinkedIn pages or bypass its access controls.
  Use LinkedIn Job Alerts delivered to an inbox, or add a compliant feed/API
  if you have authorized access. This script includes LinkedIn search links
  in its report so you can review matching roles there.

Commands:
  python job_hunter.py scan
  python job_hunter.py list
  python job_hunter.py show JOB_ID
  python job_hunter.py approve JOB_ID --to recruiter@example.com
  python job_hunter.py reject JOB_ID

The script NEVER sends automatically. You must run `approve` explicitly.
A job board usually does not expose a recruiter email; in that case, use the
application link and copy the prepared draft. Do not guess email addresses.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import smtplib
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("JOB_HUNTER_DATA_DIR", BASE_DIR / "job_hunter_data"))
JOBS_FILE = DATA_DIR / "jobs.json"
SENT_FILE = DATA_DIR / "sent.json"

# Edit these to tune the search. Keep locations explicit because some
# "remote" roles are restricted to particular countries/time zones.
ROLE_TERMS = [
    "senior backend engineer", "staff backend engineer", "software engineer",
    "distributed systems", "platform engineer", "infrastructure engineer",
    "AI infrastructure", "voice AI", "real time systems",
    "forward deployed engineer", "solutions engineer", "deployment engineer",
]
SKILLS = [
    "golang", "go", "java", "c++", "aws", "distributed systems",
    "microservices", "grpc", "temporal", "redis", "postgresql",
    "dynamodb", "websocket", "livekit", "llm", "speech", "voice ai",
    "sip", "telephony", "kubernetes",
]
NEGATIVE_TERMS = [
    "internship", "intern ", "junior", "entry level", "onsite only",
    "must be located in the united states", "us citizens only",
]
REMOTE_TERMS = ["remote", "work from home", "distributed", "anywhere"]

USER_PROFILE = (
    "7+ years of software/backend engineering experience. Go/Golang, Java, "
    "C/C++, AWS, microservices, distributed systems, gRPC, Temporal, Redis, "
    "DynamoDB, PostgreSQL/SQL, WebSockets, LiveKit, and real-time voice/AI "
    "infrastructure including LLM/STT/TTS and telephony. Target senior backend, "
    "platform, distributed systems, AI/voice infrastructure, and forward-deployed "
    "or solutions/deployment engineering roles. Prefer remote roles open to India "
    "or worldwide applicants."
)

LINKEDIN_SEARCH = (
    "https://www.linkedin.com/jobs/search/?"
    + urllib.parse.urlencode({
        "keywords": "Senior Backend Engineer OR Distributed Systems OR AI Infrastructure",
        "location": "India",
        "f_WT": "2",
    })
)

USER_AGENT = "RemoteJobHunter/1.0 (personal job search; contact: configure locally)"


def get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def strip_html(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value or "")
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def normalize_job(source: str, raw: dict[str, Any]) -> dict[str, Any] | None:
    title = str(raw.get("title") or raw.get("position") or "").strip()
    company = str(raw.get("company_name") or raw.get("company") or "").strip()
    url = str(raw.get("url") or raw.get("apply_url") or raw.get("job_url") or "").strip()
    if not title or not company or not url:
        return None

    description = strip_html(str(raw.get("description") or raw.get("description_text") or ""))
    location = str(raw.get("candidate_required_location") or raw.get("location") or "").strip()
    tags = raw.get("tags") or raw.get("job_type") or []
    if isinstance(tags, str):
        tags = [tags]
    text_blob = " ".join([title, company, location, description, " ".join(map(str, tags))]).lower()

    # Score relevance from title, skills, seniority, and remote eligibility.
    score = 0
    title_l = title.lower()
    for term in ROLE_TERMS:
        if term in title_l:
            score += 5
    for skill in SKILLS:
        if skill in text_blob:
            score += 1
    if any(term in text_blob for term in REMOTE_TERMS):
        score += 3
    if any(x in text_blob for x in ["senior", "staff", "principal", "lead", "sde iii"]):
        score += 3
    if any(x in text_blob for x in ["india", "asia", "apac", "worldwide", "anywhere"]):
        score += 2
    if any(term in text_blob for term in NEGATIVE_TERMS):
        score -= 8

    published = (
        raw.get("publication_date") or raw.get("date") or raw.get("created_at")
        or raw.get("createdAt") or ""
    )
    job_id = re.sub(r"[^a-zA-Z0-9]+", "-", f"{source}-{company}-{title}").strip("-").lower()
    return {
        "id": job_id,
        "source": source,
        "title": title,
        "company": company,
        "location": location or "Not specified",
        "url": url,
        "published": str(published),
        "score": score,
        "description": description[:7000],
        "status": "pending",
        "found_at": datetime.now(timezone.utc).isoformat(),
        "email_to": "",
        "email_subject": f"Application / interest: {title} at {company}",
        "email_body": make_email_body(title, company, url),
    }


def make_email_body(title: str, company: str, url: str) -> str:
    return f"""Hello Hiring Team,

I came across the {title} opportunity at {company} and would like to express my interest.

I have 7+ years of software engineering experience across backend services, distributed systems, cloud infrastructure, and real-time/AI systems. My hands-on stack includes Go, Java, AWS, microservices, gRPC, Temporal, Redis, SQL/PostgreSQL, WebSockets, and voice-AI infrastructure.

I would welcome the opportunity to discuss how my experience could contribute to your team. I have attached my resume for your consideration.

Role: {url}

Best regards,
Milindra Pratap Singh
"""


def fetch_remotive() -> list[dict[str, Any]]:
    # Multiple focused queries improve recall while dedupe happens after normalization.
    queries = ["golang", "backend", "distributed systems", "AI infrastructure", "voice AI"]
    results = []
    for query in queries:
        try:
            payload = get_json("https://remotive.com/api/remote-jobs?" + urllib.parse.urlencode({"search": query}))
            results.extend(payload.get("jobs", []))
            time.sleep(0.25)
        except Exception as exc:
            print(f"[WARN] Remotive query {query!r} failed: {exc}", file=sys.stderr)
    return [j for raw in results if (j := normalize_job("Remotive", {
        "title": raw.get("title"),
        "company_name": raw.get("company_name"),
        "url": raw.get("url"),
        "candidate_required_location": raw.get("candidate_required_location"),
        "description": raw.get("description"),
        "publication_date": raw.get("publication_date"),
        "tags": raw.get("tags"),
    }))]


def fetch_remoteok() -> list[dict[str, Any]]:
    try:
        payload = get_json("https://remoteok.com/api")
        if not isinstance(payload, list):
            return []
        return [j for raw in payload if isinstance(raw, dict) and (j := normalize_job("RemoteOK", {
            "title": raw.get("position"),
            "company": raw.get("company"),
            "url": raw.get("url"),
            "location": raw.get("location") or "Remote",
            "description": raw.get("description"),
            "date": raw.get("date"),
            "tags": raw.get("tags"),
        }))]
    except Exception as exc:
        print(f"[WARN] Remote OK fetch failed: {exc}", file=sys.stderr)
        return []


def fetch_arbeitnow() -> list[dict[str, Any]]:
    results = []
    # API is paginated; scan a few pages each day.
    for page in range(1, 4):
        try:
            payload = get_json("https://www.arbeitnow.com/api/job-board-api?" + urllib.parse.urlencode({"page": page}))
            rows = payload.get("data", []) if isinstance(payload, dict) else []
            results.extend(rows)
        except Exception as exc:
            print(f"[WARN] Arbeitnow page {page} failed: {exc}", file=sys.stderr)
            break
    return [j for raw in results if (j := normalize_job("Arbeitnow", {
        "title": raw.get("title"),
        "company_name": raw.get("company_name"),
        "url": raw.get("url"),
        "location": raw.get("location"),
        "description": raw.get("description"),
        "date": raw.get("created_at"),
        "tags": raw.get("tags"),
    }))]


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def save_json(path: Path, data: Any) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def scan(min_score: int = 5) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    existing = load_json(JOBS_FILE, {})
    found = fetch_remotive() + fetch_remoteok() + fetch_arbeitnow()
    added = 0
    for job in found:
        if job["score"] < min_score:
            continue
        key = job["id"]
        if key not in existing:
            existing[key] = job
            added += 1
    save_json(JOBS_FILE, existing)
    pending = [j for j in existing.values() if j.get("status") == "pending"]
    pending.sort(key=lambda j: (j.get("score", 0), j.get("found_at", "")), reverse=True)
    report = DATA_DIR / "daily_report.md"
    lines = [
        f"# Remote job report — {datetime.now().astimezone().strftime('%Y-%m-%d')}",
        "",
        f"New matches added today: **{added}**",
        f"Pending matches in queue: **{len(pending)}**",
        "",
        f"**LinkedIn search:** {LINKEDIN_SEARCH}",
        "",
        "## Best matches",
        "",
    ]
    for job in pending[:30]:
        lines += [
            f"### {job['title']} — {job['company']} (score {job['score']})",
            f"- Source: {job['source']}",
            f"- Location: {job['location']}",
            f"- Published: {job['published'] or 'Not provided'}",
            f"- Apply: {job['url']}",
            f"- Approval ID: `{job['id']}`",
            "",
        ]
    lines += [
        "## Approval workflow",
        "Review a job with `python job_hunter.py show JOB_ID`.",
        "Only after you approve it, run `python job_hunter.py approve JOB_ID --to recruiter@example.com`.",
        "The sender requires a configured resume path and SMTP credentials. No email is sent by `scan`.",
        "",
    ]
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"Scan complete. {added} new matches; {len(pending)} pending.")
    print(f"Report: {report}")
    print(f"LinkedIn review: {LINKEDIN_SEARCH}")


def list_jobs() -> None:
    jobs = load_json(JOBS_FILE, {})
    rows = sorted(jobs.values(), key=lambda j: (j.get("status") != "pending", -j.get("score", 0)))
    if not rows:
        print("No jobs yet. Run: python job_hunter.py scan")
        return
    for job in rows[:100]:
        print(f"[{job.get('status','pending'):8}] {job['id']} | {job['score']:>2} | {job['title']} — {job['company']} | {job['url']}")


def show_job(job_id: str) -> None:
    jobs = load_json(JOBS_FILE, {})
    job = jobs.get(job_id)
    if not job:
        print(f"Unknown job ID: {job_id}")
        sys.exit(1)
    print(f"{job['title']} — {job['company']}")
    print(f"Source: {job['source']} | Score: {job['score']} | Location: {job['location']}")
    print(f"URL: {job['url']}")
    print("\n--- Email draft ---")
    print(f"Subject: {job['email_subject']}\n")
    print(job["email_body"])
    print("\nNote: sending requires explicit `approve` command and a recipient email.")


def send_email(job: dict[str, Any], recipient: str) -> None:
    resume_path = Path(os.getenv("RESUME_PATH", "")).expanduser()
    if not resume_path.is_file():
        raise RuntimeError("Set RESUME_PATH to your PDF resume path in .env or environment.")
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME", "")
    password = os.getenv("SMTP_PASSWORD", "")
    sender = os.getenv("MAIL_FROM", username)
    if not username or not password or not sender:
        raise RuntimeError("Set SMTP_USERNAME, SMTP_PASSWORD, and MAIL_FROM first.")

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = job["email_subject"]
    msg.set_content(job["email_body"])
    data = resume_path.read_bytes()
    msg.add_attachment(data, maintype="application", subtype="pdf", filename=resume_path.name)

    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls()
        server.login(username, password)
        server.send_message(msg)


def approve(job_id: str, recipient: str) -> None:
    jobs = load_json(JOBS_FILE, {})
    sent = load_json(SENT_FILE, {})
    job = jobs.get(job_id)
    if not job:
        raise SystemExit(f"Unknown job ID: {job_id}")
    if job.get("status") == "sent" or job_id in sent:
        raise SystemExit("This job was already marked as sent; refusing duplicate send.")
    if not recipient or "@" not in recipient:
        raise SystemExit("Provide a real recipient with --to. Never guess recruiter emails.")
    print("You are about to send this email with your resume attached:")
    print(f"To: {recipient}")
    print(f"Subject: {job['email_subject']}")
    print(f"Role: {job['title']} — {job['company']}")
    print(f"Resume: {os.getenv('RESUME_PATH', '(RESUME_PATH not set)')}")
    confirm = input('Type SEND to confirm this exact email: ').strip()
    if confirm != "SEND":
        print("Cancelled; nothing sent.")
        return
    send_email(job, recipient)
    job["status"] = "sent"
    job["email_to"] = recipient
    job["sent_at"] = datetime.now(timezone.utc).isoformat()
    jobs[job_id] = job
    sent[job_id] = {"to": recipient, "sent_at": job["sent_at"]}
    save_json(JOBS_FILE, jobs)
    save_json(SENT_FILE, sent)
    print("Email sent and recorded.")


def reject(job_id: str) -> None:
    jobs = load_json(JOBS_FILE, {})
    if job_id not in jobs:
        raise SystemExit(f"Unknown job ID: {job_id}")
    jobs[job_id]["status"] = "rejected"
    save_json(JOBS_FILE, jobs)
    print("Marked rejected.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily remote job finder with approval-gated resume emails")
    sub = parser.add_subparsers(dest="command", required=True)
    p_scan = sub.add_parser("scan", help="Fetch jobs and generate a daily report")
    p_scan.add_argument("--min-score", type=int, default=5)
    sub.add_parser("list", help="List saved jobs")
    p_show = sub.add_parser("show", help="Show job details and email draft")
    p_show.add_argument("job_id")
    p_approve = sub.add_parser("approve", help="Send a resume email after interactive confirmation")
    p_approve.add_argument("job_id")
    p_approve.add_argument("--to", required=True, help="Verified recruiter/hiring email")
    p_reject = sub.add_parser("reject", help="Reject a saved job")
    p_reject.add_argument("job_id")
    args = parser.parse_args()

    if args.command == "scan":
        scan(args.min_score)
    elif args.command == "list":
        list_jobs()
    elif args.command == "show":
        show_job(args.job_id)
    elif args.command == "approve":
        approve(args.job_id, args.to)
    elif args.command == "reject":
        reject(args.job_id)


if __name__ == "__main__":
    main()
