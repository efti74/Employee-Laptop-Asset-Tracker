import asyncio
import concurrent.futures
import json
import logging
import os
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

# Load local environment if present
load_dotenv()
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

try:
    from winsdk.windows.devices.geolocation import (
        Geolocator,
        GeolocationAccessStatus,
        PositionAccuracy,
    )
    WINSDK_AVAILABLE = True
except Exception:
    WINSDK_AVAILABLE = False

INTERVAL_SECONDS = 300
DEFAULT_API_URL = os.getenv("API_BASE_URL") or os.getenv("PUBLIC_BASE_URL") or "http://127.0.0.1:8000"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)


def get_possible_config_paths():
    """Return ordered list of paths to look for device_config.json."""
    paths = []
    # 1. Alongside the executable or running script
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        paths.append(exe_dir / "device_config.json")
    else:
        script_dir = Path(__file__).resolve().parent
        paths.append(script_dir / "device_config.json")

    # 2. Current working directory
    paths.append(Path.cwd() / "device_config.json")
    paths.append(Path.cwd() / "agent" / "device_config.json")

    # 3. Local AppData / ProgramData paths
    local_app_data = os.environ.get("LOCALAPPDATA", os.environ.get("APPDATA", ""))
    if local_app_data:
        paths.append(Path(local_app_data) / "OrgAssetTracker" / "device_config.json")

    program_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    paths.append(Path(program_data) / "OrgAssetTracker" / "device_config.json")

    seen = set()
    unique_paths = []
    for p in paths:
        try:
            normalized = str(p.resolve())
        except Exception:
            normalized = str(p)
        if normalized not in seen:
            seen.add(normalized)
            unique_paths.append(p)
    return unique_paths


