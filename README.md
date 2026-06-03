# coreomics-fs

A Python CLI package that maintains a filesystem layout for proteomics core lab submissions. It pulls submission records from a remote API, stores them in SQLite, and projects them onto disk as a canonical directory tree (`year/month/<id>`) plus multiple symlink-tree "views" (by PI, by institute, monthly) that point into the canonical tree.

Installs four console scripts:

| Command           | Purpose                                                |
| ----------------- | ------------------------------------------------------ |
| `coreomics`       | Per-project CLI (run from within a built project dir). |
| `coreomics-build` | Build the canonical tree and view symlinks.           |
| `coreomics-fetch` | Pull submissions from the API into SQLite.            |
| `coreomics-nav`   | Search submissions and print a project dir (backend for the `ccd` shell function). |

---

## Install

Requires Python 3.10 or newer.

### End-user install

```bash
git clone https://github.com/amschaal/coreomics_fs.git ~/coreomics_fs
cd ~/coreomics_fs

pip install .
# OR, if you don't have write access to system site-packages:
pip install --user .
```

### Developer install (recommended for working on the code)

```bash
pip install -e .
```

The `-e` (editable) flag makes Python import directly from `src/`, so **any code edit takes effect the next time you run the CLI** — no reinstall, no `PYTHONPATH` setup. The three console scripts (`coreomics`, `coreomics-build`, `coreomics-fetch`) work exactly the same as with a non-editable install.

### Shared/locked-down hosts (no pip)

If `pip install` isn't usable on your system, see [LSSC0_setup.md](LSSC0_setup.md) for the shared-environment install pattern. As a last-resort fallback, the [scripts/](scripts/) directory contains shell wrappers that set `PYTHONPATH` and invoke the modules directly — symlink them into a directory on your `PATH`.

---

## `ccd` — jump to a project directory

`ccd` searches the submissions database and lets you `cd` straight into a project's
canonical or view directory.

Because a program cannot change its parent shell's working directory, `ccd` is a small
shell **function** that wraps the `coreomics-nav` backend — add it to your shell rc:

```bash
# in ~/.zshrc and/or ~/.bashrc
source /path/to/coreomics_fs/scripts/ccd.sh
```

(Or paste the function from [scripts/ccd.sh](scripts/ccd.sh) directly.) Then:

```bash
ccd PROT_0613            # search id / internal_id / PI & submitter names + emails
ccd doe                  # substring match, case-insensitive
ccd -f pi_email doe@uni.edu   # restrict the search to one field
ccd -d pi PROT_0613      # skip the directory menu; cd straight to the 'pi' view
```

How it works:

1. Matches are listed newest-first. If exactly one submission matches it is selected
   automatically; otherwise pick its number.
2. You're then shown that project's existing directories — the canonical tree plus each
   built view (pi, institute, monthly, submission_id).
3. Pick a number to `cd` there, or press Enter / `q` to cancel and stay put.

Pass `-d/--dir <canonical|view name>` to skip step 2 and select that directory directly.
Combined with a field that yields a single match (e.g. `-f internal_id`), this makes the
whole thing non-interactive — handy for scripting with the `coreomics-nav` backend:

```bash
proj_dir="$(coreomics-nav -f internal_id -d canonical PROT_0613)"
```

The backend prints only the chosen directory to stdout (all menus go to stderr), and only
ever emits a real directory that lives inside the configured `canonical_root` / `views_root`.

---

## Configuration

Configuration is INI format (`configparser`). Copy the example and fill in your values:

```bash
mkdir -p ~/.config/coreomics
cp src/coreomics_fs/config.example.ini ~/.config/coreomics/config.ini
# then edit ~/.config/coreomics/config.ini
```

See [src/coreomics_fs/config.example.ini](src/coreomics_fs/config.example.ini) for the full set of required sections and keys (`[paths]`, `[api]`, `[retain]`).

### Config file lookup order

The first file found wins ([src/coreomics_fs/config.py:7-11](src/coreomics_fs/config.py#L7-L11)):

1. `$CONFIG_PATH` env var, if set
2. `~/.config/coreomics/config.ini` — **the default for installed use**
3. `<package_dir>/config.ini` — fallback for dev checkouts (i.e. a `config.ini` placed next to `config.py`)

If none of these exist, the CLI prints all three searched paths and exits.

### `date_format` and the `%%` rule

In the `[paths]` section, `date_format` needs **doubled percent signs** (e.g. `%%Y_%%m_%%d`) because configparser performs `%`-interpolation on values. The example file already has this right; preserve the doubling when editing.

---

## Tab completion (optional)

Add to `~/.bashrc` or `~/.zshrc`:

```bash
eval "$(register-python-argcomplete coreomics)"
eval "$(register-python-argcomplete coreomics-build)"
eval "$(register-python-argcomplete coreomics-fetch)"
```

`argcomplete` is installed as a dependency of `coreomics-fs`.

---

## Further reading

- [LSSC0_setup.md](LSSC0_setup.md) — install/setup specific to the LSSC0 shared environment.
- [CLAUDE.md](CLAUDE.md) — architecture notes and data flow.
