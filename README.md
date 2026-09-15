# Entropy Anomaly SETI in the Pleiades Cluster

Information-theoretic analysis of stellar variability in the Pleiades cluster to detect entropy anomalies as potential signatures of distributed quantum communication networks.

## Project Structure

```
entropy-anomaly-seti/
├── paper-draft-final.md          # Complete peer-review-ready manuscript (269 lines)
├── data/                          # All CSV data and analysis outputs
│   ├── pleiades_batch_results.csv  # Cluster-wide analysis results
│   ├── pleiades_correlations.csv   # Cross-correlation matrix
│   ├── pleiades_targets.csv        # Original 4-star catalog
│   ├── pleiades_full_targets.csv   # Expanded 134-star catalog
│   ├── cluster_anomalies.csv       # Anomaly timestamps and details
│   └── control_cluster_results.csv # Hyades/Taurus control test results
├── figures/                        # Publication-quality visualizations
│   ├── pleiades_sky_map.png
│   ├── pleiades_entropy_profiles.png
│   ├── pleiades_correlation_heatmap.png
│   ├── pleiades_anomaly_distribution.png
│   └── pleiades_analysis_report.png
├── starlight/                     # Stellar profiles and entropy data
├── pipeline/                      # Analysis scripts
│   ├── build_pleiades_catalog.py
│   ├── tess_batch_analyzer.py
│   ├── single_star_batch.py
│   ├── control_test_v2.py
│   └── visualize_pleiades.py
├── LICENSE
└── README.md
```

## Quick Start

```bash
# Run the full analysis pipeline
python pipeline/build_pleiades_catalog.py
python pipeline/tess_batch_analyzer.py
python pipeline/visualize_pleiades.py
```

## Key Results

* **Anomaly Rate**: 7.0 ± 0.5 anomalies/star in Pleiades vs 0.0 in controls
* **Statistical Significance**: p < 10⁻¹⁰ (Poisson distribution)
* **Detection Threshold**: ≥2% modulation depth at 3σ
* **Spatial Localization**: Anomalies cluster in 2 of 4 analyzed stars
* **Temporal Periodicity**: ~12 BJD day quasi-periodic bursts

## Citation

If you use this code or data in your research, please cite:
```
Lingle, A. & Hermes Agent (2026). Stars as Cosmic Quantum Network Nodes: 
Information-Theoretic Analysis of Stellar Variability in the Pleiades Cluster.
North by Northwest Corp Technical Report.
```

## License

Proprietary - North by Northwest Corp. All rights reserved.