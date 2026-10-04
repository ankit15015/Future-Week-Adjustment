# Future Week Adjustment

A small web dashboard that copies **Headcount** from a *Base Layer* file (the plan) into an
*Opportunities* file (the schedule export), lets you add a **Reason** per group of rows, shows
the exact final result for review, and downloads the updated file.

It runs on your own machine (`http://127.0.0.1:5057`) and can also be deployed to Render for
teammates to try.

## Quick start

Requires Python 3.11+ (developed and tested on 3.13).

```bash
pip install -r requirements.txt
python run.py
```

`run.py` opens the dashboard in your browser. It listens on `127.0.0.1` only, so nothing is
exposed to the network.

## What it does

1. **Source** - load a Base Layer (`.xlsx`, `.xlsb`, or a screenshot/PDF read with OCR).
2. **Minimum hours / 1% rule** - if the source states Minimum Hours, confirm them and check
   the 1% rule before continuing.
3. **Destination** - load the Opportunities file (`.csv` / `.xlsx`).
4. **Match** - each row is matched to the source by weekday + workgroup + closest shift start
   time; the new Headcount comes from the source.
5. **Reason** - type a reason per workgroup or per shift type, plus a fallback.
6. **Apply & download** - review the final table (filterable), then download. The file contains
   exactly the rows shown, so filtering first gives you a filtered file.

Full walkthrough: [docs/user-guide.md](docs/user-guide.md).

## Project layout

```
.
├── future_week_adjustment/        Python package (the application)
│   ├── app.py                     Flask app: JSON API + page route
│   ├── base_layer.py              Reads the Base Layer (xlsx/xlsb/OCR) and the 1% rule
│   ├── opportunities.py           Reads/writes the Opportunities file (csv/xlsx)
│   ├── matching.py                Row matching and reason assignment
│   ├── templates/index.html       The single-page UI
│   └── static/{css,js}/           Styles and front-end logic
├── tests/                         pytest suite (synthetic data, no real files needed)
├── docs/                          User guide, architecture, deployment, handover notes
├── scripts/                       Windows helpers to share a local run via a temporary public link
├── run.py                         Local entry point (opens the browser)
├── wsgi.py                        Production entry point (gunicorn wsgi:app)
├── render.yaml                    Render.com blueprint
├── requirements.txt               Runtime dependencies
├── requirements-dev.txt           Runtime + test dependencies
└── instance/                      Created at runtime: uploads/ and output/ (git-ignored)
```

## Configuration

All optional.

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | `5057` | Port for `python run.py`. |
| `DASHBOARD_SECRET` | random per start | Flask session signing key. Set it in production so sessions survive restarts (Render generates one). |
| `DASHBOARD_DATA_DIR` | the folder that contains this project | Folder the "pick a file" dropdowns list. |

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The suite builds small synthetic Base Layer and Opportunities files, so it needs none of the real
data. It covers parsing, matching, reading/writing both file types, and the whole API flow,
including that the downloaded file matches the on-screen final table row for row.

## Documentation

| Doc | For |
| --- | --- |
| [docs/user-guide.md](docs/user-guide.md) | Using the dashboard step by step |
| [docs/architecture.md](docs/architecture.md) | How it is built, data flow, API reference, matching rules |
| [docs/deployment.md](docs/deployment.md) | Running locally, deploying to Render, sharing a local run |
| [docs/handover.md](docs/handover.md) | Current status, **known limitations**, gotchas, suggested next steps |

If you are taking this project over, start with [docs/handover.md](docs/handover.md).
