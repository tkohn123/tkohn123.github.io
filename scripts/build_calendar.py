#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import re
import sys
from dataclasses import dataclass
from typing import List, Optional
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

BRUSSELS = ZoneInfo("Europe/Brussels")
ROLLING_DAYS = 30

USER_AGENT = "Mozilla/5.0 (compatible; BrusselsAgendaBot/1.0; +https://tkohn123.github.io/)"

PRIORITY_PEOPLE = {
    "von der leyen",
    "ribera",
    "virkkunen",
    "séjourné",
    "sejourne",
    "kallas",
    "šefčovič",
    "sefcovic",
    "dombrovskis",
    "kubilius",
    "costa",
    "metsola",
    "secretary general",
}

COUNCIL_KEEP_CONFIGS = {
    "european council",
    "euro summit",
    "eurogroup",
    "economic and financial affairs council",
    "foreign affairs council",
    "international summit",
    "ecofin",
    "fac",
}

MONTHS = {
    "January": 1, "February": 2, "March": 3, "April": 4,
    "May": 5, "June": 6, "July": 7, "August": 8,
    "September": 9, "October": 10, "November": 11, "December": 12
}

@dataclass
class Event:
    title: str
    start: dt.datetime
    end: dt.datetime
    all_day: bool
    location: str
    description: str
    url: str
    source: str
    priority: str

def now_brussels() -> dt.datetime:
    return dt.datetime.now(tz=BRUSSELS)

def date_window():
    start = now_brussels().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + dt.timedelta(days=ROLLING_DAYS)
    return start, end

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip()).lower()

def priority_from_text(text: str) -> str:
    t = norm(text)
    if any(p in t for p in PRIORITY_PEOPLE):
        return "A"
    if any(k in t for k in COUNCIL_KEEP_CONFIGS):
        return "A"
    return "B"

def in_window(e: Event, start: dt.datetime, end: dt.datetime) -> bool:
    return not (e.end <= start or e.start >= end)

def fetch(url: str) -> Optional[str]:
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
        if r.status_code != 200:
            print(f"[WARN] {url} returned {r.status_code}")
            return None
        return r.text
    except Exception as e:
        print(f"[WARN] Failed to fetch {url}: {e}")
        return None

