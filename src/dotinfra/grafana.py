"""Fleet dashboard generator and a small Grafana HTTP API client.

The dashboard is data-driven: its ``host`` variable is filled by Prometheus
(``label_values(up{role="fleet"}, host)``), so adding or removing a host in the
CMDB only needs ``dotinfra monitoring targets`` — never a new dashboard.
GPU panels read NVIDIA DCGM exporter metrics (falling back to the
nvidia_smi_* names used by other exporters) and show "no GPU" when absent.
"""

from __future__ import annotations

import base64
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import DotinfraError

DATASOURCE_UID = "dotinfra-prometheus"
DASHBOARD_UID = "dotinfra-fleet"
EVENT_TAG = "dotinfra"

# Event types and their annotation colours (also used by events.py).
EVENT_TYPES = {
    "outage": "#F2495C",
    "incident": "#FF9830",
    "maintenance": "#5794F2",
    "change": "#B877D9",
    "observation": "#8AB8FF",
}

DS = {"type": "prometheus", "uid": "${datasource}"}
H = 'host=~"$host"'

GREEN, AMBER, RED = "green", "orange", "red"

# name -> (expr, unit, (warn, crit) or None, no-value text)
QUERIES: dict[str, tuple[str, str, tuple | None, str]] = {
    "Up": (
        f'min by(host)(up{{{H}}})', "none", None, "no data"),
    "CPU": (
        f'1 - avg by(host)(rate(node_cpu_seconds_total{{mode="idle",{H}}}[$__rate_interval]))',
        "percentunit", (0.7, 0.9), "—"),
    "RAM": (
        # Linux has MemAvailable; FreeBSD exposes size/free/inactive/cache.
        f'max by(host)(1 - node_memory_MemAvailable_bytes{{{H}}} / node_memory_MemTotal_bytes{{{H}}})'
        f' or max by(host)(1 - (node_memory_free_bytes{{{H}}} + node_memory_inactive_bytes{{{H}}}'
        f' + node_memory_cache_bytes{{{H}}}) / node_memory_size_bytes{{{H}}})',
        "percentunit", (0.75, 0.9), "—"),
    "Disk /": (
        f'max by(host)(1 - node_filesystem_avail_bytes{{mountpoint="/",fstype!~"tmpfs|ramfs",{H}}}'
        f' / node_filesystem_size_bytes{{mountpoint="/",fstype!~"tmpfs|ramfs",{H}}})',
        "percentunit", (0.8, 0.9), "—"),
    "CPU temp": (
        f'max by(host)(node_hwmon_temp_celsius{{{H}}} * on(host, chip) group_left(chip_name)'
        f' node_hwmon_chip_names{{chip_name=~"coretemp|k10temp|zenpower|cpu_thermal|soc_thermal|cpu-thermal",{H}}})'
        f' or max by(host)(node_thermal_zone_temp{{{H}}})'
        f' or max by(host)(node_cpu_temperature_celsius{{{H}}})',
        "celsius", (75, 90), "n/a"),
    "GPU": (
        f'max by(host)(DCGM_FI_DEV_GPU_UTIL{{{H}}}) / 100'
        f' or max by(host)(nvidia_smi_utilization_gpu_ratio{{{H}}})',
        "percentunit", (0.8, 0.95), "no GPU"),
    "VRAM": (
        f'max by(host)(DCGM_FI_DEV_FB_USED{{{H}}} / (DCGM_FI_DEV_FB_USED{{{H}}} + DCGM_FI_DEV_FB_FREE{{{H}}}))'
        f' or max by(host)(nvidia_smi_memory_used_bytes{{{H}}} / nvidia_smi_memory_total_bytes{{{H}}})',
        "percentunit", (0.8, 0.95), "no GPU"),
    "GPU temp": (
        f'max by(host)(DCGM_FI_DEV_GPU_TEMP{{{H}}})'
        f' or max by(host)(nvidia_smi_temperature_gpu{{{H}}})',
        "celsius", (75, 85), "no GPU"),
    "GPU power": (
        f'sum by(host)(DCGM_FI_DEV_POWER_USAGE{{{H}}})'
        f' or sum by(host)(nvidia_smi_power_draw_watts{{{H}}})',
        "watt", None, "no GPU"),
    "Load / core": (
        f'max by(host)(node_load1{{{H}}}) / count by(host)(node_cpu_seconds_total{{mode="idle",{H}}})',
        "percentunit", (0.7, 1.0), "—"),
    "Fans": (
        f'max by(host)(node_hwmon_fan_rpm{{{H}}} > 0)', "rotrpm", None, "n/a"),
    "Network": (
        f'sum by(host)(rate(node_network_receive_bytes_total{{device!~"lo|veth.*|docker.*|br-.*|virbr.*",{H}}}[$__rate_interval]))'
        f' + sum by(host)(rate(node_network_transmit_bytes_total{{device!~"lo|veth.*|docker.*|br-.*|virbr.*",{H}}}[$__rate_interval]))',
        "Bps", None, "—"),
    "Uptime": (
        f'max by(host)(time() - node_boot_time_seconds{{{H}}})', "s", None, "—"),
}

