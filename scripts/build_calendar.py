#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import html
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Iterator, Optional
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

BRUSSELS = ZoneInfo("Europe/Brussels")
ROLLING_DAYS = 30
REQUEST_TIMEOUT = 30
USER_AGENT = (
    "Mozilla/5.0 (compatible; BrusselsAgendaBot/1.1; "
    "+https://tkohn123.github.io/)"
)

MONTHS = {
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12,
}

MONTHS_SHORT = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}

DAY_NAMES = {
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
}

EP_SECTION_NAMES = {
    "Plenary session",
    "President's agenda",
    "Conference Of Presidents",
    "Press conferences",
    "Conciliation/Trialogue",
    "Parliamentary committees",
    "Delegations",
    "Public hearings",
    "Special events",
    "Official visits",
    "Formal sittings",
}

GENERIC_LINES = {
    "Type of event",
    "Filter",
    "Filter by",
    "All",
    "Debate",
    "Debates",
    "Joint Public Hearing",
    "Public hearing",
    "VOTES followed by explanations of votes",
    "Votes followed by explanations of votes",
    "No event for this day",
    "Change",
    "Loading",
    "Calendar items are organised in chronological order.",
    "Upcoming and ongoing",
    "Past",
    "Status",
    "Keywords",
    "Date",
    "End Date",
    "Commissioner",
    "Search Clear filters",
}

LOCAL_COMMISSION_PLACES = {"brussels", "bruxelles", "strasbourg", "luxembourg"}

EUCO_LOCAL_TIMEZONES = {
    "amsterdam": "Europe/Amsterdam",
    "azerbaijan": "Asia/Baku",
    "baku": "Asia/Baku",
    "belgium": "Europe/Brussels",
    "berlin": "Europe/Berlin",
    "brussels": "Europe/Brussels",
    "copenhagen": "Europe/Copenhagen",
    "france": "Europe/Paris",
    "germany": "Europe/Berlin",
    "hamburg": "Europe/Berlin",
    "lisbon": "Europe/Lisbon",
    "luxembourg": "Europe/Luxembourg",
    "madrid": "Europe/Madrid",
    "paris": "Europe/Paris",
    "poland": "Europe/Warsaw",
    "porto": "Europe/Lisbon",
    "portugal": "Europe/Lisbon",
    "rome": "Europe/Rome",
    "spain": "Europe/Madrid",
    "stockholm": "Europe/Stockholm",
    "sweden": "Europe/Stockholm",
    "the hague": "Europe/Amsterdam",
    "warsaw": "Europe/Warsaw",
}

PRIORITY_KEYWORDS = {
    "european council",
    "euro summit",
    "eurogroup",
    "ecofin",
    "economic and financial affairs council",
    "foreign affairs council",
    "tripartite social summit",
    "president metsola",
    "metsola",
    "ursula von der leyen",
    "von der leyen",
    "costa",
    "kallas",
    "kubilius",
    "virkkunen",
    "dombrovskis",
    "ribera",
    "šefčovič",
    "sefcovic",
    "sejourne",
    "séjourné",
}

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": USER_AGENT,
    "Accept-Language": "en",
})


@dataclass(frozen=True)
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
    category: str

    def to_json(self) -> dict[str, object]:
        payload = asdict(self)
        payload["start"] = self.start.isoformat()
        payload["end"] = self.end.isoformat()
        return payload


def now_brussels() -> dt.datetime:
    return dt.datetime.now(tz=BRUSSELS)


def date_window() -> tuple[dt.datetime, dt.datetime]:
    start = now_brussels().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + dt.timedelta(days=ROLLING_DAYS)
    return start, end


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).lower()


def priority_from_text(*parts: str) -> str:
    joined = norm(" ".join(part for part in parts if part))
    return "A" if any(keyword in joined for keyword in PRIORITY_KEYWORDS) else "B"


def in_window(event: Event, start: dt.datetime, end: dt.datetime) -> bool:
    return not (event.end <= start or event.start >= end)


