#!/usr/bin/env python3
"""
Redirect Auto-Fix Tool for Iceland Tourism Directory

Reads results from check_links.py and automatically updates redirected URLs
in markdown files. Safe by default with dry-run mode and automatic backups.

Usage:
    python3 scripts/fix_redirects.py                    # Preview (dry-run)
    python3 scripts/fix_redirects.py --apply            # Apply fixes
    python3 scripts/fix_redirects.py --apply --skip-homepage --skip-protocol-only
"""

import os
import re
import json
import shutil
import argparse
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


class RedirectFixer:
    def __init__(self, args):
        self.args = args
        self.results_path = Path(args.results)
        self.includes_dir = Path(args.includes_dir)
        self.results = None
        self.redirects = []
        self.fixable = []
        self.skipped = []
        self.fixes_by_file = {}

    def load_results(self):
        """Load link check results from JSON file"""
        if not self.results_path.exists():
            print(f"❌ Error: Results file not found: {self.results_path}")
            print(f"   Run check_links.py first to generate results")
            return False

        try:
            with open(self.results_path, 'r', encoding='utf-8') as f:
                self.results = json.load(f)
            return True
        except Exception as e:
            print(f"❌ Error reading results file: {e}")
            return False

    def filter_redirects(self):
        """Filter redirects based on arguments"""
        if not self.results or 'links' not in self.results:
            return

        # Get all redirects
        self.redirects = [
            link for link in self.results['links']
            if link.get('status') == 'redirect'
        ]

        if self.args.verbose:
            print(f"\n📊 Found {len(self.redirects)} redirects in results")

        # Filter each redirect
        for redirect in self.redirects:
            old_url = redirect['url']
            new_url = redirect.get('final_url', old_url)
            source_file = redirect['source']
            warnings = redirect.get('warnings', [])

            # Skip if URLs are identical (shouldn't happen)
            if old_url == new_url:
                self.skipped.append({
                    'redirect': redirect,
                    'reason': 'No actual URL change detected'
                })
                continue

            # Parse URLs for analysis
            try:
                old_parsed = urlparse(old_url)
                new_parsed = urlparse(new_url)
            except Exception as e:
                self.skipped.append({
                    'redirect': redirect,
                    'reason': f'URL parsing error: {e}'
                })
                continue

            # Check if homepage redirect
            is_homepage = (
                old_parsed.netloc == new_parsed.netloc and
                new_parsed.path in ['/', ''] and
                old_parsed.path not in ['/', '']
            )

            if is_homepage and self.args.skip_homepage:
                self.skipped.append({
                    'redirect': redirect,
                    'reason': 'Homepage redirect (use --no-skip-homepage to include)'
                })
                continue

            # Check if cross-domain redirect
            is_cross_domain = (old_parsed.netloc != new_parsed.netloc)

            if is_cross_domain and self.args.skip_cross_domain:
                self.skipped.append({
                    'redirect': redirect,
                    'reason': 'Cross-domain redirect (use --no-skip-cross-domain to include)'
                })
                continue

            # Check if protocol-only change (http→https)
            is_protocol_only = (
                old_parsed.netloc == new_parsed.netloc and
                old_parsed.path == new_parsed.path and
                old_parsed.query == new_parsed.query and
                old_parsed.fragment == new_parsed.fragment and
                old_parsed.scheme != new_parsed.scheme
            )

            if is_protocol_only and self.args.skip_protocol_only:
                self.skipped.append({
                    'redirect': redirect,
                    'reason': 'Protocol-only change (use --no-skip-protocol-only to include)'
                })
                continue

            # This redirect is fixable
            redirect_type = self._get_redirect_type(old_parsed, new_parsed, is_protocol_only)
            self.fixable.append({
                'redirect': redirect,
                'old_url': old_url,
                'new_url': new_url,
                'source_file': source_file,
                'type': redirect_type
            })

        # Group fixable redirects by source file
        for fix in self.fixable:
            source = fix['source_file']
            if source not in self.fixes_by_file:
                self.fixes_by_file[source] = []
            self.fixes_by_file[source].append(fix)

    def _get_redirect_type(self, old_parsed, new_parsed, is_protocol_only):
        """Determine the type of redirect"""
        if is_protocol_only:
            return f"Protocol upgrade ({old_parsed.scheme}→{new_parsed.scheme})"
        elif old_parsed.netloc != new_parsed.netloc:
            return "Cross-domain redirect"
        elif old_parsed.path != new_parsed.path:
            return "Path change"
        else:
            return "URL change"

    def print_preview(self):
        """Print what will be fixed (dry-run mode)"""
        print("\n" + "="*80)
        print("REDIRECT AUTO-FIX TOOL")
        print("="*80)
        print(f"Reading results from: {self.results_path}")
        print(f"Checking directory: {self.includes_dir}")

        if len(self.redirects) == 0:
            print("\n✅ No redirects found in results")
            return

        print(f"\nFound {len(self.redirects)} redirects in results")

        # Show filter settings
        filters = []
        if self.args.skip_homepage:
            filters.append("skip_homepage=True")
        if self.args.skip_cross_domain:
            filters.append("skip_cross_domain=True")
        if self.args.skip_protocol_only:
            filters.append("skip_protocol_only=True")

        if filters:
            print(f"Filtering with: {', '.join(filters)}")

        # Check minimum redirect count
        if len(self.fixable) < self.args.min_redirects:
            print(f"\n⚠️  Only {len(self.fixable)} fixable redirects found")
            print(f"   Minimum required: {self.args.min_redirects}")
            print(f"   Use --min-redirects 0 to fix anyway")
            return

        # Show fixable redirects
        if self.fixable:
            print(f"\n{'='*80}")
            print(f"WILL FIX {len(self.fixable)} REDIRECTS:")
            print("="*80)

            for i, fix in enumerate(self.fixable, 1):
                print(f"\n[{i}] {fix['source_file']}")
                print(f"    OLD: {fix['old_url']}")
                print(f"    NEW: {fix['new_url']}")
                print(f"    TYPE: {fix['type']}")

        # Show skipped redirects
        if self.skipped and self.args.verbose:
            print(f"\n{'='*80}")
            print(f"SKIPPED {len(self.skipped)} REDIRECTS:")
            print("="*80)

            for i, skip in enumerate(self.skipped, 1):
                redirect = skip['redirect']
                print(f"\n[{i}] {redirect['source']}")
                print(f"    URL: {redirect['url']}")
                print(f"    NEW: {redirect.get('final_url', 'N/A')}")
                print(f"    REASON: {skip['reason']}")

        # Summary
        print("\n" + "━"*80)
        if not self.args.apply:
            print("DRY RUN - No files will be modified")
            print("Run with --apply to execute fixes")
        print("━"*80)

    def create_backup(self):
        """Create timestamped backup of _includes directory"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_dir = self.includes_dir.parent / f"_includes_backup_{timestamp}"

        try:
            shutil.copytree(self.includes_dir, backup_dir)
            print(f"✓ Backup created: {backup_dir}")
            return backup_dir
        except Exception as e:
            print(f"❌ Error creating backup: {e}")
            return None

    def apply_fixes(self):
        """Apply the fixes to markdown files"""
        if len(self.fixable) < self.args.min_redirects:
            print(f"\n⚠️  Skipping fixes: Only {len(self.fixable)} redirects (minimum: {self.args.min_redirects})")
            return False

        if not self.fixable:
            print("\n✅ No redirects to fix")
            return False

        print("\n" + "="*80)
        print("🔧 APPLY MODE - Files will be modified")
        print("="*80)

        # Create backup
        if self.args.backup:
            backup_dir = self.create_backup()
            if not backup_dir:
                print("❌ Backup failed - aborting fixes for safety")
                return False
            print()

        # Apply fixes file by file
        fixed_count = 0
        files_modified = 0

        print(f"Fixing {len(self.fixable)} redirects...\n")

        for source_file, fixes in self.fixes_by_file.items():
            file_path = self.includes_dir / source_file

            if not file_path.exists():
                print(f"⚠️  {source_file} - File not found, skipping")
                continue

            # Read file
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except Exception as e:
                print(f"❌ {source_file} - Error reading: {e}")
                continue

            # Apply fixes
            original_content = content
            fixes_applied = 0

            for fix in fixes:
                old_url = fix['old_url']
                new_url = fix['new_url']

                # Replace URL in href attribute
                # Pattern: href="old_url"
                pattern = re.escape(f'href="{old_url}"')
                replacement = f'href="{new_url}"'

                new_content = re.sub(pattern, replacement, content)

                if new_content != content:
                    content = new_content
                    fixes_applied += 1

            # Write back if changes were made
            if content != original_content:
                try:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    print(f"✓ {source_file} - Updated {fixes_applied} link(s)")
                    files_modified += 1
                    fixed_count += fixes_applied
                except Exception as e:
                    print(f"❌ {source_file} - Error writing: {e}")
            else:
                print(f"⚠️  {source_file} - No matches found (might already be fixed)")

        # Summary
        print("\n" + "━"*80)
        print(f"COMPLETE - {fixed_count} redirects fixed in {files_modified} file(s)")
        if self.args.backup:
            print(f"Backup saved to: {backup_dir}")

        print("\nNext steps:")
        print("1. Review changes: git diff")
        print("2. Test site locally")
        print("3. Commit: git add . && git commit -m 'Fix redirected URLs'")
        print("━"*80)

        return True

    def run(self):
        """Main execution flow"""
        # Load results
        if not self.load_results():
            return 1

        # Filter redirects
        self.filter_redirects()

        # Show preview
        self.print_preview()

        # Apply fixes if requested
        if self.args.apply:
            if not self.apply_fixes():
                return 0  # No error, just nothing to fix

        return 0


def main():
    parser = argparse.ArgumentParser(
        description='Auto-fix redirected URLs in markdown files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Preview what would be fixed
  python3 scripts/fix_redirects.py

  # Apply fixes with default settings
  python3 scripts/fix_redirects.py --apply

  # Skip homepage redirects and protocol-only changes
  python3 scripts/fix_redirects.py --apply --skip-homepage --skip-protocol-only

  # Apply all redirects including cross-domain
  python3 scripts/fix_redirects.py --apply --no-skip-cross-domain

  # Verbose output
  python3 scripts/fix_redirects.py --apply -v
        """
    )

    parser.add_argument(
        '--apply',
        action='store_true',
        help='Actually modify files (default is dry-run preview)'
    )

    parser.add_argument(
        '--skip-homepage',
        dest='skip_homepage',
        action='store_true',
        default=True,
        help='Skip redirects to homepage (default: True)'
    )

    parser.add_argument(
        '--no-skip-homepage',
        dest='skip_homepage',
        action='store_false',
        help='Include redirects to homepage'
    )

    parser.add_argument(
        '--skip-protocol-only',
        dest='skip_protocol_only',
        action='store_true',
        default=False,
        help='Skip http→https only changes (default: False)'
    )

    parser.add_argument(
        '--no-skip-protocol-only',
        dest='skip_protocol_only',
        action='store_false',
        help='Include http→https changes'
    )

    parser.add_argument(
        '--skip-cross-domain',
        dest='skip_cross_domain',
        action='store_true',
        default=True,
        help='Skip redirects to different domain (default: True)'
    )

    parser.add_argument(
        '--no-skip-cross-domain',
        dest='skip_cross_domain',
        action='store_false',
        help='Include cross-domain redirects'
    )

    parser.add_argument(
        '--backup',
        dest='backup',
        action='store_true',
        default=True,
        help='Create backup before modifying (default: True)'
    )

    parser.add_argument(
        '--no-backup',
        dest='backup',
        action='store_false',
        help='Skip backup (NOT recommended)'
    )

    parser.add_argument(
        '--results',
        default='scripts/link_check_results.json',
        help='Path to link check results JSON (default: scripts/link_check_results.json)'
    )

    parser.add_argument(
        '--includes-dir',
        default='_includes',
        help='Directory containing markdown files (default: _includes)'
    )

    parser.add_argument(
        '--min-redirects',
        type=int,
        default=1,
        help='Minimum number of redirects required to apply fixes (default: 1)'
    )

    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Verbose output (show skipped redirects)'
    )

    args = parser.parse_args()

    # Adjust paths relative to script location
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent

    # Make paths absolute
    if not Path(args.results).is_absolute():
        args.results = repo_root / args.results
    if not Path(args.includes_dir).is_absolute():
        args.includes_dir = repo_root / args.includes_dir

    # Run fixer
    fixer = RedirectFixer(args)
    return fixer.run()


if __name__ == '__main__':
    exit(main())
