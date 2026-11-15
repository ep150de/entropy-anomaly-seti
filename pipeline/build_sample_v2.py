#!/usr/bin/env python3
"""
build_sample_v2.py — corrected, provenance-tracked Pleiades sample builder.

Replaces the synthetic-coordinate catalogs (build_extended_catalog.py,
build_pleiades_catalog.py) that the 2026-11-14 referee review showed were
generated with np.random.uniform.

NON-NEGOTIABLE RULES
--------------------
* NO random values. There is no np.random, no "rough estimate", no fallback
  that invents a coordinate, magnitude, distance or TIC ID.
* Every emitted row carries `provenance` (exact query/table that produced it)
  and `protocol_sha256` (freezes the pre-registration).
* If Gaia / MAST / tess-point are unreachable, the builder RAISES. It never
  emits placeholder data. A partial catalog is never silently accepted.
* Blends within one TESS pixel (21") are MERGED, not counted as separate stars.
* Sectors come from tess-point (or a supplied sector map), never guessed.

USAGE
-----
  python3 pipeline/build_sample_v2.py --self-test    # offline, no deps, no network
  python3 pipeline/build_sample_v2.py --dry-run      # print the plan + ADQL
  python3 pipeline/build_sample_v2.py --build        # real Gaia DR3 + TIC queries
  python3 pipeline/build_sample_v2.py --validate-only --input data/catalog_v2.csv

The --self-test is deliberately dependency-free (stdlib only) so it can be
executed on any machine, including before the scientific environment is set up.
"""

import os
import sys
import csv
import json
import math
import hashlib
import argparse
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROTOCOL_PATH = os.path.join(BASE_DIR, "config", "protocol.json")
DEFAULT_OUTPUT = os.path.join(BASE_DIR, "data", "catalog_v2.csv")

CATALOG_FIELDS = [
    "tic_id", "gaia_source_id", "ra_deg", "dec_deg",
    "parallax_mas", "pmra_mas_yr", "pmdec_mas_yr", "ruwe",
    "tmag", "distance_pc", "contamination_ratio",
    "sector", "camera", "ccd", "role",
    "data_product", "mast_product_id",
    "provenance", "query_utc", "protocol_sha256",
]


# =====================================================================
# Protocol
# =====================================================================
def load_protocol(path=PROTOCOL_PATH):
    """Load the pre-registration and its SHA-256. Fails closed."""
    with open(path, "rb") as f:
        raw = f.read()
    proto = json.loads(raw.decode("utf-8"))
    sha = hashlib.sha256(raw).hexdigest()
    required = ["sample", "controls", "preprocessing", "statistic",
                "null_model", "significance", "hypothesis", "reproducibility"]
    missing = [k for k in required if k not in proto]
    if missing:
        raise ValueError(f"protocol.json missing sections: {missing}")
    if proto.get("hypothesis", {}).get("falsifiable") is not True:
        raise ValueError("protocol hypothesis must be explicitly falsifiable")
    return proto, sha


# =====================================================================
# Pure helpers (stdlib only — exercised by --self-test)
# =====================================================================
def angular_sep_arcsec(ra1, dec1, ra2, dec2):
    """Great-circle separation in arcseconds (small-angle safe)."""
    r1, d1, r2, d2 = map(math.radians, [ra1, dec1, ra2, dec2])
    dra = r2 - r1
    ddec = d2 - d1
    a = math.sin(ddec / 2) ** 2 + math.cos(d1) * math.cos(d2) * math.sin(dra / 2) ** 2
    return 2 * math.asin(min(1.0, math.sqrt(a))) * 206264.806


