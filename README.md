# Bullet Timetable Fetcher

One fetch from Bullet's API for every tool that needs the timetable. A GitHub task reads Bullet
(the API can't be called from a browser), saves a clean copy of **one semester per file**, and
GitHub Pages publishes them. Each tool then loads the semester in use with **Get timetable from
Bullet**, and keeps the Bullet CSV upload as a fallback.

Published files (`https://catolica-lisbon-sbe.github.io/bullet-timetable/data/…`):
- `index.json`: the list of saved semesters (file, semester, academic year, Units, first and last
  date, number of classes, fetch time, number of classes left out for a wrong Unit).
- `timetable-2026-27-S1.json`, `timetable-2026-27-S2.json`, …: one per semester and academic year.
  Saving one semester never replaces another.
- `timetable.json`: a copy of the last save, for older copies of the tools.

Tools pick the semester in progress, or the next one; if all have ended, the most recent.

Used by:
- **Make-up Classes** (Aulas de Reposição).
- **Room Allocation Check** (since 25/11/2026; its own fetch was removed). It checks the
  undergraduate and Master classes. Make-up classes and `busy` are not checked there, but their
  rooms are never suggested as free.

Student Schedule Sandbox can move to it later and drop its own copy of the fetch.

## What the file contains

```json
{
  "source": "Bullet API · Semester 1 2026/27",
  "fetchedAt": "2026-11-18T10:32:00Z",
  "semester": 1,
  "academicYear": "2026/2027",
  "units": ["S1", "T1", "T2"],
  "firstDate": "2026-08-31",
  "lastDate": "2026-12-20",
  "unexpectedUnits": {},
  "professors": "coded (new codes on every fetch)",
  "columns": ["ModuleName", "ModuleAcronym", "ModuleCode", "SectionName", "Typology", "StudentGroup",
              "Unit", "Classroom", "WeekdayName", "StartTime", "EndTime", "Week", "EventType", "Professor"],
  "rows": [["Finance I", "Finance I", "L15.2028", "T1", "T", "Y2_LIC_GEST", "S1", "Classroom 514",
            "Tuesday", "09:30", "11:00", "2026-09-14,2026-09-21,…", "Aula Licenciatura", "P-7K3QM"], …],
  "busy": {"columns": ["Classroom", "Date", "StartTime", "EndTime"],
           "rows": [["Auditorium 511", "2026-10-15", "09:00", "17:00"], …]}
}
```

- Same column names as Bullet's *Export Events* CSV, so tools read it like an export.
- `Week`: the Mondays of the weeks the class runs.
- Undergraduate (*Aula Licenciatura*) and Master (*Aula Mestrado*) classes of one semester. The event
  type must match exactly: *Aula Mestrado Executivo* (Executive Masters) only blocks the room.
- **Units**: semester 1 keeps S1, T1, T2; semester 2 keeps S2, T3, T4. Classes of the other
  semester are skipped quietly (the date windows overlap in January–February). Any other Unit
  (empty, "T 3"…) is a mistake in Bullet: those classes are left out, counted in
  `unexpectedUnits`, and listed by course, shift and time under a ⚠ heading in the run's summary.
  The tools show the same warning. Fix the Unit in Bullet and save again.
- **No course**: entries typed as *Aula Licenciatura* / *Aula Mestrado* but with no course in
  Bullet (postgraduate programmes such as PGGL or MGA, exams, thesis defences, room bookings…) are
  not used and raise no alert. The summary lists them, undergraduate ones first, so they can be
  linked to their course or given the right event type in Bullet.
- **Make-up classes**: events of type *Make-up class*, or whose title starts with
  "Make-up Class:", are kept as classes on their date, so the tools count their students as busy.
  The course comes from the Module field or, if it is empty, from the title
  ("Make-up Class: Impact Investing", optionally followed by the shift, e.g. "TP1"). With a shift,
  only that shift's students are counted; with no shift, all students of the course. A missing Unit
  takes the course's Unit. Titles are only matched to a course name or code, never saved or
  printed. Make-up classes whose course is not found are listed in the summary (room and time
  only) and still block the room.
- **Several rooms** in one event ("Auditorium 511,Classroom 513") are all counted as busy.
- **Other room bookings** (`busy`): every other Bullet event in the semester's dates that has a
  room (room reservations, Executive Education, MBA, exams, events, classes with no course, a wrong
  Unit or of the other semester) as room, date, start and end only. The tools count those rooms as
  busy, so a make-up class is not proposed in a room that is already booked.

## Privacy

The repository and the file are public, so:
- **Professors are codes** (e.g. `P-7K3QM`), never names. Each code is an HMAC of the name with a
  random key made for that run only and never saved: codes can't be turned back into names, and
  they change on every fetch. Within one file the same person always has the same code, which is
  enough to check whether a professor is free.
- No student data, no staff e-mails or usernames, no free-text annotations.
- Other room bookings carry no title, event type or people: only room, date and times.
- The run's summary on GitHub shows counts and field names only.
- Coded data still counts as personal data under the GDPR (pseudonymised): anyone who knows who
  teaches a class can recognise that person's code. Confirm with data protection before going live.

## Setup (once)

1. On GitHub, create the repository **`bullet-timetable`** in the `catolica-lisbon-sbe`
   organization and push this folder to it.
2. Add the secrets **`BULLET_CLIENT_ID`** and **`BULLET_CLIENT_SECRET`** (the same read-only
   Bullet client as the other tools): *Settings › Secrets and variables › Actions › New repository
   secret*. (Organization secrets would let several repositories share them, but need an
   organization admin.)
3. Turn on GitHub Pages: *Settings › Pages › Deploy from a branch › main / (root)*.

Done on 18/11/2026: repository created and pushed by the **RitaQuintela** account (the one used for
the other tools), repository secrets added, Pages on, first `save` run published 838 classes of
Semester 1 2026/27.

## Fetching

**Every day at 04:00 UTC** (04:00 in Lisbon in winter, 05:00 in summer; GitHub may start it a
little late) the task runs by itself and saves **both semesters** of the current academic year
(the year switches on 1 May, so from May to July it already prepares the next year). A semester
not yet in Bullet is skipped without an error. The run ends with ❌, and GitHub e-mails the account
that set the schedule (RitaQuintela), when Bullet can't be read or when some classes have a wrong
Unit; in the second case the timetable is still saved and the summary lists the classes to fix.
Each run makes a commit (professor codes change on every fetch), which also keeps the schedule
active: GitHub turns off schedules in repositories with no activity for 60 days.

By hand, for an update straight away: *Actions › Fetch timetable from Bullet › Run workflow*:
- **semester** 1 or 2, **academic year** (empty = current; switches on 1 May, so in May–July
  empty already means the next academic year: type it, e.g. `2026`, to fetch the current one),
- **mode** `check` first (summary only), then `save`.

Professors come from Bullet's `teacherName` field (confirmed on the first `check`: 836 of 838
classes with a professor, 162 different professors). Bullet also sends `teacherAcronym`,
`teacherCode`, `teacherCategoryName`, `teacherLabourContractName` and
`teacherScientificAreaName`; none of them is published. If a later `check` finds no professor,
the summary lists Bullet's staff-like field names: add the right one to `PROFESSOR_FIELDS` in
`scripts/fetch_timetable.py`.

## Files

| File | What it is |
|---|---|
| `scripts/fetch_timetable.py` | The fetch (Python standard library only). |
| `.github/workflows/fetch-timetable.yml` | The GitHub task that runs it, by hand. |
| `data/index.json` | The list of saved semesters (written by the task; not edited by hand). |
| `data/timetable-YYYY-YY-S1.json`, `-S2.json` | One file per semester (written by the task). |
| `data/timetable.json` | Copy of the last save, for older copies of the tools. |

## Testing without Bullet

`BULLET_TOKEN_URL`, `BULLET_API_URL` and `OUT_DIR` can point the script at a local test server and a
scratch folder, so it can be tried without Bullet and without touching `data/`.
