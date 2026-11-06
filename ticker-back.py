import MetaTrader5 as mt5
from flask import Flask, abort, send_from_directory
from flask_socketio import SocketIO, emit
import json
import logging
import os
import socket
import struct
import threading
import time
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, static_folder=None)
# "threading" mode: plain OS threads + the simple-websocket package (no eventlet).
# MT5 calls that block (e.g. waiting for the terminal) no longer freeze the web server.
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Don't print a console line for every HTTP request the pages make
logging.getLogger('werkzeug').setLevel(logging.WARNING)

# Load the symbol list (single source of truth for the server and all pages)
CONFIG_PATH = os.path.join(BASE_DIR, "symbols.json")
with open(CONFIG_PATH, encoding="utf-8") as f:
    configured_symbols = json.load(f)["symbols"]

# Symbols actually streamed (filled in once MT5 is connected) and their precision
symbols = []
symbol_digits = {}

def config_payload():
    return {'symbols': [{'symbol': s, 'digits': symbol_digits[s]} for s in symbols]}

def setup_symbols():
    """Keeps only symbols this broker offers, reads their precision, tells the pages"""
    global symbols, symbol_digits
    new_symbols, new_digits = [], {}
    for symbol in configured_symbols:
        if not mt5.symbol_select(symbol, True):
            print(f"[WARN] {symbol} is not available from this broker - skipping it")
            continue
        info = mt5.symbol_info(symbol)
        new_digits[symbol] = info.digits if info else 2
        new_symbols.append(symbol)
    symbols, symbol_digits = new_symbols, new_digits
    print(f"Streaming {len(symbols)} symbols: {', '.join(symbols)}")
    socketio.emit('config', config_payload())

# --- MT5 connection & feed status -----------------------------------------------
# The server never quits because of MT5: it keeps retrying, and tells the pages
# whether the price feed is live so they can show it.
MT5_RETRY_SECONDS = 5

feed_online = False
feed_message = "Connecting to MetaTrader 5..."

def set_feed_status(online, message):
    """Logs and broadcasts feed status changes (only when something changed)"""
    global feed_online, feed_message
    if online == feed_online and message == feed_message:
        return
    feed_online, feed_message = online, message
    print(f"[FEED {'UP' if online else 'DOWN'}] {message}")
    socketio.emit('feed_status', {'online': online, 'message': message})

def mt5_problem():
    """Returns None if MT5 is running and connected to the broker, else a reason"""
    info = mt5.terminal_info()
    if info is None:
        return "MetaTrader 5 is not running or was closed"
    if not info.connected:
        return "MetaTrader 5 is not connected to the broker (check login / internet)"
    return None

def connect_mt5():
    """One connection attempt. Returns True once MT5 is ready and symbols are set up."""
    if mt5.terminal_info() is None:
        mt5.shutdown()  # drop any dead connection before starting a new one
        # Starts the MT5 terminal if it isn't running yet
        if not mt5.initialize(timeout=10000):
            code, msg = mt5.last_error()
            set_feed_status(False, f"Can't reach MetaTrader 5 ({code}: {msg}) - retrying every {MT5_RETRY_SECONDS}s")
            return False
    problem = mt5_problem()
    if problem:
        set_feed_status(False, f"{problem} - retrying every {MT5_RETRY_SECONDS}s")
        return False
    setup_symbols()
    update_ref_prices()
    set_feed_status(True, f"Streaming {len(symbols)} symbols")
    return True

# Previous day's close for each symbol (the reference for the % change)
ref_prices = {}
# Open time (broker server time) of the daily bar that reference belongs to,
# i.e. the "current day" at the time we fetched it
ref_day_start = {}
# Last time we tried to refresh each symbol (limits retries to once a second)
last_ref_attempt = {}

SECONDS_PER_DAY = 86400

def update_ref_price(symbol):
    """Fetches the PREVIOUS day's close and remembers which day it belongs to.

    Returns True if the reference moved to a newer day (or was set for the first time).
    """
    # Two most recent daily bars, oldest first: [yesterday, today]
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, 2)
    if rates is None or len(rates) < 2:
        print(f"Failed to get previous close for {symbol}")
        return False
    day_start = int(rates[1]['time'])
    if day_start <= ref_day_start.get(symbol, -1):
        return False  # MT5 hasn't started the new daily bar yet
    ref_prices[symbol] = float(rates[0]['close'])
    ref_day_start[symbol] = day_start
    day = datetime.fromtimestamp(day_start, timezone.utc).strftime('%Y-%m-%d')
    print(f"Updated Reference (Prev Close) for {symbol}: {ref_prices[symbol]} (day {day})")
    return True

def update_ref_prices():
    for symbol in symbols:
        update_ref_price(symbol)

def check_rollover(symbol, tick_time):
    """Refreshes the reference as soon as a tick from a new trading day arrives.

    Tick and bar times are both broker server time, so comparing them is
    reliable regardless of this PC's time zone. If MT5 hasn't built the new
    daily bar yet, the stored day doesn't change and we retry a second later.
    """
    if tick_time <= 0:
        return
    tick_day_start = tick_time - tick_time % SECONDS_PER_DAY
    if tick_day_start <= ref_day_start.get(symbol, 0):
        return
    now = time.time()
    last_attempt = last_ref_attempt.get(symbol, (None, 0))
    if last_attempt[0] == tick_day_start and now - last_attempt[1] < 1:
        return
    if last_attempt[0] != tick_day_start:
        print(f"New trading day detected for {symbol} - refreshing reference")
    last_ref_attempt[symbol] = (tick_day_start, now)
    update_ref_price(symbol)

