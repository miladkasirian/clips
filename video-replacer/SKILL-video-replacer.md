---
name: video-replacer
description: Build, change and maintain Course Video Replacer — the Windows app that replaces a recorded lecture's voice with American English while keeping it in step with the picture. Use whenever touching this project's code, its guide, its tests, its exe, or the YouTube route.
---

# Course Video Replacer

Everything learned building this, in the order you would need it. Written for
whoever picks it up next, including me.

> **The one-line summary.** A lecture in any language goes in as an `.mp4`; the
> same video comes out with an American English voice locked to the original
> timing, plus subtitles in both languages and a report of anything that had to
> be squeezed. Nothing about the picture is re-encoded and, unless the YouTube
> route is switched on, the video never leaves the computer.

---

## 1. How to work on this

These are not style preferences. Each one was learned by getting it wrong.

| Rule | Why |
|---|---|
| **Everything happens inside the exe.** No terminal steps, no config editing, no second file to run, no "just paste this link". | Asked for three times. A standalone test script is the wrong answer even when it is the fastest one — build the check into the app and let the app report the failure. |
| **Measure before changing anything, and measure again after.** | Every real fix here came from a number: 6.6 s of drift, 23 lines that would not fit, 0.7× vs 2.3× real time, four transcriber settings on one real minute. Every wrong guess came from reasoning without one. |
| **A test that only passes is not evidence.** Make it reproduce the bug first, then show the fix. | The drift test runs the same lecture twice — with the cap and without — so it has to produce 5.6 s before it can claim 0.8 s. |
| **Say the problem before the solution.** If the user's own answer to their question is wrong, say so in the first sentence and explain the constraint. | He asks direct questions and prefers being contradicted to being humoured. |
| **When he says stop, stop.** | It was violated once and it cost trust that took a long time to earn back. |
| **Never handle his secrets.** Create the empty file, open it for him, tell him where to paste. | `key.txt`, `client_secret.json`, `youtube_token.json` are all his to type. |
| **Report what a service said, not what you think it meant.** | The log inferred "typed by hand" from `trackKind != "ASR"` and told him a caption he never typed was his. Print the fact. |
| **Diagnose before you fix. The obvious suspect is usually innocent.** | A stuttering voice looked exactly like `atempo` artefacts at 160%. Measured on his own output: no difference at all between sped-up, slowed and natural lines. The real cause was three layers away. |
| **A long file is not an error, so nothing catches it. Make something catch it.** | The cloned voice returned ten seconds of audio for a five-second sentence — half of it noise — and every stage downstream treated that as a slow line and squeezed it. Wherever a component can fail *plausibly*, add a cheap sanity check against something you already know. |
| **When two attempts at a fix fail the same way, the input is wrong, not the algorithm.** | Two versions of `resplit` chose among YouTube's caption boundaries. Measuring showed 35 of 36 of those boundaries were nowhere near a pause. The third version threw them away. Measure the *input* before refining the method. |

Answer him in Persian. Keep the code, comments, UI and documents in English.

---

## 2. The folder

```
Course Video Replacer\
  Course Video Replacer.exe   the program. Double-click. ~11.9 MB
  app.pyw                     the window: four tabs, review panel, buttons
  replacer.py                 the entire pipeline. Runs with or without a window
  test-pipeline.py            58 checks. No network, no spend
  build-exe.bat               PyInstaller, one double-click
  make-icon.py                draws icon.png (120x120) and icon.ico
  guide.html                  the whole manual, screenshots embedded
  config.json                 every setting, written on Start
  glossary.txt                sounds like = must be
  key.txt                     OpenAI key            GITIGNORED
  client_secret.json          Google desktop client GITIGNORED
  youtube_token.json          YouTube sign-in       GITIGNORED
  input\ output\ work\ voice\ samples\ ffmpeg\ .venv\ _build\
```

