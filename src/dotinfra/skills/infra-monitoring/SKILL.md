---
name: infra-monitoring
description: Monitoring for a dotinfra CMDB — Prometheus scrape targets generated from component `metrics:`, the Prometheus+Grafana+Pushgateway docker-compose bundle, the Fleet Overview Grafana dashboard, and the infra event log (Grafana annotations for outages, maintenance, changes, incidents, observations). Use when adding a host to monitoring, installing node_exporter or the NVIDIA DCGM exporter, (re)deploying the monitoring stack, when a dashboard shows a host down or missing, when checking CPU/RAM/GPU/temperature history, or right after an outage, maintenance window or notable change that should be recorded as an event.
---

# Infra monitoring

Everything is derived from the CMDB; never hand-edit generated files.

## Where it runs: one monitoring host

The stack runs on **one** machine: the `runs_on:` server of the service
component named by `[monitoring] service` (default `services/monitoring.md`).
Start every monitoring task with:

```sh
dotinfra monitoring where            # service, host, Grafana/Prometheus URLs, this device's role
dotinfra monitoring where --check    # ...and whether both answer
```

- `this device: server` means you are on the monitoring host: deploy and change
  the stack here. Every `dotinfra sync` here refreshes the scrape targets.
- `this device: client`: do not render or start a bundle here. Change the CMDB
  (`metrics:`, the service component) and sync; the server applies it on its
  next sync. To act on the stack itself, work on the host (SSH via the CMDB).
- URLs are resolved from the service component: `url` gives Grafana and
  `prometheus_url` gives Prometheus. Without them, `http://<address>:3000`
  and `:9090` are used, where the address is the service's own or its
  `runs_on` server's. Explicit `grafana_url`/`prometheus_url` override this;
  put per-device ones (a VPN address) in `.dotinfra.local.toml`.

| source in CMDB | generated | command |
|---|---|---|
| `metrics: [job:port]` + `address` + `status` | `targets/<job>.json` (Prometheus file_sd) | `dotinfra monitoring targets` |
| `tags: [fleet]` | `role="fleet"` label → a row on the dashboard | (same) |
| whole bundle | compose, prometheus.yml, Grafana provisioning, dashboard | `dotinfra monitoring render` |
| — | Fleet Overview dashboard JSON | `dotinfra grafana dashboard` / `grafana push` |

Only components with `status: active` or `degraded` are scraped. Labels on
every target: `job`, `host` (= component id), `instance` (`<id>:<port>`),
`role` (`fleet`|`infra`), `kind`. Query by `host`, never by IP.

Config lives in `[monitoring]` of `.dotinfra.toml` (`service`, `grafana_user`,
`grafana_password_key` = vault key, `bundle_dir`; optional URL overrides) and,
per device, of `.dotinfra.local.toml` (`role = "server"|"client"`, `bundle_dir`,
URL overrides).

## Add a host to monitoring

1. Install node_exporter on it (see `README.md` in the bundle for Linux, FreeBSD,
   macOS, Alpine, OPNsense). Restrict port 9100 to the monitoring host.
2. GPU host (NVIDIA): also run the DCGM exporter on 9400
   (`docker compose --profile gpu up -d dcgm-exporter` from the bundle).
3. In the component file: `metrics: [node:9100]` (or `[node:9100, dcgm:9400]`),
   make sure `address` is reachable *from the monitoring host* (use the VPN
   address for roaming/remote hosts), add `fleet` to `tags` if it belongs on the
   dashboard. History line, `updated:`.
4. `dotinfra lint && dotinfra sync`. The monitoring host's next sync rewrites
   the targets (`role = "server"`; run `dotinfra sync` there to apply it
   now). Prometheus picks them up within a minute, with no restart.
5. Verify: `curl -s http://<prometheus>/api/v1/targets | grep '"host":"ID"'` or
   the dashboard's "All scrape targets" panel.

## Deploy or update the stack

On the monitoring host only (first time: `dotinfra monitoring setup-server`,
which records `role = "server"` locally and renders the bundle):

```sh
dotinfra monitoring render                 # to monitoring.bundle_dir (default ~/dotinfra-monitoring)
cd ~/dotinfra-monitoring && cp -n .env.example .env
dotinfra vault exec grafana_password -- sh -c 'IFS= read -r p; printf "GRAFANA_ADMIN_PASSWORD=%s\n" "$p" >> .env'  # from the vault
chmod 600 .env && docker compose up -d     # add --profile node to monitor this host too
```

- Re-running `render` keeps locally edited template files (reported as "kept");
  `--force` resets them. Targets and dashboard are always regenerated.
- Prometheus history is in the `prometheus_data` volume at `/prometheus`;
  never `docker compose down -v` unless the user wants to delete history.
- Record the deployment in `services/monitoring.md` (`runs_on:` the host,
  `url:` Grafana, optionally `prometheus_url:`), and `dotinfra timer install`
  on the host so targets stay current.
- Moving the stack to another machine: change `runs_on:` (and the URLs), run
  `setup-server` on the new host and set `role = "client"` (or delete the
  line) in the old host's `.dotinfra.local.toml`.
- Existing Grafana instead of the bundle: `dotinfra grafana push [--home]`
  (password from the vault; needs a Prometheus datasource, ideally with uid
  `dotinfra-prometheus`). A dashboard provisioned from files cannot also be pushed.

## Dashboard

"Fleet Overview — <cmdb name>" (uid `dotinfra-fleet`): one repeated row per
`fleet` host (up, CPU, RAM, disk, CPU temp, GPU, VRAM, GPU temp/power, load per
core, fans, network, uptime), host comparison time series, and an up/down
timeline of every target. Hosts come from `label_values(up{role="fleet"}, host)`,
so it never needs regenerating when hosts change. Hosts without a GPU show "no GPU".

## Diagnose "host down / missing"

1. Is it in `targets/*.json`? No → check `status`, `metrics`, `address`
   (`dotinfra monitoring targets` prints warnings).
2. Prometheus `/targets` page shows the scrape error. Typical: firewall, exporter
   bound to localhost, wrong address for the network the monitoring host is on.
3. From the monitoring host: `curl -s --max-time 5 http://ADDR:9100/metrics | head -3`.
4. Record what you found in the component (Known issues / History).

## Event log (Grafana annotations)

Record every outage, maintenance window, notable change, incident or
observation — the dashboard overlays them on all graphs, colour-coded by type.

```sh
dotinfra event add --host nas --type maintenance --time "2026-09-26T08:00Z" --end "2026-09-26T08:40Z" "replaced disk 3"
dotinfra event add --host gpu1 --type change "driver 560 -> 570"          # --time defaults to now
dotinfra event add --host hub --type outage --time -2h --end now "provider network outage"
dotinfra event list --host nas --type outage --limit 20
dotinfra event rm ID
```

Types: `outage`, `maintenance`, `change`, `incident`, `observation`. `--host`
is a component id. Events are tagged `dotinfra`, `host:<id>`, `type:<type>`.
Always pair an event with a History line in the component file — the CMDB is
the durable record; the annotation is its timeline view.
