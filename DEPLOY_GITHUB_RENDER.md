# Deploy ProposalDesk publicly with GitHub + Render

This version supports PostgreSQL in production and SQLite for local testing.

## 1. Upload the project to GitHub
1. Sign in at https://github.com and create a repository named `proposaldsk`.
2. Upload the contents of this folder (not the ZIP itself).
3. Keep `app.py`, `requirements.txt`, `render.yaml`, `templates/`, and `static/` at the repository root.

## 2. Deploy on Render
1. Sign in at https://render.com using GitHub.
2. Select **New → Blueprint** and connect the `proposaldsk` repository.
3. Render reads `render.yaml` and provisions the web service and PostgreSQL database.
4. Review the plans and pricing before approving deployment.
5. Open the public `onrender.com` URL shown in the Render dashboard after deployment completes.

## Public permissions
Anyone with the URL can view, add, edit and delete clients and proposals. There is no login in this requested public-collaboration version. Anyone can therefore change or delete shared records.

## Persistence warning
PostgreSQL stores client, proposal and attachment metadata persistently. Uploaded file contents are currently saved in the app's `uploads/` folder, which is ephemeral on standard Render web services. For durable uploaded files, configure a persistent disk or object storage before relying on attachments. Back up database records and uploaded files separately.

## Local run
```bash
pip install -r requirements.txt
python app.py
```
Then open http://127.0.0.1:5000.

## Before sharing real client data
Use backups, avoid confidential information on an unrestricted public site, and consider adding user accounts or access controls if the project later handles sensitive data. Do not commit client records, `proposals.db`, uploads, or secrets to GitHub.

The Render plans in `render.yaml` may incur charges. Check current Render pricing before deployment.