def fetch_text(url: str) -> Optional[str]:
    try:
        response = SESSION.get(url, timeout=REQUEST_TIMEOUT)
        if response.status_code != 200:
            print(f"[WARN] {url} returned {response.status_code}")
            return None
        return response.text
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] Failed to fetch {url}: {exc}")
        return None


def soup_lines(html_text: str) -> list[str]:
    soup = BeautifulSoup(html_text, "html.parser")
    return [line.strip() for line in soup.get_text("\n", strip=True).splitlines() if line.strip()]


def add_hours(base_date: dt.date, clock: str, hours: int = 1) -> tuple[dt.datetime, dt.datetime]:
    hour, minute = map(int, clock.split(":"))
    start = dt.datetime(base_date.year, base_date.month, base_date.day, hour, minute, tzinfo=BRUSSELS)
    return start, start + dt.timedelta(hours=hours)


def add_hours_in_timezone(
    base_date: dt.date,
    clock: str,
    source_tz: ZoneInfo,
    hours: int = 1,
) -> tuple[dt.datetime, dt.datetime]:
    hour, minute = map(int, clock.split(":"))
    start_local = dt.datetime(
        base_date.year,
        base_date.month,
        base_date.day,
        hour,
        minute,
        tzinfo=source_tz,
    )
    end_local = start_local + dt.timedelta(hours=hours)
    return start_local.astimezone(BRUSSELS), end_local.astimezone(BRUSSELS)


def resolve_euco_timezone(location: str) -> ZoneInfo:
    lowered = norm(location)
    for keyword, tz_name in EUCO_LOCAL_TIMEZONES.items():
        if keyword in lowered:
            return ZoneInfo(tz_name)
    return BRUSSELS


def all_day_range(start_date: dt.date, end_date: Optional[dt.date] = None) -> tuple[dt.datetime, dt.datetime]:
    end_actual = end_date or start_date
    start_dt = dt.datetime(start_date.year, start_date.month, start_date.day, tzinfo=BRUSSELS)
    end_dt = dt.datetime(end_actual.year, end_actual.month, end_actual.day, tzinfo=BRUSSELS) + dt.timedelta(days=1)
    return start_dt, end_dt


def is_footer_or_noise(line: str) -> bool:
    lowered = norm(line)
    if not lowered:
        return True
    noise_prefixes = (
        "go to the first page",
        "go to the previous page",
        "go to the next page",
        "go to the last page",
        "subscribe to meetings",
        "last review:",
        "about the secretariat",
        "about this site",
        "corporate policies",
        "contact",
        "email subscription",
        "follow us",
        "share this page",
        "see all",
        "view other websites",
        "menu",
        "current language",
        "sign up to receive",
        "this site is managed by:",
        "directorate-general for communication",
        "created and maintained",
    )
    if lowered in {norm(item) for item in GENERIC_LINES}:
        return True
    if lowered.startswith(noise_prefixes):
        return True
    if re.fullmatch(r"\d+", line):
        return True
    return False


def parse_consilium_dates_from_href(href: str) -> Optional[tuple[dt.date, dt.date]]:
    match = re.search(
        r"/en/meetings/[^/]+/(\d{4})/(\d{2})/(\d{2})(?:-(\d{2}))?/?$",
        href,
    )
    if match:
        year, month, day_start, day_end = match.groups()
        start_date = dt.date(int(year), int(month), int(day_start))
        end_date = dt.date(int(year), int(month), int(day_end or day_start))
        return start_date, end_date

    match = re.search(
        r"/(\d{4})/(\d{2})/(\d{2})-(\d{2})/(\d{2})/?$",
        href,
    )
    if match:
        year, start_month, start_day, end_month, end_day = match.groups()
        start_date = dt.date(int(year), int(start_month), int(start_day))
        end_date = dt.date(int(year), int(end_month), int(end_day))
        return start_date, end_date

    return None