GAUGES = {"CPU", "RAM", "Disk /", "GPU", "VRAM"}

# Per-host row layout: (panel, width) per line; each line sums to 24.
ROW_LAYOUT = [
    (5, [("Up", 2), ("CPU", 3), ("RAM", 3), ("Disk /", 3), ("CPU temp", 2),
         ("GPU", 3), ("VRAM", 3), ("GPU temp", 2), ("GPU power", 3)]),
    (4, [("Load / core", 6), ("Fans", 6), ("Network", 6), ("Uptime", 6)]),
]

COMPARE = [
    ("CPU utilisation", "CPU"), ("RAM used", "RAM"), ("CPU temperature", "CPU temp"),
    ("GPU utilisation", "GPU"), ("GPU temperature", "GPU temp"), ("VRAM used", "VRAM"),
    ("GPU power", "GPU power"), ("Load per core", "Load / core"), ("Network rx+tx", "Network"),
]


def _thresholds(steps) -> dict:
    if not steps:
        return {"mode": "absolute", "steps": [{"color": "text", "value": None}]}
    return {"mode": "absolute", "steps": [
        {"color": GREEN, "value": None},
        {"color": AMBER, "value": steps[0]},
        {"color": RED, "value": steps[1]},
    ]}


def _target(expr: str, ref: str = "A", legend: str = "{{host}}") -> dict:
    return {"refId": ref, "datasource": DS, "expr": expr, "legendFormat": legend}


def _field_defaults(unit: str, steps, no_value: str) -> dict:
    d = {"unit": unit, "thresholds": _thresholds(steps), "color": {"mode": "thresholds"},
         "noValue": no_value}
    if unit == "percentunit":
        d.update({"min": 0, "max": 1, "decimals": 0})
    elif unit in ("celsius", "watt", "rotrpm"):
        d["decimals"] = 0
    return d


def _host_panel(pid: int, name: str, x: int, y: int, w: int, h: int) -> dict:
    expr, unit, steps, no_value = QUERIES[name]
    defaults = _field_defaults(unit, steps, no_value)
    if name == "Up":
        defaults["mappings"] = [{"type": "value", "options": {
            "0": {"text": "DOWN", "color": RED, "index": 0},
            "1": {"text": "UP", "color": GREEN, "index": 1}}}]
        defaults["thresholds"] = {"mode": "absolute", "steps": [
            {"color": RED, "value": None}, {"color": GREEN, "value": 1}]}
    if name in GAUGES:
        panel = {"type": "gauge", "options": {
            "showThresholdMarkers": True, "showThresholdLabels": False,
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}}}
    else:
        panel = {"type": "stat", "options": {
            "graphMode": "none" if name == "Up" else "area", "colorMode": "value",
            "textMode": "value", "justifyMode": "center",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}}}
    panel.update({
        "id": pid, "title": name, "datasource": DS,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [_target(expr)],
        "fieldConfig": {"defaults": defaults, "overrides": []},
    })
    return panel


def _timeseries(pid: int, title: str, name: str, x: int, y: int, w: int = 8, h: int = 8) -> dict:
    expr, unit, _steps, no_value = QUERIES[name]
    defaults = {"unit": unit, "noValue": no_value, "min": 0,
                "custom": {"lineWidth": 2, "fillOpacity": 8, "gradientMode": "opacity",
                           "showPoints": "never", "spanNulls": True}}
    if unit == "percentunit":
        defaults["max"] = 1
    return {
        "type": "timeseries", "id": pid, "title": title, "datasource": DS,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [_target(expr)],
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
    }


def _annotations() -> dict:
    items = [{
        "builtIn": 1, "name": "Annotations & Alerts", "enable": True, "hide": True,
        "iconColor": "rgba(0, 211, 255, 1)", "type": "dashboard",
        "datasource": {"type": "grafana", "uid": "-- Grafana --"},
        "target": {"limit": 100, "matchAny": False, "tags": [], "type": "dashboard"},
    }]
    for etype, colour in EVENT_TYPES.items():
        items.append({
            "name": f"Events: {etype}", "enable": True, "hide": False, "iconColor": colour,
            "datasource": {"type": "grafana", "uid": "-- Grafana --"},
            "target": {"type": "tags", "tags": [EVENT_TAG, f"type:{etype}"],
                       "matchAny": False, "limit": 500},
        })
    return {"list": items}


