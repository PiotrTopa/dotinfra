# Monitoring

dotinfra can generate everything a small Prometheus + Grafana setup needs from
the CMDB: scrape targets, a docker-compose bundle, a fleet dashboard, and an
event log. All of it is optional.

## Targets from `metrics:`

```yaml
# servers/gpu1.md
status: active
tags: [fleet, gpu]
address: 10.10.0.21
metrics: [node:9100, dcgm:9400]
```

```sh
dotinfra monitoring targets                     # into <bundle_dir>/targets/
dotinfra monitoring targets --output /etc/prometheus/targets
dotinfra monitoring targets --stdout            # inspect
```

produces one [file_sd](https://prometheus.io/docs/prometheus/latest/configuration/configuration/#file_sd_config)
file per job — `node.json`, `dcgm.json`, ... :

```json
[
  {
    "targets": ["10.10.0.21:9100"],
    "labels": {"job": "node", "host": "gpu1", "instance": "gpu1:9100",
               "role": "fleet", "kind": "server"}
  }
]
```

- Only `status: active` and `degraded` components are included.
- The scrape address is `address` (falling back to `ssh.host`).
- `role` is `fleet` for components tagged `fleet`, otherwise `infra`. The
  dashboard shows one row per fleet host.
- `instance` is rewritten to `<id>:<port>`, so graphs show names, not IPs.
- Files for jobs that no longer exist are removed. Hand-written files named
  `custom-*.json` in the same directory are left alone.

Files are replaced atomically and Prometheus re-reads them every minute: adding,
retiring or re-addressing a host never needs a restart.

Using your own Prometheus? Point a scrape job at the directory:

```yaml
scrape_configs:
  - job_name: dotinfra        # overridden per target by the "job" label
    file_sd_configs:
      - files: [/etc/prometheus/targets/*.json]
```

## The bundle

```sh
dotinfra monitoring render            # into [monitoring] bundle_dir (~/dotinfra-monitoring)
cd ~/dotinfra-monitoring
cp .env.example .env
dotinfra vault exec grafana_password -- sh -c 'IFS= read -r p; printf "GRAFANA_ADMIN_PASSWORD=%s\n" "$p" >> .env'
chmod 600 .env
docker compose up -d                  # --profile node: also monitor this host; --profile gpu: DCGM
```

Contents: Prometheus (90-day retention, data in the `prometheus_data` volume
mounted at the TSDB path `/prometheus`), Grafana (datasource provisioned with
uid `dotinfra-prometheus`, dashboards loaded from `grafana/dashboards/`),
Pushgateway, and optional node_exporter and NVIDIA DCGM exporter services.
Prometheus config and targets are **directory** mounts, so editors that save
by renaming files do not leave the container with a stale copy.

`render` never overwrites template files you have edited (it reports them as
"kept"); `--force` resets them. Targets and the dashboard are always rewritten.
The bundle's [README](../src/dotinfra/bundle/README.md) covers installing node_exporter
on Linux, FreeBSD and macOS and setting up the DCGM exporter.

Keep targets fresh on the monitoring host with a timer or cron entry:

```sh
*/10 * * * * dotinfra sync --no-push >/dev/null 2>&1; dotinfra monitoring targets >/dev/null
```

## The fleet dashboard

`dotinfra grafana dashboard > fleet.json` or, with the bundle, automatically.
"Fleet Overview — <cmdb name>" (uid `dotinfra-fleet`) contains:

- a **row per fleet host** (repeated from a `host` variable): up/down, CPU,
  RAM, root disk, CPU temperature, GPU utilisation, VRAM, GPU temperature and
  power, load per core, fan speed, network throughput, uptime;
- **host comparison** time series for the same metrics;
- an **up/down timeline** of every scrape target (fleet and infra);
- **event annotations**, colour-coded by type.

The `host` variable is filled from Prometheus
(`label_values(up{role="fleet"}, host)`), so the dashboard never needs
regenerating when hosts come and go. Hosts without an NVIDIA GPU show "no GPU".
Queries cover Linux and FreeBSD node_exporter metric names, DCGM exporter
metrics and the `nvidia_smi_*` names of `nvidia_gpu_exporter`.

### Pushing to an existing Grafana

```sh
dotinfra grafana push                 # generated dashboard, folder "Fleet"
dotinfra grafana push --file my.json --folder "" --home
```

Credentials: `[monitoring] grafana_url`, `grafana_user`, and the password from
the vault key named by `grafana_password_key`. To use a service-account token
instead, store it in the vault and set `grafana_token_key = "grafana_token"`.
The dashboard uses a `datasource` variable (default uid `dotinfra-prometheus`),
so it works with any Prometheus datasource you pick in the UI.

A dashboard provisioned from files (the bundle) cannot also be pushed over the
API with the same uid; use one method per Grafana.

## Event log

Infra events are Grafana annotations tagged `dotinfra`, `host:<id>` and
`type:<type>`; the dashboard overlays them on every graph.

```sh
dotinfra event add --host nas --type maintenance --time 2026-09-26T08:00Z --end 2026-09-26T08:40Z "replaced disk 3"
dotinfra event add --host gpu1 --type change "NVIDIA driver 560 -> 570"      # now
dotinfra event add --host hub --type outage --time -2h --end now "provider network outage"
echo "long text" | dotinfra event add --host pi --type observation
dotinfra event list [--host ID] [--type T] [--since -7d] [--limit N] [--json]
dotinfra event rm 123
```

| type | colour | for |
|---|---|---|
| `outage` | red | something was down |
| `incident` | orange | degraded, data at risk, security event |
| `maintenance` | blue | planned work |
| `change` | purple | config, upgrades, hardware |
| `observation` | light blue | worth remembering; nothing changed |

Times: `now`, relative (`-2h`, `30m ago`), or ISO 8601 (`2026-09-26T14:05Z`,
`2026-09-26 16:05` in local time). `--host` should be a component id; unknown
ids produce a warning.

Events complement, not replace, the component's `## History`: the History
line is the durable record in git, the annotation is its view on the graphs.