def parse_consilium_meetings() -> list[Event]:
    url = "https://www.consilium.europa.eu/en/meetings/calendar/"
    html_text = fetch_text(url)
    if not html_text:
        return []

    soup = BeautifulSoup(html_text, "html.parser")
    seen_urls: set[str] = set()
    events: list[Event] = []
    start_window, end_window = date_window()

    for anchor in soup.find_all("a", href=True):
        href = urljoin(url, anchor.get("href", ""))
        if href in seen_urls:
            continue
        if "/en/meetings/" not in href:
            continue
        if not re.search(r"/\d{4}/\d{2}/", href):
            continue

        date_pair = parse_consilium_dates_from_href(href)
        if not date_pair:
            continue

        title = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()
        if not title or title.lower() in {"see more meetings", "future meetings", "past meetings"}:
            continue

        start_date, end_date = date_pair
        start_dt, end_dt = all_day_range(start_date, end_date)
        event = Event(
            title=f"CONSILIUM | {title}",
            start=start_dt,
            end=end_dt,
            all_day=True,
            location="Council of the EU / European Council",
            description="Council and European Council meeting calendar",
            url=href,
            source="CONSILIUM",
            priority=priority_from_text(title),
            category="Council meeting",
        )
        if in_window(event, start_window, end_window):
            events.append(event)
            seen_urls.add(href)

    return events