`work\` is emptied on close, on Cancel at the review panel, and when a run ends.
`voice\*.wav` is the only irreplaceable thing in the folder — each file **is** a
cloned voice; there is no model beside it.

**The architecture rule:** every decision lives in `replacer.py` and it must run
headless. `app.pyw` only collects settings, draws, and passes two callbacks:
`say(text)` for the log and `ask(segs) -> segs | None` for approval. The pipeline
does not know or care whether a window exists. This is what makes the whole thing
testable without a display.

---

## 3. The pipeline

| # | Step | Where | Notes |
|---|---|---|---|
| 1 | pull the sound out | ffmpeg | 32 kbps mono, ~14 MB/hour. On the YouTube route it is still pulled out — locally, only to find the pauses — but never sent anywhere |
| 2 | write down what was said | `whisper-1`, or YouTube | see §5 and §6 |
| 2b | proofread | `gpt-4o` | spelling only, forbidden to invent |
| 2c | join fragments into sentences | local | `merge()` on the Whisper path, `resplit()` on YouTube's — opposite rules, see §4 |
| 3 | translate | `gpt-4o` | per line, each told its word budget |
| 3b | **fit** | `gpt-4o` | shorten only what even 160% speed cannot save — §4 |
| — | **approve** | the panel | nothing spoken, nothing spent on voice |
| 4 | speak and place | OpenAI TTS or XTTS-v2 | §4 |
| 5 | mux | ffmpeg `-c:v copy` | picture never re-encoded |
| 6 | subtitles | local | both files, same clock |

**`whisper-1` is not a legacy choice, it is the only choice.** It is the only
OpenAI model that returns timestamps (`response_format=verbose_json`,
`timestamp_granularities=["segment"]`). `gpt-4o-transcribe` supports only `json`.
Without timestamps there is nothing to line the English up against. Do not
"upgrade" it.

---

## 4. Timing — the hard part, and where the real bugs were

### Sentences, not fragments

The transcriber returns short pieces. A real two-minute lecture came back as **37
of them**, some two seconds long. Two seconds holds about five spoken words, so
one fragment could not fit however it was written while its neighbour sat idle —
and neither can lend room to the other while they are separate lines.

`merge()` joins fragments less than `join_gap` (0.8 s) apart into sentences up to
`longest_line` (10 s). With that plus a per-line word budget in the translate
prompt: **23 lines that would not fit became none.**

### YouTube's captions are not sentences, and need the opposite treatment

> The single most misleading bug in the project so far. Read this before touching
> anything that reasons about line boundaries.

**YouTube writes rolling captions.** Every cue's display window overlaps the next
by two to five seconds, so the text stays on screen while the next line arrives.
The *words* in each cue are new; the *end time* is when it stops being shown, not
when he stopped talking. On a real three-minute lecture, **all 37 cues overlapped
the next one.**

Two consequences, both silent:

* `merge()`'s test is `next.start - previous.end <= gap`. With overlapping cues
  that value is always negative, so **everything joins**, and the only thing that
  ever breaks a line is the 10-second cap — a blind cut, landing mid-sentence.
* The result was half-sentences spoken as separate utterances with pauses between
  them. The report is the evidence, once you know to look:

```
line 11  "It creates a name for me. How? When I"
line 27  "hit start. What happens is that a"
```

One sentence, two lines, a gap in the middle. **That is what "it sounds like he
has a stutter" actually was.** No amount of tuning the speed touches it.

**The fix, in two parts:**

1. `parse_srt()` sorts by start and pulls each cue's `end` back to the next cue's
   `start`. Gaps stop being negative and everything downstream can reason again.
2. **Throw the cue boundaries away entirely.** This took three attempts and the
   first two were both wrong in the same way, so the measurement is the point:

   > Of the **36 caption boundaries** in a real lecture, **35 were more than a
   > third of a second from any real pause.**

   YouTube is not cutting where he stops; it is cutting where the line fills up.
   So *no* choice among those boundaries can produce a break in the right place.
   Attempt one asked "is this boundary near a pause?" — which leaves alone every
   boundary that is not, and the length cap then breaks those lines somewhere
   arbitrary. Attempt two inverted it — "each pause claims the nearest boundary"
   — which puts the break up to 1.6 s away from the pause it was chosen for.
   Both produced exactly what he reported: *"but the password"* / *"needs to be
   entered here"*, and *"...converted it to this"* / *"name, and it creates it
   for me"*.

   `word_times(cues)` lays every word on a timeline — within a cue the words are
   spread evenly across its span, an interpolation out by at most one word — and
   `resplit()` cuts **the words**, at the pauses, ignoring the boundaries
   completely. Worst break distance on the same lecture: **3.7 s before, 0.7 s
   after.** A line then begins and ends where he began and ended, so a line that
   stops mid-thought stops exactly where he did, which is how it should sound.

   `silences(..., with_length=True)` returns `(start, length)`; only a pause of
   0.45 s or more counts, because a hesitation is not a full stop.

Measured on the same lecture: 37 cues to **24 arbitrary chunks** the old way,
**17 lines that end where he stopped talking** the new way.

> **This means the audio IS extracted on the YouTube route**, locally, purely to
> find the pauses. It is not uploaded and not sent to OpenAI. The guide used to
> claim the step was skipped entirely; that claim had to be corrected, and any
> future claim like it needs checking against the code.

`merge()` still handles the Whisper path, whose fragments have real gaps. Do not
fold the two into one function: they need opposite rules, and the run decides
which by whether the words came from YouTube (`rolling`).

### How that was found, since the method matters more than the answer

Three measurements on **his own finished file**, in this order, each one killing
a hypothesis:

1. **Is it `atempo`?** Compared a per-line repetition score — how similar each
   25 ms window is to the one before it, which is WSOLA's fingerprint — across
   lines at 0.90, 1.00 and 1.26. Means: 0.420, 0.473, 0.434. **No difference**,
   and the worst-scoring lines were all at natural speed. Hypothesis dead.

   *(The wind-noise report needed a different measurement again: framewise
   autocorrelation "voicedness" across the suspect line, which found two full
   seconds at 0.15–0.30 where speech sits at 0.6–0.9. Cheaper alternatives —
   zero-crossing rate, envelope "syllable swing" — both produced false positives
   on ordinary speech and were not good enough to gate anything on. Voicedness is
   too slow to run per line in Python, which is why the shipped check is the
   duration test instead: same failure caught, a thousandth of the cost.)*
2. **Is a whole syllable being repeated?** Looked for any 220 ms stretch closely
   matching the 220 ms after it. Nothing convincing — but two lines flagged the
   *same instant*, 71.92 s and 71.96 s, which meant two lines' audio was landing
   in the same place.
3. **Why?** Printed every line's span and the gap to the next. Every single one
   overlapped. That was the whole answer.

A sweep-based comparison of `atempo` against `rubberband` was also run and showed
atempo to be *smoother* on a synthetic sweep — a reminder that a clean
measurement of the wrong thing tells you nothing. `rubberband` **is** available in
the Gyan full build (`--enable-librubberband`) if some future problem genuinely
does turn out to be time-stretch quality.

### Drift — the bug he actually heard

The old placement rule was `start = max(own moment, end of previous line)`. One
sentence whose English did not fit put **the next fifteen lines up to 6.6 seconds
behind the picture**, taking 45 seconds of video to recover, because only a real
pause could resync.

The fix, in three parts:

* `max_drift` (0.75 s) — a line is never later than this behind its own moment
* while behind, it may hurry to `catch_up_tempo` (1.45) instead of `max_tempo`
* while behind, a short line is **not** stretched to fill its slot — stretching
  when you are late is how you stay late

Measured after: worst case **0.8 s**, recovering on the very next line.

### The order of preference — speaking faster loses nothing

```
1. before approval: measure against the chosen voice, rewrite what
   even 160% cannot save                     (§ fit_english)
