# dotinfra monitoring bundle

A small, self-contained Prometheus + Grafana + Pushgateway stack whose scrape
targets and fleet dashboard are generated from your dotinfra CMDB.

```
bundle/
├── docker-compose.yml                  # prometheus, grafana, pushgateway (+ optional exporters)
├── .env.example                        # copy to .env; Grafana admin password lives here
├── prometheus/prometheus.yml           # one file_sd job; no hosts listed here
├── targets/*.json                      # GENERATED: one file per metrics job
└── grafana/
    ├── provisioning/datasources/       # Prometheus datasource, uid "dotinfra-prometheus"
    ├── provisioning/dashboards/        # loads grafana/dashboards/*.json into folder "Fleet"
    └── dashboards/dotinfra-fleet.json  # GENERATED: fleet dashboard
```

## Quick start

```sh
dotinfra monitoring render                  # writes to monitoring.bundle_dir (~/dotinfra-monitoring)
cd ~/dotinfra-monitoring
cp .env.example .env
dotinfra vault exec grafana_password -- sh -c 'IFS= read -r p; printf "GRAFANA_ADMIN_PASSWORD=%s\n" "$p" >> .env'
chmod 600 .env
docker compose up -d
```

Open Grafana at `http://<this host>:3000` and log in as `admin` with the vault
password. The "Fleet Overview" dashboard is the home page.

## How targets get here

Give components a `metrics:` list and an `address:` in the CMDB:

```yaml
address: 10.10.0.21
tags: [fleet, gpu]          # `fleet` => a row on the dashboard; otherwise role=infra
metrics: [node:9100, dcgm:9400]
```

`dotinfra monitoring targets` (also run by `render`) writes `targets/node.json`,
`targets/dcgm.json`, ... for components whose `status` is `active` or `degraded`.
Each target carries the labels `job`, `host` (component id), `instance`
(`<id>:<port>`), `role` (`fleet`|`infra`) and `kind`. Prometheus re-reads the
directory every minute; you never need to restart it for host changes.

Keep targets current after CMDB edits: make this machine the monitoring host
(`dotinfra monitoring setup-server`, which sets `role = "server"` in
`.dotinfra.local.toml`) and run `dotinfra timer install`. Every successful sync
then rewrites the targets. Without the role, a cron line works too:

```sh
*/10 * * * * dotinfra sync --no-push >/dev/null 2>&1; dotinfra monitoring targets --force >/dev/null
```

Hand-written extra targets go in `targets/custom-*.json`; dotinfra never touches
those. Stale `*.json` files that dotinfra itself generated (jobs that no longer
exist) are removed; other JSON files are left alone.

## Re-rendering

`dotinfra monitoring render` never overwrites template files you edited
(compose, prometheus.yml, provisioning); it reports them as "kept". Pass
`--force` to reset them to the packaged version. Targets and the dashboard are
always regenerated.

Prometheus data lives in the named volume `prometheus_data`, mounted at
`/prometheus` (the TSDB path), so history survives `docker compose down`,
image upgrades and re-renders. `docker compose down -v` deletes it.

## Installing exporters on your hosts

### node_exporter (all hosts, port 9100)

- **Debian/Ubuntu**: `sudo apt install prometheus-node-exporter`
- **Fedora/RHEL**: `sudo dnf install golang-github-prometheus-node-exporter`
  (or the upstream tarball below)
- **Arch**: `sudo pacman -S prometheus-node-exporter && sudo systemctl enable --now prometheus-node-exporter`
- **Alpine / postmarketOS**: `sudo apk add prometheus-node-exporter && sudo rc-update add node-exporter && sudo rc-service node-exporter start`
- **Any Linux (upstream binary)**: download `node_exporter-*.linux-<arch>.tar.gz` from
  <https://github.com/prometheus/node_exporter/releases>, put the binary in
  `/usr/local/bin/` and run it from a systemd unit as an unprivileged user.
- **Docker host**: `docker compose --profile node up -d` in this bundle, or the
  same `node-exporter` service block in any compose file (host network, `pid: host`,
  `/:/host:ro,rslave`, `--path.rootfs=/host`).
- **FreeBSD / pfSense / OPNsense**: `pkg install node_exporter`, then
  `sysrc node_exporter_enable=YES && service node_exporter start`
  (OPNsense: the `os-node_exporter` plugin).
- **macOS**: `brew install node_exporter && brew services start node_exporter`.

Check from the monitoring host: `curl -s http://10.10.0.21:9100/metrics | head`.
If a firewall is active, allow 9100/tcp from the monitoring host only.

### NVIDIA DCGM exporter (optional, GPU hosts, port 9400)

Needs the NVIDIA driver and the NVIDIA Container Toolkit
(`nvidia-ctk runtime configure --runtime=docker`, then restart docker).
On the GPU host:

```sh
docker compose --profile gpu up -d dcgm-exporter     # from this bundle, or:
docker run -d --restart unless-stopped --gpus all --cap-add SYS_ADMIN -p 9400:9400 \
  nvcr.io/nvidia/k8s/dcgm-exporter:<tag>
```

Pick a tag that matches your driver from the NGC catalog. Consumer GPUs expose
most but not all DCGM fields; the dashboard also understands the `nvidia_smi_*`
metric names of `nvidia_gpu_exporter`. Hosts without a GPU simply show "no GPU".

## Pushgateway

Batch jobs (backups, cron scripts) can push metrics:

```sh
echo "backup_last_success_timestamp_seconds $(date +%s)" |
  curl --data-binary @- http://<monitoring host>:9091/metrics/job/backup/host/nas
```

## Security notes

- Ports 9090/9091/3000 are published on all interfaces. Bind them to a LAN or
  WireGuard address (`"10.99.0.1:3000:3000"`) or firewall them; Prometheus and
  Pushgateway have no authentication.
- `.env` holds the Grafana admin password, so keep it `chmod 600` and out of git.
