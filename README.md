# Random Clip Picker

A slot-machine spinner that picks one short clip at random and plays it in a custom
player. Not tied to any one course — the clip list *and* every label on the page come
from `clips.json`.

Two files do everything: **`index.html`** is the app, **`clips.json`** is the list.
The app holds no list of its own — change `clips.json` and the page changes. No build
step, no server code, nothing to install.

---

## Putting it online (about 2 minutes)

1. Create a repository on GitHub. Public is simplest; a private repo needs a paid
   plan for Pages.
2. Upload **the contents of this folder** — `index.html`, `clips.json`, `.nojekyll` —
   into the repository root. *Add file → Upload files*, drag, commit.
3. **Settings → Pages** → Source: *Deploy from a branch* → Branch: `main`, Folder:
   `/ (root)` → Save.
4. A minute later, open:

   ```
   https://<your-username>.github.io/clips/
   ```

That link is the whole thing. `index.html` is served automatically.

---

## Using it for another course

Nothing in `index.html` names a course. The `meta` block at the top of `clips.json`
carries the labels:

```json
"meta": {
  "appName": "Random Clip Picker",
  "badge": "302",
  "course": "ACC 302",
  "courseName": "Intermediate Accounting II",
  "heading": "Today\u0027s",
  "headingAccent": "Warm-Up",
  "subtitle": "One clip, picked at random. Watch it, then we discuss."
}
```

`badge` is the little square top-left (1–4 characters). Drop `course` and `courseName`
and the line under the name disappears. Leave `meta` empty and you get a plain,
unbranded page.

**One deployment, several courses.** Keep `fin220.json`, `acc302.json`, `fin322.json`
next to `index.html` and give each class its own link:

```
https://<you>.github.io/clips/?clips=acc302.json
```

---

## Changing the clip list

You never need this folder on your PC again. Open **`links.txt`** on GitHub, press the
pencil, edit, commit. Refresh the page and the new list is live.

It is just URLs, one per line:

```
https://www.instagram.com/reel/DV-g3wmDaLe/
https://youtu.be/dQw4w9WgXcQ
# https://www.instagram.com/reel/PARKED/     <- ignored, kept for later
```

Add a line, delete a line. That is the whole job. Numbering is automatic and no title
is needed — an untitled clip shows as **?** on the reel, which keeps the surprise.
The list is kept best-first, so the top of the file is the strongest material.

| Put this on a line | Starts by itself | Knows when it ended |
|---|---|---|
| `https://youtu.be/ID` — YouTube, Shorts included | **yes** | **yes** |
| `https://vimeo.com/123456789` | **yes** | **yes** |
| `https://anywhere.com/clip.mp4` — any direct video URL | **yes** | **yes** |
| `https://www.instagram.com/reel/CODE/` | no — one click | no |
| `https://drive.google.com/file/d/ID/view` | no — one click | no |

Instagram and Google Drive give their embedded players no JavaScript interface, so
nothing on the page can press play for them or be told when they finish. **Anything you
want to start on its own has to be YouTube, Vimeo, or a direct video URL.** That is a
limit of those two services, not of this page.

### Dead links take care of themselves

Instagram posts disappear. The page handles that on its own — you only ever open the
link.

Instagram's embed script reports back to the page: a reel that still exists sends
`LOADING → MEASURE → MOUNTED`, one that has been deleted sends `LOADING` and then
nothing. That is the whole test, and it needs no server, no API and no key.

- **On load**, every Instagram link is checked in a hidden frame, three at a time, and
  dead ones leave the pool before you ever press spin. The result is cached for the day,
  so this happens once — a reload is instant.
- **While playing**, if a dead one slips through anyway, the player notices within five
  seconds and rolls again by itself. Nothing appears on screen; the class sees the next
  clip, not an error.

You can still sweep the file by hand before uploading — double-click
**`build-for-github.bat`** and it comments out anything that has died:

```
# DEAD 2026-08-28 gone  https://www.instagram.com/reel/XXXX/
```

That keeps `links.txt` tidy, but it is optional. The page copes either way.

## Sources — where the page is allowed to look

`clips.json` has a `sources` array. Every entry is resolved when the page loads and all
of the results go into one random pool. **Click the chip at the top right of the page**
to see what each source returned, or the exact reason one failed.

| `type` | What it is |
|---|---|
| `clips` | An inline list, right there in `clips.json`. This is the one you edit. |
| `folder` | A folder of video files committed to the repo. GitHub Pages serves no directory listings, so this one reads the filenames from that source's `manifest` array. Off by default. |
| `gdriveFolder` | A shared Google Drive folder, listed automatically. Off by default, and it needs a free Google API key — Google returns *"Method doesn't allow unregistered callers"* to anonymous requests, so there is no key-free way. If you switch it on, restrict the key to the Drive API and to your Pages domain: it sits in a public file. |
| `json` | Another list file — a second one in the repo, or any `https` URL. Its clips join the same pool. |

Turn any source on or off with `"enabled": true` / `false`.

### One thing that cannot work

A page served from `https://…github.io` **cannot read files on the computer of whoever
is viewing it.** A `src` like `H:\Sem 6\clip.mp4` or `G:\My Drive\clip.mp4` works only
when you open the HTML locally by double-clicking it. On the web the page shows a
specific error card instead of a black box. If you want a clip of your own on the site,
either upload it to YouTube (unlisted is fine) and link it, or commit the file into a
`videos/` folder here — GitHub refuses single files over 100 MB.

`index.html` also carries a built-in copy of the list as a safety net, used only if
`clips.json` cannot be read at all — a typo that breaks the JSON, for instance. When
that happens the page says so on screen rather than failing quietly.

---

## Keyboard

`Space` spin · `R` replay · `F` fullscreen · `Esc` close
