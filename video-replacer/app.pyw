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
import json, os, queue, shutil, subprocess, sys, threading, traceback

if getattr(sys, "frozen", False):
    HERE = os.path.dirname(os.path.abspath(sys.executable))
else:
    HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

import replacer as R

INPUT = os.path.join(HERE, "input")      # where a lecture is expected to be

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
        # Never a fixed size. A screen with Windows scaling turned up reports
        # fewer usable units than the number of pixels suggests, and a window
        # asked for in pixels then opens larger than the desk it has to sit on.
        want_w, want_h = 1180, 720
        room_w = self.winfo_screenwidth() - 60
        room_h = self.winfo_screenheight() - 130      # taskbar, title bar, margin
        w, h = min(want_w, room_w), min(want_h, room_h)
        self.geometry("%dx%d+%d+%d" % (w, h, max(0, (room_w - w) // 2), 24))
        self.minsize(min(940, room_w), min(560, room_h))
        self.cfg = R.config()
        self.q = queue.Queue()
        self.worker = None
        self.answer = queue.Queue()      # the review panel's reply to the pipeline
        self._panes = []                 # columns that scroll on a short screen
        self._skin()
        self._build()
        self.v_source.trace_add("write", lambda *_: self.show_link())
        self.show_link()
        self.protocol("WM_DELETE_WINDOW", self.shut)
        self._tick = self.after(80, self._drain)

    def shut(self):
        """Closing means closing. A half-finished transcript of a lecture is not
        something to leave lying about, and the voice model is a live process
        that would otherwise stay running with nothing to do."""
        try:
            self.after_cancel(self._tick)     # nothing left ticking into a dead window
        except Exception:
            pass
        try:
            R.stop_local()
        except Exception:
            pass
        try:
            R.clear_work(bool(self.v_keepwork.get()))
        except Exception:
            pass
        self.destroy()

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
        st.configure("TEntry", padding=6)
        st.configure("Horizontal.TScale", background=BG, troughcolor=PAN,
                     bordercolor=LINE, lightcolor=LINE, darkcolor=LINE)
        st.map("Horizontal.TScale", background=[("active", BG)])
        st.configure("Vertical.TScrollbar", background=PAN, troughcolor=BG,
                     bordercolor=BG, arrowcolor=DIM, relief="flat")
        st.map("Vertical.TScrollbar", background=[("active", LINE), ("pressed", LINE)])
        st.map("TButton", background=[("active", LINE)])

        # Ticks and radios, on a dark window. clam paints its own pale colour
        # under the label the moment the mouse is over it or it takes focus, and
        # pale under white text is text you cannot read. Every state has to be
        # named, including the dotted focus ring, which clam draws in
        # focuscolor and defaults to something bright.
        for w, back in (("TCheckbutton", BG), ("Card.TCheckbutton", PAN),
                        ("TRadiobutton", BG), ("Card.TRadiobutton", PAN)):
            st.configure(w, background=back, foreground=TXT, font=("Segoe UI", 10),
                         focuscolor=back, indicatorcolor=back,
                         indicatorbackground=PAN, indicatorforeground=TXT)
            st.map(w,
                   background=[("active", back), ("selected", back),
                               ("focus", back), ("pressed", back)],
                   foreground=[("disabled", DIM), ("active", TXT),
                               ("selected", TXT), ("focus", TXT)],
                   indicatorcolor=[("selected", OK), ("pressed", OK),
                                   ("active", LINE), ("!selected", back)],
                   indicatorbackground=[("selected", PAN), ("active", LINE),
                                        ("pressed", LINE), ("!selected", PAN)])

    hintwrap = 540      # narrow enough for the left column; Settings widens it

    def _row(self, parent, label, hint=""):
        ttk.Label(parent, text=label, style="H.TLabel").pack(anchor="w", pady=(10, 2))
        if hint:
            # wraplength, or a long sentence simply runs off the right edge and
            # the half you needed is the half you cannot see
            ttk.Label(parent, text=hint, style="Dim.TLabel",
                      wraplength=self.hintwrap, justify="left").pack(anchor="w", pady=(0, 3))
        f = ttk.Frame(parent); f.pack(fill="x")
        return f

    def _scrollpane(self, parent):
        """A column that scrolls when the screen is short. Nothing is ever
        clipped away where it cannot be reached, whatever size the display is."""
        holder = ttk.Frame(parent); holder.pack(side="top", fill="both", expand=True)
        canvas = tk.Canvas(holder, bg=BG, highlightthickness=0, bd=0)
        bar = ttk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)

        def fit(_=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(window, width=canvas.winfo_width())
            need = inner.winfo_reqheight() > canvas.winfo_height()
            if need and not bar.winfo_ismapped():
                bar.pack(side="right", fill="y")
            elif not need and bar.winfo_ismapped():
                bar.pack_forget()

        inner.bind("<Configure>", fit)
        canvas.bind("<Configure>", fit)

        def wheel(e):
            if self.nb.select() == str(self.nb.nametowidget(self.nb.tabs()[0])) \
               and bar.winfo_ismapped():
                canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")

        self.bind_all("<MouseWheel>", wheel, add="+")
        self._panes.append((canvas, inner))
        return inner

    def _scrolling(self, nb, title):
        """A tab taller than the window. Settings has outgrown one screen, and a
        setting you cannot scroll to is a setting that does not exist."""
        holder = ttk.Frame(nb); nb.add(holder, text=title)
        canvas = tk.Canvas(holder, bg=BG, highlightthickness=0, bd=0)
        bar = ttk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas, padding=16)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")

        def fit(_=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(window, width=canvas.winfo_width())

        inner.bind("<Configure>", fit)
        canvas.bind("<Configure>", fit)

        def wheel(e):
            # only while this tab is the one on top, or the wheel scrolls a
            # hidden tab while you are looking at another
            if self.nb.select() == str(holder):
                canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")

        self.bind_all("<MouseWheel>", wheel, add="+")
        return inner

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
        four = self._scrolling(nb, "  Settings  ")

        # ---------------- convert ----------------
        # Two columns. Everything you set is on the left; what the run is doing
        # is on the right, where it is visible the whole time instead of pushed
        # off the bottom of a tall window.
        cols = ttk.Frame(one); cols.pack(fill="both", expand=True)
        column = ttk.Frame(cols, width=568); column.pack(side="left", fill="y")
        column.pack_propagate(False)
        ttk.Separator(cols, orient="vertical").pack(side="left", fill="y", padx=14)
        right = ttk.Frame(cols); right.pack(side="left", fill="both", expand=True)

        # Start and the two ticks live outside the scrolling part, pinned to the
        # bottom of the column: on a small screen the settings above them may
        # need scrolling, but the button you came to press never moves.
        anchor = ttk.Frame(column); anchor.pack(side="bottom", fill="x")
        left = self._scrollpane(column)

        f = self._row(left, "The video")
        self.vid_hint = ttk.Label(left, text="", style="Dim.TLabel",
                                  wraplength=540, justify="left")
        self.vid_hint.pack(anchor="w", pady=(0, 3), before=f)
        self.v_in = tk.StringVar(value=str(self.cfg.get("last_video", "")))
        ttk.Entry(f, textvariable=self.v_in).pack(side="left", fill="x", expand=True)
        ttk.Button(f, text="Choose…", command=self.pick_in).pack(side="left", padx=(8, 0))

        f = self._row(left, "The language you speak in the video",
                      "It works this out from the audio on its own, and English is what comes "
                      "out whichever language went in. Name it only if the guess wanders.")
        self.v_lang = tk.StringVar(value=R.language_label(self.cfg.get("language", "")))
        ttk.Combobox(f, textvariable=self.v_lang, width=26,
                     values=[n for n, _ in R.LANGUAGES]).pack(side="left")
        ttk.Label(f, text="  or any ISO code", style="Dim.TLabel").pack(side="left")

        f = self._row(left, "Where the results go")
        self.v_out = tk.StringVar(value=str(self.cfg.get("out_dir", "")).strip()
                                  or os.path.join(HERE, "output"))
        ttk.Entry(f, textvariable=self.v_out).pack(side="left", fill="x", expand=True)
        ttk.Button(f, text="Choose…", command=self.pick_out).pack(side="left", padx=(8, 0))

        f = self._row(left, "How much a line may be sped up to fit",
                      "English is never the same length as what you said. Past about 125% it is audible.")
        self.v_tempo = tk.DoubleVar(value=float(self.cfg.get("max_tempo", 1.20)))
        self.tempo_lbl = ttk.Label(f, text="", style="Dim.TLabel")
        sc = ttk.Scale(f, from_=1.0, to=1.5, variable=self.v_tempo, orient="horizontal",
                       command=lambda _=None: self.tempo_lbl.config(
                           text="  %d%%" % round(self.v_tempo.get() * 100)))
        sc.pack(side="left", fill="x", expand=True); self.tempo_lbl.pack(side="left")
        self.tempo_lbl.config(text="  %d%%" % round(self.v_tempo.get() * 100))

        # anchored to the bottom of the column: whatever else is on screen, the
        # button you came here to press is never the thing that falls off it
        self.v_review = tk.BooleanVar(value=bool(self.cfg.get("review", True)))
        ttk.Checkbutton(anchor, variable=self.v_review,
                        text="Show me every line first, so I can fix a word before it is spoken"
                        ).pack(anchor="w", pady=(10, 0))
        self.v_remember = tk.BooleanVar(value=True)
        ttk.Checkbutton(anchor, variable=self.v_remember,
                        text="Remember these settings").pack(anchor="w", pady=(4, 0))
        go = ttk.Frame(anchor); go.pack(fill="x", pady=(12, 2))
        self.btn = ttk.Button(go, text="Start", style="Go.TButton", command=self.start)
        self.btn.pack(side="left")
        self.status = ttk.Label(go, text="", style="Dim.TLabel")
        self.status.pack(side="left", padx=14)

        ttk.Label(right, text="What it is doing", style="H.TLabel").pack(anchor="w", pady=(0, 6))
        self.logbox = tk.Text(right, width=44, bg="#05080f", fg="#cfe0ff", insertbackground=TXT,
                              relief="flat", font=("Consolas", 9), wrap="word",
                              highlightthickness=1, highlightbackground=LINE)
        self.logbox.pack(fill="both", expand=True)

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

        # ---------------- settings ----------------
        self.hintwrap = 820          # this tab has the whole width to itself
        f = self._row(four, "Your OpenAI key",
                      "Kept in key.txt beside this app, on this computer. It is never sent anywhere "
                      "but to OpenAI, and never goes into the repository.")
        self.v_key = tk.StringVar(value=self._read_key())
        self.keybox = ttk.Entry(f, textvariable=self.v_key, show="\u2022")
        self.keybox.pack(side="left", fill="x", expand=True)
        self.v_showkey = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, variable=self.v_showkey, text="show",
                        command=lambda: self.keybox.config(
                            show="" if self.v_showkey.get() else "\u2022")).pack(side="left", padx=8)
        ttk.Button(f, text="Save", command=self.save_key).pack(side="left")

        f = self._row(four, "ffmpeg", "Does all the work on the video. The app fetches it itself.")
        self.ff_lbl = ttk.Label(f, text="checking\u2026", style="Dim.TLabel")
        self.ff_lbl.pack(side="left")
        ttk.Button(f, text="Get it", command=self.get_ffmpeg).pack(side="left", padx=10)

        f = self._row(four, "The transcript",
                      "A pass over what you were heard to say, fixing spelling and word "
                      "boundaries only. It is forbidden to invent a word to fill a gap.")
        self.v_proof = tk.BooleanVar(value=bool(self.cfg.get("proofread", True)))
        ttk.Checkbutton(f, variable=self.v_proof,
                        text="Tidy up the transcript's spelling before translating"
                        ).pack(side="left")

        f = self._row(four, "Who writes down what you said",
                      "Both start from the same mp4. The difference is only which one listens "
                      "to it.")
        self.v_source = tk.StringVar(
            value=str(self.cfg.get("transcript_from", "here")).lower())
        ttk.Radiobutton(f, variable=self.v_source, value="here",
                        text="OpenAI Whisper  \u2014 sends the audio, about 36\u00a2 an hour"
                        ).pack(anchor="w")
        ttk.Radiobutton(f, variable=self.v_source, value="youtube",
                        text="YouTube  \u2014 free, and better on Persian"
                        ).pack(anchor="w", pady=(2, 0))
        ttk.Label(four, text="If YouTube refuses or takes too long, the run does not stop \u2014 "
                             "it says so and Whisper writes it instead.",
                  style="Dim.TLabel", wraplength=820, justify="left").pack(anchor="w")

        f = self._row(four, "The YouTube upload",
                      "Only used when the Convert tab says the words come from YouTube. The "
                      "video goes up unlisted, is transcribed, and comes down again.")
        self.v_ytdel = tk.BooleanVar(value=bool(self.cfg.get("youtube_delete", True)))
        ttk.Checkbutton(f, variable=self.v_ytdel,
                        text="Delete the upload once the words are read").pack(side="left")
        ttk.Label(f, text="   give up waiting after", style="Dim.TLabel").pack(side="left")
        self.v_ytwait = tk.StringVar(value=str(self.cfg.get("youtube_wait_minutes", 20)))
        ttk.Entry(f, textvariable=self.v_ytwait, width=5).pack(side="left", padx=6)
        ttk.Label(f, text="minutes", style="Dim.TLabel").pack(side="left")

        f = self._row(four, "Your YouTube sign-in",
                      "One desktop client from the Google Cloud console, signed in once. "
                      "Both files stay on this computer and neither goes into the repository.")
        self.yt_lbl = ttk.Label(f, text="checking\u2026", style="Dim.TLabel")
        self.yt_lbl.pack(side="left")
        ttk.Button(f, text="Choose client_secret.json\u2026",
                   command=self.pick_secret).pack(side="left", padx=10)
        ttk.Button(f, text="Sign in", command=self.yt_sign_in).pack(side="left")
        ttk.Label(four, text="In the Google console, set the app to In production rather than "
                             "Testing \u2014 a Testing app makes you sign in again every 7 days.",
                  style="Dim.TLabel").pack(anchor="w")

        f = self._row(four, "The local voice",
                      "Only needed for a voice of your own. A few gigabytes, installed in .venv "
                      "beside this app - nothing else on your computer is touched.")
        self.tts_lbl = ttk.Label(f, text="checking\u2026", style="Dim.TLabel")
        self.tts_lbl.pack(side="left")
        ttk.Button(f, text="Install", command=self.install_voice).pack(side="left", padx=10)
        self.v_cuda = tk.BooleanVar(value=bool(self.cfg.get("use_gpu", True)))
        ttk.Checkbutton(four, variable=self.v_cuda,
                        text="Use the graphics card"
                        ).pack(anchor="w", pady=(4, 0))
        ttk.Label(four, text="About 3GB more to download and several times faster. An NVIDIA "
                             "card is needed; without one it installs the processor build and "
                             "works anyway, just slower. Untick only if the card will not work.",
                  style="Dim.TLabel", wraplength=820, justify="left").pack(anchor="w")

        adv = ttk.Frame(four); adv.pack(fill="x", pady=(18, 0))
        ttk.Label(adv, text="Rarely worth changing", style="H.TLabel").pack(anchor="w")
        g = ttk.Frame(adv); g.pack(fill="x", pady=4)
        self.v_adv = {}
        for i, (k, label, hint) in enumerate([
                ("longest_line", "Longest sentence (seconds)", "fragments closer than the gap below are joined up to this"),
                ("join_gap", "A pause longer than this starts a new line", "seconds"),
                ("chunk_minutes", "Send to the transcriber in pieces of", "minutes"),
                ("writer", "The model that writes the English", ""),
                ("transcribe", "The model that listens", "whisper-1 is the only one that returns timestamps"),
                ("speaker", "The ready-made voice model", "")]):
            cell = ttk.Frame(g)
            cell.grid(row=i, column=0, sticky="w", pady=2)
            ttk.Label(cell, text=label, style="Dim.TLabel").pack(anchor="w")
            if hint:
                ttk.Label(cell, text=hint, style="CardDim.TLabel", foreground=DIM,
                          background=BG, wraplength=380, justify="left").pack(anchor="w")
            var = tk.StringVar(value=str(self.cfg.get(k, "")))
            ttk.Entry(g, textvariable=var, width=34).grid(row=i, column=1, sticky="w", padx=12)
            self.v_adv[k] = var
        self.v_keepwork = tk.BooleanVar(value=bool(self.cfg.get("keep_work", False)))
        ttk.Checkbutton(adv, variable=self.v_keepwork,
                        text="Keep the working files"
                        ).pack(anchor="w", pady=(8, 0))
        ttk.Label(adv, text="A second run then skips what is already done and does not pay for "
                            "it twice. Off by default: what is in work\\ is a half-finished "
                            "transcript of a lecture.",
                  style="Dim.TLabel", wraplength=820, justify="left").pack(anchor="w")
        ttk.Label(adv, text="Everything on this page is saved when you tick “Remember these "
                            "settings” and press Start.", style="Dim.TLabel").pack(anchor="w", pady=(10, 0))
        self.after(200, self.check_tools)

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

    # ----------------------------------------------------------- setup it does itself
    def _read_key(self):
        p = os.path.join(HERE, "key.txt")
        try:
            return open(p, encoding="utf-8-sig").read().strip()
        except Exception:
            return os.environ.get("OPENAI_API_KEY", "")

    def save_key(self):
        k = self.v_key.get().strip()
        if k and not k.startswith("sk-"):
            if not messagebox.askyesno("That does not look like a key",
                                       "An OpenAI key normally starts with sk-. Save it anyway?"):
                return
        open(os.path.join(HERE, "key.txt"), "w", encoding="utf-8").write(k)
        self.status.config(text="key saved", foreground=OK)
        messagebox.showinfo("Saved", "The key is in key.txt beside this app.")

    def show_link(self):
        """The mp4 is the only input either way. All that changes is who listens
        to it, and the video row says which - so the choice is visible where the
        work starts, without being a question asked twice."""
        if self.v_source.get() == "youtube":
            self.vid_hint.config(
                text="The mp4 you recorded. YouTube writes the words: it goes up to your "
                     "channel unlisted and is deleted again straight afterwards.")
        else:
            self.vid_hint.config(
                text="The mp4 you recorded. Whisper writes the words, from the sound only \u2014 "
                     "the video itself is never uploaded anywhere.")

    def yt_status(self):
        """Says which of the two steps is still missing, rather than just 'no'."""
        has, signed = R.yt_ready()
        if not has:
            self.yt_lbl.config(text="no client file yet", foreground=DIM)
        elif not signed:
            self.yt_lbl.config(text="client ready \u2014 not signed in", foreground=GOLD)
        else:
            self.yt_lbl.config(text="signed in", foreground=OK)

    def pick_secret(self):
        """The file Google gave you, copied into place by the app. There is
        nothing to move by hand and nothing to rename."""
        f = filedialog.askopenfilename(title="The client_secret file you downloaded",
                                       filetypes=[("Google client secret", "*.json"),
                                                  ("All files", "*.*")])
        if not f:
            return
        try:
            d = json.load(open(f, encoding="utf-8-sig"))
            if not (d.get("installed") or d.get("web")):
                raise ValueError("that is not an OAuth client file")
            if os.path.abspath(f) != os.path.abspath(R.YT_SECRET):
                shutil.copyfile(f, R.YT_SECRET)
        except Exception as e:
            messagebox.showwarning("Not that file", "%s\n\nIn the Google console it is under "
                                   "Clients \u2192 your desktop client \u2192 Download JSON." % e)
            return
        self.yt_status()

    def yt_sign_in(self):
        """Opens the browser once. Nothing is typed or pasted by hand."""
        if not R.yt_client():
            messagebox.showinfo("One file first", "Press \u201cChoose client_secret.json\u201d "
                                "and pick the file you downloaded from the Google Cloud console.")
            return
        self.nb.select(0)
        self._log("\n  signing in to YouTube...\n")

        def job():
            try:
                R.yt_sign_in(lambda m: self.q.put(("log", m + "\n")))
                self.q.put(("log", "  Signed in. The Convert tab can use a YouTube link now.\n"))
            except Exception as e:
                self.q.put(("log", "  sign-in failed: %s\n" % e))
            self.q.put(("yt", None))

        threading.Thread(target=job, daemon=True).start()

    def check_tools(self):
        self.yt_status()
        try:
            R.tool("ffmpeg"); self.ff_lbl.config(text="installed", foreground=OK)
        except SystemExit:
            self.ff_lbl.config(text="missing - press Get it", foreground=GOLD)
        except Exception:
            self.ff_lbl.config(text="missing - press Get it", foreground=GOLD)
        py = R.venv_python()
        if not py:
            self.tts_lbl.config(text="not installed", foreground=DIM); return
        # "installed" is not the useful fact. Which device it will actually use is.
        def look():
            try:
                r = subprocess.run(
                    [py, "-c", "import torch;print(torch.cuda.is_available(), torch.version.cuda)"],
                    capture_output=True, text=True, timeout=90, **R._NOWINDOW)
                self.q.put(("tts", (r.stdout or "").strip()))
            except Exception as e:
                self.q.put(("tts", "? %s" % e))
        threading.Thread(target=look, daemon=True).start()
        self.tts_lbl.config(text="installed, checking the card\u2026", foreground=DIM)

    def get_ffmpeg(self):
        """Fetched by the app. Nothing to run, nothing to unzip by hand."""
        self.nb.select(0)
        self._log("\n  getting ffmpeg...\n")

        def job():
            import urllib.request, zipfile, shutil as sh
            try:
                url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
                zp = os.path.join(HERE, "_ffmpeg.zip")
                self.q.put(("log", "  downloading (about 30MB)...\n"))
                urllib.request.urlretrieve(url, zp)
                self.q.put(("log", "  unpacking...\n"))
                tmp = os.path.join(HERE, "_ff")
                sh.rmtree(tmp, ignore_errors=True)
                with zipfile.ZipFile(zp) as z:
                    z.extractall(tmp)
                inner = [os.path.join(tmp, d) for d in os.listdir(tmp)
                         if os.path.isdir(os.path.join(tmp, d))]
                dest = os.path.join(HERE, "ffmpeg")
                sh.rmtree(dest, ignore_errors=True)
                sh.move(inner[0], dest)
                sh.rmtree(tmp, ignore_errors=True)
                os.remove(zp)
                self.q.put(("log", "  ffmpeg is ready.\n"))
            except Exception as e:
                self.q.put(("log", "  could not get ffmpeg: %s\n" % e))
            self.q.put(("tools", None))
        threading.Thread(target=job, daemon=True).start()

    def install_voice(self):
        if R.venv_python() and not messagebox.askyesno(
                "Already installed", "The local voice is already installed. Install it again?"):
            return
        self.nb.select(0)
        self._log("\n  installing the local voice. This is a few gigabytes and takes a while.\n"
                  "  It all goes in .venv beside this app - nothing else is touched.\n")

        def job():
            venv = os.path.join(HERE, ".venv")
            py = sys.executable
            if getattr(sys, "frozen", False):
                py = shutil_which_python()
                if not py:
                    self.q.put(("log", "\n  Python is not installed on this computer, and the local "
                                       "voice needs it. Install Python 3.11 from python.org, then "
                                       "press Install again.\n"))
                    self.q.put(("tools", None)); return
            steps = [[py, "-m", "venv", venv]]
            vpy = os.path.join(venv, "Scripts", "python.exe")
            # The graphics card is not automatic. `pip install torch` on Windows
            # gives the CPU wheel and nothing warns you - the app simply runs
            # five times slower for ever. The CUDA build lives on its own index.
            # torch 2.8 on purpose: 2.9 wants torchcodec, which needs ffmpeg DLLs
            # the static Windows build does not ship.
            cuda = self.v_cuda.get()
            torch_args = ["torch==2.8.0", "torchaudio==2.8.0"]
            if cuda:
                torch_args = ["--index-url", "https://download.pytorch.org/whl/cu126"] + torch_args
            steps += [[vpy, "-m", "pip", "install", "--upgrade", "pip"],
                      [vpy, "-m", "pip", "install"] + torch_args,
                      [vpy, "-m", "pip", "install", "coqui-tts", "transformers<5"]]
            for i, cmd in enumerate(steps, 1):
                self.q.put(("log", "  step %d of %d...\n" % (i, len(steps))))
                try:
                    r = subprocess.run(cmd, capture_output=True, text=True, **R._NOWINDOW)
                    if r.returncode != 0:
                        self.q.put(("log", "  failed:\n" + (r.stderr or "")[-700:] + "\n"))
                        break
                except Exception as e:
                    self.q.put(("log", "  failed: %s\n" % e)); break
            else:
                self.q.put(("log", "\n  the local voice is installed. Go to Voice and add one.\n"))
            self.q.put(("tools", None))
        threading.Thread(target=job, daemon=True).start()

    # ----------------------------------------------------------- running
    def pick_in(self):
        """Opens in the folder you were last in, and on the first run in the
        input folder beside the app - which is made if it is not there yet."""
        start = os.path.dirname(self.v_in.get().strip('" ')) or INPUT
        if not os.path.isdir(start):
            start = INPUT
        os.makedirs(INPUT, exist_ok=True)
        f = filedialog.askopenfilename(title="Your lecture", initialdir=start,
                                       filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi"),
                                                  ("All files", "*.*")])
        if f: self.v_in.set(f)

    def pick_out(self):
        start = self.v_out.get().strip() or os.path.join(HERE, "output")
        if not os.path.isdir(start):
            start = HERE
        d = filedialog.askdirectory(title="Where the results go", initialdir=start)
        if d: self.v_out.set(d)

    def settings(self):
        c = dict(self.cfg)
        c["voice"] = self.chosen_voice()
        c["max_tempo"] = round(float(self.v_tempo.get()), 3)
        c["review"] = bool(self.v_review.get())
        c["keep_work"] = bool(self.v_keepwork.get())
        c["language"] = R.language_code(self.v_lang.get())
        c["proofread"] = bool(self.v_proof.get())
        c["transcript_from"] = self.v_source.get()
        c["out_dir"] = self.v_out.get().strip()
        c["use_gpu"] = bool(self.v_cuda.get())
        c["youtube_delete"] = bool(self.v_ytdel.get())
        try:
            c["youtube_wait_minutes"] = max(1, int(float(self.v_ytwait.get())))
        except ValueError:
            pass
        c["last_video"] = self.v_in.get().strip('" ')
        for k, var in self.v_adv.items():
            raw = var.get().strip()
            if not raw:
                continue
            try:
                c[k] = float(raw) if "." in raw else int(raw)
            except ValueError:
                c[k] = raw
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
                elif kind == "tools":
                    self.check_tools()
                elif kind == "tts":
                    if payload.startswith("True"):
                        self.tts_lbl.config(text="installed, using the graphics card",
                                            foreground=OK)
                    elif payload.startswith("False None"):
                        self.tts_lbl.config(
                            text="installed, but the CPU build \u2014 press Install again with "
                                 "the card ticked", foreground=GOLD)
                    else:
                        self.tts_lbl.config(text="installed, on the processor (slow)",
                                            foreground=GOLD)
                elif kind == "yt":
                    self.yt_status()
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
        self._tick = self.after(80, self._drain)


class Review(tk.Toplevel):
    """Every line, with the English that will be spoken over it, before a word of
    it has been made. This is the cheap moment to fix a name."""

    def __init__(self, master, segs, answer):
        super().__init__(master)
        self.title("Read this before it speaks")
        self.configure(bg=BG)
        self.geometry("860x580")
        self.segs, self.answer, self.boxes = segs, answer, []
        self.protocol("WM_DELETE_WINDOW", self.cancel)

        top = ttk.Frame(self, padding=(16, 14, 16, 8)); top.pack(fill="x")
        ttk.Label(top, text="%d lines — nothing has been spoken yet" % len(segs),
                  font=("Segoe UI Semibold", 13)).pack(anchor="w")
        ttk.Label(top, text="Under each line you said is the English that will be spoken over that "
                            "exact moment of the video. Change anything that is wrong — a name it "
                            "did not know, a term it translated. Fixing it here costs nothing.",
                  style="Dim.TLabel", wraplength=800, justify="left").pack(anchor="w", pady=(3, 0))

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
            fa = tk.Label(card, text=s["said"].strip(), bg=PAN, fg=DIM, wraplength=740,
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


def shutil_which_python():
    """A frozen app has no Python of its own to build a venv with."""
    import shutil as sh
    for name in ("python", "python3", "py"):
        p = sh.which(name)
        if p:
            return p
    for root in (os.environ.get("LOCALAPPDATA", ""), r"C:\\"):
        for sub in ("Programs\\Python", "Python"):
            base = os.path.join(root, sub)
            if os.path.isdir(base):
                for d in sorted(os.listdir(base), reverse=True):
                    p = os.path.join(base, d, "python.exe")
                    if os.path.exists(p):
                        return p
    return None


if __name__ == "__main__":
    app = App()
    try:
        app.mainloop()
    finally:
        R.stop_local()
