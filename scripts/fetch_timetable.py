"""
Bullet timetable – one shared fetch for every tool (run by GitHub, see
.github/workflows/fetch-timetable.yml). Adapted from Room Allocation Check's fetch task.

Downloads one semester of classes (Undergraduate "Aula Licenciatura" and Master
"Aula Mestrado"), keeps only the columns the tools use and saves them in one file per
semester, data/timetable-2026-27-S1.json (published by GitHub Pages), listed in
data/index.json so the tools can pick the semester in use with "Get timetable from Bullet".
data/timetable.json is also written (a copy of the last save) for older copies of the tools.

Units: semester 1 = S1, T1, T2; semester 2 = S2, T3, T4. Classes of the other semester are
skipped quietly (the date windows overlap in January and February); any other Unit (empty,
misspelt…) is a mistake in Bullet: the classes are left out and listed with a ⚠ warning.

Privacy (the repository and the file are public):
  - Professors are replaced by codes (e.g. P-7K3QM). A code is an HMAC of the name with a
    random key made for this run only and never saved, so codes can't be turned back into
    names and change on every fetch. Within one file, the same person always has the same
    code, which is all the tools need to check whether a professor is free.
  - No student data, no staff e-mails or usernames, no free-text annotations.
  - The run's summary on GitHub shows counts and field names only, never values that
    could identify a person.

Python standard library only. Settings come from environment variables:
  BULLET_CLIENT_ID, BULLET_CLIENT_SECRET  (GitHub secrets)
  SEMESTER        1 (Units S1, T1, T2) or 2 (Units S2, T3, T4)
  ACADEMIC_YEAR   first year of the academic year, e.g. 2026 for 2026/27 (empty = current)
  MODE            "check" (report only, saves nothing) or "save"
  OUT_DIR         where to save the files (default: data/ next to this script's folder)
"""
import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = os.environ.get('BULLET_TOKEN_URL') or 'https://clsbe-is.bulletscheduling.com/connect/token'
API_URL = os.environ.get('BULLET_API_URL') or 'https://clsbe-api.bulletscheduling.com'   # overridable for local tests
SCOPE = 'bestlegacy_api_scope'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.environ.get('OUT_DIR') or os.path.join(ROOT, 'data')

UNITS = {'1': ('S1', 'T1', 'T2'), '2': ('S2', 'T3', 'T4')}
LEVELS = ['Aula Licenciatura', 'Aula Mestrado']   # event types kept
WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

# Column of the shared file <- Bullet API field(s), first non-empty one wins.
# Same names as Bullet's "Export Events" CSV, so tools read the file like an export.
FIELDS = {
    'ModuleName': ['moduleName'],
    'ModuleAcronym': ['moduleAcronym'],
    'ModuleCode': ['moduleCode'],
    'SectionName': ['wlsSectionName'],
    'Typology': ['typologyName'],
    'StudentGroup': ['studentGroupName', 'studentGroupCode'],
    'Unit': ['unit'],
    'Classroom': ['classroomName', 'classroomCode'],
}
# Where Bullet may put the professor(s). TO CONFIRM on the first "check" run: the summary
# lists the field names that look like staff fields (names only, never values).
PROFESSOR_FIELDS = ['academicStaffName', 'academicStaffNames', 'academicStaff', 'academicStaffs',
                    'teacherName', 'teacherNames', 'teachers', 'staffName', 'staff']
COLUMNS = ['ModuleName', 'ModuleAcronym', 'ModuleCode', 'SectionName', 'Typology', 'StudentGroup',
           'Unit', 'Classroom', 'WeekdayName', 'StartTime', 'EndTime', 'Week', 'EventType', 'Professor']