def parse_euco_president_calendar() -> list[Event]:
    url = "https://www.consilium.europa.eu/en/european-council/president/calendar/"
    html_text = fetch_text(url)
    if not html_text:
        return []

    lines = soup_lines(html_text)
    date_re = re.compile(r"^(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})$")
    weekday_re = re.compile(r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+")
    timed_re = re.compile(r"^(\d{1,2}:\d{2})\s+(.+)$")
    location_re = re.compile(r"^[A-Z][^\n]+,\s*[^\n]+(?:\s*\(local time\))?$")

    events: list[Event] = []
    current_date: Optional[dt.date] = None
    current_location = ""
    current_location_is_local_time = False
    start_window, end_window = date_window()

    for raw_line in lines:
        line = raw_line.replace("\xa0", " ").strip()
        if not line or is_footer_or_noise(line):
            continue

        date_match = date_re.match(line)
        if date_match:
            day, month_name, year = date_match.groups()
            current_date = dt.date(int(year), MONTHS[month_name], int(day))
            current_location = ""
            current_location_is_local_time = False
            continue

        if current_date is None:
            continue
        if weekday_re.match(line):
            continue
        if line == "European Council":
            continue
        if line.startswith("*"):
            continue
        if line.startswith("Page "):
            continue

        if location_re.match(line) and not timed_re.match(line):
            current_location_is_local_time = "(local time)" in line.lower()
            current_location = re.sub(r"\s*\(local time\)\s*$", "", line, flags=re.IGNORECASE).strip()
            continue

        timed_match = timed_re.match(line)
        if timed_match:
            clock, title = timed_match.groups()
            if current_location_is_local_time and current_location:
                start_dt, end_dt = add_hours_in_timezone(
                    current_date,
                    clock,
                    resolve_euco_timezone(current_location),
                    1,
                )
                description = (
                    "President of the European Council schedule "
                    "(time converted from local time to Europe/Brussels)"
                )
            else:
                start_dt, end_dt = add_hours(current_date, clock, 1)
                description = "President of the European Council schedule"
            event = Event(
                title=f"EUCO President | {title.strip()}",
                start=start_dt,
                end=end_dt,
                all_day=False,
                location=current_location,
                description=description,
                url=url,
                source="EUCO PRESIDENT",
                priority=priority_from_text(title),
                category="President schedule",
            )
            if in_window(event, start_window, end_window):
                events.append(event)
            continue

        title = line
        if title and not title.startswith("[") and not title.startswith("http"):
            start_dt, end_dt = all_day_range(current_date)
            event = Event(
                title=f"EUCO President | {title}",
                start=start_dt,
                end=end_dt,
                all_day=True,
                location=current_location,
                description="President of the European Council schedule (time not specified)",
                url=url,
                source="EUCO PRESIDENT",
                priority=priority_from_text(title),
                category="President schedule",
            )
            if in_window(event, start_window, end_window):
                events.append(event)

    return events


def parse_ep_date(line: str) -> Optional[dt.date]:
    match = re.match(
        r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+(\d{2})-(\d{2})-(\d{4})$",
        line,
    )
    if not match:
        return None
    _weekday, day, month, year = match.groups()
    return dt.date(int(year), int(month), int(day))


EP_LOCATION_RE = re.compile(r"^[A-Z][\wÀ-ÿ.'’-]+(?:[ -][\wÀ-ÿ.'’-]+)*,\s*[A-Z][\wÀ-ÿ.'’-]+(?:[ -][\wÀ-ÿ.'’-]+)*(?:,\s*[^,]+)?$")

EP_LOCATION_STOPWORDS = (
    "committee on",
    "joint meeting",
    "president ",
    "meeting with",
    "meeting of",
    "conference",
    "plenary",
    "debate",
    "hearing",
    "session",
    "report:",
    "website of",
)


def looks_like_location(line: str) -> bool:
    lowered = norm(line)
    if any(stopword in lowered for stopword in EP_LOCATION_STOPWORDS):
        return False
    if any(place in lowered for place in ("brussels", "strasbourg", "luxembourg")):
        return True
    return bool(EP_LOCATION_RE.match(line.strip()))


def ep_is_control_line(line: str) -> bool:
    lowered = norm(line)
    if not lowered:
        return True
    if line in EP_SECTION_NAMES:
        return True
    if parse_ep_date(line):
        return True
    if lowered.startswith("choose a type of event"):
        return True
    if lowered.startswith("select a committee"):
        return True
    if lowered.startswith("filter by committee"):
        return True
    if lowered.startswith("watch webstreaming"):
        return True
    if lowered.startswith("catch up via video on demand"):
        return True
    if lowered.startswith("procedure file:"):
        return True
    if lowered.startswith("report:"):
        return True
    if lowered.startswith("website of the committee"):
        return True
    if lowered.startswith("website of"):
        return True
    if lowered.startswith("select this day"):
        return True
    if lowered.startswith("mon ") or lowered.startswith("tue ") or lowered.startswith("wed ") or lowered.startswith("thu ") or lowered.startswith("fri "):
        return True
    if lowered == "###":
        return True
    return False


def choose_ep_title(section: str, block_lines: list[str]) -> str:
    cleaned = [line for line in block_lines if line and not ep_is_control_line(line)]
    if not cleaned:
        return section

    if section == "Parliamentary committees":
        acronyms = [line for line in cleaned[:3] if re.fullmatch(r"[A-Z]{3,6}", line)]
        names = [line for line in cleaned if "Committee on" in line or line.startswith("Joint Meeting")]
        topic = next(
            (
                line.lstrip("* ")
                for line in cleaned
                if len(line) > 25
                and "Committee on" not in line
                and not re.fullmatch(r"[A-Z]{3,6}", line)
                and not looks_like_location(line)
                and line not in {"Debate", "Debates", "Joint Public Hearing"}
            ),
            "",
        )
        if names:
            prefix = names[0]
        elif acronyms:
            prefix = "/".join(acronyms)
        else:
            prefix = cleaned[0]
        if topic:
            return f"{prefix} — {topic}"
        return prefix

    if section == "Plenary session":
        for line in cleaned:
            if line in {"Brussels", "Strasbourg", "Luxembourg", "Debates", "Debate", "VOTES followed by explanations of votes", "Votes followed by explanations of votes"}:
                continue
            if not re.fullmatch(r"[A-Z]{3,6}", line):
                return f"Plenary — {line.lstrip('* ')}"
        return "Plenary session"

    for line in cleaned:
        if line in {"Debates", "Debate"}:
            continue
        if not looks_like_location(line):
            return line.lstrip("* ")

    return cleaned[0].lstrip("* ")


def choose_ep_location(block_lines: list[str], fallback: str = "European Parliament") -> str:
    for line in block_lines:
        if looks_like_location(line):
            return line
    return fallback


def parse_ep_weekly_agenda() -> list[Event]:
    url = "https://www.europarl.europa.eu/news/en/agenda/weekly-agenda"
    html_text = fetch_text(url)
    if not html_text:
        return []

    lines = soup_lines(html_text)
    events: list[Event] = []
    current_date: Optional[dt.date] = None
    current_section = ""
    current_section_location = ""
    start_window, end_window = date_window()
    index = 0

    range_re = re.compile(r"^(?:\d+\.\s*)?(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})$")
    inline_re = re.compile(r"^(\d{1,2}:\d{2})\s+(.+)$")

    while index < len(lines):
        line = lines[index].strip()
        maybe_date = parse_ep_date(line)
        if maybe_date:
            current_date = maybe_date
            current_section = ""
            current_section_location = ""
            index += 1
            continue

        if line in EP_SECTION_NAMES:
            current_section = line
            current_section_location = ""
            index += 1
            continue

        if current_date is None or current_date < start_window.date() or current_date >= end_window.date():
            index += 1
            continue

        if current_section and looks_like_location(line) and not range_re.match(line) and not inline_re.match(line):
            current_section_location = line
            index += 1
            continue

        range_match = range_re.match(line)
        if range_match and current_section:
            start_clock, end_clock = range_match.groups()
            block: list[str] = []
            lookahead = index + 1
            while lookahead < len(lines):
                candidate = lines[lookahead].strip()
                if parse_ep_date(candidate) or candidate in EP_SECTION_NAMES or range_re.match(candidate) or inline_re.match(candidate):
                    break
                block.append(candidate)
                lookahead += 1
            start_hour, start_minute = map(int, start_clock.split(":"))
            end_hour, end_minute = map(int, end_clock.split(":"))
            start_dt = dt.datetime(current_date.year, current_date.month, current_date.day, start_hour, start_minute, tzinfo=BRUSSELS)
            end_dt = dt.datetime(current_date.year, current_date.month, current_date.day, end_hour, end_minute, tzinfo=BRUSSELS)
            title = choose_ep_title(current_section, block)
            location = choose_ep_location(block, fallback=current_section_location or "European Parliament")
            event = Event(
                title=f"EP | {title}",
                start=start_dt,
                end=end_dt,
                all_day=False,
                location=location,
                description=f"European Parliament weekly agenda — {current_section}",
                url=url,
                source="EP",
                priority=priority_from_text(title, current_section),
                category=current_section,
            )
            events.append(event)
            index = lookahead
            continue

        inline_match = inline_re.match(line)
        if inline_match and current_section:
            start_clock, title = inline_match.groups()
            start_dt, end_dt = add_hours(current_date, start_clock, 1)
            event = Event(
                title=f"EP | {title}",
                start=start_dt,
                end=end_dt,
                all_day=False,
                location=current_section_location or "European Parliament",
                description=f"European Parliament weekly agenda — {current_section}",
                url=url,
                source="EP",
                priority=priority_from_text(title, current_section),
                category=current_section,
            )
            events.append(event)
            index += 1
            continue

        index += 1

    return events


def parse_commission_date(line: str) -> Optional[tuple[dt.date, dt.date]]:
    match = re.match(r"^(\d{1,2})(?:-(\d{1,2}))?\s+([A-Za-z]{3})\s+(\d{4})$", line)
    if not match:
        return None
    day_start, day_end, month_short, year = match.groups()
    month = MONTHS_SHORT.get(month_short)
    if month is None:
        return None
    start_date = dt.date(int(year), month, int(day_start))
    end_date = dt.date(int(year), month, int(day_end or day_start))
    return start_date, end_date


def commission_location_allowed(location: str) -> bool:
    lowered = norm(location)
    return any(place in lowered for place in LOCAL_COMMISSION_PLACES)


def iter_commission_pages() -> Iterator[str]:
    base_url = "https://commission.europa.eu/about/organisation/college-commissioners/calendar-items-president-and-commissioners_en"
    first = fetch_text(base_url)
    if first:
        yield first
    for page in range(1, 9):
        paged = fetch_text(f"{base_url}?page={page}")
        if not paged:
            break
        yield paged


def parse_commission_calendar() -> list[Event]:
    base_url = "https://commission.europa.eu/about/organisation/college-commissioners/calendar-items-president-and-commissioners_en"
    events: list[Event] = []
    start_window, end_window = date_window()

    for html_text in iter_commission_pages():
        lines = soup_lines(html_text)
        page_events: list[Event] = []
        index = 0
        page_min_date: Optional[dt.date] = None
        page_max_date: Optional[dt.date] = None

        while index < len(lines):
            line = lines[index].strip()
            date_pair = parse_commission_date(line)
            if not date_pair:
                index += 1
                continue

            start_date, end_date = date_pair
            page_min_date = start_date if page_min_date is None else min(page_min_date, start_date)
            page_max_date = end_date if page_max_date is None else max(page_max_date, end_date)

            title = ""
            location = ""
            if index + 1 < len(lines):
                title = lines[index + 1].strip().lstrip("* ")
            if index + 2 < len(lines):
                location = lines[index + 2].strip().lstrip("* ")

            if title and location and commission_location_allowed(location):
                start_dt, end_dt = all_day_range(start_date, end_date)
                event = Event(
                    title=f"COMMISSION | {title}",
                    start=start_dt,
                    end=end_dt,
                    all_day=True,
                    location=location,
                    description="European Commission calendar items of the President and Commissioners",
                    url=base_url,
                    source="COMMISSION",
                    priority=priority_from_text(title, location),
                    category="Commission calendar",
                )
                if in_window(event, start_window, end_window):
                    page_events.append(event)

            index += 1

        events.extend(page_events)
        if page_min_date and page_min_date >= end_window.date():
            break
        if page_max_date and page_max_date >= end_window.date() and not page_events:
            break

    return events


def dedupe_events(events: Iterable[Event]) -> list[Event]:
    deduped: list[Event] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for event in sorted(events, key=lambda item: (item.start, item.source, item.title)):
        key = (
            event.source,
            norm(event.title),
            event.start.isoformat(),
            norm(event.location),
            event.url,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(event)
    return deduped


def build_ics(events: Iterable[Event]) -> str:
    def esc(value: str) -> str:
        return (
            value.replace("\\", "\\\\")
            .replace("\n", "\\n")
            .replace(",", "\\,")
            .replace(";", "\\;")
        )

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//TK Brussels Agenda//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Brussels Agenda",
        "X-WR-TIMEZONE:Europe/Brussels",
    ]

    stamp = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    for event in sorted(events, key=lambda item: (item.start, item.source, item.title)):
        unique = hashlib.md5(
            f"{event.source}|{event.title}|{event.start.isoformat()}|{event.url}".encode("utf-8")
        ).hexdigest()
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{unique}@tkohn123")
        lines.append(f"DTSTAMP:{stamp}")
        lines.append(f"SUMMARY:{esc(event.title)}")
        if event.all_day:
            lines.append(f"DTSTART;VALUE=DATE:{event.start.strftime('%Y%m%d')}")
            lines.append(f"DTEND;VALUE=DATE:{event.end.strftime('%Y%m%d')}")
        else:
            lines.append(
                f"DTSTART;TZID=Europe/Brussels:{event.start.strftime('%Y%m%dT%H%M%S')}"
            )
            lines.append(
                f"DTEND;TZID=Europe/Brussels:{event.end.strftime('%Y%m%dT%H%M%S')}"
            )
        if event.location:
            lines.append(f"LOCATION:{esc(event.location)}")
        if event.url:
            lines.append(f"URL:{esc(event.url)}")
        description = event.description
        if event.url:
            description = f"{description}\nSource: {event.url}"
        lines.append(f"DESCRIPTION:{esc(description)}")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def write_csv(events: Iterable[Event], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "priority",
            "source",
            "category",
            "start",
            "end",
            "all_day",
            "title",
            "location",
            "url",
        ])
        for event in sorted(events, key=lambda item: (item.start, item.source, item.title)):
            writer.writerow([
                event.priority,
                event.source,
                event.category,
                event.start.isoformat(),
                event.end.isoformat(),
                str(event.all_day).lower(),
                event.title,
                event.location,
                event.url,
            ])


