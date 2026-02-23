#!/usr/bin/env python3
"""Verify all 15 PracSuite Help Center collections are present in the crawl."""

from pathlib import Path

COLLECTIONS = [
    "Getting Started With PracSuite",
    "PracSuite AI",
    "Appointment Book",
    "Invoicing",
    "SMS, Email & Letters",
    "Online Booking",
    "Forms",
    "Integrations",
    "Clinical Notes",
    "Users & Security",
    "Reporting",
    "Patient File Management",
    "Contacts",
    "Your PracSuite Subscription",
    "Miscellaneous",
]

def check_collections(filepath: Path):
    content = filepath.read_text(encoding="utf-8")
    
    found = []
    missing = []
    
    for collection in COLLECTIONS:
        # Search for collection name (case insensitive)
        if collection.lower() in content.lower():
            found.append(collection)
        else:
            missing.append(collection)
    
    print("=" * 60)
    print("PRACSUITE HELP CENTER COLLECTION COVERAGE CHECK")
    print("=" * 60)
    print(f"\nFile: {filepath}")
    print(f"Total Collections Expected: {len(COLLECTIONS)}")
    print(f"Found: {len(found)}")
    print(f"Missing: {len(missing)}")
    
    print(f"\n{'✓ FOUND COLLECTIONS:'}")
    for c in found:
        print(f"  ✓ {c}")
    
    if missing:
        print(f"\n{'✗ MISSING COLLECTIONS:'}")
        for c in missing:
            print(f"  ✗ {c}")
    else:
        print(f"\n{'🎉 ALL COLLECTIONS PRESENT!'}")
    
    return len(missing) == 0

if __name__ == "__main__":
    filepath = Path("output/help.pracsuite.com/help_index.md")
    if not filepath.exists():
        print(f"ERROR: File not found: {filepath}")
        print("Make sure you're running from the repo root.")
        exit(1)
    
    complete = check_collections(filepath)
    exit(0 if complete else 1)
