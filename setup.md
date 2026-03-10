# Setup

## Install

```bash
git clone https://github.com/amschaal/coreomics_fs.git ~/coreomics_fs
cd ~/coreomics_fs

pip install .
# OR if installing only for user
pip install --user .

```

This installs three commands:
- `coreomics` — project/submission CLI
- `coreomics-build` — build filesystem views
- `coreomics-fetch` — fetch submissions from API into the DB

No `PYTHONPATH` or aliases needed.

## Tab completion (optional)

Add to `~/.bashrc` or `~/.zshrc`:

```bash
eval "$(register-python-argcomplete coreomics)"
eval "$(register-python-argcomplete coreomics-build)"
eval "$(register-python-argcomplete coreomics-fetch)"
```

## Configuration

Copy the example config and fill in your values:

```bash
cp ~/coreomics_fs/src/coreomics_fs/config.example.yaml ~/coreomics_fs/src/coreomics_fs/config.yaml
```

## Shared/multi-user systems

If you can't use `pip install`, create a wrapper script in `~/.local/bin/coreomics`:

```bash
#!/usr/bin/env bash
export PYTHONPATH="/path/to/coreomics_fs/src:$PYTHONPATH"
exec python -m coreomics_fs.cli.project_cli "$@"
```

Then `chmod +x ~/.local/bin/coreomics` and ensure `~/.local/bin` is on your `PATH`.