def write_json(events: Iterable[Event], path: Path) -> None:
    payload = [event.to_json() for event in sorted(events, key=lambda item: (item.start, item.source, item.title))]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def html_event_card(event: Event) -> str:
    time_label = "All day" if event.all_day else f"{event.start.strftime('%H:%M')}–{event.end.strftime('%H:%M')}"
    return "".join(
        [
            f"<article class='event-card' data-source='{html.escape(event.source)}' data-priority='{html.escape(event.priority)}'>",
            f"<div class='time'>{html.escape(time_label)}</div>",
            "<div class='details'>",
            f"<div class='meta'><span class='badge badge-source'>{html.escape(event.source)}</span><span class='badge badge-priority'>{html.escape(event.priority)}</span></div>",
            f"<h3>{html.escape(event.title)}</h3>",
            f"<p class='category'>{html.escape(event.category)}</p>",
            f"<p class='location'>{html.escape(event.location or 'Location TBD')}</p>",
            f"<p class='link'><a href='{html.escape(event.url, quote=True)}' target='_blank' rel='noopener'>Source</a></p>",
            "</div>",
            "</article>",
        ]
    )


def write_html(events: list[Event], path: Path) -> None:
    start_window, end_window = date_window()
    by_day: dict[str, list[Event]] = {}
    for event in sorted(events, key=lambda item: (item.start, item.source, item.title)):
        by_day.setdefault(event.start.strftime("%A, %d %B %Y"), []).append(event)

    source_counts: dict[str, int] = {}
    for event in events:
        source_counts[event.source] = source_counts.get(event.source, 0) + 1

    day_sections: list[str] = []
    for label, day_events in by_day.items():
        cards = "\n".join(html_event_card(event) for event in day_events)
        day_sections.append(f"<section class='day'><h2>{html.escape(label)}</h2>{cards}</section>")

    sources_text = " · ".join(
        f"{html.escape(source)}: {count}" for source, count in sorted(source_counts.items())
    )

    page = f"""<!DOCTYPE html>
<html lang='en'>
<head>
  <meta charset='utf-8'>
  <meta name='viewport' content='width=device-width, initial-scale=1'>
  <title>Brussels Agenda</title>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #0b1020;
      --card: #131a2e;
      --muted: #a7b1c6;
      --text: #eef3ff;
      --line: #28324a;
      --accent: #87b2ff;
    }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.45;
    }}
    main {{
      max-width: 980px;
      margin: 0 auto;
      padding: 32px 20px 64px;
    }}
    header {{ margin-bottom: 24px; }}
    h1 {{ margin: 0 0 8px; font-size: 2.2rem; }}
    p {{ margin: 0 0 10px; }}
    .lede {{ color: var(--muted); max-width: 72ch; }}
    .toolbar {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin: 18px 0 8px;
    }}
    .toolbar a, .toolbar button {{
      border: 1px solid var(--line);
      background: var(--card);
      color: var(--text);
      padding: 10px 14px;
      border-radius: 999px;
      text-decoration: none;
      cursor: pointer;
      font: inherit;
    }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin: 20px 0 28px;
    }}
    .summary-card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 14px 16px;
    }}
    .summary-card strong {{ display: block; font-size: 1.45rem; margin-bottom: 4px; }}
    .day {{ margin: 28px 0; }}
    .day h2 {{
      position: sticky;
      top: 0;
      background: var(--bg);
      padding: 10px 0;
      margin: 0 0 14px;
      border-bottom: 1px solid var(--line);
    }}
    .event-card {{
      display: grid;
      grid-template-columns: 120px 1fr;
      gap: 16px;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 16px;
      margin: 0 0 12px;
    }}
    .time {{ font-weight: 700; color: var(--accent); }}
    .details h3 {{ margin: 6px 0 6px; font-size: 1.05rem; }}
    .details p {{ margin: 0 0 6px; color: var(--muted); }}
    .meta {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .badge {{
      display: inline-block;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 3px 8px;
      font-size: 0.8rem;
      color: var(--muted);
    }}
    .filters {{ display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 16px; }}
    .filters select, .filters input {{
      background: var(--card);
      color: var(--text);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px 12px;
      font: inherit;
    }}
    a {{ color: var(--accent); }}
    footer {{ margin-top: 32px; color: var(--muted); font-size: 0.95rem; }}
    @media (max-width: 720px) {{
      .event-card {{ grid-template-columns: 1fr; }}
      .time {{ margin-bottom: -6px; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Brussels Agenda</h1>
      <p class='lede'>A rolling {ROLLING_DAYS}-day institutional calendar covering Council meetings, the European Council President schedule, the European Parliament weekly agenda, and Brussels-facing Commission calendar items.</p>
      <div class='toolbar'>
        <a href='brussels.ics'>Subscribe (.ics)</a>
        <a href='brussels.csv'>Download CSV</a>
        <a href='brussels.json'>Download JSON</a>
      </div>
      <div class='summary'>
        <div class='summary-card'><strong>{len(events)}</strong><span>Total events</span></div>
        <div class='summary-card'><strong>{start_window.strftime('%d %b %Y')}</strong><span>Window start</span></div>
        <div class='summary-card'><strong>{(end_window - dt.timedelta(days=1)).strftime('%d %b %Y')}</strong><span>Window end</span></div>
        <div class='summary-card'><strong>{html.escape(sources_text or 'None')}</strong><span>By source</span></div>
      </div>
      <div class='filters'>
        <select id='sourceFilter'>
          <option value=''>All sources</option>
          <option value='CONSILIUM'>CONSILIUM</option>
          <option value='EUCO PRESIDENT'>EUCO PRESIDENT</option>
          <option value='EP'>EP</option>
          <option value='COMMISSION'>COMMISSION</option>
        </select>
        <select id='priorityFilter'>
          <option value=''>All priority levels</option>
          <option value='A'>Priority A</option>
          <option value='B'>Priority B</option>
        </select>
        <input id='searchBox' type='search' placeholder='Search title or location'>
      </div>
    </header>
    {''.join(day_sections) if day_sections else '<p>No events found in the current window.</p>'}
    <footer>
      <p>Generated {html.escape(now_brussels().strftime('%Y-%m-%d %H:%M %Z'))}. Always verify critical meeting details against the official source page.</p>
    </footer>
  </main>
  <script>
    const cards = Array.from(document.querySelectorAll('.event-card'));
    const sourceFilter = document.getElementById('sourceFilter');
    const priorityFilter = document.getElementById('priorityFilter');
    const searchBox = document.getElementById('searchBox');

    function applyFilters() {{
      const source = sourceFilter.value.toLowerCase();
      const priority = priorityFilter.value.toLowerCase();
      const query = searchBox.value.trim().toLowerCase();

      cards.forEach((card) => {{
        const text = card.innerText.toLowerCase();
        const sourceMatch = !source || card.dataset.source.toLowerCase() === source;
        const priorityMatch = !priority || card.dataset.priority.toLowerCase() === priority;
        const queryMatch = !query || text.includes(query);
        card.style.display = sourceMatch && priorityMatch && queryMatch ? '' : 'none';
      }});
    }}

    sourceFilter.addEventListener('change', applyFilters);
    priorityFilter.addEventListener('change', applyFilters);
    searchBox.addEventListener('input', applyFilters);
  </script>
</body>
</html>
"""
    path.write_text(page, encoding="utf-8")


def main() -> int:
    start_window, end_window = date_window()
    all_events: list[Event] = []
    all_events.extend(parse_consilium_meetings())
    all_events.extend(parse_euco_president_calendar())
    all_events.extend(parse_ep_weekly_agenda())
    all_events.extend(parse_commission_calendar())

    events = [event for event in all_events if in_window(event, start_window, end_window)]
    deduped = dedupe_events(events)
    if not deduped:
        raise SystemExit("No events generated; refusing to overwrite published files.")

    source_counts: dict[str, int] = {}
    for event in deduped:
        source_counts[event.source] = source_counts.get(event.source, 0) + 1

    root = Path.cwd()
    (root / "brussels.ics").write_text(build_ics(deduped), encoding="utf-8")
    write_csv(deduped, root / "brussels.csv")
    write_json(deduped, root / "brussels.json")
    write_html(deduped, root / "index.html")

    print(f"Wrote {len(deduped)} events")
    for source, count in sorted(source_counts.items()):
        print(f"  {source}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
