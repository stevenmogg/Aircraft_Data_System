"""Wi-Fi / network status for the Configuration page."""

from __future__ import annotations

import json
import re
import subprocess
import urllib.request
from pathlib import Path
from typing import Any


WPA_CLIENT_CONFS = (
    Path("/etc/wpa_supplicant/wpa_supplicant.conf"),
    Path("/etc/wpa_supplicant/wpa_supplicant-wlan1.conf"),
)


def _run(cmd: list[str], timeout: float = 2.0) -> str:
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        return (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _sudo_run(cmd: list[str], timeout: float = 2.0) -> str:
    """Run via passwordless sudo (Stratux pi user)."""
    return _run(["sudo", "-n"] + cmd, timeout=timeout)


def _wpa_cli(iface: str, *args: str) -> str:
    return _sudo_run(["/sbin/wpa_cli", "-i", iface, *args])


def _wpa_status(iface: str) -> dict[str, Any]:
    out = _wpa_cli(iface, "status")
    info: dict[str, str] = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            info[k.strip()] = v.strip()
    return {
        "iface": iface,
        "state": info.get("wpa_state"),
        "ssid": info.get("ssid"),
        "bssid": info.get("bssid"),
        "freq": info.get("freq"),
        "ip_address": info.get("ip_address"),
    }


def _wpa_networks(iface: str) -> list[dict[str, Any]]:
    listed = _wpa_cli(iface, "list_networks")
    networks: list[dict[str, Any]] = []
    for line in listed.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        try:
            nid = int(parts[0])
        except ValueError:
            continue
        ssid = parts[1]
        flags = parts[3] if len(parts) > 3 else ""
        prio_raw = _wpa_cli(iface, "get_network", str(nid), "priority").strip()
        try:
            priority = int(prio_raw.splitlines()[-1])
        except ValueError:
            priority = None
        networks.append(
            {
                "id": nid,
                "ssid": ssid,
                "priority": priority,
                "flags": flags,
                "current": "[CURRENT]" in flags,
            }
        )
    networks.sort(key=lambda n: (-(n["priority"] or 0), n["id"]))
    return networks


def _parse_conf_networks(path: Path) -> list[dict[str, Any]]:
    text = ""
    if path.exists():
        try:
            text = path.read_text()
        except OSError:
            text = _sudo_run(["/bin/cat", str(path)])
    if not text:
        return []
    networks: list[dict[str, Any]] = []
    blocks = re.findall(r"network\s*=\s*\{(.*?)\}", text, re.S)
    for block in blocks:
        ssid_m = re.search(r'^\s*ssid="([^"]*)"', block, re.M)
        prio_m = re.search(r"^\s*priority\s*=\s*(\d+)", block, re.M)
        if not ssid_m:
            continue
        networks.append(
            {
                "ssid": ssid_m.group(1),
                "priority": int(prio_m.group(1)) if prio_m else None,
                "has_psk": bool(re.search(r"^\s*psk=", block, re.M)),
            }
        )
    networks.sort(key=lambda n: (-(n["priority"] or 0), n["ssid"]))
    return networks


def _stratux_wifi() -> dict[str, Any]:
    try:
        with urllib.request.urlopen("http://127.0.0.1/getSettings", timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": str(e)}

    clients = []
    for i, net in enumerate(data.get("WiFiClientNetworks") or []):
        clients.append(
            {
                "ssid": net.get("SSID"),
                "has_password": bool(net.get("Password")),
                "list_order": i + 1,
            }
        )
    return {
        "ok": True,
        "wifi_mode": data.get("WiFiMode"),
        "ap_ssid": data.get("WiFiSSID"),
        "ap_channel": data.get("WiFiChannel"),
        "ap_security_enabled": data.get("WiFiSecurityEnabled"),
        "wifi_country": data.get("WiFiCountry"),
        "internet_passthrough": data.get("WiFiInternetPassThroughEnabled"),
        "client_networks": clients,
    }


def wifi_configuration() -> dict[str, Any]:
    """Read-only Wi-Fi picture for Configuration page (no passwords)."""
    stratux = _stratux_wifi()
    ifaces = []
    for iface in ("wlan0", "wlan1", "ap0"):
        status = _wpa_status(iface) if iface != "ap0" else {
            "iface": iface,
            "state": None,
            "ssid": None,
        }
        # ap0 often has no wpa_cli client status in the same way
        if iface == "ap0":
            link = _run(["/sbin/ip", "-br", "link", "show", "ap0"])
            addr = _run(["/sbin/ip", "-4", "-br", "addr", "show", "ap0"])
            status = {
                "iface": "ap0",
                "role": "stratux_ap",
                "link": link.strip(),
                "addr": addr.strip(),
                "ssid": stratux.get("ap_ssid") if stratux.get("ok") else None,
            }
        else:
            status["role"] = "client"
            status["networks"] = _wpa_networks(iface)
            # IP from ip command if wpa_cli lacks it
            if not status.get("ip_address"):
                addr = _run(["/sbin/ip", "-4", "-br", "addr", "show", iface]).strip()
                status["addr"] = addr
        ifaces.append(status)

    conf_files = []
    for path in WPA_CLIENT_CONFS:
        conf_files.append(
            {
                "path": str(path),
                "exists": path.exists(),
                "networks": _parse_conf_networks(path),
            }
        )

    # Preferred order from config files (union by highest priority)
    preferred: dict[str, int] = {}
    for cf in conf_files:
        for n in cf.get("networks") or []:
            ssid = n.get("ssid")
            prio = n.get("priority")
            if not ssid or prio is None:
                continue
            if ssid not in preferred or prio > preferred[ssid]:
                preferred[ssid] = prio
    priority_order = [
        f"{ssid} ({prio})"
        for ssid, prio in sorted(preferred.items(), key=lambda x: -x[1])
    ]

    return {
        "ok": True,
        "note": "Passwords are never shown. Priority: higher number is preferred.",
        "priority_order": priority_order,
        "stratux": stratux,
        "interfaces": ifaces,
        "config_files": conf_files,
    }
