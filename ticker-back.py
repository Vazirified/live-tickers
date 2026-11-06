import eventlet
eventlet.monkey_patch()

import MetaTrader5 as mt5
from flask import Flask
from flask_socketio import SocketIO, emit
import threading
import time
from datetime import datetime

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# 1. Initialize MT5
if not mt5.initialize():
    print("MT5 Initialize failed")
    quit()

symbols = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "EURGBP", "S&P500"]

# Dictionary to store the previous day's close price for each symbol
ref_prices = {}

def update_ref_prices():
    """Fetches the closing price of the PREVIOUS day for all symbols"""
    global ref_prices
    for symbol in symbols:
        # Ensure symbol is selected in Market Watch
        if not mt5.symbol_select(symbol, True):
            print(f"Failed to select {symbol}")
            continue

        # Index 1 is the previous completed day (yesterday)
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 1, 1)
        if rates is not None and len(rates) > 0:
            ref_prices[symbol] = rates[0]['close']
            print(f"Updated Reference (Prev Close) for {symbol}: {ref_prices[symbol]}")
        else:
            print(f"Failed to get previous close for {symbol}")

# Initial fetch
update_ref_prices()

def background_tick_reader():
    """Reads prices from MT5 and pushes to Webpage via WebSocket"""
    last_prices = {symbol: 0 for symbol in symbols}
    last_ref_update = time.time()

    while True:
        # Re-fetch reference prices every hour (to catch daily rollover)
        if time.time() - last_ref_update > 3600:
            update_ref_prices()
            last_ref_update = time.time()

        for symbol in symbols:
            tick = mt5.symbol_info_tick(symbol)
            # Ensure we have a valid tick with a positive bid price
            if tick and tick.bid > 0 and tick.bid != last_prices[symbol]:
                last_prices[symbol] = tick.bid
                
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

@app.route('/')
def index():
    return "MT5 WebSocket Server is Running."

if __name__ == '__main__':
    thread = threading.Thread(target=background_tick_reader)
    thread.daemon = True
    thread.start()
    socketio.run(app, port=5000)
