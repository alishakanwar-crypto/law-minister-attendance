"""DDNS Updater — keeps a DuckDNS hostname pointed at the office's public IP.

This allows remote access to the NVR camera feed from anywhere,
even with MTNL broadband's dynamic IP.
"""

import logging
import threading
import time

logger = logging.getLogger("office_engine.ddns")

DUCKDNS_UPDATE_URL = "https://www.duckdns.org/update"
PUBLIC_IP_SERVICES = [
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
    "https://icanhazip.com",
]


def get_public_ip() -> str | None:
    """Get the current public IP address."""
    import urllib.request
    for url in PUBLIC_IP_SERVICES:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "LawMinisterDDNS/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                ip = resp.read().decode().strip()
                if ip and "." in ip:
                    return ip
        except Exception:
            continue
    return None


def update_duckdns(domain: str, token: str, ip: str | None = None) -> bool:
    """Update DuckDNS with the current IP. Returns True on success."""
    import urllib.request
    params = f"domains={domain}&token={token}&verbose=true"
    if ip:
        params += f"&ip={ip}"
    url = f"{DUCKDNS_UPDATE_URL}?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "LawMinisterDDNS/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = resp.read().decode().strip()
            return result.startswith("OK")
    except Exception as e:
        logger.error(f"DuckDNS update failed: {e}")
        return False


class DDNSUpdater:
    """Background DDNS updater thread."""

    def __init__(self, domain: str, token: str, interval: int = 300):
        self.domain = domain.replace(".duckdns.org", "").strip()
        self.token = token.strip()
        self.interval = interval
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self.current_ip: str | None = None
        self.last_update: str | None = None
        self.status: str = "Stopped"
        self.hostname = f"{self.domain}.duckdns.org"

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info(f"DDNS updater started for {self.hostname}")

    def stop(self):
        self._stop_event.set()
        self.status = "Stopped"
        logger.info("DDNS updater stopped")

    def _run_loop(self):
        self.status = "Starting..."
        while not self._stop_event.is_set():
            try:
                ip = get_public_ip()
                if ip:
                    if ip != self.current_ip:
                        logger.info(f"IP changed: {self.current_ip} -> {ip}")
                    success = update_duckdns(self.domain, self.token, ip)
                    if success:
                        self.current_ip = ip
                        from datetime import datetime, timezone, timedelta
                        ist = timezone(timedelta(hours=5, minutes=30))
                        self.last_update = datetime.now(ist).strftime("%d-%m-%Y %H:%M IST")
                        self.status = f"Active — {ip}"
                        logger.info(f"DDNS updated: {self.hostname} -> {ip}")
                    else:
                        self.status = "Update failed — check token"
                        logger.warning("DuckDNS update returned error")
                else:
                    self.status = "No internet"
                    logger.warning("Could not determine public IP")
            except Exception as e:
                self.status = f"Error: {e}"
                logger.error(f"DDNS update error: {e}")

            self._stop_event.wait(self.interval)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
