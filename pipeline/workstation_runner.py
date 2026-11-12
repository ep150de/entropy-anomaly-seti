#!/usr/bin/env python3
"""
Entropy Anomaly SETI - Workstation Pipeline (Phase 3)

METRIC ALIGNMENT (user decision: option 1)
-----------------------------------------
This runner uses the EXACT same metric as the published Phase 1/2 results
in pipeline/tess_batch_analyzer.py and pipeline/single_star_batch.py:

    Kolmogorov complexity K(S) via zlib compression of quantized flux
    WINDOW_SIZE = 150, STEP_SIZE = 10 (overlapping windows)
    anomaly  =  K(S) < mean(K) - 3*std(K)

so Phase 3 numbers are directly comparable to Phase 1/2.

History of fixes
----------------
* Broken numba KS statistic (constant 1/sqrt(n)) -> zero anomalies. Replaced.
* NO numba (caused "no implementation found for 'numpy.save'" in workers).
* NO np.save/np.load caching.
* ThreadPoolExecutor: TESS downloads are I/O-bound.
* setup_and_run.sh no longer generates this file via heredoc.
* FFI fallback now queries TessCut WITHOUT a sector filter (returns every
  sector that actually observed the star). The catalog hardcodes sector=11
  for all targets, which does not cover Orion OB1 (Dec ~ -5 deg) or several
  bright Hyades standards -- those targets need their real observed sectors.
* Every failed target now records WHY in the DB `error` column.
* --retry-missing re-runs only previously failed targets and merges them
  into a complete results DB, avoiding a full 18-target re-download.

Usage
-----
  python3 pipeline/workstation_runner.py                    # full 18-target run
  python3 pipeline/workstation_runner.py --test            # 2 targets, verbose
  python3 pipeline/workstation_runner.py --retry-missing   # only failed targets
  python3 pipeline/workstation_runner.py --verbose         # full run, verbose
  python3 pipeline/workstation_runner.py --sector 11       # override sector
  python3 pipeline/workstation_runner.py --workers 8
"""

import os
import glob
import time
import zlib
import sqlite3
import argparse
import warnings
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---- Phase 1/2 constants (identical to tess_batch_analyzer.py) ----
WINDOW_SIZE = 150
STEP_SIZE = 10
ANOMALY_SIGMA = 3.0


# ===================================================================
# METRIC -- verbatim Phase 1/2 implementation
# ===================================================================
def compute_ks(flux_array, levels=256):
    """Kolmogorov complexity via zlib compression."""
    clean = flux_array[~np.isnan(flux_array)]
    if len(clean) == 0:
        return 1.0
    fmin, fmax = np.min(clean), np.max(clean)
    if fmax == fmin:
        return 1.0
    norm = (clean - fmin) / (fmax - fmin)
    quant = (norm * (levels - 1)).astype(np.uint8).tobytes()
    return len(zlib.compress(quant, level=9)) / len(quant)


def sliding_window_kcomplexity(flux, window_size=WINDOW_SIZE, step_size=STEP_SIZE):
    """Sliding window Kolmogorov complexity scan (overlapping windows)."""
    n_windows = (len(flux) - window_size) // step_size + 1
    comps = []
    for i in range(n_windows):
        start = i * step_size
        window = flux[start:start + window_size]
        comps.append(compute_ks(window))
    return np.array(comps)


