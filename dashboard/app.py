import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import requests
from datetime import datetime
from flask import Flask, render_template, jsonify, request
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

from connectors.deribit import fetch
import wheel

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

# --- View-only / share mode --------------------------------------------------
# Run a second, read-only instance (DASH_VIEW_ONLY=1 on a different DASH_PORT)
# and expose THAT one through a tunnel. It serves the same cached data but
# refuses every write + live Deribit refresh, so a shared link can't change your
# config/snapshots or burn your API rate limit. DASH_TOKEN adds a simple
# password gate (?key=TOKEN on first visit sets a cookie).
VIEW_ONLY = os.getenv('DASH_VIEW_ONLY') == '1'
DASH_TOKEN = os.getenv('DASH_TOKEN', '').strip()


@app.before_request
def _guard():
    # 1) Optional shared-link password.
    if DASH_TOKEN:
        if request.cookies.get('dash_token') == DASH_TOKEN:
            pass
        elif request.args.get('key') == DASH_TOKEN:
            request.environ['_set_token'] = True   # cookie set in after_request
        else:
            return ('Unauthorized. Append ?key=YOUR_TOKEN to the URL.', 401)
    # 2) Read-only: block writes + any live Deribit fetch.
    if VIEW_ONLY:
        if request.method != 'GET':
            return jsonify({"error": "read-only dashboard"}), 403
        if request.args.get('refresh') == '1':
            return jsonify({"error": "read-only: live refresh disabled"}), 403


@app.after_request
def _set_token_cookie(resp):
    if request.environ.get('_set_token'):
        # Persist for a week so in-page fetch() calls stay authorised.
        resp.set_cookie('dash_token', DASH_TOKEN, max_age=7 * 24 * 3600,
                        samesite='Lax')
    # Never let browsers (esp. mobile) cache the page/data — otherwise template
    # or layout changes don't show up after a refresh.
    resp.headers['Cache-Control'] = 'no-store, must-revalidate'
    return resp


@app.route('/')
def index():
    return render_template('index.html', view_only=VIEW_ONLY)

DATA_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.data_cache.json')


@app.route('/api/data')
def data():
    """Cached Deribit account data. ?refresh=1 forces a live fetch.

    Page loads / recomputes read the cache (fast, no Deribit round-trip).
    Only the explicit Refresh button hits Deribit live."""
    if request.args.get('refresh') != '1' and os.path.exists(DATA_CACHE):
        try:
            with open(DATA_CACHE, 'r', encoding='utf-8') as f:
                return jsonify(json.load(f))
        except Exception:
            pass  # fall through to live fetch
    try:
        result = fetch()
        result['_fetched_at'] = datetime.now().isoformat(timespec='seconds')
        with open(DATA_CACHE, 'w', encoding='utf-8') as f:
            json.dump(result, f)
        return jsonify(result)
    except Exception as e:
        # On live-fetch failure, serve stale cache if we have it
        if os.path.exists(DATA_CACHE):
            with open(DATA_CACHE, 'r', encoding='utf-8') as f:
                d = json.load(f)
            d['_stale_error'] = str(e)
            return jsonify(d)
        return jsonify({"error": str(e)}), 500


def _fetch_chain_and_spot():
    """Live BTC option chain + spot index via public Deribit endpoints."""
    chain = requests.get(
        "https://www.deribit.com/api/v2/public/get_book_summary_by_currency",
        params={"currency": "BTC", "kind": "option"}, timeout=20,
    ).json().get("result", [])
    spot = requests.get(
        "https://www.deribit.com/api/v2/public/get_index_price",
        params={"index_name": "btc_usd"}, timeout=10,
    ).json().get("result", {}).get("index_price", 0)
    return chain, spot


@app.route('/api/wheel/config', methods=['GET', 'POST'])
def wheel_config():
    if request.method == 'POST':
        return jsonify(wheel.save_config(request.get_json(force=True)))
    return jsonify(wheel.load_config())


@app.route('/api/wheel/pricetable')
def wheel_pricetable():
    # cached unless ?refresh=1
    if request.args.get('refresh') != '1':
        cached = wheel.load_price_table()
        if cached:
            return jsonify(cached)
    try:
        chain, spot = _fetch_chain_and_spot()
        table = wheel.compute_price_table(chain, spot)
        wheel.save_price_table(table)
        return jsonify(table)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/wheel/snapshots', methods=['GET'])
def wheel_snapshots_list():
    snaps = wheel.load_snapshots()
    return jsonify([
        {"name": n, "saved_at": v.get("saved_at"), "note": v.get("note", "")}
        for n, v in sorted(snaps.items())
    ])


@app.route('/api/wheel/snapshot/<name>', methods=['GET', 'DELETE'])
def wheel_snapshot_one(name):
    snaps = wheel.load_snapshots()
    if request.method == 'DELETE':
        snaps.pop(name, None)
        wheel.save_snapshots(snaps)
        return jsonify({"ok": True})
    snap = snaps.get(name)
    return jsonify(snap if snap else {"error": "not found"})


@app.route('/api/wheel/optimize', methods=['POST'])
def wheel_optimize_route():
    """Run the buy-action optimiser on the state currently on screen and save it
    as an auto-named scenario (e.g. 50K-2606110908). Body: {config, data,
    price_table, lines, peak?}."""
    import wheel_optimize as WO
    body = request.get_json(force=True)
    cfg, data, pt = body.get('config'), body.get('data'), body.get('price_table')
    if not (cfg and data and pt):
        return jsonify({"error": "missing config / data / price_table"}), 400
    lines = body.get('lines') or ['low50']
    if isinstance(lines, str):
        lines = [s.strip() for s in lines.split(',') if s.strip()]
    try:
        lock_levels = [int(x) for x in (body.get('lock_levels') or [])]
        res = WO.run_and_save(cfg, data, pt, lines,
                              peak=int(body.get('peak') or 80000),
                              starts=int(body.get('starts') or 12),
                              name=body.get('name'), lock_levels=lock_levels)
        return jsonify(res)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/wheel/snapshot', methods=['POST'])
def wheel_snapshot_save():
    body = request.get_json(force=True)
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    snaps = wheel.load_snapshots()
    snaps[name] = body.get("snapshot") or {}
    wheel.save_snapshots(snaps)
    return jsonify({"ok": True})


if __name__ == '__main__':
    import webbrowser
    import threading
    import time
    import urllib.request

    port = int(os.getenv('DASH_PORT', '5050'))

    def open_browser():
        # Wait until the server actually answers, THEN open exactly one tab.
        # A fixed sleep opens too early on a cold start (numpy/scipy import +
        # first Deribit fetch), which is what showed the error page before.
        url = f'http://localhost:{port}/'
        for _ in range(120):                       # up to ~60s
            try:
                urllib.request.urlopen(url, timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        webbrowser.open(url)

    # The view-only instance is meant to be tunnelled, not browsed locally.
    if not VIEW_ONLY:
        threading.Thread(target=open_browser, daemon=True).start()
    app.run(port=port, debug=False, threaded=True)
