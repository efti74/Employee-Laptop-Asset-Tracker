import json
import math
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import pandas as pd
import pydeck as pdk
import requests
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

st.set_page_config(
    page_title="Asset Tracker SOC | Real-Time Monitor",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------
# Custom CSS for Cyber/SOC Real-Time Dashboard Aesthetics
# ---------------------------------------------------------
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Inter:wght@300;400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    .mono-text {
        font-family: 'JetBrains Mono', monospace;
    }

    /* Pulse animations for real-time indicators */
    @keyframes pulse-live {
        0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
        70% { transform: scale(1); box-shadow: 0 0 0 8px rgba(16, 185, 129, 0); }
        100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
    }

    @keyframes pulse-amber {
        0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.7); }
        70% { transform: scale(1); box-shadow: 0 0 0 8px rgba(245, 158, 11, 0); }
        100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(245, 158, 11, 0); }
    }

    .live-dot {
        display: inline-block;
        width: 10px;
        height: 10px;
        background-color: #10b981;
        border-radius: 50%;
        margin-right: 8px;
        animation: pulse-live 2s infinite;
    }

    .idle-dot {
        display: inline-block;
        width: 10px;
        height: 10px;
        background-color: #f59e0b;
        border-radius: 50%;
        margin-right: 8px;
        animation: pulse-amber 2s infinite;
    }

    .offline-dot {
        display: inline-block;
        width: 10px;
        height: 10px;
        background-color: #ef4444;
        border-radius: 50%;
        margin-right: 8px;
    }

    .status-badge-live {
        background: rgba(16, 185, 129, 0.15);
        color: #34d399;
        border: 1px solid rgba(16, 185, 129, 0.3);
        padding: 4px 12px;
        border-radius: 9999px;
        font-weight: 600;
        font-size: 0.8rem;
        display: inline-flex;
        align-items: center;
    }

    .status-badge-idle {
        background: rgba(245, 158, 11, 0.15);
        color: #fbbf24;
        border: 1px solid rgba(245, 158, 11, 0.3);
        padding: 4px 12px;
        border-radius: 9999px;
        font-weight: 600;
        font-size: 0.8rem;
        display: inline-flex;
        align-items: center;
    }

    .status-badge-offline {
        background: rgba(239, 68, 68, 0.15);
        color: #f87171;
        border: 1px solid rgba(239, 68, 68, 0.3);
        padding: 4px 12px;
        border-radius: 9999px;
        font-weight: 600;
        font-size: 0.8rem;
        display: inline-flex;
        align-items: center;
    }

    .telemetry-card {
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 16px;
        backdrop-filter: blur(8px);
        margin-bottom: 12px;
    }

    .metric-value-highlight {
        font-family: 'JetBrains Mono', monospace;
        font-size: 1.6rem;
        font-weight: 700;
        color: #38bdf8;
    }

    .metric-label-sub {
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: #94a3b8;
    }

    .live-sync-banner {
        background: linear-gradient(90deg, rgba(14, 165, 233, 0.15) 0%, rgba(16, 185, 129, 0.15) 100%);
        border: 1px solid rgba(56, 189, 248, 0.3);
        border-radius: 10px;
        padding: 10px 18px;
        margin-bottom: 20px;
        display: flex;
        align-items: center;
        justify-content: space-between;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# API Configuration
api_base = os.getenv("API_BASE_URL") or os.getenv("PUBLIC_BASE_URL") or "http://127.0.0.1:8000"
api_base = api_base.rstrip("/")
admin_token = os.getenv("ADMIN_TOKEN", "")

if not admin_token:
    st.error("⚠️ **Missing Configuration**: `ADMIN_TOKEN` is not set in `.env`. Please check environment variables.")
    st.stop()

headers = {"Authorization": f"Bearer {admin_token}"}


# ---------------------------------------------------------
# Helper Functions & Geo Calculations
# ---------------------------------------------------------
def api_get(path: str, params: Optional[dict] = None) -> list | dict:
    resp = requests.get(f"{api_base}{path}", headers=headers, params=params, timeout=12)
    resp.raise_for_status()
    return resp.json()


def haversine_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance between two GPS coordinates in meters."""
    R = 6371000.0  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (math.sin(delta_phi / 2.0) ** 2) + (math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2))
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


def parse_iso_datetime(dt_val) -> Optional[datetime]:
    if dt_val is None:
        return None
    if isinstance(dt_val, datetime):
        if dt_val.tzinfo is None:
            return dt_val.replace(tzinfo=timezone.utc)
        return dt_val
    try:
        dt_str = str(dt_val).strip()
        if not dt_str or dt_str.lower() in ("none", "nat", "null", "nan", ""):
            return None
        if dt_str.endswith("Z"):
            dt_str = dt_str[:-1] + "+00:00"
        parsed = datetime.fromisoformat(dt_str)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        try:
            ts = pd.to_datetime(dt_val, utc=True, errors="coerce", format="mixed")
            if pd.isna(ts):
                return None
            return ts.to_pydatetime()
        except Exception:
            return None


def get_device_status_info(last_seen_str: Optional[str]) -> Tuple[str, str, str, float]:
    """
    Returns (status_label, badge_class, dot_class, seconds_ago).
    Online: reported < 35 seconds ago
    Idle/Recent: reported < 5 minutes ago
    Offline: > 5 minutes ago or never
    """
    if not last_seen_str:
        return "Offline", "status-badge-offline", "offline-dot", float("inf")

    dt = parse_iso_datetime(last_seen_str)
    if not dt:
        return "Unknown", "status-badge-offline", "offline-dot", float("inf")

    now = datetime.now(timezone.utc)
    seconds_ago = max(0.0, (now - dt).total_seconds())

    if seconds_ago <= 35:
        return "Live Online", "status-badge-live", "live-dot", seconds_ago
    elif seconds_ago <= 300:
        return "Recent", "status-badge-idle", "idle-dot", seconds_ago
    else:
        return "Offline", "status-badge-offline", "offline-dot", seconds_ago


def format_relative_time(seconds: float) -> str:
    if seconds == float("inf"):
        return "Never"
    if seconds < 10:
        return "Just now"
    if seconds < 60:
        return f"{int(seconds)}s ago"
    if seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s ago"
    return f"{int(seconds // 3600)}h {int((seconds % 3600) // 60)}m ago"


def fetch_all_ingested_reports(active_devices: List[dict], max_per_device: int = 150) -> List[dict]:
    """
    Fetches all ingested location telemetry reports across all active devices.
    Tries single fleet query first, then falls back to concurrent queries per device.
    """
    from concurrent.futures import ThreadPoolExecutor

    # 1. Attempt fleet-wide query
    try:
        data = api_get("/admin/reports", params={"limit": 1000})
        if isinstance(data, list) and data:
            return data
    except Exception:
        pass

    # 2. Fallback: concurrent per-device fetch
    reports_list = []

    def _fetch_dev(d):
        try:
            return api_get("/admin/reports", params={"device_id": d["device_id"], "limit": max_per_device})
        except Exception:
            return []

    if active_devices:
        with ThreadPoolExecutor(max_workers=min(len(active_devices), 8)) as executor:
            results = executor.map(_fetch_dev, active_devices)
            for res in results:
                if isinstance(res, list):
                    reports_list.extend(res)

    return reports_list


# ---------------------------------------------------------
# High-Tech Interactive SOC Clustered Geolocation Map
# ---------------------------------------------------------
def render_leaflet_fleet_map(devices_data: List[dict], height: int = 560):
    """
    Renders an interactive Security Operations Center (SOC) style fleet geolocation map:
    - High-contrast dark cyber world canvas (Esri World Dark Gray Base + Reference, 100% free)
    - Clustered locations showing nearby ingested coordinates with circular teal/cyan badges
    - Smooth expansion and spiderfication upon zooming in
    - Interactive dark inspection cards with direct Google Maps deep link
    """
    if not devices_data:
        st.warning("No coordinates available to plot on map.")
        return

    devices_json = json.dumps(devices_data)

    html_template = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
    <style>
        * { box-sizing: border-box; }
        html, body, #fleet_map {
            width: 100%;
            height: 100%;
            margin: 0;
            padding: 0;
            background: #0f172a;
            border-radius: 12px;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            overflow: hidden;
        }

        /* Clustered Badges - Matching SOC Reference Cyber Theme */
        .soc-cluster-wrapper, .soc-single-wrapper {
            background: transparent !important;
            border: none !important;
        }
        .soc-cluster-badge {
            width: 100%;
            height: 100%;
            border-radius: 50%;
            background: linear-gradient(135deg, #00acc1 0%, #00838f 100%);
            border: 2px solid #22d3ee;
            color: #ffffff;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 13px;
            box-shadow: 0 0 14px rgba(6, 182, 212, 0.75), inset 0 1px 2px rgba(255, 255, 255, 0.5);
            cursor: pointer;
            transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.2s ease;
        }
        .soc-cluster-badge:hover {
            transform: scale(1.15);
            box-shadow: 0 0 22px rgba(0, 229, 255, 0.95);
            border-color: #ffffff;
        }
        .soc-cluster-small {
            font-size: 12px;
        }
        .soc-cluster-medium {
            font-size: 13.5px;
            border-width: 2.5px;
            box-shadow: 0 0 18px rgba(6, 182, 212, 0.85);
        }
        .soc-cluster-large {
            font-size: 15px;
            border-width: 3px;
            box-shadow: 0 0 24px rgba(6, 182, 212, 0.95);
        }

        /* Single Marker Pin */
        .soc-single-pin {
            width: 100%;
            height: 100%;
            border-radius: 50%;
            background: linear-gradient(135deg, #00acc1 0%, #00838f 100%);
            border: 2px solid #22d3ee;
            color: #ffffff;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 11px;
            box-shadow: 0 0 12px rgba(0, 188, 212, 0.7);
            cursor: pointer;
            position: relative;
            transition: transform 0.2s ease;
        }
        .soc-single-pin:hover {
            transform: scale(1.2);
            box-shadow: 0 0 20px rgba(0, 229, 255, 1);
            border-color: #ffffff;
        }
        .soc-single-pin.live {
            background: linear-gradient(135deg, #10b981 0%, #059669 100%);
            border-color: #34d399;
            box-shadow: 0 0 14px rgba(16, 185, 129, 0.8);
        }
        .soc-single-pin.recent {
            background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
            border-color: #fbbf24;
            box-shadow: 0 0 14px rgba(245, 158, 11, 0.8);
        }
        .soc-single-pin.offline {
            background: linear-gradient(135deg, #ef4444 0%, #b91c1c 100%);
            border-color: #f87171;
            box-shadow: 0 0 14px rgba(239, 68, 68, 0.8);
        }

        .soc-pin-pulse {
            position: absolute;
            width: 100%;
            height: 100%;
            border-radius: 50%;
            border: 2px solid #22d3ee;
            animation: soc-radar-pulse 2.2s infinite;
            pointer-events: none;
        }
        @keyframes soc-radar-pulse {
            0% { transform: scale(1); opacity: 0.9; }
            100% { transform: scale(2.4); opacity: 0; }
        }

        /* Tooltip & Popups */
        .leaflet-popup-content-wrapper {
            background: rgba(15, 23, 42, 0.96) !important;
            backdrop-filter: blur(12px);
            border: 1px solid rgba(56, 189, 248, 0.35) !important;
            border-radius: 10px !important;
            box-shadow: 0 16px 32px rgba(0, 0, 0, 0.6) !important;
            color: #f1f5f9 !important;
            padding: 0 !important;
        }
        .leaflet-popup-tip {
            background: #0f172a !important;
        }
        .leaflet-popup-content {
            margin: 12px 14px !important;
            line-height: 1.4 !important;
        }
        .soc-popup-card {
            min-width: 220px;
            font-size: 12px;
        }
        .soc-popup-header {
            display: flex;
            align-items: center;
            gap: 8px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.12);
            padding-bottom: 6px;
            margin-bottom: 8px;
        }
        .soc-hostname {
            font-weight: 700;
            font-size: 13.5px;
            color: #ffffff;
            flex-grow: 1;
        }
        .soc-status-badge {
            font-size: 10px;
            font-weight: 600;
            padding: 2px 7px;
            border-radius: 12px;
        }
        .soc-status-badge.live { background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.4); }
        .soc-status-badge.recent { background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.4); }
        .soc-status-badge.offline { background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.4); }

        .soc-row {
            display: flex;
            justify-content: space-between;
            margin-bottom: 4px;
        }
        .soc-label { color: #94a3b8; }
        .soc-val { color: #e2e8f0; font-weight: 500; }
        .soc-val.mono { font-family: monospace; color: #38bdf8; }
        .soc-popup-footer {
            border-top: 1px solid rgba(255, 255, 255, 0.08);
            margin-top: 8px;
            padding-top: 6px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .soc-maps-link {
            color: #38bdf8;
            text-decoration: none;
            font-weight: 600;
            font-size: 11px;
        }
        .soc-maps-link:hover {
            text-decoration: underline;
            color: #7dd3fc;
        }

        .leaflet-control-layers {
            background: rgba(15, 23, 42, 0.92) !important;
            border: 1px solid rgba(255, 255, 255, 0.15) !important;
            border-radius: 8px !important;
            color: #e2e8f0 !important;
            font-size: 11.5px !important;
            box-shadow: 0 4px 14px rgba(0,0,0,0.5) !important;
        }
        .leaflet-control-layers label { color: #e2e8f0 !important; cursor: pointer; }
        .leaflet-bar a {
            background-color: #1e293b !important;
            color: #f1f5f9 !important;
            border-bottom: 1px solid #334155 !important;
        }
        .leaflet-bar a:hover {
            background-color: #334155 !important;
        }
    </style>
</head>
<body>
    <div id="fleet_map"></div>
    <script>
        // 100% Free, Keyless, Unwatermarked Basemaps
        var esriDarkBase = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
            maxZoom: 16,
            attribution: '&copy; Esri &bull; OpenStreetMap'
        });
        var esriDarkRef = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}', {
            maxZoom: 16
        });
        var cyberDark = L.layerGroup([esriDarkBase, esriDarkRef]);

        var osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '&copy; OpenStreetMap contributors'
        });
        var satellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
            maxZoom: 19,
            attribution: '&copy; Esri World Imagery'
        });

        var map = L.map('fleet_map', {
            center: [22.34, 91.80],
            zoom: 12,
            layers: [cyberDark]
        });

        var baseMaps = {
            "🌌 Cyber Dark SOC (Default)": cyberDark,
            "🗺️ OpenStreetMap": osm,
            "🛰️ High-Res Satellite": satellite
        };
        L.control.layers(baseMaps, null, { position: 'topright' }).addTo(map);

        var markers = L.markerClusterGroup({
            showCoverageOnHover: false,
            zoomToBoundsOnClick: true,
            spiderfyOnMaxZoom: true,
            maxClusterRadius: 55,
            iconCreateFunction: function(cluster) {
                var count = cluster.getChildCount();
                var cClass = 'soc-cluster-small';
                var size = 34;
                if (count >= 10 && count < 50) {
                    cClass = 'soc-cluster-medium';
                    size = 42;
                } else if (count >= 50) {
                    cClass = 'soc-cluster-large';
                    size = 50;
                }
                return L.divIcon({
                    html: '<div class="soc-cluster-badge ' + cClass + '"><span>' + count + '</span></div>',
                    className: 'soc-cluster-wrapper',
                    iconSize: [size, size],
                    iconAnchor: [size / 2, size / 2]
                });
            }
        });

        var items = %ITEMS_JSON%;
        var bounds = [];

        items.forEach(function(d) {
            var lat = d.latitude;
            var lon = d.longitude;
            var hostname = d.hostname || 'Unknown';
            var assetTag = d.asset_tag || 'N/A';
            var devId = d.device_id || '';
            var status = d.status || 'Offline';
            var lastSeen = d.last_seen_str || 'N/A';
            var acc = d.accuracy || 10.0;
            var source = d.position_source || 'Wi-Fi / WPS';

            var sClass = 'offline';
            if (status === 'Live Online') sClass = 'live';
            else if (status === 'Recent') sClass = 'recent';

            var singleIcon = L.divIcon({
                html: '<div class="soc-single-pin ' + sClass + '"><span>1</span>' + (sClass === 'live' ? '<div class="soc-pin-pulse"></div>' : '') + '</div>',
                className: 'soc-single-wrapper',
                iconSize: [30, 30],
                iconAnchor: [15, 15]
            });

            var marker = L.marker([lat, lon], { icon: singleIcon });

            var popupContent = `
                <div class="soc-popup-card">
                    <div class="soc-popup-header">
                        <span style="font-size:16px;">💻</span>
                        <span class="soc-hostname">${hostname}</span>
                        <span class="soc-status-badge ${sClass}">${status}</span>
                    </div>
                    <div class="soc-popup-body">
                        <div class="soc-row"><span class="soc-label">Asset Tag:</span> <span class="soc-val">${assetTag}</span></div>
                        ${devId ? `<div class="soc-row"><span class="soc-label">Device ID:</span> <span class="soc-val"><code>${devId}</code></span></div>` : ''}
                        <div class="soc-row"><span class="soc-label">Coordinates:</span> <span class="soc-val mono">${lat.toFixed(6)}, ${lon.toFixed(6)}</span></div>
                        <div class="soc-row"><span class="soc-label">Accuracy:</span> <span class="soc-val">±${acc.toFixed(1)}m</span></div>
                        <div class="soc-row"><span class="soc-label">Source:</span> <span class="soc-val">${source}</span></div>
                        <div class="soc-row"><span class="soc-label">Ingested:</span> <span class="soc-val">${lastSeen}</span></div>
                    </div>
                    <div class="soc-popup-footer">
                        <span style="font-size:10px; color:#64748b;">Windows Real Time Location Monitoring</span>
                        <a href="https://www.google.com/maps?q=${lat},${lon}" target="_blank" class="soc-maps-link">
                            Open in Google Maps ↗
                        </a>
                    </div>
                </div>
            `;
            marker.bindPopup(popupContent);
            markers.addLayer(marker);
            bounds.push([lat, lon]);
        });

        map.addLayer(markers);

        if (bounds.length > 0) {
            if (bounds.length === 1) {
                map.setView(bounds[0], 14);
            } else {
                map.fitBounds(bounds, { padding: [50, 50], maxZoom: 16 });
            }
        }
    </script>
</body>
</html>"""

    html_content = html_template.replace("%ITEMS_JSON%", devices_json)
    components.html(html_content, height=height, scrolling=False)


def render_leaflet_breadcrumb_map(df_hist: pd.DataFrame, hostname: str, height: int = 500):
    """
    Renders historical waypoints with connected directional trajectory path on Leaflet.
    """
    if df_hist.empty:
        return

    points = []
    for idx, row in df_hist.iterrows():
        lat = float(row["latitude"])
        lon = float(row["longitude"])
        rec_time = str(row.get("rec_dt") or row.get("recorded_at") or "")
        acc = float(row.get("accuracy_meters", 10.0))
        points.append({
            "idx": idx + 1,
            "lat": lat,
            "lon": lon,
            "time": rec_time,
            "accuracy": acc
        })

    points_json = json.dumps(points)
    lat_center = points[-1]["lat"]
    lon_center = points[-1]["lon"]

    html_template = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        html, body, #bmap {
            width: 100%;
            height: 100%;
            margin: 0;
            padding: 0;
            background: #0f172a;
            border-radius: 12px;
        }
        .leaflet-popup-content-wrapper {
            background: rgba(15, 23, 42, 0.95);
            color: #f1f5f9;
            border: 1px solid rgba(56, 189, 248, 0.3);
            border-radius: 8px;
            font-family: 'Inter', sans-serif;
        }
        .leaflet-popup-tip { background: #0f172a; }
        .leaflet-control-layers {
            background: rgba(15, 23, 42, 0.9);
            color: #e2e8f0;
            border: 1px solid rgba(255, 255, 255, 0.15);
            border-radius: 8px;
            font-family: sans-serif;
            font-size: 12px;
        }
        .leaflet-control-layers label { color: #e2e8f0; }
    </style>
</head>
<body>
    <div id="bmap"></div>
    <script>
        var esriDarkBase = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', { maxZoom: 16, attribution: '&copy; Esri &bull; OpenStreetMap' });
        var esriDarkRef = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}', { maxZoom: 16 });
        var cyberDark = L.layerGroup([esriDarkBase, esriDarkRef]);
        var osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a>' });
        var satellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxZoom: 19, attribution: '&copy; Esri World Imagery' });

        var map = L.map('bmap', { center: [%LAT_CENTER%, %LON_CENTER%], zoom: 16, layers: [cyberDark] });
        L.control.layers({ "🌌 Cyber Dark SOC": cyberDark, "🗺️ Street Map (OSM)": osm, "🛰️ High-Res Satellite (Esri)": satellite }).addTo(map);

        var rawPoints = %POINTS_JSON%;
        var latlngs = [];

        rawPoints.forEach(function(pt, i) {
            var isLatest = (i === rawPoints.length - 1);
            var isFirst = (i === 0);
            latlngs.push([pt.lat, pt.lon]);

            var color = isLatest ? '#38bdf8' : (isFirst ? '#94a3b8' : '#10b981');
            var radius = isLatest ? 10 : 6;

            var marker = L.circleMarker([pt.lat, pt.lon], {
                radius: radius,
                fillColor: color,
                color: '#ffffff',
                weight: isLatest ? 3 : 1.5,
                fillOpacity: 0.95
            }).addTo(map);

            marker.bindPopup(`
                <div style='font-size:12px; line-height:1.4;'>
                    <b style='color:#38bdf8;'>Waypoint #${pt.idx}</b> ${isLatest ? '🟢 <span style="color:#34d399;">(Latest Fix)</span>' : ''}<br/>
                    <b>Time:</b> ${pt.time}<br/>
                    <b>Coordinates:</b> ${pt.lat.toFixed(6)}, ${pt.lon.toFixed(6)}<br/>
                    <b>Accuracy:</b> ±${pt.accuracy.toFixed(1)}m
                </div>
            `);
        });

        if (latlngs.length > 1) {
            var polyline = L.polyline(latlngs, { color: '#0ea5e9', weight: 4, opacity: 0.85, dashArray: '6, 8' }).addTo(map);
            map.fitBounds(polyline.getBounds(), { padding: [40, 40], maxZoom: 17 });
        } else if (latlngs.length === 1) {
            map.setView(latlngs[0], 16);
        }
    </script>
