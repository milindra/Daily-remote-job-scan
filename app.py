import base64
import json
import os
from datetime import datetime
from email.message import EmailMessage
import smtplib

import requests
import streamlit as st

st.set_page_config(page_title="Remote Job Hunter", page_icon="🧭", layout="wide")

st.title("🧭 Remote Job Hunter")
st.caption("Daily remote-role discovery · shortlist · email drafts · approval before sending")

st.markdown("""
<style>
.block-container {padding-top: 1.4rem; max-width: 1200px;}
div[data-testid="stMetric"] {background: rgba(120,120,120,.08); padding: 14px; border-radius: 12px;}
.job-card {border: 1px solid rgba(128,128,128,.25); padding: 16px; border-radius: 12px; margin: 8px 0;}
.small-muted {color: #777; font-size: .9rem;}
</style>
""", unsafe_allow_html=True)

# Secrets expected in Streamlit Community Cloud -> App settings -> Secrets:
# GITHUB_TOKEN, GITHUB_REPO ("owner/repo"), GITHUB_BRANCH (optional)
# SMTP_USERNAME, SMTP_PASSWORD, MAIL_FROM, SMTP_HOST (optional), SMTP_PORT (optional)
def secret(name, default=""):
    try:
        return str(st.secrets.get(name, os.getenv(name, default)))
    except Exception:
        return os.getenv(name, default)

repo = secret("GITHUB_REPO")
token = secret("GITHUB_TOKEN")
branch = secret("GITHUB_BRANCH", "main")
data_path = "job_hunter_data/jobs.json"

def github_request(method, path, **kwargs):
    if not repo or not token:
        raise RuntimeError("Configure GITHUB_REPO and GITHUB_TOKEN in Streamlit Secrets.")
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    return requests.request(method, url, headers=headers, timeout=25, params={"ref": branch} if method == "GET" else None, **kwargs)

def load_jobs():
    r = github_request("GET", data_path)
    if r.status_code == 404:
        return {}, None
    r.raise_for_status()
    payload = r.json()
    content = base64.b64decode(payload["content"]).decode("utf-8")
    return json.loads(content), payload["sha"]

def save_jobs(jobs, sha):
    content = base64.b64encode(json.dumps(jobs, indent=2, ensure_ascii=False).encode()).decode()
    body = {"message": f"Update job statuses via dashboard ({datetime.utcnow().isoformat()}Z)",
            "content": content, "branch": branch}
    if sha:
        body["sha"] = sha
    r = github_request("PUT", data_path, json=body)
    r.raise_for_status()

def send_email(job, recipient, resume_bytes, resume_name):
    username = secret("SMTP_USERNAME")
    password = secret("SMTP_PASSWORD")
    sender = secret("MAIL_FROM", username)
    host = secret("SMTP_HOST", "smtp.gmail.com")
    port = int(secret("SMTP_PORT", "587"))
    if not username or not password or not sender:
        raise RuntimeError("Configure SMTP_USERNAME, SMTP_PASSWORD, and MAIL_FROM in Streamlit Secrets.")
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = job.get("email_subject") or f"Interest in {job['title']} at {job['company']}"
    msg.set_content(job.get("email_body", "Hello,\\n\\nI am interested in this role: " + job["url"]))
    msg.add_attachment(resume_bytes, maintype="application", subtype="pdf", filename=resume_name)
    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls()
        server.login(username, password)
        server.send_message(msg)

with st.sidebar:
    st.header("Search profile")
    st.write("**Experience:** 7+ years")
    st.write("**Core stack:** Go, Java, C/C++, AWS, microservices, gRPC, Temporal, Redis, SQL, WebSockets")
    st.write("**Focus:** Backend, platform, distributed systems, AI/voice infrastructure, Forward Deployed Engineer")
    st.link_button("Search LinkedIn jobs", "https://www.linkedin.com/jobs/search/?keywords=Senior%20Backend%20Engineer%20OR%20Distributed%20Systems%20OR%20AI%20Infrastructure&location=India&f_WT=2", use_container_width=True)
    st.caption("LinkedIn login-protected pages are not scraped. Use LinkedIn job alerts or authorized access.")

if not repo or not token:
    st.warning("Connect the dashboard to your private GitHub repository first.")
    st.markdown("""
    **Quick setup**
    1. Push this project to a **private GitHub repository**.
    2. Create a GitHub token with Contents read/write access to that repository.
    3. Deploy `app.py` on [Streamlit Community Cloud](https://share.streamlit.io/).
    4. Add `GITHUB_REPO`, `GITHUB_TOKEN`, `GITHUB_BRANCH`, `SMTP_USERNAME`, `SMTP_PASSWORD`, and `MAIL_FROM` under app Secrets.
    """)
    st.stop()

try:
    jobs, sha = load_jobs()
except Exception as e:
    st.error(f"Could not load job data from GitHub: {e}")
    st.stop()

all_jobs = list(jobs.values())
pending = [j for j in all_jobs if j.get("status", "pending") == "pending"]
sent = [j for j in all_jobs if j.get("status") == "sent"]
rejected = [j for j in all_jobs if j.get("status") == "rejected"]

m1, m2, m3, m4 = st.columns(4)
m1.metric("All matches", len(all_jobs))
m2.metric("Awaiting review", len(pending))
m3.metric("Sent", len(sent))
m4.metric("Rejected", len(rejected))

