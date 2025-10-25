#!/usr/bin/env python3
"""
Link Validation Script for Iceland Tourism Directory

Checks all links in _includes/*.md files for:
- HTTP status (200 OK, 404 Not Found, etc.)
- Response time (flags slow links)
- Redirects (actual URL changes, not just status codes)
- Parked domains
- Fake 404 pages (return 200 but show error)
- Homepage redirects

Features:
- Parallel checking with configurable workers
- Smart content detection
- Configurable logging
- Priority-based checking
- Retry logic for HEAD failures

Usage:
    python3 scripts/check_links.py
    python3 scripts/check_links.py --verbose
    python3 scripts/check_links.py --config scripts/custom_config.json
    python3 scripts/check_links.py --quick  # Only check previously broken
"""

import os
import re
import time
import json
import requests
import logging
from datetime import datetime
from pathlib import Path
import argparse
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

# Disable SSL warnings for sites with cert issues
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class LinkChecker:
    def __init__(self, config_path=None, verbose=False):
        self.verbose = verbose
        self.config = self.load_config(config_path)
        self.setup_logging()

        self.results = {
            'timestamp': datetime.now().isoformat(),
            'summary': {
                'total': 0,
                'working': 0,
                'broken': 0,
                'slow': 0,
                'redirects': 0,
                'timeout': 0,
                'server_error': 0,
                'warning': 0,
                'parked': 0,
                'fake_404': 0
            },
            'links': []
        }

        # Load previous results if they exist for comparison
        self.previous_results = self.load_previous_results()

    def load_config(self, config_path):
        """Load configuration from JSON file"""
        if config_path is None:
            config_path = Path(__file__).parent / 'check_links_config.json'

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            logging.warning(f"Config file not found at {config_path}, using defaults")
            return self.default_config()

    def default_config(self):
        """Return default configuration"""
        return {
            "output": {
                "json_file": "scripts/link_check_results.json",
                "log_file": "scripts/link_checker.log",
                "log_level": "INFO",
                "save_only_problems": False
            },
            "checking": {
                "timeout": 10,
                "slow_threshold": 5,
                "max_workers": 10,
                "retry_with_get": True,
                "rate_limit_delay": 0.1
            },
            "features": {
                "detect_parked_domains": True,
                "detect_fake_404": True,
                "detect_homepage_redirects": True,
                "check_title_changes": False,
                "screenshot_failures": False
            },
            "priority_files": [
                "emergency.md",
                "weather.md",
                "transportation.md"
            ],
            "parked_domain_keywords": [
                "domain parked",
                "this domain is for sale",
                "buy this domain",
                "domain parking",
                "sedo",
                "godaddy parked"
            ],
            "fake_404_keywords": [
                "404",
                "not found",
                "page not found",
                "error 404",
                "doesn't exist"
            ]
        }

    def setup_logging(self):
        """Setup logging with file and console handlers"""
        log_level = getattr(logging, self.config['output']['log_level'], logging.INFO)

        # Create logger
        self.logger = logging.getLogger('LinkChecker')
        self.logger.setLevel(log_level)

        # Clear any existing handlers
        self.logger.handlers = []

        # File handler
        log_file = Path(self.config['output']['log_file'])
        log_file.parent.mkdir(exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(log_level)

        # Console handler (only if verbose)
        if self.verbose:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(log_level)
            self.logger.addHandler(console_handler)

        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)

        self.logger.addHandler(file_handler)
        self.logger.info("="*60)
        self.logger.info("Link Checker started")
        self.logger.info(f"Config: {self.config}")

    def load_previous_results(self):
        """Load previous results for comparison"""
        try:
            results_path = Path(self.config['output']['json_file'])
            if results_path.exists():
                with open(results_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            self.logger.warning(f"Could not load previous results: {e}")
        return None

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

    def is_parked_domain(self, content):
        """Check if page content indicates a parked domain"""
        if not self.config['features']['detect_parked_domains']:
            return False

        content_lower = content.lower()
        for keyword in self.config['parked_domain_keywords']:
            if keyword.lower() in content_lower:
                self.logger.debug(f"Parked domain keyword found: {keyword}")
                return True
        return False

    def is_fake_404(self, content, status_code):
        """Check if page returns 200 but is actually a 404"""
        if not self.config['features']['detect_fake_404']:
            return False

        if status_code != 200:
            return False

        content_lower = content.lower()
        # Count how many 404 keywords appear
        matches = 0
        for keyword in self.config['fake_404_keywords']:
            if keyword.lower() in content_lower:
                matches += 1

        # If 2+ keywords found, likely a fake 404
        if matches >= 2:
            self.logger.debug(f"Fake 404 detected: {matches} keywords found")
            return True
        return False

    def is_homepage_redirect(self, original_url, final_url):
        """Check if URL redirects to homepage"""
        if not self.config['features']['detect_homepage_redirects']:
            return False

        try:
            original_parsed = urlparse(original_url)
            final_parsed = urlparse(final_url)

            # Same domain but final path is just / or empty
            if (original_parsed.netloc == final_parsed.netloc and
                final_parsed.path in ['/', ''] and
                original_parsed.path not in ['/', '']):
                self.logger.debug(f"Homepage redirect detected: {original_url} -> {final_url}")
                return True
        except Exception as e:
            self.logger.debug(f"Error checking homepage redirect: {e}")

        return False

    def check_link(self, url, source_file):
        """Check a single URL and return detailed status"""
        result = {
            'url': url,
            'source': source_file,
            'status': None,
            'status_code': None,
            'response_time': None,
            'error': None,
            'final_url': url,
            'warnings': []
        }

        try:
            start_time = time.time()

            # Try HEAD request first
            response = requests.head(
                url,
                timeout=self.config['checking']['timeout'],
                allow_redirects=True,
                verify=False,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            )

            # BUG FIX #3: Retry with GET if HEAD fails with 403/405/501
            if (self.config['checking']['retry_with_get'] and
                response.status_code in [403, 405, 501]):
                self.logger.debug(f"HEAD failed with {response.status_code}, retrying with GET: {url}")
                response = requests.get(
                    url,
                    timeout=self.config['checking']['timeout'],
                    allow_redirects=True,
                    verify=False,
                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                )

            response_time = time.time() - start_time

            result['status_code'] = response.status_code
            result['response_time'] = round(response_time, 2)
            result['final_url'] = response.url

            # Get content for smart detection (only if we did GET request or status is suspicious)
            content = ""
            if response.request.method == 'GET' or response.status_code == 200:
                try:
                    # For HEAD requests that succeeded, do a quick GET to check content
                    if response.request.method == 'HEAD' and (
                        self.config['features']['detect_parked_domains'] or
                        self.config['features']['detect_fake_404']):
                        content_response = requests.get(
                            url,
                            timeout=self.config['checking']['timeout'],
                            verify=False,
                            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                        )
                        content = content_response.text[:5000]  # First 5KB only
                    else:
                        content = response.text[:5000] if hasattr(response, 'text') else ""
                except:
                    pass

            # BUG FIX #1: Check for redirects by comparing URLs, not status codes
            is_redirect = (result['final_url'] != url)

            # Smart detection
            is_parked = self.is_parked_domain(content)
            is_fake404 = self.is_fake_404(content, response.status_code)
            is_homepage = self.is_homepage_redirect(url, result['final_url'])

            # Determine final status
            if is_parked:
                result['status'] = 'parked'
                result['warnings'].append('Domain appears to be parked')
            elif is_fake404:
                result['status'] = 'fake_404'
                result['warnings'].append('Page returns 200 but shows 404 content')
            elif response.status_code == 404:
                result['status'] = 'broken'
            elif response.status_code >= 500:
                result['status'] = 'server_error'
            elif response.status_code == 200:
                if is_homepage:
                    result['status'] = 'redirect'
                    result['warnings'].append('Redirects to homepage')
                elif is_redirect:
                    result['status'] = 'redirect'
                elif response_time > self.config['checking']['slow_threshold']:
                    result['status'] = 'slow'
                    result['warnings'].append(f'Response time > {self.config["checking"]["slow_threshold"]}s')
                else:
                    result['status'] = 'working'
            elif is_redirect:
                result['status'] = 'redirect'
            else:
                result['status'] = 'warning'
                result['warnings'].append(f'Unusual status code: {response.status_code}')

        except requests.exceptions.Timeout:
            result['status'] = 'timeout'
            result['error'] = f'Timeout after {self.config["checking"]["timeout"]}s'
        except requests.exceptions.ConnectionError as e:
            result['status'] = 'broken'
            result['error'] = 'Connection failed'
        except requests.exceptions.TooManyRedirects:
            result['status'] = 'broken'
            result['error'] = 'Too many redirects'
        except Exception as e:
            result['status'] = 'error'
            result['error'] = str(e)

        self.logger.debug(f"Checked {url}: {result['status']} ({result['status_code']})")
        return result

    def check_all_links(self, includes_dir):
        """Check all links in _includes directory with parallel processing"""
        md_files = list(Path(includes_dir).glob('*.md'))

        # Sort by priority
        priority_files = self.config.get('priority_files', [])
        md_files.sort(key=lambda f: (
            f.name not in priority_files,
            priority_files.index(f.name) if f.name in priority_files else 999
        ))

        # Collect all links with their source files
        all_links = []
        for md_file in md_files:
            self.logger.info(f"Processing file: {md_file.name}")
            links = self.extract_links_from_file(md_file)
            for url in links:
                all_links.append((url, md_file.name))

        self.results['summary']['total'] = len(all_links)
        self.logger.info(f"Total links to check: {len(all_links)}")

        # Check links in parallel
        max_workers = self.config['checking']['max_workers']
        self.logger.info(f"Starting parallel checking with {max_workers} workers")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_link = {
                executor.submit(self.check_link, url, source): (url, source)
                for url, source in all_links
            }

            # Process results as they complete
            completed = 0
            for future in as_completed(future_to_link):
                url, source = future_to_link[future]
                try:
                    result = future.result()
                    self.results['links'].append(result)

                    # BUG FIX #2: Update summary for ALL status types
                    status = result['status']
                    if status in self.results['summary']:
                        self.results['summary'][status] += 1

                    completed += 1
                    if self.verbose and completed % 10 == 0:
                        print(f"Progress: {completed}/{len(all_links)} links checked")

                except Exception as e:
                    self.logger.error(f"Error checking {url}: {e}")

                # Rate limiting (small delay to avoid overwhelming servers)
                time.sleep(self.config['checking']['rate_limit_delay'])

        self.logger.info("All links checked")

    def print_report(self):
        """Print summary report to console"""
        print("\n" + "="*80)
        print("LINK VALIDATION REPORT")
        print("="*80)
        print(f"\nTimestamp: {self.results['timestamp']}")
        print(f"\nSummary:")
        print(f"  Total links checked:  {self.results['summary']['total']}")
        print(f"  ✓ Working:            {self.results['summary']['working']}")
        print(f"  ⚠ Slow (>{self.config['checking']['slow_threshold']}s):      {self.results['summary']['slow']}")
        print(f"  ↪ Redirects:          {self.results['summary']['redirects']}")
        print(f"  ✗ Broken:             {self.results['summary']['broken']}")
        print(f"  ⏱ Timeout:            {self.results['summary']['timeout']}")
        print(f"  ⚡ Server Error:      {self.results['summary']['server_error']}")
        print(f"  ⚠ Warning:            {self.results['summary']['warning']}")

        if self.config['features']['detect_parked_domains']:
            print(f"  🅿 Parked Domains:    {self.results['summary']['parked']}")
        if self.config['features']['detect_fake_404']:
            print(f"  🚫 Fake 404s:         {self.results['summary']['fake_404']}")

        # Show broken links
        broken_statuses = ['broken', 'timeout', 'error', 'server_error', 'parked', 'fake_404']
        broken = [l for l in self.results['links'] if l['status'] in broken_statuses]
        if broken:
            print(f"\n{'='*80}")
            print(f"BROKEN/PROBLEMATIC LINKS ({len(broken)}):")
            print("="*80)
            for link in broken:
                print(f"\n  File: {link['source']}")
                print(f"  URL: {link['url']}")
                print(f"  Status: {link['status'].upper()}")
                if link['status_code']:
                    print(f"  Code: {link['status_code']}")
                if link['error']:
                    print(f"  Error: {link['error']}")
                if link['warnings']:
                    print(f"  Warnings: {', '.join(link['warnings'])}")

        # Show slow links
        slow = [l for l in self.results['links'] if l['status'] == 'slow']
        if slow:
            print(f"\n{'='*80}")
            print(f"SLOW LINKS (>{self.config['checking']['slow_threshold']} seconds):")
            print("="*80)
            for link in slow[:10]:  # Show first 10
                print(f"\n  File: {link['source']}")
                print(f"  URL: {link['url']}")
                print(f"  Time: {link['response_time']}s")
            if len(slow) > 10:
                print(f"\n  ... and {len(slow) - 10} more slow links")

        # Show redirects
        redirects = [l for l in self.results['links'] if l['status'] == 'redirect']
        if redirects:
            print(f"\n{'='*80}")
            print(f"REDIRECTS ({len(redirects)}) - consider updating:")
            print("="*80)
            for link in redirects[:10]:  # Show first 10
                print(f"\n  File: {link['source']}")
                print(f"  Old: {link['url']}")
                print(f"  New: {link['final_url']}")
                if link['warnings']:
                    print(f"  Note: {', '.join(link['warnings'])}")
            if len(redirects) > 10:
                print(f"\n  ... and {len(redirects) - 10} more redirects")

        print("\n" + "="*80)

    def save_results(self, output_file):
        """Save detailed results to JSON"""
        # Create a copy of results for saving
        results_to_save = self.results.copy()

        # Filter out working links if configured
        if self.config['output'].get('save_only_problems', False):
            original_count = len(results_to_save['links'])
            results_to_save['links'] = [
                link for link in results_to_save['links']
                if link['status'] != 'working'
            ]
            filtered_count = original_count - len(results_to_save['links'])
            self.logger.info(f"Filtered out {filtered_count} working links from results file")

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results_to_save, f, indent=2)

        print(f"\nDetailed results saved to: {output_file}")
        if self.config['output'].get('save_only_problems', False):
            print(f"  (Only problematic links saved - {len(results_to_save['links'])} links)")
        print(f"Log file saved to: {self.config['output']['log_file']}")


