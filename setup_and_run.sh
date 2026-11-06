#!/bin/bash
# ===================================================================
# NbNW Entropy Anomaly SETI Pipeline - Workstation Edition
# One-click setup + execution.
#
# IMPORTANT: this script NO LONGER generates the Python runner via a
# heredoc. pipeline/workstation_runner.py is a committed, syntax-checked
# source file. Earlier heredoc versions produced indentation/syntax bugs
# ("break outside loop") and numba conflicts ("numpy.save").
# ===================================================================

set -e

WORK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$WORK_DIR" || exit 1
mkdir -p "$WORK_DIR/results" "$WORK_DIR/data" "$WORK_DIR/pipeline"

echo "============================================================"
echo "  NbNW Entropy Anomaly SETI Pipeline - Workstation Edition"
echo "============================================================"

echo ""
echo "[1/3] System resources..."
echo "  CPU Cores : $(nproc)"
echo "  RAM       : $(free -g | awk '/^Mem:/{print $2}') GB"
echo "  Disk free : $(df -h . | tail -1 | awk '{print $4}')"

echo ""
echo "[2/3] Python environment..."
VENV="$WORK_DIR/venv_workstation"
if [ ! -d "$VENV" ]; then
    python3 -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

pip install --quiet --upgrade pip
pip install --quiet \
    "numpy>=1.24" \
    "scipy>=1.10" \
    "pandas>=2.0" \
    "lightkurve>=2.0" \
    "astropy>=5.3" \
    "astroquery>=0.4"

echo "  Ready (numpy/scipy/pandas/lightkurve/astropy)"

echo ""
echo "[3/3] Running pipeline..."
echo "  (use --test for a 2-target verbose diagnostic)"
echo ""
python3 "$WORK_DIR/pipeline/workstation_runner.py" "$@"

echo ""
echo "============================================================"
echo "  COMPLETE - results in $WORK_DIR/results/"
echo "============================================================"
echo ""
echo "Re-run:  bash setup_and_run.sh"
echo "Test:    bash setup_and_run.sh --test"
echo "Direct:  python3 $WORK_DIR/pipeline/workstation_runner.py --verbose"
