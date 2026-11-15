#!/usr/bin/env python3
"""
local_sample_probe.py — LOCAL FEASIBILITY PROBE (Chromebook), NOT the registered study.

WHY THIS EXISTS
---------------
The canonical builder pipeline/build_sample_v2.py queries Gaia DR3 TAP. That
endpoint is UNREACHABLE from the agent's Chromebook (verified: timeout to
gea.esac.esa.int). MAST *is* reachable, and TIC v8.2 carries Gaia-derived
astrometry (plx, pmRA, pmDEC, GAIA source id, contratio). So this probe builds
a REAL Pleiades-member candidate catalog from MAST TIC + tess-point, with full
provenance, using the FROZEN cuts from config/protocol.json.

DEVIATION FROM PROTOCOL (explicit, must be amended before use in the study):
  * Astrometry source = TIC v8.2 Gaia-derived columns, NOT a live Gaia DR3 TAP
    query. TIC v8 is based on Gaia DR2, so parallax/PM are DR2-era values.
  * RUWE is not in TIC; `gaiaqflag` is used only as a reported quality field.
  * TARGETS ONLY. Matched controls and the full validate_catalog() gate are
    deliberately deferred to the B70 workstation run (see B70_VERIFICATION.md).
  * This output is a PROBE, never a result. It is not cited, not a detection.

It imports the canonical builder's pure helpers so the cuts and geometry are
literally identical, and never edits config/protocol.json (hash stays frozen).

USAGE
  python3 pipeline/local_sample_probe.py --run
  python3 pipeline/local_sample_probe.py --dry-run
"""
import os
import sys
import csv
import json
import argparse
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "pipeline"))

from build_sample_v2 import (  # noqa: E402
    load_protocol, angular_sep_arcsec, merge_blends, enforce_provenance,
    CATALOG_FIELDS,
)

OUT = os.path.join(BASE_DIR, "data", "catalog_local_probe.csv")

DEVIATION = ("PROTOCOL DEVIATION (local Chromebook probe): astrometry from "
             "MAST TIC v8.2 Gaia-derived columns (Gaia DR2 era), not live "
             "Gaia DR3 TAP (unreachable on this host); RUWE unavailable -> "
             "gaiaqflag reported; TARGETS ONLY; NOT a study result")


