# Events

Component docs state **what is**. The event log records **what happened**:
outages, incidents, maintenance windows, changes, observations. Keeping the
two apart keeps the docs short — agents read them on every task — while the
past stays one command away. Git history keeps every earlier version of the
docs themselves.

```sh
dotinfra event add --host nas --type maintenance --time 2026-09-26T07:34Z --end 2026-09-26T08:10Z "replaced disk 2"
dotinfra event add --host gpu1 --type change "NVIDIA driver 560 -> 570"      # --time defaults to now
dotinfra event list [--host ID] [--type T] [--since -30d] [--limit N] [--json]
dotinfra event rm ID
```

Types: `outage`, `incident`, `maintenance`, `change`, `observation`. `--host`
is a component id. Times: `now`, `-2h`, `30m ago`, or ISO 8601
(`2026-09-26T14:05Z`; without a zone, local time).

## Backends

`.dotinfra.toml`:

```toml
[events]
backend = "auto"   # "auto" | "grafana" | "file"
```

| backend | where events go | `event rm` id |
|---|---|---|
| `grafana` | Grafana annotations, overlaid on the fleet dashboard ([monitoring](monitoring.md#event-log)) | annotation number |
| `file` | `events/<YYYY>.md` inside the CMDB | `YEAR.N` (shown by `event list`) |
| `auto` (default) | `grafana` when `[monitoring] grafana_url` is set or the `[monitoring] service` component exists; otherwise `file` | |

`event list` takes the same filters on both backends and prints the same table
(`--json` gives annotation-shaped objects).

## The file backend

One Markdown bullet per event, oldest first, one file per year (UTC):

```markdown
# Events 2026

- 2026-03-14T10:00Z · hub · change · created; replaces port forwarding on the router
- 2026-09-26T07:34Z/2026-09-26T08:10Z · nas · maintenance · replaced disk 2
```

The fields are separated by ` · `: timestamp (UTC to the minute; an event
with a duration has `start/end`), host, type, text.

- The files **sync with the CMDB** (`dotinfra sync`) like everything else.
- They are **not components**: the loader, `INDEX.md` and lint's component
  rules ignore `events/` (the secret scan still covers it — no secrets in events).
- **Agents do not load them by default** (`AGENTS.md` says so); they run
  `dotinfra event list --host ID` when a task is about the past.
- **Merges never conflict**: the dotinfra merge driver unions `events/*.md`
  line by line (two devices appending on the same day is the normal case),
  sorted by timestamp; a line deleted on one side stays deleted.
- Editing by hand is fine — keep the line format, or `event list` skips the line.

## Moving history out of an old doc

CMDBs from dotinfra < 0.3 kept `## History` sections in component files.
`dotinfra lint` flags them as `journal`. To convert one (or ask an agent: *"Use
the infra-cmdb skill to fix the journal warnings"*):

1. fold anything that is still true into the doc's sections as facts;
2. record the events worth keeping: `dotinfra event add --host nas --type change
   --time 2026-04-02 "model cache moved to NFS"`;
3. delete the History section and any resolved issues; `dotinfra lint`, `dotinfra sync`.
