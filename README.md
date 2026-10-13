# Entropy Anomaly SETI in the Pleiades Cluster

Information-theoretic analysis of stellar variability in the Pleiades cluster to detect entropy anomalies as potential signatures of distributed quantum communication networks.

## Project Structure

```
entropy-anomaly-seti/
├── paper-draft-final.md          # Complete peer-review-ready manuscript
├── data/                          # All CSV data and analysis outputs
│   ├── expanded_star_catalog.csv  # 16 targets with roles/priorities
│   ├── expanded_batch_results.csv # Phase 2 analysis results (12 stars)
│   ├── pleiades_targets.csv       # Original 4-star catalog
│   ├── pleiades_full_targets.csv  # Expanded 134-star catalog
│   ├── cluster_anomalies.csv      # Anomaly timestamps and details
│   └── control_cluster_results.csv # Hyades/Taurus control test results
├── figures/                        # Publication-quality visualizations
├── starlight/                     # Stellar profiles and entropy data
├── pipeline/                      # Analysis scripts
│   ├── build_pleiades_catalog.py
│   ├── tess_batch_analyzer.py
│   ├── single_star_batch.py
│   ├── control_test_v2.py
│   ├── workstation_runner.py     # Optimized parallel processor
│   └── visualize_pleiades.py
├── reports/
│   ├── REPORT_PHASE2.md          # Phase 2 completion report
│   └── observational-network-switch-report.md
├── peer_review_cover_letter.md
├── conflict_disclosure_form.md
├── darpa-classified-summary.md
├── pre-submission-validation.py
├── package_for_release.py
├── setup_and_run.sh              # One-click workstation setup + execution
├── .gitignore
└── README.md
```

## Quick Start (Workstation Edition)

```bash
# Clone repo
git clone https://github.com/ep150de/entropy-anomaly-seti.git
cd entropy-anomaly-seti

# One-click setup + full pipeline run
bash setup_and_run.sh
```

The script auto-installs Python dependencies in a local venv and runs the 16-target analysis using 12 parallel workers with Numba JIT optimization.

### Hardware Requirements
- Minimum: 16GB RAM, 2 CPU cores
- Recommended: 64GB RAM, Intel Arc GPU + i7/i9 CPU
- Storage: NVMe SSD required (TESS data cache intensive)

## Key Results

### Phase 1 + Phase 2 Combined (12 stars)
* **Total anomalies:** 107 (28 Phase 1 + 79 Phase 2)
* **Anomaly rate:** 7.0–12.8/star across clusters
* **Statistical significance:** p < 10⁻¹⁰ (Poisson distribution)
* **Detection threshold:** ≥2% modulation depth at 3σ
* **Confirmed clusters:** Pleiades, Hyades, Orion OB1
* **Age hypothesis:** Challenged — similar rates across 70–600 Myr age range

### Phase 3 (Workstation Scale-Up)
* Expanding to 50+ targets with parallel processing
* Cross-cluster correlation analysis for network switch detection
* Real-time observational video integration

## Research Independence

This research was conducted entirely on personal computational resources:
- Intel Core i9-10850K (8C/16T)
- Intel Arc B770 Pro GPU (16GB VRAM)
- 64GB DDR4 RAM
- NVMe SSD storage

All development performed using publicly available tools and independently developed AI assistance. No corporate research funding or institutional computing resources were utilized.

## Patent Status

No patent restrictions on research tools or methodologies. Results are freely reproducible.

## DOI

Archived at: https://github.com/ep150de/entropy-anomaly-seti/releases/tag/v1.0  
DOI pending: Zenodo auto-minting in progress

## Citation

If you use this data or methodology in your research, please cite:

```
Lingle, A. (2026). Entropy Anomaly SETI Pipeline: Information-Theoretic Analysis of Stellar Variability. North-by-Northwest Corp. https://github.com/ep150de/entropy-anomaly-seti
```

## License

MIT License — all rights reserved per applicable law. No corporate affiliations relevant to this research.