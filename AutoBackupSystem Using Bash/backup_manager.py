#!/usr/bin/env python3
"""
Advanced Desktop Backup Manager v2.0
Multi-source, scheduled, incremental, verified — Linux Mint
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading, subprocess, os, time, tarfile, shutil, json, stat, fnmatch
from datetime import datetime, timedelta
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════════
BASE_DIR   = Path.home() / "AutoBackupSystem"
CFG_FILE   = BASE_DIR / "config" / "settings.json"
LOG_FILE   = BASE_DIR / "logs"   / "backup.log"
BACKUP_DIR = BASE_DIR / "backups"
AUTOSTART  = Path.home() / ".config" / "autostart" / "autobackup.desktop"

for d in [BASE_DIR/"config", BASE_DIR/"logs", BACKUP_DIR]:
    d.mkdir(parents=True, exist_ok=True)

DEFAULT_CFG = {
    "sources":           [str(Path.home()/"Desktop")],
    "backup_dest":       str(BACKUP_DIR),
    "interval":          60,
    "max_backups":       20,
    "compression":       "gz",
    "exclude_patterns":  ["*.tmp","*.swp","*~","__pycache__",".git","node_modules"],
    "auto_start_backup": False,
    "startup_launch":    False,
    "notify_desktop":    True,
    "shutdown_backup":   True,
    "schedule_mode":     "interval",
    "schedule_time":     "02:00",
    "schedule_weekday":  0,
    "incremental":       False,
    "verify_after":      False,
}

T = {
    "BG":"#0d0d1a","BG2":"#12122a","BG3":"#1a1a32","BG4":"#222240",
    "ACCENT":"#7c6af7","ACCENT2":"#f75f7c","GREEN":"#2ecc71",
    "YELLOW":"#f1c40f","CYAN":"#00d4ff","ORANGE":"#ff8c42",
    "TEXT":"#e8e8f8","TEXT_DIM":"#6a6a9a","BORDER":"#2a2a50",
}

def load_cfg():
    if CFG_FILE.exists():
        try: return {**DEFAULT_CFG,**json.loads(CFG_FILE.read_text())}
        except: pass
    return DEFAULT_CFG.copy()

def save_cfg(cfg):
    CFG_FILE.parent.mkdir(parents=True,exist_ok=True)
    CFG_FILE.write_text(json.dumps(cfg,indent=2))

def write_log(msg,level="INFO"):
    with open(LOG_FILE,"a") as f:
        f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [{level}] {msg}\n")

def fmt_size(b):
    for u in ("B","KB","MB","GB","TB"):
        if abs(b)<1024: return f"{b:.1f} {u}"
        b/=1024
    return f"{b:.1f} PB"

def get_disk_usage(path):
    try: st=shutil.disk_usage(path); return st.used,st.total
    except: return 0,1

def verify_archive(path):
    try:
        with tarfile.open(path,"r:*") as t: t.getmembers()
        return True
    except: return False

def get_archive_contents(path):
    items=[]
    try:
        with tarfile.open(path,"r:*") as t:
            for m in t.getmembers():
                if m.isfile():
                    items.append((m.name,m.size,
                                  datetime.fromtimestamp(m.mtime).strftime("%Y-%m-%d %H:%M")))
    except: pass
    return items

def calc_folder_size(path):
    total=0
    try:
        for f in Path(path).rglob("*"):
            if f.is_file():
                try: total+=f.stat().st_size
                except: pass
    except: pass
    return total

def set_autostart(enable,app_path):
    AUTOSTART.parent.mkdir(parents=True,exist_ok=True)
    if enable:
        AUTOSTART.write_text(f"""[Desktop Entry]