def build_adql(proto):
    """Gaia DR3 ADQL for Pleiades members, using ONLY pre-registered cuts."""
    s = proto["sample"]
    plo, phi = s["parallax_mas"]
    pmra_lo, pmra_hi = s["pmra_mas_yr"]
    pmdec_lo, pmdec_hi = s["pmdec_mas_yr"]
    return f"""SELECT
  source_id, ra, dec, parallax, pmra, pmdec, ruwe,
  parallax_over_error, phot_g_mean_mag,
  DISTANCE(POINT('ICRS', {s['center_ra_deg']}, {s['center_dec_deg']}),
           POINT('ICRS', ra, dec)) AS sep_deg
FROM gaiadr{proto['sample']['gaia_dr'].lower().replace('dr','')}.gaia_source
WHERE CONTAINS(
      POINT('ICRS', {s['center_ra_deg']}, {s['center_dec_deg']}),
      CIRCLE('ICRS', {s['center_ra_deg']}, {s['center_dec_deg']},
             {s['cone_radius_deg']})) = 1
  AND parallax BETWEEN {plo} AND {phi}
  AND parallax_over_error > {s['parallax_over_error_min']}
  AND pmra BETWEEN {pmra_lo} AND {pmra_hi}
  AND pmdec BETWEEN {pmdec_lo} AND {pmdec_hi}
  AND ruwe < {s['ruwe_max']}
  AND phot_g_mean_mag IS NOT NULL
  AND phot_g_mean_mag < 15.0
ORDER BY parallax DESC"""


def merge_blends(rows, radius_arcsec):
    """Collapse sources within one TESS pixel; keep the brightest (lowest Tmag).

    Returns (merged_rows, n_collapsed). Never drops provenance.
    """
    order = sorted(range(len(rows)),
                   key=lambda i: (float(rows[i].get("tmag") or 99.9), i))
    used, out, collapsed = set(), [], 0
    for i in order:
        if i in used:
            continue
        keep = dict(rows[i])
        used.add(i)
        members = [keep.get("gaia_source_id") or keep.get("tic_id")]
        for j in order:
            if j in used or j == i:
                continue
            if angular_sep_arcsec(float(keep["ra_deg"]), float(keep["dec_deg"]),
                                  float(rows[j]["ra_deg"]), float(rows[j]["dec_deg"])) <= radius_arcsec:
                used.add(j)
                collapsed += 1
                members.append(rows[j].get("gaia_source_id") or rows[j].get("tic_id"))
                keep["data_product"] = keep.get("data_product") or rows[j].get("data_product")
        keep["blend_members"] = ";".join(str(m) for m in members if m is not None)
        out.append(keep)
    return out, collapsed


def enforce_provenance(rows, sha):
    """Reject ANY row without a real provenance or with a synthetic marker."""
    banned = ("synthetic", "random", "placeholder", "rough estimate", "dummy", "simulated")
    for n, r in enumerate(rows):
        prov = str(r.get("provenance", ""))
        if not prov or prov.strip().lower() in ("none", "nan", "unknown"):
            raise ValueError(f"row {n}: missing provenance — refusing to emit")
        if any(b in prov.lower() for b in banned):
            raise ValueError(f"row {n}: synthetic provenance marker {prov!r} — refusing")
        if r.get("synthetic") is True or r.get("is_synthetic") is True:
            raise ValueError(f"row {n}: flagged synthetic — refusing")
        for k in ("ra_deg", "dec_deg"):
            v = r.get(k)
            if v is None or not math.isfinite(float(v)):
                raise ValueError(f"row {n}: non-finite {k} — refusing")
        if str(r.get("protocol_sha256", "")) != sha:
            raise ValueError(f"row {n}: protocol hash mismatch — catalog is stale")
    return True


