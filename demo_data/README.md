# Demo roster workbooks (fictional data)

Excel ফাইল না থাকলে demo/test-এর জন্য এই ৫টা workbook ব্যবহার করুন।

| File | Employees | What it tests |
|---|---|---|
| `demo_roster_01_standard.xlsx` | 200 | Baseline. কোনো shortage নেই, night fairness spread ছোট |
| `demo_roster_02_night_shortage.xlsx` | 200 | মাত্র 15 জন night-eligible, তাই Night shortage report |
| `demo_roster_03_senior_tight.xlsx` | 200 | মাত্র 9 জন Senior Support, তাই Senior coverage shortage |
| `demo_roster_04_leave_heavy.xlsx` | 200 | 45টা leave (Sick/Casual/Annual, half-day, Pending/Approved) |
| `demo_roster_05_new_joiners.xlsx` | 215 | 15 new joiner (কেউ কেউ roster চলাকালীন join) + 6 inactive |

Sheets: `README`, `Employee_Master`, `Daily_Requirement`, `Leave_Applications`, `Roster_Draft`,
`Coverage_Report`, `Fairness_Summary`. Roster window: 2026-10-26 থেকে 14 দিন।
Targets: Morning 55, Evening 45, **Night 14**, প্রতি shift-এ minimum 3 Senior।

`Roster_Draft` একটা সাধারণ greedy demo, **OR-Tools engine নয়**। এটা পরের ধাপে engine-এর output
যাচাই করার reference/input হিসেবে রাখা।

## Import

```bash
cd backend
python -m app.scripts.import_employees ../demo_data/demo_roster_01_standard.xlsx
```

## Regenerate (fixed seed, সবসময় একই data)

```bash
cd backend
python -m app.scripts.generate_demo_data
```

## Tests

```bash
cd backend
pip install -r requirements.txt
pytest -q        # PostgreSQL লাগে না, in-memory SQLite ব্যবহার করে
```
