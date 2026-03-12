#!/usr/bin/env python3
"""
Build a rolling 14-day Brussels agenda calendar.

Outputs:
- brussels.ics (Europe/Brussels timezone)
- brussels.csv

Sources implemented initially:
- Council / Consilium meetings calendar (filtered)
- European Council President calendar page
- European Parliament weekly agenda
- Commission calendar items page (unfiltered list + filter)
- NATO media advisories (basic)
- EEAS press material (basic)

Notes:
- Some sources (EBS grid) can be tricky due to JS/anti-bot; keep manual unless you later add a headless fetch.
"""
from __future__ import annotations

import time
import random
import csv
import dataclasses
import datetime as dt
import re
import sys
from dataclasses import dataclass
from typing import Iterable, List, Optional
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

BRUSSELS = ZoneInfo("Europe/Brussels")

ROLLING_DAYS = 14

USER_AGENT = (
    "Mozilla/5.0 (compatible; BrusselsAgendaBot/1.0; +https://tkohn123.github.io/)"
)

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
    priority: str  # A/B/C

def now_brussels() -> dt.datetime:
    return dt.datetime.now(tz=BRUSSELS)

def date_window() -> tuple[dt.datetime, dt.datetime]:
    start = now_brussels().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + dt.timedelta(days=ROLLING_DAYS)
    return start, end

def in_window(e: Event, start: dt.datetime, end: dt.datetime) -> bool:
    # include if any overlap
    return not (e.end <= start or e.start >= end)

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip()).lower()

def priority_from_text(text: str) -> str:
    t = norm(text)
    if any(p in t for p in PRIORITY_PEOPLE):
        return "A"
    if any(k in t for k in COUNCIL_KEEP_CONFIGS):
        return "A"
    return "B"

import time
import random
import requests

SESSION = requests.Session()

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

def fetch(url: str) -> str:
    last_exc = None
    for attempt in range(4):
        try:
            # small jitter helps avoid simple bot detection
            time.sleep(0.3 + random.random() * 0.4)

            response = SESSION.get(
                url,
                headers=DEFAULT_HEADERS,
                timeout=30,
            )
            response.raise_for_status()
            return response.text

        except Exception as exc:
            last_exc = exc
            # exponential backoff
            time.sleep(2 ** attempt)

    raise last_exc

def parse_consilium_meetings() -> List[Event]:
    # Consilium meetings calendar page (contains multiple meeting types)
    url = "https://www.consilium.europa.eu/en/meetings/calendar/"
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")

    events: List[Event] = []
    # The site changes structure occasionally; we do a best-effort scrape:
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        text = a.get_text(" ", strip=True)
        if not text:
            continue
        t = norm(text)

        # Keep only key configurations (rough filter)
        keep = any(k in t for k in COUNCIL_KEEP_CONFIGS)
        if not keep:
            continue

        # Try to find a nearby date (best-effort)
        # Many pages link to meeting detail pages that include the date in the URL or on page.
        if href.startswith("/"):
            link = "https://www.consilium.europa.eu" + href
        else:
            link = href

        # Visit detail page to get the date range if possible
        try:
            detail = fetch(link)
            dsoup = BeautifulSoup(detail, "html.parser")
            title = dsoup.find("h1")
            title_text = title.get_text(" ", strip=True) if title else text

            # Look for <time datetime="YYYY-MM-DD"> patterns
            times = dsoup.select("time[datetime]")
            dates = []
            for ttag in times:
                d = ttag.get("datetime", "")
                if re.match(r"^\d{4}-\d{2}-\d{2}", d):
                    dates.append(d[:10])
            dates = sorted(set(dates))

            if dates:
                d0 = dt.date.fromisoformat(dates[0])
                d1 = dt.date.fromisoformat(dates[-1])
                start = dt.datetime(d0.year, d0.month, d0.day, tzinfo=BRUSSELS)
                end = dt.datetime(d1.year, d1.month, d1.day, tzinfo=BRUSSELS) + dt.timedelta(days=1)
            else:
                # fallback: skip if no date found
                continue

            ev = Event(
                title=f"CONSILIUM | {title_text}",
                start=start,
                end=end,
                all_day=True,
                location="Brussels",
                description=f"Source: {link}",
                url=link,
                source="CONSILIUM",
                priority="A",
            )
            events.append(ev)
        except Exception:
            # if detail fetch fails, ignore
            continue

    return events

