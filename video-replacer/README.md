# Course Video Replacer

Your recorded lecture, in an American voice, still in sync with the picture.

```
your.mp4  →  your.en.mp4        the video, your voice replaced
             your.original.srt  subtitles in the language you spoke
             your.english.srt   subtitles in English
             your.report.txt    every line that had to be squeezed
```

## Once

Run **Setup.bat**. It gets ffmpeg and makes the `input` and `output` folders.
Then put your OpenAI key in a file called **key.txt** in this folder, on one
line. That file is in `.gitignore` and never leaves this computer.

## Every time

Drag an `.mp4` onto **Replace.bat**. Or drop the file in `input\` and
double-click Replace.bat — it takes the newest one.

Everything lands in `output\`.

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

### The one hard problem

English is never the same length as the Persian it came from. In order:

1. say it at a natural speed;
2. if it will not fit, speed it up — never past `max_tempo` in `config.json`
   (1.20). `atempo` changes speed without changing pitch, so the voice still
   sounds like the same person;
3. if it still will not fit, use the silence that follows it;
4. if it **still** will not fit, let it run over and name it in the report.

The picture is never touched and the sound never drifts far from it. Read
`report.txt` after a run: anything listed as *"runs past its slot"* is a
sentence worth shortening, and the fix is to say less in that moment, not to
make the voice unlistenable.

## Settings — `config.json`

| | |
|---|---|
| `max_tempo` | how fast a line may be pushed to fit. `1.0` = never speed anything up |
| `min_tempo` | how much a very short line may be slowed |
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