def shannon_entropy(window, num_bins=50):
    """Supplementary diagnostic only -- NOT used for anomaly detection."""
    x = np.asarray(window, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 2:
        return 0.0
    hist, _ = np.histogram(x, bins=num_bins)
    probs = hist[hist > 0].astype(float)
    probs /= probs.sum()
    return float(-np.sum(probs * np.log2(probs)))


# ===================================================================
# DATA ACQUISITION (lightkurve 2.x, mirrors Phase 1/2 safe_download)
# ===================================================================
def _flux_from_lightcurve(lc):
    """Return normalized, NaN-free flux -- same as lc.remove_nans().normalize()."""
    arr = None
    try:
        arr = np.asarray(lc.flux.value, dtype=float)
    except Exception:
        try:
            arr = np.asarray(lc.flux, dtype=float)
        except Exception:
            pass
    if arr is None:
        colnames = [str(c).lower() for c in lc.colnames]
        for candidate in ("pdcsap_flux", "sap_flux", "flux"):
            if candidate in colnames:
                col = lc.colnames[colnames.index(candidate)]
                try:
                    arr = np.asarray(lc[col].value, dtype=float)
                except Exception:
                    arr = np.asarray(lc[col], dtype=float)
                if arr is not None:
                    break
    if arr is None:
        return None
    arr = arr[np.isfinite(arr)]
    if len(arr) <= WINDOW_SIZE:
        return None
    med = np.median(arr)
    if med == 0 or not np.isfinite(med):
        return None
    return arr / med


def _download_flux(search, max_products=3, verbose=False, log=None):
    """Try the first few search products with Phase 1/2 download settings."""
    for i in range(min(max_products, len(search))):
        try:
            lc = search[i].download(quality_bitmask="default")
            arr = _flux_from_lightcurve(lc)
            if arr is not None and len(arr) > WINDOW_SIZE:
                return arr
        except Exception as e:
            if verbose and log:
                log(f"2min product {i}: {type(e).__name__}: {str(e)[:90]}")
    return None


def fetch_flux(tic_id, sector=11, verbose=False, max_sectors=6):
    """Download a TESS light curve. Returns (flux, sector, source, reasons)."""
    import lightkurve as lk

    reasons = []

    def log(msg):
        reasons.append(msg)
        if verbose:
            print("      " + msg, flush=True)

    sectors_to_try = [sector] + [s for s in range(1, 70) if s != sector]

    # ---- 1) 2-min / 20-s cadence products, catalog sector first ----
    for try_sector in sectors_to_try[:max_sectors]:
        try:
            search = lk.search_lightcurve(f"TIC {tic_id}", mission="TESS", sector=try_sector)
            if len(search) == 0:
                log(f"s{try_sector}: 0 products")
                continue
            log(f"s{try_sector}: {len(search)} product(s)")
            arr = _download_flux(search, verbose=verbose, log=log)
            if arr is not None:
                return arr, try_sector, "lightcurve", reasons
            log(f"s{try_sector}: download/flux extraction failed")
        except Exception as e:
            log(f"s{try_sector}: {type(e).__name__}: {str(e)[:90]}")

    # ---- 1b) unfiltered search (any sector / any author) ----
    try:
        search = lk.search_lightcurve(f"TIC {tic_id}", mission="TESS")
        log(f"unfiltered: {len(search)} product(s)")
        if len(search) > 0:
            arr = _download_flux(search, max_products=8, verbose=verbose, log=log)
            if arr is not None:
                return arr, sector, "lightcurve-any", reasons
            log("unfiltered: download/flux extraction failed")
    except Exception as e:
        log(f"unfiltered: {type(e).__name__}: {str(e)[:90]}")

    # ---- 2) FFI / TessCut: NO sector filter -> all sectors that saw star ----
    log("FFI: querying TessCut for ALL observed sectors")
    try:
        try:
            from lightkurve import search_tesscut
        except ImportError:
            from lightkurve import TesscutClass
            search_tesscut = TesscutClass().search
        res = search_tesscut(f"TIC {tic_id}")
        n_sectors = len(res)
        log(f"FFI: {n_sectors} sector(s) in field of view")
        for i in range(min(n_sectors, 10)):
            try:
                tpf = res[i].download(cutout_size=11)
                if tpf is None:
                    continue
                try:
                    lc = tpf.to_lightcurve(aperture_mask="threshold")
                except Exception:
                    mask = tpf.create_threshold_mask(threshold=3)
                    lc = tpf.to_lightcurve(aperture_mask=mask)
                arr = _flux_from_lightcurve(lc)
                if arr is not None:
                    return arr, sector, "ffi", reasons
                log(f"FFI sector#{i}: too few usable cadences")
            except Exception as e:
                log(f"FFI sector#{i}: {type(e).__name__}: {str(e)[:90]}")
        if n_sectors == 0:
            log("FFI: star not in TESS field of view in any sector")
    except Exception as e:
        log(f"FFI unavailable: {type(e).__name__}: {str(e)[:90]}")

    return None, sector, "none", reasons


# ===================================================================
# PER-TARGET ANALYSIS
# ===================================================================
def process_single_star(tic_id, sector=11, window_size=WINDOW_SIZE, verbose=False):
    try:
        flux, used_sector, source, reasons = fetch_flux(tic_id, sector=sector, verbose=verbose)
        if flux is None:
            detail = "; ".join(reasons[-6:]) if reasons else "no products found"
            return {"tic_id": tic_id, "status": "no_data", "anomalies": 0,
                    "mean_ks": np.nan, "error": "No TESS data | " + detail[:400]}

        n_cadences = len(flux)
        comp = sliding_window_kcomplexity(flux, window_size, STEP_SIZE)
        if len(comp) < 5:
            return {"tic_id": tic_id, "status": "insufficient_data", "anomalies": 0,
                    "mean_ks": np.nan, "cadences": n_cadences}

        mean_k = float(np.mean(comp))
        std_k = float(np.std(comp))
        threshold = mean_k - ANOMALY_SIGMA * std_k
        anomalies = int(np.sum(comp < threshold))

        ent = [shannon_entropy(flux[i * STEP_SIZE:i * STEP_SIZE + window_size])
               for i in range(len(comp))]

        return {
            "tic_id": tic_id,
            "status": "ok",
            "cadences": n_cadences,
            "windows": len(comp),
            "anomalies": anomalies,
            "mean_ks": mean_k,
            "std_ks": std_k,
            "threshold": float(threshold),
            "mean_entropy": float(np.mean(ent)),
            "is_anomalous": anomalies > 0,
            "sector": used_sector,
            "source": source,
        }
    except Exception as e:
        return {"tic_id": tic_id, "status": "error",
                "error": f"{type(e).__name__}: {str(e)[:180]}", "anomalies": 0}


# ===================================================================
# HELPERS
# ===================================================================
def _latest_db():
    dbs = sorted(glob.glob(os.path.join(BASE_DIR, "results", "workstation_run_*.db")))
    return dbs[-1] if dbs else None


def _write_db(df, prefix="workstation_run"):
    os.makedirs(os.path.join(BASE_DIR, "results"), exist_ok=True)
    db_path = os.path.join(
        BASE_DIR, "results",
        f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
    conn = sqlite3.connect(db_path)
    df.to_sql("results", conn, if_exists="replace", index=False)
    conn.close()
    return db_path


def _print_summary(df, db_path, t0):
    total_anom = df[df["status"] == "ok"]["anomalies"].sum()
    print("\n=== WORKSTATION RUN SUMMARY ===")
    print(f"Targets processed : {len(df)}")
    print(f"Successful (ok)   : {len(df[df['status']=='ok'])}")
    print(f"No data           : {len(df[df['status']=='no_data'])}")
    print(f"Insufficient data : {len(df[df['status']=='insufficient_data'])}")
    print(f"Errors            : {len(df[df['status']=='error'])}")
    print(f"Total anomalies   : {total_anom}")
    print(f"Results saved to  : {db_path}")
    if len(df):
        print("\nCluster breakdown (all targets; no-data rows count as 0):")
        print(df.groupby("cluster")["anomalies"].agg(["sum", "count", "mean"]).to_string())
    missing = df[df["status"] != "ok"]
    if len(missing):
        print("\nTargets still missing (with reasons):")
        for r in missing.itertuples():
            print(f"  TIC {r.tic_id}: {str(getattr(r, 'error', ''))[:160]}")
    print("\nElapsed: %.1f min" % ((time.time() - t0) / 60))


# ===================================================================
# MAIN
# ===================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="2 targets, sequential, verbose")
    ap.add_argument("--retry-missing", action="store_true",
                    help="Re-run only failed targets from the latest DB and merge results")
    ap.add_argument("--verbose", action="store_true", help="Verbose download logs")
    ap.add_argument("--sector", type=int, default=None, help="Override catalog sector")
    ap.add_argument("--workers", type=int, default=None, help="Parallel workers")
    args = ap.parse_args()

    catalog_path = os.path.join(BASE_DIR, "data", "expanded_star_catalog.csv")
    catalog = pd.read_csv(catalog_path)
    catalog["tic_id"] = catalog["tic_id"].astype(int)
    cat_by_tic = catalog.set_index("tic_id")

    ordered = pd.concat([catalog[catalog["priority"] >= 2],
                         catalog[catalog["priority"] == 1]], ignore_index=True)

    targets = []
    for _, row in ordered.iterrows():
        sec = args.sector if args.sector else int(row.get("sector", 11))
        targets.append((int(row["tic_id"]), sec))

    # ---- retry-missing: restrict to previously failed TICs ----
    prev_df = None
    if args.retry_missing:
        db = _latest_db()
        if not db:
            print("No prior results DB found. Run the full pipeline first.")
            return
        conn = sqlite3.connect(db)
        prev_df = pd.read_sql("SELECT * FROM results", conn)
        conn.close()
        prev_df["tic_id"] = prev_df["tic_id"].astype(int)
        failed = set(prev_df[prev_df["status"] != "ok"]["tic_id"])
        if not failed:
            print("No missing targets in the latest DB -- nothing to retry.")
            return
        targets = [(tic, int(cat_by_tic.loc[tic, "sector"]) if tic in cat_by_tic.index else 11)
                   for tic in sorted(failed)]
        args.verbose = True
        print(f"=== RETRY MODE: {len(targets)} previously failed targets "
              f"(from {os.path.basename(db)}) ===\n")

    sequential = args.test or args.retry_missing
    n_workers = 1 if sequential else (args.workers or min(12, os.cpu_count() or 8))
    if args.test:
        targets = targets[:2]
        print("=== TEST MODE: 2 targets, sequential, verbose ===\n")

    print(f"Metric: zlib Kolmogorov complexity | window={WINDOW_SIZE} "
          f"step={STEP_SIZE} sigma={ANOMALY_SIGMA}")
    print(f"Loaded {len(targets)} targets | workers={n_workers}", flush=True)
    t0 = time.time()
    results = []

    if sequential:
        for tic, sec in targets:
            print(f"[TIC {tic}] sector {sec} ...", flush=True)
            r = process_single_star(tic, sector=sec, verbose=args.verbose)
            print(f"  -> {r['status']}: {r.get('anomalies',0)} anomalies "
                  f"| {str(r.get('error',''))[:120]}", flush=True)
            results.append(r)
    else:
        print(f"Processing {len(targets)} targets with {n_workers} workers...", flush=True)
        with ThreadPoolExecutor(max_workers=n_workers) as ex:
            futs = {ex.submit(process_single_star, tic, sec, WINDOW_SIZE, args.verbose): tic
                    for tic, sec in targets}
            for i, fut in enumerate(as_completed(futs), 1):
                r = fut.result()
                results.append(r)
                elapsed = time.time() - t0
                rate = i / elapsed * 60 if elapsed > 0 else 0
                remaining = (len(targets) - i) / rate if rate > 0 else 0
                icon = "*" if r.get("anomalies", 0) > 0 else " "
                extra = ""
                if r.get("status") != "ok":
                    extra = f" [{r.get('status')}: {str(r.get('error',''))[:50]}]"
                print(f"  [{i}/{len(targets)}] {icon} TIC {r['tic_id']}: "
                      f"{r.get('anomalies',0)} anomalies | "
                      f"ETA {remaining:.1f} min{extra}", flush=True)

    if args.test:
        print("\n=== TEST COMPLETE ===")
        return

    df = pd.DataFrame(results)
    cluster_map = dict(zip(catalog["tic_id"], catalog["cluster"]))
    df["cluster"] = df["tic_id"].map(cluster_map).fillna("unknown")

    # Merge retried results over the previous complete set
    if args.retry_missing and prev_df is not None:
        failed_ids = set(df["tic_id"])
        kept = prev_df[~prev_df["tic_id"].isin(failed_ids)].copy()
        if "cluster" not in kept.columns:
            kept["cluster"] = kept["tic_id"].map(cluster_map).fillna("unknown")
        df = pd.concat([kept, df], ignore_index=True)
        print(f"\nMerged: {len(kept)} prior ok + {len(results)} retried = {len(df)} total")

    db_path = _write_db(df)
    _print_summary(df, db_path, t0)


if __name__ == "__main__":
    main()
