slug: MINE-PHP
round: 1
date: 2026-04-20
commit_range: baaa671..976cc04
findings:
  - id: F-1
    title: "vendor/ directory not in SKIP_DIRS — Composer dependencies would be mined"
    severity: high
    location: "mempalace/miner.py:146"
    claim: >
      PHP projects managed by Composer always have a vendor/ directory containing
      third-party dependencies (e.g. laravel/framework, symfony/http-kernel). Because
      "vendor" was absent from SKIP_DIRS, mining any PHP project would silently index
      thousands of library files. This bloats the palace with irrelevant third-party
      code, pollutes search results, and wastes embed time.
    decision: fixed
    fix: >
      Added "vendor" to the SKIP_DIRS set in miner.py. Added
      test_skip_dirs_vendor_php() in test_miner.py to assert that vendor/laravel/.../*.php
      files are excluded while src/App.php is included.

  - id: F-2
    title: "Redundant #[ entry in PHP comment_prefixes lookback"
    severity: info
    location: "mempalace/miner.py:1735"
    claim: >
      The PHP-specific branch adds "#[" to comment_prefixes so that PHP 8 attribute
      lines like #[Route('/api')] attach to their declaration chunk. However, "#" is
      already in the default comment_prefixes tuple, and startswith() matches the
      prefix — so #[...] lines are already captured by the "#" entry. The "#["
      addition is redundant but harmless.
    decision: dismissed

  - id: F-3
    title: "Extraction regexes accept abstract/final/readonly on interface/trait/enum"
    severity: low
    location: "mempalace/miner.py:1222"
    claim: >
      The _PHP_EXTRACT patterns for interface, trait, and enum share the prefix
      (?:(?:abstract|final|readonly)\s+)* from the class pattern. In PHP, interface
      cannot be abstract/final/readonly, trait cannot be final/readonly, and enum
      cannot have these modifiers. The over-permissive prefix causes no false negatives
      on real PHP code (no valid PHP uses these combinations), but a future typo-fix
      could silently match invalid PHP that a strict parser would reject.
    decision: dismissed

totals:
  fixed: 1
  backlogged: 0
  dismissed: 2

fixes_applied:
  - "Added 'vendor' to SKIP_DIRS in miner.py to prevent Composer dependencies from being mined"
  - "Added test_skip_dirs_vendor_php() in test_miner.py to regression-test the fix"

new_backlog: []