def main():
    parser = argparse.ArgumentParser(
        description='Check all links in Iceland Tourism Directory',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--config', help='Path to config JSON file')
    parser.add_argument('--timeout', type=int, help='Timeout in seconds (overrides config)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose console output')
    parser.add_argument('--workers', type=int, help='Max parallel workers (overrides config)')
    parser.add_argument('--only-problems', action='store_true', help='Save only problematic links in results file')
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
    print("-" * 80)

    # Initialize checker
    checker = LinkChecker(config_path=args.config, verbose=args.verbose)

    # Override config with CLI args if provided
    if args.timeout:
        checker.config['checking']['timeout'] = args.timeout
    if args.workers:
        checker.config['checking']['max_workers'] = args.workers
    if args.only_problems:
        checker.config['output']['save_only_problems'] = True

    print(f"Timeout: {checker.config['checking']['timeout']}s")
    print(f"Max workers: {checker.config['checking']['max_workers']}")
    print(f"Smart detection: Parked={checker.config['features']['detect_parked_domains']}, "
          f"Fake404={checker.config['features']['detect_fake_404']}, "
          f"HomepageRedirect={checker.config['features']['detect_homepage_redirects']}")

    # Check all links
    checker.check_all_links(includes_dir)
    checker.print_report()

    # Save results
    output_path = repo_root / checker.config['output']['json_file']
    checker.save_results(output_path)

    # Exit code: 0 if no broken links, 1 if broken links found
    broken_count = (checker.results['summary']['broken'] +
                   checker.results['summary']['timeout'] +
                   checker.results['summary']['parked'] +
                   checker.results['summary']['fake_404'])

    return 1 if broken_count > 0 else 0


if __name__ == '__main__':
    exit(main())
