#!/bin/bash
# ===================================================================
# NbNW Entropy Anomaly SETI Pipeline - Workstation Edition
# One-click setup + execution.
#
# NOTES
#  * pipeline/workstation_runner.py is a COMMITTED, syntax-checked file.
#    This script no longer regenerates it via heredoc (that caused repeated
#    "break outside loop" / indentation bugs).
#  * The venv is validated properly: a half-created venv directory with no
#    bin/activate is wiped and rebuilt (fixes "No such file or directory"
#    on line 35 of the old script).
#  * Uses $VENV/bin/python3 -m pip directly instead of `source activate`,
#    so a missing/broken activate script can never abort the run.
# ===================================================================

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

VENV="$WORK_DIR/venv_workstation"
VPY="$VENV/bin/python3"

echo ""
echo "[2/3] Python environment..."

# Rebuild if the venv is missing OR incomplete (no python binary / no pip).
rebuild=0
if [ ! -x "$VPY" ]; then
    rebuild=1
elif ! "$VPY" -m pip --version >/dev/null 2>&1; then
    echo "  venv exists but pip is missing/broken - rebuilding"
    rebuild=1
fi

if [ "$rebuild" -eq 1 ]; then
    echo "  Creating virtual environment at $VENV ..."
    rm -rf "$VENV"
    if ! python3 -m venv "$VENV" 2>/dev/null; then
        echo "  python3-venv failed; trying --without-pip + ensurepip ..."
        python3 -m venv --without-pip "$VENV" 2>/dev/null || true
        if [ -x "$VPY" ]; then
            "$VPY" -m ensurepip --upgrade >/dev/null 2>&1 || true
        fi
    fi
fi

# Decide which interpreter runs the pipeline.
if [ -x "$VPY" ] && "$VPY" -m pip --version >/dev/null 2>&1; then
    PY="$VPY"
    PIP=("$VPY" -m pip)
else
    echo "  WARNING: venv unusable - falling back to system python3"
    PY="$(command -v python3)"
    if python3 -m pip --version >/dev/null 2>&1; then
        PIP=(python3 -m pip --break-system-packages)
    else
        PIP=(python3 -m pip)
    fi
fi

"${PIP[@]}" install --quiet --upgrade pip 2>/dev/null || true
"${PIP[@]}" install --quiet \
    "numpy>=1.24" \
    "scipy>=1.10" \
    "pandas>=2.0" \
    "lightkurve>=2.0" \
    "astropy>=5.3" \
    "astroquery>=0.4"

echo "  Ready ($PY)"

echo ""
echo "[3/3] Running pipeline..."
echo "  (use --test for a 2-target verbose diagnostic)"
echo ""
"$PY" "$WORK_DIR/pipeline/workstation_runner.py" "$@"

echo ""
echo "============================================================"
echo "  COMPLETE - results in $WORK_DIR/results/"
echo "============================================================"
echo ""
echo "Re-run:         bash setup_and_run.sh"
echo "Test:           bash setup_and_run.sh --test"
echo "Retry failed:   bash setup_and_run.sh --retry-missing"
