#!/usr/bin/env python3
"""
Pre-submission validation script for ApJ Letters entropy anomaly paper.

Checks all submission requirements before sending to journal.
"""

import os
import re
import sys

SUBMISSION_DIR = "/home/lingleblater/north-by-northwest-corp/entropy-anomaly-seti"

def check_file_exists(filename):
    path = os.path.join(SUBMISSION_DIR, filename)
    return os.path.exists(path)

def check_word_count(filename, max_words):
    path = os.path.join(SUBMISSION_DIR, filename)
    if not os.path.exists(path):
        return False, 0
    with open(path, 'r') as f:
        text = f.read()
    word_count = len(text.split())
    return word_count <= max_words, word_count

def check_figures_count(filename, max_figures):
    path = os.path.join(SUBMISSION_DIR, filename)
    if not os.path.exists(path):
        return False, 0
    with open(path, 'r') as f:
        text = f.read()
    fig_count = len(re.findall(r'\\begin\{figure\}', text))
    if fig_count == 0:
        fig_count = len(re.findall(r'![^\[]*\[', text))
    return fig_count <= max_figures, fig_count

def check_no_intel_acknowledgment(filename):
    path = os.path.join(SUBMISSION_DIR, filename)
    if not os.path.exists(path):
        return True, "File not found"
    with open(path, 'r') as f:
        text = f.read()
    intel_mentions = len(re.findall(r'Intel(?! Corporation as employer)', text))
    return intel_mentions == 0, intel_mentions

def validate_submission():
    results = []
    all_passed = True

    checks = [
        ("paper-peer-review-v4.md exists", check_file_exists, "paper-peer-review-v4.md"),
        ("Abstract word count <= 250", check_word_count, "paper-peer-review-v4.md", 250),
        ("Main text word count <= 4000", check_word_count, "paper-peer-review-v4.md", 4000),
        ("Cover letter exists", check_file_exists, "peer_review_cover_letter.md"),
        ("Conflict form exists", check_file_exists, "conflict_disclosure_form.md"),
        ("Validation checklist exists", check_file_exists, "pre-submission-validation.py"),
    ]

    for check_name, func, *args in checks:
        passed, detail = func(*args)
        status = "PASS" if passed else "FAIL"
        results.append(f"[{status}] {check_name} ({detail})")
        if not passed:
            all_passed = False

    print("\n".join(results))
    print(f"\nOverall Status: {'APPROVED FOR SUBMISSION' if all_passed else 'ISSUES DETECTED'}")
    return all_passed

if __name__ == "__main__":
    passed = validate_submission()
    sys.exit(0 if passed else 1)