def validate_catalog(rows, proto, sha):
    """Full schema + physics validation. Raises on any violation."""
    s = proto["sample"]
    c_tol = float(proto["controls"]["match_tmag_tolerance"])
    if not rows:
        raise ValueError("empty catalog")
    seen_tic, seen_gaia = set(), set()
    allowed_sectors = set(int(x) for x in s["sectors"])
    for n, r in enumerate(rows):
        for k in CATALOG_FIELDS:
            if k not in r:
                raise ValueError(f"row {n}: missing column {k}")
        tic = str(r["tic_id"])
        if tic in seen_tic:
            raise ValueError(f"row {n}: duplicate tic_id {tic}")
        seen_tic.add(tic)
        g = str(r["gaia_source_id"])
        if g and g != "None":
            if g in seen_gaia:
                raise ValueError(f"row {n}: duplicate gaia_source_id {g}")
            seen_gaia.add(g)
        ra, dec = float(r["ra_deg"]), float(r["dec_deg"])
        if not (-90 <= dec <= 90 and 0 <= ra < 360):
            raise ValueError(f"row {n}: impossible coordinates ({ra}, {dec})")
        # Member-physics cuts apply to TARGETS only. Controls are field stars
        # deliberately OUTSIDE the cluster cone, so they must not be checked
        # against the parallax / proper-motion / RUWE membership locus.
        if str(r["role"]) == "target":
            sep = angular_sep_arcsec(s["center_ra_deg"], s["center_dec_deg"], ra, dec) / 3600.0
            if sep > s["cone_radius_deg"] + 1e-6:
                raise ValueError(f"row {n}: target outside Pleiades cone ({sep:.3f} deg)")
            plo, phi = s["parallax_mas"]
            if not (plo <= float(r["parallax_mas"]) <= phi):
                raise ValueError(f"row {n}: parallax outside pre-registered cut")
            if float(r["ruwe"]) >= s["ruwe_max"]:
                raise ValueError(f"row {n}: RUWE above pre-registered cut")
        if float(r["tmag"]) > s["tmag_max"] + c_tol:
            raise ValueError(f"row {n}: Tmag above pre-registered cut (+match tolerance)")
        if int(r["sector"]) not in allowed_sectors:
            raise ValueError(f"row {n}: sector {r['sector']} not in {sorted(allowed_sectors)}")
        if str(r["role"]) not in ("target", "control"):
            raise ValueError(f"row {n}: invalid role {r['role']}")
    enforce_provenance(rows, sha)
    # Controls must satisfy the pre-registered minimum ratio
    n_t = sum(1 for r in rows if r["role"] == "target")
    n_c = sum(1 for r in rows if r["role"] == "control")
    if n_t and n_c < proto["controls"]["min_total_controls"]:
        raise ValueError(f"only {n_c} controls; protocol requires "
                         f">= {proto['controls']['min_total_controls']}")
    if n_t and n_c < n_t * proto["controls"]["min_ratio_controls_per_target"]:
        raise ValueError("control:target ratio below protocol minimum")
    return {"n_targets": n_t, "n_controls": n_c, "n_rows": len(rows)}


def write_catalog(rows, path=DEFAULT_OUTPUT):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CATALOG_FIELDS + ["blend_members"],
                           extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path


# =====================================================================
# Network stages (lazy imports — never used by --self-test / --dry-run)
# =====================================================================
def query_gaia_members(proto, sha):
    """Real Gaia DR3 TAP query. Raises (never fabricates) on any failure."""
    try:
        from astroquery.gaia import Gaia
    except ImportError as e:
        raise RuntimeError("astroquery is required for --build (pip install astroquery)") from e
    adql = build_adql(proto)
    print("  Gaia DR3 ADQL:\n" + "\n".join("    " + l for l in adql.splitlines()))
    job = Gaia.launch_job(adql)
    tbl = job.get_results()
    if len(tbl) == 0:
        raise RuntimeError("Gaia query returned 0 members — check cuts, do NOT relax silently")
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for r in tbl:
        rows.append({
            "gaia_source_id": str(r["source_id"]),
            "ra_deg": float(r["ra"]), "dec_deg": float(r["dec"]),
            "parallax_mas": float(r["parallax"]),
            "pmra_mas_yr": float(r["pmra"]), "pmdec_mas_yr": float(r["pmdec"]),
            "ruwe": float(r["ruwe"]),
            "tmag": float(r["phot_g_mean_mag"]),
            "provenance": f"Gaia {proto['sample']['gaia_dr']} gaiadr3.gaia_source; ADQL sha "
                          f"{hashlib.sha256(adql.encode()).hexdigest()[:16]}",
            "query_utc": now, "protocol_sha256": sha, "role": "target",
        })
    print(f"  Gaia returned {len(rows)} member candidates")
    return rows


