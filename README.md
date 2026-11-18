# Bullet timetable (shared fetch)

One fetch from Bullet's API for every tool that needs the timetable. A GitHub task reads Bullet
(the API can't be called from a browser), saves a clean copy in `data/timetable.json`, and GitHub
Pages publishes it. Each tool then loads it with **Get timetable from Bullet**, and keeps the
Bullet CSV upload as a fallback.

Published file: `https://catolica-lisbon-sbe.github.io/bullet-timetable/data/timetable.json`

Used by: Make-up Classes (Aulas de Reposição). Room Allocation Check and Student Schedule Sandbox
can move to it later and drop their own copies of the fetch.

## What the file contains

```json
{
  "source": "Bullet API · Semester 1 2026/27",
  "fetchedAt": "2026-11-18T10:32:00Z",
  "semester": 1,
  "academicYear": "2026/2027",
  "professors": "coded (new codes on every fetch)",
  "columns": ["ModuleName", "ModuleAcronym", "ModuleCode", "SectionName", "Typology", "StudentGroup",
              "Unit", "Classroom", "WeekdayName", "StartTime", "EndTime", "Week", "EventType", "Professor"],
  "rows": [["Finance I", "Finance I", "L15.2028", "T1", "T", "Y2_LIC_GEST", "S1", "Classroom 514",
            "Tuesday", "09:30", "11:00", "2026-09-14,2026-09-21,…", "Aula Licenciatura", "P-7K3QM"], …]
}
```

- Same column names as Bullet's *Export Events* CSV, so tools read it like an export.
- `Week`: the Mondays of the weeks the class runs.
- Undergraduate (*Aula Licenciatura*) and Master (*Aula Mestrado*) classes of one semester.

## Privacy

The repository and the file are public, so:
- **Professors are codes** (e.g. `P-7K3QM`), never names. Each code is an HMAC of the name with a
  random key made for that run only and never saved: codes can't be turned back into names, and
  they change on every fetch. Within one file the same person always has the same code, which is
  enough to check whether a professor is free.
- No student data, no staff e-mails or usernames, no free-text annotations.
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

*Actions › Fetch timetable from Bullet › Run workflow*:
- **semester** 1 or 2, **academic year** (empty = current; switches on 1 May),
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
| `data/timetable.json` | The latest fetch (written by the task; not edited by hand). |

## Testing without Bullet

`BULLET_TOKEN_URL`, `BULLET_API_URL` and `OUT_DIR` can point the script at a local test server and a
scratch folder, so it can be tried without Bullet and without touching `data/`.
