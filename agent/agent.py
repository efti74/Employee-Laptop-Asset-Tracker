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

INTERVAL_SECONDS = int(os.getenv("REPORT_INTERVAL_SECONDS", "10"))
DEFAULT_API_URL = os.getenv("API_BASE_URL") or os.getenv("PUBLIC_BASE_URL") or "https://asset-tracker-backend-tqx7.onrender.com"

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

                # If config points to localhost but .env provides an active remote URL, use remote URL
                env_url = (os.getenv("API_BASE_URL") or os.getenv("PUBLIC_BASE_URL") or "").rstrip("/")
                if env_url and ("127.0.0.1" in cfg["api_base_url"] or "localhost" in cfg["api_base_url"]) and ("127.0.0.1" not in env_url and "localhost" not in env_url):
                    logging.info("Overriding localhost API url with environment API URL: %s", env_url)
                    cfg["api_base_url"] = env_url

                logging.info("Loaded device configuration from: %s (API: %s)", p, cfg["api_base_url"])
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
            raise PermissionError(
                "Windows Location access is not allowed. "
                "Please enable Settings -> Privacy & security -> Location on this PC."
            )

        locator = Geolocator()
        locator.desired_accuracy = PositionAccuracy.HIGH
        locator.desired_accuracy_in_meters = 1

        pos = loop.run_until_complete(locator.get_geoposition_async())
        coord = pos.coordinate
        point = coord.point.position
        return {
            "latitude": float(point.latitude),
            "longitude": float(point.longitude),
            "accuracy_meters": float(coord.accuracy or 10.0),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        loop.close()


def get_windows_location():
    """Query coordinates directly from Windows Built-in Location Service."""
    if not WINSDK_AVAILABLE:
        raise RuntimeError("Windows Location SDK (winsdk) is not available on this machine.")
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_query_windows_geolocator_sync)
        return future.result(timeout=10.0)


async def get_location():
    """Exclusively obtain accurate location from the Windows Built-in Location Service."""
    win_loc = await asyncio.to_thread(get_windows_location)
    return win_loc


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
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


async def main():
    cfg = load_config()
    logging.info("==================================================")
    logging.info("     OrgAssetAgent - Real-Time Tracking Engine    ")
    logging.info("==================================================")
    logging.info("Device ID : %s", cfg["device_id"])
    logging.info("Hostname  : %s", socket.gethostname())
    logging.info("API URL   : %s", cfg["api_base_url"])
    logging.info("Interval  : Real-time sync every %s seconds", INTERVAL_SECONDS)
    logging.info("Press Ctrl+C to stop.")

    seq = 0
    while True:
        cycle_start = time.monotonic()
        seq += 1
        try:
            location = await get_location()
            t0 = time.monotonic()
            result = send_report(cfg, location)
            lat_ms = (time.monotonic() - t0) * 1000
            logging.info(
                "[Sync #%04d] SUCCESS -> Lat: %.6f, Lon: %.6f (±%.1fm) | Ping: %.0fms | Server Time: %s",
                seq,
                location["latitude"],
                location["longitude"],
                location["accuracy_meters"],
                lat_ms,
                result.get("received_at", "ok"),
            )
        except Exception as exc:
            logging.error("[Sync #%04d] Report cycle failed: %s", seq, exc)

        elapsed = time.monotonic() - cycle_start
        sleep_duration = max(0.5, INTERVAL_SECONDS - elapsed)
        await asyncio.sleep(sleep_duration)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Agent stopped by user.")
    except Exception as exc:
        logging.error("Agent startup failed: %s", exc)
        time.sleep(3)
        sys.exit(1)
