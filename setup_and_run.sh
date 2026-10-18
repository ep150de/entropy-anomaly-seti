#!/bin/bash
# ===================================================================
# NbNW Entropy Anomaly SETI Pipeline - Workstation Edition
# One-click setup for Intel Arc B70 Pro + i7-10700K + 64GB RAM
# ===================================================================

set -e

echo "============================================================"
echo "  NbNW Entropy Anomaly SETI Pipeline"
echo "  Workstation Edition - Single Script Setup + Execution"
echo "============================================================"

# --- ENVIRONMENT ---
WORK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$WORK_DIR" || exit 1

# Ensure required directories exist
mkdir -p "$WORK_DIR/results" "$WORK_DIR/data" "$WORK_DIR/pipeline"

echo "[1/5] Checking system resources..."
CPU_CORES=$(nproc)
TOTAL_RAM_GB=$(free -g | awk '/^Mem:/{print $2}')
GPU_INFO=$(lshw -C display 2>/dev/null | grep -A2 "product:" | head -3 || echo "Unknown GPU")
DISK_PATH=$(df / | tail -1 | awk '{print $1}')
echo "  CPU Cores: $CPU_CORES"
echo "  RAM: ${TOTAL_RAM_GB}GB"
echo "  GPU: $GPU_INFO"
echo "  Disk: $DISK_PATH"

# --- PYTHON SETUP ---
echo ""
echo "[2/5] Setting up Python environment..."
PYTHON_VENV="$WORK_DIR/venv_workstation"
if [ ! -d "$PYTHON_VENV" ]; then
    python3 -m venv "$PYTHON_VENV" 2>/dev/null || python3 -m venv --without-pip "$PYTHON_VENV"
    source "$PYTHON_VENV/bin/activate"
    # Install pip if missing
    if ! command -v pip &> /dev/null; then
        curl -sS https://bootstrap.pypa.io/get-pip.py | python3
    fi
else
    source "$PYTHON_VENV/bin/activate"
fi

# Install optimized packages
pip install --quiet --upgrade pip
pip install --quiet \
    "numpy>=1.24" \
    "scipy>=1.10" \
    "pandas>=2.0" \
    "lightkurve>=2.0" \
    "astropy>=5.3" \
    "astroquery>=0.4" \
    "numba>=0.57"

echo "  Python environment ready (optimized packages installed)"
echo "  Numba JIT acceleration enabled"

# --- PARALLEL PROCESSOR ---
echo ""
echo "[3/5] Creating parallel processor..."

