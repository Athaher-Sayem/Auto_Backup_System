# Keep / Restore — isolated design concept

Open `index.html` directly or serve this folder with `python -m http.server 8000`. **This page performs no backup or restore and never reads local files.** The interactive workflow tabs only swap explanatory text.

The repository's starting `main` (`e5981a73`) contains Python and Bash folders. Source-verified Bash details are taken from `AutoBackupSystem Using Bash/main.sh` and `config.cfg`: Zenity action choices, a tar → pv → gzip backup pipeline, configured source/destination and restore delegation. The code card is shortened and not runnable. No claim about actual backup status, recovery success or safety is made.

Art direction: operational field guide; cool mist, navy, sea glass and muted orange, Outfit + DM Sans + IBM Plex Mono; a diagram for workflow orientation rather than an invented dashboard. All work is confined to `showcase-design/`.

Rendered screenshots: `assets/screenshots/desktop.png`, `assets/screenshots/tablet.png`, `assets/screenshots/mobile.png`.
