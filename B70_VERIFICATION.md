# B70 Workstation — Sample Expansion & Verification Runbook

**Status:** prepared, not yet executed. Run on the B70 workstation (WSL Ubuntu),
which has network access to Gaia DR3 TAP (unreachable from the agent's Chromebook).

## What the Chromebook already did (phase 2, completed 2026-11-14)

`pipeline/local_sample_probe.py --run` produced `data/catalog_local_probe.csv`:

- 257,381 MAST TIC rows in a 3° cone → **281 real Pleiades member candidates**
  after the frozen parallax/PM/Tmag/contamination cuts
- 1392 target×sector rows across sectors **42, 43, 44, 70, 71**, cameras 1–4
- **0 of 7 falsified IDs** (π Men, its neighbour, Member B/C, the duplicate/blend
  pair, the placeholder control) leaked in
- Coordinates RA 53.5–59.6, Dec +21.3 to +26.9, parallax 6.52–8.29 mas

This catalog is a **PROBE**, with an explicit protocol-deviation provenance
string. It is not the registered study catalog and is not a result. It exists to
prove the corrected geometry works before committing B70 time.

## Why the B70 is needed

1. **Gaia DR3 TAP** — the pre-registered astrometry source. The Chromebook
   cannot reach `gea.esac.esa.int`; the B70 can.
2. **RUWE** — only in Gaia DR3, not TIC v8.2. Required by the frozen cut.
3. **Matched controls** — the protocol requires ≥300 field controls from the
   same sector/camera/CCD, matched in Tmag. The probe built targets only.
4. **Full `validate_catalog()` gate** — the canonical builder refuses to emit
   anything that fails schema, provenance, duplicate, sector or ratio checks.
5. **Scale** — expanding to more clusters/sectors is CPU/RAM-bound on the
   TESS downloads; that is the B70's job.

## Prerequisites on the B70

```bash
cd ~/entropy-anomaly-seti
git pull
python3 -m venv venv_workstation
source venv_workstation/bin/activate
pip install --upgrade pip
pip install "numpy>=1.24" "pandas>=2.0" "scipy>=1.10" \
    "astropy>=5.3" "astroquery>=0.4.7" "lightkurve>=2.0" \
    "tess-point>=0.9" 
```

Verify Gaia TAP reachability before the full run (this is the one thing the
Chromebook could not do):

```bash
python3 -c "import urllib.request as u; \
print(u.urlopen('https://gea.esac.esa.int/tap-server/tap/tables', timeout=15).status)"
# expect: 200
```

## Step 1 — canonical (pre-registered) build

```bash
python3 pipeline/build_sample_v2.py --self-test      # must pass
python3 pipeline/build_sample_v2.py --dry-run        # frozen params + ADQL
python3 pipeline/build_sample_v2.py --build          # real Gaia DR3 + TIC + tess-point
python3 pipeline/build_sample_v2.py --validate-only --input data/catalog_v2.csv
```

`--build` **raises rather than fabricating** if any service is unreachable. Every
row carries `provenance` + `protocol_sha256`. Do not proceed if it fails; report
the error instead of relaxing a cut.

## Step 2 — sample expansion (the "expand samples" step)

Expansion is a **protocol amendment**, not a silent parameter edit. Editing
`config/protocol.json` changes its SHA-256 and invalidates every downstream
catalog — that is intentional. To expand:

1. Copy the frozen protocol to a versioned amendment:
   ```bash
   cp config/protocol.json config/protocol_v2_1_expanded.json
   ```
2. In the amendment, widen only the pre-registered fields, e.g.:
   - `sample.cone_radius_deg`: 3.0 → 5.0
   - `sample.tmag_max`: 13.0 → 14.0
   - `sample.sectors`: add confirmed sectors from tess-point
   - `controls.min_total_controls`: 300 → 1000
   - add further clusters (Hyades, Taurus, Orion OB1, IC 348, Upper Sco) as
     separate entries with their own Gaia-derived centers/cuts
3. **Re-run `--self-test`, `--dry-run`, then `--build`** against the amendment
   and record its new hash. Never mix catalogs from two protocol versions.
4. Document the amendment BEFORE inspecting any outcome (pre-registration rule).

Do NOT expand by lowering `ruwe_max`, `contamination_ratio_max`, the quality
mask, the sigma clip, or `alpha_global`. Those protect against the exact
artifacts that falsified the original study.

## Step 3 — verification on the B70

```bash
python3 pipeline/verify_expanded_sample.py \
    --catalog data/catalog_v2.csv \
    --probe data/catalog_local_probe.csv
```

The verifier (below) checks: protocol hash consistency, provenance on every row,
duplicate TIC/position handling, sector/camera/CCD validity, target/control ratio,
coordinate plausibility, and agreement between the B70 canonical catalog and the
Chromebook probe on the shared Pleiades members.

## Step 4 — what counts as success

- `validate_catalog()` passes with ≥300 matched controls and 0 provenance gaps.
- ≥90% of the probe's 281 TIC ids appear in the canonical catalog (geometry
  agreement between MAST-TIC and Gaia DR3+TIC).
- No row has a synthetic/placeholder provenance marker.
- All sectors are in the pre-registered set; cameras/CCDs are populated.
- Any disagreement is a **finding**, not something to patch silently.

## Troubleshooting (from the 2026-11-18 B70 run)

- **`ValueError: duplicate tic_id <id>`** — fixed. The validator used to key
  uniqueness on `tic_id` alone, but one target legitimately appears once per
  (sector, camera, ccd). It now keys on the observation tuple, counts unique
  stars for the control ratio, and `build()` defensively dedups repeated rows
  from MAST cone queries. Added a self-test regression for this exact case.
- **A wall of `... not in pre-registered sectors — DROPPED` lines** — this was a
  logging artifact, not a total failure: `assign_sectors` printed only dropped
  stars and never the kept ones. The build had in fact produced
  `Matched controls: 14330`. It now prints a `KEPT / dropped` summary, shows
  only the first 5 drops with the sectors tess-point actually returned, and
  raises a clear error if *no* target survives.
- If the build still ends with an error, paste the full traceback plus the
  `tess-point: N targets KEPT / M dropped` line above it.

## Honest expectation

Per the referee's Section 6, a properly rebuilt sample with matched controls will
most likely yield event rates consistent with controls. That is a **null result**
and the publishable outcome. The B70 run is to verify the sample is real and the
pipeline is calibrated — not to rescue the detection claim.

## Files

- `pipeline/build_sample_v2.py` — canonical Gaia DR3 builder
- `pipeline/local_sample_probe.py` — Chromebook MAST-TIC probe (deviation recorded)
- `pipeline/verify_expanded_sample.py` — cross-catalog verifier
- `config/protocol.json` — frozen v2.0.0 (SHA-256 `fd0c705c…`)
- `PROTOCOL.md` — pre-registered design
