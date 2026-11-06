Run setup.bat to create a virtual environment for the Python server once.

On each recording/streaming session start, run run.bat to execute an
instance of MetaTrader and bridge it's data to webpages in the project folder
which can be used in OBS scenes with the browser source.

To change which instruments are shown, edit symbols.json (use the exact
symbol names from your broker's MT5 Market Watch) and restart run.bat.
Both pages pick up the list and each symbol's decimal places from the
server automatically; symbols the broker doesn't offer are skipped.
