# sonde-search
a couple dorks trying to break into the easiest hobby ever

## Conda environment

The conda environment is pinned in `environment.yml` (versions only, no build hashes — portable across platforms).

Create a fresh env:
```bash
mamba env create -n sondesearch -f environment.yml
```

Sync an existing env to match (adds new deps, removes removed ones):
```bash
mamba env update -n sondesearch -f environment.yml --prune
```

After changing deps locally, regenerate the lock and commit it:
```bash
conda env export --no-builds | sed '/^prefix:/d' > environment.yml
```

## Tests

From the repo root:
```bash
pytest
```
Each subproject (`aprs-backhaul/`, `analyzers/paneltest/`, `website/backend/`) can also be tested independently from its own directory.