Type=Application
Name=Auto Backup Manager
Exec=python3 {app_path}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
""")
    elif AUTOSTART.exists():
        AUTOSTART.unlink()

def send_notify(title,body):
    try: subprocess.Popen(["notify-send",title,body],
                          stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    except: pass

# ══════════════════════════════════════════════════════════════════════════════
#  BACKUP ENGINE
# ══════════════════════════════════════════════════════════════════════════════
class BackupEngine:
    def __init__(self):
        self.running=False; self._thread=None; self._cache={}
        self.on_start=None; self.on_progress=None; self.on_done=None
        self.on_tick=None;  self.on_verify=None

    def start(self,cfg):
        if self.running: return
        self.running=True
        self._thread=threading.Thread(target=self._loop,args=(cfg,),daemon=True)
        self._thread.start()

    def stop(self): self.running=False

    def run_once(self,cfg):
        threading.Thread(target=self._do,args=(cfg,),daemon=True).start()

    def _loop(self,cfg):
        mode=cfg.get("schedule_mode","interval")
        while self.running:
            self._do(cfg)
            if not self.running: break
            if mode=="interval":
                iv=int(cfg.get("interval",60))
                for rem in range(iv,0,-1):
                    if not self.running: return
                    if self.on_tick: self.on_tick(rem,iv)
                    time.sleep(1)
            elif mode=="daily":
                self._wait_time(cfg.get("schedule_time","02:00"))
            elif mode=="weekly":
                self._wait_weekday(int(cfg.get("schedule_weekday",0)),
                                   cfg.get("schedule_time","02:00"))

    def _wait_time(self,hhmm):
        h,m=map(int,hhmm.split(":"))
        now=datetime.now()
        target=now.replace(hour=h,minute=m,second=0,microsecond=0)
        if target<=now: target+=timedelta(days=1)
        secs=int((target-now).total_seconds())
        for rem in range(secs,0,-1):
            if not self.running: return
            if self.on_tick: self.on_tick(rem,secs)
            time.sleep(1)

    def _wait_weekday(self,weekday,hhmm):
        h,m=map(int,hhmm.split(":"))
        now=datetime.now()
        days=(weekday-now.weekday())%7
        target=(now+timedelta(days=days)).replace(hour=h,minute=m,second=0,microsecond=0)
        if target<=now: target+=timedelta(weeks=1)
        secs=int((target-now).total_seconds())
        for rem in range(secs,0,-1):
            if not self.running: return
            if self.on_tick: self.on_tick(rem,secs)
            time.sleep(1)

    def _do(self,cfg):
        sources=cfg.get("sources",[])
        dest=Path(cfg.get("backup_dest",str(BACKUP_DIR)))
        dest.mkdir(parents=True,exist_ok=True)
        comp=cfg.get("compression","gz")
        excludes=cfg.get("exclude_patterns",[])
        incr=cfg.get("incremental",False)
        do_verify=cfg.get("verify_after",False)
        if self.on_start: self.on_start()
        ts=datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        mode_map={"gz":"w:gz","bz2":"w:bz2","xz":"w:xz","none":"w:"}
        mode=mode_map.get(comp,"w:gz")
        ext=f".tar.{comp}" if comp!="none" else ".tar"
        fname=dest/f"backup_{ts}{ext}"
        try:
            with tarfile.open(fname,mode) as tar:
                for i,src in enumerate(sources):
                    sp=Path(src)
                    if not sp.exists():
                        write_log(f"Source missing, skipped: {src}","WARN"); continue
                    if self.on_progress:
                        self.on_progress(src,int(i/max(len(sources),1)*100))
                    self._add(tar,sp,excludes,incr)
            size=fname.stat().st_size
            write_log(f"Backup created: {fname} ({fmt_size(size)})")
            self._prune(dest,int(cfg.get("max_backups",20)))
            if do_verify:
                ok=verify_archive(str(fname))
                write_log(f"Verify: {'OK' if ok else 'FAILED'} — {fname}",
                          "INFO" if ok else "ERROR")
                if self.on_verify: self.on_verify(ok)
            if cfg.get("notify_desktop"):
                send_notify("Backup Complete",f"{fmt_size(size)} saved")
            if self.on_done: self.on_done(str(fname),size,True,"OK")
        except Exception as e:
            write_log(f"Backup FAILED: {e}","ERROR")
            if self.on_done: self.on_done("",0,False,str(e))
            try: fname.unlink(missing_ok=True)
            except: pass

    def _add(self,tar,src,excludes,incr):
        def excl(p): return any(fnmatch.fnmatch(p.name,pat) for pat in excludes)
        if src.is_file():
            if not excl(src): tar.add(str(src),arcname=str(src))
            return
        for root,dirs,files in os.walk(str(src)):
            rp=Path(root)
            dirs[:]=[d for d in dirs if not excl(rp/d)]
            for fn in files:
                fp=rp/fn
                if excl(fp): continue
                try:
                    if incr:
                        key=str(fp); mt=fp.stat().st_mtime
                        if self._cache.get(key)==mt: continue
                        self._cache[key]=mt
                    tar.add(str(fp),arcname=str(fp))
                except Exception as e:
                    write_log(f"Skipped {fp}: {e}","WARN")

    def _prune(self,dest,maxb):
        files=sorted(dest.glob("backup_*"))
        while len(files)>maxb:
            try: files.pop(0).unlink()
            except: pass
            files=sorted(dest.glob("backup_*"))

engine=BackupEngine()

# ══════════════════════════════════════════════════════════════════════════════
#  WIDGETS
# ══════════════════════════════════════════════════════════════════════════════
class Btn(tk.Canvas):
    def __init__(self,parent,text,cmd=None,color=None,w=180,h=40,fg="white",**kw):
        color=color or T["ACCENT"]
        super().__init__(parent,width=w,height=h,bg=T["BG2"],
                         highlightthickness=0,cursor="hand2",**kw)
        self._t=text;self._cmd=cmd;self._c=color;self._fg=fg
        self._hov=False;self._prs=False
        for ev,fn in [("<Configure>",self._d),("<Enter>",self._en),
                      ("<Leave>",self._lv),("<ButtonPress-1>",self._bp),
                      ("<ButtonRelease-1>",self._br)]:
            self.bind(ev,fn)
        self._d()
    def _d(self,e=None):
        self.delete("all")
        w=self.winfo_width() or int(self["width"])
        h=self.winfo_height() or int(self["height"])
        r=h//2
        c=self._dk(self._c) if self._prs else self._lk(self._c) if self._hov else self._c
        self.create_polygon(r,0,w-r,0,w,r,w,h-r,w-r,h,r,h,0,h-r,0,r,
                            smooth=True,fill=c,outline="")
        self.create_text(w//2,h//2,text=self._t,fill=self._fg,
                         font=("Courier New",9,"bold"))
    def _lk(self,c):
        r,g,b=int(c[1:3],16),int(c[3:5],16),int(c[5:7],16)
        return "#{:02x}{:02x}{:02x}".format(min(r+25,255),min(g+25,255),min(b+25,255))
    def _dk(self,c):
        r,g,b=int(c[1:3],16),int(c[3:5],16),int(c[5:7],16)
        return "#{:02x}{:02x}{:02x}".format(max(r-25,0),max(g-25,0),max(b-25,0))
    def _en(self,e): self._hov=True; self._d()
    def _lv(self,e): self._hov=False;self._prs=False;self._d()
    def _bp(self,e): self._prs=True; self._d()
    def _br(self,e):
        self._prs=False; self._d()
        if self._cmd: self._cmd()
    def set(self,text=None,color=None):
        if text:  self._t=text
        if color: self._c=color
        self._d()

class Toggle(tk.Canvas):
    def __init__(self,parent,variable,cmd=None,**kw):
        super().__init__(parent,width=48,height=26,bg=T["BG2"],
                         highlightthickness=0,cursor="hand2",**kw)
        self._v=variable;self._cmd=cmd
        self.bind("<Button-1>",self._click)
        self.bind("<Configure>",self._draw)
        self._draw()
    def _draw(self,e=None):
        self.delete("all"); w,h=48,26; on=self._v.get()
        bg=T["ACCENT"] if on else T["BG4"]
        self.create_polygon(h//2,2,w-h//2,2,w-2,h//2,w-h//2,h-2,
                            h//2,h-2,2,h//2,smooth=True,fill=bg,outline="")
        cx=w-h//2-1 if on else h//2+1
        self.create_oval(cx-10,3,cx+10,h-3,fill="white",outline="")
    def _click(self,e):
        self._v.set(not self._v.get()); self._draw()
        if self._cmd: self._cmd()

# ══════════════════════════════════════════════════════════════════════════════
#  DIALOGS
# ══════════════════════════════════════════════════════════════════════════════
class ArchivePreviewDialog(tk.Toplevel):
    def __init__(self,parent,archive_path):
        super().__init__(parent)
        self.title(f"Contents — {Path(archive_path).name}")
        self.configure(bg=T["BG"]); self.geometry("720x480"); self.grab_set()
        tk.Label(self,text=f"📦  {Path(archive_path).name}",bg=T["BG"],
                 fg=T["TEXT"],font=("Courier New",11,"bold")).pack(anchor="w",padx=20,pady=(16,8))
        fr=tk.Frame(self,bg=T["BG3"]); fr.pack(fill="both",expand=True,padx=20,pady=(0,16))
        style=ttk.Style()
        style.configure("Pv.Treeview",background=T["BG3"],foreground=T["TEXT"],
                        fieldbackground=T["BG3"],font=("Courier New",9),rowheight=24)
        style.configure("Pv.Treeview.Heading",background=T["BG2"],
                        foreground=T["ACCENT"],font=("Courier New",9,"bold"))
        cols=("File Path","Size","Modified")
        tree=ttk.Treeview(fr,columns=cols,show="headings",style="Pv.Treeview")
        for c,w in zip(cols,(420,80,150)): tree.heading(c,text=c);tree.column(c,width=w,anchor="w")
        sb=ttk.Scrollbar(fr,orient="vertical",command=tree.yview)
        tree.configure(yscrollcommand=sb.set); sb.pack(side="right",fill="y")
        tree.pack(fill="both",expand=True)
        lbl=tk.Label(self,text="Loading…",bg=T["BG"],fg=T["TEXT_DIM"],font=("Courier New",8))
        lbl.pack(pady=4)
        def load():
            items=get_archive_contents(archive_path)
            self.after(0,lambda: [tree.insert("","end",values=(n,fmt_size(s),m))
                                  for n,s,m in items] or lbl.configure(
                                  text=f"{len(items)} files in archive"))
        threading.Thread(target=load,daemon=True).start()

class RestoreDialog(tk.Toplevel):
    def __init__(self,parent,archive_path,done_cb):
        super().__init__(parent)
        self.title("Restore Backup"); self.configure(bg=T["BG"])
        self.geometry("520x280"); self.grab_set()
        self._arc=archive_path; self._cb=done_cb
        self._dest=tk.StringVar(value=str(Path.home()))
        tk.Label(self,text="♻  Restore Backup",bg=T["BG"],fg=T["TEXT"],
                 font=("Courier New",13,"bold")).pack(anchor="w",padx=24,pady=(20,4))
        tk.Label(self,text=Path(archive_path).name,bg=T["BG"],fg=T["TEXT_DIM"],
                 font=("Courier New",9)).pack(anchor="w",padx=24)
        tk.Frame(self,bg=T["BORDER"],height=1).pack(fill="x",padx=24,pady=12)
        row=tk.Frame(self,bg=T["BG"]); row.pack(fill="x",padx=24,pady=4)
        tk.Label(row,text="Restore to:",bg=T["BG"],fg=T["TEXT"],
                 font=("Courier New",9),width=12,anchor="w").pack(side="left")
        tk.Entry(row,textvariable=self._dest,bg=T["BG3"],fg=T["TEXT"],
                 insertbackground=T["TEXT"],font=("Courier New",9),bd=0,
                 highlightthickness=1,highlightbackground=T["BORDER"],
                 highlightcolor=T["ACCENT"]).pack(side="left",fill="x",expand=True,ipady=4,padx=(0,6))
        Btn(row,"Browse",cmd=self._browse,color=T["BG4"],w=80,h=30,fg=T["ACCENT"]).pack(side="left")
        tk.Label(self,text="⚠ Existing files will be overwritten",bg=T["BG"],
                 fg=T["YELLOW"],font=("Courier New",9)).pack(anchor="w",padx=24,pady=(10,4))
        self._prog=ttk.Progressbar(self,mode="indeterminate")
        self._prog.pack(fill="x",padx=24,pady=4)
        brow=tk.Frame(self,bg=T["BG"]); brow.pack(pady=14)
        Btn(brow,"✅  Restore Now",cmd=self._start,color=T["ACCENT"],w=160,h=38).pack(side="left",padx=8)
        Btn(brow,"Cancel",cmd=self.destroy,color=T["BG4"],w=100,h=38,fg=T["TEXT"]).pack(side="left")
    def _browse(self):
        p=filedialog.askdirectory(title="Restore destination")
        if p: self._dest.set(p)
    def _start(self):
        self._prog.start(); arc=self._arc; dest=self._dest.get()
        def run():
            try:
                with tarfile.open(arc,"r:*") as t: t.extractall(dest)
                write_log(f"Restored {arc} → {dest}")
                self.after(0,lambda:(self._prog.stop(),self._cb(True),self.destroy()))
            except Exception as e:
                write_log(f"Restore FAILED: {e}","ERROR")
                self.after(0,lambda:(self._prog.stop(),
                           messagebox.showerror("Restore Error",str(e),parent=self)))
        threading.Thread(target=run,daemon=True).start()

# ══════════════════════════════════════════════════════════════════════════════
#  MAIN APP
# ══════════════════════════════════════════════════════════════════════════════
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.cfg=load_cfg(); self._backup_on=False
        self.title("Backup Pro — Advanced Manager")
        self.geometry("1020x700"); self.minsize(900,600)
        self.configure(bg=T["BG"])
        engine.on_start    = lambda:           self.after(0,self._eng_start)
        engine.on_progress = lambda s,p:       self.after(0,self._eng_prog,s,p)
        engine.on_done     = lambda f,sz,ok,m: self.after(0,self._eng_done,f,sz,ok,m)
        engine.on_tick     = lambda r,i:       self.after(0,self._eng_tick,r,i)
        engine.on_verify   = lambda ok:        self.after(0,self._eng_verify,ok)
        self._build_ui()
        self._refresh_list()
        self._disk_loop()
        self._update_loop()
        if self.cfg.get("auto_start_backup") and self.cfg.get("sources"):
            self.after(1500,self._start_backup)
        self.protocol("WM_DELETE_WINDOW",self._on_close)

    # ── SIDEBAR ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        sb=tk.Frame(self,bg=T["BG2"],width=235)
        sb.pack(side="left",fill="y"); sb.pack_propagate(False)
        tk.Label(sb,text="💾",bg=T["BG2"],fg=T["ACCENT"],
                 font=("Segoe UI Emoji",30)).pack(pady=(24,2))
        tk.Label(sb,text="BACKUP PRO",bg=T["BG2"],fg=T["TEXT"],
                 font=("Courier New",13,"bold")).pack()
        tk.Label(sb,text="v2.0 Advanced",bg=T["BG2"],fg=T["TEXT_DIM"],
                 font=("Courier New",8)).pack(pady=(0,14))
        tk.Frame(sb,bg=T["BORDER"],height=1).pack(fill="x",padx=16)
        self._nav={}
        for label,key in [("🏠  Dashboard","dashboard"),("📁  Sources","sources"),
                          ("⚙️  Settings","settings"),("🕐  Schedule","schedule"),
                          ("📊  Statistics","stats"),("📋  Logs","logs")]:
            b=tk.Label(sb,text=label,bg=T["BG2"],fg=T["TEXT_DIM"],
                       font=("Courier New",10),anchor="w",padx=20,pady=11,cursor="hand2")
            b.pack(fill="x")
            b.bind("<Enter>",  lambda e,w=b: w.configure(bg=T["BG3"],fg=T["TEXT"]))
            b.bind("<Leave>",  lambda e,w=b,k=key:
                   w.configure(bg=T["BG2"],fg=T["ACCENT"] if self._cur==k else T["TEXT_DIM"]))
            b.bind("<Button-1>", lambda e,k=key: self._show(k))
            self._nav[key]=b
        tk.Frame(sb,bg=T["BORDER"],height=1).pack(fill="x",padx=16,pady=10)
        self._dot=tk.Label(sb,text="⬤  Idle",bg=T["BG2"],fg=T["TEXT_DIM"],
                           font=("Courier New",9))
        self._dot.pack(pady=2)
        self._next_lbl=tk.Label(sb,text="",bg=T["BG2"],fg=T["TEXT_DIM"],font=("Courier New",8))
        self._next_lbl.pack()
        self._disk_lbl=tk.Label(sb,text="",bg=T["BG2"],fg=T["TEXT_DIM"],font=("Courier New",8))
        self._disk_lbl.pack(pady=(8,0))

        self._content=tk.Frame(self,bg=T["BG"])
        self._content.pack(side="right",fill="both",expand=True)
        self._tabs={}; self._cur=None
        self._build_dashboard(); self._build_sources(); self._build_settings()
        self._build_schedule(); self._build_stats(); self._build_logs()
        self._show("dashboard")

    # ── DASHBOARD ────────────────────────────────────────────────────────────
    def _build_dashboard(self):
        f=tk.Frame(self._content,bg=T["BG"]); self._tabs["dashboard"]=f
        hdr=tk.Frame(f,bg=T["BG"]); hdr.pack(fill="x",padx=28,pady=(24,0))
        tk.Label(hdr,text="Dashboard",bg=T["BG"],fg=T["TEXT"],
                 font=("Georgia",20,"bold")).pack(side="left")
        cards=tk.Frame(f,bg=T["BG"]); cards.pack(fill="x",padx=28,pady=14)
        self._sc_total  =self._scard(cards,"Total Backups","0",  T["ACCENT"])
        self._sc_last   =self._scard(cards,"Last Backup",  "–",  T["GREEN"])
        self._sc_size   =self._scard(cards,"Archive Size", "0 B",T["YELLOW"])
        self._sc_sources=self._scard(cards,"Sources",      "0",  T["CYAN"])
        ctrl=tk.Frame(f,bg=T["BG"]); ctrl.pack(fill="x",padx=28,pady=4)
        self._btn_toggle=Btn(ctrl,"▶  Start Auto Backup",cmd=self._toggle_backup,
                             color=T["ACCENT"],w=210,h=44)
        self._btn_toggle.pack(side="left",padx=(0,10))
        Btn(ctrl,"⚡  Backup Now",cmd=self._backup_now,color="#2d7d9a",w=150,h=44).pack(side="left",padx=(0,10))
        Btn(ctrl,"📂  Open Folder",cmd=self._open_folder,color="#3d5a3e",w=150,h=44).pack(side="left",padx=(0,10))
        Btn(ctrl,"🔄  Refresh",cmd=self._refresh_list,color=T["BG4"],w=110,h=44,fg=T["TEXT"]).pack(side="left")
        prow=tk.Frame(f,bg=T["BG"]); prow.pack(fill="x",padx=28,pady=(10,2))
        tk.Label(prow,text="Next backup:",bg=T["BG"],fg=T["TEXT_DIM"],font=("Courier New",9)).pack(side="left")
        self._prog_lbl=tk.Label(prow,text="–",bg=T["BG"],fg=T["ACCENT"],font=("Courier New",9,"bold"))
        self._prog_lbl.pack(side="left",padx=8)
        self._src_lbl=tk.Label(prow,text="",bg=T["BG"],fg=T["TEXT_DIM"],font=("Courier New",8))
        self._src_lbl.pack(side="right")
        st=ttk.Style(); st.theme_use("clam")
        st.configure("P.Horizontal.TProgressbar",troughcolor=T["BG3"],
                     background=T["ACCENT"],lightcolor=T["ACCENT"],
                     darkcolor=T["ACCENT"],bordercolor=T["BG3"])
        self._progress=ttk.Progressbar(f,style="P.Horizontal.TProgressbar",
                                       mode="determinate",maximum=100,value=0)
        self._progress.pack(fill="x",padx=28,pady=(0,12))
        tk.Label(f,text="BACKUP ARCHIVE LIST",bg=T["BG"],fg=T["TEXT_DIM"],
                 font=("Courier New",8,"bold"),anchor="w").pack(fill="x",padx=28)
        lf=tk.Frame(f,bg=T["BG3"]); lf.pack(fill="both",expand=True,padx=28,pady=(6,28))
        cols=("Filename","Size","Date","Verified")
        st.configure("Bk.Treeview",background=T["BG3"],foreground=T["TEXT"],
                     fieldbackground=T["BG3"],rowheight=28,font=("Courier New",9))
        st.configure("Bk.Treeview.Heading",background=T["BG2"],foreground=T["ACCENT"],
                     font=("Courier New",9,"bold"),relief="flat")
        st.map("Bk.Treeview",background=[("selected",T["ACCENT"])],foreground=[("selected","white")])
        self._tree=ttk.Treeview(lf,columns=cols,show="headings",style="Bk.Treeview",selectmode="browse")
        for c,w in zip(cols,(310,90,180,90)):
            self._tree.heading(c,text=c); self._tree.column(c,width=w,anchor="w")
        tsb=ttk.Scrollbar(lf,orient="vertical",command=self._tree.yview)
        self._tree.configure(yscrollcommand=tsb.set); tsb.pack(side="right",fill="y")
        self._tree.pack(fill="both",expand=True)
        self._tree.bind("<Button-3>",self._ctx_show)
        self._tree.bind("<Double-1>",self._preview)
        self._ctx=tk.Menu(self,tearoff=0,bg=T["BG2"],fg=T["TEXT"],
                          activebackground=T["ACCENT"],activeforeground="white",font=("Courier New",10))
        self._ctx.add_command(label="👁  Preview Contents",command=self._preview)
        self._ctx.add_command(label="♻  Restore",          command=self._restore)
        self._ctx.add_command(label="✅  Verify Integrity", command=self._verify)
        self._ctx.add_separator()
        self._ctx.add_command(label="🗑  Delete",           command=self._delete)

    def _scard(self,parent,title,value,color):
        c=tk.Frame(parent,bg=T["BG3"]); c.pack(side="left",expand=True,fill="both",padx=(0,10))
        tk.Label(c,text=title,bg=T["BG3"],fg=T["TEXT_DIM"],
                 font=("Courier New",8),anchor="w",padx=14).pack(fill="x",pady=(10,2))
        lbl=tk.Label(c,text=value,bg=T["BG3"],fg=color,
                     font=("Georgia",18,"bold"),anchor="w",padx=14)
        lbl.pack(fill="x",pady=(0,10)); return lbl

    # ── SOURCES ──────────────────────────────────────────────────────────────
    def _build_sources(self):
        f=tk.Frame(self._content,bg=T["BG"]); self._tabs["sources"]=f
        tk.Label(f,text="Backup Sources",bg=T["BG"],fg=T["TEXT"],
                 font=("Georgia",20,"bold")).pack(anchor="w",padx=28,pady=(24,10))
        # Quick add pills
        qa=tk.Frame(f,bg=T["BG"]); qa.pack(fill="x",padx=28,pady=(0,10))
        tk.Label(qa,text="Quick add:",bg=T["BG"],fg=T["TEXT_DIM"],font=("Courier New",9)).pack(side="left",padx=(0,8))
        for label,path in [("🖥 Desktop",str(Path.home()/"Desktop")),
                           ("📄 Documents",str(Path.home()/"Documents")),
                           ("🖼 Pictures",str(Path.home()/"Pictures")),
                           ("🎵 Music",str(Path.home()/"Music")),
                           ("📥 Downloads",str(Path.home()/"Downloads")),
                           ("🏠 Home",str(Path.home())),
                           ("💾 Root /","/")]:
            b=tk.Label(qa,text=label,bg=T["BG4"],fg=T["TEXT"],font=("Courier New",8),
                       padx=8,pady=4,cursor="hand2")
            b.pack(side="left",padx=3)
            b.bind("<Button-1>",lambda e,p=path:self._add_src(p))
            b.bind("<Enter>",lambda e,w=b:w.configure(bg=T["ACCENT"]))
            b.bind("<Leave>",lambda e,w=b:w.configure(bg=T["BG4"]))
        sf=tk.Frame(f,bg=T["BG3"]); sf.pack(fill="both",expand=True,padx=28,pady=(0,10))
        cols=("Path","Type","Size","Status")
        st=ttk.Style()
        st.configure("Sc.Treeview",background=T["BG3"],foreground=T["TEXT"],
                     fieldbackground=T["BG3"],rowheight=30,font=("Courier New",9))
        st.configure("Sc.Treeview.Heading",background=T["BG2"],foreground=T["CYAN"],
                     font=("Courier New",9,"bold"),relief="flat")
        st.map("Sc.Treeview",background=[("selected",T["ACCENT"])],foreground=[("selected","white")])
        self._stree=ttk.Treeview(sf,columns=cols,show="headings",style="Sc.Treeview",selectmode="browse")
        for c,w in zip(cols,(330,80,120,100)):
            self._stree.heading(c,text=c); self._stree.column(c,width=w,anchor="w")
        ssb=ttk.Scrollbar(sf,orient="vertical",command=self._stree.yview)
        self._stree.configure(yscrollcommand=ssb.set); ssb.pack(side="right",fill="y")
        self._stree.pack(fill="both",expand=True)
        brow=tk.Frame(f,bg=T["BG"]); brow.pack(fill="x",padx=28,pady=(0,8))
        Btn(brow,"➕ Add Folder",cmd=self._add_folder,color=T["ACCENT"],w=140,h=38).pack(side="left",padx=(0,8))
        Btn(brow,"➕ Add File",cmd=self._add_file,color="#3d5a80",w=120,h=38).pack(side="left",padx=(0,8))
        Btn(brow,"🗂 Browse FS",cmd=self._fs_browser,color="#5a3d80",w=130,h=38).pack(side="left",padx=(0,8))
        Btn(brow,"🗑 Remove",cmd=self._rem_src,color="#5e3d3d",w=120,h=38).pack(side="left",padx=(0,8))
        Btn(brow,"💾 Save",cmd=self._save_sources,color=T["GREEN"],w=110,h=38,fg=T["BG"]).pack(side="left")
        self._sz_lbl=tk.Label(f,text="",bg=T["BG"],fg=T["TEXT_DIM"],font=("Courier New",8))
        self._sz_lbl.pack(anchor="w",padx=28,pady=(0,8))
        self._reload_srcs()

    def _reload_srcs(self):
        self._stree.delete(*self._stree.get_children())
        for src in self.cfg.get("sources",[]):
            p=Path(src)
            kind="Folder" if p.is_dir() else "File" if p.is_file() else "Missing"
            status="✅ OK" if p.exists() else "❌ Missing"
            self._stree.insert("","end",values=(src,kind,"…",status))
        threading.Thread(target=self._calc_srcs,daemon=True).start()

    def _calc_srcs(self):
        total=0; rows=self._stree.get_children()
        srcs=self.cfg.get("sources",[])
        for iid,src in zip(rows,srcs):
            sz=calc_folder_size(src); total+=sz
            self.after(0,lambda i=iid,s=sz:self._stree.set(i,"Size",fmt_size(s)))
        self.after(0,lambda:self._sz_lbl.configure(text=f"Total source size: {fmt_size(total)}"))

    def _add_src(self,path):
        if path not in self.cfg["sources"]:
            self.cfg["sources"].append(path); self._reload_srcs()

    def _add_folder(self):
        p=filedialog.askdirectory(title="Select folder to back up")
        if p: self._add_src(p)

    def _add_file(self):
        p=filedialog.askopenfilename(title="Select file to back up")
        if p: self._add_src(p)

    def _fs_browser(self):
        dlg=tk.Toplevel(self); dlg.title("Filesystem Browser")
        dlg.configure(bg=T["BG"]); dlg.geometry("640x520"); dlg.grab_set()
        cur=tk.StringVar(value="/")
        pf=tk.Frame(dlg,bg=T["BG"]); pf.pack(fill="x",padx=16,pady=10)
        tk.Label(pf,text="Path:",bg=T["BG"],fg=T["TEXT"],font=("Courier New",9)).pack(side="left")
        pe=tk.Entry(pf,textvariable=cur,bg=T["BG3"],fg=T["TEXT"],insertbackground=T["TEXT"],
                    font=("Courier New",9),bd=0,highlightthickness=1,
                    highlightbackground=T["BORDER"],highlightcolor=T["ACCENT"])
        pe.pack(side="left",fill="x",expand=True,ipady=4,padx=(6,6))
        lf=tk.Frame(dlg,bg=T["BG3"]); lf.pack(fill="both",expand=True,padx=16,pady=(0,8))
        st=ttk.Style()
        st.configure("FB.Treeview",background=T["BG3"],foreground=T["TEXT"],
                     fieldbackground=T["BG3"],rowheight=26,font=("Courier New",9))
        st.configure("FB.Treeview.Heading",background=T["BG2"],foreground=T["CYAN"],
                     font=("Courier New",9,"bold"),relief="flat")
        fb=ttk.Treeview(lf,columns=("Name","Type","Size"),show="headings",style="FB.Treeview")
        for c,w in zip(("Name","Type","Size"),(340,80,120)):
            fb.heading(c,text=c); fb.column(c,width=w,anchor="w")
        fsb=ttk.Scrollbar(lf,orient="vertical",command=fb.yview)
        fb.configure(yscrollcommand=fsb.set); fsb.pack(side="right",fill="y")
        fb.pack(fill="both",expand=True)
        def load(path):
            fb.delete(*fb.get_children()); p=Path(path)
            if not p.is_dir(): return
            cur.set(str(p))
            if p!=p.parent: fb.insert("","end",iid="__up__",values=("📁  ..(up)","dir",""))
            try:
                entries=sorted(p.iterdir(),key=lambda x:(x.is_file(),x.name.lower()))
                for e in entries:
                    try:
                        if e.is_dir(): fb.insert("","end",values=(f"📁  {e.name}","dir",""))
                        else: fb.insert("","end",values=(f"📄  {e.name}","file",fmt_size(e.stat().st_size)))
                    except PermissionError: fb.insert("","end",values=(f"🔒  {e.name}","locked",""))
            except PermissionError: pass
        def on_dbl(e):
            sel=fb.selection()
            if not sel: return
            iid=sel[0]
            if iid=="__up__": load(str(Path(cur.get()).parent)); return
            name=fb.item(iid)["values"][0].replace("📁  ","").replace("📄  ","").replace("🔒  ","")
            full=Path(cur.get())/name
            if full.is_dir(): load(str(full))
        fb.bind("<Double-1>",on_dbl)
        pe.bind("<Return>",lambda e:load(cur.get()))
        load("/")
        brow=tk.Frame(dlg,bg=T["BG"]); brow.pack(fill="x",padx=16,pady=8)
        def add_sel():
            sel=fb.selection()
            if not sel: self._add_src(cur.get()); dlg.destroy(); return
            for iid in sel:
                name=fb.item(iid)["values"][0].replace("📁  ","").replace("📄  ","").replace("🔒  ","")
                full=str(Path(cur.get())/name)
                self._add_src(full)
            dlg.destroy()
        Btn(brow,"✅  Add Selected / Current Dir",cmd=add_sel,color=T["ACCENT"],w=240,h=38).pack(side="left",padx=(0,8))
        Btn(brow,"Cancel",cmd=dlg.destroy,color=T["BG4"],w=100,h=38,fg=T["TEXT"]).pack(side="left")

    def _rem_src(self):
        sel=self._stree.selection()
        if not sel: return
        path=self._stree.item(sel[0])["values"][0]
        if path in self.cfg["sources"]:
            self.cfg["sources"].remove(path); self._reload_srcs()

    def _save_sources(self):
        save_cfg(self.cfg); self._show_toast("✅ Sources saved!")
        self._sc_sources.configure(text=str(len(self.cfg.get("sources",[]))))

    # ── SETTINGS ─────────────────────────────────────────────────────────────
    def _build_settings(self):
        outer=tk.Frame(self._content,bg=T["BG"]); self._tabs["settings"]=outer
        cv=tk.Canvas(outer,bg=T["BG"],highlightthickness=0)
        sb=ttk.Scrollbar(outer,orient="vertical",command=cv.yview)
        cv.configure(yscrollcommand=sb.set); sb.pack(side="right",fill="y"); cv.pack(fill="both",expand=True)
        f=tk.Frame(cv,bg=T["BG"]); cw=cv.create_window((0,0),window=f,anchor="nw")
        f.bind("<Configure>",lambda e:cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>",lambda e:cv.itemconfig(cw,width=e.width))
        tk.Label(f,text="Settings",bg=T["BG"],fg=T["TEXT"],
                 font=("Georgia",20,"bold")).pack(anchor="w",padx=28,pady=(24,16))
        # Destination
        self._dest_var=tk.StringVar(value=self.cfg.get("backup_dest",""))
        self._settings_row(f,"Backup Destination",self._dest_var,browse=True)
        # Compression
        tk.Label(f,text="COMPRESSION",bg=T["BG"],fg=T["TEXT_DIM"],
                 font=("Courier New",8,"bold"),anchor="w").pack(fill="x",padx=28,pady=(4,2))
        cc=tk.Frame(f,bg=T["BG3"]); cc.pack(fill="x",padx=28,pady=(0,14))
        crow=tk.Frame(cc,bg=T["BG3"]); crow.pack(fill="x",padx=16,pady=12)
        tk.Label(crow,text="Format:",bg=T["BG3"],fg=T["TEXT"],font=("Courier New",9),width=12,anchor="w").pack(side="left")
        self._comp_var=tk.StringVar(value=self.cfg.get("compression","gz"))
        for lbl,val in [("Fast (gz)","gz"),("Small (bz2)","bz2"),("Tiny (xz)","xz"),("None","none")]:
            tk.Radiobutton(crow,text=lbl,variable=self._comp_var,value=val,
                           bg=T["BG3"],fg=T["TEXT"],selectcolor=T["BG4"],
                           activebackground=T["BG3"],activeforeground=T["ACCENT"],
                           font=("Courier New",9)).pack(side="left",padx=10)
        # Exclusions
        tk.Label(f,text="EXCLUDE PATTERNS (one per line, * wildcard OK)",
                 bg=T["BG"],fg=T["TEXT_DIM"],font=("Courier New",8,"bold"),anchor="w").pack(fill="x",padx=28,pady=(4,2))
        ec=tk.Frame(f,bg=T["BG3"]); ec.pack(fill="x",padx=28,pady=(0,14))
        self._excl=tk.Text(ec,bg=T["BG4"],fg=T["TEXT"],font=("Courier New",9),bd=0,height=6,
                           insertbackground=T["TEXT"],highlightthickness=1,
                           highlightbackground=T["BORDER"],highlightcolor=T["ACCENT"])
        self._excl.pack(fill="x",padx=16,pady=12,ipady=4)
        self._excl.insert("1.0","\n".join(self.cfg.get("exclude_patterns",[])))
        # Toggles
        tk.Label(f,text="ADVANCED OPTIONS",bg=T["BG"],fg=T["TEXT_DIM"],
                 font=("Courier New",8,"bold"),anchor="w").pack(fill="x",padx=28,pady=(4,2))
        ac=tk.Frame(f,bg=T["BG3"]); ac.pack(fill="x",padx=28,pady=(0,14))
        self._tvars={}
        for lbl,key in [("Incremental backup (only changed files)","incremental"),
                        ("Verify archive integrity after backup","verify_after"),
                        ("Desktop notifications","notify_desktop"),
                        ("Backup on app close","shutdown_backup"),
                        ("Auto-start backup engine on launch","auto_start_backup"),
                        ("Launch app at system startup","startup_launch")]:
            row=tk.Frame(ac,bg=T["BG3"]); row.pack(fill="x",padx=16,pady=7)
            tk.Label(row,text=lbl,bg=T["BG3"],fg=T["TEXT"],font=("Courier New",9),anchor="w").pack(side="left")
            var=tk.BooleanVar(value=self.cfg.get(key,False))
            self._tvars[key]=var
            Toggle(row,var).pack(side="right")
        mx_row=tk.Frame(ac,bg=T["BG3"]); mx_row.pack(fill="x",padx=16,pady=8)
        tk.Label(mx_row,text="Max backups to keep:",bg=T["BG3"],fg=T["TEXT"],font=("Courier New",9),anchor="w").pack(side="left")
        self._max_var=tk.StringVar(value=str(self.cfg.get("max_backups",20)))
        tk.Entry(mx_row,textvariable=self._max_var,bg=T["BG4"],fg=T["TEXT"],
                 insertbackground=T["TEXT"],font=("Courier New",9),bd=0,width=8,
                 highlightthickness=1,highlightbackground=T["BORDER"],
                 highlightcolor=T["ACCENT"]).pack(side="right",ipady=4)
        Btn(f,"💾  Save All Settings",cmd=self._save_settings,color=T["ACCENT"],w=200,h=44).pack(anchor="w",padx=28,pady=12)

    def _settings_row(self,parent,label,var,browse=False):
        tk.Label(parent,text=label.upper(),bg=T["BG"],fg=T["TEXT_DIM"],
                 font=("Courier New",8,"bold"),anchor="w").pack(fill="x",padx=28,pady=(4,2))
        card=tk.Frame(parent,bg=T["BG3"]); card.pack(fill="x",padx=28,pady=(0,14))
        row=tk.Frame(card,bg=T["BG3"]); row.pack(fill="x",padx=16,pady=12)
        tk.Label(row,text=label+":",bg=T["BG3"],fg=T["TEXT"],font=("Courier New",9),
                 width=20,anchor="w").pack(side="left")
        tk.Entry(row,textvariable=var,bg=T["BG4"],fg=T["TEXT"],insertbackground=T["TEXT"],
                 font=("Courier New",9),bd=0,highlightthickness=1,
                 highlightbackground=T["BORDER"],highlightcolor=T["ACCENT"]).pack(
                 side="left",fill="x",expand=True,ipady=5,padx=(0,8))
        if browse:
            Btn(row,"Browse",cmd=lambda:var.set(filedialog.askdirectory() or var.get()),
                color=T["BG4"],w=80,h=30,fg=T["ACCENT"]).pack(side="left")

    # ── SCHEDULE ─────────────────────────────────────────────────────────────
    def _build_schedule(self):
        f=tk.Frame(self._content,bg=T["BG"]); self._tabs["schedule"]=f
        tk.Label(f,text="Schedule",bg=T["BG"],fg=T["TEXT"],
                 font=("Georgia",20,"bold")).pack(anchor="w",padx=28,pady=(24,16))
        card=tk.Frame(f,bg=T["BG3"]); card.pack(fill="x",padx=28,pady=(0,14))
        self._sched=tk.StringVar(value=self.cfg.get("schedule_mode","interval"))
        for val,lbl in [("interval","⏱  Interval — repeat every N seconds"),
                        ("daily",  "📅  Daily — at a specific time"),
                        ("weekly", "🗓  Weekly — specific day & time")]:
            tk.Radiobutton(card,text=lbl,variable=self._sched,value=val,bg=T["BG3"],
                           fg=T["TEXT"],selectcolor=T["BG4"],activebackground=T["BG3"],
                           activeforeground=T["ACCENT"],font=("Courier New",10),pady=8).pack(anchor="w",padx=20)
        # interval
        ir=tk.Frame(card,bg=T["BG3"]); ir.pack(fill="x",padx=20,pady=6)
        tk.Label(ir,text="Interval (seconds):",bg=T["BG3"],fg=T["TEXT"],
                 font=("Courier New",9),width=22,anchor="w").pack(side="left")
        self._int_var=tk.StringVar(value=str(self.cfg.get("interval",60)))
        tk.Entry(ir,textvariable=self._int_var,bg=T["BG4"],fg=T["TEXT"],
                 insertbackground=T["TEXT"],font=("Courier New",9),width=10,bd=0,
                 highlightthickness=1,highlightbackground=T["BORDER"],
                 highlightcolor=T["ACCENT"]).pack(side="left",ipady=4)
        pr=tk.Frame(card,bg=T["BG3"]); pr.pack(fill="x",padx=20,pady=(0,10))
        tk.Label(pr,text="Quick:",bg=T["BG3"],fg=T["TEXT_DIM"],font=("Courier New",8)).pack(side="left",padx=(0,8))
        for lbl,secs in [("10s",10),("30s",30),("1m",60),("5m",300),
                         ("10m",600),("30m",1800),("1h",3600),("6h",21600),("12h",43200)]:
            b=tk.Label(pr,text=lbl,bg=T["BG4"],fg=T["CYAN"],font=("Courier New",8,"bold"),
                       padx=8,pady=4,cursor="hand2")
            b.pack(side="left",padx=2)
            b.bind("<Button-1>",lambda e,s=secs:(self._int_var.set(str(s)),self._sched.set("interval")))
            b.bind("<Enter>",lambda e,w=b:w.configure(bg=T["ACCENT"],fg="white"))
            b.bind("<Leave>",lambda e,w=b:w.configure(bg=T["BG4"],fg=T["CYAN"]))
        # time
        tr=tk.Frame(card,bg=T["BG3"]); tr.pack(fill="x",padx=20,pady=6)
        tk.Label(tr,text="Daily/Weekly time (HH:MM):",bg=T["BG3"],fg=T["TEXT"],
                 font=("Courier New",9),width=26,anchor="w").pack(side="left")
        self._time_var=tk.StringVar(value=self.cfg.get("schedule_time","02:00"))
        tk.Entry(tr,textvariable=self._time_var,bg=T["BG4"],fg=T["TEXT"],
                 insertbackground=T["TEXT"],font=("Courier New",9),width=8,bd=0,
                 highlightthickness=1,highlightbackground=T["BORDER"],
                 highlightcolor=T["ACCENT"]).pack(side="left",ipady=4)
        wr=tk.Frame(card,bg=T["BG3"]); wr.pack(fill="x",padx=20,pady=(0,14))
        tk.Label(wr,text="Weekly day:",bg=T["BG3"],fg=T["TEXT"],
                 font=("Courier New",9),width=26,anchor="w").pack(side="left")
        self._wday=tk.StringVar(value=str(self.cfg.get("schedule_weekday",0)))
        days=["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
        ttk.Combobox(wr,textvariable=self._wday,
                     values=[f"{i} – {d}" for i,d in enumerate(days)],
                     width=20,font=("Courier New",9)).pack(side="left",ipady=3)
        Btn(f,"💾  Save Schedule",cmd=self._save_sched,color=T["ACCENT"],w=180,h=42).pack(anchor="w",padx=28,pady=12)

    def _save_sched(self):
        self.cfg["schedule_mode"]=self._sched.get()
        try: self.cfg["interval"]=int(self._int_var.get())
        except: messagebox.showerror("Invalid","Interval must be a number"); return
        self.cfg["schedule_time"]=self._time_var.get()
        try: self.cfg["schedule_weekday"]=int(self._wday.get().split("–")[0].strip())
        except: self.cfg["schedule_weekday"]=0
        save_cfg(self.cfg); self._show_toast("✅ Schedule saved!")

    # ── STATISTICS ───────────────────────────────────────────────────────────
    def _build_stats(self):
        f=tk.Frame(self._content,bg=T["BG"]); self._tabs["stats"]=f
        tk.Label(f,text="Statistics",bg=T["BG"],fg=T["TEXT"],
                 font=("Georgia",20,"bold")).pack(anchor="w",padx=28,pady=(24,16))
        tk.Label(f,text="DISK USAGE — BACKUP DESTINATION",bg=T["BG"],fg=T["TEXT_DIM"],
                 font=("Courier New",8,"bold"),anchor="w").pack(fill="x",padx=28,pady=(4,2))
        dc=tk.Frame(f,bg=T["BG3"]); dc.pack(fill="x",padx=28,pady=(0,14))
        self._disk_canvas=tk.Canvas(dc,bg=T["BG3"],height=36,highlightthickness=0)
        self._disk_canvas.pack(fill="x",padx=16,pady=(12,4))
        self._disk_detail=tk.Label(dc,text="",bg=T["BG3"],fg=T["TEXT_DIM"],font=("Courier New",8))
        self._disk_detail.pack(anchor="w",padx=16,pady=(0,10))
        tk.Label(f,text="BACKUP HISTORY",bg=T["BG"],fg=T["TEXT_DIM"],
                 font=("Courier New",8,"bold"),anchor="w").pack(fill="x",padx=28,pady=(4,2))
        hc=tk.Frame(f,bg=T["BG3"]); hc.pack(fill="both",expand=True,padx=28,pady=(0,20))
        self._hist=tk.Text(hc,bg=T["BG3"],fg=T["TEXT"],font=("Courier New",9),bd=0,
                           state="disabled",wrap="none",height=12)
        hsb=ttk.Scrollbar(hc,orient="vertical",command=self._hist.yview)
        self._hist.configure(yscrollcommand=hsb.set); hsb.pack(side="right",fill="y")
        self._hist.pack(fill="both",expand=True,padx=4,pady=4)
        Btn(f,"🔄 Refresh Stats",cmd=self._refresh_stats,color=T["BG4"],w=160,h=38,fg=T["TEXT"]).pack(anchor="w",padx=28,pady=(0,12))

    def _refresh_stats(self):
        dest=Path(self.cfg.get("backup_dest",str(BACKUP_DIR)))
        used,total=get_disk_usage(str(dest)); pct=int(used/total*100) if total else 0
        c=self._disk_canvas; c.delete("all"); w=c.winfo_width() or 600
        col=T["ACCENT2"] if pct>85 else T["YELLOW"] if pct>65 else T["GREEN"]
        c.create_rectangle(0,0,w,36,fill=T["BG4"],outline="")
        c.create_rectangle(0,0,int(w*pct/100),36,fill=col,outline="")
        c.create_text(w//2,18,text=f"{pct}%  ({fmt_size(used)} / {fmt_size(total)})",
                      fill="white",font=("Courier New",9,"bold"))
        self._disk_detail.configure(text=f"Free: {fmt_size(total-used)}")
        files=sorted(dest.glob("backup_*"),reverse=True)
        lines=["  Date/Time              Filename                             Size\n",
               "  "+"─"*75+"\n"]
        total_sz=0
        for fp in files:
            sz=fp.stat().st_size; total_sz+=sz
            mt=datetime.fromtimestamp(fp.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            lines.append(f"  {mt}   {fp.name:<38}{fmt_size(sz):>10}\n")
        lines+=["  "+"─"*75+"\n",
                f"  {len(files)} backups  ·  Total: {fmt_size(total_sz)}\n"]
        self._hist.configure(state="normal")
        self._hist.delete("1.0","end")
        for l in lines: self._hist.insert("end",l)
        self._hist.configure(state="disabled")

    # ── LOGS ─────────────────────────────────────────────────────────────────
    def _build_logs(self):
        f=tk.Frame(self._content,bg=T["BG"]); self._tabs["logs"]=f
        hdr=tk.Frame(f,bg=T["BG"]); hdr.pack(fill="x",padx=28,pady=(24,12))
        tk.Label(hdr,text="Activity Logs",bg=T["BG"],fg=T["TEXT"],
                 font=("Georgia",20,"bold")).pack(side="left")
        brow=tk.Frame(hdr,bg=T["BG"]); brow.pack(side="right")
        Btn(brow,"🔄",cmd=self._refresh_logs,color=T["BG4"],w=50,h=36,fg=T["TEXT"]).pack(side="left",padx=(0,4))
        Btn(brow,"📋 Export",cmd=self._export_logs,color="#3d4a5e",w=110,h=36).pack(side="left",padx=(0,4))
        Btn(brow,"🗑 Clear",cmd=self._clear_logs,color="#5e3d3d",w=100,h=36).pack(side="left")
        ff=tk.Frame(f,bg=T["BG"]); ff.pack(fill="x",padx=28,pady=(0,8))
        tk.Label(ff,text="Filter:",bg=T["BG"],fg=T["TEXT_DIM"],font=("Courier New",9)).pack(side="left")
        self._log_filter=tk.StringVar()
        tk.Entry(ff,textvariable=self._log_filter,bg=T["BG3"],fg=T["TEXT"],
                 insertbackground=T["TEXT"],font=("Courier New",9),bd=0,width=30,
                 highlightthickness=1,highlightbackground=T["BORDER"],
                 highlightcolor=T["ACCENT"]).pack(side="left",ipady=4,padx=8)
        Btn(ff,"Apply",cmd=self._refresh_logs,color=T["ACCENT"],w=80,h=28).pack(side="left")
        lf=tk.Frame(f,bg=T["BG3"]); lf.pack(fill="both",expand=True,padx=28,pady=(0,28))
        self._log=tk.Text(lf,bg=T["BG3"],fg=T["TEXT"],font=("Courier New",9),bd=0,
                          state="disabled",wrap="none",insertbackground=T["TEXT"])
        self._log.tag_configure("ok",   foreground=T["GREEN"])
        self._log.tag_configure("err",  foreground=T["ACCENT2"])
        self._log.tag_configure("warn", foreground=T["YELLOW"])
        self._log.tag_configure("info", foreground=T["TEXT_DIM"])
        lsby=ttk.Scrollbar(lf,orient="vertical",  command=self._log.yview)
        lsbx=ttk.Scrollbar(lf,orient="horizontal",command=self._log.xview)
        self._log.configure(yscrollcommand=lsby.set,xscrollcommand=lsbx.set)
        lsby.pack(side="right",fill="y"); lsbx.pack(side="bottom",fill="x")
        self._log.pack(fill="both",expand=True)
        self._refresh_logs()

    def _refresh_logs(self):
        flt=getattr(self,"_log_filter",None)
        flt=flt.get().strip().lower() if flt else ""
        self._log.configure(state="normal"); self._log.delete("1.0","end")
        if LOG_FILE.exists():
            lines=LOG_FILE.read_text().splitlines()
            if flt: lines=[l for l in lines if flt in l.lower()]
            for line in reversed(lines[-400:]):
                tag="ok"  if any(x in line.lower() for x in ["created","restored","ok"]) else \
                    "err" if any(x in line.lower() for x in ["fail","error","corrupt"]) else \
                    "warn" if any(x in line.lower() for x in ["warn","skip","missing"]) else "info"
                self._log.insert("end",line+"\n",tag)
        else:
            self._log.insert("end","No logs yet.")
        self._log.configure(state="disabled")

    def _clear_logs(self):
        if messagebox.askyesno("Clear","Delete all log entries?"):
            LOG_FILE.write_text(""); self._refresh_logs()

    def _export_logs(self):
        p=filedialog.asksaveasfilename(defaultextension=".txt",
            filetypes=[("Text","*.txt"),("All","*")],
            initialfile=f"backup_log_{datetime.now().strftime('%Y%m%d')}.txt")
        if p and LOG_FILE.exists():
            shutil.copy(LOG_FILE,p); self._show_toast(f"✅ Exported!")

    # ── TAB NAV ──────────────────────────────────────────────────────────────
    def _show(self,key):
        for k,f in self._tabs.items(): f.pack_forget()
        self._tabs[key].pack(fill="both",expand=True); self._cur=key
        for k,b in self._nav.items():
            b.configure(fg=T["ACCENT"] if k==key else T["TEXT_DIM"])
        if key=="logs":   self._refresh_logs()
        if key=="stats":  self.after(100,self._refresh_stats)
        if key=="sources":self._reload_srcs()

    # ── BACKUP CONTROLS ──────────────────────────────────────────────────────
    def _start_backup(self):
        if self._backup_on: return
        engine.start(self.cfg); self._backup_on=True
        self._btn_toggle.set("⏹  Stop Auto Backup",T["ACCENT2"])
        self._dot.configure(text="⬤  Running",fg=T["GREEN"])
        write_log(f"Auto-backup started. mode={self.cfg.get('schedule_mode')} interval={self.cfg.get('interval')}s")

    def _toggle_backup(self):
        if self._backup_on:
            engine.stop(); self._backup_on=False
            self._btn_toggle.set("▶  Start Auto Backup",T["ACCENT"])
            self._dot.configure(text="⬤  Idle",fg=T["TEXT_DIM"])
            self._next_lbl.configure(text=""); self._progress["value"]=0
            self._prog_lbl.configure(text="–"); write_log("Auto-backup stopped.")
        else:
            self._start_backup()

    def _backup_now(self):
        if not self.cfg.get("sources"):
            messagebox.showwarning("No Sources","Add sources in the Sources tab first."); return
        self._dot.configure(text="⬤  Backing up…",fg=T["YELLOW"])
        engine.run_once(self.cfg)

    def _open_folder(self):
        dest=self.cfg.get("backup_dest",str(BACKUP_DIR))
        os.makedirs(dest,exist_ok=True); subprocess.Popen(["xdg-open",dest])

    # ── ENGINE CALLBACKS ─────────────────────────────────────────────────────
    def _eng_start(self):
        self._dot.configure(text="⬤  Backing up…",fg=T["YELLOW"])
        self._progress.configure(mode="indeterminate"); self._progress.start(12)

    def _eng_prog(self,src,pct):
        self._src_lbl.configure(text=f"→ {Path(src).name}")
        self._progress.stop(); self._progress.configure(mode="determinate",value=pct)

    def _eng_done(self,fname,size,ok,msg):
        self._progress.stop(); self._progress.configure(mode="determinate",value=0)
        self._src_lbl.configure(text="")
        if ok:
            self._dot.configure(text="⬤  Running" if self._backup_on else "⬤  Done",fg=T["GREEN"])
            self._show_toast(f"✅  Backup complete · {fmt_size(size)}")
        else:
            self._dot.configure(text="⬤  Error",fg=T["ACCENT2"])
            self._show_toast(f"❌  Failed: {msg[:50]}")
        self._refresh_list()

    def _eng_tick(self,rem,iv):
        self._progress.stop(); pct=int((1-rem/iv)*100)
        self._progress.configure(mode="determinate",value=pct)
        m,s=divmod(rem,60); h,m=divmod(m,60)
        txt=f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
        self._prog_lbl.configure(text=txt); self._next_lbl.configure(text=f"Next: {txt}")

    def _eng_verify(self,ok):
        self._show_toast("✅ Archive valid" if ok else "❌ Archive CORRUPT!")

    # ── ARCHIVE ACTIONS ──────────────────────────────────────────────────────
    def _refresh_list(self):
        self._tree.delete(*self._tree.get_children())
        dest=Path(self.cfg.get("backup_dest",str(BACKUP_DIR)))
        if not dest.exists(): return
        files=sorted(dest.glob("backup_*"),reverse=True); total=0
        for fp in files:
            sz=fp.stat().st_size; total+=sz
            mt=datetime.fromtimestamp(fp.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            self._tree.insert("","end",values=(fp.name,fmt_size(sz),mt,"–"))
        self._sc_total.configure(text=str(len(files)))
        self._sc_size.configure(text=fmt_size(total))
        self._sc_sources.configure(text=str(len(self.cfg.get("sources",[]))))
        if files:
            self._sc_last.configure(text=datetime.fromtimestamp(
                files[0].stat().st_mtime).strftime("%H:%M:%S"))

    def _sel_path(self):
        sel=self._tree.selection()
        if not sel: return None
        fname=self._tree.item(sel[0])["values"][0]
        return Path(self.cfg.get("backup_dest",str(BACKUP_DIR)))/fname

    def _ctx_show(self,e):
        row=self._tree.identify_row(e.y)
        if row: self._tree.selection_set(row); self._ctx.post(e.x_root,e.y_root)

    def _preview(self,e=None):
        p=self._sel_path()
        if p: ArchivePreviewDialog(self,str(p))

    def _restore(self):
        p=self._sel_path()
        if p: RestoreDialog(self,str(p),lambda ok:self._show_toast("✅ Restored!" if ok else "❌ Failed"))

    def _verify(self):
        p=self._sel_path()
        if not p: return
        sel=self._tree.selection(); self._show_toast("🔍 Verifying…")
        def run():
            ok=verify_archive(str(p)); result="✅ VALID" if ok else "❌ CORRUPT"
            write_log(f"Verify {p.name}: {result}")
            self.after(0,lambda:(self._tree.set(sel[0],"Verified",result),
                                 self._show_toast(f"Archive {result}")))
        threading.Thread(target=run,daemon=True).start()

    def _delete(self):
        p=self._sel_path()
        if not p: return
        if messagebox.askyesno("Delete",f"Delete:\n{p.name}?"):
            p.unlink(missing_ok=True); write_log(f"Deleted: {p.name}"); self._refresh_list()

    # ── SAVE SETTINGS ────────────────────────────────────────────────────────
    def _save_settings(self):
        self.cfg["backup_dest"]=self._dest_var.get().strip()
        self.cfg["compression"]=self._comp_var.get()
        self.cfg["exclude_patterns"]=[l.strip() for l in
                                      self._excl.get("1.0","end").splitlines() if l.strip()]
        try: self.cfg["max_backups"]=int(self._max_var.get())
        except: messagebox.showerror("Invalid","Max backups must be a number"); return
        for key,var in self._tvars.items(): self.cfg[key]=var.get()
        set_autostart(self.cfg.get("startup_launch",False),__file__)
        save_cfg(self.cfg); self._show_toast("✅ Settings saved!"); write_log("Settings updated.")

    # ── TOAST / LOOPS / CLOSE ────────────────────────────────────────────────
    def _show_toast(self,msg):
        t=tk.Toplevel(self); t.overrideredirect(True); t.attributes("-topmost",True)
        x=self.winfo_x()+self.winfo_width()-340; y=self.winfo_y()+self.winfo_height()-70
        t.geometry(f"320x44+{x}+{y}"); t.configure(bg=T["BG3"])
        tk.Label(t,text=msg,bg=T["BG3"],fg=T["TEXT"],font=("Courier New",10),padx=16).pack(expand=True)
        t.after(3000,t.destroy)

    def _disk_loop(self):
        dest=self.cfg.get("backup_dest",str(BACKUP_DIR))
        try:
            used,total=get_disk_usage(dest); pct=int(used/total*100) if total else 0
            col=T["ACCENT2"] if pct>85 else T["YELLOW"] if pct>65 else T["TEXT_DIM"]
            self._disk_lbl.configure(text=f"Disk: {fmt_size(used)}/{fmt_size(total)} ({pct}%)",fg=col)
        except: pass
        self.after(15000,self._disk_loop)

    def _update_loop(self):
        if self._backup_on and not engine.running:
            self._backup_on=False
            self._btn_toggle.set("▶  Start Auto Backup",T["ACCENT"])
            self._dot.configure(text="⬤  Idle",fg=T["TEXT_DIM"])
        self.after(2000,self._update_loop)

    def _on_close(self):
        if self.cfg.get("shutdown_backup") and self.cfg.get("sources"):
            write_log("App closing — running final backup")
            engine.run_once(self.cfg); time.sleep(0.8)
        engine.stop(); self.destroy()

if __name__=="__main__":
    App().mainloop()