2. natural speed
3. up to max_tempo        1.20
4. up to catch_up_tempo   1.45   only when already behind
5. up to squeeze_tempo    1.60   rather than cut anything at all
6. cut the tail, with a 45 ms fade            (fade_tail)
```

Step 1 means step 6 should never be reached. **Never reorder these.** Cutting
loses words; speeding up does not. `atempo` changes speed without changing pitch,
so a hurried line still sounds like the same person.

### Written one way, spoken another

`glossary.txt` decides what is **written** — it belongs in the subtitles, the
review panel and the report. `say.txt` decides only what reaches the **voice**:

```
ChatGPT = Chat G P T
OpenAI  = Open A I
```

"ChatGPT" is right on screen and wrong in the mouth; "Chat G P T" is the reverse.
`as_spoken()` substitutes on a **copy** of the line inside `speak()`, at the last
moment, so nothing anyone reads is ever changed. Keep these two files separate —
merging them would force one answer onto two different questions.

### The writer's instructions are his to edit

`TRANSLATE` is the default; `writer_prompt` in config overrides it;
`writer_rules(cfg)` picks. The Settings tab shows the text in an editable box
with a **Reset** button.

> **`writer_prompt` is stored blank while it still matches the built-in text.**
> Compare whitespace-normalised, and only save a copy once he has actually
> changed something — otherwise an improvement to `TRANSLATE` is frozen out for
> ever by a copy he never meant to keep.

### A bad take from the voice, and how it is caught

**A cloned voice does not fail loudly. It rambles.** One fourteen-word sentence
came back as **ten seconds** of audio — five of speech and five of noise that
sounds like wind — and every stage after it treated that as a very slow line and
sped it up to fit. Nothing in the pipeline could tell, because a long file is not
an error.

**The words are the check.** The voice's speed is measured before the run
(`voice_rate`), so how long a line *should* take is known: 14 words at 2.743 w/s
is 5.1 s. The bad take was 9.98 s — **1.96×**. `speak()` now times every take and
says the line again when it falls outside `shortest_take` (0.60) to
`longest_take` (1.65) of what its words should take. Retries are free for the
cloned voice and default to 2; a bought voice gets 1. If no attempt comes back
right, the closest is used and the log says so.

Too *short* is caught by the same test and means the opposite failure: the voice
dropped words.

> `voice_rate()` must call `say_once()`, not `speak()` — the check needs the rate
> that the calibration exists to produce.

### Fitting before approval

`voice_rate(cfg, k)` has the chosen voice say one fixed sentence, times it, and
keeps words-per-second in `config.json` under `voice_rates`. A cloned voice and a
ready-made one are not the same speed and every fitting decision comes from this
number. Costs a fraction of a cent, once per voice, ever.

`fit_english()` then rewrites only the lines that would not fit at the squeeze
ceiling, keeps the old text in `s["was"]`, and sets `s["fit"]` (the word
allowance) on every line. The panel shows both: the allowance in the header, and
`"shortened to fit — it read: ..."` in gold under any line that was rewritten, so
he can put his own words back before anything is spoken.

### Placement mechanics

`build_track` writes raw PCM into one silent file **by byte offset**. With several
hundred lines an `amix` of that many inputs is slow and imprecise; byte offsets
are exact by construction. `int(start * rate) * 2` — the `* 2` is 16-bit samples,
and the offset must be even or the audio is garbage.

### Reporting

Two different things go wrong and must never be blamed the same way:

* **culprit** — this line's English is too long for its own moment
* **pushed / sped up** — a consequence of somebody else's line

Getting this wrong once turned one bad line into a report naming twenty-three,
which sent him fixing the wrong sentence. The tuple is
`(index, start, message, is_culprit)` and only culprits are worth acting on.

A related bug: the report said `pushed 0.0s late by the lines before it` because
the branch was chosen by overrun rather than by lateness. **Do not report a
number that is zero as though it were a finding.**

---

## 5. Transcript quality — what was measured

One real minute of his lecture, four ways:

| Tried | Result |
|---|---|
| `whisper-1` as it was | baseline |
| + told the language is Persian | **nothing at all** — byte-identical output |
| + the glossary handed to it as a prompt | **the win.** "Add Voice" not اد ویس, "Output" not اد پود, تبدیل not تبلیل |
| `gpt-4o-transcribe` instead | not better — different mistakes, not fewer, and no timestamps |

**Most errors were English terms said inside Persian sentences.** Both sides of
every glossary line go into the whisper `prompt`: knowing a word is coming is what
lets it hear the word. It costs nothing.

The `language` setting therefore earns its place in exactly one case — a lecture
that switches between two languages, where the guess can wander. Otherwise leave
it blank.

---

## 6. The YouTube route

YouTube's Persian is better than anything reachable through an API. Say so; it is
true and pretending otherwise helps nobody.

### What it does

Choose the mp4, press Start. Behind the scenes: **upload unlisted → wait for the
captions → read them → delete the upload → rejoin the cues and cut them at the
pauses in the recording** (§4 — do not skip that last step, it is what stops the
voice sounding broken). No link to paste. The delete is in a
`finally`, so it happens whether or not anything above it worked, and if the
delete itself fails the log **shouts in capitals with the video id** — a lecture
quietly left on a channel is the one outcome that must never happen silently.

### The Google setup, from zero

1. Cloud console → new project → **Library** → enable **YouTube Data API v3**
2. **Google Auth Platform → Branding**: app name, email, **home page URL**,
   **privacy policy URL**, and both domains under **Authorized domains**.
   Google will not publish without the last two.
3. **Data Access** → add `https://www.googleapis.com/auth/youtube.force-ssl`.
   That one scope covers upload, read captions and delete.
