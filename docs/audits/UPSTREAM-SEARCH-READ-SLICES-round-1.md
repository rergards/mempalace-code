slug: UPSTREAM-SEARCH-READ-SLICES
round: 1
date: 2026-05-23
commit_range: 70e5f9f..HEAD
findings:
  - id: F-1
    title: "Chunk text mismatch: chunker inserts \\n\\n between merged blocks, breaking str.find"
    severity: high
    location: "mempalace_code/mining/orchestrator.py:196"
    claim: >
      The mining orchestrator used str.find(chunk_text, cursor) to locate each chunk in the
      stripped source content. However, the adaptive_merge_split chunker joins multiple blocks
      with \\n\\n (double newline) when merging them, even when the original source uses single
      \\n between definitions. As a result, content.find returns -1 for any merged multi-block
      chunk, silently setting line_start=0 and line_end=0. In practice, any Python file without
      PEP 8 blank lines between functions (or any language where the chunker merges blocks)
      produces chunks with null line ranges, defeating AC-1 and AC-2 for the majority of
      real-world files processed by the miner.
    decision: fixed
    fix: >
      Added _find_chunk_in_content(content, chunk_text, cursor) that splits chunk_text on \\n+
      runs, re.escapes each part, and joins with \\n+ to form a regex that matches any number of
      consecutive newlines. This correctly finds merged chunks in content regardless of whether
      the original source uses single or double newlines between blocks. Updated
      _collect_specs_for_file to use the new helper and advance _cursor to pos_end.

  - id: F-2
    title: "Repeated-chunk test assertion allows duplicate start lines, masking the F-1 regression"
    severity: medium
    location: "tests/test_miner.py:4742"
    claim: >
      test_line_range_metadata_repeated_chunk_text checked cur_start >= prev_start
      (non-decreasing), which allows equal start lines. Before the F-1 fix, both chunks had
      line_start=0, the with_ranges list was empty, and the assertion loop never ran, so the
      test passed trivially without detecting the cursor-match failure.
    decision: fixed
    fix: >
      Strengthened assertions: (1) added assert len(with_ranges) == len(metas) to verify all
      chunks have positive line_start values; (2) changed the ordering check to
      cur_start > prev_start (strictly increasing) to catch duplicate starts from a failed
      cursor mechanism.

  - id: F-3
    title: "wing filter path in read_slice has no test coverage"
    severity: medium
    location: "mempalace_code/reader.py:63"
    claim: >
      When wing is provided to read_slice, the where dict switches from the simple
      {"source_file": sf} form to {"$and": [{"source_file": sf}, {"wing": w}]}. No test in
      test_reader.py or test_mcp_server.py exercised this conditional branch. A broken $and
      filter would silently return chunks from all wings instead of the requested one.
    decision: fixed
    fix: >
      Added test_wing_filter_restricts_to_matching_wing to tests/test_reader.py. Seeds a chunk
      under wing="proj_a", then verifies: (a) read_slice with wing="proj_a" returns the lines,
      and (b) read_slice with wing="proj_b" returns not_found.

totals:
  fixed: 3
  backlogged: 0
  dismissed: 0

fixes_applied:
  - "Added _find_chunk_in_content with flexible newline matching to fix line range computation for merged multi-block chunks"
  - "Strengthened test_line_range_metadata_repeated_chunk_text to assert all chunks have positive line_start and distinct start lines"
  - "Added test_wing_filter_restricts_to_matching_wing to cover the $and where-filter branch in read_slice"

new_backlog: []
