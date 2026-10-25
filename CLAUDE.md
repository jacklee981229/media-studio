# CLAUDE.md: Media Studio

Jack's local photo and video tool for his trips: open a trip folder of iPhone originals, pick the keepers, give the whole trip one look, and export web-sized photos and ~7 s clips for Jack's Space. It runs only on this laptop, as a Python server on 127.0.0.1 with its screen in a Chrome app window. These rules add to `C:\repos\Jack\CLAUDE.md`.

## Commands

Run these in this folder.

- `start.cmd` (double-click): Jack's copy on 4710, in a Chrome app window. It stops itself 10 minutes after its window closes.
- `.venv\Scripts\python.exe -m unittest discover -s tests -t .`: the tests.
- My copy: the `media-studio-probe` entry in `C:\repos\Jack\.claude\launch.json` (port 4712, cache in the scratchpad).
- Setup on a fresh machine: `python -m venv .venv`, `.venv\Scripts\pip install -r requirements.txt`, and `ffmpeg.exe` and `ffprobe.exe` from gyan.dev's 9.0.2 essentials zip into `tools\ffmpeg\`.

## Where to look

- `main.py`: starting the server and the window. `studio/server.py`: the requests and their checks.
- `studio/trip.py`: one trip: scanning `originals\`, the cached index, thumbnails in worker processes, and the view the screen gets.
- `studio/meta.py` reads what files say about themselves; `studio/source.py` decides mine / received / screenshot; `studio/timeline.py` the capture time; `studio/similar.py` the look-alike stacks (its thresholds were measured on the Yunnan photos); `studio/subject.py` portrait or landscape, from the face regions the iPhone writes into XMP; `studio/looks.py` the trip looks A–D as colour tables (portraits at 40%); `studio/pictures.py` makes thumbnails, previews and look samples.
- Jack's choices for a trip (picks, portrait/landscape fixes, the two looks, the story's photos and words) live in its `studio.json`, written only through `Trip._update`.
- `studio/publish.py` and `Trip.publish`: the story page's 发布 puts the story's photos and clips into the media repo (`C:\repos\Jack\media\<address>\`, Jack's Space's `/media/`) and writes the post into `C:\repos\Jack\jacks-space\src\content\posts\<address>\`: `story.json` and `cover.webp` every time, `index.md` (a draft) the first time and afterwards only its title line (Jack may edit the rest by hand). The site reads `story.json` in `src/lib/travel/story.js`; change both sides together.
- `web/`: the screen (one page, plain JS).

## Safety rules

These are correctness issues, not style.

1. Never write, move, rename or delete anything in a trip's `originals\` folder. Open originals read-only. A test proves a whole run leaves every original's hash unchanged.
2. The server listens on 127.0.0.1 only, never on the LAN. It rejects requests whose Host isn't its own address, and changes come only as JSON requests, so another website open in Chrome can't drive it.
3. Requests name items by ID, never by path. File paths are built only from the trips folder listing and the trip's own index.
4. Exported photos and clips carry the capture date and time only: no GPS, no device. GPS stays in the trip's `studio.json`.
5. `studio.json` is written to a temporary file and then swapped in, so a crash can't lose Jack's picks.
6. Nothing talks to the internet: no CDN, web fonts, analytics or update checks.

## Where things live

- Jack sends photos and videos from his iPhone with LocalSend, saved straight into a trip's `originals\`.
- Trips: `%USERPROFILE%\Pictures\Trips\<trip>\`, holding `originals\` (read-only), `studio.json` (picks, looks, adjustments, clips, export format) and `export\` (what the tool makes: WebP for the website in `export\photos\` with `media.json`, JPEG for sharing in `export\jpeg\`, clips in `export\videos\`). Photo files are numbered in timeline order and renumbered when picks change, so the website must find photos by id through `media.json`, never by file name.
- Cache (thumbnails, previews): `%LOCALAPPDATA%\MediaStudio\`. Safe to delete; it is rebuilt.
- Songs for clips: `%USERPROFILE%\Music\Media Studio\`, music Jack may publish (his site is public): 8-second pieces, so a 7 s clip's music always starts at the piece's beginning (the screen has no song-start slider). The full songs they were cut from sit in its `完整版\` subfolder, with their credits in its `songs.json`; the story page picks one of those for a whole story (story clips are always silent; per-clip sound is for exports only).
- Not in git: `.venv\`, `tools\ffmpeg\`, the cache, and any real photo or video.

## Testing

- Tests point `config.TRIPS`, `config.CACHE`, `config.MUSIC`, `config.SITE` and `config.MEDIA` at temporary folders before touching any of them: one test once made Jack's real music folder.
- My copy publishes into the real `jacks-space` and `media` folders (the site's local preview reads them there). What it publishes is a draft and is never committed; Jack's own publish replaces it.
- Unit tests with Python's `unittest`. Test photos and clips are generated inside the tests (pillow-heif writes HEIC, ffmpeg makes HLG clips); never commit Jack's photos, since the repo is public. The one exception, by Jack's choice: the README's screenshot (`.github/readme/studio.webp`), picked landscapes only, no faces.
- Checks on real files read Jack's trip folder and write only to the scratchpad: my copy's trips folder is in the scratchpad, each trip's `originals` a junction (`mklink /J`) to the real one, so test picks never land in Jack's `studio.json`. Remove such a junction with `cmd /c rmdir "<junction>"` before deleting anything around it: a recursive delete in Windows PowerShell 5.1 can follow it and wipe the real originals.
- Jack's copy runs on port 4710. Mine run on 4712; never stop or restart his.
- No UI tests. I check the UI myself with screenshots in Chrome at Jack's screen size (about 1985×1047) and at 1366×768.

## Working on this PC

- Python 3.14 with the packages pinned in `requirements.txt`, inside `.venv\`. ffmpeg is the gyan.dev build unzipped into `tools\ffmpeg\`, never on PATH. Don't upgrade either without asking.
- The UI is plain HTML, CSS and JavaScript served by the Python server: no framework, no npm, no build step.
- Chinese text is in Noto Sans SC, installed on this laptop (Microsoft YaHei is the fallback); the app ships no font files.
- Around photos the UI is neutral grey, so colours can be judged; anywhere else, follow Jack's taste notes and the `/designer` skill.
