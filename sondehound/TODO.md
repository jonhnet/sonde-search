# SondeHound TODO

## Features
- Auto/frequency mode selector: auto_rx has no command interface to
  switch modes or set a frequency remotely. Its web API (Flask on port
  5000) is read-only. To support this we'd need a wrapper that manages
  the auto_rx process (e.g. rewrite station.cfg and restart). The UI
  code is written but hidden for now.