def parse_consilium_meetings() -> List[Event]:
    url = "https://www.consilium.europa.eu/en/meetings/calendar/"
    html = fetch(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    events: List[Event] = []

    for a in soup.select("a[href]"):
        text = a.get_text(" ", strip=True)
        if not text:
            continue

        t = norm(text)
        if not any(k in t for k in COUNCIL_KEEP_CONFIGS):
            continue

        href = a["href"]
        link = "https://www.consilium.europa.eu" + href if href.startswith("/") else href

        detail_html = fetch(link)
        if not detail_html:
            continue

        dsoup = BeautifulSoup(detail_html, "html.parser")
        title_tag = dsoup.find("h1")
        title = title_tag.get_text(" ", strip=True) if title_tag else text

        dates = []
        for ttag in dsoup.select("time[datetime]"):
            d = ttag.get("datetime", "")[:10]
            if re.match(r"^\d{4}-\d{2}-\d{2}$", d):
                dates.append(d)

        dates = sorted(set(dates))
        if not dates:
            continue

        d0 = dt.date.fromisoformat(dates[0])
        d1 = dt.date.fromisoformat(dates[-1])
        start = dt.datetime(d0.year, d0.month, d0.day, tzinfo=BRUSSELS)
        end = dt.datetime(d1.year, d1.month, d1.day, tzinfo=BRUSSELS) + dt.timedelta(days=1)

        events.append(Event(
            title=f"CONSILIUM | {title}",
            start=start,
            end=end,
            all_day=True,
            location="Brussels",
            description=f"Source: {link}",
            url=link,
            source="CONSILIUM",
            priority="A"
        ))

    return events

def parse_euco_president_calendar() -> List[Event]:
    url = "https://www.consilium.europa.eu/en/european-council/president/calendar/"
    html = fetch(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    date_re = re.compile(r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b")

    events = []
    current_date: Optional[dt.date] = None

    for ln in lines:
        m = date_re.search(ln)
        if m:
            current_date = dt.date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))
            continue

        if current_date and len(ln) > 10:
            start = dt.datetime(current_date.year, current_date.month, current_date.day, tzinfo=BRUSSELS)
            end = start + dt.timedelta(days=1)

            events.append(Event(
                title=f"EUCO | President Costa: {ln}",
                start=start,
                end=end,
                all_day=True,
                location="(See source)",
                description=f"Source: {url}",
                url=url,
                source="EUCO",
                priority=priority_from_text(ln),
            ))

    return events

def parse_ep_weekly_agenda() -> List[Event]:
    url = "https://www.europarl.europa.eu/news/en/agenda/weekly-agenda"
    html = fetch(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    date_re = re.compile(r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b")
    time_re = re.compile(r"(\d{1,2})[:.](\d{2})\s*[-–]\s*(\d{1,2})[:.](\d{2})")

    events = []
    current_date: Optional[dt.date] = None

    for i, ln in enumerate(lines):
        dm = date_re.search(ln)
        if dm:
            current_date = dt.date(int(dm.group(3)), MONTHS[dm.group(2)], int(dm.group(1)))
            continue

        tm = time_re.search(ln)
        if tm and current_date:
            h1, m1, h2, m2 = map(int, tm.groups())
            title = lines[i+1] if i+1 < len(lines) else "EP agenda item"

            start = dt.datetime(current_date.year, current_date.month, current_date.day, h1, m1, tzinfo=BRUSSELS)
            end = dt.datetime(current_date.year, current_date.month, current_date.day, h2, m2, tzinfo=BRUSSELS)

            events.append(Event(
                title=f"EP | {title}",
                start=start,
                end=end,
                all_day=False,
                location="European Parliament",
                description=f"Source: {url}",
                url=url,
                source="EP",
                priority=priority_from_text(title),
            ))

    return events

def build_ics(events: List[Event]) -> str:
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//TK Brussels Agenda//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Brussels Agenda (AUTO)",
        "X-WR-TIMEZONE:Europe/Brussels",
    ]

    stamp = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    for e in sorted(events, key=lambda x: x.start):
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{abs(hash((e.title, e.start.isoformat())))}@tkohn123")
        lines.append(f"DTSTAMP:{stamp}")
        lines.append(f"SUMMARY:{esc(e.title)}")

        if e.all_day:
            lines.append(f"DTSTART;VALUE=DATE:{e.start.strftime('%Y%m%d')}")
            lines.append(f"DTEND;VALUE=DATE:{e.end.strftime('%Y%m%d')}")
        else:
            lines.append(f"DTSTART;TZID=Europe/Brussels:{e.start.strftime('%Y%m%dT%H%M%S')}")
            lines.append(f"DTEND;TZID=Europe/Brussels:{e.end.strftime('%Y%m%dT%H%M%S')}")

        lines.append(f"DESCRIPTION:{esc(e.description)}")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"

def write_csv(events: List[Event]):
    with open("brussels.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["priority", "start", "end", "title", "source", "url"])
        for e in sorted(events, key=lambda x: x.start):
            w.writerow([e.priority, e.start.isoformat(), e.end.isoformat(), e.title, e.source, e.url])


def write_html(events: List[Event], path="index.html"):
    lines = []
    lines.append("<!DOCTYPE html>")
    lines.append("<html>")
    lines.append("<head>")
    lines.append("<meta charset='utf-8'>")
    lines.append("<title>Brussels Agenda</title>")

    # --- PASSWORD PROTECTION ---
    lines.append("<script>")
    lines.append("const password = 'Brussels';")
    lines.append("const userInput = prompt('Enter password:');")
    lines.append("if (userInput !== password) {")
    lines.append("  document.write('Access denied');")
    lines.append("  document.stop();")
    lines.append("}")
    lines.append("</script>")
    # ----------------------------

    lines.append("</head>")
    lines.append("<body>")
    
    current_date = None

    for e in sorted(events, key=lambda x: x.start):
        date_str = e.start.strftime("%A, %d %B %Y")
        if date_str != current_date:
            lines.append(f"<h2>{date_str}</h2>")
            current_date = date_str

        time_part = "All day" if e.all_day else f"{e.start.strftime('%H:%M')}–{e.end.strftime('%H:%M')}"
        lines.append(f"<p><strong>{time_part}</strong> — {e.title}<br>")
        lines.append(f"<small><a href='{e.url}' target='_blank'>Source</a></small></p>")

    lines.append("</body></html>")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> int:
    start, end = date_window()

    all_events: List[Event] = []
    all_events += parse_consilium_meetings()
    all_events += parse_euco_president_calendar()
    all_events += parse_ep_weekly_agenda()

    events = [e for e in all_events if in_window(e, start, end)]

    seen = set()
    deduped = []
    for e in events:
        key = (norm(e.title), e.start.date())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(e)

    with open("brussels.ics", "w", encoding="utf-8") as f:
        f.write(build_ics(deduped))

    write_csv(deduped)
    write_html(deduped, "index.html")
    return 0

if __name__ == "__main__":
    sys.exit(main())
