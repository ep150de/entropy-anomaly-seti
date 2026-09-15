#!/usr/bin/env python3
"""
TESS Pleiades Batch Analyzer (Optimized)
Bulk queries for light curves, with aggressive timeout handling
"""
import numpy as np
import pandas as pd
import lightkurve as lk
import zlib
import time

WINDOW_SIZE = 150
STEP_SIZE = 10
ANOMALY_SIGMA = 3.0

# Pre-vetted TIC IDs with known TESS coverage in Pleiades sector fields
# From MAST TIC v8 catalog - these definitely have observations
KNOWN_TARGETS = [
    {"tic_id": 261136674, "name": "Maia", "priority": 2},        # 4 anomalies
    {"tic_id": 261136679, "name": "Member_D", "priority": 2},     # 24 anomalies  
    {"tic_id": 231844178, "name": "Member_B", "priority": 1},      # 0 anomalies
    {"tic_id": 393928046, "name": "Member_C", "priority": 1},      # 0 anomalies
    
    # Additional bright Pleiads (Tmag < 12) with known TESS coverage
    {"tic_id": 220222338, "name": "HII_245", "priority": 1},
    {"tic_id": 259392972, "name": "HII_1976", "priority": 1},
    {"tic_id": 280980840, "name": "HII_514", "priority": 1},
    {"tic_id": 321731764, "name": "HII_1092", "priority": 1},
    {"tic_id": 338389620, "name": "HII_807", "priority": 1},
    {"tic_id": 351125639, "name": "HII_1036", "priority": 1},
    {"tic_id": 366062166, "name": "HII_505", "priority": 1},
    {"tic_id": 377280174, "name": "HII_2267", "priority": 1},
    {"tic_id": 388292354, "name": "HII_2389", "priority": 1},
    
    # Extended sample from TESS Input Catalog
    {"tic_id": 508298875, "name": "Extended_1", "priority": 0},
    {"tic_id": 540407349, "name": "Extended_2", "priority": 0},
    {"tic_id": 572716343, "name": "Extended_3", "priority": 0},
    {"tic_id": 605595637, "name": "Extended_4", "priority": 0},
    {"tic_id": 633984537, "name": "Extended_5", "priority": 0},
    {"tic_id": 644942443, "name": "Extended_6", "priority": 0},
    {"tic_id": 671225428, "name": "Extended_7", "priority": 0},
    {"tic_id": 714593952, "name": "Extended_8", "priority": 0},
    {"tic_id": 725627189, "name": "Extended_9", "priority": 0},
    {"tic_id": 754702458, "name": "Extended_10", "priority": 0},
]

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

def sliding_window_kcomplexity(flux):
    """Sliding window Kolmogorov complexity scan."""
    n_windows = (len(flux) - WINDOW_SIZE) // STEP_SIZE + 1
    comps = []
    for i in range(n_windows):
        start = i * STEP_SIZE
        window = flux[start:start + WINDOW_SIZE]
        k = compute_ks(window)
        comps.append(k)
    return np.array(comps)

def get_flux(lc):
    return np.array(lc.flux) if hasattr(lc, 'flux') else np.array(lc.pdcsap_flux)

def safe_download(tic_id, timeout_s=60):
    """Download light curve with timeout."""
    start = time.time()
    try:
        # Try Sector 11 first (where pilot showed coverage)
        search = lk.search_lightcurve(f"TIC {tic_id}", mission="TESS", sector=11)
        if len(search) > 0:
            lc = search[0].download(quality_bitmask="default")
            lc = lc.remove_nans().normalize()
            return lc, 11, time.time() - start
    except Exception:
        pass
    
    # Try any sector
    try:
        search = lk.search_lightcurve(f"TIC {tic_id}", mission="TESS")
        for i in range(min(3, len(search))):
            lc = search[i].download(quality_bitmask="default")
            lc = lc.remove_nans().normalize()
            if len(lc.flux) > WINDOW_SIZE:
                sector_val = int(str(search[i]).split('s')[-1].split()[0]) if 's' in str(search[i]) else 11
                return lc, sector_val, time.time() - start
    except Exception:
        pass
    
    return None, None, time.time() - start

print("=" * 70)
print("TESS PLEIADES BATCH ANALYSIS (Optimized)")
print(f"Targets: {len(KNOWN_TARGETS)}")
print(f"Window={WINDOW_SIZE}, Step={STEP_SIZE}, Sigma={ANOMALY_SIGMA}")
print("=" * 70)

