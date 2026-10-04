"""Run the dashboard locally: `python run.py` (opens http://127.0.0.1:5057 in your browser)."""
import os
import threading
import webbrowser

from future_week_adjustment.app import app, DATA_DIR

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5057))
    url = f"http://127.0.0.1:{port}/"
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"Dashboard running at {url}")
    print(f"Data folder: {DATA_DIR}")
    app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)
