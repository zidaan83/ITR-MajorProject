import os
import sys
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Optional libs (graceful fallback)
PIL_OK = True
DND_OK = True
try:
    from PIL import Image, ImageTk
except Exception:
    PIL_OK = False
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:
    DND_OK = False

import vlc

# ---------- helpers ----------
def fmt_time(ms: int) -> str:
    if ms is None or ms < 0:
        return "00:00"
    s = ms // 1000
    return f"{s // 60:02}:{s % 60:02}"

class MiniVLC:
    def __init__(self, root):
        self.root = root
        self.root.title("🎬 Mini VLC")
        self.root.geometry("1000x650")
        self.root.minsize(820, 520)
        self.root.configure(bg="#0f1115")

        self.vlc_instance = vlc.Instance()
        self.player = self.vlc_instance.media_player_new()

        self.playlist = []
        self.current_index = -1
        self.length_ms = 0
        self.poll_job = None
        self.user_dragging_seek = False
        self.fullscreen = False
        self.muted = False
        self.saved_volume = 80
        self.is_playing = False 

        self._setup_styles()
        self._load_images()
        self._build_ui()
        self._bind_shortcuts()
        self._embed_video_after_ready()

        if DND_OK:
            try:
                self.root.drop_target_register(DND_FILES)
                self.root.dnd_bind('<<Drop>>', self._on_drop)
            except Exception:
                pass

    # ---------- UI setup ----------
    def _setup_styles(self):
        style = ttk.Style()
        try:
            style.theme_use('clam')
        except Exception:
            pass
        style.configure(".", background="#0f1115", foreground="#e6e6e6", font=("Segoe UI", 10))
        style.configure("Title.TLabel", background="#0f1115", foreground="#e6e6e6", font=("Segoe UI", 16, "bold"))
        style.configure("Card.TFrame", background="#151922")
        style.configure("Bar.TFrame", background="#0f1115")
        style.configure("TButton", background="#1DB954", foreground="white", padding=8, font=("Segoe UI", 10, "bold"))
        style.map("TButton", background=[("active", "#1ed760")])
        style.configure("Alt.TButton", background="#2b3240")
        style.map("Alt.TButton", background=[("active", "#343d4e")])
        style.configure("TScale", background="#151922", troughcolor="#2a2f3a")

    def _load_images(self):
        global PIL_OK
        if not PIL_OK:
            return
        
        size = (24, 24)
        try:
            # Create a path for the icons folder
            base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
            icons_path = os.path.join(base_path, "icons")
            
            self.play_img = ImageTk.PhotoImage(Image.open(os.path.join(icons_path, "play.png")).resize(size, Image.LANCZOS))
            self.pause_img = ImageTk.PhotoImage(Image.open(os.path.join(icons_path, "pause.png")).resize(size, Image.LANCZOS))
            self.stop_img = ImageTk.PhotoImage(Image.open(os.path.join(icons_path, "stop.png")).resize(size, Image.LANCZOS))
            self.prev_img = ImageTk.PhotoImage(Image.open(os.path.join(icons_path, "prev.png")).resize(size, Image.LANCZOS))
            self.next_img = ImageTk.PhotoImage(Image.open(os.path.join(icons_path, "next.png")).resize(size, Image.LANCZOS))
            self.fullscreen_img = ImageTk.PhotoImage(Image.open(os.path.join(icons_path, "fullscreen.png")).resize(size, Image.LANCZOS))
            self.mute_img = ImageTk.PhotoImage(Image.open(os.path.join(icons_path, "mute.png")).resize(size, Image.LANCZOS))
            self.unmute_img = ImageTk.PhotoImage(Image.open(os.path.join(icons_path, "unmute.png")).resize(size, Image.LANCZOS))
        except Exception as e:
            print(f"Error loading images: {e}. Falling back to text.")
            PIL_OK = False

    def _build_ui(self):
        top = ttk.Frame(self.root, style="Bar.TFrame")
        top.pack(fill="x", padx=14, pady=(10, 6))
        ttk.Label(top, text="🎬 Mini VLC", style="Title.TLabel").pack(side="left")
        ttk.Button(top, text="📂 Open", command=self.open_files, style="Alt.TButton").pack(side="right", padx=4)
        ttk.Button(top, text="📁 Folder", command=self.open_folder, style="Alt.TButton").pack(side="right", padx=4)

        main = ttk.Frame(self.root)
        main.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        left = ttk.Frame(main, style="Card.TFrame")
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))

        self.video_area = tk.Frame(left, bg="black")
        self.video_area.pack(fill="both", expand=True, padx=12, pady=12)

        ctrl_card = ttk.Frame(left, style="Card.TFrame")
        ctrl_card.pack(fill="x", padx=12, pady=(0, 12))

        times = ttk.Frame(ctrl_card, style="Card.TFrame")
        times.pack(fill="x", padx=12, pady=(10, 0))
        self.lbl_cur = ttk.Label(times, text="00:00")
        self.lbl_tot = ttk.Label(times, text="00:00")
        self.lbl_cur.pack(side="left")
        self.lbl_tot.pack(side="right")

        self.seek = ttk.Scale(ctrl_card, from_=0, to=100, orient="horizontal",
                              command=self._on_seek_drag)
        self.seek.pack(fill="x", padx=12, pady=(4, 10))
        self.seek.bind("<Button-1>", lambda e: self._set_drag(True))
        self.seek.bind("<ButtonRelease-1>", lambda e: self._set_drag(False, commit=True))

        row = ttk.Frame(ctrl_card, style="Card.TFrame")
        row.pack(fill="x", padx=12, pady=(4, 12))

        if PIL_OK:
            self.prev_btn = ttk.Button(row, image=self.prev_img, command=self.prev, style="Alt.TButton")
            self.play_btn = ttk.Button(row, image=self.play_img, command=self.play_pause)
            self.stop_btn = ttk.Button(row, image=self.stop_img, command=self.stop, style="Alt.TButton")
            self.next_btn = ttk.Button(row, image=self.next_img, command=self.next, style="Alt.TButton")
            self.fs_btn = ttk.Button(row, image=self.fullscreen_img, command=self.toggle_fullscreen, style="Alt.TButton")
            self.mute_btn = ttk.Button(row, image=self.unmute_img, command=self.toggle_mute, style="Alt.TButton")
            
            self.prev_btn.pack(side="left", padx=4)
            self.play_btn.pack(side="left", padx=4)
            self.stop_btn.pack(side="left", padx=4)
            self.next_btn.pack(side="left", padx=4)
            self.fs_btn.pack(side="right", padx=4)
            
        else:
            self.prev_btn = ttk.Button(row, text="⏮", width=4, style="Alt.TButton", command=self.prev)
            self.play_btn = ttk.Button(row, text="▶/⏸", width=6, command=self.play_pause)
            self.stop_btn = ttk.Button(row, text="⏹", width=4, style="Alt.TButton", command=self.stop)
            self.next_btn = ttk.Button(row, text="⏭", width=4, style="Alt.TButton", command=self.next)
            self.fs_btn = ttk.Button(row, text="⛶ Fullscreen", style="Alt.TButton", command=self.toggle_fullscreen)
            self.mute_btn = ttk.Button(row, text="🔇/🔊", width=5, style="Alt.TButton", command=self.toggle_mute)
            
            self.prev_btn.pack(side="left", padx=4)
            self.play_btn.pack(side="left", padx=4)
            self.stop_btn.pack(side="left", padx=4)
            self.next_btn.pack(side="left", padx=4)
            self.fs_btn.pack(side="right", padx=4)

        # volume/mute
        volrow = ttk.Frame(ctrl_card, style="Card.TFrame")
        volrow.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Label(volrow, text="🔊").pack(side="left")
        self.vol = ttk.Scale(volrow, from_=0, to=100, orient="horizontal", command=self._set_volume)
        self.vol.set(self.saved_volume)
        self._set_volume(self.saved_volume)
        self.vol.pack(side="left", fill="x", expand=True, padx=8)
        self.mute_btn.pack(side="right")

        # playlist card
        right = ttk.Frame(main, style="Card.TFrame")
        right.pack(side="left", fill="both", expand=False, padx=(8, 0))
        header = ttk.Frame(right, style="Card.TFrame")
        header.pack(fill="x", padx=10, pady=(10, 0))
        ttk.Label(header, text="Playlist", font=("Segoe UI", 11, "bold")).pack(side="left")

        lstwrap = ttk.Frame(right, style="Card.TFrame")
        lstwrap.pack(fill="both", expand=True, padx=10, pady=10)
        self.listbox = tk.Listbox(lstwrap, bg="#0f131a", fg="#e6e6e6",
                                  selectbackground="#1DB954", activestyle="none",
                                  highlightthickness=0, bd=0, font=("Segoe UI", 10))
        self.listbox.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(lstwrap, orient="vertical", command=self.listbox.yview)
        sb.pack(side="right", fill="y")
        self.listbox.config(yscrollcommand=sb.set)
        self.listbox.bind("<Double-Button-1>", lambda e: self.play_selected())
        self.listbox.bind("<Return>", lambda e: self.play_selected())

        pbtns = ttk.Frame(right, style="Card.TFrame")
        pbtns.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(pbtns, text="＋ Add", style="Alt.TButton", command=self.open_files).pack(side="left", padx=4)
        ttk.Button(pbtns, text="📁 Folder", style="Alt.TButton", command=self.open_folder).pack(side="left", padx=4)
        ttk.Button(pbtns, text="🗑 Remove", style="Alt.TButton", command=self.remove_selected).pack(side="right", padx=4)
        ttk.Button(pbtns, text="🧹 Clear", style="Alt.TButton", command=self.clear_playlist).pack(side="right", padx=4)

        # status bar
        status = ttk.Frame(self.root, style="Bar.TFrame")
        status.pack(fill="x")
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(status, textvariable=self.status_var, font=("Segoe UI", 9)).pack(anchor="w", padx=14, pady=6)

    def _bind_shortcuts(self):
        self.root.bind("<space>", lambda e: self.play_pause())
        self.root.bind("<Left>", lambda e: self.seek_relative(-5))
        self.root.bind("<Right>", lambda e: self.seek_relative(+5))
        self.root.bind("<Up>", lambda e: self._nudge_volume(+5))
        self.root.bind("<Down>", lambda e: self._nudge_volume(-5))
        self.root.bind("<f>", lambda e: self.toggle_fullscreen())
        self.root.bind("<Escape>", lambda e: self._exit_fullscreen_if_needed())
        self.root.bind("<Control-o>", lambda e: self.open_files())
        self.root.bind("<Control-Delete>", lambda e: self.remove_selected())
        self.root.bind("<Prior>", lambda e: self.prev())
        self.root.bind("<Next>", lambda e: self.next())

    def _embed_video_after_ready(self):
        self.root.after(200, self._try_embed)

    def _try_embed(self):
        try:
            wid = self.video_area.winfo_id()
            if sys.platform.startswith("win"):
                self.player.set_hwnd(wid)
            elif sys.platform == "darwin":
                self.player.set_nsobject(wid)
            else:
                self.player.set_xwindow(wid)
        except Exception:
            self.root.after(200, self._try_embed)

    # ---------- playlist ----------
    def open_files(self):
        files = filedialog.askopenfilenames(
            title="Open Media",
            filetypes=[("Media files", "*.*")])
        if not files:
            return
        added = 0
        for f in files:
            if f not in self.playlist:
                self.playlist.append(f)
                self.listbox.insert(tk.END, os.path.basename(f))
                added += 1
        self.status_var.set(f"Added {added} file(s).")
        if self.current_index == -1 and self.playlist:
            self.current_index = 0

    def open_folder(self):
        folder = filedialog.askdirectory(title="Open Folder")
        if not folder:
            return
        exts = (".mp4", ".mkv", ".avi", ".mov", ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg")
        items = []
        for root_, _, files in os.walk(folder):
            for name in files:
                if name.lower().endswith(exts):
                    items.append(os.path.join(root_, name))
        if not items:
            messagebox.showinfo("No media", "No supported media found in this folder.")
            return
        added = 0
        for p in items:
            if p not in self.playlist:
                self.playlist.append(p)
                self.listbox.insert(tk.END, os.path.basename(p))
                added += 1
        self.status_var.set(f"Added {added} file(s) from folder.")
        if self.current_index == -1 and self.playlist:
            self.current_index = 0

    def remove_selected(self):
        sel = list(self.listbox.curselection())
        if not sel:
            return
        for idx in reversed(sel):
            real = idx
            if real == self.current_index:
                self.stop()
                self.current_index = -1
            del self.playlist[real]
            self.listbox.delete(idx)
        
        if self.playlist:
            self.current_index = min(self.current_index if self.current_index != -1 else 0,
                                     len(self.playlist) - 1)
        else:
            self.current_index = -1
        self.status_var.set("Removed selection.")

    def clear_playlist(self):
        self.stop()
        self.playlist.clear()
        self.listbox.delete(0, tk.END)
        self.current_index = -1
        self.status_var.set("Playlist cleared.")

    def play_selected(self):
        try:
            idx = self.listbox.curselection()[0]
        except Exception:
            return
        self.current_index = idx
        self._load_and_play_current()

    # ---------- playback ----------
    def _load_and_play_current(self):
        if self.current_index < 0 or self.current_index >= len(self.playlist):
            return
        path = self.playlist[self.current_index]
        try:
            media = self.vlc_instance.media_new(path)
            self.player.set_media(media)
            self.player.play()
            self.is_playing = True
            if PIL_OK:
                self.play_btn.config(image=self.pause_img)
            else:
                self.play_btn.config(text="⏸")
            self.status_var.set(f"Playing: {os.path.basename(path)}")
            self.root.after(300, self._update_total_length)
            self._start_poll()
        except Exception as e:
            messagebox.showerror("Playback error", str(e))

    def play_pause(self):
        if self.player.get_state() in (vlc.State.NothingSpecial, vlc.State.Stopped) and self.playlist:
            if self.current_index == -1:
                self.current_index = 0
            self._load_and_play_current()
            return
        
        self.player.pause()
        self.is_playing = self.player.get_state() == vlc.State.Playing
        
        if PIL_OK:
            if self.is_playing:
                self.play_btn.config(image=self.pause_img)
            else:
                self.play_btn.config(image=self.play_img)
        else:
            if self.is_playing:
                self.play_btn.config(text="⏸")
            else:
                self.play_btn.config(text="▶")
        
        self.root.after(150, self._update_status_from_state)

    def stop(self):
        try:
            self.player.stop()
        except Exception:
            pass
        self._stop_poll()
        self.seek.set(0)
        self.lbl_cur.config(text="00:00")
        self.lbl_tot.config(text="00:00")
        self.length_ms = 0
        self.is_playing = False
        if PIL_OK:
            self.play_btn.config(image=self.play_img)
        else:
            self.play_btn.config(text="▶/⏸")
        self.status_var.set("Stopped")

    def next(self):
        if not self.playlist:
            return
        self.current_index = (self.current_index + 1) % len(self.playlist)
        self._load_and_play_current()
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(self.current_index)
        self.listbox.see(self.current_index)

    def prev(self):
        if not self.playlist:
            return
        self.current_index = (self.current_index - 1) % len(self.playlist)
        self._load_and_play_current()
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(self.current_index)
        self.listbox.see(self.current_index)

    # ---------- time/seek ----------
    def _update_total_length(self):
        ms = self.player.get_length()
        if ms and ms > 0:
            self.length_ms = ms
            self.seek.configure(to=ms)
            self.lbl_tot.config(text=fmt_time(ms))
        else:
            self.root.after(300, self._update_total_length)

    def _start_poll(self):
        self._stop_poll()
        self.poll_job = self.root.after(250, self._poll)

    def _stop_poll(self):
        if self.poll_job:
            self.root.after_cancel(self.poll_job)
            self.poll_job = None

    def _poll(self):
        state = self.player.get_state()
        if state == vlc.State.Ended:
            self.next()
            return
        if not self.user_dragging_seek:
            cur = self.player.get_time()
            if cur is None:
                cur = 0
            self.seek.set(cur)
            self.lbl_cur.config(text=fmt_time(cur))
            if self.length_ms <= 0:
                self._update_total_length()
        self.poll_job = self.root.after(250, self._poll)

    def _on_seek_drag(self, _val):
        if self.user_dragging_seek:
            self.lbl_cur.config(text=fmt_time(int(float(self.seek.get()))))

    def _set_drag(self, dragging: bool, commit: bool = False):
        self.user_dragging_seek = dragging
        if commit:
            try:
                t = int(float(self.seek.get()))
                self.player.set_time(t)
            except Exception:
                pass

    def seek_relative(self, seconds: int):
        if self.length_ms <= 0:
            return
        cur = self.player.get_time() or 0
        new_ms = max(0, min(self.length_ms - 500, cur + seconds * 1000))
        self.player.set_time(new_ms)
        self.seek.set(new_ms)
        self.lbl_cur.config(text=fmt_time(new_ms))

    # ---------- volume ----------
    def _set_volume(self, val):
        try:
            v = int(float(val))
        except Exception:
            v = 80
        self.player.audio_set_volume(v)
        if not self.muted:
            self.saved_volume = v

    def _nudge_volume(self, delta):
        v = max(0, min(100, int(self.vol.get()) + delta))
        self.vol.set(v)
        self._set_volume(v)

    def toggle_mute(self):
        self.muted = not self.muted
        self.player.audio_toggle_mute()
        if PIL_OK:
            if self.muted:
                self.mute_btn.config(image=self.mute_img)
            else:
                self.mute_btn.config(image=self.unmute_img)
        else:
            self.mute_btn.config(text="🔇" if self.muted else "🔊")
        
        if self.muted:
            self.saved_volume = int(self.vol.get())
            self.vol.set(0)
        else:
            self.vol.set(self.saved_volume)

    # ---------- fullscreen ----------
    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        self.root.attributes("-fullscreen", self.fullscreen)

    def _exit_fullscreen_if_needed(self):
        if self.fullscreen:
            self.toggle_fullscreen()

    # ---------- status ----------
    def _update_status_from_state(self):
        st = self.player.get_state()
        name = {
            vlc.State.Playing: "Playing",
            vlc.State.Paused: "Paused",
            vlc.State.Stopped: "Stopped",
        }.get(st, str(st))
        self.status_var.set(name)

    # ---------- drag & drop ----------
    def _on_drop(self, event):
        raw = event.data
        items = []
        cur = ""
        in_brace = False
        for ch in raw:
            if ch == "{":
                in_brace = True
                cur = ""
            elif ch == "}":
                in_brace = False
                items.append(cur)
                cur = ""
            elif ch == " " and not in_brace:
                if cur:
                    items.append(cur)
                    cur = ""
            else:
                cur += ch
        if cur:
            items.append(cur)
        
        exts = (".mp4", ".mkv", ".avi", ".mov", ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg")
        to_add = []
        for p in items:
            if os.path.isdir(p):
                for r, _, fs in os.walk(p):
                    for nm in fs:
                        if nm.lower().endswith(exts):
                            to_add.append(os.path.join(r, nm))
            elif os.path.isfile(p) and p.lower().endswith(exts):
                to_add.append(p)
        if to_add:
            added = 0
            for f in to_add:
                if f not in self.playlist:
                    self.playlist.append(f)
                    self.listbox.insert(tk.END, os.path.basename(f))
                    added += 1
            self.status_var.set(f"Added {added} item(s) by drag & drop.")
            if self.current_index == -1:
                self.current_index = 0

# ---------- run ----------
def main():
    if DND_OK:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    app = MiniVLC(root)
    root.mainloop()

if __name__ == "__main__":
    main()