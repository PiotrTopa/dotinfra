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
    ├── provisioning/datasources/       # "dotinfra Prometheus", uid "dotinfra-prometheus", not default
    ├── provisioning/dashboards/        # loads grafana/dashboards/*.json into folder "Fleet"
    └── dashboards/dotinfra-fleet.json  # GENERATED: fleet dashboard
```

## Quick start

> **Already running Grafana or Prometheus on this machine?** Read
> [Adopting an existing stack](#adopting-an-existing-stack) before the first
> `docker compose up -d`: starting the bundle's Grafana on a newer Grafana
> database can corrupt it.

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

## Adopting an existing stack

Do this **before the first `docker compose up -d`** if this machine already
runs Grafana and/or Prometheus (a hand-written compose file, `docker run`, an
older setup) and the bundle should take over their data. `dotinfra monitoring
render` and `setup-server` print a warning when docker has Grafana or
Prometheus containers or volumes that the bundle does not own, until a
`docker-compose.override.yml` exists next to the bundle's compose file.

1. **Pin Grafana to at least the version that runs now.** Grafana migrates its
   database forward on start and cannot migrate it back: an older Grafana on a
   newer database can corrupt it. The bundle's default tag may well be older
   than what a `:latest` container pulled. Ask the running container:

   ```sh
   docker exec <grafana-container> grafana server -v    # e.g. "Version 13.0.4 (...)"
   echo 'GRAFANA_IMAGE=grafana/grafana:13.0.4' >> .env    # the same version, never older
   ```

   The same version is safest: nothing is migrated, so rolling back stays
   possible. Upgrade later as a separate step. Prometheus: check
   `docker exec <prometheus-container> prometheus --version` and do not go
   below it either (`PROMETHEUS_IMAGE`).

2. **Find the old data.** List what each old container mounts:

   ```sh
   docker inspect -f '{{range .Mounts}}{{.Type}} {{.Name}} {{.Source}} -> {{.Destination}}{{println}}{{end}}' \
     <grafana-container> <prometheus-container>
   ```

   Grafana keeps its database in `/var/lib/grafana`, Prometheus its TSDB in
   the directory given by `--storage.tsdb.path` (`/prometheus` in the official
   image). A volume whose name is 64 hex characters is **anonymous**: it has
   no stable name and is lost to `docker volume prune` once its container is
   removed.

3. **Stop the old stack; do not remove it.** Stopped containers keep their
   volumes (anonymous ones included), so rolling back is one `docker start`.

   ```sh
   docker stop <grafana-container> <prometheus-container>   # or `docker compose stop` in the old project
   ```

   Optionally back up the Grafana volume now:
   `docker run --rm -v <grafana-volume>:/from:ro -v "$PWD":/backup alpine tar czf /backup/grafana-data.tgz -C /from .`

4. **Copy an anonymous Prometheus volume into a named one** (skip this when
   the TSDB already lives in a named volume). Prometheus must be stopped so the
   copy is consistent:

   ```sh
   docker volume create prometheus-history
   docker run --rm -v <64-hex-volume>:/from:ro -v prometheus-history:/to alpine cp -a /from/. /to/
   ```

   `cp -a` keeps the file owner (`nobody` in the official image).

5. **Reuse the volumes in `docker-compose.override.yml`**, next to the bundle's
   `docker-compose.yml`. Docker Compose merges it automatically and
   `dotinfra monitoring render` never touches it:

   ```yaml
   # docker-compose.override.yml: keep the data of the stack this bundle replaces.
   # `external: true` means compose uses these volumes as they are and never
   # creates or deletes them (not even with `docker compose down -v`).
   volumes:
     grafana_data:
       external: true
       name: grafana-storage          # the old Grafana volume (step 2)
     prometheus_data:
       external: true
       name: prometheus-history       # the named copy (step 4) or the old named volume

   # Data in a host directory (bind mount) instead of a volume? Mount it over
   # the same container path; compose replaces the bundle's mount:
   # services:
   #   grafana:
   #     volumes:
   #       - /srv/grafana:/var/lib/grafana
   ```

6. **Start and check.**

   ```sh
   docker compose config --volumes     # shows grafana_data and prometheus_data
   docker compose up -d
   docker compose logs grafana | grep -iE 'error|migrat'
   dotinfra monitoring where --check
   ```

   The adopted Grafana keeps its users, dashboards, datasources and admin
   password (`GRAFANA_ADMIN_PASSWORD` only applies to a new database). The
   bundle adds the datasource "dotinfra Prometheus" next to any existing
   "Prometheus" one; an old datasource that pointed at the old container's
   hostname may need its URL changed to `http://prometheus:9090`. To keep
   existing series names, give components a `labels:` map with `host:`.

7. **Roll back** if anything is wrong: `docker compose down` in the bundle
   (external volumes are kept), then `docker start` the old containers. Remove
   the old containers and volumes only after the new stack has run for a while.

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
