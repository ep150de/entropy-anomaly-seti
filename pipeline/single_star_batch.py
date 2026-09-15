#!/usr/bin/env python3
"""
TESS Pleiades Single-Star Batch Analyzer (Robust, Single-Target)
Optimized for reliability - processes individual TIC IDs with retries
and multi-sector fallback
"""
import numpy as np
import pandas as pd
import lightkurve as lk
import zlib
import time
import sys

WINDOW_SIZE = 150
STEP_SIZE = 10
ANOMALY_SIGMA = 3.0

def compute_ks(flux_array, levels=256):
    """Kolmogorov complexity via zlib compression."""
    clean = flux_array[~np.isnan(flux_array)]
    if len(clean) < 2:
        return 1.0
    f_min, f_max = np.min(clean), np.max(clean)
    if f_max == f_min:
        return 1.0
    norm = (clean - f_min) / (f_max - f_min)
    quant = (norm * (levels - 1)).astype(np.uint8).tobytes()
    return len(zlib.compress(quant, level=9)) / len(quant)

def sliding_entropy(flux):
    """Sliding window K(S) computation."""
    n_windows = max(1, (len(flux) - WINDOW_SIZE) // STEP_SIZE + 1)
    comps = []
    indices = []
    for i in range(n_windows):
        start = i * STEP_SIZE
        window = flux[start:start + WINDOW_SIZE]
        k = compute_ks(window)
        comps.append(k)
        indices.append(start + WINDOW_SIZE // 2)
    return np.array(comps), np.array(indices)

def analyze_single_star(tic_id, sectors=None):
    """Analyze a single TIC ID across specified sectors."""
    if sectors is None:
        sectors = [11]  # Default sector
    
    for sector in sectors:
        try:
            print(f"  Trying Sector {sector}...", end=" ")
            search = lk.search_lightcurve(f"TIC {tic_id}", sector=sector)
            
            if len(search) == 0:
                # Try without sector filter
                search = lk.search_lightcurve(f"TIC {tic_id}")
                if len(search) == 0:
                    print("no data")
                    continue
                # Find matching sector
                best_match = None
                best_sector = sector
                for i in range(len(search)):
                    try:
                        s = int(search[i].sector) if hasattr(search[i], 'sector') else sector
                        if s == sector:
                            best_match = search[i]
                            best_sector = s
                            break
                    except:
                        pass
                if best_match is None:
                    # Just take the first result
                    best_match = search[0]
                    try:
                        best_sector = int(best_match.sector)
                    except:
                        best_sector = sector
                lc_raw = best_match.download(quality_bitmask="default")
            else:
                lc_raw = search[0].download(quality_bitmask="default")
            
            lc = lc_raw.remove_nans().normalize()
            flux = np.array(lc.flux)
            time_arr = np.array(lc.time.value)
            
            print(f"✅ {len(flux)} cadences")
            
            comp, win_idx = sliding_entropy(flux)
            mean_k = np.mean(comp)
            std_k = np.std(comp)
            threshold = mean_k - (ANOMALY_SIGMA * std_k)
            anom_count = int(np.sum(comp < threshold))
            
            # Save profile
            time_per_window = time_arr[np.clip(win_idx, 0, len(time_arr)-1)]
            pd.DataFrame({
                'window_index': win_idx,
                'time_btjd': time_per_window,
                'kolmogorov_ratio': comp,
                'is_anomaly': comp < threshold
            }).to_csv(f"pleiades_tic_{tic_id}_profile.csv", index=False)
            
            return {
                "tic_id": tic_id, "sector": sector,
                "status": "ok", "cadences": int(len(flux)),
                "anomalies": anom_count,
                "mean_ks": float(mean_k), "std_ks": float(std_k),
                "threshold": float(threshold),
                "processing_time_s": 0  # Will be filled by caller
            }, comp, mean_k, std_k, threshold
            
        except Exception as e:
            print(f"failed: {str(e)[:50]}")
            continue
    
    return None, None, None, None, None

# --- Main ---
if len(sys.argv) > 1:
    tic_ids = [int(x) for x in sys.argv[1:]]
else:
    tic_ids = [261136674, 261136679, 231844178, 393928046]

# Extended sector list for fallback
FALLBACK_SECTORS = [11, 12, 13, 14, 15, 39, 40, 41, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

print(f"Analyzing {len(tic_ids)} targets...")
results = []
profiles = {}

for tic_id in tic_ids:
    print(f"\nTIC {tic_id}:")
    start = time.time()
    
    result, comp, mean_k, std_k, thresh = analyze_single_star(tic_id, [11] + FALLBACK_SECTORS)
    elapsed = time.time() - start
    
    if result:
        result["tic_id"] = tic_id
        result["processing_time_s"] = elapsed
        result["name"] = f"Pleiades_{tic_id}"
        results.append(result)
        profiles[tic_id] = {"complexity": comp, "mean_k": mean_k, "anomaly_count": result["anomalies"]}
        icon = "⚡" if result["anomalies"] > 0 else "✅"
        print(f"  {icon} K(S)={mean_k:.4f}±{std_k:.4f} | A:{result['anomalies']} | {elapsed:.1f}s")

# --- Save results ---
if results:
    df = pd.DataFrame(results)
    df.to_csv("pleiades_batch_results.csv", index=False)
    
    # Correlation analysis
    tics = list(profiles.keys())
    n = len(tics)
    print(f"\n{'='*40}")
    print(f"SUMMARY: {len(tics)} stars processed")
    print(f"Total anomalies: {sum(profiles[t]['anomaly_count'] for t in tics)}")
    print(f"Mean K(S): {np.mean([profiles[t]['mean_k'] for t in tics]):.4f}")
    
    if n >= 2:
        corr_matrix = np.zeros((n, n))
        min_len = min(len(profiles[t]["complexity"]) for t in tics)
        
        for i in range(n):
            pi = profiles[tics[i]]["complexity"][:min_len]
            for j in range(i, n):
                pj = profiles[tics[j]]["complexity"][:min_len]
                r = np.corrcoef(pi - np.mean(pi), pj - np.mean(pj))[0,1]
                r = 0.0 if np.isnan(r) else r
                corr_matrix[i,j] = r
                corr_matrix[j,i] = r
            corr_matrix[i,i] = 1.0
        
        np.save("pleiades_corr_matrix.npy", corr_matrix)
        np.save("pleiades_tic_list.npy", np.array(tics))
        
        # Save correlation pairs
        pairs = []
        for i in range(n):
            for j in range(i+1, n):
                pairs.append({"TIC_A": tics[i], "TIC_B": tics[j], 
                             "Correlation": corr_matrix[i,j],
                             "Abs_Corr": abs(corr_matrix[i,j])})
        pd.DataFrame(pairs).to_csv("pleiades_correlations.csv", index=False)
        
        print("\nCorrelation matrix:")
        header = "     " + "".join([f"{str(t)[:8]:>10}" for t in tics])
        print(header)
        for i in range(n):
            row = f"{str(tics[i])[:8]:>10}"
            for j in range(n):
                row += f"{corr_matrix[i,j]:>10.4f}"
            print(row)
        
        sig_pairs = [(i,j,corr_matrix[i,j]) for i in range(n) for j in range(i+1,n) if abs(corr_matrix[i,j]) > 0.3]
        if sig_pairs:
            print("\n⚡ Significant correlations (|r|>0.3):")
            for i,j,r in sig_pairs:
                print(f"  TIC {tics[i]} ↔ TIC {tics[j]}: r={r:.4f}")
        else:
            print("\nNo significant correlations detected")
    
    print(f"\nResults saved to pleiades_batch_results.csv")
else:
    print("No results to save")