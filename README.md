# Entropy Anomaly SETI — Pre-Registered Rebuild

> **STATUS: the original detection claims are WITHDRAWN.**
> A first-pass referee review (2026-11-14, commit `7f8079e`) rejected the
> manuscript, and its decisive findings were independently reproduced against
> this repository. All Phase 1/2 results, catalogs and figures are **falsified
> and superseded**. See `PROTOCOL.md` and `archive/README.md`.
>
> The repository is being rebuilt as a **falsification-first methods / null-result
> study**: *"A compression-based anomaly statistic for TESS light curves:
> calibration, systematics, and limits."* A null result is the expected outcome
> and will be published regardless of sign.

## What is current

| Path | Purpose |
|---|---|
| `PROTOCOL.md` | Pre-registered study design (v2.0.0), H0/H1, decision rule, frozen parameters |
| `config/protocol.json` | Machine-readable pre-registration; SHA-256 frozen into every downstream catalog |
| `pipeline/build_sample_v2.py` | Corrected Gaia DR3 / TIC v8.2 sample builder (no synthetic values) |
| `pipeline/workstation_runner.py` | Reusable TESS download + SQLite pipeline infrastructure |
| `setup_and_run.sh` | Thin venv + run wrapper |

`config/protocol.json` is the **single source of truth**. Editing it changes the
protocol hash and invalidates every downstream catalog and result.

## Why the original claim was withdrawn

Verified locally on 2026-11-14:

- Targets labelled "Pleiades" are not Pleiades members — TIC 261136679 is
  π Men (Dec −80°, 18 pc). The real Pleiades were observed in TESS sectors
  **42–44, 70–71**, never sector 11.
- Catalog coordinates, Tmag and distances were generated with `np.random.uniform`.
- The zlib `K(S)` statistic is saturated: 150 random bytes → 161 bytes, so
  `K(S)=1.0733` is container overhead, not entropy. One 8σ cadence *lowers*
  `K(S)` (1.0733 → 1.0533), so `μ−3σ` flags cosmic rays.
- 24 headline "anomalies" = **2 events**, inflated by 93%-overlapping windows.
  Replacing those two cadences removes all anomalies.
- `p<10⁻¹⁵` and "Excess factor >∞" are hard-coded strings, never computed.
- Several figures were generated from `np.random` and presented as results.
- Controls showed the same effect as targets — an instrumental/statistical origin.

The conclusion is **disproven**, not under-powered. It is not being rescued.

## Corrected design (summary)

- Sample: Gaia DR3 Pleiades members cross-matched to TIC v8.2 by position;
  real sectors 42–44 / 70–71; one documented data product; blends within one
  TESS pixel merged; ≥300 matched field controls from the same sector/camera/CCD.
- Preprocessing: `hard` quality mask, detrend, 5σ per-cadence clipping,
  time-based windows that never cross gaps.
- Statistic: LZ76 / permutation entropy on a fixed per-star noise scale
  (no per-window min-max); **events**, not overlapping windows.
- Null: ≥1000 IAAFT surrogates per star; pre-registered threshold; FDR +
  look-elsewhere correction; `α_global = 0.01`.
- Validation: ≥1000 injections, ROC curves, matched-filter/BLS baseline.
- Reproducibility: pinned lockfile, fixed seeds, MAST product IDs, Zenodo DOI.

## Running the sample builder

```bash
python3 pipeline/build_sample_v2.py --self-test    # offline, stdlib only
python3 pipeline/build_sample_v2.py --dry-run      # frozen params + Gaia ADQL
python3 pipeline/build_sample_v2.py --build        # real Gaia + TIC + tess-point
python3 pipeline/build_sample_v2.py --validate-only --input data/catalog_v2.csv
```

`--build` requires `astroquery`, `astropy` and `tess-point` plus network access.
The builder **raises rather than fabricating** any value if a service is
unreachable; every emitted row carries a `provenance` string and the protocol hash.

## Archive (not scientific evidence)

`archive/` retains, for transparency, the superseded manuscript, cover letter,
COI form, Phase-2 report, simulated figures and duplicate catalogs. None of it
may be cited or presented as data. See `archive/README.md` for the full list and
the list of known-broken legacy scripts.

`darpa-classified-summary.md` has been removed from git tracking and is kept on
the local machine only. It remains in git *history*; purging that history is a
separate destructive decision requiring explicit sign-off.

## Authorship and independence — CORRECTED in archived docs (2026-11-14)

The archived documents now carry a prominent **WITHDRAWN / SUPERSEDED** banner and
their authorship has been corrected: sole human author (Alexander Ross Lingle,
independent researcher), the AI tool removed as co-author, the fictitious
"North by Northwest Corp, Lunar Intelligence Division" affiliation removed, and
non-deliverable `.corp` contact addresses removed. AI assistance is disclosed in
acknowledgements only. The falsified scientific claims in those documents were
left unchanged as a record and are explicitly flagged in each banner.

The corrected study uses a single human author with AI assistance disclosed in
the acknowledgements.

This research was conducted on personal computational resources with no
corporate research funding or institutional computing resources.

## License / DOI

MIT License. The v1.0 release and its "pending" DOI refer to the **superseded**
work; a new release matching the rebuilt study is required.

## Citation

Do not cite the superseded results. Cite the protocol/pre-registration once a
release matching it exists.