def parse_euco_president_calendar() -> List[Event]:
    url = "https://www.consilium.europa.eu/en/european-council/president/calendar/"
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")
    events: List[Event] = []

    # Best-effort: look for headings containing dates and associated items
    # We’ll parse any element that looks like "11 March 2026" etc.
    date_re = re.compile(r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b")
    month_map = {m: i for i, m in enumerate(
        ["January","February","March","April","May","June","July","August","September","October","November","December"], start=1
    )}

    text = soup.get_text("\n", strip=True)
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    current_date: Optional[dt.date] = None
    for ln in lines:
        m = date_re.search(ln)
        if m:
            day = int(m.group(1))
            month = month_map[m.group(2)]
            year = int(m.group(3))
            current_date = dt.date(year, month, day)
            continue
        if current_date and len(ln) > 10:
            # treat as an item
            start = dt.datetime(current_date.year, current_date.month, current_date.day, tzinfo=BRUSSELS)
            end = start + dt.timedelta(days=1)
            ev = Event(
                title=f"EUCO | President Costa: {ln}",
                start=start,
                end=end,
                all_day=True,
                location="(See source)",
                description=f"Source: {url}",
                url=url,
                source="EUCO",
                priority=priority_from_text(ln),
            )
            events.append(ev)

    return events

def parse_ep_weekly_agenda() -> List[Event]:
    url = "https://www.europarl.europa.eu/news/en/agenda/weekly-agenda"
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")

    events: List[Event] = []

    # Best-effort: find time ranges like 09.00 - 11.50 or 09:00 - 11:50 and nearby titles.
    page_text = soup.get_text("\n", strip=True)
    lines = [ln.strip() for ln in page_text.split("\n") if ln.strip()]

    time_re = re.compile(r"(\d{1,2})[:.](\d{2})\s*[-–]\s*(\d{1,2})[:.](\d{2})")
    date_re = re.compile(r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b")
    month_map = {m: i for i, m in enumerate(
        ["January","February","March","April","May","June","July","August","September","October","November","December"], start=1
    )}

    current_date: Optional[dt.date] = None
    for i, ln in enumerate(lines):
        dm = date_re.search(ln)
        if dm:
            current_date = dt.date(int(dm.group(3)), month_map[dm.group(2)], int(dm.group(1)))
            continue

        tm = time_re.search(ln)
        if tm and current_date:
            h1, m1, h2, m2 = map(int, tm.groups())
            title = lines[i+1] if i+1 < len(lines) else "European Parliament agenda item"
            start = dt.datetime(current_date.year, current_date.month, current_date.day, h1, m1, tzinfo=BRUSSELS)
            end = dt.datetime(current_date.year, current_date.month, current_date.day, h2, m2, tzinfo=BRUSSELS)
            ev = Event(
                title=f"EP | {title}",
                start=start,
                end=end,
                all_day=False,
                location="European Parliament (see agenda)",
                description=f"Source: {url}",
                url=url,
                source="EP",
                priority=priority_from_text(title),
            )
            events.append(ev)

    return events

def parse_commission_calendar_items() -> List[Event]:
    # Uses the “calendar items” listing (works even when “individual calendars” 403)
    base = "https://commission.europa.eu/about/organisation/college-commissioners/calendar-items-president-and-commissioners_en"
    urls = [base, base + "?page=1", base + "?page=2", base + "?page=3"]

    keep_names = {"von der leyen","ribera","virkkunen","sejourne","séjourné","kallas","sefcovic","šefčovič","dombrovskis","kubilius"}
    events: List[Event] = []

    for url in urls:
        try:
            html = fetch(url)
        except Exception:
            continue
        soup = BeautifulSoup(html, "html.parser")
        # Best-effort: find list items/cards
        for item in soup.select("article, .ecl-card, .listing-item, li"):
            text = item.get_text(" ", strip=True)
            if not text:
                continue
            t = norm(text)

            if not any(n in t for n in keep_names):
                continue

            # Try to extract a date like "11 March 2026"
            m = re.search(r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b", text)
            if not m:
                continue
            day = int(m.group(1))
            month = ["January","February","March","April","May","June","July","August","September","October","November","December"].index(m.group(2)) + 1
            year = int(m.group(3))
            d0 = dt.date(year, month, day)

            start = dt.datetime(d0.year, d0.month, d0.day, tzinfo=BRUSSELS)
            end = start + dt.timedelta(days=1)

            title = re.sub(r"\s+", " ", text)
            events.append(Event(
                title=f"EC | {title}",
                start=start,
                end=end,
                all_day=True,
                location="(See source)",
                description=f"Source: {url}",
                url=url,
                source="EC",
                priority="A",
            ))

    return events

def build_ics(events: List[Event]) -> str:
    # Minimal, Google-friendly ICS with TZID Europe/Brussels
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")

    lines: List[str] = []
    lines += [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//TK Brussels Agenda//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Brussels Agenda (AUTO)",
        "X-WR-TIMEZONE:Europe/Brussels",
        "BEGIN:VTIMEZONE",
        "TZID:Europe/Brussels",
        "BEGIN:DAYLIGHT",
        "TZOFFSETFROM:+0100",
        "TZOFFSETTO:+0200",
        "TZNAME:CEST",
        "DTSTART:19700329T020000",
        "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU",
        "END:DAYLIGHT",
        "BEGIN:STANDARD",
        "TZOFFSETFROM:+0200",
        "TZOFFSETTO:+0100",
        "TZNAME:CET",
        "DTSTART:19701025T030000",
        "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU",
        "END:STANDARD",
        "END:VTIMEZONE",
    ]

    stamp = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    for idx, e in enumerate(sorted(events, key=lambda x: x.start)):
        uid = f"{abs(hash((e.title, e.start.isoformat(), e.url)))}-{idx}@tkohn123"
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{uid}")
        lines.append(f"DTSTAMP:{stamp}")
        lines.append(f"SUMMARY:{esc(e.title)}")
        if e.all_day:
            d0 = e.start.date().strftime("%Y%m%d")
            d1 = e.end.date().strftime("%Y%m%d")
            lines.append(f"DTSTART;VALUE=DATE:{d0}")
            lines.append(f"DTEND;VALUE=DATE:{d1}")
        else:
            lines.append(f"DTSTART;TZID=Europe/Brussels:{e.start.strftime('%Y%m%dT%H%M%S')}")
            lines.append(f"DTEND;TZID=Europe/Brussels:{e.end.strftime('%Y%m%dT%H%M%S')}")
        if e.location:
            lines.append(f"LOCATION:{esc(e.location)}")
        desc = f"[{e.priority}] {e.description}"
        lines.append(f"DESCRIPTION:{esc(desc)}")
        if e.url:
            lines.append(f"URL:{e.url}")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    # iCal recommends CRLF; GitHub/Google are fine with LF but we’ll be proper:
    return "\r\n".join(lines) + "\r\n"

def write_csv(events: List[Event], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["priority", "start", "end", "all_day", "title", "source", "location", "url"])
        for e in sorted(events, key=lambda x: x.start):
            w.writerow([
                e.priority,
                e.start.isoformat(),
                e.end.isoformat(),
                "1" if e.all_day else "0",
                e.title,
                e.source,
                e.location,
                e.url,
            ])
def write_markdown(events, path="index.md"):
    lines = []
    today = now_brussels().strftime("%d %B %Y")
    lines.append(f"# Brussels Agenda (Rolling 14 Days)")
    lines.append(f"_Generated: {today} (Europe/Brussels)_")
    lines.append("")
    
    # Group by date
    events_sorted = sorted(events, key=lambda e: e.start)
    current_date = None
    
    for e in events_sorted:
        date_str = e.start.strftime("%A, %d %B %Y")
        if date_str != current_date:
            lines.append(f"## {date_str}")
            lines.append("")
            current_date = date_str
        
        if e.all_day:
            time_part = "All day"
        else:
            time_part = f"{e.start.strftime('%H:%M')}–{e.end.strftime('%H:%M')}"
        
        lines.append(f"- **{time_part}** — {e.title}")
        lines.append(f"  - Source: {e.url}")
        lines.append("")
    
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        
def main() -> int:
    start, end = date_window()
    all_events: List[Event] = []
    all_events += parse_consilium_meetings()
    all_events += parse_euco_president_calendar()
    all_events += parse_ep_weekly_agenda()
    all_events += parse_commission_calendar_items()

    # TODO: add NATO + EEAS + EBS scrapers as you iterate (kept out initially for reliability)

    # Window filter
    events = [e for e in all_events if in_window(e, start, end)]

    # De-dupe (simple)
    seen = set()
    deduped: List[Event] = []
    for e in events:
        key = (norm(e.title), e.start.date(), e.url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(e)

    ics = build_ics(deduped)
    with open("brussels.ics", "w", encoding="utf-8", newline="\n") as f:
        f.write(ics)

    write_csv(deduped, "brussels.csv")
    write_markdown(deduped, "index.md")
    write_markdown(deduped, "brussels.md")
    return 0
    

if __name__ == "__main__":
    sys.exit(main())
