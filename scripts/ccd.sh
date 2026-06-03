# ccd.sh — sourced shell function to search submissions and cd into a project dir.
#
# Install: add `source /path/to/coreomics_fs/scripts/ccd.sh` to your ~/.zshrc
# and/or ~/.bashrc (or paste the function below directly). Then:
#
#     ccd <term>                 # search id / internal_id / PI & submitter names+emails
#     ccd -f pi_email <term>     # restrict the search to one field
#     ccd -d pi <term>           # skip the directory menu; cd straight to the 'pi' view
#                                # (-d takes 'canonical' or a view name)
#
# This must be *sourced*, not executed — the function runs `cd` in your current
# shell, which a subprocess cannot do.

ccd() {
    local dir
    # Backend prints the chosen directory to stdout; menus/prompts go to stderr.
    if command -v coreomics-nav >/dev/null 2>&1; then
        dir="$(coreomics-nav "$@")" || return        # non-zero exit (no selection) -> do nothing
    else
        # Dev fallback: run the module in-tree (no pip install). Resolve this
        # script's directory under both bash and zsh.
        local _src _root
        if [ -n "${BASH_SOURCE:-}" ]; then
            _src="${BASH_SOURCE[0]}"
        else
            _src="${(%):-%N}"   # zsh
        fi
        _root="$(cd "$(dirname "$_src")/.." && pwd)"
        dir="$(PYTHONPATH="${_root}/src:${PYTHONPATH}" python -m coreomics_fs.cli.navigate "$@")" || return
    fi

    [ -n "$dir" ] || return                          # empty output -> do nothing
    [ -d "$dir" ] || { printf 'ccd: not a directory: %s\n' "$dir" >&2; return 1; }
    cd -- "$dir"                                      # `--` stops a leading-dash path being read as an option
}
