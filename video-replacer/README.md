# Course Video Replacer

Your recorded lecture, in an American voice, still in sync with the picture.

```
your.mp4  →  your.en.mp4        the video, your voice replaced
             your.original.srt  subtitles in the language you spoke
             your.english.srt   subtitles in English
             your.report.txt    every line that had to be squeezed
```

## Use it

Double-click **Course Video Replacer.exe**. That is the whole thing — there is
nothing else to run and nothing to edit by hand.

| Tab | What is in it |
|---|---|
| **Convert** | the video, the language you spoke, where results go, whether to show you the English first, how much a line may be sped up — then **Start** |
| **Voice** | every voice you can use. **Hear it** plays a sample. **Add a voice…** makes a new one from any recording |
| **Words to keep right** | the glossary, for names it would otherwise get wrong |
| **Settings** | your OpenAI key, ffmpeg, the local voice, and the models |

**Remember these settings** next to Start writes everything into `config.json`,
so the app opens the way you left it.

The first time: go to **Settings**, paste your OpenAI key, press **Save**. If
ffmpeg says *missing*, press **Get it** — the app fetches it itself.

### Any language in, English out

The transcriber knows about a hundred languages and works out which one it is
hearing on its own, so a lecture in Hindi is the same run as one in Persian:
choose the file and press Start. The dropdown on **Convert** is there for the one
case that needs it — a lecture that switches between two languages, where the
guess can wander. Any ISO code can be typed into it.

Measured on a real Persian lecture, naming the language changed *nothing*: the
transcript came back identical.

If you were already speaking English, this is a **rewrite, not a translation** —
your words kept where they work, the false starts and the "um"s gone, and then the
American voice you picked speaks it instead of you.

### The panel before it speaks

Partway through, a window opens with one card per line: the moment it covers,
how many words fit there, what you said, and a box with the English that will be
spoken over it. Fix anything wrong and press **Approve and make the video**.

Nothing has been spoken when that panel opens, so a name the translator got
wrong costs nothing to fix there and a whole run to fix afterwards.

### A voice of your own

**Settings → The local voice → Install** (a few gigabytes, all inside `.venv`
beside the app — nothing else on the computer is touched). Then **Voice → Add a
voice…**, pick any recording of someone speaking, name it, and it is in the list.

Give it a recording in **English**, not Persian. The model copies the timbre of
whatever it is given, and giving it the language it has to speak gives it far
more to work with — compare `_your-cloned-voice.mp3` with
`_cloned-from-persian.mp3` in `samples\`.

It runs on this computer, so it costs nothing to use and nothing leaves.

**Tick "Use the graphics card"** when installing. `pip install torch` on Windows
gives the CPU build and nothing warns you — measured here, the card is
**0.7× real time against 2.3× on the processor**, so an hour of lecture takes
forty minutes instead of over two hours. If the card runs out of memory the voice
moves to the processor by itself and says so.

## What happens, and where

| Step | Where | Why |
|---|---|---|
| take the sound out | ffmpeg, here | 32 kbps mono — an hour is ~14 MB |
| write down what you said | OpenAI `whisper-1` | the only model that returns timestamps |
| turn it into English | OpenAI `gpt-4o` | per line, with the lines around it for context |
| speak it | OpenAI `gpt-4o-mini-tts`, voice `onyx` | the same voice as the clips page |
| fit it to the picture | ffmpeg, here | see below |
| put it back on the video | ffmpeg, here | `-c:v copy` — the picture is never re-encoded |

**Your video is never uploaded anywhere.** Only the small audio file is sent,
and only to OpenAI. Nothing is stored on any service, so there is nothing to
delete afterwards. The `work\` folder is removed when a run finishes.

### Why not YouTube

Uploading the video to borrow YouTube's captions costs 1600 quota units per
upload — six a day out of 10,000 — needs OAuth rather than an API key, only
works for videos you own, and is widely reported to refuse the automatic
captions. It would also mean waiting on a queue you do not control and then
remembering to delete a private lecture from the internet. Taking the audio out
here is faster, predictable, cheaper, gives real word timestamps, and leaves
nothing behind.

### Choosing the voice

`python voices.py` writes a ten-second sample of every voice into `samples\`,
all at the same price. Play them, then put the one you want in `config.json`.

### The one hard problem

English is never the same length as the Persian it came from. In order:

1. say it at a natural speed;
2. if it will not fit, speed it up — never past `max_tempo` in `config.json`
   (1.20). `atempo` changes speed without changing pitch, so the voice still
   sounds like the same person;
3. if it still will not fit, use the silence that follows it;
4. if it **still** will not fit, let it run over and name it in the report.

**Why sentences, not fragments.** The transcriber hands back short pieces — a
real two-minute lecture came back as 37 of them, some two seconds long. Two
seconds holds about five spoken words, so *"When I select Spin here, the videos
start playing"* could not fit however it was written, while *"And there,"* sat
next door in two seconds with nothing to do. Neither can lend room to the other
while they are separate lines. Joined into sentences, and with each line told in
the prompt how many words its moment allows, the same lecture went from **23
lines that would not fit to none**.

The picture is never touched and the sound never drifts far from it. Read
`report.txt` after a run: anything listed as *"runs past its slot"* is a
sentence worth shortening, and the fix is to say less in that moment, not to
make the voice unlistenable.

## Settings — `config.json`

| | |
|---|---|
| `max_tempo` | how fast a line may be pushed to fit. `1.0` = never speed anything up |
| `min_tempo` | how much a very short line may be slowed |
| `longest_line` | fragments closer together than `join_gap` are joined into sentences up to this long |
| `join_gap` | a pause longer than this is left as a break between lines |
| `chunk_minutes` | how long each piece sent to the transcriber is |
| `voice` | `onyx`, `ash`, `echo`, `cedar` are the male ones |
| `keep_work` | `true` keeps the intermediate files, so a re-run skips what is done |

## If it stops

A run keeps `heard.json` and `english.json` while it is going, so if it fails
part way through, set `keep_work: true` and run it again — it will not pay for
the transcription or the translation twice.

## Cost

Roughly, per hour of lecture: transcription about 40¢, the English about 15¢,
the voice about 90¢. Under two dollars for an hour, billed to the OpenAI API
account — which is separate from a ChatGPT Plus subscription.

## Testing

`python test-pipeline.py` runs the whole thing on a made-up 40-second lecture
with the three paid steps replaced. It checks that each line lands on the moment
of video it belongs to, that the gaps stay silent, that the picture came through
as the same stream, that both subtitle files line up, and that a line too long
for its slot is capped and reported rather than allowed to trample the next one.
Nothing is sent anywhere and nothing is spent.