tab_jobs, tab_sent, tab_setup = st.tabs(["🔎 Review jobs", "✉️ Sent", "⚙️ Setup & notes"])
with tab_jobs:
    c1, c2 = st.columns([2, 1])
    with c1:
        search = st.text_input("Search title, company, skills", placeholder="e.g. Golang, voice AI, platform")
    with c2:
        minimum = st.selectbox("Minimum match score", ["All", "5+", "8+", "12+"], index=1)
    filtered = pending
    if search:
        filtered = [j for j in filtered if search.lower() in (j.get("title","") + " " + j.get("company","") + " " + j.get("description","")).lower()]
    if minimum != "All":
        cutoff = int(minimum[:-1])
        filtered = [j for j in filtered if int(j.get("score", 0)) >= cutoff]
    filtered.sort(key=lambda j: (int(j.get("score", 0)), j.get("found_at", "")), reverse=True)
    st.caption(f"Showing {len(filtered)} pending jobs. Daily scans are run by GitHub Actions.")
    if not filtered:
        st.info("No matching pending jobs yet. Run the GitHub Actions workflow manually or wait for its next scheduled run.")
    for job in filtered:
        with st.container(border=True):
            left, right = st.columns([4, 1])
            with left:
                st.subheader(f"{job.get('title','Role')} — {job.get('company','Company')}")
                st.write(f"**Match score:** {job.get('score', 0)} · **Source:** {job.get('source','')} · **Location:** {job.get('location','Not specified')}")
                st.write(f"**Published:** {job.get('published') or 'Not provided'}")
                st.link_button("Open job posting ↗", job["url"])
                with st.expander("Description / details"):
                    st.write(job.get("description") or "No description was provided by the source.")
            with right:
                st.write("")
                st.write("")
                action = st.radio("Review", ["Keep pending", "Reject", "Prepare email"], key=f"action_{job['id']}", label_visibility="collapsed")
            if action == "Reject":
                if st.button("Confirm reject", key=f"reject_{job['id']}"):
                    jobs[job["id"]]["status"] = "rejected"
                    save_jobs(jobs, sha)
                    st.success("Job rejected. Refresh the page to update the list.")
                    st.rerun()
            elif action == "Prepare email":
                st.markdown("**Email draft**")
                recipient = st.text_input("Verified recruiter / hiring email", key=f"to_{job['id']}", placeholder="name@company.com")
                subject = st.text_input("Subject", value=job.get("email_subject", f"Interest in {job['title']} at {job['company']}"), key=f"subject_{job['id']}")
                body = st.text_area("Message", value=job.get("email_body", ""), height=210, key=f"body_{job['id']}")
                resume = st.file_uploader("Attach resume PDF", type=["pdf"], key=f"resume_{job['id']}")
                st.warning("Nothing is sent until you press Send approved email below. Use only a verified recipient.")
                if st.button("Send approved email", type="primary", key=f"send_{job['id']}"):
                    if not recipient or "@" not in recipient:
                        st.error("Enter a verified recipient email.")
                    elif not resume:
                        st.error("Upload your resume PDF.")
                    else:
                        # Save current edited draft in the data store before sending.
                        job["email_subject"] = subject
                        job["email_body"] = body
                        try:
                            # Refresh SHA before writes to avoid overwriting concurrent workflow updates.
                            latest, latest_sha = load_jobs()
                            latest_job = latest.get(job["id"], job)
                            latest_job["email_subject"] = subject
                            latest_job["email_body"] = body
                            send_email(latest_job, recipient, resume.getvalue(), resume.name)
                            latest_job["status"] = "sent"
                            latest_job["email_to"] = recipient
                            latest_job["sent_at"] = datetime.utcnow().isoformat() + "Z"
                            latest[job["id"]] = latest_job
                            save_jobs(latest, latest_sha)
                            st.success("Email sent and status saved.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Send failed or status could not be saved: {e}")

with tab_sent:
    if not sent:
        st.info("No emails sent yet.")
    for job in sorted(sent, key=lambda j: j.get("sent_at", ""), reverse=True):
        with st.container(border=True):
            st.write(f"**{job.get('title')} — {job.get('company')}**")
            st.caption(f"To: {job.get('email_to','')} · Sent: {job.get('sent_at','')}")
            st.link_button("Open job posting", job["url"])

with tab_setup:
    st.markdown("""
    ### Hosting plan
    - **UI:** Streamlit Community Cloud (free).
    - **Daily backend:** GitHub Actions scheduled workflow (free allowance).
    - **Persistent job queue:** a JSON file in your private GitHub repository.
    - **Email:** Gmail SMTP with an App Password; no credentials are stored in source code.
    - **Resume:** uploaded from your phone when preparing an email; it is attached in memory and not committed to GitHub.

    ### Security
    Keep the repository private and use a fine-scoped GitHub token. Anyone who can open this dashboard may be able to see job records and send mail if the app is left public. Restrict app viewers where available; for stronger protection, add app-level authentication before sharing the URL.

    ### Limitations
    - Public job-board APIs may change, rate-limit, or return incomplete listings.
    - The scanner uses public job feeds and does not scrape LinkedIn login-protected pages.
    - Recruiter emails are not guessed; you must enter a verified address.
    - Streamlit app restarts do not erase jobs because the dashboard reads and writes the private GitHub repository.
    """)
