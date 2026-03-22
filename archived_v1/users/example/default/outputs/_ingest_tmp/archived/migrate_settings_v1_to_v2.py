#!/usr/bin/env python3
"""
One-time migration:
- settings.yaml (v1) → config/*.yaml (v2)
- Original file preserved verbatim
"""

import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(".").resolve()
SRC = ROOT / "settings.yaml"
CFG = ROOT / "config"
LEGACY = CFG / "legacy"

if not SRC.exists():
    print("ERROR: settings.yaml not found")
    sys.exit(1)

CFG.mkdir(exist_ok=True)
LEGACY.mkdir(exist_ok=True)

# ------------------------------------------------------------------
# Load v1
# ------------------------------------------------------------------
raw = yaml.safe_load(SRC.read_text())
if not isinstance(raw, dict):
    print("ERROR: settings.yaml is not a mapping")
    sys.exit(1)

version = raw.get("version", 1)

# ------------------------------------------------------------------
# Preserve original
# ------------------------------------------------------------------
legacy_copy = LEGACY / f"settings.v{version}.yaml"
if not legacy_copy.exists():
    shutil.copy2(SRC, legacy_copy)
    print(f"✓ Preserved legacy → {legacy_copy}")
else:
    print(f"✓ Legacy already exists → {legacy_copy}")

# ------------------------------------------------------------------
# Section → file mapping
# ------------------------------------------------------------------
SECTIONS = {
    "paths": "paths.yaml",
    "resume": "resume.yaml",
    "workspace": "workspace.yaml",
    "ranking": "ranking.yaml",
    "functional_role_terms": "functional_roles.yaml",
    "company_scoring": "company_scoring.yaml",
    "profiles": "profiles.yaml",
    "embeddings": "embeddings.yaml",
    "llm": "llm.yaml",
    "scraping": "scraping.yaml",
    "cache": "cache.yaml",
    "outputs": "outputs.yaml",
    "scheduler": "scheduler.yaml",
    "logging": "logging.yaml",
    "environment": "environment.yaml",
    "search": "search.yaml",
    "skills": "skills.yaml",
}

written = []

# ------------------------------------------------------------------
# Write split files
# ------------------------------------------------------------------
for key, fname in SECTIONS.items():
    if key not in raw:
        continue

    out = CFG / fname
    payload = {key: raw[key]}

    out.write_text(yaml.safe_dump(payload, sort_keys=False))
    written.append(fname)

# ------------------------------------------------------------------
# Write new root settings.yaml (v2)
# ------------------------------------------------------------------
root_v2 = {
    "version": 2,
    "includes": [f"config/{f}" for f in written],
}

SRC.write_text(yaml.safe_dump(root_v2, sort_keys=False))

print("\n✓ Migration complete")
print("  New v2 root → settings.yaml")
print("  Split files:")
for f in written:
    print(f"   - config/{f}")

print("\nNext steps:")
print("  1) Update config_loader to support includes")
print("  2) Run a dry load: python - << 'EOF' ... EOF")