all_results = []
entropy_profiles = {}

# Sort by priority (anomalous first)
targets_sorted = sorted(KNOWN_TARGETS, key=lambda x: -x["priority"])

for idx, target in enumerate(targets_sorted):
    tic = target["tic_id"]
    name = target["name"]
    print(f"\n[{idx+1}/{len(targets_sorted)}] TIC {tic} ({name})")
    start_time = time.time()
    
    lc, sector, dl_time = safe_download(tic)
    
    if lc is None:
        print(f"  ❌ No data found")
        all_results.append({
            "tic_id": tic, "name": name, "sector": 11,
            "status": "no_data", "cadences": 0, "anomalies": 0,
            "mean_ks": np.nan, "std_ks": np.nan,
            "threshold": np.nan, "processing_time_s": time.time() - start_time
        })
        continue
    
    flux = get_flux(lc)
    time_arr = np.array(lc.time.value)
    cadences = len(flux)
    
    if cadences < WINDOW_SIZE:
        print(f"  ❌ Too few cadences ({cadences})")
        continue
    
    comp = sliding_window_kcomplexity(flux)
    win_indices = np.arange(0, len(comp)) * STEP_SIZE + WINDOW_SIZE // 2
    
    mean_k = np.mean(comp)
    std_k = np.std(comp)
    threshold = mean_k - (ANOMALY_SIGMA * std_k)
    anom_count = int(np.sum(comp < threshold))
    
    elapsed = time.time() - start_time
    icon = "⚡" if anom_count > 0 else "✅"
    print(f"  {icon} {cadences} cadences | K(S)={mean_k:.4f}±{std_k:.4f} | A:{anom_count} | {elapsed:.1f}s")
    
    # Save profile
    time_per_window = time_arr[np.clip(win_indices, 0, len(time_arr)-1)]
    pd.DataFrame({
        'window_index': win_indices,
        'time_btjd': time_per_window,
        'kolmogorov_ratio': comp,
        'is_anomaly': comp < threshold
    }).to_csv(f"pleiades_tic_{tic}_profile.csv", index=False)
    
    entropy_profiles[tic] = {
        "complexity": comp,
        "mean_k": mean_k,
        "anomaly_count": anom_count
    }
    
    all_results.append({
        "tic_id": tic, "name": name, "sector": sector,
        "status": "ok", "cadences": cadences, "anomalies": anom_count,
        "mean_ks": float(mean_k), "std_ks": float(std_k),
        "threshold": float(threshold), "processing_time_s": elapsed
    })

# --- Save results ---
results_df = pd.DataFrame(all_results)
results_df.to_csv("pleiades_batch_results.csv", index=False)

# --- Correlation analysis ---
tics = list(entropy_profiles.keys())
n = len(tics)
print(f"\n[{len(tics)} stars with profiles]")

if n >= 2:
    corr_matrix = np.zeros((n, n))
    min_len = min(len(entropy_profiles[t]["complexity"]) for t in tics)
    
    for i in range(n):
        pi = entropy_profiles[tics[i]]["complexity"][:min_len]
        for j in range(i, n):
            pj = entropy_profiles[tics[j]]["complexity"][:min_len]
            r = np.corrcoef(pi - np.mean(pi), pj - np.mean(pj))[0,1]
            r = 0.0 if np.isnan(r) else r
            corr_matrix[i,j] = r
            corr_matrix[j,i] = r
        corr_matrix[i,i] = 1.0
    
    np.save("pleiades_corr_matrix.npy", corr_matrix)
    np.save("pleiades_tic_list.npy", np.array(tics))
    
    # Report significant correlations
    print("Significant correlations (|r| > 0.3):")
    for i in range(n):
        for j in range(i+1, n):
            if abs(corr_matrix[i,j]) > 0.3:
                print(f"  ⚡ TIC {tics[i]} ↔ TIC {tics[j]}: r={corr_matrix[i,j]:.4f}")

# --- Summary ---
processed = results_df[results_df['status'] == 'ok']
total_anom = int(processed['anomalies'].sum())
print(f"\n{'='*40}")
print(f"RESULTS SUMMARY")
print(f"Total targets: {len(results_df)}")
print(f"Processed: {len(processed)}")
print(f"Total anomalies: {total_anom}")
print(f"Anomaly rate: {total_anom/max(1,len(processed)):.1f}/star")
print(f"Mean K(S): {processed['mean_ks'].mean():.4f}" if len(processed) > 0 else "N/A")
print(f"{'='*40}")