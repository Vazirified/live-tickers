import eventlet
eventlet.monkey_patch()

import MetaTrader5 as mt5
from flask import Flask
from flask_socketio import SocketIO, emit
import json
import os
import socket
import struct
import threading
import time
from datetime import datetime, timezone

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# 1. Initialize MT5
if not mt5.initialize():
    print("MT5 Initialize failed")
    quit()

# 2. Load the symbol list (single source of truth for the server and all pages)
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "symbols.json")
with open(CONFIG_PATH, encoding="utf-8") as f:
    configured_symbols = json.load(f)["symbols"]

# Only keep symbols this broker actually offers; read display precision from MT5
symbols = []
symbol_digits = {}
for symbol in configured_symbols:
    if not mt5.symbol_select(symbol, True):
        print(f"[WARN] {symbol} is not available from this broker - skipping it")
        continue
    info = mt5.symbol_info(symbol)
    symbol_digits[symbol] = info.digits if info else 2
    symbols.append(symbol)

print(f"Streaming {len(symbols)} symbols: {', '.join(symbols)}")

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

# Initial fetch
update_ref_prices()

def background_tick_reader():
    """Reads prices from MT5 and pushes to Webpage via WebSocket"""
    last_prices = {symbol: 0 for symbol in symbols}

    while True:
        for symbol in symbols:
            tick = mt5.symbol_info_tick(symbol)
            # Ensure we have a valid tick with a positive bid price
            if tick and tick.bid > 0 and tick.bid != last_prices[symbol]:
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
    """Tells each newly connected page which symbols to show, their precision and the clock correction"""
    emit('config', {
        'symbols': [{'symbol': s, 'digits': symbol_digits[s]} for s in symbols]
    })
    emit('time_offset', {'offset_ms': clock_offset_ms})

@app.route('/')
def index():
    return "MT5 WebSocket Server is Running."

if __name__ == '__main__':
    thread = threading.Thread(target=background_tick_reader)
    thread.daemon = True
    thread.start()
    clock_thread = threading.Thread(target=background_clock_sync)
    clock_thread.daemon = True
    clock_thread.start()
    socketio.run(app, port=5000)
