# ARCHIVE — superseded / non-evidence material

Everything under this directory is **retained for transparency only**. None of it
is a valid scientific result. Nothing here may be cited, presented as data, or
included in a submission.

## Why

A first-pass referee review (2026-11-14, repo commit `7f8079e`) rejected the
original manuscript. Its decisive findings were independently reproduced on
2026-11-14 against this repository:

- The Phase 1/2 "Pleiades" targets are **not Pleiades members** — TIC 261136679
  is HIP 26394 / π Men (Dec −80°, 18 pc). The real Pleiades were observed by TESS
  in sectors **42–44 and 70–71**, never sector 11.
- Catalog coordinates, Tmag and distances were generated with `np.random.uniform`.
- The zlib `K(S)` statistic is **saturated**: 150 random bytes compress to 161,
  i.e. `K(S)=1.0733` is container overhead, not entropy. A single 8σ cadence
  *lowers* `K(S)` (1.0733 → 1.0533), so `μ−3σ` flags cosmic rays, not information.
- The 24 headline "anomalies" are **2 events**, inflated by 93%-overlapping windows
  (one cadence enters ~15 windows at W=150/stride=10). Replacing those 2 cadences
  removes all anomalies.
- `p<10⁻¹⁵` and "Excess factor >∞" are **hard-coded strings** in
  `visualize_pleiades.py`, never computed.
- The figures below are simulated with `np.random` ("dummy K(S) data for
  visualization") — schematic placeholders, **not measurements** (referee M12).
- `observational-network-switch-report.md` describes ground-based stellar flicker,
  which is atmospheric scintillation, not evidence (M13b).

## What IS current and valid

- `PROTOCOL.md` — pre-registered falsification protocol, v2.0.0
- `config/protocol.json` — machine-readable frozen parameters (SHA-256 `fd0c705c…`)
- `pipeline/build_sample_v2.py` — corrected Gaia DR3 / TIC v8.2 sample builder
- `pipeline/workstation_runner.py` — reusable pipeline infrastructure

## Quarantined here

- `legacy-figures/` — simulated / schematic PNGs from `figures/`
- `legacy-visualizations/` — PNGs + `cluster_statistics.csv` from `results/visualizations/`
- `legacy-docs/` — old paper (`.md`, `.tex`, `.pdf`), cover letter, COI form,
  Phase-2 report, execution plan, release notes, network-switch report.
  Each of the four submission documents carries a WITHDRAWN banner and had its
  authorship corrected on 2026-11-14 (sole human author; AI removed as co-author;
  fictitious affiliation and `.corp` contacts removed). Their falsified scientific
  claims were deliberately left unchanged as a record.
- Root duplicate catalogs (`expanded_star_catalog.csv`, `expanded_batch_results.csv`)
  were removed from tracking; the canonical copies in `data/` are also superseded.

## Deliberately NOT in the public repo

- `darpa-classified-summary.md` — removed from git tracking, **kept on the local
  machine** as requested. Self-applied classification markings on a public,
  self-authored document were inappropriate (referee M13a).
  **NOTE:** it remains in git *history*. Purging history (`git filter-repo` +
  force push) is a separate, destructive decision requiring explicit sign-off.

## Present but known-broken — do not use

- `pre-submission-validation.py` — crashes (TypeError); references a missing
  `paper-peer-review-v4.md`
- `package_for_release.py` — packages that same missing file
- `colab_entropy_analysis.ipynb` — computes a different metric; cell 4 SyntaxError
- `pipeline/generate_cluster_report.py`, `pipeline/visualize_pleiades.py` —
  simulate data; must be rewritten to fail loudly on missing inputs
- `pipeline/build_extended_catalog.py`, `pipeline/build_pleiades_catalog.py` —
  synthetic coordinates / magnitudes

These are kept visible so the record is complete. They are not part of the
scientific package. See `PROTOCOL.md` for the corrected study design.
