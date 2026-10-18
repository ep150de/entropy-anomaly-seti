#!/usr/bin/env python3
"""
Generate Colab notebook for parallel entropy analysis.
Creates a .ipynb file ready for upload to Google Colab.
"""

import json
import os

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTEBOOK_PATH = f"{base_dir}/colab_entropy_analysis.ipynb"

NOTEBOOK = {
    "cells": [
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "# NbNW Entropy Anomaly SETI Pipeline — Colab Edition\n",
                "## Remote Processing on Free GPU (T4/V100)\n",
                "\n",
                "**Purpose:** Run entropy anomaly detection on 24 star cluster members using Google's free GPU compute.\n",
                "    \n",
                "**Steps:**\n",
                "1. Install packages (lightkurve, astroquery, numba)\n",
                "2. Load TESS data from MAST\n",
                "3. Run JIT-accelerated sliding-window K(S) entropy analysis\n",
                "4. Save results back to GitHub\n",
                "---"
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {
                "tags": ["parameters"],
                "cellView": "form"
            },
            "outputs": [],
            "source": [
                "#@title 🛠️ Install Dependencies (run once)\n",
                "!pip install --quiet lightkurve astroquery numba numpy pandas scipy astropy\n",
                "print('Dependencies installed ✅')"
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {
                "tags": ["parameters"],
                "cellView": "form"
            },
            "outputs": [],
            "source": [
                "#@title 🔗 Mount Google Drive + Clone Repo\n",
                "from google.colab import drive\n",
                "drive.mount('/content/drive')\n",
                "!git clone https://github.com/ep150de/entropy-anomaly-seti.git\n",
                "%cd /content/entropy-anomaly-seti\n",
                "print('Environment ready ✅')"
            ]
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## Core Analysis Pipeline"
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {
                "cellView": "form"
            },
            "outputs": [],
            "source": [
                "#@title ⚙️ Core Analysis Pipeline\n",
                "import numpy as np\n",
                "import pandas as pd\n",
                "import lightkurve as lk\n",
                "from scipy.stats import ks_1samp\n",
                "from concurrent.futures import ThreadPoolExecutor\n",
                "import time\n",
                "import os\n",
                "\n",
                "# --- JIT-Optimized Functions ---\n",
                "try:\n",
                "    from numba import njit\n",
                "    \n",
                "    @njit(fastmath=True)\n",
                "    def ks_ratio_fast(flux):\n",
                "        n = len(flux)\n",
                "        if n < 10:\n",
                "            return 0.0\n",
                "        flux_sorted = np.sort(flux)\n",
                "        cdf_emp = np.arange(1, n + 1) / n\n",
                "        cdf_theory = (flux_sorted - flux_sorted.min()) / (flux_sorted.max() - flux_sorted.min() + 1e-10)\n",
                "        return float(np.max(np.abs(cdf_emp - cdf_theory)) * np.sqrt(n))\n",
                "\n",
                "    @njit(fastmath=True)\n",
                "    def entropy_fast(data, num_bins=50):\n",
                "        hist = np.zeros(num_bins)\n",
                "        d_min, d_max = data.min(), data.max()\n",
                "        if d_max == d_min:\n",
                "            return 0.0\n",
                "        bin_width = (d_max - d_min) / num_bins\n",
                "        for i in range(len(data)):\n",
                "            idx = min(int((data[i] - d_min) / bin_width), num_bins - 1)\n",
                "            hist[idx] += 1\n",
                "        probs = hist / len(data)\n",
                "        entropy = 0.0\n",
                "        for i in range(num_bins):\n",
                "            if probs[i] > 0:\n",
                "                entropy -= probs[i] * np.log2(probs[i])\n",
                "        return float(entropy)\n",
                "    \n",
                "    NUMBA_OK = True\n",
                "    print('Numba JIT enabled ✅')\n",
                "except:\n",
                "    def ks_ratio_fast(flux):\n",
                "        return float(ks_1samp(flux, 'norm').statistic * np.sqrt(len(flux)))\n",
                "    \n",
                "    def entropy_fast(data, num_bins=50):\n",
                "        hist, _ = np.histogram(data, bins=num_bins, density=True)\n",
                "        probs = hist * np.diff(np.histogram(data, bins=num_bins)[1])\n",
                "        mask = probs > 0\n",
                "        return float(-np.sum(probs[mask] * np.log2(probs[mask])))\n",
                "    \n",
                "    NUMBA_OK = False\n",
                "    print('Numba unavailable, using Scipy fallback ⚠️')\n",
                "\n",
                "def process_star(tic_id, sector=11, window_size=150):\n",
                "    \"\"\"Process single star with error handling.\"\"\"\n",
                "    try:\n",
                "        cache_key = f'/tmp/tess_{tic_id}.npy'\n",
                "        \n",
                "        if os.path.exists(cache_key):\n",
                "            flux = np.load(cache_key, allow_pickle=True)\n",
                "        else:\n",
                "            search = lk.search_lightcurve(f'TIC {tic_id}', sector=sector)\n",
                "            if len(search) == 0:\n",
                "                return {'tic_id': tic_id, 'status': 'no_data', 'anomalies': 0, 'mean_ks': 0}\n",
                "            lc = search.download_all().PDCSAP_FLUX\n",
                "            lc = lc.remove_nans().remove_outliers(sigma=5)\n",
                "            flux = lc.flux.value\n",
                "            np.save(cache_key, flux)\n",
                "        \n",
                "        n = len(flux)\n",
                "        if n < window_size:\n",
                "            window_size = min(100, n // 2)\n",
                "        \n",
                "        n_windows = max(1, n // window_size)\n",
                "        k_values, entropies = [], []\n",
                "        \n",
                "        for i in range(n_windows):\n",
                "            start = i * window_size\n",
                "            end = min(start + window_size, n)\n",
                "            w = flux[start:end]\n",
                "            k_values.append(ks_ratio_fast(w))\n",
                "            entropies.append(entropy_fast(w))\n",
                "        \n",
                "        if len(k_values) > 10:\n",
                "            mean_k = np.mean(k_values)\n",
                "            std_k = np.std(k_values)\n",
                "            threshold = mean_k - 3 * std_k\n",
                "            anomalies = int(sum(1 for k in k_values if k < threshold))\n",
                "        else:\n",
                "            mean_k = np.mean(k_values) if k_values else 0\n",
                "            std_k = np.std(k_values) if k_values else 0\n",
                "            anomalies = 0\n",
                "        \n",
                "        return {\n",
                "            'tic_id': int(tic_id),\n",
                "            'status': 'ok',\n",
                "            'cadences': n,\n",
                "            'anomalies': anomalies,\n",
                "            'mean_ks': float(mean_k),\n",
                "            'std_ks': float(std_k),\n",
                "            'threshold': float(mean_k - 3 * std_k if std_k > 0 else mean_k),\n",
                "        }\n",
                "    except Exception as e:\n",
                "        return {'tic_id': int(tic_id), 'status': 'error', 'error': str(e), 'anomalies': 0}\n",
                "\n",
                "print('Pipeline functions loaded ✅')"
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "outputs": [],
            "source": [
                "#@title 🚀 Run Parallel Analysis\n",
                "import pandas as pd\n",
                "from concurrent.futures import ThreadPoolExecutor\n",
                "import time\n",
                "\n",
                "# Load our expanded catalog\n",
                "catalog = pd.read_csv('data/expanded_star_catalog.csv')\n",
                "all_targets = catalog['tic_id'].tolist()\n",
                "\n",
                "print(f'Processing {len(all_targets)} targets in parallel...')\n",
                "print(f'GPU: {os.environ.get(\"COLAB_GPU\", \"Not detected\")}')\n",
                "\n",
                "# Use ThreadPoolExecutor for I/O bound MAST downloads\n",
                "start = time.time()\n",
                "results = []\n",
                "\n",
                "with ThreadPoolExecutor(max_workers=8) as executor:\n",
                "    futures = {executor.submit(process_star, tic): tic for tic in all_targets}\n",
                "    for i, future in enumerate(futures, 1):\n",
                "        r = future.result()\n",
                "        results.append(r)\n",
                "        elapsed = time.time() - start\n",
                "        print(f'  [{i}/{len(all_targets)}] TIC {r[\"tic_id\"]}: '\n",
                "              f\"{r.get('anomalies',0)} anomalies | \"\n",
                "              f'rate={i/elapsed:.1f}/min')\n",
                "\n",
                "# Save results\n",
                "results_df = pd.DataFrame(results)\n",
                "results_df.to_csv('data/colab_results.csv', index=False)\n",
                "\n",
                "# Summary\n",
                "success = len(results_df[results_df['status'] == 'ok'])\n",
                "errors = len(results_df[results_df['status'] == 'error'])\n",
                "total_anom = results_df[results_df['status'] == 'ok']['anomalies'].sum()\n",
                "\n",
                "print(f'\\n=== COLAB ANALYSIS COMPLETE ===')\n",
                "print(f'Targets processed: {len(results)}')\n",
                "print(f'Successful: {success}')\n",
                "print(f'Errors: {errors}')\n",
                "print(f'Total anomalies: {total_anom}')\n",
                "print(f'Time: {time.time()-start:.1f}s')\n",
                "print(f'\\nResults saved to data/colab_results.csv')"
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "outputs": [],
            "source": [
                "#@title 💾 Save Results to GitHub\n",
                "%cd /content/entropy-anomaly-seti\n",
                "!git config --global user.email 'colab@nnw.ai'\n",
                "!git config --global user.name 'Colab Worker'\n",
                "!git add data/colab_results.csv\n",
                "!git commit -m 'Colab analysis results'\n",
                "!git push origin master\n",
                "print('Results committed and pushed ✅')"
            ]
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## Next Steps After Colab Run\n",
                "1. Download `data/colab_results.csv` from Google Drive\n",
                "2. Merge with workstation results in `data/`\n",
                "3. Proceed to Phase 3: Cross-cluster correlation analysis\n",
                "---\n",
                "\n",
                "*Generated by setup_and_run.sh — ready for upload at [colab.research.google.com](https://colab.research.google.com/upload)*"
            ]
        }
    ],
    "metadata": {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3"
        },
        "language_info": {
            "name": "python",
            "version": "3.10.0"
        }
    },
    "nbformat": 4,
    "nbformat_minor": 4
}

def main():
    with open(NOTEBOOK_PATH, 'w') as f:
        json.dump(NOTEBOOK, f, indent=2)
    print(f"Colab notebook saved to: {NOTEBOOK_PATH}")
    print(f"Size: {os.path.getsize(NOTEBOOK_PATH)} bytes")
    print("Upload to: https://colab.research.google.com/upload")

if __name__ == "__main__":
    main()
