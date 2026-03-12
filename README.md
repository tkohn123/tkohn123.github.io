# Brussels Policy & Institutional Calendar

An automatically generated calendar tracking key meetings, events, and institutional activity in Brussels — including EU institutions, Council configurations, Commission events, Parliament sessions, and other relevant policy moments.

🔗 Live site: [https://tkohn123.github.io/tkohn123.github.io](https://tkohn123.github.io/tkohn123.github.io)

---

## Overview

This project aggregates publicly available information from EU institutional websites and publishes a structured, unified calendar via GitHub Pages.

The goal is to:

* Provide a single view of major Brussels policy events
* Make institutional schedules easier to track
* Offer a lightweight, transparent, reproducible aggregation pipeline
* Enable reuse of structured event data

The calendar is rebuilt automatically using Python scripts and deployed via GitHub Actions.

---

## Architecture

### 1. Data Sources

The project pulls event data from publicly available institutional pages, such as:

* European Council / Council of the EU (Consilium)
* European Commission
* European Parliament
* Other relevant institutional or policy calendars

All data is scraped or parsed from public sources.

### 2. Build Pipeline

The main build logic lives in:

```
scripts/build_calendar.py
```

The pipeline:

1. Fetches source pages
2. Parses meeting/event data
3. Normalizes event structure
4. Merges events into a unified dataset
5. Outputs structured files used by the frontend

### 3. Deployment

* GitHub Actions runs the build script
* Generated output is committed or published
* GitHub Pages serves the static site

---

## Repository Structure

```
.
├── scripts/
│   └── build_calendar.py
├── docs/ or site files
├── .github/workflows/
│   └── deploy.yml
└── README.md
```

*(Structure may evolve as the project grows.)*

---

## Local Development

### 1. Clone the repository

```bash
git clone https://github.com/tkohn123/tkohn123.github.io.git
cd tkohn123.github.io
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

If no `requirements.txt` exists yet, typical dependencies include:

* `requests`
* `beautifulsoup4`
* `lxml`
* `python-dateutil`

### 3. Run the build script

```bash
python scripts/build_calendar.py
```

This will:

* Fetch institutional data
* Parse events
* Generate updated calendar files

---

## Handling Scraping Errors (e.g., 403)

Some institutional websites may:

* Block automated requests
* Require headers (User-Agent)
* Rate-limit traffic

If you encounter:

```
requests.exceptions.HTTPError: 403
```

Consider:

* Adding a realistic `User-Agent` header
* Adding request delays
* Using session headers
* Checking whether the target page changed structure

Example:

```python
headers = {
    "User-Agent": "Mozilla/5.0 (compatible; BrusselsCalendarBot/1.0)"
}
r = requests.get(url, headers=headers)
```

Always ensure compliance with each website’s terms of use.

---

## Data Model (Conceptual)

Each event typically includes:

* `title`
* `institution`
* `date`
* `start_time` (if available)
* `location` (if available)
* `source_url`
* `category`

Events are normalized into a unified internal schema before publication.

---

## Roadmap

Potential future improvements:

* ICS export
* Filtering by institution
* API endpoint for structured access
* Historical archive view
* Change tracking for rescheduled meetings
* Alerting for newly added high-level meetings

---

## Disclaimer

This project:

* Is not affiliated with any EU institution
* Uses publicly available information
* May contain parsing errors if source websites change

Always verify important meeting details directly with the official source.

---

## License

MIT License (or specify your preferred license)

---

## Contributing

Contributions are welcome. If institutional page structures change or new sources should be added:

1. Open an issue
2. Submit a pull request
3. Include sample URLs and expected structured output

---

## Author

Created and maintained by @tkohn123

---

If you use or reference this calendar in research, media, or policy work, attribution is appreciated.
