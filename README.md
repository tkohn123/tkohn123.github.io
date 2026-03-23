# Brussels Policy & Institutional Calendar

An automatically generated, Brussels-centered calendar tracking key EU institutional meetings, agendas, and public-facing schedule items.

🔗 Live site: [https://tkohn123.github.io](https://tkohn123.github.io)

---

## Overview

This project aggregates publicly available information from EU institutional websites and publishes a structured rolling calendar via GitHub Pages.

Current sources:

* Council of the EU / European Council meeting calendar
* President of the European Council schedule
* European Parliament weekly agenda
* European Commission calendar items for the President and Commissioners

The goal is to:

* Provide a single view of major Brussels policy events
* Make institutional schedules easier to track
* Offer a lightweight, transparent, reproducible aggregation pipeline
* Publish reusable structured data files alongside the web view

---

## Outputs

Each build generates:

* `index.html` — human-readable agenda view
* `brussels.csv` — flat export
* `brussels.json` — structured export
* `brussels.ics` — calendar subscription file

The build refuses to overwrite the published files if it generates zero events.

---

## Architecture

### Build logic

Main script:

```text
scripts/build_calendar.py
```

The pipeline:

1. Fetches source pages
2. Parses event data from each source
3. Normalizes fields into one schema
4. Deduplicates overlapping entries
5. Writes HTML, CSV, JSON, and ICS outputs

### Deployment

GitHub Actions runs the build and commits updated generated files back to `main`.

Workflow file:

```text
.github/workflows/brussels.yml
```

---

## Repository Structure

```text
.
├── .github/
│   └── workflows/
│       └── brussels.yml
├── scripts/
│   └── build_calendar.py
├── brussels.csv
├── brussels.ics
├── brussels.json
├── index.html
├── requirements.txt
└── README.md
```

---

## Local Development

Clone the repo and install dependencies:

```bash
git clone https://github.com/tkohn123/tkohn123.github.io.git
cd tkohn123.github.io
pip install -r requirements.txt
```

Run the build:

```bash
python scripts/build_calendar.py
```

That will regenerate the site and export files in the repository root.

---

## Notes on scraping reliability

Institutional pages change structure over time and may occasionally block or rate-limit requests. If the build stops producing events:

* check whether a source page changed layout
* confirm the request headers still work
* inspect whether date or location formats changed
* run the script locally before re-enabling scheduled deploys

This project uses only publicly available information, but important meeting details should always be verified against the official source page.

---

## Disclaimer

This project is not affiliated with any EU institution and may contain parsing errors if source websites change.

---

## Author

Created and maintained by @tkohn123.
