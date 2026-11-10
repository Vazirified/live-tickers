# Live Tickers

Live market price overlays for OBS, fed by MetaTrader 5.

A small Python server reads prices from a running MetaTrader 5 terminal and
pushes them over WebSocket to two HTML overlay pages, which you add to your
OBS scenes as Browser Sources:

- **`ticker-front.html`**: a scrolling ticker stripe with each symbol's
  price and % change, plus a clock.
- **`ticker-terminal.html`**: a terminal-style data panel with prices,
  feed status and an event log.

Everything runs on the same PC as OBS and works without internet access,
except for the MT5 broker connection itself.

## Requirements

- **Windows**: the `MetaTrader5` Python package only works on Windows.
- **Python 3**: from [python.org](https://www.python.org/), with "Add
  python.exe to PATH" ticked during install. Tested with Python 3.14.
- **MetaTrader 5 terminal**: installed and logged in to your broker account.
- **OBS Studio**: tested with OBS 33.

## Setup

Run `setup.bat` once. It creates a virtual environment in `.venv/` and
installs the packages listed in `requirements.txt`.

## Running a show

1. Run `run.bat` at the start of each recording or streaming session. It
   starts the server, which starts MetaTrader 5 if it isn't already
   running.
2. Then open OBS (or refresh the browser sources, see below).

The server keeps running until you close its console window.
`http://localhost:5000/` lists the overlay URLs.

## OBS Browser Source setup

Leave **"Local file" unchecked** and use these URLs:

```
http://localhost:5000/ticker-front.html
http://localhost:5000/ticker-terminal.html
```

Why: OBS 33+ (Chromium 150) blocks pages opened as a local file from
connecting to `localhost`, so the ticker stays blank. Pages served by the
server itself are allowed.

Start `run.bat` before OBS loads the scene. If OBS was opened first, open
the source's properties and click **"Refresh cache of current page"**, or
tick **"Refresh browser when scene becomes active"**.

## Choosing instruments

Edit `symbols.json` and restart `run.bat`:

```json
{
    "symbols": ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "EURGBP", "S&P500"]
}
```

Use the exact symbol names from your broker's MT5 **Market Watch**. Both
pages get the list and each symbol's decimal places from the server
automatically. Symbols the broker doesn't offer are skipped, with a
warning in the server console.

## How it behaves

**% change**: measured against the previous trading day's close. The
reference switches to the new previous close as soon as the first tick of
a new trading day arrives (the broker's daily rollover, in broker server
time).

**MT5 connection**: the server keeps running if MetaTrader 5 isn't up,
isn't logged in, or closes during a show. It retries every 5 seconds and
resumes streaming by itself. The pages show the feed status:

| Page | Live | Feed down | Server not running |
|---|---|---|---|
| `ticker-front` | green dot, bottom right | amber dot | grey dot |
| `ticker-terminal` | header `S1_FEED: LIVE` | header `S1_FEED: DOWN`, reason in the event log | — |

**Clock**: the server checks this PC's clock against NTP
(`time.google.com`, `pool.ntp.org`, `time.windows.com`) at startup and
every 15 minutes, and the on-screen clocks apply the correction. If NTP is
unreachable, the last good correction (or the plain PC clock) is used.

**Offline**: the pages load their Socket.IO client and fonts from
`vendor/`, which the server also serves, so no CDN is needed.

**Network exposure**: the server listens on `127.0.0.1:5000` only. It is
not reachable from other machines.

## Files

| File | Purpose |
|---|---|
| `ticker-back.py` | Server: MT5 reader, WebSocket, NTP clock check, serves the pages |
| `ticker-front.html` | Scrolling ticker stripe overlay |
| `ticker-terminal.html` | Terminal-style overlay |
| `symbols.json` | Instruments to show |
| `setup.bat` | One-time setup: virtual environment and packages |
| `run.bat` | Starts the server |
| `requirements.txt` | Python packages (pinned versions) |
| `vendor/` | Local copies of the Socket.IO client and fonts |

## License

[MIT](LICENSE). The bundled Socket.IO client (MIT) and fonts (Inter,
JetBrains Mono, VT323, under the SIL Open Font License 1.1, see
[`vendor/fonts/OFL.txt`](vendor/fonts/OFL.txt)) keep their own licences.
