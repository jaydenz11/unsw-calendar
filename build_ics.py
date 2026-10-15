#!/usr/bin/env python3
"""Build the UNSW Deadlines calendar feed (.ics) from a dump of the tracker database.

Usage: python3 -I build_ics.py <dump_dir> <output.ics>

<dump_dir> is laid out as ArtifactData's out_dir writes it:
  <dump_dir>/items/<id>.json      one deadline per file (the document's fields)
  <dump_dir>/progress/<id>.json   ticks ({"done": true}) - optional
  <dump_dir>/terms/<id>.json      term definitions with course names - optional
Only the standard library is used.
"""
import datetime as dt
import glob
import json
import os
import sys

CAL_NAME = "UNSW Deadlines"
UID_DOMAIN = "unsw-deadlines.tracker"


def load_dir(path):
    out = {}
    for f in sorted(glob.glob(os.path.join(path, "*.json"))):
        try:
            with open(f, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            continue
        # Tolerate a wrapped shape {"id":..., "data": {...}} as well as bare fields.
        if isinstance(doc, dict) and isinstance(doc.get("data"), dict) and "id" in doc:
            doc = doc["data"]
        if isinstance(doc, dict):
            out[os.path.splitext(os.path.basename(f))[0]] = doc
    return out


def parse_iso(s):
    if not s:
        return None
    try:
        d = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone(dt.timedelta(hours=10)))
    return d


def utc(d):
    return d.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def esc(text):
    text = str(text or "")
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def fold(line):
    """Fold a content line at 75 octets (RFC 5545 3.1)."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > (75 if not parts else 74):
            parts.append(cur.decode("utf-8"))
            cur = b""
        cur += b
    parts.append(cur.decode("utf-8"))
    return "\r\n ".join(parts)


def sydney_date(d):
    # Calendar date in Sydney. Offset from the stored ISO string is already Sydney local time.
    return d.date()


def sydney_9am(day):
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime(day.year, day.month, day.day, 9, 0, tzinfo=ZoneInfo("Australia/Sydney"))
    except Exception:
        return None


def weight_text(it):
    if it.get("weightLabel"):
        return str(it["weightLabel"])
    if it.get("weight") is not None:
        return f"{it['weight']}%"
    return ""


def build(dump_dir, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    items = load_dir(os.path.join(dump_dir, "items"))
    progress = load_dir(os.path.join(dump_dir, "progress"))
    terms = load_dir(os.path.join(dump_dir, "terms"))
    names = {}
    for t in terms.values():
        for c in t.get("courses") or []:
            if c.get("code"):
                names[c["code"]] = c.get("name") or ""

    stamp = utc(now)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//UNSW Deadlines tracker//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{CAL_NAME}",
        "X-WR-CALDESC:Quizzes\\, tests\\, assignments and exams from Moodle. Updated nightly.",
        "X-WR-TIMEZONE:Australia/Sydney",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
    ]
    count = 0
    for iid, it in sorted(items.items()):
        due = parse_iso(it.get("due"))
        start = parse_iso(it.get("start"))
        kind = it.get("kind") or ""
        time_known = bool(it.get("timeKnown"))
        if not due and not start:
            continue
        # Exams (and anything else) with only a window and no exact date stay out until dated.
        if not time_known and kind == "exam":
            continue

        done = bool((progress.get(iid) or {}).get("done")) or it.get("status") == "graded"
        course = it.get("course") or ""
        title = it.get("title") or iid
        prefix = "✓ " if done else ""
        summary = f"{prefix}{course} {title}".strip()

        desc = []
        if names.get(course):
            desc.append(f"{course} {names[course]}")
        w = weight_text(it)
        if w:
            desc.append(f"Weight: {w}")
        if it.get("mark"):
            desc.append(f"Mark: {it['mark']}")
        if it.get("when") and not time_known:
            desc.append(f"When: {it['when']}")
        if it.get("notes"):
            desc.append(str(it["notes"]))
        if done:
            desc.append("Marked done in your tracker.")

        ev = ["BEGIN:VEVENT",
              f"UID:{iid}@{UID_DOMAIN}",
              f"DTSTAMP:{stamp}",
              f"LAST-MODIFIED:{stamp}"]
        if time_known and due:
            if it.get("timeIs") == "start" or kind == "exam":
                # The time is when it starts (a test in a lecture slot, a dated exam): one hour from then.
                ev.append(f"DTSTART:{utc(due)}")
                ev.append(f"DTEND:{utc(due + dt.timedelta(hours=1))}")
                ev.append(f"SUMMARY:{esc(summary)}")
            else:
                # Deadline: a 30-minute block ending at the due time.
                ev.append(f"DTSTART:{utc(due - dt.timedelta(minutes=30))}")
                ev.append(f"DTEND:{utc(due)}")
                ev.append(f"SUMMARY:{esc(('✓ ' if done else 'Due: ') + course + ' ' + title)}")
        else:
            # Week-only item (e.g. a tutorial quiz): all-day on the Monday of that week.
            day = sydney_date(start or due)
            ev.append(f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}")
            ev.append(f"DTEND;VALUE=DATE:{(day + dt.timedelta(days=1)).strftime('%Y%m%d')}")
            ev.append(f"SUMMARY:{esc(summary + ' · this week')}")
            ev.append("TRANSP:TRANSPARENT")
        if it.get("where"):
            ev.append(f"LOCATION:{esc(it['where'])}")
        if desc:
            ev.append(f"DESCRIPTION:{esc(chr(10).join(desc))}")
        if it.get("link"):
            ev.append(f"URL:{it['link']}")
        ev.append("STATUS:CONFIRMED")
        if not done:
            # Same alerts as the tracker's reminders: 9am Sydney, 3 days and 1 day before.
            ref_day = due.date() if (time_known and due) else sydney_date(start or due)
            for n, label in ((3, "In 3 days"), (1, "Tomorrow")):
                at = sydney_9am(ref_day - dt.timedelta(days=n))
                if at and at > now:
                    ev += ["BEGIN:VALARM", "ACTION:DISPLAY",
                           f"DESCRIPTION:{esc(label + ': ' + course + ' ' + title)}",
                           f"TRIGGER;VALUE=DATE-TIME:{utc(at)}", "END:VALARM"]

        ev.append("END:VEVENT")
        lines += ev
        count += 1
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines) + "\r\n", count


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: build_ics.py <dump_dir> <output.ics>")
    text, n = build(sys.argv[1])
    with open(sys.argv[2], "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    print(f"wrote {n} events to {sys.argv[2]}")