4. **Audience → Publish app.** *Not optional.* An app left on **Testing** expires
   the refresh token **every seven days**. Unverified in production is fine: a
   warning screen and a 100-user cap.
5. **Clients → Create client → Desktop app** → Download JSON.
6. In the app: **Choose client_secret.json** (it copies the file into place),
   then **Sign in** (loopback flow, PKCE, browser opens once).

Everything must be done on the account that **owns the channel**.

### Quota, per lecture

| Call | Units |
|---|---|
| `videos.insert` | 1, but a separate cap of **100 uploads a day** |
| `captions.list` | 50 — **each poll**, every 20 s while waiting |
| `captions.download` | 200 |
| `videos.delete` | 50 |

10,000 a day → about **25 lectures**. The polling is the only way to burn it
fast, and that is also the case that gives up and hands the job to Whisper.

### The risk, and the thing that was wrong for weeks

**YouTube locks videos uploaded through an unaudited API project as private, and
that cannot be appealed.** The video is deleted within minutes so nothing should
remain — but it is his channel, and this is stated in the guide in a box he
cannot miss, not buried.

It was also widely reported that `captions.download` refuses ASR tracks even for
the owner. **On the first real run it did not refuse.** One account, one video —
not proof for everyone, but it is why the route exists and it works.

---