class Stop(Exception):
    """An error explained in plain words for the run's summary (status = Bullet's HTTP code, if any)."""
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def explain(status, where):
    if where == 'the sign-in' and status in (400, 401):
        return ('Bullet refused the sign-in: check BULLET_CLIENT_ID and BULLET_CLIENT_SECRET '
                '(no spaces), or ask Bullet whether the secret has expired.')
    return {
        400: f'Bullet did not accept the request for {where} (400). The date format may need changing.',
        401: 'Bullet refused the sign-in (401): check BULLET_CLIENT_ID and BULLET_CLIENT_SECRET, or the secret has expired.',
        403: f'The Bullet client is not allowed to read {where} (403).',
        404: f'Bullet does not know {where} (404): the API address may have changed.',
    }.get(status, f'Bullet answered with error {status} for {where}. Try again later; if it persists, ask Bullet.')


def request(url, data=None, headers=None, where='the timetable'):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=180) as res:
            return json.loads(res.read().decode('utf-8-sig'))
    except urllib.error.HTTPError as err:
        raise Stop(explain(err.code, where), err.code) from None
    except urllib.error.URLError as err:
        raise Stop(f'Could not reach Bullet ({err.reason}). If Bullet only accepts approved '
                   'computers, GitHub\'s servers may be blocked: ask Bullet.') from None


def get_token(client_id, secret):
    body = urllib.parse.urlencode({'grant_type': 'client_credentials', 'client_id': client_id,
                                   'client_secret': secret, 'scope': SCOPE}).encode()
    res = request(TOKEN_URL, body, {'Content-Type': 'application/x-www-form-urlencoded'}, 'the sign-in')
    if not res.get('access_token'):
        raise Stop('Bullet\'s sign-in gave no access key.')
    return res['access_token']


def weeks(start, end):
    """(Monday, Sunday) of every week from start to end.
    One week per request: Bullet sends each class once per request (its first date in the
    requested range), so asking for a whole month would keep only one week of each month."""
    d = start - dt.timedelta(days=start.weekday())
    while d <= end:
        yield d, d + dt.timedelta(days=6)
        d += dt.timedelta(days=7)


def semester_dates(semester, year):
    # Wide windows on purpose: rows are kept by their Unit, not by date.
    if semester == '1':
        return dt.date(year, 8, 1), dt.date(year + 1, 2, 28)
    return dt.date(year + 1, 1, 1), dt.date(year + 1, 7, 31)


# Two read-only requests give the same class rows (same field names for what we use).
# The first one the Bullet client may use is kept for the whole fetch.
ENDPOINTS = ['/api/Events/createeventallcsv/{a}/{b}', '/api/Events/allRows/{a}/{b}']
PROBES = [('/api/AcademicYear/active', 'GET /api/AcademicYear/active (academic years)')] + \
    [(e, 'GET ' + e) for e in ENDPOINTS]


def get(token, path, where):
    res = request(API_URL + path, headers={'Authorization': f'Bearer {token}', 'Accept': 'application/json'}, where=where)
    return res.get('data') if isinstance(res, dict) else res


def access_report(token, a, b):
    """Which read requests the client may use, to send to Bullet when the timetable is refused."""
    lines = []
    for path, label in PROBES:
        try:
            get(token, path.format(a=a.isoformat(), b=b.isoformat()), label)
            lines.append(f'  - {label}: allowed')
        except Stop as err:
            lines.append(f'  - {label}: refused ({err.status or "no answer"})')
    return lines


def fetch_rows(token, start, end, report):
    rows, endpoint = [], None
    for a, b in weeks(start, end):
        where = f'the classes of the week of {a:%d %B %Y}'
        if endpoint is None:
            for candidate in ENDPOINTS:
                try:
                    data = get(token, candidate.format(a=a.isoformat(), b=b.isoformat()), where)
                    endpoint = candidate
                    break
                except Stop as err:
                    if err.status not in (403, 404, 405):
                        raise
            if endpoint is None:
                report += ['- Access of the Bullet client (send this to Bullet):'] + access_report(token, a, b)
                raise Stop('The Bullet client may sign in but is not allowed to read the classes (403). '
                           'Ask Bullet to allow one of the two Events requests listed above (read only).')
            report.append(f'- Bullet request used: `GET {endpoint}`')
        else:
            data = get(token, endpoint.format(a=a.isoformat(), b=b.isoformat()), where)
        for raw in data or []:
            if isinstance(raw, dict):
                raw['_week'] = a
                rows.append(raw)
    return rows