def build_fleet_dashboard(name: str = "home", datasource_uid: str = DATASOURCE_UID) -> dict:
    """Return the fleet dashboard as a dict (Grafana dashboard JSON model)."""
    panels: list[dict] = []
    pid = 1
    panels.append({"type": "row", "title": "$host", "id": pid, "collapsed": False,
                   "repeat": "host", "gridPos": {"h": 1, "w": 24, "x": 0, "y": 0}, "panels": []})
    pid += 1
    y = 1
    for height, line in ROW_LAYOUT:
        x = 0
        for panel_name, width in line:
            panels.append(_host_panel(pid, panel_name, x, y, width, height))
            pid += 1
            x += width
        y += height

    panels.append({"type": "row", "title": "Compare hosts", "id": pid, "collapsed": False,
                   "gridPos": {"h": 1, "w": 24, "x": 0, "y": y}, "panels": []})
    pid += 1
    y += 1
    for i, (title, key) in enumerate(COMPARE):
        panels.append(_timeseries(pid, title, key, (i % 3) * 8, y + (i // 3) * 8))
        pid += 1
    y += ((len(COMPARE) + 2) // 3) * 8

    panels.append({"type": "row", "title": "All scrape targets", "id": pid, "collapsed": False,
                   "gridPos": {"h": 1, "w": 24, "x": 0, "y": y}, "panels": []})
    pid += 1
    y += 1
    panels.append({
        "type": "state-timeline", "id": pid, "title": "Target up/down (fleet and infra)",
        "datasource": DS, "gridPos": {"h": 10, "w": 24, "x": 0, "y": y},
        "targets": [_target('max by(host, job)(up{host!=""})', legend="{{host}} {{job}}")],
        "fieldConfig": {"defaults": {
            "color": {"mode": "thresholds"},
            "thresholds": {"mode": "absolute", "steps": [
                {"color": RED, "value": None}, {"color": GREEN, "value": 1}]},
            "mappings": [{"type": "value", "options": {
                "0": {"text": "down", "color": RED, "index": 0},
                "1": {"text": "up", "color": GREEN, "index": 1}}}],
        }, "overrides": []},
        "options": {"showValue": "never", "mergeValues": True, "rowHeight": 0.8,
                    "legend": {"showLegend": False}},
    })

    return {
        "uid": DASHBOARD_UID,
        "title": f"Fleet Overview — {name}",
        "description": (
            "Generated by dotinfra (`dotinfra grafana dashboard`). One row per host tagged "
            "`fleet` in the CMDB; hosts come from Prometheus labels, so the dashboard never "
            "needs regenerating when hosts change. Annotations are dotinfra events."),
        "tags": ["dotinfra", "fleet"],
        "timezone": "browser",
        "refresh": "30s",
        "time": {"from": "now-6h", "to": "now"},
        "graphTooltip": 1,
        "schemaVersion": 39,
        "editable": True,
        "panels": panels,
        "annotations": _annotations(),
        "templating": {"list": [
            {
                "name": "datasource", "label": "Data source", "type": "datasource",
                "query": "prometheus", "hide": 0, "refresh": 1, "regex": "",
                "current": {"text": "Prometheus", "value": datasource_uid},
            },
            {
                "name": "host", "label": "Host", "type": "query", "datasource": DS,
                "query": {"query": 'label_values(up{role="fleet"}, host)', "refId": "hosts"},
                "definition": 'label_values(up{role="fleet"}, host)',
                "refresh": 2, "sort": 1, "multi": True, "includeAll": True,
                "current": {"text": ["All"], "value": ["$__all"]}, "options": [],
            },
        ]},
        "links": [],
    }


def dashboard_json(dashboard: dict) -> str:
    return json.dumps(dashboard, indent=2, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------- API client

class GrafanaError(DotinfraError):
    """A Grafana API or credential problem; the CLI prints it without a traceback."""


class GrafanaClient:
    """Minimal Grafana HTTP API client (stdlib urllib)."""

    def __init__(self, url: str, *, user: str | None = None, password: str | None = None,
                 token: str | None = None, timeout: float = 15.0):
        self.url = url.rstrip("/")
        self.timeout = timeout
        if token:
            self.auth = f"Bearer {token}"
        elif user is not None and password is not None:
            cred = base64.b64encode(f"{user}:{password}".encode()).decode()
            self.auth = f"Basic {cred}"
        else:
            self.auth = None

    def request(self, method: str, path: str, data=None, params: dict | None = None):
        url = self.url + path
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Accept", "application/json")
        if body is not None:
            req.add_header("Content-Type", "application/json")
        if self.auth:
            req.add_header("Authorization", self.auth)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:300]
            except Exception:  # noqa: BLE001 - best effort
                pass
            finally:
                e.close()
            raise GrafanaError(f"Grafana API {method} {path} -> HTTP {e.code}: {detail}") from None
        except urllib.error.URLError as e:
            raise GrafanaError(f"cannot reach Grafana at {self.url}: {e.reason}") from None
        return json.loads(raw) if raw.strip() else {}

    # -- dashboards

    def ensure_folder(self, title: str, uid: str | None = None) -> str:
        for folder in self.request("GET", "/api/folders") or []:
            if folder.get("title") == title:
                return folder["uid"]
        payload = {"title": title}
        if uid:
            payload["uid"] = uid
        return self.request("POST", "/api/folders", payload)["uid"]

    def push_dashboard(self, dashboard: dict, *, folder_uid: str | None = None,
                       message: str = "dotinfra: update fleet dashboard") -> dict:
        dash = dict(dashboard)
        dash.pop("id", None)  # let Grafana match by uid
        payload = {"dashboard": dash, "overwrite": True, "message": message}
        if folder_uid:
            payload["folderUid"] = folder_uid
        return self.request("POST", "/api/dashboards/db", payload)

    def set_home_dashboard(self, uid: str) -> dict:
        return self.request("PATCH", "/api/org/preferences", {"homeDashboardUID": uid})


def client_from_context(ctx) -> GrafanaClient:
    """Build a client from ``[monitoring]`` config; credentials come from the vault.

    If ``monitoring.grafana_token_key`` is set, that vault key holds a service
    account token (Bearer auth). Otherwise basic auth with ``grafana_user`` and
    the password stored under ``grafana_password_key``.
    """
    get = ctx.config.get
    url = get("monitoring", "grafana_url", "http://localhost:3000")
    token_key = get("monitoring", "grafana_token_key", "") or ""
    key = token_key or get("monitoring", "grafana_password_key", "grafana_password")
    try:
        secret = ctx.secret(key)
    except DotinfraError as e:  # vault unreadable, key missing, age not installed, ...
        raise GrafanaError(f"cannot read Grafana credentials from vault key '{key}': {e}\n"
                           f"hint: dotinfra vault set {key}") from None
    if token_key:
        return GrafanaClient(url, token=secret)
    return GrafanaClient(url, user=get("monitoring", "grafana_user", "admin"), password=secret)


# ---------------------------------------------------------------- CLI

def _cmd_dashboard(args) -> int:
    from .context import get_context

    ctx = get_context(args)
    name = ctx.config.get("cmdb", "name", "home") or "home"
    text = dashboard_json(build_fleet_dashboard(name=name))
    if args.output and args.output != "-":
        Path(args.output).expanduser().write_text(text, encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        sys.stdout.write(text)
    return 0


def _cmd_push(args) -> int:
    from .context import get_context

    ctx = get_context(args)
    if args.file:
        try:
            dashboard = json.loads(Path(args.file).expanduser().read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise DotinfraError(f"cannot read dashboard {args.file}: {e}") from None
    else:
        dashboard = build_fleet_dashboard(name=ctx.config.get("cmdb", "name", "home") or "home")
    client = client_from_context(ctx)
    folder_uid = client.ensure_folder(args.folder, "dotinfra") if args.folder else None
    result = client.push_dashboard(dashboard, folder_uid=folder_uid)
    if args.home:
        client.set_home_dashboard(dashboard.get("uid", DASHBOARD_UID))
    url = result.get("url", "")
    print(f"pushed dashboard '{dashboard.get('title')}' ({result.get('status', 'ok')}) "
          f"{client.url}{url}")
    return 0


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "grafana", help="fleet dashboard: generate JSON or push via the Grafana API",
        description="Generate the fleet dashboard or push it to Grafana (credentials from the vault).")
    sub = p.add_subparsers(dest="grafana_cmd", metavar="COMMAND", required=True)

    d = sub.add_parser("dashboard", help="print or write the fleet dashboard JSON")
    d.add_argument("--output", metavar="FILE", help="write to FILE instead of stdout")
    d.set_defaults(func=_cmd_dashboard)

    u = sub.add_parser("push", help="upload a dashboard via the Grafana API")
    u.add_argument("--file", metavar="FILE", help="dashboard JSON to upload (default: freshly generated fleet dashboard)")
    u.add_argument("--folder", metavar="TITLE", default="Fleet",
                   help="Grafana folder title, created if missing (default: Fleet; '' for General)")
    u.add_argument("--home", action="store_true", help="also make it the organisation's home dashboard")
    u.set_defaults(func=_cmd_push)
