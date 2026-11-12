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
* The earlier numba-accelerated runner had a broken KS statistic: it sorted
  the flux then never used it, returning a constant ~1/sqrt(n) for every
  window -> std ~ 0 -> zero anomalies on every target, even when TESS data
  downloaded fine. That metric was ALSO inconsistent with Phase 1/2.
* NO numba (caused "no implementation found for 'numpy.save'" in workers
  and gives no benefit; WSL does not expose the Arc GPU to lightkurve).
* NO np.save/np.load caching.
* ThreadPoolExecutor: TESS downloads are I/O-bound; threads avoid the
  ProcessPool pickling/spawn problems on WSL/Windows.
* setup_and_run.sh no longer GENERATES this file via heredoc -- it is a
  committed, syntax-checked source file (kills the "break outside loop" /
  indentation bug class).

Usage
-----
  python3 pipeline/workstation_runner.py                 # full 18-target run
  python3 pipeline/workstation_runner.py --test         # 2 targets, verbose
  python3 pipeline/workstation_runner.py --verbose      # full run, verbose
  python3 pipeline/workstation_runner.py --sector 11    # override sector
  python3 pipeline/workstation_runner.py --workers 8
"""

import os
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
        # Fall back to explicit flux columns
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


def _download_flux(search, max_products=3, verbose=False, log=print):
    """Try the first few search products with Phase 1/2 download settings."""
    for i in range(min(max_products, len(search))):
        try:
            lc = search[i].download(quality_bitmask="default")
            arr = _flux_from_lightcurve(lc)
            if arr is not None and len(arr) > WINDOW_SIZE:
                return arr
        except Exception as e:
            if verbose:
                log(f"      product {i}: {type(e).__name__}: {str(e)[:80]}")
    return None


def fetch_flux(tic_id, sector=11, verbose=False, max_sectors=6):
    """Download a TESS light curve for a TIC id. Returns (flux, sector, source)."""
    import lightkurve as lk

    def log(*a):
        if verbose:
            print("      ", *a, flush=True)

    sectors_to_try = [sector] + [s for s in range(1, 70) if s != sector]

    # ---- 1) 2-min / 20-s cadence products, catalog sector first ----
    for try_sector in sectors_to_try[:max_sectors]:
        try:
            search = lk.search_lightcurve(f"TIC {tic_id}", mission="TESS", sector=try_sector)
            if len(search) == 0:
                log(f"s{try_sector}: no products")
                continue
            log(f"s{try_sector}: {len(search)} product(s)")
            arr = _download_flux(search, verbose=verbose, log=log)
            if arr is not None:
                return arr, try_sector, "lightcurve"
        except Exception as e:
            log(f"s{try_sector}: {type(e).__name__}: {str(e)[:80]}")
            continue

    # ---- 1b) unfiltered search (any sector / any author) ----
    try:
        search = lk.search_lightcurve(f"TIC {tic_id}", mission="TESS")
        if len(search) > 0:
            log(f"unfiltered: {len(search)} product(s)")
            arr = _download_flux(search, max_products=5, verbose=verbose, log=log)
            if arr is not None:
                return arr, sector, "lightcurve-any"
    except Exception as e:
        log(f"unfiltered: {type(e).__name__}: {str(e)[:80]}")

    # ---- 2) FFI cutout fallback (any star in the TESS field of view) ----
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
                if arr is not None:
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
def process_single_star(tic_id, sector=11, window_size=WINDOW_SIZE, verbose=False):
    try:
        flux, used_sector, source = fetch_flux(tic_id, sector=sector, verbose=verbose)
        if flux is None:
            return {"tic_id": tic_id, "status": "no_data", "anomalies": 0,
                    "mean_ks": np.nan, "error": "No TESS data found (lightcurve + FFI)"}

        n_cadences = len(flux)
        comp = sliding_window_kcomplexity(flux, window_size, STEP_SIZE)
        if len(comp) < 5:
            return {"tic_id": tic_id, "status": "insufficient_data", "anomalies": 0,
                    "mean_ks": np.nan, "cadences": n_cadences}

        mean_k = float(np.mean(comp))
        std_k = float(np.std(comp))
        threshold = mean_k - ANOMALY_SIGMA * std_k
        anomalies = int(np.sum(comp < threshold))

        # Supplementary entropy over the same windows (diagnostic only)
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
# MAIN
# ===================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="2 targets, sequential, verbose")
    ap.add_argument("--verbose", action="store_true", help="Verbose download logs")
    ap.add_argument("--sector", type=int, default=None, help="Override catalog sector")
    ap.add_argument("--workers", type=int, default=None, help="Parallel workers")
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

    print(f"Metric: zlib Kolmogorov complexity | window={WINDOW_SIZE} "
          f"step={STEP_SIZE} sigma={ANOMALY_SIGMA}")
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
