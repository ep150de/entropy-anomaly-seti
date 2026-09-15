#!/usr/bin/env python3
"""
Optimized Parallel Pipeline for Workstation Execution
Targets: Intel Arc B70 Pro, i7-10700K, 64GB RAM
"""

import os
import sys
import time
import sqlite3
import numpy as np
import pandas as pd
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime

# Optimize numba
try:
    import numba
    from numba import jit, njit
    NUMBA_AVAILABLE = True
except ImportError:
    NUMBA_AVAILABLE = False

# ===================================================================
# JIT-OPTIMIZED ENTROPY COMPUTATIONS
# ===================================================================
if NUMBA_AVAILABLE:
    @njit(fastmath=True, parallel=False)
    def _ks_ratio_fast(flux):
        """JIT-compiled KS ratio computation"""
        n = len(flux)
        flux_sorted = np.sort(flux)
        cdf_theory = np.linspace(0, 1, n)
        cdf_empirical = np.arange(1, n + 1) / n
        ks_stat = np.max(np.abs(cdf_empirical - cdf_theory))
        return float(ks_stat * np.sqrt(n))

    @njit(fastmath=True)
    def _entropy_fast(data, num_bins):
        """JIT-compiled entropy calculation"""
        hist = np.zeros(num_bins)
        min_val = np.min(data)
        max_val = np.max(data)
        bin_width = (max_val - min_val) / num_bins if max_val > min_val else 1.0

        for i in range(len(data)):
            bin_idx = int((data[i] - min_val) / bin_width)
            if bin_idx >= num_bins:
                bin_idx = num_bins - 1
            if bin_idx < 0:
                bin_idx = 0
            hist[bin_idx] += 1

        total = len(data)
        probs = hist / total
        entropy = 0.0
        for i in range(num_bins):
            if probs[i] > 0:
                entropy -= probs[i] * np.log2(probs[i])
        return float(entropy)
else:
    def _ks_ratio_fast(flux):
        from scipy.stats import ks_1samp
        return float(ks_1samp(flux, 'norm').statistic * np.sqrt(len(flux)))

    def _entropy_fast(data, num_bins):
        hist, _ = np.histogram(data, bins=num_bins, density=True)
        probs = hist * np.diff(np.histogram(data, bins=num_bins)[1])
        probs = probs[probs > 0]
        return float(-np.sum(probs * np.log2(probs)))


def process_single_star(tic_id, sector=11, window_size=150, save_cache=True):
    """Process a single TIC target with optimized pipeline"""
    try:
        import lightkurve as lk

        cache_file = f"/tmp/tess_cache_{tic_id}_s{sector}.npy"

        # Check cache first (NVMe SSD will be used for /tmp)
        if save_cache and os.path.exists(cache_file):
            flux_data = np.load(cache_file, allow_pickle=True)
        else:
            # Download TESS data
            search = lk.search_lightcurve(f"TIC {tic_id}", sector=sector)
            if len(search) == 0:
                return {'tic_id': tic_id, 'status': 'no_data', 'anomalies': 0, 'mean_ks': 0.0}

            lc = search.download_all().PLD()
            flux_data = lc.flatten(window_size=101).remove_outliers().flux.value

            if save_cache:
                np.save(cache_file, flux_data, allow_pickle=True)

        # Compute entropy metrics
        from scipy.stats import ks_1samp

        n_cadences = len(flux_data)
        if n_cadences < window_size:
            window_size = min(100, n_cadences // 2)

        n_windows = max(1, n_cadences // window_size)

        results = []
        for i in range(n_windows):
            start = i * window_size
            end = min(start + window_size, n_cadences)
            window_data = flux_data[start:end]

            ks_score = _ks_ratio_fast(window_data)
            entropy = _entropy_fast(window_data, 50)
            results.append({'ks_ratio': ks_score, 'entropy': entropy,
                            'window_index': i, 'time_btjd': 1325 + i * (window_size / 1440)})

        df = pd.DataFrame(results)

        if len(df) > 10:
            mean_ks = df['ks_ratio'].mean()
            std_ks = df['ks_ratio'].std()
            threshold = mean_ks - 3 * std_ks
            anomalies = int((df['ks_ratio'] < threshold).sum())
            is_anomalous = anomalies > 0
        else:
            mean_ks = 0
            std_ks = 0
            threshold = 0
            anomalies = 0
            is_anomalous = False

        return {
            'tic_id': tic_id,
            'status': 'ok',
            'cadences': n_cadences,
            'anomalies': anomalies,
            'mean_ks': float(mean_ks),
            'std_ks': float(std_ks),
            'threshold': float(threshold),
            'is_anomalous': is_anomalous,
            'processing_time': 0.0
        }
    except Exception as e:
        return {'tic_id': tic_id, 'status': 'error', 'error': str(e), 'anomalies': 0}


def process_batch(tic_list, n_workers=12):
    """Process multiple stars in parallel"""
    results = []
    total = len(tic_list)
    start_time = time.time()

    print(f"Processing {total} targets with {n_workers} workers...")

    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        futures = {executor.submit(process_single_star, tic): tic for tic in tic_list}

        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            results.append(result)

            elapsed = time.time() - start_time
            rate = i / elapsed * 60 if elapsed > 0 else 0
            remaining = (total - i) / rate if rate > 0 else 0

            status_icon = "⚡" if result.get('anomalies', 0) > 5 else "  "
            print(f"  [{i}/{total}] {status_icon} TIC {result['tic_id']}: "
                  f"{result.get('anomalies', 0)} anomalies | "
                  f"ETA: {remaining:.1f} min")

    return results


def main():
    # Load expanded catalog
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    catalog = pd.read_csv(f"{base_dir}/data/expanded_star_catalog.csv")

    # Prioritize targets
    high_priority = catalog[catalog['priority'] >= 2]['tic_id'].tolist()
    medium_priority = catalog[catalog['priority'] == 1]['tic_id'].tolist()
    all_targets = high_priority + medium_priority

    print(f"Loaded {len(all_targets)} targets from catalog")
    print(f"High priority: {len(high_priority)}")
    print(f"Medium priority: {len(medium_priority)}")

    # Determine worker count based on memory
    # 64GB RAM / 2GB per worker = 32 workers max, but limit to 12 for safety
    n_workers = min(12, os.cpu_count() or 8)

    # Execute parallel processing
    results = process_batch(all_targets, n_workers=n_workers)

    # Save results to SQLite database
    os.makedirs(f"{base_dir}/results", exist_ok=True)
    db_path = f"{base_dir}/results/workstation_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    conn = sqlite3.connect(db_path)

    df = pd.DataFrame(results)
    df.to_sql('results', conn, if_exists='replace', index=False)

    # Summary
    total_anomalies = df[df['status'] == 'ok']['anomalies'].sum()
    cluster_counts = df['tic_id'].apply(lambda x: catalog[catalog['tic_id'] == x]['cluster'].iloc[0] if x in catalog['tic_id'].values else 'unknown')
    df['cluster'] = cluster_counts
    cluster_summary = df.groupby('cluster').agg({
        'anomalies': ['sum', 'count', 'mean']
    })

    print(f"\n=== WORKSTATION RUN SUMMARY ===")
    print(f"Targets processed: {len(results)}")
    print(f"Successful: {len(df[df['status'] == 'ok'])}")
    print(f"Errors: {len(df[df['status'] == 'error'])}")
    print(f"Total anomalies: {total_anomalies}")
    print(f"\nResults saved to: {db_path}")
    print(f"Cluster breakdown:")
    print(cluster_summary.to_string())


if __name__ == "__main__":
    main()
