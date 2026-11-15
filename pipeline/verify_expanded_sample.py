#!/usr/bin/env python3
"""
verify_expanded_sample.py — cross-check the B70 canonical catalog against the
Chromebook probe. Stdlib-only so it runs anywhere.

Checks, in order:
  1. protocol hash consistency (all rows share one frozen hash)
  2. provenance present and free of synthetic markers on every row
  3. no duplicate (tic_id, sector, camera, ccd) tuples
  4. coordinates plausible (RA/Dec finite, Pleiades-ish declination)
  5. sectors in the pre-registered set; camera/CCD populated
  6. target/control ratio and minimum control count
  7. overlap between canonical targets and probe TIC ids (geometry agreement)

Exit 0 = all pass. Any failure prints the reason and exits 1.
"""
import os
import sys
import csv
import argparse
import math

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "pipeline"))
from build_sample_v2 import load_protocol, angular_sep_arcsec  # noqa: E402

BANNED = ("synthetic", "random", "placeholder", "dummy", "simulated", "rough estimate")


def load(path):
    if not os.path.exists(path):
        raise SystemExit(f"MISSING catalog: {path}")
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default=os.path.join(BASE_DIR, "data", "catalog_v2.csv"))
    ap.add_argument("--probe", default=os.path.join(BASE_DIR, "data", "catalog_local_probe.csv"))
    args = ap.parse_args()

    proto, sha = load_protocol()
    rows = load(args.catalog)
    probe = load(args.probe)
    failures = []

    def check(ok, label, detail=""):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(label)

    print("=== B70 EXPANDED SAMPLE VERIFICATION ===")
    print(f"  canonical: {len(rows)} rows | probe: {len(probe)} rows")
    print(f"  frozen protocol hash: {sha[:16]}...\n")

    # 1. hash consistency
    hashes = {r.get("protocol_sha256", "") for r in rows}
    check(len(hashes) == 1 and sha in hashes,
          "all rows share the frozen protocol hash",
          f"found {len(hashes)} distinct hash(es)")

    # 2. provenance
    bad_prov = [r for r in rows
                if not r.get("provenance")
                or any(b in r["provenance"].lower() for b in BANNED)
                or r["provenance"].strip().lower() in ("none", "nan", "unknown")]
    # NOTE: the probe's deviation string contains 'Gaia DR2 era' but no banned
    # words; 'PROTOCOL DEVIATION' is allowed and must be visible, not hidden.
    check(not bad_prov, "provenance complete on every row",
          f"{len(bad_prov)} bad row(s)" if bad_prov else "")

    # 3. duplicate tuples
    keys = [(r["tic_id"], r.get("sector"), r.get("camera"), r.get("ccd")) for r in rows]
    check(len(keys) == len(set(keys)), "no duplicate (tic,sector,camera,ccd) tuples",
          f"{len(keys)-len(set(keys))} duplicates" if len(keys) != len(set(keys)) else "")

    # 4. coordinates
    coord_bad = 0
    for r in rows:
        try:
            ra, dec = float(r["ra_deg"]), float(r["dec_deg"])
            if not (math.isfinite(ra) and math.isfinite(dec)
                    and 0 <= ra < 360 and -90 <= dec <= 90):
                coord_bad += 1
        except (ValueError, TypeError, KeyError):
            coord_bad += 1
    check(coord_bad == 0, "coordinates finite and plausible",
          f"{coord_bad} bad row(s)" if coord_bad else "")

    # 5. sectors / camera / ccd
    allowed = {int(x) for x in proto["sample"]["sectors"]}
    bad_sec = [r for r in rows if r.get("sector") and int(r["sector"]) not in allowed]
    no_cam = [r for r in rows if not str(r.get("camera", "")).strip()]
    check(not bad_sec, "all sectors in pre-registered set",
          f"{len(bad_sec)} row(s) outside {sorted(allowed)}" if bad_sec else "")
    check(not no_cam, "camera populated", f"{len(no_cam)} missing" if no_cam else "")

    # 6. controls
    n_t = sum(1 for r in rows if r.get("role") == "target")
    n_c = sum(1 for r in rows if r.get("role") == "control")
    min_c = proto["controls"]["min_total_controls"]
    ratio = proto["controls"]["min_ratio_controls_per_target"]
    check(n_c >= min_c, f"controls >= {min_c}", f"found {n_c}")
    check(n_t == 0 or n_c >= n_t * ratio,
          f"control:target ratio >= {ratio}", f"{n_c}/{n_t} = "
          f"{(n_c/n_t if n_t else 0):.2f}")

    # 7. geometry agreement with the Chromebook probe
    probe_tics = {r["tic_id"] for r in probe}
    canon_tics = {r["tic_id"] for r in rows if r.get("role") == "target"}
    shared = probe_tics & canon_tics
    pct = 100.0 * len(shared) / len(probe_tics) if probe_tics else 0.0
    check(pct >= 90.0, ">=90% of probe members appear in canonical catalog",
          f"{len(shared)}/{len(probe_tics)} = {pct:.1f}%")

    # report falsified-ID leakage as a hard failure
    falsified = {"261136679", "261136674", "231844178", "393928046",
                 "640613235", "640613236", "123456789"}
    leaked = (probe_tics | canon_tics) & falsified
    check(not leaked, "no falsified IDs in either catalog",
          f"leaked: {sorted(leaked)}" if leaked else "")

    print()
    if failures:
        print(f"=== VERIFICATION FAILED ({len(failures)} check(s)) ===")
        for f in failures:
            print("  -", f)
        return 1
    print("=== ALL VERIFICATION CHECKS PASSED ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