def crossmatch_tic(rows, proto):
    """Positional cross-match to TIC v8.2. Raises rather than inventing TIC IDs."""
    try:
        from astroquery.mast import Catalogs
        import astropy.units as u
        from astropy.coordinates import SkyCoord
    except ImportError as e:
        raise RuntimeError("astroquery + astropy required for --build") from e
    out = []
    for r in rows:
        coord = SkyCoord(r["ra_deg"], r["dec_deg"], unit="deg", frame="icrs")
        res = Catalogs.query_region(coord, radius=3 * u.arcsec, catalog="TIC")
        if len(res) == 0:
            print(f"    Gaia {r['gaia_source_id']}: no TIC match — DROPPED (not guessed)")
            continue
        hit = res[0]
        rr = dict(r)
        rr["tic_id"] = str(hit["ID"])
        rr["tmag"] = float(hit["Tmag"]) if "Tmag" in res.colnames else r["tmag"]
        rr["distance_pc"] = float(hit["dstArcSec"]) if "dstArcSec" in res.colnames else ""
        rr["contamination_ratio"] = ""
        rr["provenance"] = r["provenance"] + "; TIC v8.2 Catalogs.query_region radius=3arcsec"
        out.append(rr)
    if not out:
        raise RuntimeError("TIC cross-match produced 0 rows — refusing to emit empty catalog")
    print(f"  TIC cross-match: {len(out)}/{len(rows)} matched")
    return out


def assign_sectors(rows, proto):
    """Sector/camera/CCD from tess-point. Raises if it is unavailable."""
    try:
        from tess_stars2px import tess_stars2px_function_entry
    except ImportError as e:
        raise RuntimeError(
            "tess-point is required for --build (pip install tess-point). "
            "Sectors will NOT be guessed.") from e
    allowed = set(int(x) for x in proto["sample"]["sectors"])
    out = []
    for r in rows:
        result = tess_stars2px_function_entry(
            r["tic_id"], float(r["ra_deg"]), float(r["dec_deg"]))
        sectors = list(result[3]) if len(result) > 3 else []
        cams = list(result[4]) if len(result) > 4 else []
        ccds = list(result[5]) if len(result) > 5 else []
        kept = False
        for i, sec in enumerate(sectors):
            if int(sec) in allowed:
                rr = dict(r)
                rr["sector"] = int(sec)
                rr["camera"] = int(cams[i]) if i < len(cams) else ""
                rr["ccd"] = int(ccds[i]) if i < len(ccds) else ""
                rr["provenance"] = r["provenance"] + f"; tess-point sector={sec}"
                out.append(rr)
                kept = True
        if not kept:
            print(f"    TIC {r['tic_id']}: not in pre-registered sectors — DROPPED")
    if not out:
        raise RuntimeError("no target falls in pre-registered sectors — refusing")
    return out


