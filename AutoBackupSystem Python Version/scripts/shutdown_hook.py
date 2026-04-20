#!/usr/bin/env python3
"""Called on system shutdown to create a final backup."""
import tarfile, json
from datetime import datetime
from pathlib import Path

cfg_path = Path.home() / "AutoBackupSystem" / "config" / "settings.json"
default = {
    "backup_src":  str(Path.home() / "Desktop"),
    "backup_dest": str(Path.home() / "AutoBackupSystem" / "backups"),
}
cfg = {**default, **(json.loads(cfg_path.read_text()) if cfg_path.exists() else {})}

dest = Path(cfg["backup_dest"])
dest.mkdir(parents=True, exist_ok=True)
ts   = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
out  = dest / f"shutdown_{ts}.tar.gz"

with tarfile.open(out, "w:gz") as tar:
    tar.add(cfg["backup_src"], arcname="Desktop")

log = Path.home() / "AutoBackupSystem" / "logs" / "backup.log"
log.parent.mkdir(parents=True, exist_ok=True)
with open(log, "a") as f:
    f.write(f"[{datetime.now()}] Shutdown backup created: {out}\n")
