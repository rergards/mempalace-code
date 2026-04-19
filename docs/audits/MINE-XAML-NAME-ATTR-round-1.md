slug: MINE-XAML-NAME-ATTR
round: 1
date: 2026-04-19
commit_range: d4e87df..HEAD
findings:
  - id: F-1
    title: "Name= on non-FrameworkElement types could theoretically produce false-positive triples"
    severity: info
    location: "mempalace/miner.py:2577"
    claim: >
      The implementation calls elem.get("Name", "") on every XAML element, including
      non-FrameworkElement types (e.g. SolidColorBrush, Storyboard, Timeline). In valid
      WPF XAML the CLR Name property only exists on FrameworkElement/FrameworkContentElement,
      so a Name= attribute on a non-FrameworkElement would be a compile error and will not
      appear in real-world files. No false positives occur in practice.
    decision: dismissed

  - id: F-2
    title: "Differing x:Name and Name values on the same element emit two triples"
    severity: info
    location: "mempalace/miner.py:2573-2581"
    claim: >
      If an element has x:Name="foo" and Name="bar" (different values), both are added to
      the set and both triples are emitted. This is undefined/invalid in WPF — the XAML
      compiler rejects it at build time — so it cannot occur in a compilable project. The
      plan explicitly marks this scenario out-of-scope. Set-based dedup already handles the
      only real-world case (same value on both attributes).
    decision: dismissed

totals:
  fixed: 0
  backlogged: 0
  dismissed: 2
fixes_applied: []
new_backlog: []
