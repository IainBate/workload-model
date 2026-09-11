# Google Sheets sync-check — design

## Motivation

Several `data/*.csv`/`*.xlsx` inputs to this pipeline are hand-maintained copies of
Google Sheets the department actually edits live. Those copies drift: this session
alone found a renamed-column bug that silently zeroed every research grant hours
figure (`% FTE for CS.csv`), a stale committee membership (`WAW.csv`), and 22
rounded-vs-precise grant percentages. There's no way to know a local file is stale
short of manually fetching and diffing each sheet, which is what this session did
by hand, repeatedly, for about a dozen files.

This adds a standalone, on-demand tool that does that fetch-and-diff mechanically,
across every known source, and asks before writing anything.

## Non-goals

- **No live fetch at calculation time.** `main.py` stays fully offline and
  reproducible from what's checked into git. Syncing is a deliberate, separate
  step you run when you want to check for upstream changes — not a dependency of
  every calculation run.
- **No OAuth.** Every source here is a Google Sheet shared "anyone with the link
  can view" — read via its CSV export URL (`.../export?format=csv[&gid=N]`), a
  plain unauthenticated HTTP GET. A sheet that can't be made link-shared is out of
  scope for automatic sync (see "Inaccessible sources" below).
- **No general-purpose diff/merge UI.** Per-file comparison strategy is simple and
  hardcoded per source (exact match, or a numeric-tolerance variant for exactly
  one known file) — not a configurable rules engine.

## Source mapping — `data/google_sheets_sources.json`

A hand-editable JSON file, one entry per local file:

```json
{
  "WAW.csv": {
    "url": "https://docs.google.com/spreadsheets/d/1mMEwW5UUkOguRDdtDNjA-1yRigPO3633F7YQf3C0o4s",
    "gid": "991769073",
    "supplementary_file": "WAW_supplementary.csv"
  },
  "% FTE for CS.csv": {
    "url": "https://docs.google.com/spreadsheets/d/1LoF95Hy0J1aHYiy4bC_1FstG1MwnzDZQnxg3rw7jW6Q",
    "compare": "fte_tolerant"
  },
  "CS Module Numbers.csv": {
    "url": "https://docs.google.com/spreadsheets/d/1WaS8snhkSZiIlCqYtWlD3iwk5GuefNj0GnKzJXiWhY8"
  },
  "PhD Supervision Data.csv": {
    "url": "https://docs.google.com/spreadsheets/d/1DrPBAn-LKFxXzetkoEahzo2hLcMRRkT1gduLoWQ252Y"
  },
  "workload_adjustments.csv": {
    "url": "https://docs.google.com/spreadsheets/d/1A9QYHbOArZc8l05gUt8Rs8TNwuZ-a5v5D000z2MvTlo"
  },
  "CS Research Groups.csv": {
    "url": "https://docs.google.com/spreadsheets/d/1Akv7KO91jLj5JlRmB8vSlRwWHF1cuLH9XeQPrAhLC4M"
  },
  "CS Module Assessment Numbers.csv": {
    "url": "https://docs.google.com/spreadsheets/d/1Nb_og04ZA1egQhia2uoekvuWX1BdpjKLvG-EohJkni0",
    "accessible": false
  },
  "CS WTW Who Teaches What.xlsx": {
    "url": "https://docs.google.com/spreadsheets/d/1QlWKgsuH_x6qI5tdmpcsf7_y2R0QbAtbBwZNAYvxLVw",
    "tabs": {}
  },
  "ProjectLoads 2025-26.xlsx": {
    "url": "https://docs.google.com/spreadsheets/d/1J2XRbGXz3JFAUPel3jeGS0JRAmNOo2yx",
    "tabs": { "Advisor Loads": null }
  }
}
```

Fields:
- `url` (required): the sheet's `/d/<id>` URL (the script strips any `/edit...`
  suffix and builds the export URL itself).
- `gid` (optional): specific tab, for a single-comparison-target source.
- `tabs` (optional, for multi-tab workbooks compared tab-by-tab): `{tab_name:
  gid}`. A `null` gid means "not yet configured — skip with a note." Gids aren't
  discoverable by this script (Google's tab-name-to-gid association isn't exposed
  in the public CSV/HTML export in a reliably parseable way — confirmed this
  session). You get a tab's gid by opening it in your browser and copying the
  number after `gid=` in the URL; paste it in here once.
- `compare` (optional): comparison strategy name; defaults to exact match.
  Only `"fte_tolerant"` exists initially (see below).
- `supplementary_file` (optional): a second local file whose rows are appended
  after the sheet's content when propagating (see WAW.csv below).
- `accessible` (optional, default true): set to `false` for a source known to be
  unreachable (wrong sharing settings) — the script always reports these as
  skipped rather than retrying and failing noisily.

`CS WTW Who Teaches What.xlsx`'s `tabs` starts empty — you'll need to add the two
most-recent year tabs (e.g. `"2026-7": null, "2025-6": null`) and their gids
yourself for that source to be checked; until then it's skipped with a note,
same as any other tab with a `null` gid.

## Comparison strategies

- **Exact** (default): fetched CSV bytes vs. local file bytes, after normalizing
  line endings. Any difference is reported.
- **`fte_tolerant`** (`% FTE for CS.csv` only): row-matched by `(Project ID,
  Staff)`, comparing the `% FTE` field with a tolerance (default 1.0 — i.e.
  differences under 1 percentage point, matching the rounding noise already
  observed, are ignored). Any other column differing, or a row present in one
  side only, is still reported as exact-match would.

Both strategies report **new rows, removed rows, and changed rows** distinctly,
not just "files differ" — this session's manual diffs already established this is
what's actually useful to read.