## 7. Voices

Eleven ready-made (`onyx ash echo ballad verse sage alloy fable coral nova
shimmer`), all the same price. Male: onyx, ash, echo, verse.

**Add a voice…** takes any audio or video ffmpeg can read and makes a clone:
mono, 22 050 Hz, leading silence trimmed, **capped at 40 seconds** (past that the
model gains nothing and only gets slower), written as one `.wav` in `voice\`.
That file *is* the voice.

Give it a recording **in English**, not Persian — the model copies the timbre of
whatever it is given, and handing it the language it must produce gives it far
more to work with. The difference is audible in `samples\`.

XTTS-v2, installed into a `.venv` beside the app. Licensed **non-commercial**.
The model itself downloads once, ~1.8 GB, on first use. It runs as a persistent
subprocess worker because loading the model takes ~15 s and must not repeat per
line — see `WORKER` in `replacer.py`.

**Both** voices are trimmed with `trim_silence` now. It used to be only the
cloned one, which quietly made every ready-made line longer than its words and
made the drift worse for no reason.

---

## 8. Traps that cost real time

### `pip install torch` on Windows gives the CPU build, silently

It installs, it imports, it runs — three times slower than it should, for ever,
with no warning. CUDA needs
`--index-url https://download.pytorch.org/whl/cu126`, and an existing CPU build
must be uninstalled first. Measured: **0.7× real time on the card, 2.3× on the
processor** — 40 minutes versus over two hours for an hour of lecture.

The Settings status line therefore does not say "installed". It asks the
installed torch which device it will actually use and reports that, so a silent
CPU build cannot hide.

**torch is pinned to 2.8.0.** 2.9+ pulls `torchcodec`, which needs ffmpeg
*shared* DLLs; the static Windows build has none.

An earlier install upgraded `transformers` inside his main Anaconda and broke
coqui. Everything for the local voice goes in `.venv` and nowhere else.

### winget's PATH

winget adds itself only to the PATH of shells opened *afterwards*. `tool()`
searches PATH, then the local `ffmpeg\bin`, then winget's Packages folder.

### PyInstaller can build a crippled exe and say nothing

Run from a shell with a stripped PATH it could not resolve `tcl86t.dll` /
`tk86t.dll` and produced a **9.9 MB** exe instead of ~11.9 MB, leaving out the
Tcl/Tk data. It launched. It looked fine. It misbehaved.

> **If the built exe is not around 11.9 MB, it is not a complete build.**

Also: the exe cannot be replaced while it is running. Check first and say so
rather than failing halfway.

Build line (the icon is easy to lose on a rebuild):

```
--onefile --noconsole --name CourseVideoReplacer --icon "..\icon.ico"
--exclude-module torch --exclude-module TTS --exclude-module numpy
--exclude-module matplotlib --exclude-module scipy --exclude-module pandas
```

### Console death on the first Persian word

cp1252. Every entry point does
`sys.stdout.reconfigure(encoding="utf-8", errors="replace")`.

### Name collisions

`started()` shadowed by `var started = 0`; a pipeline `run()` shadowed the
subprocess helper. Both silent, both took a while. Grep before naming.

