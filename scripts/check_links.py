#!/usr/bin/env python3
"""
Link Validation Script for Iceland Tourism Directory

Checks all links in _includes/*.md files for:
- HTTP status (200 OK, 404 Not Found, etc.)
- Response time (flags slow links)
- Redirects

Usage:
    python3 scripts/check_links.py
    python3 scripts/check_links.py --timeout 10
    python3 scripts/check_links.py --verbose
"""

import os
import re
import time
import json
import requests
from datetime import datetime
from pathlib import Path
import argparse
from urllib.parse import urlparse

# Disable SSL warnings for sites with cert issues
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class LinkChecker:
    def __init__(self, timeout=10, verbose=False):
        self.timeout = timeout
        self.verbose = verbose
        self.results = {
            'timestamp': datetime.now().isoformat(),
            'summary': {
                'total': 0,
                'working': 0,
                'broken': 0,
                'slow': 0,
                'redirects': 0
            },
            'links': []
        }

    def extract_links_from_file(self, filepath):
        """Extract all URLs from markdown file"""
        links = []
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Match <a href="URL">
        pattern = r'<a\s+href="([^"]+)"[^>]*>'
        matches = re.findall(pattern, content)

        for url in matches:
            if url.startswith('http'):
                links.append(url)

        return links

    def check_link(self, url, source_file):
        """Check a single URL and return status"""
        result = {
            'url': url,
            'source': source_file,
            'status': None,
            'status_code': None,
            'response_time': None,
            'error': None,
            'final_url': url
        }

        try:
            start_time = time.time()
            response = requests.head(
                url,
                timeout=self.timeout,
                allow_redirects=True,
                verify=False,  # Skip SSL verification for problematic sites
                headers={'User-Agent': 'Mozilla/5.0 (Link Checker)'}
            )
            response_time = time.time() - start_time

            result['status_code'] = response.status_code
            result['response_time'] = round(response_time, 2)
            result['final_url'] = response.url

            # Determine status
            if response.status_code == 200:
                result['status'] = 'slow' if response_time > 5 else 'working'
            elif response.status_code in [301, 302, 303, 307, 308]:
                result['status'] = 'redirect'
            elif response.status_code == 404:
                result['status'] = 'broken'
            elif response.status_code >= 500:
                result['status'] = 'server_error'
            else:
                result['status'] = 'warning'

        except requests.exceptions.Timeout:
            result['status'] = 'timeout'
            result['error'] = f'Timeout after {self.timeout}s'
        except requests.exceptions.ConnectionError as e:
            result['status'] = 'broken'
            result['error'] = 'Connection failed'
        except requests.exceptions.TooManyRedirects:
            result['status'] = 'broken'
            result['error'] = 'Too many redirects'
        except Exception as e:
            result['status'] = 'error'
            result['error'] = str(e)

        return result

    def check_all_links(self, includes_dir):
        """Check all links in _includes directory"""
        md_files = Path(includes_dir).glob('*.md')

        for md_file in md_files:
            if self.verbose:
                print(f"\nProcessing: {md_file.name}")

            links = self.extract_links_from_file(md_file)

            for url in links:
                self.results['summary']['total'] += 1

                if self.verbose:
                    print(f"  Checking: {url[:60]}...")

                result = self.check_link(url, md_file.name)
                self.results['links'].append(result)

                # Update summary
                if result['status'] == 'working':
                    self.results['summary']['working'] += 1
                elif result['status'] == 'broken':
                    self.results['summary']['broken'] += 1
                elif result['status'] == 'slow':
                    self.results['summary']['slow'] += 1
                elif result['status'] == 'redirect':
                    self.results['summary']['redirects'] += 1

                # Brief pause to avoid overwhelming servers
                time.sleep(0.5)

    def print_report(self):
        """Print summary report to console"""
        print("\n" + "="*80)
        print("LINK VALIDATION REPORT")
        print("="*80)
        print(f"\nTimestamp: {self.results['timestamp']}")
        print(f"\nSummary:")
        print(f"  Total links checked: {self.results['summary']['total']}")
        print(f"  ✓ Working:          {self.results['summary']['working']}")
        print(f"  ⚠ Slow (>5s):       {self.results['summary']['slow']}")
        print(f"  ↪ Redirects:        {self.results['summary']['redirects']}")
        print(f"  ✗ Broken:           {self.results['summary']['broken']}")

        # Show broken links
        broken = [l for l in self.results['links'] if l['status'] in ['broken', 'timeout', 'error', 'server_error']]
        if broken:
            print(f"\n{'='*80}")
            print("BROKEN LINKS:")
            print("="*80)
            for link in broken:
                print(f"\n  File: {link['source']}")
                print(f"  URL: {link['url']}")
                print(f"  Status: {link['status']}")
                if link['error']:
                    print(f"  Error: {link['error']}")
                if link['status_code']:
                    print(f"  Code: {link['status_code']}")

        # Show slow links
        slow = [l for l in self.results['links'] if l['status'] == 'slow']
        if slow:
            print(f"\n{'='*80}")
            print("SLOW LINKS (>5 seconds):")
            print("="*80)
            for link in slow:
                print(f"\n  File: {link['source']}")
                print(f"  URL: {link['url']}")
                print(f"  Time: {link['response_time']}s")

        # Show redirects
        redirects = [l for l in self.results['links'] if l['status'] == 'redirect']
        if redirects:
            print(f"\n{'='*80}")
            print("REDIRECTS (consider updating):")
            print("="*80)
            for link in redirects[:10]:  # Show first 10
                print(f"\n  File: {link['source']}")
                print(f"  Old: {link['url']}")
                print(f"  New: {link['final_url']}")
            if len(redirects) > 10:
                print(f"\n  ... and {len(redirects) - 10} more redirects")

        print("\n" + "="*80)

    def save_results(self, output_file):
        """Save detailed results to JSON"""
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, indent=2)
        print(f"\nDetailed results saved to: {output_file}")


def main():
    parser = argparse.ArgumentParser(description='Check all links in Iceland Tourism Directory')
    parser.add_argument('--timeout', type=int, default=10, help='Timeout in seconds (default: 10)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--output', default='scripts/link_check_results.json', help='Output JSON file')
    args = parser.parse_args()

    # Get paths
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent
    includes_dir = repo_root / '_includes'

    if not includes_dir.exists():
        print(f"Error: _includes directory not found at {includes_dir}")
        return 1

    print("Iceland Tourism Directory - Link Checker")
    print(f"Checking links in: {includes_dir}")
    print(f"Timeout: {args.timeout}s")
    print("-" * 80)

    checker = LinkChecker(timeout=args.timeout, verbose=args.verbose)
    checker.check_all_links(includes_dir)
    checker.print_report()

    # Save results
    output_path = repo_root / args.output
    checker.save_results(output_path)

    # Exit code: 0 if no broken links, 1 if broken links found
    return 1 if checker.results['summary']['broken'] > 0 else 0


if __name__ == '__main__':
    exit(main())