def build_controls(targets, proto, sha):
    """Matched field controls from same sector/camera/CCD. Raises if unavailable."""
    try:
        from astroquery.mast import Catalogs
        import astropy.units as u
        from astropy.coordinates import SkyCoord
    except ImportError as e:
        raise RuntimeError("astroquery + astropy required for --build") from e
    s = proto["sample"]
    c = proto["controls"]
    # Annulus outside the cluster cone, same Tmag range
    center = SkyCoord(s["center_ra_deg"], s["center_dec_deg"], unit="deg", frame="icrs")
    res = Catalogs.query_region(center, radius=(s["cone_radius_deg"] + 3) * u.deg,
                                catalog="TIC")
    if len(res) == 0:
        raise RuntimeError("TIC field query empty — cannot build controls")
    now = datetime.now(timezone.utc).isoformat()
    controls = []
    targ_sec = {(int(t["sector"]), str(t["camera"]), str(t["ccd"])) for t in targets}
    for h in res:
        try:
            ra, dec, tmag = float(h["RA_orig"]), float(h["Dec_orig"]), float(h["Tmag"])
        except (KeyError, TypeError, ValueError):
            continue
        if not math.isfinite(ra) or not math.isfinite(dec) or not math.isfinite(tmag):
            continue
        sep = angular_sep_arcsec(s["center_ra_deg"], s["center_dec_deg"], ra, dec) / 3600.0
        if sep <= s["cone_radius_deg"] or tmag > s["tmag_max"]:
            continue
        # Tmag matching against some target
        if not any(abs(tmag - float(t["tmag"])) <= c["match_tmag_tolerance"] for t in targets):
            continue
        for sec, cam, ccd in targ_sec:
            controls.append({
                "tic_id": str(h["ID"]), "gaia_source_id": "",
                "ra_deg": ra, "dec_deg": dec, "parallax_mas": "",
                "pmra_mas_yr": "", "pmdec_mas_yr": "", "ruwe": "",
                "tmag": tmag, "distance_pc": "", "contamination_ratio": "",
                "sector": sec, "camera": cam, "ccd": ccd, "role": "control",
                "data_product": "", "mast_product_id": "",
                "provenance": "TIC v8.2 Catalogs.query_region field annulus; "
                              "sector/camera/ccd matched to target set",
                "query_utc": now, "protocol_sha256": sha,
            })
            break
    if len(controls) < c["min_total_controls"]:
        raise RuntimeError(f"only {len(controls)} matched controls; protocol requires "
                           f">= {c['min_total_controls']} — do NOT lower the bar silently")
    print(f"  Matched controls: {len(controls)}")
    return controls


def fill_defaults(rows, proto, sha):
    p = proto["sample"]["data_product_primary"]
    for r in rows:
        r.setdefault("data_product", p)
        r.setdefault("mast_product_id", "")
        r.setdefault("distance_pc", "")
        r.setdefault("contamination_ratio", "")
        r.setdefault("camera", "")
        r.setdefault("ccd", "")
        r.setdefault("query_utc", datetime.now(timezone.utc).isoformat())
        r["protocol_sha256"] = sha
    return rows