def pick(raw, keys):
    low = {k.lower(): v for k, v in raw.items()}
    for k in keys:
        v = low.get(k.lower())
        if v not in (None, '') and not isinstance(v, (list, dict)):
            return str(v).strip()
    return ''


def to_date(v):
    m = re.match(r'(\d{4})-(\d{1,2})-(\d{1,2})', v or '')
    if m:
        return dt.date(int(m[1]), int(m[2]), int(m[3]))
    m = re.match(r'(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})', v or '')
    if m:
        return dt.date(int(m[3]), int(m[2]), int(m[1]))
    return None


def to_time(v):
    m = re.search(r'(\d{1,2}):(\d{2})', v or '')
    return f'{int(m[1]):02d}:{m[2]}' if m else (v or '')


def level_of(raw):
    """'Aula Licenciatura', 'Aula Mestrado' or None, from the event type (EventType / EventTitle)."""
    for text in (pick(raw, ['eventTypeName']), pick(raw, ['eventName'])):
        for level in LEVELS:
            if text.lower().startswith(level.lower()):
                return level
    return None


# ---------- Professors → codes ----------
def professor_names(raw):
    """The professor name(s) of a row, whatever shape Bullet uses: text ("A; B"), a list of
    texts, or a list of objects with a name."""
    low = {k.lower(): v for k, v in raw.items()}
    for key in PROFESSOR_FIELDS:
        v = low.get(key.lower())
        if v in (None, '', []):
            continue
        items = v if isinstance(v, list) else [v]
        names = []
        for it in items:
            if isinstance(it, dict):
                it = it.get('name') or it.get('academicStaffName') or it.get('fullName') or ''
            names += [n.strip() for n in re.split(r'[;|\n]', str(it)) if n.strip()]
        if names:
            return names
    return []


class Coder:
    """Name → code, with a key made for this run only (never saved or printed)."""
    def __init__(self):
        self.key = secrets.token_bytes(32)
        self.codes = {}

    def code(self, name):
        norm = ' '.join(unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode().upper().split())
        if norm not in self.codes:
            digest = hmac.new(self.key, norm.encode(), hashlib.sha256).digest()
            self.codes[norm] = 'P-' + base64.b32encode(digest).decode()[:5]
        return self.codes[norm]


def staff_like_fields(raw_rows):
    """Field NAMES (never values) that look like staff fields, to confirm PROFESSOR_FIELDS."""
    keys = set()
    for raw in raw_rows[:200]:
        keys |= {k for k in raw if re.search(r'staff|teacher|docente|professor|lecturer', k, re.I)}
    return sorted(keys)


def convert(raw, level, coder):
    row = {col: pick(raw, keys) for col, keys in FIELDS.items()}
    row['EventType'] = level
    day = to_date(pick(raw, ['eventDateOccurrence']))
    week = raw.get('_week')
    if day and week and not (week <= day <= week + dt.timedelta(days=6)):
        day = week + dt.timedelta(days=day.weekday())  # a date outside the week asked for: keep its weekday in that week
    monday = day - dt.timedelta(days=day.weekday()) if day else to_date(pick(raw, ['eventWeekStartDate']))
    row['WeekdayName'] = WEEKDAYS[day.weekday()] if day else pick(raw, ['eventWeekdayText'])
    row['StartTime'] = to_time(pick(raw, ['eventStartTime']))
    row['EndTime'] = to_time(pick(raw, ['eventEndTime']))
    row['Week'] = monday.isoformat() if monday else ''
    row['Professor'] = '; '.join(sorted({coder.code(n) for n in professor_names(raw)}))
    return {c: row[c] for c in COLUMNS}


