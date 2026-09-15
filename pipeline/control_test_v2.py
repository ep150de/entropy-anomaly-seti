#!/usr/bin/env python3
"""
TESS Random Cluster Control Test (Optimized Version)
Uses direct TIC targeting to avoid slow region searches
"""
import numpy as np
import pandas as pd
import lightkurve as lk
import zlib
import time

WINDOW_SIZE = 150
STEP_SIZE = 10
ANOMALY_SIGMA = 3.0

# Random control clusters with known TIC IDs and sectors
CONTROL_SAMPLES = [
    {"name": "Hyades_Field", "tic": 235955803, "sector": 11},  # Known Pleiades member but not in main scan
    {"name": "Kepler10_Field", "tic": 217330998, "sector": 1},  # Kepler field
    {"name": "Taurus_Region", "tic": 225953695, "sector": 13},  # Taurus
    {"name": "Upper_Sco", "tic": 317314963, "sector": 12},  # Upper Scorpius
    {"name": "Random_North", "tic": 123456789, "sector": 11},  # Random northern target
]

def compute_ks(flux, ql=256):
    clean = flux[~np.isnan(flux)]
    if len(clean) == 0:
        return 1.0
    f_min, f_max = np.min(clean), np.max(clean)
    if f_max == f_min:
        return 1.0
    norm = (clean - f_min) / (f_max - f_min)
    q = (norm * (ql - 1)).astype(np.uint8).tobytes()
    return len(zlib.compress(q, level=9)) / len(q)

def sliding_entropy(flux, ws=WINDOW_SIZE, step=STEP_SIZE):
    comps = []
    for s in range(0, len(flux) - ws, step):
        comps.append(compute_ks(flux[s:s+ws]))
    return np.array(comps)

def get_flux(lc):
    for attr in ['flux', 'pdcsap_flux']:
        v = getattr(lc, attr, None)
        if v is not None and len(v) > 100:
            return np.asarray(v).flatten()
    return np.asarray(lc.flux).flatten()

print("=" * 70)
print("TESS CONTROL CLUSTER TEST - OPTIMIZED")
print(f"Targets: {len(CONTROL_SAMPLES)}")
print("=" * 70)

results = []

for sample in CONTROL_SAMPLES:
    name = sample['name']
    tic = sample['tic']
    sector = sample['sector']
    print(f"\n[{name}] TIC {tic}, Sector {sector}...")
    
    try:
        search = lk.search_lightcurve(f"TIC {tic}", mission="TESS", sector=sector)
        if len(search) == 0:
            search = lk.search_lightcurve(f"TIC {tic}", mission="TESS")
        
        if len(search) == 0:
            print(f"  ❌ No data found")
            results.append({"Cluster_Name": name, "TIC_ID": tic, "Status": "No data",
                           "Cadences": 0, "Mean_KS": np.nan, "Anomaly_Count": 0, "Max_Corr": 0})
            continue
            
        lc_raw = search[0].download(quality_bitmask="default")
        lc = lc_raw.remove_nans().normalize()
        flux = get_flux(lc)
        time_arr = lc.time.value
        
        if len(flux) < 200:
            print(f"  ❌ Too few cadences ({len(flux)})")
            continue
            
        comp = sliding_entropy(flux)
        mean_k = np.mean(comp)
        std_k = np.std(comp)
        threshold = mean_k - (ANOMALY_SIGMA * std_k)
        anom_count = len(np.where(comp < threshold)[0])
        
        parallax_mas = float(lc.meta.get('PARALLAX', 0.0))
        dist_ly = (1000.0 / parallax_mas * 3.26156) if parallax_mas > 0 else None
        
        print(f"  ✅ {len(flux)} cadences | K(S)={mean_k:.4f}±{std_k:.4f} | Anomalies={anom_count}")
        if dist_ly:
            print(f"  Distance: {dist_ly:.1f} ly")
        
        results.append({
            "Cluster_Name": name,
            "TIC_ID": tic,
            "Status": "OK",
            "Cadences": len(flux),
            "Mean_KS": float(mean_k),
            "Std_KS": float(std_k),
            "Anomaly_Count": int(anom_count),
            "Max_Corr": 0.0,  # Single star, no correlation
            "Distance_LY": dist_ly if dist_ly else "Unknown"
        })
        
    except Exception as e:
        print(f"  ❌ Error: {e}")
        results.append({"Cluster_Name": name, "TIC_ID": tic, "Status": "Error",
                       "Cadences": 0, "Mean_KS": np.nan, "Anomaly_Count": 0, "Max_Corr": 0})

# Save results
print("\n" + "=" * 70)
print("CONTROL TEST SUMMARY")
print("=" * 70)

results_df = pd.DataFrame(results)
print(results_df.to_string(index=False))

results_df.to_csv("/home/lingleblater/.hermes/hermes-agent/control_cluster_results.csv", index=False)
print(f"\nSaved to control_cluster_results.csv")

# Compare to Pleiades
print("\n[COMPARISON] Control Clusters vs. Pleiades")
print("=" * 70)
try:
    pleiades_df = pd.read_csv("/home/lingleblater/.hermes/hermes-agent/cluster_star_summary.csv")
    pleiades_anom_per_star = pleiades_df['Anomaly_Count'].sum() / len(pleiades_df)
    pleiades_mean_ks = pleiades_df['Mean_KS'].mean()
    
    control_df = results_df[results_df['Status'] == 'OK']
    control_anom_per_star = control_df['Anomaly_Count'].sum() / len(control_df) if len(control_df) > 0 else 0
    control_mean_ks = control_df['Mean_KS'].mean() if len(control_df) > 0 else 0
    
    print(f"Pleiades: {pleiades_anom_per_star:.1f} anomalies/star, K(S)={pleiades_mean_ks:.4f}")
    print(f"Controls: {control_anom_per_star:.1f} anomalies/star, K(S)={control_mean_ks:.4f}")
    
    if pleiades_anom_per_star > control_anom_per_star * 1.5:
        print("⚠️  Pleiades anomaly rate exceeds controls by 50%+ — warrants investigation")
    else:
        print("✅ Anomaly rates consistent with natural variability")
        
except Exception as e:
    print(f"Comparison error: {e}")

print("\nControl test complete!")