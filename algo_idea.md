## Algorithm Design

Each slot from the API is 30 minutes. A `SESSION_LENGTH_HOURS=2` session = **4 consecutive 30-min blocks**.

### Step 1 - Filter slots by time window
Keep only slots where `start >= window_start` AND `start + 30min <= window_end`.

### Step 2 - Index slots
Build a `dict[(court, start_time)] -> bool` for O(1) lookups.

### Step 3 - DFS to enumerate all valid chains
For each possible `chain_start` in `[window_start, window_end - session_length]` (stepping by 30 min):
- Times in chain: `T0, T0+30m, T0+60m, ..., T0+(N-1)*30m`
- At each time step, collect available courts
- DFS through all combinations of court choices at each time step
- Each complete path (length N) = one candidate suggestion

This avoids the full cartesian product by pruning early when no court is available at a time step.

### Step 4 - Deduplicate
Each chain is a `tuple[tuple[int, datetime], ...]` - `(court, time)` per block. Store in a `set` of tuples to guarantee no duplicates.

### Step 5 - One suggestion per (start time, first-block court)
Group all valid chains by `(T0, first_court)`. For each group, keep only the **single highest-priority chain**:

Priority within a group:
1. Single-court chain (full session on one court) - always beats any multi-court chain
2. Among multi-court chains: lowest adjacency score wins (`sum(|court[i+1] - court[i]|)`, lower = more adjacent)
3. Tie-break: lowest court numbers

Examples:
- Court 1 available 12:00–14:00 (full session): kept as-is. Multi-court chains starting with Court 1 at 12:00 all dropped.
- Court 1 only available 12:00–13:00 (partial): two multi-court chains exist - `Court1+Court2` (score 1) and `Court1+Court3` (score 2). Only `Court1+Court2` is kept.
- Court 2 available 12:00–14:00 AND Court 1 also 12:00–14:00: both kept independently as separate single-court suggestions (different first-block courts).

### Step 6 - Sort and display

Priority order:
1. Single-court chains first
2. Multi-court chains sorted by adjacency score = `sum(|court[i+1] - court[i]|)` (lower = more adjacent)
3. Then by start time

### Output format (per date)

```
Date: 11/04/2026
  Court 1: 12:00–14:00
  Court 2 (12:00–13:00) + Court 3 (13:00–14:00)
  ...
```