---

## 9. tkinter on Windows

| Problem | Fix |
|---|---|
| Ticks and radios go **pale under the pointer** and white text vanishes | `clam` paints its own light colour on `active`/`focus`. Name **every** state — active, focus, selected, pressed and the pairs — and `focuscolor`, which draws the dotted ring. Do it for `TCheckbutton`, `TRadiobutton` and the `Card.` variants. |
| Window opens **bigger than the screen** | tk is not DPI-aware, so a display at 150% reports fewer units than its pixels. **Never hardcode geometry.** Measure `winfo_screenwidth/height`, subtract margins, take what fits. |
| A tab taller than the window | Wrap it in a Canvas + Scrollbar, show the bar only when needed. A setting you cannot scroll to is a setting that does not exist. |
| Long hints run off the right edge | `wraplength` on every hint label. `_row()` does it centrally. |
| A `ttk.Checkbutton` caption is clipped | **ttk checkbuttons have no `wraplength`.** Keep the caption short and put the sentence in a `Dim.TLabel` underneath. |
| `invalid command name ..._drain` on close | Keep the `after` id and `after_cancel` it in `shut()`. |
| Screenshots come out scaled or cropped | `ctypes.windll.user32.SetProcessDPIAware()` **before** creating Tk, then `ImageGrab.grab(bbox=..., all_screens=True)` with `winfo_rootx/rooty`. |

Layout that works: **two columns on Convert** — settings left in a scrolling
pane, the log right and full height. Start and the two ticks live *outside* the
scrolling part, pinned to the bottom, so the button you came to press is never
the thing that falls off the edge.

The window must only ever be touched from the main thread. The pipeline runs in a
worker thread and talks to the window through a `queue.Queue` — `("log", text)`,
`("review", segs)`, `("done", path)`, `("fail", why)` — drained by `_drain()` on
an `after` tick.

---

## 10. Testing

`python test-pipeline.py` — **58 checks, no network, no spend.** It stubs `post()`
with something that raises, so a test that reaches for OpenAI fails loudly rather
than quietly costing money.

What it actually does, and why it is worth copying:

* **Measures the finished audio.** Each line is spoken at its own pitch, so a
  tenth of a second of sound can be traced back to the line it came from and the
  answer is *where that line really landed* — not where the code says it put it.
* **Shows the bug before the fix.** The drift check runs the same lecture twice,
  once with the cap and once without, and asserts the 5.6 s **and** the 0.8 s.
* **Proves both paths agree.** The same lines, whether the words came from
  Whisper or YouTube, must place the audio **byte for byte identically**.
* **Reproduces the caption shape that caused the bug.** Four cues with the exact
  overlapping windows YouTube produces, then: the ends are pulled back, the gaps
  stop being negative, the cues rejoin and cut only at the one real pause, and the
  old gap rule is shown producing more lines than the new one on the same input.
* **Opens the real window** for the UI checks: every setting survives a restart,
  no widget goes pale in any state. Skips itself where there is no display.
* **Builds the YouTube upload against a stubbed transport**: unlisted, whole, in
  the right byte ranges, and **deleted even when the captions never arrive**.

> ### The harness trap — it has now happened four times
> `main()` replaces `R.config`, `R.transcribe`, `R.yt_transcript`, `R.fit_english`,
> `R.voice_rate` and `R.speak` with stubs. A later check that calls one of those
> is exercising the stub, not the code, and will report a bug that is not there
> or miss one that is. **Capture the real functions at import** — `REAL_CONFIG`,
> `REAL_YT`, `REAL_FIT`, `REAL_RATE`, `REAL_SPEAK` — and call those. It will
> happen again; suspect it first whenever a new check reports something
> impossible.

Run headless with `xvfb-run -a --server-args="-screen 0 1400x1000x24" python3.12`.

---

## 11. Building the guide

`guide.html` is one self-contained file with the screenshots embedded as data
URIs. It is written in parts and assembled, because a 250 KB file with base64 in
it is not editable by hand.

1. **Parts.** `_g/00_head.html` (CSS + nav), then numbered sections. Images are
   referenced by placeholder: `src="IMG_convert"`.
