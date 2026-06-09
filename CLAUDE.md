# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`coreomics-fs` is a Python CLI package that maintains a filesystem layout for proteomics core lab submissions. It pulls submission records from a remote API, stores them in SQLite, and projects them onto disk as a canonical directory tree (`year/month/<id>`) plus multiple symlink-tree "views" (by PI, by institute, monthly) that point into the canonical tree. An optional parallel tree of Windows `.lnk` shortcuts ([winlnk.py](src/coreomics_fs/build/winlnk.py)) serves Windows SMB clients, which can't follow POSIX symlinks.

## Install and run

```bash
pip install .           # or: pip install --user .
pip install -e .        # editable install for development — code edits take effect without reinstall
```

Installs three console scripts (declared in [pyproject.toml](pyproject.toml#L13-L16)):

| Command            | Entry point                                          | Purpose                                     |
| ------------------ | ---------------------------------------------------- | ------------------------------------------- |
| `coreomics`        | `coreomics_fs.cli.project_cli:main`                  | Per-project CLI (run from within a project) |
| `coreomics-build`  | `coreomics_fs.build.build_views:main`                | Build canonical tree + view symlinks        |
| `coreomics-fetch`  | `coreomics_fs.build.fetch_projects:main`             | Pull submissions from API → SQLite          |

The [scripts/](scripts/) directory contains shell wrappers (`build_views.sh`, `fetch_projects.sh`, `submission.sh`) that set `PYTHONPATH` and `exec python -m ...`. They exist as a fallback for environments where `pip install` isn't available — prefer the installed console scripts.

User-facing install/config docs live in [README.md](README.md); LSSC0-specific notes in [LSSC0_setup.md](LSSC0_setup.md).

There are **no tests, no lint config, and no build step** beyond `pip install`.

## Configuration

Config is loaded by [src/coreomics_fs/config.py](src/coreomics_fs/config.py) using `configparser` (INI format only). Lookup order (first hit wins):

1. `$CONFIG_PATH` env var
2. `~/.config/coreomics/config.ini`
3. `<package_dir>/config.ini` (dev-checkout fallback)

Required sections/keys are shown in [src/coreomics_fs/config.example.ini](src/coreomics_fs/config.example.ini): `[paths]` (canonical_root, views_root, submissions_db_directory, date_format, log_name, error_log), `[api]` (api_key, api_base_url), `[retain]` (daily, weekly, monthly). The optional `[permissions]` section (group, owner) enables filesystem deletion-protection — see Architecture below.

When importing `cfg["paths"]["date_format"]` from INI, `%` must be doubled (e.g. `%%Y_%%m_%%d`) — configparser's interpolation rule.

## Architecture

### Data flow

```
remote API ──fetch_projects.py──> SQLite (submissions.db)
                                      │
                                      ▼
                              build_views.py
                                      │
                ┌─────────────────────┼─────────────────────┐
                ▼                     ▼                     ▼
        canonical_root/         views_root/.versions/<view>/<date>/...
        <YYYY>/<MM>/<id>/       (symlinks → canonical)
        .submission/
          submission.json       views_root/<view> → latest version
```

- **Canonical tree** ([build_views.py:ensure_canonical](src/coreomics_fs/build/build_views.py#L71-L85)) is the one place each submission's data physically lives. It also seeds `.submission/submission.json` per project — this is the file the `coreomics` per-project CLI later discovers.
- **Views** are version-stamped symlink trees. Each build writes to `.versions_tmp/<view>/<today>/`, atomically moves to `.versions/<view>/<today>/`, then repoints `latest` and the top-level `<view>` symlink.
- **Retention** ([prune_old_views](src/coreomics_fs/build/build_views.py#L125-L183)) keeps last N daily + weekly + monthly snapshots per view; everything else is deleted.

### Optional Windows `.lnk` views tree ([winlnk.py](src/coreomics_fs/build/winlnk.py))

POSIX symlinks don't work for Windows SMB clients. When `[paths] windows_views_root` is set (blank = off, default), `build_views.py:build_windows_views` builds a **second views tree** under that root, structurally identical to `views_root` but with each project leaf as a `<id>.lnk` Windows shortcut instead of a symlink — every other segment is a real directory. It's **current-state only** (no `.versions`/`latest`): each view is staged in `windows_views_root/.tmp/<view>/` and atomically swapped into place via two `os.replace` renames (move-aside, rename-in, drop-old).

[winlnk.py](src/coreomics_fs/build/winlnk.py) writes the `.lnk` via **pylnk3** (an *optional* dependency — `pip install 'coreomics-fs[windows]'` — lazy-imported, only needed for this feature). A bare hand-rolled `.lnk` with just a relative/working path opens with an **empty target** in Explorer, because Explorer reads the target from a binary `LinkTargetIDList`/expand-string; that's why pylnk3 (not stdlib `struct`) is used, and why shortcut targets are **absolute**. `windows_views_target = unc|drive` chooses the form: both need `windows_server_path` (the server dir the share maps to, an ancestor of `canonical_root`) to rewrite each canonical path to a Windows path; `unc` joins it under `windows_unc_base` (`\\server\share`), `drive` under `windows_drive_letter` (`Z:`). UNC uses pylnk3's remote `LinkInfo`+expand-string; drive builds a `MyComputer→Drive→folder` IDList with every segment forced to `TYPE_FOLDER` (pylnk3's `for_file` would mislabel the non-existent leaf as a file). The part-computation loop is shared with the POSIX build via `_iter_view_leaves`, so both trees stay identical. **`.lnk` resolution must be verified on a real Windows client.**

### Two parallel `VIEWS` modules

[views.py](src/coreomics_fs/build/views.py) and [json_views.py](src/coreomics_fs/build/json_views.py) both define a `VIEWS` dict mapping view name → list of component-extractor functions. They differ in **which keys they read from a submission dict**:

- `views.py` reads CSV-style keys like `"PI Last Name"`, `"Internal ID"`, `"Submitted"`.
- `json_views.py` reads API/JSON-style keys like `proj["pi"]["last_name"]`, `internal_id`, `submitted`.

[build_views.py:main](src/coreomics_fs/build/build_views.py#L186) picks between them by the input file's suffix: `.csv` → `views.py`, otherwise (`.json`, `.db`, `.sqlite`) → `json_views.py`. If you add a new view, add it to **both** dicts (or accept that it only works for one input format).

To add a view: write component functions that take a project dict and return a path-segment string, then add `"<name>": [fn1, fn2, ...]` to `VIEWS`. `safe_name()` (uppercase, strip non-`\w\-\.`) is the standard sanitizer.

### Filesystem deletion-protection ([permissions.py](src/coreomics_fs/build/permissions.py))

When `[permissions] group` is set, `load_perm_policy(cfg)` returns a policy and `build_views.py` enforces ownership/modes so lab users (SMB clients) can write **inside** their own project but can't delete project dirs or the structure above them. The model relies on the POSIX rule that deleting an entry needs write on its *parent*: parents (`canonical_root`/`<YYYY>`/`<MM>` and the whole views tree) are `02755` (group `r-x`), the project `<id>` dir is `02775` (group `rwx`), and `<id>/.submission` stays `0755` so metadata can't be removed. The setgid bit (`02xxx`) makes new files inherit the lab group.

- `enforce_project(dst, policy, canon_root)` runs in `ensure_canonical` **every build** (idempotent, self-healing on pre-existing dirs); `enforce_tree` locks the views tree at the end of `main` and powers the `coreomics-build --enforce-permissions` one-time migration sweep.
- The build must run as the **owner** (a lab-group member) so `chgrp`/`chmod` work without root; `chown` to a *different* owner needs root and only happens in the `--enforce-permissions` pass. Blank `group` = feature off (default, backward compatible). All chmod/chown failures are logged and swallowed, never abort a build.

### Per-project CLI discovery

[project_cli.py:find_submission](src/coreomics_fs/cli/project_cli.py#L31-L48) walks upward from `cwd` looking for `.submission/submission.json`. That file is created by `ensure_canonical` during `coreomics-build`. So the `coreomics` CLI only works inside (or under) a built canonical directory. `--stop-at <dir>` caps the upward walk.

`coreomics update` re-fetches the single submission from the API and rewrites both the local `.submission/submission.json` and the SQLite row (via [SubmissionsDB.upsert_submission](src/coreomics_fs/db/sqlite_submissions.py#L44)).

### API client

[cli/api.py](src/coreomics_fs/cli/api.py) is a thin urllib wrapper — no `requests`, no `yaml`, stdlib-only. Auth is `Authorization: Token <api_key>`. `SubmissionAPI.create()` is the factory most code uses; it loads config and instantiates the client.

### SQLite schema

Single `submissions` table ([sqlite_submissions.py:init_db](src/coreomics_fs/db/sqlite_submissions.py#L19-L42)): scalar columns for indexed/searchable fields (id, internal_id, submitted, names, emails) plus a `submission JSON` column holding the full record. Upsert is keyed on `id`. `fetch_all_submissions()` prefers the JSON column when present and falls back to the scalar columns.

## Gotchas

- The `pi` nested dict in API JSON may be `None` — extractor functions in `json_views.py` already guard for this; new ones should too.
- `cfg["paths"]["date_format"]` is the format used for **view version folder names** (e.g. `2026_05_19`); changing it mid-deployment will break retention pruning until old folders age out.
- `_set_timestamp` ([build_views.py:63](src/coreomics_fs/build/build_views.py#L63)) sets `mtime` on symlinks/dirs from the submission's `submitted` field — view trees end up sorted by submission date in `ls -lt`, not by build date.
- `build_views copy.py` and `submissions.json.save` are scratch files, not source — ignore them.
- `src/scripts/anonymize_submissions.py` is an unrelated one-off; the `scripts/` directory at the repo root is the canonical home for shell wrappers.
- `[permissions]` enforcement never `chmod`s symlinks (Linux ignores symlink mode bits — no `lchmod`); deletion of a view symlink is blocked by its parent dir's `02755` mode instead. The view symlinks are `chgrp`'d with `follow_symlinks=False`. `os.umask(0o022)` is set at build start only when the feature is enabled.