cat > "$WORK_DIR/pipeline/workstation_runner.py" << 'PYEOF'
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
from astropy.time import Time
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
        flux_sorted = np.sort(flux)
        n = len(flux_sorted)
        cdf = np.arange(1, n + 1) / n
        return float(ks_1samp(flux, 'norm').statistic * np.sqrt(n))
    
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
            try:
                flux_data = np.load(cache_file, allow_pickle=True)
                if len(flux_data) > 0:
                    pass  # cache valid
                else:
                    os.remove(cache_file)
                    flux_data = None
            except Exception:
                # Corrupt cache file - remove and re-download
                try:
                    os.remove(cache_file)
                except OSError:
                    pass
                flux_data = None
        else:
            flux_data = None
        
        if flux_data is None:
            # Try specified sector first, then search all available
            sectors_to_try = [sector] + [s for s in range(1, 70) if s != sector]
            found_data = False
            
            for try_sector in sectors_to_try[:5]:  # Limit to 5 sectors to avoid long waits
                try:
                    # First try: search with specific sector
                    search = lk.search_lightcurve(f"TIC {tic_id}", sector=try_sector)
                    if len(search) == 0:
                        # Try without sector filter (all available data)
                        try:
                            search = lk.search_lightcurve(f"TIC {tic_id}")
                            if len(search) > 0:
                                # Filter to this sector if possible
                                sector_results = [r for r in search if try_sector in str(r)]
                                if sector_results:
                                    search = sector_results
                        except Exception:
                            continue
                    if len(search) == 0:
                        continue
                    
                    # Download single lightcurve (more reliable than download_all)
                    try:
                        lc = search.download()
                    except Exception:
                        # Try download_all as fallback
                        lc_collection = search.download_all()
                        if len(lc_collection) > 0:
                            lc = lc_collection[0]
                        else:
                            continue
                    
                    # Get flux data - try PDCSAP, then SAP, then raw
                    flux_data = None
                    if hasattr(lc, 'PDCSAP_FLUX'):
                        try:
                            flux_data = lc.PDCSAP_FLUX.flatten(window_size=101).remove_outliers().flux.value
                        except Exception:
                            pass
                    if flux_data is None and hasattr(lc, 'SAP_FLUX'):
                        try:
                            flux_data = lc.SAP_FLUX.flatten(window_size=101).remove_outliers().flux.value
                        except Exception:
                            pass
                    if flux_data is None:
                        try:
                            flux_data = lc.flatten(window_size=101).remove_outliers().flux.value
                        except Exception:
                            pass
                    if flux_data is None:
                        try:
                            flux_data = lc.flux.value
                        except Exception:
                            pass
                    
                    if flux_data is not None and len(flux_data) > 100:
                        found_data = True
                        sector = try_sector
                        break
                except Exception as e:
                    continue
            # If no 2-min data found, try FFI-based extraction
            if flux_data is None:
                try:
                    from lightkurve import search_tesscut
                    tpf = search_tesscut(f"TIC {tic_id}", sector=try_sector).download(cutout_size=10)
                    if tpf is not None:
                        lc = tpf.to_lightcurve(aperture_mask='threshold')
                        flux_data = lc.flux.value
                        if len(flux_data) > 100:
                            found_data = True
                            sector = try_sector
                            break
                except Exception:
                    continue
            
            if not found_data or flux_data is None:
                return {'tic_id': tic_id, 'status': 'no_data', 'anomalies': 0, 
                        'mean_ks': 0.0, 'sector_tried': sector, 'error': 'No TESS data found in any sector'}
            
            if save_cache:
                np.save(cache_file, flux_data, allow_pickle=True)
        
        # Compute entropy metrics
        from scipy.stats import ks_1samp
        
        n_cadences = len(flux_data)
        if n_cadences < window_size:
            window_size = min(100, n_cadences // 2)
            if window_size < 10:
                return {'tic_id': tic_id, 'status': 'insufficient_data', 'anomalies': 0,
                        'mean_ks': 0.0, 'cadences': n_cadences}
        
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
            'processing_time': 0.0,
            'sector': sector
        }
    except Exception as e:
        return {'tic_id': tic_id, 'status': 'error', 'error': str(e)[:200], 'anomalies': 0}


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
    
    # Prioritize targets and get their sectors
    high_priority = catalog[catalog['priority'] >= 2]
    medium_priority = catalog[catalog['priority'] == 1]
    
    all_targets = []
    target_sectors = {}
    for _, row in high_priority.iterrows():
        all_targets.append(row['tic_id'])
        target_sectors[row['tic_id']] = int(row.get('sector', 11))
    for _, row in medium_priority.iterrows():
        all_targets.append(row['tic_id'])
        target_sectors[row['tic_id']] = int(row.get('sector', 11))
    
    print(f"Loaded {len(all_targets)} targets from catalog")
    print(f"High priority: {len(high_priority)}")
    print(f"Medium priority: {len(medium_priority)}")
    
    # Determine worker count based on memory
    # 64GB RAM / 2GB per worker = 32 workers max, but limit to 12 for safety
    n_workers = min(12, os.cpu_count() or 8)
    
    # Execute parallel processing with sectors
    # Modified process_batch to accept sector mapping
    results = []
    total = len(all_targets)
    start_time = time.time()
    
    print(f"Processing {total} targets with {n_workers} workers...")
    
    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        futures = {executor.submit(process_single_star, tic, sector=target_sectors.get(tic, 11)): tic for tic in all_targets}
        
        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            results.append(result)
            
            elapsed = time.time() - start_time
            rate = i / elapsed * 60 if elapsed > 0 else 0
            remaining = (total - i) / rate if rate > 0 else 0
            
            status_icon = "⚡" if result.get('anomalies', 0) > 5 else "  "
            error_msg = f" [{str(result.get('error', ''))[:40]}]" if result.get('status') in ('error', 'no_data') else ""
            print(f"  [{i}/{total}] {status_icon} TIC {result['tic_id']}: "
                  f"{result.get('anomalies', 0)} anomalies | "
                  f"ETA: {remaining:.1f} min{error_msg}")
    
    # Save results to SQLite database
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
    print(f"Successful (ok): {len(df[df['status'] == 'ok'])}")
    print(f"No data: {len(df[df['status'] == 'no_data'])}")
    print(f"Insufficient data: {len(df[df['status'] == 'insufficient_data'])}")
    print(f"Errors: {len(df[df['status'] == 'error'])}")
    print(f"Total anomalies: {total_anomalies}")
    print(f"\nResults saved to: {db_path}")
    print(f"Cluster breakdown:")
    print(cluster_summary.to_string())


if __name__ == "__main__":
    main()
PYEOF

echo "  Parallel processor created"

# --- RUN PIPELINE ---
echo ""
echo "[4/5] Running pipeline..."
python3 "$WORK_DIR/pipeline/workstation_runner.py"
echo "  Pipeline execution complete"

# --- REPORT ---
echo ""
echo "[5/5] Generating summary report..."
cat > "$WORK_DIR/results/latest_report.txt" << 'REPORT'
WORKSTATION PIPELINE EXECUTION REPORT
=====================================
Generated: $(date)

System Configuration:
  CPU: $(nproc) cores
  RAM: $(free -h | awk '/^Mem:/{print $2}') 
  GPU: $(lshw -C display 2>/dev/null | grep "product:" | head -1)
  Disk: $(df -h / | tail -1 | awk '{print $4}') free

Pipeline Settings:
  Parallel Workers: 12
  Window Size: 150 samples
  JIT Acceleration: Numba enabled

Results:
  See results/workstation_run_*.db for full dataset
  Cluster summaries generated automatically
REPORT

echo "  Report saved to results/latest_report.txt"

echo ""
echo "============================================================"
echo "  WORKSTATION SETUP AND EXECUTION COMPLETE"
echo "============================================================"
echo ""
echo "Results location: $WORK_DIR/results/"
echo "Database: results/workstation_run_*.db"
echo "Run again anytime with: python3 $WORK_DIR/pipeline/workstation_runner.py"