2. **Screenshots, from the real window on Windows** — never from Linux, because
   tk there has no bidi shaping and Persian comes out reversed. A throwaway
   `_shots.py`: `SetProcessDPIAware()`, build the App, set fields to realistic
   values, `snap()` each tab, then the Review panel. Delete the script afterwards.
   **Set every state explicitly before its shot** — two screenshots came out
   byte-identical because his `config.json` already had the state I was about to
   set.
3. **Shrink.** `Image.quantize(colors=96, dither=NONE)` — the UI is flat, so this
   halves the size with no visible loss. Seven shots ≈ 160 KB.
4. **Assemble** and replace each placeholder with `data:image/png;base64,...`.
5. **Validate, every time**:
   * every `<a href="#x">` has a matching `id`
   * `<div> <table> <ol> <ul> <li> <figure>` open/close counts match
   * **no literal `\uXXXX` left in the output.** Writing the HTML through a
     Python string that is itself written by a script means an escape can survive
     into the file as six characters. `re.sub(r'\\u([0-9a-f]{4})', ...)` and
     assert none remain.
   * grep for instructions that the last change made false
6. **Look at it.** Render with Playwright (`/opt/pw-browsers/chromium`) and read
   the sections you changed. A full-page screenshot of a very tall page can come
   back blank in headless — that is a compositing artifact, not a layout bug;
   screenshot the element instead.

The guide assumes **nothing**: it starts at "make a GitHub repository" and ends at
"your exe is the wrong size, here is how to tell". Prices are checked against the
vendor and dated. Where a number is an estimate it says so — the token-billed
step is given as a range with its assumption stated, because it cannot honestly
be given as one number.

---

## 12. Shipping a change

```
1. edit here            → 2. run the tests headless
3. SendUserFile         → 4. device_commit_files onto his machine
5. run the tests THERE  → 6. rebuild the exe (skip if the app is open, say so)
7. smoke test the exe: launch, close, assert work\ is empty
8. copy into repo\video-replacer\, config.json with voice "onyx"
9. commit, push
```

Never push `key.txt`, `client_secret.json`, `youtube_token.json`, `voice\`,
`*.exe`, `*.mp4`. The repo copy of `config.json` has the preset voice, not
`mine:Milad`, which points at a file that is not there.

**Commit messages are prose, not changelogs.** Say what was wrong, what the
number was, what changed, and what it cost. Anything measured goes in with its
figure. If a test caught its own harness, say that too — it is the most useful
sentence in the message.

---

## 13. Cost, as of August 2026

| Step | Model | Price | Per hour |
|---|---|---|---|
| transcribe | `whisper-1` | $0.006/min | ~36¢ |
| proofread + translate | `gpt-4o` | $2.50/1M in, $10/1M out | ~30–50¢ |
| speak | `gpt-4o-mini-tts` | ~$0.015/min of audio | ~90¢ |

**Under $2 an hour.** YouTube for the transcript saves the 36¢; a cloned voice
saves the 90¢; both together bring it to roughly 30–50¢.

The middle row is a range **on purpose**: it is billed per token, and how many
tokens an hour of speech becomes depends on the speaker and the language. Give
the assumption, not a false precision, and point at the Usage page.

---

## 14. Open questions

* `captions.download` worked for an ASR track on his account. Whether that holds
  generally is unknown — treat a 403 as expected and fall back, which the code
  already does.
* Everything about transcript quality was measured **on Persian**. The same
  machinery applies to any language and there is no reason it would differ, but
  that is reasoning, not evidence. Read `.original.srt` once after a run in a
  language not used before.
* The bad-take band is 0.60× to 1.65× of expected. Wide enough that a naturally
  slow or emphatic line is not re-spoken, narrow enough to catch a two-second
  ramble. Checked against one voice on one lecture.
* `resplit` calls a pause `-30dB` for at least 0.30 s and only breaks on one of
  0.45 s or more. Word times inside a cue are interpolated, so a break can be a
  word out; with word-level timestamps (whisper can give them) it would be exact.
* Lines whose English is much shorter than the Persian took still leave real
  silence in the slot. That is honest — the English *is* shorter — but he has
  noticed it, and padding it would mean inventing words. That worked on one lecture
  in one room. A noisier recording finds fewer pauses and produces longer lines; a
  very quiet one finds too many. If lines come out consistently wrong, that pair
  of numbers is the first thing to look at.
* The drift cap is 0.75 s because it is imperceptible for lecture sync and
  generous enough that ordinary overruns are not cut. It has not been tuned
  against a long lecture with many long sentences.