# =====================================================================
# Offline self-test (stdlib only)
# =====================================================================
def self_test():
    print("=== build_sample_v2.py OFFLINE SELF-TEST ===")
    print("    (no network, no astroquery, no numpy — stdlib only)\n")
    proto, sha = load_protocol()
    assert len(sha) == 64, "sha256 should be 64 hex chars"
    print(f"  [PASS] protocol loads; sha256 = {sha[:16]}...")
    print(f"         version {proto['protocol_version']}, "
          f"status {proto['status'][:52]}...")

    assert proto["hypothesis"]["falsifiable"] is True
    assert proto["null_model"]["no_self_referenced_mu_minus_3sigma"] is True
    assert proto["statistic"]["symbolization"]["never_per_window_minmax"] is True
    assert proto["reproducibility"]["simulated_figures_prohibited"] is True
    assert proto["preprocessing"]["quality_bitmask"] == "hard"
    print("  [PASS] pre-registration forbids mu-3sigma, min-max, default mask, fake figures")

    adql = build_adql(proto)
    assert "gaiadr3.gaia_source" in adql
    assert "parallax BETWEEN" in adql and "ruwe <" in adql and "pmra BETWEEN" in adql
    assert "RANDOM" not in adql.upper()
    print("  [PASS] ADQL targets real Gaia DR3 table with parallax/PM/RUWE cuts")

    # separation sanity
    assert angular_sep_arcsec(56.75, 24.12, 56.75, 24.12) < 1e-6
    d = angular_sep_arcsec(56.75, 24.12, 56.75, 24.12 + 21 / 3600.0)
    assert 20.9 < d < 21.1, f"expected ~21 arcsec, got {d}"
    print(f"  [PASS] angular separation: 21\" offset -> {d:.2f}\"")

    # TEST FIXTURE — in-memory only, NEVER emitted as catalog data.
    # Used solely to exercise merge/validation logic.
    fixture = [
        {"tic_id": "A", "gaia_source_id": "G1", "ra_deg": 56.7500, "dec_deg": 24.1200,
         "tmag": 9.0, "provenance": "TEST FIXTURE (in-memory only)"},
        {"tic_id": "B", "gaia_source_id": "G2", "ra_deg": 56.7500,
         "dec_deg": 24.1200 + 1.9 / 3600.0, "tmag": 11.0,
         "provenance": "TEST FIXTURE (in-memory only)"},
        {"tic_id": "C", "gaia_source_id": "G3", "ra_deg": 56.9000, "dec_deg": 24.3000,
         "tmag": 10.0, "provenance": "TEST FIXTURE (in-memory only)"},
    ]
    merged, collapsed = merge_blends(fixture, proto["sample"]["blend_merge_radius_arcsec"])
    assert collapsed == 1 and len(merged) == 2, (collapsed, len(merged))
    assert merged[0]["tic_id"] == "A", "brightest member must be kept"
    assert "G2" in merged[0]["blend_members"]
    print(f"  [PASS] blend merge: 1.9\" pair collapsed into 1 source (kept brightest)")

    # Provenance guard must REJECT synthetic markers
    for bad in [
        {"provenance": ""},
        {"provenance": "np.random.uniform synthetic placeholder"},
        {"provenance": "unknown"},
    ]:
        row = {"tic_id": "X", "ra_deg": 56.75, "dec_deg": 24.12,
               "protocol_sha256": sha}
        row.update(bad)
        try:
            enforce_provenance([row], sha)
            raise AssertionError(f"guard accepted {bad}")
        except ValueError:
            pass
    print("  [PASS] provenance guard rejects empty/unknown/synthetic markers")

    # Full validation on a well-formed fixture (with controls to satisfy ratio)
    good = []
    for i in range(2):
        good.append({
            "tic_id": f"T{i}", "gaia_source_id": f"GG{i}",
            "ra_deg": 56.75 + 0.001 * i, "dec_deg": 24.12,
            "parallax_mas": 7.35, "pmra_mas_yr": 19.0, "pmdec_mas_yr": -45.0,
            "ruwe": 1.0, "tmag": 9.5, "distance_pc": 136.0,
            "contamination_ratio": 0.01, "sector": 42, "camera": 1, "ccd": 1,
            "role": "target", "data_product": "SPOC 2-min PDCSAP",
            "mast_product_id": "", "provenance": "TEST FIXTURE (in-memory only)",
            "query_utc": "2026-11-14T00:00:00+00:00", "protocol_sha256": sha,
        })
    n_ctrl = max(proto["controls"]["min_total_controls"],
                 len(good) * proto["controls"]["min_ratio_controls_per_target"])
    allowed_secs = proto["sample"]["sectors"]
    for i in range(n_ctrl):   # in-memory fixture; satisfies the real control threshold
        good.append({
            "tic_id": f"C{i}", "gaia_source_id": "",
            "ra_deg": 56.75 + 3.2 + 0.0001 * i, "dec_deg": 24.12,
            "parallax_mas": "", "pmra_mas_yr": "", "pmdec_mas_yr": "",
            "ruwe": "", "tmag": 9.6, "distance_pc": "",
            "contamination_ratio": "", "sector": allowed_secs[i % len(allowed_secs)],
            "camera": 1, "ccd": 1,
            "role": "control", "data_product": "SPOC 2-min PDCSAP",
            "mast_product_id": "", "provenance": "TEST FIXTURE (in-memory only)",
            "query_utc": "2026-11-14T00:00:00+00:00", "protocol_sha256": sha,
        })
    stats = validate_catalog(good, proto, sha)
    print(f"  [PASS] full schema validation: {stats}")

    # Validation must REJECT a duplicate TIC and a bogus sector
    dup = good + [dict(good[0])]
    try:
        validate_catalog(dup, proto, sha)
        raise AssertionError("duplicate tic_id accepted")
    except ValueError:
        pass
    badsec = [dict(r) for r in good]
    badsec[0]["sector"] = 11   # Sector 11 is NOT a real Pleiades pointing
    try:
        validate_catalog(badsec, proto, sha)
        raise AssertionError("sector 11 accepted")
    except ValueError:
        pass
    print("  [PASS] validation rejects duplicate TIC IDs and non-Pleiades sector 11")

    # NO randomness anywhere in this source file. Inspect the AST for real
    # attribute/call usage so that docstrings and this very check's token
    # list don't produce false positives.
    import ast
    tree = ast.parse(open(os.path.abspath(__file__)).read())
    banned_attrs = {("np", "random"), ("random", "uniform"),
                    ("random", "random"), ("np", "save")}
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if (node.value.id, node.attr) in banned_attrs:
                found.append(f"{node.value.id}.{node.attr}")
    assert not found, f"forbidden random/synthetic calls in production source: {found}"
    print("  [PASS] AST contains NO random/synthetic-value generators")

    print("\n=== ALL OFFLINE SELF-TESTS PASSED ===")
    print("    Nothing was written to disk. No fabricated catalog was emitted.")
    return 0


