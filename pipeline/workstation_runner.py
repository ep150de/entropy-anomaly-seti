#!/usr/bin/env python3
"""
Entropy Anomaly SETI - Workstation Pipeline (clean standalone runner)

Design notes
------------
* Pure numpy/scipy. NO numba (it caused "no implementation found for
  'numpy.save'" errors inside multiprocessing workers and gave no benefit
  here -- WSL does not expose the Arc GPU to lightkurve).
* NO np.save/np.load caching (numba + pickling conflict).
* The KS statistic is DATA-DEPENDENT (KS test of each window against a
  normal distribution). The previous JIT version sorted the flux and then
  ignored it, returning a constant ~1/sqrt(n) for every window, which is
  why every target reported 0 anomalies.
* ThreadPoolExecutor: TESS downloads are I/O-bound, threads avoid the
  pickling/spawn problems of ProcessPool on WSL/Windows.
* setup_and_run.sh no longer GENERATES this file via heredoc. It is a
  committed, syntax-checked source file. That removes the whole class of
  "break outside loop" / indentation bugs from earlier attempts.

Usage
-----
  python3 pipeline/workstation_runner.py                 # full 18-target run
  python3 pipeline/workstation_runner.py --test         # 2 targets, verbose
  python3 pipeline/workstation_runner.py --verbose      # full run, verbose
  python3 pipeline/workstation_runner.py --sector 11    # override sector
  python3 pipeline/workstation_runner.py --workers 8
"""

import os
import sys
import time
import sqlite3
import argparse
import warnings
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
from scipy.special import ndtr  # vectorized standard-normal CDF

