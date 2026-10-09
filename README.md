# Employee Laptop Asset Tracking System

A transparent asset-security system for **enrolled, company-owned Windows devices**. The visible Windows agent reports hostname, Windows-provided latitude/longitude, accuracy, and timestamps every five minutes to an authenticated HTTPS API. FastAPI stores reports in MongoDB Atlas. An authenticated Streamlit dashboard shows device status and Google Maps embeds.

## Security and privacy design

- Use only on company-owned devices with documented employee notice and approved enrollment.
- The agent runs visibly in a console; this starter project does **not** install persistence, hide itself, disable security tools, or attempt to evade removal.
- Device reports use a per-device bearer token. The backend stores only a SHA-256 hash of that token.
- Admin endpoints require a separate admin bearer token.
- Keep all secrets in environment variables or a protected device config file, never in source code or the EXE.
- Use HTTPS in production. Do not expose the API over plain HTTP on the public internet.
- Location depends on Windows Location Services and available provider signals. A powered-off/offline device cannot report; the dashboard shows its last report, not guaranteed live location.
- This is a starter implementation, not a substitute for endpoint management, legal review, access logging, backups, and production security testing.

## Project layout

- `backend/main.py` — FastAPI API and MongoDB integration
- `agent/agent.py` — Windows location-reporting agent
- `dashboard/app.py` — Streamlit admin dashboard
- `*.example` files — configuration templates; copy and fill them locally
- `requirements-*.txt` — dependencies

## 1. Configure MongoDB Atlas

1. Create a MongoDB Atlas cluster and database user with only the permissions this application needs.
2. Restrict Atlas network access to your API server's egress IP where possible. Avoid `0.0.0.0/0`.
3. Copy the connection URI into the backend environment as `MONGODB_URI`.
4. Do not put the URI in the agent or dashboard.

The app uses database `employee_asset_tracker` and collections `devices` and `location_reports`.

## 2. Run the backend

Use Python 3.11 on the API server.

Windows PowerShell:
```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
$env:MONGODB_URI = "mongodb+srv://..."
$env:ADMIN_TOKEN = "replace-with-a-long-random-secret"
$env:PUBLIC_BASE_URL = "https://your-api.example.com"
py -m uvicorn main:app --host 127.0.0.1 --port 8000
```

For local testing only, `http://127.0.0.1:8000` is fine. For production, put Uvicorn behind a reverse proxy or managed hosting that provides HTTPS. Do not publish a raw HTTP listener.

Generate a strong admin token, for example with:
```powershell
py -c "import secrets; print(secrets.token_urlsafe(48))"
```

`PUBLIC_BASE_URL` is used to show the agent API URL in enrollment responses. It should be the externally reachable **HTTPS** URL in production.

## 3. Enroll a device

The enrollment endpoint requires the admin token and creates a random device token. The raw device token is returned only once; copy it to the enrolled laptop's protected config file.

PowerShell example:
```powershell
$headers = @{ "Authorization" = "Bearer YOUR_ADMIN_TOKEN" }
$body = @{ hostname = "EMP-LAPTOP-014"; asset_tag = "ASSET-014" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "https://your-api.example.com/admin/enroll" -Headers $headers -ContentType "application/json" -Body $body
```

Save the returned `device_id` and `device_token` securely. If the token is lost, revoke/disable the device and enroll a replacement rather than logging or emailing the token.

## 4. Configure and run the agent

On the company-owned Windows laptop:

1. Enable **Settings → Privacy & security → Location → Location services**.
2. Review and enable the appropriate Windows location permissions for desktop apps.
3. Copy `agent/device_config.example.json` to:
   `%ProgramData%\OrgAssetTracker\device_config.json`
4. Fill in `api_base_url`, `device_id`, and `device_token` from enrollment. Set restrictive NTFS permissions so only SYSTEM/Administrators and the intended service account can read it. Do not commit it to Git.
5. Install agent requirements and run it visibly for testing:
```powershell
cd agent
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
py agent.py
```

The agent requests Windows location access and reports once immediately, then approximately every five minutes. It logs report success/failure in the console. A Windows desktop app may be unable to obtain a location if permissions/provider are unavailable; the agent reports the error instead of inventing coordinates.

## 5. Build the Windows EXE

On Windows, using a compatible Python version:
```powershell
cd agent
py -m pip install -r requirements.txt
py -m pip install pyinstaller
py -m PyInstaller --clean --onefile --name OrgAssetAgent agent.py
```

Output: `agent\dist\OrgAssetAgent.exe`

The EXE intentionally contains **no device token or API secret**. It reads `%ProgramData%\OrgAssetTracker\device_config.json` at runtime. Test with Windows Defender and your organization's endpoint controls; sign the executable before broad deployment. Do not add hidden persistence. If the organization needs a managed service, deploy it transparently through its endpoint-management platform with employee notice and an approved uninstall/revocation process.

## 6. Run the Streamlit dashboard

Set environment variables in the dashboard host:
- `API_BASE_URL=https://your-api.example.com`
- `ADMIN_TOKEN=the-same-admin-token`

Then:
```powershell
cd dashboard
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
py -m streamlit run app.py
```

Only authorized IT administrators should be able to reach the dashboard. Put it behind your organization's SSO/reverse proxy or private network in production. The starter app uses the admin API token; it does not implement enterprise SSO or per-admin role-based access control.

## 7. API endpoints

- `GET /health` — basic health check
- `POST /agent/report` — device-token authenticated report ingestion
- `POST /admin/enroll` — admin-only device enrollment
- `GET /admin/devices` — admin-only device list with latest report
- `GET /admin/reports?device_id=...&limit=100` — admin-only report history
- `POST /admin/devices/{device_id}/revoke` — admin-only token revocation

## Operational checklist

- Use HTTPS and strong secrets from a secret manager.
- Restrict Atlas network access and use least-privilege database credentials.
- Back up MongoDB; set a retention policy for location reports.
- Audit admin access and enrollment/revocation actions before production.
- Use a company asset tag and inventory record; hostnames alone are not unique.
- Treat location data as sensitive personal data and define access, purpose, and retention with HR/legal.