def auto_enroll_device(api_url: str):
    """Automatically enroll the machine on the server without any user intervention."""
    hostname = socket.gethostname()
    api_url = api_url.rstrip("/")
    logging.info("Auto-registering device '%s' with server at %s...", hostname, api_url)

    payload = {
        "hostname": hostname,
        "asset_tag": hostname,
        "machine_id": f"{hostname}-{os.environ.get('USERNAME', 'user')}",
    }

    try:
        resp = requests.post(f"{api_url}/agent/auto-enroll", json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        cfg = {
            "api_base_url": api_url,
            "device_id": data["device_id"],
            "device_token": data["device_token"],
        }

        # Save config next to executable
        if getattr(sys, "frozen", False):
            save_path = Path(sys.executable).resolve().parent / "device_config.json"
        else:
            save_path = Path(__file__).resolve().parent / "device_config.json"

        try:
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with save_path.open("w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            logging.info("Configuration saved automatically to: %s", save_path)
        except Exception as save_err:
            logging.warning("Could not persist config to disk (%s), using in-memory token.", save_err)

        logging.info("Auto-enrollment SUCCESS! Assigned Device ID: %s", data["device_id"])
        return cfg
    except Exception as err:
        logging.error("Auto-enrollment failed: %s", err)
        raise


def load_config():
    # 1. Look for existing config
    for p in get_possible_config_paths():
        if p.exists() and p.is_file():
            try:
                with p.open("r", encoding="utf-8-sig") as f:
                    cfg = json.load(f)
                for key in ("api_base_url", "device_id", "device_token"):
                    if not cfg.get(key):
                        raise ValueError(f"Missing '{key}' in {p}")
                cfg["api_base_url"] = cfg["api_base_url"].rstrip("/")
                logging.info("Loaded device configuration from: %s", p)
                return cfg
            except Exception as e:
                logging.warning("Failed to parse config at %s: %s", p, e)

    # 2. No config found -> Perform 100% automatic zero-touch self-enrollment
    logging.info("No prior configuration found. Performing automatic device enrollment...")
    return auto_enroll_device(DEFAULT_API_URL)


def _query_windows_geolocator_sync():
    """Worker function executed in isolated thread to query Windows Built-in Location."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        access = loop.run_until_complete(Geolocator.request_access_async())
        if access != GeolocationAccessStatus.ALLOWED:
            return None

        locator = Geolocator()
        if hasattr(locator, "desired_accuracy"):
            locator.desired_accuracy = PositionAccuracy.HIGH
        locator.desired_accuracy_in_meters = 10

        # Give Windows up to 12 seconds to perform Wi-Fi / cell scan
        pos = loop.run_until_complete(locator.get_geoposition_async())
        coord = pos.coordinate
        point = coord.point.position
        return {
            "latitude": float(point.latitude),
            "longitude": float(point.longitude),
            "accuracy_meters": float(coord.accuracy or 50.0),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return None
    finally:
        loop.close()


def get_windows_location():
    """Query coordinates directly from Windows Built-in Location Service."""
    if not WINSDK_AVAILABLE:
        return None
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_query_windows_geolocator_sync)
            return future.result(timeout=14.0)
    except Exception:
        return None


def get_ip_location():
    """Fast fallback geolocation if Windows Location Service is toggled off."""
    endpoints = [
        ("http://ip-api.com/json", lambda r: (r.get("lat"), r.get("lon"))),
        ("https://ipwho.is/", lambda r: (r.get("latitude"), r.get("longitude"))),
        ("https://freeipapi.com/api/json", lambda r: (r.get("latitude"), r.get("longitude"))),
    ]

    for url, parser in endpoints:
        try:
            resp = requests.get(url, timeout=3.5, headers={"User-Agent": "OrgAssetAgent/1.0"})
            if resp.status_code == 200:
                data = resp.json()
                lat, lon = parser(data)
                if lat is not None and lon is not None:
                    return {
                        "latitude": float(lat),
                        "longitude": float(lon),
                        "accuracy_meters": 1000.0,
                        "recorded_at": datetime.now(timezone.utc).isoformat(),
                    }
        except Exception:
            continue
    raise RuntimeError("Could not determine device location.")


async def get_location():
    """Get location directly from Windows Built-in Location Service, with fallback if disabled."""
    # 1. Primary: Windows Built-in Location Service
    win_loc = await asyncio.to_thread(get_windows_location)
    if win_loc:
        logging.info("Captured location from Windows Built-in Location Service (Accuracy: ±%.1fm)", win_loc["accuracy_meters"])
        return win_loc

    # 2. Fallback if Windows Location is turned off
    logging.info("Windows Location Service unavailable; using network fallback...")
    ip_loc = await asyncio.to_thread(get_ip_location)
    logging.info("Captured location via network fallback (Lat: %.4f, Lon: %.4f)", ip_loc["latitude"], ip_loc["longitude"])
    return ip_loc


def send_report(cfg, location):
    hostname = socket.gethostname()
    payload = {
        "hostname": hostname,
        **location,
    }
    response = requests.post(
        f'{cfg["api_base_url"]}/agent/report',
        json=payload,
        headers={"Authorization": f'Bearer {cfg["device_token"]}'},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


async def main():
    cfg = load_config()
    logging.info("==========================================")
    logging.info("     OrgAssetAgent - Started Reporting     ")
    logging.info("==========================================")
    logging.info("Device ID : %s", cfg["device_id"])
    logging.info("Hostname  : %s", socket.gethostname())
    logging.info("API URL   : %s", cfg["api_base_url"])
    logging.info("Interval  : Every %s minutes", INTERVAL_SECONDS // 60)
    logging.info("Press Ctrl+C to stop.")

    while True:
        try:
            location = await get_location()
            result = send_report(cfg, location)
            logging.info(
                "Report SUCCESS -> Lat: %.6f, Lon: %.6f, Accuracy: %.1fm (Dashboard updated at %s)",
                location["latitude"],
                location["longitude"],
                location["accuracy_meters"],
                result.get("received_at", "ok"),
            )
        except Exception as exc:
            logging.error("Report failed: %s", exc)

        await asyncio.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Agent stopped by user.")
    except Exception as exc:
        logging.error("Agent startup failed: %s", exc)
        time.sleep(3)
        sys.exit(1)
