import os
from datetime import datetime, timezone

from dotenv import load_dotenv
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

# Load environment variables from .env or dashboard/.env if present
load_dotenv()
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

st.set_page_config(page_title="Employee Asset Tracker", page_icon="🛡️", layout="wide")
st.title("🛡️ Employee Laptop Asset Tracker")
st.caption("Authorized IT use only. Shows the latest location reported by enrolled company devices.")

api_base = os.getenv("API_BASE_URL", "").rstrip("/")
admin_token = os.getenv("ADMIN_TOKEN", "")

if not api_base or not admin_token:
    st.error("Set API_BASE_URL and ADMIN_TOKEN in the dashboard environment.")
    st.stop()

headers = {"Authorization": f"Bearer {admin_token}"}


def api_get(path, params=None):
    response = requests.get(
        f"{api_base}{path}", headers=headers, params=params, timeout=20
    )
    response.raise_for_status()
    return response.json()


try:
    devices = api_get("/admin/devices")
except requests.RequestException as exc:
    st.error(f"Could not load devices from the API: {exc}")
    st.stop()

active_devices = [d for d in devices if not d.get("revoked", False)]
col1, col2 = st.columns(2)
col1.metric("Registered devices", len(devices))
col2.metric("Active devices", len(active_devices))

if not devices:
    st.info("No devices enrolled yet. Use the admin enrollment endpoint to register a company device.")
    st.stop()

rows = []
for d in devices:
    latest = d.get("latest_report") or {}
    rows.append({
        "Hostname": d.get("hostname", ""),
        "Asset tag": d.get("asset_tag") or "",
        "Device ID": d.get("device_id", ""),
        "Status": "Revoked" if d.get("revoked") else ("Reported" if latest else "No report yet"),
        "Latitude": latest.get("latitude"),
        "Longitude": latest.get("longitude"),
        "Accuracy (m)": latest.get("accuracy_meters"),
        "Last received (UTC)": str(latest.get("received_at") or d.get("last_seen_at") or "Never"),
    })

st.subheader("Devices")
st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

selectable = [d for d in active_devices if d.get("latest_report")]
if not selectable:
    st.warning("No active device has reported a location yet.")
    st.stop()

labels = {
    f'{d.get("hostname", "Unknown")} — {d.get("asset_tag") or d["device_id"]}': d
    for d in selectable
}
selected_label = st.selectbox("Select a device to view", list(labels.keys()))
selected = labels[selected_label]
latest = selected["latest_report"]

lat = latest.get("latitude")
lon = latest.get("longitude")
if lat is None or lon is None:
    st.warning("The selected device has no valid coordinates.")
    st.stop()

m1, m2, m3 = st.columns(3)
m1.metric("Latitude", f"{lat:.6f}")
m2.metric("Longitude", f"{lon:.6f}")
m3.metric("Accuracy", f'{latest.get("accuracy_meters", float("nan")):.1f} m')

st.caption(
    f'Last report received: {latest.get("received_at", "unknown")} (server time). '
    "Coordinates can be stale if the device is offline or Windows returns a cached location."
)
map_url = f"https://maps.google.com/maps?q={lat},{lon}&z=16&output=embed"
components.iframe(map_url, height=480, scrolling=False)
st.markdown(f"[Open this location in Google Maps](https://www.google.com/maps?q={lat},{lon})")

with st.expander("Location history"):
    try:
        history = api_get(
            "/admin/reports",
            params={"device_id": selected["device_id"], "limit": 100},
        )
        if history:
            history_df = pd.DataFrame(history)
            st.dataframe(history_df, width="stretch", hide_index=True)
        else:
            st.info("No history reports available.")
    except requests.RequestException as exc:
        st.error(f"Could not load report history: {exc}")

st.caption("This dashboard does not continuously refresh itself. Reload the page to fetch the newest server data.")