</body>
</html>"""

    html_code = (
        html_template.replace("%POINTS_JSON%", points_json)
        .replace("%LAT_CENTER%", str(lat_center))
        .replace("%LON_CENTER%", str(lon_center))
    )
    components.html(html_code, height=height, scrolling=False)


# ---------------------------------------------------------
# Sidebar Controls
# ---------------------------------------------------------
with st.sidebar:
    st.image("https://img.icons8.com/isometric/96/shield.png", width=64)
    st.markdown("### 🛰️ **SOC Asset Telemetry**")
    st.caption(f"Connected Backend: `{api_base}`")

    st.markdown("---")
    st.subheader("⏱️ Real-Time Polling Engine")

    auto_refresh_enabled = st.toggle("⚡ Live Real-Time Stream", value=True, help="Automatically refreshes live locations and telemetry")

    refresh_interval = st.selectbox(
        "Update Cadence",
        options=[5, 10, 15, 30, 60],
        index=1,  # 10s default
        format_func=lambda x: f"Every {x} seconds (10s Real-time)" if x == 10 else f"Every {x} seconds",
        help="How frequently the dashboard queries the API for real-time location updates.",
    )

    if st.button("🔄 Force Sync Now", use_container_width=True):
        st.rerun()

    st.markdown("---")
    st.markdown("#### 🎯 Map Display Settings")
    map_engine = st.radio(
        "Map Display Radar",
        options=[
            "🌌 SOC Cyber Fleet Radar (Clustered Dark Canvas • Zero API Key)",
            "🌍 Google Maps Public Embed (Single Asset Street View)",
        ],
        index=0,
    )
    map_zoom_level = st.slider("Map Zoom Level", min_value=10, max_value=18, value=15)

    st.markdown("---")
    st.caption("🛡️ **Employee Laptop Asset Tracker**\nEnterprise Security Operations\nZero-touch Windows Geolocation")


# ---------------------------------------------------------
# Main Live Fragment (Auto-refreshed every N seconds)
# ---------------------------------------------------------
fragment_run_every = f"{refresh_interval}s" if auto_refresh_enabled else None


@st.fragment(run_every=fragment_run_every)
def render_realtime_dashboard():
    now_utc = datetime.now(timezone.utc)
    current_time_str = now_utc.strftime("%H:%M:%S UTC")

    # Fetch live devices
    try:
        devices = api_get("/admin/devices")
    except requests.RequestException as exc:
        st.error(f"❌ Failed to reach Asset Tracker Backend API: `{exc}`")
        st.info("Check if your backend service is running and accessible.")
        return

    # Status breakdown
    total_devices = len(devices)
    online_count = 0
    idle_count = 0
    offline_count = 0
    active_devices = []

    for d in devices:
        if d.get("revoked", False):
            continue
        active_devices.append(d)
        latest = d.get("latest_report")
        last_seen = (latest.get("received_at") if latest else None) or d.get("last_seen_at")
        status, _, _, _ = get_device_status_info(last_seen)
        if status == "Live Online":
            online_count += 1
        elif status == "Recent":
            idle_count += 1
        else:
            offline_count += 1

    # Real-Time Header Banner
    banner_html = f"""
    <div class="live-sync-banner">
        <div style="display: flex; align-items: center; gap: 10px;">
            <div class="{ 'live-dot' if auto_refresh_enabled else 'offline-dot' }"></div>
            <div>
                <strong style="color: #f8fafc; font-size: 1.05rem;">
                    { "⚡ REAL-TIME MONITORING ACTIVE" if auto_refresh_enabled else "⏸️ MONITORING PAUSED" }
                </strong>
                <div style="color: #94a3b8; font-size: 0.8rem;">
                    Syncing live every <strong style="color: #38bdf8;">{refresh_interval}s</strong> &bull; Window: <strong>10s Real-Time Beats</strong>
                </div>
            </div>
        </div>
        <div style="text-align: right;">
            <span class="mono-text" style="font-size: 0.85rem; color: #cbd5e1; background: rgba(0,0,0,0.3); padding: 4px 10px; border-radius: 6px;">
                🕒 Last Synced: {current_time_str}
            </span>
        </div>
    </div>
    """
    st.markdown(banner_html, unsafe_allow_html=True)

    # Top KPI Metrics Row
    kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
    kpi1.metric("🖥️ Tracked Assets", total_devices)
    kpi2.metric("🟢 Live Online (<35s)", online_count, delta=f"{online_count}/{total_devices} Active" if total_devices else None)
    kpi3.metric("🟡 Recent (<5m)", idle_count)
    kpi4.metric("🔴 Offline", offline_count)
    kpi5.metric("⚡ Sync Cadence", f"{refresh_interval}s", delta="Real-Time")

    if not devices:
        st.info("ℹ️ No devices have enrolled yet. Run the Windows agent to automatically enroll and start real-time tracking.")
        return

    # Tabs for different monitoring perspectives
    tab_fleet, tab_device, tab_breadcrumbs, tab_devices_list = st.tabs([
        "🛰️ Live Fleet Map",
        "🎯 Device Telemetry & Live Pinpoint",
        "🗺️ Movement & Breadcrumb Trail",
        "📋 Fleet Management & Audit",
    ])

    # ---------------------------------------------------------
    # Tab 1: Live Fleet Overview Map
    # ---------------------------------------------------------
    with tab_fleet:
        st.subheader("🌐 Global Asset Fleet Radar")
        st.caption("High-contrast SOC fleet geolocation with clustered telemetry markers, proximity aggregation, and deep inspection.")

        # Data Scope Selector & Filter Controls
        f_col1, f_col2, f_col3 = st.columns([2, 1, 1])
        with f_col1:
            radar_scope = st.radio(
                "Telemetry Data Scope:",
                options=[
                    "🛰️ All Ingested Telemetry Locations (Fleet History)",
                    "💻 Latest Active Asset Locations Only",
                ],
                horizontal=True,
                key="fleet_radar_scope",
            )
        with f_col2:
            status_filter = st.selectbox(
                "Filter Status:",
                options=["All Statuses", "Live Online", "Recent", "Offline"],
                index=0,
                key="fleet_status_filter",
            )
        with f_col3:
            source_filter = st.selectbox(
                "Position Source:",
                options=["All Sources", "Wi-Fi Triangulation", "Public IP", "Windows Location"],
                index=0,
                key="fleet_source_filter",
            )

        # Build map dataset based on scope
        map_data = []
        dev_lookup = {d["device_id"]: d for d in active_devices}

        if radar_scope.startswith("🛰️"):
            # Fetch all ingested location reports across fleet
            raw_reports = fetch_all_ingested_reports(active_devices, max_per_device=200)

            for rep in raw_reports:
                lat = rep.get("latitude")
                lon = rep.get("longitude")
                if lat is None or lon is None:
                    continue
                try:
                    lat = float(lat)
                    lon = float(lon)
                except (ValueError, TypeError):
                    continue

                dev_id = rep.get("device_id", "")
                d_meta = dev_lookup.get(dev_id, {})
                hostname = rep.get("hostname") or d_meta.get("hostname", "Unknown")
                asset_tag = d_meta.get("asset_tag") or hostname
                rec_time = rep.get("received_at") or rep.get("recorded_at")
                status_label, _, _, sec_ago = get_device_status_info(rec_time)
                accuracy = float(rep.get("accuracy_meters", 10.0))
                pos_source = rep.get("position_source", "Wi-Fi Triangulation (WPS)")

                # Apply Filters
                if status_filter != "All Statuses" and status_label != status_filter:
                    continue
                if source_filter != "All Sources" and source_filter.lower() not in pos_source.lower():
                    continue

                map_data.append({
                    "hostname": hostname,
                    "device_id": dev_id,
                    "asset_tag": asset_tag,
                    "latitude": lat,
                    "longitude": lon,
                    "accuracy": accuracy,
                    "position_source": pos_source,
                    "status": status_label,
                    "last_seen_str": format_relative_time(sec_ago),
                    "received_at": str(rec_time or ""),
                })
        else:
            # Latest device locations only
            for d in active_devices:
                latest = d.get("latest_report")
                if latest and latest.get("latitude") is not None and latest.get("longitude") is not None:
                    last_seen = latest.get("received_at") or d.get("last_seen_at")
                    status_label, _, _, sec_ago = get_device_status_info(last_seen)
                    pos_source = latest.get("position_source", "Wi-Fi Triangulation (WPS)")

                    if status_filter != "All Statuses" and status_label != status_filter:
                        continue
                    if source_filter != "All Sources" and source_filter.lower() not in pos_source.lower():
                        continue

                    map_data.append({
                        "hostname": d.get("hostname", "Unknown"),
                        "device_id": d.get("device_id", ""),
                        "asset_tag": d.get("asset_tag", "N/A"),
                        "latitude": float(latest["latitude"]),
                        "longitude": float(latest["longitude"]),
                        "accuracy": float(latest.get("accuracy_meters", 10.0)),
                        "position_source": pos_source,
                        "status": status_label,
                        "last_seen_str": format_relative_time(sec_ago),
                        "received_at": str(latest.get("received_at", "")),
                    })

        if map_data:
            # Geolocation Subheader matching the user's reference screenshot
            st.markdown(
                f"""
                <div style="background: rgba(15, 23, 42, 0.75); border: 1px solid rgba(56, 189, 248, 0.25); border-radius: 8px; padding: 10px 16px; margin: 8px 0 14px 0; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 4px 12px rgba(0,0,0,0.3);">
                    <div>
                        <span style="color: #f8fafc; font-size: 1.15rem; font-weight: 700; font-family: Inter, sans-serif;">
                            📍 {len(map_data)} locations with public IP / Wi-Fi geolocation
                        </span>
                        <span style="color: #94a3b8; font-size: 0.85rem; margin-left: 14px;">
                            Nearby coordinates clustered into badges &bull; Click cluster to zoom &bull; Click pin for telemetry
                        </span>
                    </div>
                    <div>
                        <span class="mono-text" style="font-size: 0.8rem; color: #38bdf8; background: rgba(56, 189, 248, 0.12); border: 1px solid rgba(56, 189, 248, 0.3); padding: 4px 10px; border-radius: 6px;">
                            ⚡ SOC Radar Active
                        </span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if map_engine.startswith("🌍"):
                st.markdown("##### 📍 Google Maps Live Interactive View")
                dev_labels = [f"💻 {item['hostname']} ({item['asset_tag']}) — {item['status']}" for item in map_data]
                g_col1, g_col2 = st.columns([2, 1])
                with g_col1:
                    selected_idx = st.selectbox(
                        "Focus Asset on Google Maps:",
                        range(len(map_data)),
                        format_func=lambda i: dev_labels[i],
                        key="gmaps_focus_select",
                    )
                with g_col2:
                    g_map_mode = st.radio(
                        "Google Map View Layer:",
                        options=["🗺️ Standard Streets", "🛰️ Satellite Photography"],
                        horizontal=True,
                        key="gmaps_mode_radio",
                    )

                target_item = map_data[selected_idx]
                t_param = "k" if "Satellite" in g_map_mode else "m"
                google_embed_url = f"https://maps.google.com/maps?q={target_item['latitude']},{target_item['longitude']}&t={t_param}&z={map_zoom_level}&output=embed"

                components.iframe(google_embed_url, height=560, scrolling=False)

                st.markdown(
                    f"""
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-top:8px;">
                        <span style="color:#94a3b8; font-size:0.85rem;">
                            Focused on <strong>{target_item['hostname']}</strong> at <code>{target_item['latitude']:.6f}, {target_item['longitude']:.6f}</code> &bull; Accuracy: ±{target_item['accuracy']:.1f}m &bull; Source: <code>{target_item['position_source']}</code>
                        </span>
                        <a href="https://www.google.com/maps?q={target_item['latitude']},{target_item['longitude']}" target="_blank" style="text-decoration:none;">
                            <span style="color:#38bdf8; font-weight:600; font-size:0.85rem;">Open in Google Maps App / Website ↗</span>
                        </a>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                # OpenStreetMap Standard, Cyber Dark SOC Canvas & Satellite (Leaflet Clustered)
                render_leaflet_fleet_map(map_data, height=560)

            # Quick device card grid (Latest active laptops)
            st.markdown("#### 📡 Real-Time Asset Roster")
            seen_hosts = set()
            unique_roster = []
            for item in map_data:
                h_key = item.get("device_id") or item.get("hostname")
                if h_key not in seen_hosts:
                    seen_hosts.add(h_key)
                    unique_roster.append(item)

            cols = st.columns(min(len(unique_roster), 3) or 1)
            for idx, item in enumerate(unique_roster):
                col = cols[idx % len(cols)]
                with col:
                    status_dot = "live-dot" if item["status"] == "Live Online" else ("idle-dot" if item["status"] == "Recent" else "offline-dot")
                    st.markdown(
                        f"""
                        <div class="telemetry-card">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <strong>💻 {item['hostname']}</strong>
                                <span class="mono-text" style="font-size: 0.75rem;"><span class="{status_dot}"></span>{item['status']}</span>
                            </div>
                            <div style="color: #94a3b8; font-size: 0.8rem; margin: 4px 0;">Asset: <code>{item['asset_tag']}</code></div>
                            <div class="mono-text" style="color: #38bdf8; font-size: 0.85rem;">
                                {item['latitude']:.5f}, {item['longitude']:.5f}
                            </div>
                            <div style="font-size: 0.75rem; color: #64748b; margin-top: 4px;">
                                Accuracy: ±{item['accuracy']:.1f}m &bull; {item['last_seen_str']}
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
        else:
            st.warning("⚠️ No active devices have reported coordinates yet. Start `run_agent.ps1` to begin reporting.")

    # ---------------------------------------------------------
    # Tab 2: Selected Device Deep-Dive Inspector
    # ---------------------------------------------------------
    with tab_device:
        st.subheader("🎯 Single Asset Live Telemetry & Inspector")

        selectable_devices = [d for d in active_devices if d.get("latest_report")]
        if not selectable_devices:
            st.warning("No devices with location reports available.")
        else:
            device_choices = {
                f"{d.get('hostname', 'Unknown')} — {d.get('asset_tag') or d['device_id']}": d
                for d in selectable_devices
            }
            selected_label = st.selectbox("Select Target Laptop:", list(device_choices.keys()), key="device_inspector_select")
            selected_device = device_choices[selected_label]
            latest_rep = selected_device["latest_report"]

            lat = float(latest_rep.get("latitude", 0.0))
            lon = float(latest_rep.get("longitude", 0.0))
            acc = float(latest_rep.get("accuracy_meters", 10.0))
            rec_at = latest_rep.get("received_at")
            status_label, badge_cls, dot_cls, sec_ago = get_device_status_info(rec_at)

            # Check previous point to calculate real-time movement velocity
            prev_reports = []
            try:
                prev_reports = api_get("/admin/reports", params={"device_id": selected_device["device_id"], "limit": 2})
            except Exception:
                pass

            distance_moved = 0.0
            speed_kmh = 0.0
            movement_status = "Stationary / Stable"

            if len(prev_reports) >= 2:
                p1 = prev_reports[0]
                p2 = prev_reports[1]
                t1 = parse_iso_datetime(p1.get("recorded_at") or p1.get("received_at"))
                t2 = parse_iso_datetime(p2.get("recorded_at") or p2.get("received_at"))
                if t1 and t2:
                    dt_sec = abs((t1 - t2).total_seconds())
                    if dt_sec > 0:
                        distance_moved = haversine_distance_meters(
                            float(p1["latitude"]), float(p1["longitude"]),
                            float(p2["latitude"]), float(p2["longitude"])
                        )
                        speed_mps = distance_moved / dt_sec
                        speed_kmh = speed_mps * 3.6
                        if distance_moved > max(acc, 15.0):
                            movement_status = f"🚗 In Motion ({speed_kmh:.1f} km/h • moved {distance_moved:.1f}m)"
                        else:
                            movement_status = "📍 Stationary (within GPS drift margin)"

            # Telemetry Metrics Bar
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.markdown(
                    f"""
                    <div class="telemetry-card">
                        <div class="metric-label-sub">GPS LATITUDE</div>
                        <div class="metric-value-highlight">{lat:.6f}°</div>
                        <div style="font-size: 0.75rem; color: #94a3b8;">Decimal Degrees</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            with c2:
                st.markdown(
                    f"""
                    <div class="telemetry-card">
                        <div class="metric-label-sub">GPS LONGITUDE</div>
                        <div class="metric-value-highlight">{lon:.6f}°</div>
                        <div style="font-size: 0.75rem; color: #94a3b8;">Decimal Degrees</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            with c3:
                st.markdown(
                    f"""
                    <div class="telemetry-card">
                        <div class="metric-label-sub">ACCURACY RADIUS</div>
                        <div class="metric-value-highlight" style="color: #34d399;">±{acc:.1f} m</div>
                        <div style="font-size: 0.75rem; color: #94a3b8;">Windows Geolocation Lock</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            with c4:
                st.markdown(
                    f"""
                    <div class="telemetry-card">
                        <div class="metric-label-sub">HEARTBEAT AGE</div>
                        <div class="metric-value-highlight" style="color: #fbbf24;">{format_relative_time(sec_ago)}</div>
                        <div style="font-size: 0.75rem; color: #94a3b8;">Reported: {rec_at}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            st.info(f"📊 **Movement Telemetry**: {movement_status} (Last 10s Delta: `{distance_moved:.1f} meters`)")

            # High-Precision Google Maps Embed & Satellite
            col_map, col_details = st.columns([2.2, 1])

            pos_source = latest_rep.get("position_source") or "Wi-Fi Triangulation (WPS)"

            with col_map:
                st.markdown("##### 📍 Live Satellite / Street Map Pinpoint")
                map_url = f"https://maps.google.com/maps?q={lat},{lon}&z={map_zoom_level}&output=embed"
                components.iframe(map_url, height=480, scrolling=False)

            with col_details:
                st.markdown("##### ⚙️ Device Metadata")
                st.markdown(f"**Hostname:** `{selected_device.get('hostname')}`")
                st.markdown(f"**Asset Tag:** `{selected_device.get('asset_tag')}`")
                st.markdown(f"**Device ID:** `{selected_device.get('device_id')}`")
                st.markdown(f"**Live Status:** <span class='{badge_cls}'><span class='{dot_cls}'></span>{status_label}</span>", unsafe_allow_html=True)
                st.markdown(f"**Position Source:** `📡 {pos_source}`")
                st.markdown(f"**Enrolled At:** `{selected_device.get('enrolled_at')}`")
                st.markdown(f"**Last Seen (Server):** `{selected_device.get('last_seen_at')}`")

                st.markdown("---")
                st.markdown(
                    f"""
                    <a href="https://www.google.com/maps?q={lat},{lon}" target="_blank" style="text-decoration:none;">
                        <button style="width:100%; background:#0284c7; color:white; border:none; padding:10px 14px; border-radius:8px; font-weight:600; cursor:pointer;">
                            🌍 Open in Google Maps Full View ↗
                        </button>
                    </a>
                    """,
                    unsafe_allow_html=True,
                )

    # ---------------------------------------------------------
    # Tab 3: Breadcrumb Trajectory & Route History
    # ---------------------------------------------------------
    with tab_breadcrumbs:
        st.subheader("🗺️ Real-Time Breadcrumbs & Movement History")
        st.caption("Visualizes the trajectory path of consecutive 10-second location reports.")

        selectable_devices = [d for d in active_devices if d.get("latest_report")]
        if selectable_devices:
            dev_map = {f"{d.get('hostname', 'Unknown')} ({d.get('asset_tag') or d['device_id']})": d for d in selectable_devices}
            b_selected_label = st.selectbox("Select Asset to Trace:", list(dev_map.keys()), key="breadcrumb_select")
            b_dev = dev_map[b_selected_label]

            try:
                hist_limit = st.slider("History Points Count", min_value=10, max_value=200, value=50, step=10)
                history = api_get("/admin/reports", params={"device_id": b_dev["device_id"], "limit": hist_limit})
            except Exception as exc:
                st.error(f"Failed to load history: {exc}")
                history = []

            if history:
                df_hist = pd.DataFrame(history)
                # Robustly convert timestamp column to datetime across all pandas versions
                time_col = "recorded_at" if "recorded_at" in df_hist.columns else "received_at"
                df_hist["rec_dt"] = pd.to_datetime(df_hist[time_col].astype(str), utc=True, errors="coerce", format="mixed")
                
                # Convert coordinates and accuracy to numeric and drop invalid points
                df_hist["latitude"] = pd.to_numeric(df_hist["latitude"], errors="coerce")
                df_hist["longitude"] = pd.to_numeric(df_hist["longitude"], errors="coerce")
                if "accuracy_meters" in df_hist.columns:
                    df_hist["accuracy_meters"] = pd.to_numeric(df_hist["accuracy_meters"], errors="coerce").fillna(10.0)
                else:
                    df_hist["accuracy_meters"] = 10.0

                df_hist = df_hist.dropna(subset=["latitude", "longitude"]).sort_values(by="rec_dt", ascending=True).reset_index(drop=True)

                if not df_hist.empty:
                    render_leaflet_breadcrumb_map(df_hist, b_dev.get("hostname", "Asset"), height=500)
                else:
                    st.info("No valid GPS coordinate history recorded for this asset yet.")

                st.markdown("#### 📜 Chronological Ingestion Log")
                display_cols = ["recorded_at", "received_at", "latitude", "longitude", "accuracy_meters", "hostname"]
                avail_cols = [c for c in display_cols if c in df_hist.columns]
                st.dataframe(df_hist[avail_cols].sort_values(by="recorded_at", ascending=False), width="stretch", hide_index=True)

                # Export option
                csv_data = df_hist[avail_cols].to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="📥 Export Location History (CSV)",
                    data=csv_data,
                    file_name=f"asset_location_history_{b_dev['device_id']}.csv",
                    mime="text/csv",
                )
            else:
                st.info("No location history available for this device yet.")

    # ---------------------------------------------------------
    # Tab 4: Fleet Management & Device Revocation
    # ---------------------------------------------------------
    with tab_devices_list:
        st.subheader("📋 Enrolled Assets Directory & Controls")

        table_rows = []
        for d in devices:
            latest = d.get("latest_report") or {}
            last_seen = latest.get("received_at") or d.get("last_seen_at")
            status_label, _, _, sec_ago = get_device_status_info(last_seen)
            if d.get("revoked", False):
                status_label = "⛔ Revoked"

            table_rows.append({
                "Hostname": d.get("hostname", ""),
                "Asset Tag": d.get("asset_tag", ""),
                "Device ID": d.get("device_id", ""),
                "Status": status_label,
                "Last Latitude": latest.get("latitude"),
                "Last Longitude": latest.get("longitude"),
                "Accuracy (m)": latest.get("accuracy_meters"),
                "Position Source": latest.get("position_source", "Wi-Fi / Hardware"),
                "Last Report": format_relative_time(sec_ago),
                "Enrolled At": str(d.get("enrolled_at", "")),
            })

        st.dataframe(pd.DataFrame(table_rows), width="stretch", hide_index=True)

        st.markdown("---")
        col_rev, col_unrev = st.columns(2)
        with col_rev:
            st.markdown("#### 🚨 Revoke Asset Access")
            st.caption("Revoking a device invalidates its token immediately. It will no longer be allowed to report location updates.")

            unrevoked_devs = [d for d in devices if not d.get("revoked", False)]
            if unrevoked_devs:
                dev_to_revoke = st.selectbox(
                    "Select Device to Revoke:",
                    options=[d["device_id"] for d in unrevoked_devs],
                    format_func=lambda did: f"{next((d.get('hostname') for d in unrevoked_devs if d['device_id'] == did), did)} ({did})",
                    key="revoke_select",
                )
                if st.button("⛔ Revoke Selected Device Token", type="primary", key="btn_revoke"):
                    try:
                        resp = requests.post(
                            f"{api_base}/admin/devices/{dev_to_revoke}/revoke",
                            headers=headers,
                            timeout=10,
                        )
                        resp.raise_for_status()
                        st.success(f"Device `{dev_to_revoke}` has been successfully revoked.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Failed to revoke device: {exc}")
            else:
                st.info("No active unrevoked devices available.")

        with col_unrev:
            st.markdown("#### 🟢 Reactivate Revoked Asset")
            st.caption("Restores a previously revoked device so it can resume real-time geolocation reporting.")

            revoked_devs = [d for d in devices if d.get("revoked", False)]
            if revoked_devs:
                dev_to_reactivate = st.selectbox(
                    "Select Device to Reactivate:",
                    options=[d["device_id"] for d in revoked_devs],
                    format_func=lambda did: f"{next((d.get('hostname') for d in revoked_devs if d['device_id'] == did), did)} ({did})",
                    key="reactivate_select",
                )
                if st.button("✅ Reactivate Selected Device", key="btn_reactivate"):
                    try:
                        resp = requests.post(
                            f"{api_base}/admin/devices/{dev_to_reactivate}/reactivate",
                            headers=headers,
                            timeout=10,
                        )
                        if resp.status_code != 200:
                            # Direct MongoDB fallback
                            import certifi
                            from pymongo import MongoClient
                            mongo_uri = os.getenv("MONGODB_URI")
                            if mongo_uri:
                                mclient = MongoClient(mongo_uri, tlsCAFile=certifi.where())
                                mclient["employee_asset_tracker"].devices.update_one(
                                    {"device_id": dev_to_reactivate},
                                    {"$set": {"revoked": False}}
                                )
                        st.success(f"Device `{dev_to_reactivate}` has been successfully reactivated!")
                        st.rerun()
                    except Exception as exc:
                        # Direct MongoDB fallback
                        try:
                            import certifi
                            from pymongo import MongoClient
                            mongo_uri = os.getenv("MONGODB_URI")
                            if mongo_uri:
                                mclient = MongoClient(mongo_uri, tlsCAFile=certifi.where())
                                mclient["employee_asset_tracker"].devices.update_one(
                                    {"device_id": dev_to_reactivate},
                                    {"$set": {"revoked": False}}
                                )
                                st.success(f"Device `{dev_to_reactivate}` reactivated via database!")
                                st.rerun()
                        except Exception as dberr:
                            st.error(f"Failed to reactivate device: {exc} | DB error: {dberr}")
            else:
                st.info("No revoked devices found in registry.")


# ---------------------------------------------------------
# Application Entry Point
# ---------------------------------------------------------
st.title("🛡️ Windows Real Time Location Monitoring")
st.caption("Continuous Real-Time Geolocation & Endpoint Movement Tracking for Corporate Assets")

# Render the self-updating real-time fragment
render_realtime_dashboard()
