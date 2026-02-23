#!/usr/bin/env python3
"""Quick script to count pages on help.pracsuite.com via sitemap or crawl discovery."""

import requests
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse
import sys

def fetch_sitemap(url):
    """Fetch and parse a sitemap.xml file."""
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"Could not fetch sitemap: {e}")
        return None

def count_urls_in_sitemap(xml_content):
    """Count URLs in sitemap XML content."""
    if not xml_content:
        return 0, []
    try:
        root = ET.fromstring(xml_content)
        # Handle both standard sitemap format and sitemap index
        urls = []
        for elem in root.iter():
            if elem.tag.endswith('loc'):
                urls.append(elem.text)
        return len(urls), urls
    except ET.ParseError as e:
        print(f"XML parse error: {e}")
        return 0, []

def main():
    base_url = "https://help.pracsuite.com"
    sitemap_url = urljoin(base_url, "/sitemap.xml")
    
    print(f"Fetching sitemap from {sitemap_url}...")
    xml_content = fetch_sitemap(sitemap_url)
    
    if xml_content:
        count, urls = count_urls_in_sitemap(xml_content)
        if count > 0:
            print(f"\n✓ Found {count} URLs in sitemap.xml")
            # Show first 10 URLs as sample
            print("\nSample URLs:")
            for url in urls[:10]:
                print(f"  - {url}")
            if count > 10:
                print(f"  ... and {count - 10} more")
            return count
        else:
            print("Sitemap found but no URLs parsed.")
    
    # Fallback: try common sitemap variations
    print("\nTrying alternative sitemap locations...")
    alt_paths = ["/sitemap_index.xml", "/sitemap1.xml", "/sitemap/sitemap.xml"]
    for path in alt_paths:
        alt_url = urljoin(base_url, path)
        content = fetch_sitemap(alt_url)
        if content:
            count, urls = count_urls_in_sitemap(content)
            if count > 0:
                print(f"✓ Found {count} URLs in {path}")
                return count
    
    print("\n✗ No sitemap found. Site may require crawling to count pages.")
    return None

if __name__ == "__main__":
    count = main()
    if count:
        print(f"\n>>> TOTAL PAGES: {count}")
    sys.exit(0 if count else 1)