def background_tick_reader():
    """Connects to MT5 (and reconnects), reads prices and pushes them to the pages"""
    last_prices = {}
    last_health_check = 0

    while True:
        if not feed_online:
            if not connect_mt5():
                time.sleep(MT5_RETRY_SECONDS)
                continue
            last_prices = {}  # (re)connected: send every price again
            last_health_check = time.time()

        # Once a second, make sure MT5 is still there and connected to the broker
        if time.time() - last_health_check >= 1:
            last_health_check = time.time()
            problem = mt5_problem()
            if problem:
                set_feed_status(False, f"Lost price feed: {problem} - reconnecting")
                continue

        for symbol in symbols:
            tick = mt5.symbol_info_tick(symbol)
            # Ensure we have a valid tick with a positive bid price
            if tick and tick.bid > 0 and tick.bid != last_prices.get(symbol):
                last_prices[symbol] = tick.bid

                # Switch to the new previous close the moment the day rolls over
                check_rollover(symbol, tick.time)

                # Calculate percentage change from previous close
                change_pct = 0.0
                if symbol in ref_prices and ref_prices[symbol] != 0:
                    change_pct = ((tick.bid - ref_prices[symbol]) / ref_prices[symbol]) * 100

                # Push data to all connected browser tabs
                socketio.emit('price_update', {
                    'symbol': symbol,
                    'price': tick.bid,
                    'change': round(change_pct, 2)
                })

        time.sleep(0.1)

# --- Clock correction via NTP -------------------------------------------------
# The on-screen clocks use this PC's time. We measure how far it is off from
# NTP and send the correction to the pages. If NTP can't be reached, the last
# good correction is kept (or 0 = plain PC clock if it never succeeded).
NTP_SERVERS = ["time.google.com", "pool.ntp.org", "time.windows.com"]
NTP_INTERVAL = 900  # seconds (15 minutes)
NTP_EPOCH_DELTA = 2208988800  # seconds between 1900-01-01 and 1970-01-01

clock_offset_ms = 0

def query_ntp_offset(host):
    """Returns (NTP time - PC time) in seconds for one server, or raises"""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(3)
        t0 = time.time()
        s.sendto(b'\x1b' + 47 * b'\0', (host, 123))  # SNTP v3 client request
        data, _ = s.recvfrom(48)
        t1 = time.time()
    secs, frac = struct.unpack('!II', data[40:48])  # server transmit timestamp
    ntp_time = secs - NTP_EPOCH_DELTA + frac / 2**32
    return ntp_time - (t0 + t1) / 2

def background_clock_sync():
    global clock_offset_ms
    while True:
        for host in NTP_SERVERS:
            try:
                offset = query_ntp_offset(host)
            except OSError as e:
                print(f"[WARN] NTP {host} failed: {e}")
                continue
            clock_offset_ms = round(offset * 1000)
            direction = "slow" if offset > 0 else "fast"
            print(f"Clock check ({host}): PC clock is {abs(offset):.2f}s {direction}")
            socketio.emit('time_offset', {'offset_ms': clock_offset_ms})
            break
        else:
            print(f"[WARN] No NTP server reachable - keeping correction of {clock_offset_ms} ms")
        time.sleep(NTP_INTERVAL)

@socketio.on('connect')
def send_config():
    """Tells each newly connected page the symbols, clock correction and feed status"""
    emit('config', config_payload())
    emit('time_offset', {'offset_ms': clock_offset_ms})
    emit('feed_status', {'online': feed_online, 'message': feed_message})

# --- Overlay pages ----------------------------------------------------------------
# OBS (Chromium 150+) blocks pages opened as "Local file" (origin http://absolute)
# from talking to localhost. Serving the pages from this server makes them
# same-origin with the WebSocket, so use these URLs in OBS Browser Sources:
#   http://localhost:5000/ticker-front.html
#   http://localhost:5000/ticker-terminal.html
PAGES = ["ticker-front.html", "ticker-terminal.html"]

@app.route('/')
def index():
    links = "".join(f'<li><a href="/{p}">http://localhost:5000/{p}</a></li>' for p in PAGES)
    return f"<p>MT5 WebSocket Server is Running.</p><p>OBS Browser Source URLs:</p><ul>{links}</ul>"

@app.route('/<page>')
def overlay_page(page):
    if page not in PAGES:
        abort(404)
    # max_age=0: OBS always gets the current version after an edit
    return send_from_directory(BASE_DIR, page, max_age=0)

@app.route('/vendor/<path:filename>')
def vendor_file(filename):
    return send_from_directory(os.path.join(BASE_DIR, "vendor"), filename)

if __name__ == '__main__':
    thread = threading.Thread(target=background_tick_reader)
    thread.daemon = True
    thread.start()
    clock_thread = threading.Thread(target=background_clock_sync)
    clock_thread.daemon = True
    clock_thread.start()
    # Werkzeug's built-in server is fine here: it only listens on 127.0.0.1
    # and serves a couple of local OBS browser sources.
    socketio.run(app, host="127.0.0.1", port=5000, allow_unsafe_werkzeug=True)
