# -*- coding: utf-8 -*-
"""Course Video Replacer - the window.

Everything the console version does, with the two things a console cannot do
well: picking a voice by hearing it, and reading the English before it is spoken
in a panel you can type into.

Built on tkinter, which comes with Python. Nothing to install for the window
itself - the only optional install is the local cloned voice.

The pipeline is not duplicated here. replacer.convert() does the work and this
hands it two things: somewhere to print, and a way to ask. That is why fixing
the pipeline fixes both ways of running it.
"""
import json, os, queue, subprocess, sys, threading, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

import replacer as R

PRESETS = ["onyx", "ash", "echo", "ballad", "verse", "sage",
           "alloy", "fable", "coral", "nova", "shimmer"]

BG, PAN, LINE = "#0d1118", "#161d2b", "#2a3547"
TXT, DIM, OK, GOLD, RED = "#eef2fb", "#93a1bd", "#31e0c0", "#ffc861", "#ff6b78"


def play(path):
    """Preview a sample. No player is bundled - Windows opens whatever you use."""
    try:
        os.startfile(path)
    except Exception:
        subprocess.Popen(["cmd", "/c", "start", "", path], shell=False)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Course Video Replacer")
        self.configure(bg=BG)
        self.geometry("980x760")
        self.minsize(880, 640)
        self.cfg = R.config()
        self.q = queue.Queue()
        self.worker = None
        self.answer = queue.Queue()      # the review panel's reply to the pipeline
        self._skin()
        self._build()
        self.after(80, self._drain)

    # ----------------------------------------------------------- looks
    def _skin(self):
        st = ttk.Style(self)
        try: st.theme_use("clam")
        except Exception: pass
        st.configure(".", background=BG, foreground=TXT, fieldbackground=PAN,
                     bordercolor=LINE, lightcolor=LINE, darkcolor=LINE)
        st.configure("TFrame", background=BG)
        st.configure("Card.TFrame", background=PAN, relief="flat")
        st.configure("TLabel", background=BG, foreground=TXT, font=("Segoe UI", 10))
        st.configure("Card.TLabel", background=PAN, foreground=TXT, font=("Segoe UI", 10))
        st.configure("Dim.TLabel", background=BG, foreground=DIM, font=("Segoe UI", 9))
        st.configure("CardDim.TLabel", background=PAN, foreground=DIM, font=("Segoe UI", 9))
        st.configure("H.TLabel", background=BG, foreground=TXT, font=("Segoe UI Semibold", 11))
        st.configure("TButton", font=("Segoe UI", 10), padding=(12, 6))
        st.configure("Go.TButton", font=("Segoe UI Semibold", 12), padding=(20, 11))
        st.configure("TCheckbutton", background=BG, foreground=TXT, font=("Segoe UI", 10))
        st.configure("Card.TCheckbutton", background=PAN, foreground=TXT)
        st.configure("TEntry", padding=6)
        st.map("TButton", background=[("active", LINE)])

    def _row(self, parent, label, hint=""):
        ttk.Label(parent, text=label, style="H.TLabel").pack(anchor="w", pady=(14, 2))
        if hint:
            ttk.Label(parent, text=hint, style="Dim.TLabel").pack(anchor="w", pady=(0, 4))
        f = ttk.Frame(parent); f.pack(fill="x")
        return f

    # ----------------------------------------------------------- layout
    def _build(self):
        wrap = ttk.Frame(self, padding=18); wrap.pack(fill="both", expand=True)
        ttk.Label(wrap, text="Course Video Replacer",
                  font=("Segoe UI Semibold", 18)).pack(anchor="w")
        ttk.Label(wrap, text="Your lecture, in English, still in step with the picture. "
                             "The video never leaves this computer.",
                  style="Dim.TLabel").pack(anchor="w", pady=(0, 6))

        nb = ttk.Notebook(wrap); nb.pack(fill="both", expand=True, pady=(10, 0))
        one = ttk.Frame(nb, padding=16); nb.add(one, text="  Convert  ")
        two = ttk.Frame(nb, padding=16); nb.add(two, text="  Voice  ")
        three = ttk.Frame(nb, padding=16); nb.add(three, text="  Words to keep right  ")
        self.nb = nb

        # ---------------- convert ----------------
        f = self._row(one, "The video", "The mp4 you recorded. Nothing about it is re-encoded.")
        self.v_in = tk.StringVar()
        ttk.Entry(f, textvariable=self.v_in).pack(side="left", fill="x", expand=True)
        ttk.Button(f, text="Choose…", command=self.pick_in).pack(side="left", padx=(8, 0))

        f = self._row(one, "Where the results go")
        self.v_out = tk.StringVar(value=os.path.join(HERE, "output"))
        ttk.Entry(f, textvariable=self.v_out).pack(side="left", fill="x", expand=True)
        ttk.Button(f, text="Choose…", command=self.pick_out).pack(side="left", padx=(8, 0))

        f = self._row(one, "Before it speaks")
        self.v_review = tk.BooleanVar(value=bool(self.cfg.get("review", True)))
        ttk.Checkbutton(f, variable=self.v_review,
                        text="Show me every line first, so I can fix a word before it is spoken"
                        ).pack(anchor="w")

        f = self._row(one, "How much a line may be sped up to fit",
                      "English is never the same length as what you said. Past about 125% it is audible.")
        self.v_tempo = tk.DoubleVar(value=float(self.cfg.get("max_tempo", 1.20)))
        self.tempo_lbl = ttk.Label(f, text="", style="Dim.TLabel")
        s = ttk.Scale(f, from_=1.0, to=1.5, variable=self.v_tempo, orient="horizontal",
                      command=lambda _=None: self.tempo_lbl.config(
                          text="  %d%%" % round(self.v_tempo.get() * 100)))
        s.pack(side="left", fill="x", expand=True); self.tempo_lbl.pack(side="left")
        self.tempo_lbl.config(text="  %d%%" % round(self.v_tempo.get() * 100))

        go = ttk.Frame(one); go.pack(fill="x", pady=(20, 6))
        self.v_remember = tk.BooleanVar(value=True)
        ttk.Checkbutton(go, variable=self.v_remember,
                        text="Remember these settings").pack(side="right", padx=6)
        self.btn = ttk.Button(go, text="Start", style="Go.TButton", command=self.start)
        self.btn.pack(side="left")
        self.status = ttk.Label(go, text="", style="Dim.TLabel")
        self.status.pack(side="left", padx=14)

        self.logbox = tk.Text(one, height=12, bg="#05080f", fg="#cfe0ff", insertbackground=TXT,
                              relief="flat", font=("Consolas", 9), wrap="word",
                              highlightthickness=1, highlightbackground=LINE)
        self.logbox.pack(fill="both", expand=True, pady=(8, 0))

        # ---------------- voice ----------------
        ttk.Label(three if False else two, text="Which voice speaks your lecture",
                  style="H.TLabel").pack(anchor="w")
        ttk.Label(two, text="The eleven ready-made voices cost the same as each other. A voice of "
                            "your own runs on this computer and costs nothing to use, but it is "
                            "slower and has to be installed once.",
                  style="Dim.TLabel", wraplength=820, justify="left").pack(anchor="w", pady=(2, 10))

        self.v_voice = tk.StringVar(value=str(self.cfg.get("voice", "onyx")))
        box = ttk.Frame(two, style="Card.TFrame", padding=12); box.pack(fill="both", expand=True)
        self.voicelist = tk.Listbox(box, bg="#05080f", fg=TXT, selectbackground="#1f6feb",
                                    relief="flat", font=("Segoe UI", 10), height=14,
                                    highlightthickness=1, highlightbackground=LINE)
        self.voicelist.pack(side="left", fill="both", expand=True)
        side = ttk.Frame(box, style="Card.TFrame"); side.pack(side="left", fill="y", padx=(12, 0))
        ttk.Button(side, text="Hear it", command=self.hear).pack(fill="x", pady=3)
        ttk.Button(side, text="Make all samples", command=self.make_samples).pack(fill="x", pady=3)
        ttk.Separator(side).pack(fill="x", pady=9)
        ttk.Button(side, text="Add a voice…", command=self.add_voice).pack(fill="x", pady=3)
        ttk.Label(side, text="From any recording\nof someone speaking\n— English is best.",
                  style="CardDim.TLabel", justify="left").pack(anchor="w", pady=(4, 0))
        self.refresh_voices()

        # ---------------- glossary ----------------
        ttk.Label(three, text="Words it would otherwise get wrong", style="H.TLabel").pack(anchor="w")
        ttk.Label(three, text="A name you invented has no translation. Say MLAD out loud in Persian "
                              "and it comes back as ملاد, and the writer turns that into \"Milad\" — in "
                              "every line, in every video. One line here fixes it once and for all.\n"
                              "Write them as:   what it sounds like  =  what it must be",
                  style="Dim.TLabel", wraplength=820, justify="left").pack(anchor="w", pady=(2, 10))
        self.gloss = tk.Text(three, bg="#05080f", fg=TXT, insertbackground=TXT, relief="flat",
                             font=("Consolas", 11), highlightthickness=1, highlightbackground=LINE)
        self.gloss.pack(fill="both", expand=True)
        path = os.path.join(HERE, "glossary.txt")
        if os.path.exists(path):
            self.gloss.insert("1.0", open(path, encoding="utf-8-sig").read())
        ttk.Button(three, text="Save", command=self.save_gloss).pack(anchor="e", pady=8)

    # ----------------------------------------------------------- voices
    def refresh_voices(self):
        self.voicelist.delete(0, "end")
        self.voice_ids = []
        for v in R.cloned_voices():
            self.voicelist.insert("end", "  %s   — cloned, runs on this computer" % v)
            self.voice_ids.append(R.MINE + v)
        for v in PRESETS:
            self.voicelist.insert("end", "  %s" % v)
            self.voice_ids.append(v)
        want = self.v_voice.get()
        if want in self.voice_ids:
            i = self.voice_ids.index(want)
            self.voicelist.selection_set(i); self.voicelist.see(i)
        elif self.voice_ids:
            self.voicelist.selection_set(0)

    def chosen_voice(self):
        sel = self.voicelist.curselection()
        return self.voice_ids[sel[0]] if sel else self.v_voice.get()

    def hear(self):
        v = self.chosen_voice()
        name = v[len(R.MINE):] if v.startswith(R.MINE) else v
        for f in ("samples/_your-cloned-voice.mp3" if v.startswith(R.MINE) else None,
                  "samples/%s.mp3" % name, "voice/%s.wav" % name):
            if f and os.path.exists(os.path.join(HERE, f)):
                play(os.path.join(HERE, f)); return
        messagebox.showinfo("No sample yet",
                            "There is no sample of %s yet.\n\nPress “Make all samples” to "
                            "hear the ready-made voices, or add a voice from a recording." % name)

    def make_samples(self):
        self.nb.select(0)
        self._log("\n  making a sample of every ready-made voice...\n")
        self._spawn(lambda: subprocess.run([sys.executable, os.path.join(HERE, "voices.py")],
                                           cwd=HERE, capture_output=True, text=True))

    def add_voice(self):
        src = filedialog.askopenfilename(
            title="A recording of the voice to copy",
            filetypes=[("Audio or video", "*.mp4 *.m4a *.mp3 *.wav *.mov *.mkv *.aac *.ogg"),
                       ("All files", "*.*")])
        if not src:
            return
        name = simpledialog.askstring("Name it", "What should this voice be called?",
                                      initialvalue=os.path.splitext(os.path.basename(src))[0])
        if not name:
            return
        try:
            safe, dest = R.add_voice(src, name)
        except Exception as e:
            messagebox.showerror("Could not read that", str(e)[:400]); return
        self.v_voice.set(R.MINE + safe)
        self.refresh_voices()
        messagebox.showinfo(
            "Added",
            "“%s” is now in the list.\n\nIt is copied from the voice in that recording. "
            "The first time you use it, the model downloads once (about 1.8GB) and it will take a "
            "few minutes." % safe)

    def save_gloss(self):
        open(os.path.join(HERE, "glossary.txt"), "w", encoding="utf-8", newline="\r\n").write(
            self.gloss.get("1.0", "end-1c"))
        self.status.config(text="glossary saved", foreground=OK)

    # ----------------------------------------------------------- running
    def pick_in(self):
        f = filedialog.askopenfilename(title="Your lecture",
                                       filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi"),
                                                  ("All files", "*.*")])
        if f: self.v_in.set(f)

    def pick_out(self):
        d = filedialog.askdirectory(title="Where the results go")
        if d: self.v_out.set(d)

    def settings(self):
        c = dict(self.cfg)
        c["voice"] = self.chosen_voice()
        c["max_tempo"] = round(float(self.v_tempo.get()), 3)
        c["review"] = bool(self.v_review.get())
        return c

    def start(self):
        video = self.v_in.get().strip('" ')
        if not os.path.exists(video):
            messagebox.showwarning("Which video?", "Choose the mp4 first."); return
        if self.worker and self.worker.is_alive():
            return
        cfg = self.settings()
        if self.v_remember.get():
            keep = dict(cfg)
            keep.pop("offline", None)
            json.dump(keep, open(os.path.join(HERE, "config.json"), "w", encoding="utf-8"), indent=2)
        self.save_gloss()
        self.logbox.delete("1.0", "end")
        self.btn.config(state="disabled")
        self.status.config(text="working…", foreground=GOLD)
        out = self.v_out.get().strip() or os.path.join(HERE, "output")
        os.makedirs(out, exist_ok=True)

        def job():
            try:
                done = R.convert(video, cfg, say=self._say, ask=self._ask, out_dir=out)
                self.q.put(("done", done))
            except Exception as e:
                self.q.put(("fail", "%s\n\n%s" % (e, traceback.format_exc()[-900:])))
        self.worker = threading.Thread(target=job, daemon=True)
        self.worker.start()

    def _spawn(self, fn):
        def job():
            try:
                r = fn()
                self.q.put(("log", (getattr(r, "stdout", "") or "") + (getattr(r, "stderr", "") or "")))
                self.q.put(("samples", None))
            except Exception as e:
                self.q.put(("log", str(e)))
        threading.Thread(target=job, daemon=True).start()

    # the pipeline talks to the window only through the queue: tkinter must be
    # touched from the main thread and nowhere else
    def _say(self, msg):
        self.q.put(("log", str(msg) + "\n"))

    def _ask(self, segs):
        self.q.put(("review", segs))
        return self.answer.get()          # blocks this worker until you answer

    def _log(self, text):
        self.logbox.insert("end", text)
        self.logbox.see("end")

    def _drain(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "samples":
                    self.refresh_voices()
                    self.status.config(text="samples ready", foreground=OK)
                elif kind == "review":
                    Review(self, payload, self.answer)
                elif kind == "done":
                    self.btn.config(state="normal")
                    if payload:
                        self.status.config(text="finished", foreground=OK)
                        play(self.v_out.get())
                    else:
                        self.status.config(text="stopped", foreground=DIM)
                elif kind == "fail":
                    self.btn.config(state="normal")
                    self.status.config(text="stopped", foreground=RED)
                    self._log("\n  STOPPED: " + payload + "\n")
        except queue.Empty:
            pass
        self.after(80, self._drain)


class Review(tk.Toplevel):
    """Every line, with the English that will be spoken over it, before a word of
    it has been made. This is the cheap moment to fix a name."""

    def __init__(self, master, segs, answer):
        super().__init__(master)
        self.title("Read this before it speaks")
        self.configure(bg=BG)
        self.geometry("1000x740")
        self.segs, self.answer, self.boxes = segs, answer, []
        self.protocol("WM_DELETE_WINDOW", self.cancel)

        top = ttk.Frame(self, padding=(16, 14, 16, 8)); top.pack(fill="x")
        ttk.Label(top, text="%d lines — nothing has been spoken yet" % len(segs),
                  font=("Segoe UI Semibold", 13)).pack(anchor="w")
        ttk.Label(top, text="Under each line you said is the English that will be spoken over that "
                            "exact moment of the video. Change anything that is wrong — a name it "
                            "did not know, a term it translated. Fixing it here costs nothing.",
                  style="Dim.TLabel", wraplength=940, justify="left").pack(anchor="w", pady=(3, 0))

        outer = ttk.Frame(self); outer.pack(fill="both", expand=True, padx=16, pady=8)
        cv = tk.Canvas(outer, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=cv.yview)
        inner = ttk.Frame(cv)
        inner.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        win = cv.create_window((0, 0), window=inner, anchor="nw")
        cv.bind("<Configure>", lambda e: cv.itemconfig(win, width=e.width))
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        cv.bind_all("<MouseWheel>", lambda e: cv.yview_scroll(int(-e.delta / 120), "units"))

        for i, s in enumerate(segs):
            card = ttk.Frame(inner, style="Card.TFrame", padding=10)
            card.pack(fill="x", pady=4, padx=(0, 12))
            head = "%03d    %s – %s    (about %d words fit here)" % (
                i + 1, R.clock(s["start"])[3:-4], R.clock(s["end"])[3:-4], R.budget(segs, i))
            ttk.Label(card, text=head, style="CardDim.TLabel",
                      font=("Consolas", 9)).pack(anchor="w")
            fa = tk.Label(card, text=s["said"].strip(), bg=PAN, fg=DIM, wraplength=880,
                          justify="right", anchor="e", font=("Segoe UI", 10))
            fa.pack(fill="x", pady=(4, 6))
            box = tk.Text(card, height=2, bg="#05080f", fg=TXT, insertbackground=TXT,
                          relief="flat", font=("Segoe UI", 11), wrap="word",
                          highlightthickness=1, highlightbackground=LINE)
            box.insert("1.0", (s.get("en") or "").strip())
            box.pack(fill="x")
            self.boxes.append(box)

        bar = ttk.Frame(self, padding=(16, 8, 16, 14)); bar.pack(fill="x")
        ttk.Button(bar, text="Approve and make the video", style="Go.TButton",
                   command=self.approve).pack(side="left")
        ttk.Button(bar, text="Cancel", command=self.cancel).pack(side="left", padx=10)
        ttk.Label(bar, text="Nothing has been spent on the voice yet.",
                  style="Dim.TLabel").pack(side="left", padx=10)

    def approve(self):
        changed = 0
        for s, box in zip(self.segs, self.boxes):
            new = " ".join(box.get("1.0", "end-1c").split())
            # an emptied box keeps what it had: deleting a line by accident
            # should not silently delete that piece of the lecture
            if new and new != (s.get("en") or "").strip():
                s["en"] = new
                changed += 1
        self.answer.put(self.segs)
        self.master._log("  approved%s\n" %
                         (" with %d line%s of your own" % (changed, "" if changed == 1 else "s")
                          if changed else " unchanged"))
        self.destroy()

    def cancel(self):
        self.answer.put(None)
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