def merge_weeks(rows):
    """One row per class slot, listing all its weeks (like Bullet's export)."""
    merged = {}
    for r in rows:
        key = tuple(r[c] for c in COLUMNS if c != 'Week')
        if key in merged:
            merged[key]['_weeks'].add(r['Week'])
        else:
            merged[key] = dict(r, _weeks={r['Week']} - {''})
    out = []
    for r in merged.values():
        r['Week'] = ','.join(sorted(r.pop('_weeks')))
        out.append(r)
    out.sort(key=lambda r: (r['ModuleName'], r['SectionName'], r['Unit'], r['WeekdayName'], r['StartTime']))
    return out


def counted(values, n=12):
    counts = {}
    for v in values:
        counts[v or '(empty)'] = counts.get(v or '(empty)', 0) + 1
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:n]
    return ', '.join(f'{k} ({v})' for k, v in top) + (' …' if len(counts) > n else '')


def main():
    client_id = os.environ.get('BULLET_CLIENT_ID', '').strip()
    secret = os.environ.get('BULLET_CLIENT_SECRET', '').strip()
    semester = os.environ.get('SEMESTER', '1').strip()
    mode = os.environ.get('MODE', 'check').strip()
    today = dt.date.today()
    year_text = os.environ.get('ACADEMIC_YEAR', '').strip()[:4]
    year = int(year_text) if year_text.isdigit() else (today.year if today.month >= 5 else today.year - 1)
    label = f'Semester {semester} {year}/{str(year + 1)[2:]}'
    report = [f'## Bullet timetable: {label}', '']

    try:
        if semester not in UNITS:
            raise Stop('Semester must be 1 or 2.')
        if not client_id or not secret:
            raise Stop('The secrets BULLET_CLIENT_ID and BULLET_CLIENT_SECRET are not set.')
        token = get_token(client_id, secret)
        start, end = semester_dates(semester, year)
        raw_rows = fetch_rows(token, start, end, report)
        report.append(f'- Rows received from Bullet ({start:%d %b %Y} – {end:%d %b %Y}): **{len(raw_rows)}**')
        if not raw_rows:
            raise Stop('Bullet returned no classes for these dates.')

        units, coder = UNITS[semester], Coder()
        other_sem = UNITS['2' if semester == '1' else '1']
        rows, other_types, other_sem_rows, bad_units = [], [], [], []
        for raw in raw_rows:
            level = level_of(raw)
            if not level:
                other_types.append(pick(raw, ['eventTypeName']))
                continue
            row = convert(raw, level, coder)
            unit = row['Unit'].strip().upper()
            if unit in other_sem:                      # the other semester's classes (overlapping dates)
                other_sem_rows.append(unit)
                continue
            if unit not in units:                      # a mistake in Bullet: wrong or empty Unit
                bad_units.append(row)
                continue
            row['Unit'] = unit
            rows.append(row)

        report.append(f'- Skipped, not "Aula Licenciatura" / "Aula Mestrado": {len(other_types)}'
                      + (f' – {counted(other_types)}' if other_types else ''))
        report.append(f'- Skipped, classes of the other semester ({"/".join(other_sem)}): {len(other_sem_rows)}')
        bad = merge_weeks(bad_units) if bad_units else []
        bad_count = {}
        for r in bad:
            bad_count[r['Unit'] or '(empty)'] = bad_count.get(r['Unit'] or '(empty)', 0) + 1
        if bad:
            report += ['', f'### ⚠ {len(bad)} classes left out: Unit is not {"/".join(units)}',
                       f'- Units found: {", ".join(f"{k} ({v})" for k, v in sorted(bad_count.items()))}',
                       '- Fix the Unit of these classes in Bullet, then run this again:']
            for r in sorted(bad, key=lambda r: (r['ModuleName'], r['SectionName']))[:30]:
                report.append(f"  - {r['ModuleName']} ({r['ModuleCode']}) – {r['SectionName'] or '–'} · "
                              f"{r['WeekdayName']} {r['StartTime']} · Unit: {r['Unit'] or '(empty)'}")
            if len(bad) > 30:
                report.append(f'  - … and {len(bad) - 30} more')
        fetched = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        merged = merge_weeks(rows)
        with_prof = sum(1 for r in merged if r['Professor'])
        report += ['', '### Classes',
                   f'- Class rows: {len(rows)} → {len(merged)} after merging weeks',
                   f'- Event types: {counted(r["EventType"] for r in merged)}',
                   f'- Courses: {len({r["ModuleCode"] for r in merged})}',
                   f'- Units: {counted(r["Unit"] for r in merged)}',
                   f'- Weekdays: {counted(r["WeekdayName"] for r in merged)}',
                   f'- Classrooms (sample): {counted((r["Classroom"] for r in merged), 8)}',
                   f'- Without a room: {sum(1 for r in merged if not r["Classroom"])}',
                   f'- Missing week: {sum(1 for r in merged if not r["Week"])}',
                   '', '### Professors (coded)',
                   f'- Classes with a professor: {with_prof} of {len(merged)}',
                   f'- Different professors: {len(coder.codes)}',
                   f'- Staff-like fields found in Bullet (names only): {", ".join(staff_like_fields(raw_rows)) or "none"}']
        if not with_prof:
            report.append('- ⚠ No professor found. Add the right field name from the line above to '
                          'PROFESSOR_FIELDS in scripts/fetch_timetable.py.')
        if not merged:
            raise Stop('No Undergraduate or Master classes of this semester were found.')
        mondays = sorted({w for r in merged for w in r['Week'].split(',') if w})
        first = mondays[0] if mondays else ''
        last = (dt.date.fromisoformat(mondays[-1]) + dt.timedelta(days=6)).isoformat() if mondays else ''
        if mode == 'save':
            name = f'timetable-{year}-{str(year + 1)[2:]}-S{semester}.json'
            out = {'source': f'Bullet API · {label}', 'fetchedAt': fetched, 'semester': int(semester),
                   'academicYear': f'{year}/{year + 1}', 'units': list(units), 'firstDate': first, 'lastDate': last,
                   'unexpectedUnits': bad_count, 'professors': 'coded (new codes on every fetch)',
                   'columns': COLUMNS, 'rows': [[r[c] for c in COLUMNS] for r in merged]}
            os.makedirs(OUT_DIR, exist_ok=True)
            for fname in (name, 'timetable.json'):     # timetable.json: copy of the last save, for older tools
                with open(os.path.join(OUT_DIR, fname), 'w', encoding='utf-8', newline='\n') as f:
                    json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
            index_path = os.path.join(OUT_DIR, 'index.json')
            try:
                with open(index_path, encoding='utf-8') as f:
                    index = json.load(f).get('timetables', [])
            except (OSError, ValueError):
                index = []
            index = [e for e in index if e.get('file') != name]
            index.append({'file': name, 'semester': int(semester), 'academicYear': f'{year}/{year + 1}',
                          'label': label, 'units': list(units), 'firstDate': first, 'lastDate': last,
                          'fetchedAt': fetched, 'classes': len(merged), 'unexpectedUnits': sum(bad_count.values())})
            index.sort(key=lambda e: (e['academicYear'], e['semester']))
            with open(index_path, 'w', encoding='utf-8', newline='\n') as f:
                json.dump({'timetables': index}, f, ensure_ascii=False, indent=1)
            report.append(f'- Saved `data/{name}` ({len(merged)} classes, {first} to {last}) and updated `data/index.json`')
        report += ['', '**Check only: nothing was saved.**' if mode != 'save' else
                   '**Saved.** In 1–2 minutes the tools can load it with "Get timetable from Bullet".']
        code = 0
    except Stop as err:
        report += ['', f'**✕ {err}**']
        code = 1

    text = '\n'.join(report) + '\n'
    sys.stdout.reconfigure(encoding='utf-8')
    print(text)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as f:
            f.write(text)
    return code


if __name__ == '__main__':
    sys.exit(main())
