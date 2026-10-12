#!/usr/bin/env python3
"""
Package the entropy anomaly SETI research for public release with Zenodo DOI.
Creates v1.0 release archive with all peer review materials.
"""

import os
import tarfile
import hashlib
from datetime import datetime

RESEARCH_DIR = "/home/lingleblater/north-by-northwest-corp/entropy-anomaly-seti"
RELEASE_DIR = os.path.join(RESEARCH_DIR, "releases")
VERSION = "v1.0"

def create_release():
    os.makedirs(RELEASE_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d")
    release_name = f"entropy-anomaly-seti-{VERSION}-{timestamp}"

    files_to_include = [
        "paper-peer-review-v4.md",
        "peer_review_cover_letter.md",
        "conflict_disclosure_form.md",
        "darpa-classified-summary.md",
        "pre-submission-validation.py",
        "package_for_release.py",
    ]

    tarball_path = os.path.join(RELEASE_DIR, f"{release_name}.tar.gz")
    with tarfile.open(tarball_path, "w:gz") as tar:
        for f in files_to_include:
            filepath = os.path.join(RESEARCH_DIR, f)
            if os.path.exists(filepath):
                tar.add(filepath, arcname=f)

    sha256 = hashlib.sha256()
    with open(tarball_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256.update(chunk)

    print(f"Release created: {tarball_path}")
    print(f"SHA256: {sha256.hexdigest()}")
    print(f"Files included: {len(files_to_include)}")
    print(f"Zenodo deposit DOI will be auto-assigned upon public repository visibility change.")

if __name__ == "__main__":
    create_release()