## Per-source flow

For each `accessible: true` source, in the order given in the JSON file:

1. Fetch the export CSV (or each configured tab, for a `tabs` source). A fetch
   failure (network error, unexpected HTML instead of CSV — the signature of a
   sharing permission problem) is reported as `"could not fetch: <reason>"` and
   that source is skipped, not treated as "no differences."
2. Compare against the local file using its configured strategy.
3. No differences → print `"<file>: up to date"`, move on.
4. Differences → print a summary (added/removed/changed rows, capped at showing
   the first ~20 with a count of the rest) and prompt:
   `Propagate these changes to data/<file>? [y/N]`
   - **Exact-match sources**: `y` overwrites the local file with the fetched
     content verbatim.
   - **WAW.csv**: `y` writes fetched content + the contents of
     `WAW_supplementary.csv` appended (see below) — never a bare overwrite.
   - Default is **No** on empty input — a sync run changes nothing unless you
     explicitly confirm each file.

## WAW.csv: supplementary rows + parser fixes

Two independent problems, both real, neither blocking the other:

**1. Content that's only ever been in the local file, never the sheet** (e.g. the
Union role). `data/WAW_supplementary.csv` holds exactly these rows, same
column shape as `WAW.csv`. Propagating a WAW.csv sync means: write
`<fetched sheet content>` + `<WAW_supplementary.csv content>` to `data/WAW.csv`.
This file starts with just the Union row (`Union,Chris Crispin-Bailey,,,`) since
that's the one case found this session; add rows to it by hand as more come up,
same "flag the exception" spirit as `Staff Categories and FTE.csv`.

**2. `_load_waw_roles()` in `scripts/data_loader.py` doesn't handle a blank role
cell as "same role as the row above."** The sheet author has been filling role
name into column A once per block and leaving it blank on subsequent rows (this
is what a merged cell looks like once Sheets exports it to CSV) — a standard
spreadsheet convention this parser has never needed to handle before because
every existing block repeats the role text on every row. Fix: track the last
non-blank role seen; a blank role inherits it; a fully blank row (role **and**
person both empty) resets the carry-forward to `None`, so a stray blank
separator line between two unrelated blocks can't leak a role across them.
Also add `_WAW_ROLE_MAPPING` entries for the sheet's current wording:
`"Research Group Leads": "Research Group Leader"` and
`"Research Grant Mentors": "Research Mentor"`.

**Known remaining gap, not fixed by the above:** the "Research Group Leads"
block currently has the *group name* in column B and the *person* in column D,
while every other role in the file (including the sibling "Research Grant
Mentors" block) has the person in column B. This parser doesn't guess which
column holds a person vs. other data — that's exactly the kind of heuristic that
breaks quietly on the next sheet edit. Once the carry-forward and mapping fixes
above land, "Research Grant Mentors" will parse correctly immediately; "Research
Group Leads" still needs its column B changed to the person's name (group name
can move to any later column, or be dropped) before it will.

## Coverage check

After processing every mapped source, list any file directly under `data/`
that: (a) is a data file (`.csv` or `.xlsx`, not `.json`), and (b) has no entry
in `google_sheets_sources.json`. For each, prompt:
`No Google Sheet registered for data/<file> — paste a share link now, or press Enter to skip:`
A pasted URL is added to `google_sheets_sources.json` (exact-match comparison,
no gid/tabs) immediately, so the very next run picks it up. This runs even if
every mapped source above was already up to date.

## Inaccessible sources

`CS Module Assessment Numbers.csv` → `1Nb_og04ZA1egQhia2uoekvuWX1BdpjKLvG-EohJkni0`
returns HTTP 401 (not link-shared) and this can't be changed. Recorded in the
mapping with `"accessible": false` so the script always prints
`"<file>: not accessible (sharing) - flip to 'anyone with link can view' to enable, or update the CSV by hand as before"`
rather than silently omitting it or erroring. If sharing is ever fixed, flipping
`accessible` to `true` (or removing the field, since it defaults to `true`)
re-enables it with no other change needed.

## CLI shape

```
$ python sync_sheets.py

WAW.csv: 1 difference (1 changed row)
  Ethics Committee members: Yan Jia -> Mark Sujan
Propagate these changes to data/WAW.csv? [y/N] y
  Fetched sheet + WAW_supplementary.csv (1 row) written to data/WAW.csv

CS WTW Who Teaches What.xlsx: skipped - tabs not configured (edit google_sheets_sources.json)

% FTE for CS.csv: up to date

CS Module Assessment Numbers.csv: not accessible (sharing)

...

No Google Sheet registered for data/pastoral_load.csv - paste a share link now, or press Enter to skip:
```

## Testing

- Pure functions (no network): the exact-match and `fte_tolerant` comparison
  strategies, the WAW.csv carry-forward role parsing, the supplementary-file
  merge logic — all unit-testable against small in-memory/tmp_path fixtures, no
  different in spirit from this repo's existing loader tests.
- The fetch step itself is not unit-tested against the live network (flaky,
  slow, and not this repo's existing testing style) — it's a thin function
  (`GET` the export URL, raise on non-CSV response) exercised manually.
- `_load_waw_roles()`'s carry-forward + new mapping entries get the same kind of
  tests as its existing behavior in `test_data_loader.py`.

## Out of scope for this pass

- Automating gid discovery for multi-tab sources — confirmed this session that
  scraping it reliably isn't practical without an API key; left as a one-time
  manual step per tab.
- A `--yes`/non-interactive mode. Every propagate decision is a manual y/N this
  round; can be added later if the coverage list grows large enough that batch
  confirmation becomes worth it.
