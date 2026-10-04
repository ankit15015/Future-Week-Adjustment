# Running and deploying

## Locally

```bash
pip install -r requirements.txt
python run.py
```

Opens http://127.0.0.1:5057. Use `PORT=...` to change the port.

The "pick a file" dropdowns list the data folder: by default the folder that contains this
project. Point it elsewhere with `DASHBOARD_DATA_DIR`:

```powershell
$env:DASHBOARD_DATA_DIR = "C:\path\to\files"; python run.py
```

Uploads and generated files go in `instance/uploads` and `instance/output`; both are safe to
delete at any time.

## Deploying to Render

`render.yaml` describes the service.

1. In Render choose **New + -> Blueprint** and connect this repository.
2. Apply. Render runs `pip install -r requirements.txt` and starts
   `gunicorn -w 1 --timeout 120 -b 0.0.0.0:$PORT wsgi:app` on Python 3.11.9.
3. It generates `DASHBOARD_SECRET` for you.

Things to know about the deployed copy:

- **There is no login.** Anyone with the URL can use it and can download generated files. Do not
  deploy it with real data unless access is restricted some other way.
- **Keep one worker.** Run state lives in process memory; more workers would lose users' progress
  between requests.
- The file dropdowns are empty (there is no data folder) - use **Upload file**.
- The free tier sleeps when idle (first request can take 30-60 s) and clears `instance/` on
  every redeploy.
- Render deploys the branch the service is connected to. Check which branch that is before
  merging changes here.

## Production notes

- gunicorn does not run on Windows. Locally use `python run.py`.
- Set `DASHBOARD_SECRET` to a fixed value if you want sessions to survive restarts (state itself
  does not, so the benefit is small).
- The gunicorn timeout is 120 s, which leaves room for OCR of a large PDF (the OCR model loads
  lazily on first use).

## Sharing a local run with a teammate (Windows)

Temporary public links to your machine, for quick testing. Start the dashboard first, then:

| Script | How it works |
| --- | --- |
| `scripts/share-via-cloudflare.bat` | Cloudflare quick tunnel. Needs `cloudflared.exe` placed in `scripts/` (git-ignored; download from the cloudflared releases page). |
| `scripts/share-via-ssh.ps1` | Tunnel through `localhost.run` using the Windows OpenSSH client. No download needed. |

Keep the window open while the link is in use. These links have **no authentication** either, and
they point at whatever data your dashboard can see.