warnings.filterwarnings("ignore")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ===================================================================
# METRICS (pure numpy / scipy -- data dependent)
# ===================================================================
def ks_ratio(window):
    """KS statistic of a window against N(0,1) after z-scoring, scaled by sqrt(n).

    A window whose flux distribution is close to Gaussian yields a small value;
    structured / non-Gaussian (information-bearing) windows yield a large one.
    """
    x = np.asarray(window, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 10:
        return 0.0
    mu = x.mean()
    sigma = x.std()
    if sigma <= 0 or not np.isfinite(sigma):
        return 0.0
    z = np.sort((x - mu) / sigma)
    cdf_theory = ndtr(z)
    cdf_empirical = np.arange(1, n + 1) / n
    ks = np.max(np.abs(cdf_empirical - cdf_theory))
    return float(ks * np.sqrt(n))


def shannon_entropy(window, num_bins=50):
    """Shannon entropy (bits) of the window's value distribution."""
    x = np.asarray(window, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 2:
        return 0.0
    hist, _ = np.histogram(x, bins=num_bins)
    probs = hist[hist > 0].astype(float)
    probs /= probs.sum()
    return float(-np.sum(probs * np.log2(probs)))


# ===================================================================
# DATA ACQUISITION (lightkurve, robust across 2.x versions)
# ===================================================================
def _flux_from_lightcurve(lc):
    """Extract a clean float array from a LightCurve object."""
    colnames = [str(c).lower() for c in lc.colnames]
    arr = None
    for candidate in ("pdcsap_flux", "sap_flux", "flux"):
        if candidate in colnames:
            col = lc.colnames[colnames.index(candidate)]
            try:
                arr = np.asarray(lc[col].value, dtype=float)
            except Exception:
                try:
                    arr = np.asarray(lc[col], dtype=float)
                except Exception:
                    arr = None
            if arr is not None:
                break
    if arr is None:
        arr = np.asarray(lc.flux.value, dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) < 100:
        return None
    # Mild sigma-clip to remove cosmic-ray outliers (keep structure intact)
    med = np.median(arr)
    mad = np.median(np.abs(arr - med)) + 1e-12
    keep = np.abs(arr - med) < 8 * 1.4826 * mad
    arr = arr[keep]
    if len(arr) < 100:
        return None
    # Normalize (anomaly metric is scale-free)
    arr = arr / np.median(arr)
    return arr


def fetch_flux(tic_id, sector=11, verbose=False, max_sectors=6):
    """Download a TESS light curve for a TIC id. Returns (flux_array, sector, source)."""
    import lightkurve as lk

    def log(*a):
        if verbose:
            print("      ", *a, flush=True)

    sectors_to_try = [sector] + [s for s in range(1, 70) if s != sector]

    # ---- 1) 2-minute / 20-second cadence light curves ----
    for try_sector in sectors_to_try[:max_sectors]:
        try:
            search = lk.search_lightcurve(f"TIC {tic_id}", mission="TESS", sector=try_sector)
            if len(search) == 0:
                search = lk.search_lightcurve(f"TIC {tic_id}", mission="TESS")
            if len(search) == 0:
                log(f"s{try_sector}: no lightcurve products")
                continue
            log(f"s{try_sector}: {len(search)} product(s)")
            # Download all products and stitch -> more cadences, fewer gaps
            try:
                collection = search.download_all()
                if len(collection) == 0:
                    continue
                lc = collection.stitch() if hasattr(collection, "stitch") else collection[0]
            except Exception:
                lc = search.download()
            arr = _flux_from_lightcurve(lc)
            if arr is not None and len(arr) > 100:
                return arr, try_sector, "lightcurve"
        except Exception as e:
            log(f"s{try_sector}: {type(e).__name__}: {str(e)[:80]}")
            continue

    # ---- 2) FFI cutout fallback (works for any star in the TESS FOV) ----
    log("falling back to FFI / TessCut")
    try:
        try:
            from lightkurve import search_tesscut
        except ImportError:
            from lightkurve import TesscutClass
            search_tesscut = TesscutClass().search
        for try_sector in sectors_to_try[:3]:
            try:
                res = search_tesscut(f"TIC {tic_id}", sector=try_sector)
                tpf = res.download(cutout_size=11)
                if tpf is None:
                    continue
                try:
                    lc = tpf.to_lightcurve(aperture_mask="threshold")
                except Exception:
                    mask = tpf.create_threshold_mask(threshold=3)
                    lc = tpf.to_lightcurve(aperture_mask=mask)
                arr = _flux_from_lightcurve(lc)
                if arr is not None and len(arr) > 100:
                    return arr, try_sector, "ffi"
            except Exception as e:
                log(f"ffi s{try_sector}: {type(e).__name__}: {str(e)[:80]}")
                continue
    except Exception as e:
        log(f"ffi unavailable: {type(e).__name__}: {str(e)[:80]}")

    return None, sector, "none"


# ===================================================================
# PER-TARGET ANALYSIS
# ===================================================================
def process_single_star(tic_id, sector=11, window_size=150, verbose=False):
    try:
        flux, used_sector, source = fetch_flux(tic_id, sector=sector, verbose=verbose)
        if flux is None:
            return {"tic_id": tic_id, "status": "no_data", "anomalies": 0,
                    "mean_ks": 0.0, "error": "No TESS data found (lightcurve + FFI)"}

        n_cadences = len(flux)
        ws = window_size
        if n_cadences < ws:
            ws = max(10, n_cadences // 2)
        n_windows = max(1, n_cadences // ws)

        ks_vals, ent_vals = [], []
        for i in range(n_windows):
            w = flux[i * ws: min((i + 1) * ws, n_cadences)]
            if len(w) < 10:
                continue
            ks_vals.append(ks_ratio(w))
            ent_vals.append(shannon_entropy(w, 50))

        if len(ks_vals) < 5:
            return {"tic_id": tic_id, "status": "insufficient_data", "anomalies": 0,
                    "mean_ks": 0.0, "cadences": n_cadences}

        ks_arr = np.asarray(ks_vals)
        mean_ks = float(ks_arr.mean())
        std_ks = float(ks_arr.std())
        threshold = mean_ks - 3 * std_ks
        anomalies = int((ks_arr < threshold).sum()) if std_ks > 0 else 0

        return {
            "tic_id": tic_id,
            "status": "ok",
            "cadences": n_cadences,
            "windows": len(ks_vals),
            "anomalies": anomalies,
            "mean_ks": mean_ks,
            "std_ks": std_ks,
            "threshold": float(threshold),
            "mean_entropy": float(np.mean(ent_vals)),
            "is_anomalous": anomalies > 0,
            "sector": used_sector,
            "source": source,
        }
    except Exception as e:
        return {"tic_id": tic_id, "status": "error", "error": f"{type(e).__name__}: {str(e)[:180]}",
                "anomalies": 0}


# ===================================================================
# MAIN
# ===================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="Process 2 targets sequentially with verbose output")
    ap.add_argument("--verbose", action="store_true", help="Verbose per-target download logs")
    ap.add_argument("--sector", type=int, default=None, help="Override catalog sector")
    ap.add_argument("--workers", type=int, default=None, help="Number of parallel workers")
    args = ap.parse_args()

    catalog_path = os.path.join(BASE_DIR, "data", "expanded_star_catalog.csv")
    catalog = pd.read_csv(catalog_path)

    high = catalog[catalog["priority"] >= 2]
    medium = catalog[catalog["priority"] == 1]
    ordered = pd.concat([high, medium], ignore_index=True)

    targets = []
    for _, row in ordered.iterrows():
        sec = args.sector if args.sector else int(row.get("sector", 11))
        targets.append((int(row["tic_id"]), sec))

    n_workers = args.workers or min(12, os.cpu_count() or 8)

    if args.test:
        targets = targets[:2]
        n_workers = 1
        print("=== TEST MODE: 2 targets, sequential, verbose ===\n")

    print(f"Loaded {len(targets)} targets | workers={n_workers}", flush=True)
    t0 = time.time()
    results = []

    if args.test:
        for tic, sec in targets:
            print(f"[TIC {tic}] sector {sec} ...", flush=True)
            r = process_single_star(tic, sector=sec, verbose=True)
            print(f"  -> {r}", flush=True)
            results.append(r)
    else:
        print(f"Processing {len(targets)} targets with {n_workers} workers...", flush=True)
        with ThreadPoolExecutor(max_workers=n_workers) as ex:
            futs = {ex.submit(process_single_star, tic, sec, 150, args.verbose): tic
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

    # ---- Save results ----
    os.makedirs(os.path.join(BASE_DIR, "results"), exist_ok=True)
    db_path = os.path.join(BASE_DIR, "results",
                           f"workstation_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
    df = pd.DataFrame(results)
    conn = sqlite3.connect(db_path)
    df.to_sql("results", conn, if_exists="replace", index=False)
    conn.close()

    cluster_map = dict(zip(catalog["tic_id"].astype(int), catalog["cluster"]))
    df["cluster"] = df["tic_id"].map(cluster_map).fillna("unknown")
    total_anom = df[df["status"] == "ok"]["anomalies"].sum()

    print("\n=== WORKSTATION RUN SUMMARY ===")
    print(f"Targets processed : {len(results)}")
    print(f"Successful (ok)   : {len(df[df['status']=='ok'])}")
    print(f"No data           : {len(df[df['status']=='no_data'])}")
    print(f"Insufficient data : {len(df[df['status']=='insufficient_data'])}")
    print(f"Errors            : {len(df[df['status']=='error'])}")
    print(f"Total anomalies   : {total_anom}")
    print(f"Results saved to  : {db_path}")
    if len(df[df["status"] == "ok"]):
        print("\nCluster breakdown:")
        print(df.groupby("cluster")["anomalies"].agg(["sum", "count", "mean"]).to_string())
    print("\nElapsed: %.1f min" % ((time.time() - t0) / 60))


if __name__ == "__main__":
    main()