def run(proto, sha):
    import numpy as np
    from astroquery.mast import Catalogs
    from astropy.coordinates import SkyCoord
    import astropy.units as u
    from tess_stars2px import tess_stars2px_function_entry

    s = proto["sample"]
    print("=== LOCAL MAST-TIC SAMPLE PROBE ===")
    print("  " + DEVIATION)
    print(f"  frozen protocol_sha256: {sha}\n")

    center = SkyCoord(s["center_ra_deg"], s["center_dec_deg"],
                      unit="deg", frame="icrs")
    print(f"  Querying MAST TIC, {s['cone_radius_deg']} deg cone "
          f"(~100 s, ~250k rows)...")
    t = Catalogs.query_region(center, radius=s["cone_radius_deg"] * u.deg,
                              catalog="Tic")
    print(f"  returned {len(t)} rows")

    def col(name):
        return np.array(t[name], dtype=float)

    plx, pmra, pmdec = col("plx"), col("pmRA"), col("pmDEC")
    tmag, contr = col("Tmag"), col("contratio")
    plo, phi = s["parallax_mas"]
    ra_lo, ra_hi = s["pmra_mas_yr"]
    dec_lo, dec_hi = s["pmdec_mas_yr"]
    sel = ((plx >= plo) & (plx <= phi) &
           (pmra >= ra_lo) & (pmra <= ra_hi) &
           (pmdec >= dec_lo) & (pmdec <= dec_hi) &
           (tmag <= s["tmag_max"]) &
           (contr < s["contamination_ratio_max"]))
    print(f"  after frozen parallax/PM/Tmag/contamination cuts: {int(sel.sum())}")

    sub = t[sel]
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for r in sub:
        rows.append({
            "tic_id": str(r["ID"]), "gaia_source_id": str(r["GAIA"]),
            "ra_deg": float(r["ra"]), "dec_deg": float(r["dec"]),
            "parallax_mas": float(r["plx"]),
            "pmra_mas_yr": float(r["pmRA"]), "pmdec_mas_yr": float(r["pmDEC"]),
            "ruwe": "", "tmag": float(r["Tmag"]),
            "distance_pc": float(r["d"]) if r["d"] else "",
            "contamination_ratio": float(r["contratio"]),
            "provenance": "MAST TIC v8.2 Catalogs.query_region cone "
                          f"{s['cone_radius_deg']}deg; {DEVIATION}",
            "query_utc": now, "protocol_sha256": sha, "role": "target",
        })
    if not rows:
        raise RuntimeError("0 members survived cuts — refusing to emit")

    rows, collapsed = merge_blends(rows, s["blend_merge_radius_arcsec"])
    print(f"  blend merge (21\" = 1 TESS pixel): collapsed {collapsed}")

    allowed = set(int(x) for x in s["sectors"])
    out = []
    for r in rows:
        try:
            res = tess_stars2px_function_entry(
                r["tic_id"], r["ra_deg"], r["dec_deg"])
        except Exception as e:
            print(f"    TIC {r['tic_id']}: tess-point failed ({type(e).__name__}) — dropped")
            continue
        secs, cams, ccds = list(res[3]), list(res[4]), list(res[5])
        for i, sec in enumerate(secs):
            if int(sec) in allowed:
                rr = dict(r)
                rr["sector"] = int(sec)
                rr["camera"] = int(cams[i]) if i < len(cams) else ""
                rr["ccd"] = int(ccds[i]) if i < len(ccds) else ""
                rr["data_product"] = s["data_product_primary"]
                rr["mast_product_id"] = ""
                rr["provenance"] = r["provenance"] + f"; tess-point sector={sec}"
                out.append(rr)
    if not out:
        raise RuntimeError("no member in pre-registered sectors — refusing")

    enforce_provenance(out, sha)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CATALOG_FIELDS + ["blend_members"],
                           extrasaction="ignore")
        w.writeheader()
        for r in out:
            w.writerow(r)

    n_tic = len({r["tic_id"] for r in out})
    secs = sorted({int(r["sector"]) for r in out})
    print(f"\n  WROTE {len(out)} rows ({n_tic} unique TIC ids) -> {OUT}")
    print(f"  sectors represented: {secs}")
    print(f"  cameras: {sorted({str(r['camera']) for r in out})}")
    print("\n  PROBE COMPLETE. This is a real, provenance-tracked catalog but")
    print("  it is NOT the registered study catalog and NOT a result.")
    return 0


def dry_run(proto, sha):
    s = proto["sample"]
    print("=== LOCAL PROBE DRY RUN ===")
    print("  " + DEVIATION)
    print(f"  protocol_sha256: {sha}")
    print(f"  MAST TIC cone: ({s['center_ra_deg']}, {s['center_dec_deg']}) "
          f"r={s['cone_radius_deg']} deg")
    print(f"  cuts: plx {s['parallax_mas']}, pmRA {s['pmra_mas_yr']}, "
          f"pmDec {s['pmdec_mas_yr']}, Tmag<{s['tmag_max']}, "
          f"contratio<{s['contamination_ratio_max']}")
    print(f"  blend merge: {s['blend_merge_radius_arcsec']}\"")
    print(f"  sectors kept: {s['sectors']} (via tess-point)")
    print(f"  output: {OUT}")
    print("  requires: astroquery, astropy, tess-point, numpy (Hermes venv has them)")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    proto, sha = load_protocol()
    if args.dry_run:
        return dry_run(proto, sha)
    if args.run:
        return run(proto, sha)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
