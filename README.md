# Remote Job Hunter — free-tier starter

Mobile-friendly job dashboard + daily scheduled scanner.

## Architecture

- **Frontend:** Streamlit Community Cloud.
- **Scheduled backend:** GitHub Actions (09:00 IST daily).
- **Persistence:** `job_hunter_data/jobs.json` in this private GitHub repository.
- **Email:** Gmail SMTP; email is sent only when you press **Send approved email**.
- **Resume:** upload a PDF from your phone at send time. The app attaches it in memory and does not commit it to GitHub.

## Deploy

1. Create a **private GitHub repository** and upload the contents of this folder.
2. In GitHub, open **Actions** and enable workflows if prompted. Run **Daily remote job scan → Run workflow** once to seed the job queue.
3. Open [Streamlit Community Cloud](https://share.streamlit.io/) and sign in with GitHub.
4. Create an app from your repository, branch `main`, file path `app.py`.
5. In Streamlit app settings → **Secrets**, add (TOML format):

```toml
GITHUB_REPO = "YOUR_GITHUB_USERNAME/remote-job-hunter"
GITHUB_BRANCH = "main"
GITHUB_TOKEN = "github_pat_REPLACE_ME"

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = "587"
SMTP_USERNAME = "your-gmail@gmail.com"
SMTP_PASSWORD = "your-16-character-google-app-password"
MAIL_FROM = "your-gmail@gmail.com"
```

Create a fine-grained GitHub token limited to this private repository with **Contents: Read and write**. Never put the token in source files or commit it.

For Gmail, enable 2-Step Verification and create a Google App Password. Do not use your normal account password.

## Use from mobile

Open your Streamlit app URL. Review matches, open a job listing, choose **Prepare email**, enter a verified recruiter email, edit the draft, upload your resume PDF, then press **Send approved email**.

## Important notes

- Free tiers and policies can change. GitHub Actions usage is subject to your plan's quota.
- Scheduled workflows can be delayed and do not guarantee exact start times.
- The public job feeds can be incomplete or rate-limited.
- This does not scrape LinkedIn login-protected pages. The dashboard includes a LinkedIn search shortcut; configure LinkedIn job alerts separately.
- This is a starter app, not a hardened multi-user service. Keep the repository private and restrict dashboard access. Do not share the app URL broadly until authentication is added.
- The workflow commits job listings to the private repository. Do not commit your resume, credentials, or secrets.
- GitHub API writes can conflict if a scan and dashboard update happen simultaneously; retry after refresh if a save fails.
