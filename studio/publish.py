"""Publishing a trip's story to Jack's Space: the chosen photos, in their look, and clips go to the media repo
(<MEDIA>/<address>/, clips in its videos/, served at the site's /media/), and the post goes to
<SITE>/src/content/posts/<address>/: its story.json (the photos, clips and Jack's words, in timeline order) and, the
first time, an index.md draft and a cover.

The site reads story.json as it is (src/lib/travel/story.js); the photos' layout is export.file_name's.
"""
import json
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import export

MALAYSIA = timezone(timedelta(hours=8))


def address(trip_name: str) -> str:
    """The post's address and the photos' folder: '2026-10 Yunnan' becomes 'yunnan-2026'."""
    year = re.match(r'^(\d{4})-\d{2}\s+', trip_name)
    words = re.sub(r'[^a-z0-9]+', '-', trip_name[year.end():].lower() if year else trip_name.lower()).strip('-')
    if not words:
        raise ValueError('the trip folder needs a name in English letters, like 2026-10 Yunnan')
    return f'{words}-{year.group(1)}' if year else words


def title(trip_name: str) -> str:
    """The draft's title until Jack writes his own: the folder name without its year and month."""
    return re.sub(r'^\d{4}-\d{2}\s+', '', trip_name).strip() or trip_name


def story(folder: str, moments: list, music=None, intro='', outro='', intro_photo=None, outro_photo=None) -> dict:
    """story.json: each moment's photo or clip (by id), its size, when it was taken, the words under it and the
    place, if Jack named one; a clip also its length. With a song, the story's music: its file and its credit. The
    opening and closing words, if any, and the photo behind each if Jack picked one (else the site uses the first and
    the last)."""
    keys = ('id', 'kind', 'width', 'height', 'taken', 'words', 'place', 'after', 'seconds', 'joined')
    told = {'folder': folder, 'moments': [{k: m[k] for k in keys if k in m} for m in moments]}
    if music:
        told['music'] = music
    for key, words, photo in (('intro', intro, intro_photo), ('outro', outro, outro_photo)):
        if words.strip():
            told[key] = words
            if photo:
                told[f'{key}Photo'] = photo
    return told


MUSIC = 'music'


def song(src: Path, folder: Path, credit: dict) -> dict:
    """Copy the story's song into the trip's media folder; returns story.json's music entry."""
    out = folder / MUSIC
    out.mkdir(parents=True, exist_ok=True)
    name = f'song{src.suffix.lower()}'
    shutil.copyfile(src, out / name)
    return {'file': f'{MUSIC}/{name}', 'title': credit.get('title') or src.stem,
            **{k: credit[k] for k in ('artist', 'url') if credit.get(k)}}


def draft(heading: str, now: datetime) -> str:
    """index.md for a new travel post: a draft, so it shows only in the local preview until Jack publishes it."""
    stamp = now.astimezone(MALAYSIA).replace(microsecond=0).isoformat()
    return (f'---\ntitle: {json.dumps(heading, ensure_ascii=False)}\ndate: {stamp}\ntopic: travel\n'
            f'tags: []\ncover: ./cover.webp\ndraft: true\n---\n')


TITLE_LINE = re.compile(r'^title:[ \t]*(.*)$', re.M)


def read_title(post: Path):
    """The title in a post's index.md, or None if it has none yet."""
    page = post / 'index.md'
    found = TITLE_LINE.search(page.read_text(encoding='utf-8')) if page.exists() else None
    if not found:
        return None
    raw = found.group(1).strip()
    try:
        return json.loads(raw) if raw.startswith('"') else raw.strip("'") or None
    except ValueError:
        return raw


def set_title(post: Path, heading: str) -> None:
    """Change only the title line of a post's index.md: Jack may have changed the rest by hand."""
    page = post / 'index.md'
    text = page.read_text(encoding='utf-8')
    line = f'title: {json.dumps(heading, ensure_ascii=False)}'
    page.write_text(TITLE_LINE.sub(lambda _: line, text, count=1), encoding='utf-8')


def write_post(post: Path, heading: str, folder: str, moments: list, cover: Path, now: datetime, music=None,
               intro='', outro='', intro_photo=None, outro_photo=None) -> None:
    """Write the post's story.json and cover; index.md whole only if it isn't there, since Jack may have changed
    it, else just its title."""
    post.mkdir(parents=True, exist_ok=True)
    temp = post / 'story.json.tmp'
    temp.write_text(json.dumps(story(folder, moments, music, intro, outro, intro_photo, outro_photo), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(post / 'story.json')
    shutil.copyfile(cover, post / 'cover.webp')
    if not (post / 'index.md').exists():
        (post / 'index.md').write_text(draft(heading, now), encoding='utf-8')
    elif read_title(post) != heading:
        set_title(post, heading)


def stale(folder: Path, moments: list, music=None) -> list:
    """Photos, clips and songs in a trip's media folder that are no longer in its story."""
    photos = {export.file_name(m['id'], w).split('/')[-1] for m in moments if m['kind'] == 'photo' for w in export.WIDTHS}
    clips = {f"{m['id']}{ext}" for m in moments if m['kind'] == 'video' for ext in ('.mp4', '.webp')}
    return (export.stale(folder, photos) + export.stale(folder / export.SMALLER, photos)
            + export.stale(folder / export.VIDEOS, clips) + stale_songs(folder / MUSIC, music))


def stale_songs(folder: Path, music) -> list:
    """Songs in the trip's music folder other than the story's current one."""
    keep = {music['file'].split('/')[-1]} if music else set()
    return [p for p in folder.iterdir() if p.is_file() and p.name not in keep] if folder.is_dir() else []


def cover(folder: Path, moments: list) -> Path:
    """The post's cover: the story's first photo at 1280, or its first clip's cover when it has no photo."""
    photo = next((m for m in moments if m['kind'] == 'photo'), None)
    if photo:
        return folder / export.file_name(photo['id'], 1280)
    return folder / export.VIDEOS / f"{moments[0]['id']}.webp"
