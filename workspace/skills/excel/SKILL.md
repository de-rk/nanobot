---
name: excel
description: Read, search, and remember Excel file contents. Summarizes sheets, headers, rows, and key data so you can answer questions about any Excel file the user shares.
---

# Excel Skill

## When to Use

Use this skill when the user:
- Asks to "load", "read", "analyze", or "remember" an Excel file (`.xlsx`, `.xls`)
- Shares a file path or attaches an Excel file and asks about its contents
- Asks questions about data that may be in a previously loaded Excel file
- Says "search this Excel" or "find in the spreadsheet"

## Core Principle

You do NOT need to remember every cell value — you need to remember the **structure** and **key data** well enough to answer questions accurately. After reading a file, store a summary in memory so you can answer follow-up questions without re-reading the file.

---

## Step 1: Read the Excel File

Use the `exec` tool to run Python:

```bash
python3 - <<'EOF'
import openpyxl, json, sys
path = sys.argv[1]
wb = openpyxl.load_workbook(path, data_only=True)

for name in wb.sheetnames:
    ws = wb[name]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        continue
    headers = rows[0] if rows else []
    data_rows = rows[1:] if len(rows) > 1 else []
    print(f"=== Sheet: {name} ===")
    print(f"Dimensions: {ws.dimensions}")
    print(f"Headers: {headers}")
    print(f"Total data rows: {len(data_rows)}")
    # Print all rows for small sheets; first 50 for large ones
    for i, row in enumerate(data_rows[:50]):
        print(json.dumps(row))
    if len(data_rows) > 50:
        print(f"... ({len(data_rows) - 50} more rows)")
EOF
"/path/to/file.xlsx"
```

> Always pass `data_only=True` to openpyxl — it evaluates formulas instead of returning the formula text.

---

## Step 2: Summarize and Store in Memory

After reading, extract and write a summary to `memory/MEMORY.md` (or `memory/excel/<name>.md` for large files).

**Summary template** — write something like this to `memory/MEMORY.md`:

```markdown
## Excel: <filename>

**Path:** /path/to/file.xlsx
**Sheets:** <list of sheet names>
**Last loaded:** <date>

### Sheet: <sheet-name>
- **Headers:** <comma-separated header names>
- **Data rows:** <count>
- **Key columns:** <brief description of important columns>

#### Sample data (first 5 rows)
| col1 | col2 | col3 |
|------|------|------|
| val1 | val2 | val3 |
...
```

Use the `write_file` tool:

```
write_file
path: <workspace>/memory/MEMORY.md  (append section, don't overwrite existing content)
content: <summary above>
```

For multi-sheet or large files, use `memory/excel/<filename>.md` instead (one file per workbook).

---

## Step 3: Answer User Questions

When the user asks a question about the Excel file:

1. **If the summary is in memory:** Answer directly from it. Use grep to verify details.
2. **If the summary is NOT in memory:** Read the file again (Step 1), then store the summary (Step 2).
3. **For specific data lookups:** Re-read the file or grep the output from Step 1.

### Example Q&A

| Question | Approach |
|----------|----------|
| "What columns does the file have?" | Answer from memory summary |
| "How many rows in the Sales sheet?" | Answer from memory summary |
| "What is the value in row 42?" | Re-read file or grep output |
| "Find all rows where column A = X" | Run Python grep on the file |
| "Sum column B" | Run Python aggregation |

### Quick search without full re-read

```bash
python3 - <<'EOF'
import openpyxl, sys
path, sheet, keyword = sys.argv[1], sys.argv[2], sys.argv[3].lower()
wb = openpyxl.load_workbook(path, data_only=True)
ws = wb[sheet]
for row in ws.iter_rows(values_only=True):
    if any(keyword in str(c).lower() for c in row if c):
        print(row)
EOF
"/path.xlsx" "Sheet1" "search-term"
```

---

## Supported File Formats

| Format | Library | Notes |
|--------|---------|-------|
| `.xlsx` | `openpyxl` | Primary; installed by default |
| `.xls` | `xlrd` (pip install) | Legacy Excel 97-2003 |
| `.csv` | Built-in `csv` module | Use `exec` with Python's csv module |

---

## Memory Strategy

- **Small files (< 100 rows):** Full summary in `memory/MEMORY.md`
- **Large files:** Summary in `memory/excel/<filename-safe>.md`, link from `memory/MEMORY.md`
- **Update on reload:** If user asks to reload the same file, refresh both the memory and answer
- **Sheet-specific memory:** Store per-sheet summaries to make it easy to answer "what's in sheet X?"

---

## Common Traps

- **Merged cells:** Use `data_only=True` and iterate with `iter_rows` to avoid reading merged cell artifacts
- **Dates:** openpyxl returns datetime objects — convert with `str(c)` before printing
- **Empty cells:** Check `if c is not None` before including in grep results
- **Large files:** Never print every row — always show first N + total count
- **Missing headers:** If the first row doesn't look like headers, treat row 1 as data and note it