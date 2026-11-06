Run setup.bat to create a virtual environment for the Python server once.

On each recording/streaming session start, run run.bat to execute an
instance of MetaTrader and bridge it's data to webpages in the project folder
which can be used in OBS scenes with the browser source.

To change which instruments are shown, edit symbols.json (use the exact
symbol names from your broker's MT5 Market Watch) and restart run.bat.
Both pages pick up the list and each symbol's decimal places from the
server automatically; symbols the broker doesn't offer are skipped.

The pages load their script and fonts from the vendor/ folder, so they
work without internet access. Keep vendor/ next to the HTML files.

MT5 connection: the server keeps running if MetaTrader 5 isn't up, isn't
logged in, or closes during a show - it retries every 5 seconds and
resumes streaming by itself. Status is shown on the pages:
  - ticker-front: small dot bottom-right - green = live,
    amber = server running but MT5 feed down, grey = server not running
  - ticker-terminal: header "S1_FEED: LIVE / DOWN", reasons in the event log

Clock: the server checks this PC's clock against NTP (time.google.com,
pool.ntp.org, time.windows.com) at startup and every 15 minutes, and
the on-screen clocks apply the correction. If NTP is unreachable, the
last good correction (or the plain PC clock) is used.