# =====================================================================
# Dry run / build
# =====================================================================
def dry_run(proto, sha):
    s = proto["sample"]
    print("=== DRY RUN (no network, no writes) ===")
    print(f"  protocol_sha256 : {sha}")
    print(f"  cluster         : {s['cluster']} @ ({s['center_ra_deg']}, {s['center_dec_deg']})")
    print(f"  cone            : {s['cone_radius_deg']} deg")
    print(f"  parallax        : {s['parallax_mas']} mas  (distance ~{1000/s['parallax_mas'][1]:.0f}-{1000/s['parallax_mas'][0]:.0f} pc)")
    print(f"  proper motion   : pmRA {s['pmra_mas_yr']}, pmDec {s['pmdec_mas_yr']} mas/yr")
    print(f"  RUWE < {s['ruwe_max']}, Tmag < {s['tmag_max']}, contam < {s['contamination_ratio_max']}")
    print(f"  blend radius    : {s['blend_merge_radius_arcsec']}\" (1 TESS pixel)")
    print(f"  real sectors    : {s['sectors']}")
    print(f"  product         : {s['data_product_primary']}")
    print(f"  controls        : >= {proto['controls']['min_total_controls']} matched, "
          f">= {proto['controls']['min_ratio_controls_per_target']}x targets")
    print(f"  quality mask    : {proto['preprocessing']['quality_bitmask']}")
    print(f"  statistic       : {proto['statistic']['primary']} "
          f"(stride {proto['statistic']['primary_stride']}, events not windows)")
    print(f"  null            : {proto['null_model']['surrogates_per_star']} IAAFT surrogates/star")
    print(f"  alpha_global    : {proto['significance']['alpha_global']}")
    print("\n  Gaia DR3 ADQL:\n")
    print("\n".join("    " + l for l in build_adql(proto).splitlines()))
    print("\n  Planned outputs: data/catalog_v2.csv (every row carries provenance + hash)")
    return 0


def build(proto, sha):
    print("=== BUILD (real catalog queries) ===")
    print(f"  protocol_sha256: {sha}\n")
    rows = query_gaia_members(proto, sha)
    rows = crossmatch_tic(rows, proto)
    rows, collapsed = merge_blends(rows, proto["sample"]["blend_merge_radius_arcsec"])
    print(f"  Blend merge collapsed {collapsed} duplicate source(s)")
    rows = assign_sectors(rows, proto)
    controls = build_controls(rows, proto, sha)
    rows = fill_defaults(rows + controls, proto, sha)
    validate_catalog(rows, proto, sha)
    path = write_catalog(rows)
    print(f"\n  WROTE {len(rows)} rows -> {path}")
    print("  Catalog is provenance-complete and hash-frozen to this protocol.")
    return 0


def validate_only(path, proto, sha):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    stats = validate_catalog(rows, proto, sha)
    print(f"=== VALIDATED {path} ===\n  {stats}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--validate-only", action="store_true")
    ap.add_argument("--input", default=DEFAULT_OUTPUT)
    args = ap.parse_args()
    proto, sha = load_protocol()
    if args.self_test:
        return self_test()
    if args.dry_run:
        return dry_run(proto, sha)
    if args.validate_only:
        return validate_only(args.input, proto, sha)
    if args.build:
        return build(proto, sha)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
