"""One trip: its folder of originals, what each file is, and the thumbnails being made in the background.

The index (what the files say about themselves, plus fingerprints) lives in the cache and is rebuilt for any file
whose size or date changed. Nothing here ever writes inside originals.
"""
import hashlib
import threading
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

from . import config, export, looks, meta, pictures, publish, similar, source, store, subject, timeline

# Index format; bump it when what's stored per file changes, so old caches are rebuilt.
VERSION = 3
# Words under one photo in the story: a few paragraphs at most.
STORY_WORDS = 4000
STORY_PLACE = 40
STORY_TITLE = 120


def trips() -> list:
    """Trip folders under the trips folder, newest name first, with whether they hold an originals folder."""
    if not config.TRIPS.is_dir():
        return []
    found = [p for p in config.TRIPS.iterdir() if p.is_dir() and not p.name.startswith('.')]
    return [{'name': p.name, 'ready': (p / 'originals').is_dir()} for p in sorted(found, key=lambda p: p.name, reverse=True)]


def music() -> list:
    """The songs in Jack's music folder, by name. The folder is made the first time, so he can find it."""
    config.MUSIC.mkdir(parents=True, exist_ok=True)
    return sorted((p.name for p in config.MUSIC.iterdir() if p.is_file() and p.suffix.lower() in config.MUSIC_TYPES),
                  key=str.lower)


# Full songs, one of which a whole story can play under it: the music folder's 完整版 (the 8 s pieces beside it are
# for single clips). A songs.json there gives each one's credit: title, artist and the address it came from.
FULL = '完整版'


def full_music() -> list:
    """The full songs, by name, each with its credit."""
    folder = config.MUSIC / FULL
    if not folder.is_dir():
        return []
    credits = store.read_json(folder / 'songs.json', {}) or {}
    return [{'name': p.name, **credits.get(p.name, {})} for p in sorted(folder.iterdir(), key=lambda p: p.name.lower())
            if p.is_file() and p.suffix.lower() in config.MUSIC_TYPES]


def media_files(originals: Path) -> list:
    """Photos and videos under originals, as paths relative to it, skipping hidden files."""
    found = []
    for path in originals.rglob('*'):
        if path.is_file() and not path.name.startswith('.') and path.suffix.lower() in config.PHOTO_TYPES | config.VIDEO_TYPES:
            found.append(path.relative_to(originals))
    return sorted(found, key=lambda p: str(p).lower())


def assign_ids(paths: list) -> dict:
    """Each file's id: its name without the extension, in small letters (img_6057), the same every time so later
    exports and posts can rely on it. A Live Photo's video shares its photo's name and is left out (None).
    Two other files with one name get the extension added (img_1234-jpg)."""
    by_stem = {}
    for path in paths:
        by_stem.setdefault(str(path.with_suffix('')).lower().replace('\\', '/'), []).append(path)
    ids = {}
    for stem, same in by_stem.items():
        base = stem.replace('/', '~')
        photos = [p for p in same if p.suffix.lower() in config.PHOTO_TYPES]
        videos = [p for p in same if p.suffix.lower() in config.VIDEO_TYPES]
        if len(photos) == 1 and len(videos) == 1:
            ids[photos[0]] = base
            ids[videos[0]] = None
        elif len(same) == 1:
            ids[same[0]] = base
        else:
            for p in same:
                ids[p] = f'{base}-{p.suffix.lower().lstrip(".")}'
    return ids


class Trip:
    def __init__(self, name: str):
        self.name = name
        self.folder = config.TRIPS / name
        self.originals = self.folder / 'originals'
        key = hashlib.sha1(str(self.folder).lower().encode()).hexdigest()[:12]
        self.cache = config.CACHE / 'trips' / key
        # Re-entrant: _update holds it while reading studio.json through _choices. On Windows a file being read
        # can't be replaced, so reads and writes of studio.json take turns.
        self.lock = threading.RLock()
        self.entries = {}  # id -> stored facts about one file
        self.progress = {'done': 0, 'total': 0, 'running': False}
        self.export_progress = {'done': 0, 'total': 0, 'running': False, 'failed': 0}
        self.publish_progress = {'done': 0, 'total': 0, 'running': False, 'failed': 0, 'address': None, 'error': None}

    # ---- the index

    def scan(self) -> None:
        """Read what's new or changed since the last scan; keep the rest from the cache."""
        old = store.read_json(self.cache / 'index.json', {})
        old = old.get('files', {}) if old.get('version') == VERSION else {}
        paths = media_files(self.originals)
        entries = {}
        for path, item_id in assign_ids(paths).items():
            if item_id is None:
                continue
            full = self.originals / path
            stat = full.stat()
            kind = 'photo' if path.suffix.lower() in config.PHOTO_TYPES else 'video'
            stamp = [stat.st_size, int(stat.st_mtime)]
            cached = old.get(item_id)
            # A file that failed before is read again: the failure may have been passing (a file still arriving).
            if cached and cached['file'] == str(path) and cached['stamp'] == stamp and 'error' not in cached['meta']:
                entries[item_id] = cached
                continue
            try:
                facts = meta.read_photo(full) if kind == 'photo' else meta.read_video(full)
            except Exception as error:  # a file still arriving, or broken: list it, say why, try again next scan
                facts = {'error': str(error)[:200]}
            entries[item_id] = {'file': str(path), 'kind': kind, 'stamp': stamp, 'meta': facts, 'print': None, 'colour': None}
        with self.lock:
            self.entries = entries
        self._save()

    def _save(self) -> None:
        with self.lock:
            store.write_json(self.cache / 'index.json', {'version': VERSION, 'files': self.entries})

    # ---- Jack's choices, kept in the trip folder (studio.json) so they're backed up with the originals

    def _choices(self) -> dict:
        with self.lock:
            data = store.read_json(self.folder / 'studio.json', {})
        return data if isinstance(data, dict) else {}

    def marks(self) -> dict:
        return self._choices().get('marks', {})

    def looks(self) -> dict:
        """The trip's look for portraits and for landscapes ('A'–'D', or None for as shot)."""
        chosen = self._choices().get('looks', {})
        return {s: chosen.get(s) for s in (subject.PORTRAIT, subject.LANDSCAPE)}

    def set_look(self, kind: str, look_id) -> None:
        if kind not in (subject.PORTRAIT, subject.LANDSCAPE):
            raise ValueError('portrait or landscape')
        if look_id is not None and look_id not in looks.LOOKS:
            raise ValueError('unknown look')
        self._update(lambda data: data.setdefault('looks', {}).__setitem__(kind, look_id))

    def export_format(self) -> str:
        """'webp' for the website (the default) or 'jpeg' for sharing and keeping."""
        chosen = self._choices().get('export_format')
        return chosen if chosen in export.FORMATS else export.FORMATS[0]

    def set_export_format(self, fmt: str) -> None:
        if fmt not in export.FORMATS:
            raise ValueError('webp or jpeg')
        self._update(lambda data: data.__setitem__('export_format', fmt))

    def set_subject(self, ids: list, kind) -> None:
        """Jack's own call on portrait or landscape, over the guess; None goes back to the guess."""
        self._check_ids(ids)
        if kind not in (subject.PORTRAIT, subject.LANDSCAPE, None):
            raise ValueError('portrait, landscape or null')

        def change(data):
            subjects = data.setdefault('subjects', {})
            for item_id in ids:
                if kind:
                    subjects[item_id] = kind
                else:
                    subjects.pop(item_id, None)
        self._update(change)

    def _update(self, change) -> None:
        with self.lock:
            data = self._choices()
            change(data)
            store.write_json(self.folder / 'studio.json', {**data, 'version': 1})

    def _check_ids(self, ids) -> None:
        if not isinstance(ids, list) or not ids or any(not isinstance(i, str) or i not in self.entries for i in ids):
            raise ValueError('unknown file')

    def mark(self, ids: list, pick) -> None:
        """Keep ('yes'), drop ('no') or clear (None) the given files."""
        self._check_ids(ids)
        if pick not in ('yes', 'no', None):
            raise ValueError('pick is yes, no or null')

        def change(data):
            marks = data.setdefault('marks', {})
            for item_id in ids:
                # Cleared files leave the file, so it stays small and shows only real choices.
                if pick:
                    marks[item_id] = {'pick': pick}
                else:
                    marks.pop(item_id, None)
        self._update(change)

    def adjustments(self) -> dict:
        return self._choices().get('adjust', {})

    def adjust(self, item_id: str, exposure, warmth) -> None:
        """One photo's own brightness (exposure, -2 to 2 stops) and warmth (-1 to 1), over its look."""
        self._check_ids([item_id])
        for value, top in ((exposure, 2), (warmth, 1)):
            if type(value) not in (int, float) or not -top <= value <= top:
                raise ValueError('exposure is -2 to 2, warmth -1 to 1')

        def change(data):
            every = data.setdefault('adjust', {})
            if exposure or warmth:
                every[item_id] = {'exposure': round(exposure, 2), 'warmth': round(warmth, 2)}
            else:
                every.pop(item_id, None)
        self._update(change)

    def clip_of(self, item_id: str, choices=None) -> dict:
        """A video's clip: where it starts, how long (about 7 s, or the whole video if shorter) and its sound.
        Without Jack's own start, the clip is the video's middle."""
        duration = self.entries[item_id]['meta'].get('duration') or 0
        length = min(export.CLIP_SECONDS, duration)
        chosen = (choices or self._choices()).get('clips', {}).get(item_id, {})
        start = chosen.get('start', max(0.0, (duration - length) / 2))
        return {'start': round(min(start, max(0.0, duration - length)), 2), 'length': round(length, 2),
                'sound': chosen.get('sound', 'mute'), 'music': chosen.get('music'),
                'music_start': chosen.get('music_start', 0.0), 'chosen': 'start' in chosen}

    def set_clip(self, item_id: str, changes: dict) -> None:
        """Change a video's clip start, sound, song or where in the song to begin."""
        self._check_ids([item_id])
        if self.entries[item_id]['kind'] != 'video':
            raise ValueError('only videos have clips')
        duration = self.entries[item_id]['meta'].get('duration') or 0
        number = lambda v: type(v) in (int, float) and v >= 0
        if 'start' in changes and not (number(changes['start']) and changes['start'] <= duration):
            raise ValueError('start is within the video')
        if 'sound' in changes and changes['sound'] not in export.SOUNDS:
            raise ValueError('sound is mute, original or music')
        if 'music' in changes and changes['music'] is not None and changes['music'] not in music():
            raise ValueError('no such song in the music folder')
        if 'music_start' in changes and not number(changes['music_start']):
            raise ValueError('music_start is seconds into the song')

        def change(data):
            clip = data.setdefault('clips', {}).setdefault(item_id, {})
            clip.update({k: changes[k] for k in ('start', 'sound', 'music', 'music_start') if k in changes})
        self._update(change)

    def set_story(self, item_id: str, chosen=None, words=None, joined=None, place=None, note=None) -> None:
        """Put a kept photo into the trip's story or take it out, set the words written under it and the place it was
        taken, and/or join it to the one before it in the story: joined photos share that one's words and place and show
        one after another. A note is words on their own after it (after its group), shown on the site without a photo.
        Words stay when a photo is taken out, so putting it back brings them back."""
        self._check_ids([item_id])
        if self.entries[item_id]['kind'] == 'video' and self.clip_of(item_id)['length'] <= 0:
            raise ValueError('this video has no clip to show')
        if chosen is not None and not isinstance(chosen, bool):
            raise ValueError('chosen is true or false')
        if words is not None and (not isinstance(words, str) or len(words) > STORY_WORDS):
            raise ValueError(f'words are text, at most {STORY_WORDS} characters')
        if joined is not None and not isinstance(joined, bool):
            raise ValueError('joined is true or false')
        if place is not None and (not isinstance(place, str) or len(place) > STORY_PLACE):
            raise ValueError(f'the place is text, at most {STORY_PLACE} characters')
        if note is not None and (not isinstance(note, str) or len(note) > STORY_WORDS):
            raise ValueError(f'the note is text, at most {STORY_WORDS} characters')

        def change(data):
            story = data.setdefault('story', {})
            ids = story.setdefault('ids', [])
            if chosen and item_id not in ids:
                ids.append(item_id)
            elif chosen is False and item_id in ids:
                ids.remove(item_id)
            if words is not None:
                texts = story.setdefault('words', {})
                if words.strip():
                    texts[item_id] = words
                else:
                    texts.pop(item_id, None)
            if joined is not None:
                together = story.setdefault('joined', [])
                if joined and item_id not in together:
                    together.append(item_id)
                elif not joined and item_id in together:
                    together.remove(item_id)
            if place is not None:
                places = story.setdefault('places', {})
                if place.strip():
                    places[item_id] = place.strip()
                else:
                    places.pop(item_id, None)
            if note is not None:
                # Kept even when empty: an empty box Jack added stays open until he removes it (note=None never
                # reaches here; removing sends remove_note).
                story.setdefault('notes', {})[item_id] = note
        self._update(change)

    def remove_story_note(self, item_id: str) -> None:
        """Take away the box of words after a photo."""
        self._check_ids([item_id])
        self._update(lambda data: data.setdefault('story', {}).setdefault('notes', {}).pop(item_id, None))

    def set_story_title(self, title) -> None:
        """The post's title on Jack's Space, written into its index.md when the story is published."""
        if not isinstance(title, str) or not title.strip() or len(title) > STORY_TITLE:
            raise ValueError(f'the title is text, 1 to {STORY_TITLE} characters')
        self._update(lambda data: data.setdefault('story', {}).__setitem__('title', title.strip()))

    def story_title(self, choices=None) -> str:
        """Jack's title for the post, else the one its index.md has now, else one from the trip's name."""
        choices = choices if choices is not None else self._choices()
        post = config.SITE / 'src' / 'content' / 'posts' / publish.address(self.name)
        return choices.get('story', {}).get('title') or publish.read_title(post) or publish.title(self.name)

    def set_story_text(self, which: str, words) -> None:
        """The story's opening ('intro') or closing ('outro') words, written apart from any photo; empty is fine."""
        if which not in ('intro', 'outro'):
            raise ValueError('intro or outro')
        if not isinstance(words, str) or len(words) > STORY_WORDS:
            raise ValueError(f'words are text, at most {STORY_WORDS} characters')
        self._update(lambda data: data.setdefault('story', {}).__setitem__(which, words))

    def set_story_back(self, which: str, item_id) -> None:
        """The photo behind the story's opening ('intro') or closing ('outro') words, or None for the default: the
        story's first photo for the opening, its last for the closing."""
        if which not in ('intro', 'outro'):
            raise ValueError('intro or outro')
        if item_id is not None:
            self._check_ids([item_id])
        self._update(lambda data: data.setdefault('story', {}).__setitem__(f'{which}_photo', item_id))

    def set_story_song(self, name) -> None:
        """The full song the whole story plays under it, or None for a silent story."""
        if name is not None and name not in [s['name'] for s in full_music()]:
            raise ValueError('no such song in the full songs folder')
        self._update(lambda data: data.setdefault('story', {}).__setitem__('song', name))

    def subject_of(self, item_id: str):
        """Portrait or landscape for one file: Jack's own call if he made one, else the guess."""
        choices = self._choices()
        if item_id in choices.get('subjects', {}):
            return choices['subjects'][item_id]
        entry = self.entries[item_id]
        own = source.own_camera([e['meta'] for e in self.entries.values()])
        src = source.classify(entry['meta'], entry['kind'], own)[0]
        return subject.classify(entry['meta'], entry['kind'], src)[0]

    def develop_settings(self, item_id: str) -> tuple:
        """(look, strength, exposure, warmth): everything that decides how a photo comes out."""
        kind = self.subject_of(item_id) or subject.LANDSCAPE
        own = self.adjustments().get(item_id, {})
        return self.looks()[kind], looks.STRENGTH[kind], own.get('exposure', 0), own.get('warmth', 0)

    def base_path(self, item_id: str) -> Path:
        return self.cache / 'base' / f'{item_id}.jpg'

    def path_of(self, item_id: str):
        entry = self.entries.get(item_id)
        return self.originals / entry['file'] if entry else None

    def thumb_path(self, item_id: str) -> Path:
        return self.cache / 'thumbs' / f'{item_id}.jpg'

    def look_path(self, item_id: str, look_id, strength: float) -> Path:
        return self.cache / 'looks' / f'{look_id or "none"}-{round(strength * 100)}' / f'{item_id}.jpg'

    # ---- thumbnails, in worker processes

    def make_thumbs(self, pool: ProcessPoolExecutor) -> None:
        todo = [i for i, e in self.entries.items()
                if 'error' not in e['meta'] and (e['print'] is None or not self.thumb_path(i).exists())]
        self.progress = {'done': 0, 'total': len(todo), 'running': bool(todo)}
        if not todo:
            return
        jobs = {}
        for item_id in todo:
            entry = self.entries[item_id]
            src, out = str(self.path_of(item_id)), str(self.thumb_path(item_id))
            if entry['kind'] == 'photo':
                jobs[pool.submit(pictures.photo_thumb, src, out)] = item_id
            else:
                facts = entry['meta']
                at = min(1.0, facts.get('duration', 0) / 2)
                jobs[pool.submit(pictures.video_thumb, src, out, at, facts.get('hdr', False))] = item_id
        for future, item_id in jobs.items():
            try:
                mark, colour = future.result()
                with self.lock:
                    self.entries[item_id]['print'] = format(mark, '032x')
                    self.entries[item_id]['colour'] = colour
            except Exception as error:
                with self.lock:
                    self.entries[item_id]['meta'] = {**self.entries[item_id]['meta'], 'error': str(error)[:200]}
            self.progress['done'] += 1
        self.progress['running'] = False
        self._save()

    # ---- export, in worker processes

    def export_folder(self) -> Path:
        return self.folder / 'export'

    def cube_file(self) -> tuple:
        """(folder, file name) of the videos' look as a .cube (the landscape look), or (folder, None) for none."""
        look_id = self.looks()[subject.LANDSCAPE]
        folder = self.cache / 'cubes'
        if not look_id:
            return folder, None
        strength = looks.STRENGTH[subject.LANDSCAPE]
        name = f'look-{look_id}-{round(strength * 100)}.cube'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(looks.cube(look_id, strength), encoding='ascii')
        return folder, name

    def _clip_job(self, pool: ProcessPoolExecutor, item: dict, folder: Path, name: str, cube_dir: Path, cube_name,
                  silent=False):
        """Make one kept video's clip, with its chosen sound (or none), in a worker process; returns the future."""
        clip = {**item['clip'], 'sound': 'mute'} if silent else item['clip']
        song = config.MUSIC / clip['music'] if clip['sound'] == 'music' and clip['music'] else None
        # A song taken out of the music folder since it was chosen: the clip goes out silent, not broken.
        song = str(song) if song and song.is_file() else None
        sound = clip['sound'] if clip['sound'] != 'music' or song else 'mute'
        return pool.submit(export.export_video, str(config.FFMPEG), str(self.path_of(item['id'])), str(folder), name,
                           clip['start'], clip['length'], item['hdr'], str(cube_dir), cube_name, sound, song, clip['music_start'])

    def export(self, pool: ProcessPoolExecutor) -> None:
        """Write every kept photo and video clip to the export folder and list them in media.json, in timeline
        order. As JPEG, the photos go to their own folder and media.json keeps the website's photos as they were."""
        items = [i for i in self.view()['items'] if i['pick'] == 'yes' and not i['error']]
        photos_kept = [i for i in items if i['kind'] == 'photo']
        videos_kept = [i for i in items if i['kind'] == 'video']
        self.export_progress = {'done': 0, 'total': len(items), 'running': True, 'failed': 0}
        jpeg = self.export_format() == 'jpeg'
        photos = self.export_folder() / (export.JPEG_FOLDER if jpeg else export.PHOTOS)
        videos = self.export_folder() / export.VIDEOS
        named = {**export.names(photos_kept), **export.names(videos_kept)}
        try:
            jobs = []
            for item in photos_kept:
                facts = self.entries[item['id']]['meta']
                jobs.append((item, pool.submit(export.export_jpeg if jpeg else export.export_photo, str(self.path_of(item['id'])),
                                               str(photos), named[item['id']], self.develop_settings(item['id']),
                                               facts.get('taken'), facts.get('offset'))))
            cube_dir, cube_name = self.cube_file()
            for item in videos_kept:
                jobs.append((item, self._clip_job(pool, item, videos, named[item['id']], cube_dir, cube_name)))
            listed = {'photo': [], 'video': []}
            before = store.read_json(self.export_folder() / 'media.json', {}) or {}
            last = {e['id']: e for key in ('photos', 'videos') for e in before.get(key, [])}
            for item, future in jobs:
                try:
                    written = future.result()
                    entry = {'id': item['id'], 'taken': item['when'], **written}
                    if item['kind'] == 'photo':
                        entry['subject'] = item['subject']
                    listed[item['kind']].append(entry)
                except Exception:
                    self.export_progress['failed'] += 1
                    old = last.get(item['id'])
                    # Its last good export stays, unless renumbering has handed its files to another one.
                    name = named[item['id']]
                    same = {'files': export.photo_files(name)} if item['kind'] == 'photo' else export.video_files(name)
                    if old and all(old.get(k) == v for k, v in same.items()):
                        listed[item['kind']].append(old)
                self.export_progress['done'] += 1
            if jpeg:
                listed['photo'] = before.get('photos', [])
                keep = {export.jpeg_name(named[i['id']]) for i in photos_kept}
            else:
                keep = {Path(f).name for entry in listed['photo'] for f in entry['files'].values()}
            keep |= {Path(f).name for entry in listed['video'] for f in (entry['file'], entry['poster'])}
            for old in export.stale(photos, keep) + export.stale(photos / export.SMALLER, keep) + export.stale(videos, keep):
                old.unlink()
            store.write_json(self.export_folder() / 'media.json', {
                'version': 1, 'trip': self.name, 'sizes': list(export.WIDTHS),
                'photos': listed['photo'], 'videos': listed['video']})
        finally:
            self.export_progress['running'] = False

    # ---- publishing the story to Jack's Space

    def publish(self, pool: ProcessPoolExecutor) -> None:
        """Put the story's photos into the media repo and its post into Jack's Space (publish.py). Nothing is
        written to the site unless every photo made it, so the site never lists a photo the media repo lacks."""
        items = [i for i in self.view()['items'] if i['story'] and i['pick'] == 'yes' and not i['error'] and (i['kind'] == 'photo' or i['clip'])]
        self.publish_progress = {'done': 0, 'total': len(items), 'running': True, 'failed': 0, 'address': None, 'error': None}
        try:
            folder = publish.address(self.name)
            posts = config.SITE / 'src' / 'content' / 'posts'
            if not items:
                raise ValueError('故事里还没有照片')
            if not posts.is_dir() or not config.MEDIA.is_dir():
                raise ValueError(f"找不到 Jack's Space（{config.SITE}）或照片仓库（{config.MEDIA}）")
            media = config.MEDIA / folder
            cube_dir, cube_name = self.cube_file()
            jobs = []
            for item in items:
                facts = self.entries[item['id']]['meta']
                if item['kind'] == 'video':
                    # In a story every clip is silent, like a moving photo: the story has one song of its own.
                    jobs.append((item, self._clip_job(pool, item, media / export.VIDEOS, item['id'], cube_dir, cube_name,
                                                      silent=True)))
                    continue
                jobs.append((item, pool.submit(export.export_photo, str(self.path_of(item['id'])), str(media), item['id'],
                                               self.develop_settings(item['id']), facts.get('taken'), facts.get('offset'))))
            moments, why = [], None
            for item, future in jobs:
                try:
                    written = future.result()
                    # A photo joined to the one before shares its words; the first in the story can't join anything.
                    joined = item['joined'] and bool(moments)
                    moment = {'id': item['id'], 'kind': item['kind'], 'width': written['width'], 'height': written['height'],
                              'taken': item['when'], 'words': '' if joined else item['words']}
                    if joined:
                        moment['joined'] = True
                    elif item['place']:
                        moment['place'] = item['place']
                    if item['note'] is not None and item['note'].strip():
                        moment['after'] = item['note']
                    if item['kind'] == 'video':
                        moment.update(seconds=written['seconds'])
                    moments.append(moment)
                except Exception as error:
                    self.publish_progress['failed'] += 1
                    why = why or f"{item['file']}：{error}"
                self.publish_progress['done'] += 1
            if self.publish_progress['failed']:
                raise ValueError(f"{self.publish_progress['failed']} 张照片没做出来（{why}），网站没有改")
            song = next((s for s in full_music() if s['name'] == self._choices().get('story', {}).get('song')), None)
            music = publish.song(config.MUSIC / FULL / song['name'], media, song) if song else None
            for old in publish.stale(media, moments, music):
                old.unlink()
            told = self._choices().get('story', {})
            # A background photo left out of the story since it was picked falls back to the default.
            shown = {m['id'] for m in moments}
            backs = {k: told.get(f'{k}_photo') if told.get(f'{k}_photo') in shown else None for k in ('intro', 'outro')}
            publish.write_post(posts / folder, self.story_title(), folder, moments, publish.cover(media, moments), datetime.now(),
                               music, told.get('intro', ''), told.get('outro', ''), backs['intro'], backs['outro'])
            self.publish_progress['address'] = folder
        except Exception as error:
            self.publish_progress['error'] = str(error)
        finally:
            self.publish_progress['running'] = False

    # ---- what the screen shows

    def view(self) -> dict:
        """Every file with its source, time and stack, in timeline order: files with a time first, by time; then
        the rest by name."""
        with self.lock:
            entries = {i: dict(e) for i, e in self.entries.items()}
        own = source.own_camera([e['meta'] for e in entries.values()])
        choices = self._choices()
        marks = choices.get('marks', {})
        chosen = choices.get('subjects', {})
        adjust = choices.get('adjust', {})
        story = choices.get('story', {})
        in_story = set(story.get('ids', []))
        words = story.get('words', {})
        joined = set(story.get('joined', []))
        places = story.get('places', {})
        notes = story.get('notes', {})
        items = []
        for item_id, entry in entries.items():
            facts = entry['meta']
            src, reason = source.classify(facts, entry['kind'], own) if 'error' not in facts else (source.RECEIVED, '读不了这个文件')
            when = timeline.taken(facts)
            kind_of, why = subject.classify(facts, entry['kind'], src)
            if item_id in chosen and kind_of:
                kind_of, why = chosen[item_id], '你改的'
            items.append({
                'subject': kind_of,
                'subject_reason': why,
                'id': item_id,
                'kind': entry['kind'],
                'file': Path(entry['file']).name,
                'source': src,
                'reason': reason,
                'when': when.isoformat() if when else None,
                'day': when.strftime('%Y-%m-%d') if when else None,
                'time': when.timestamp() if when else None,
                'width': facts.get('width'),
                'height': facts.get('height'),
                'duration': facts.get('duration'),
                'hdr': facts.get('hdr', False),
                'camera': ' '.join(c for c in (facts.get('make'), facts.get('model')) if c) or None,
                'gps': bool(facts.get('gps')),
                'error': facts.get('error'),
                'print': int(entry['print'], 16) if entry.get('print') else None,
                'colour': entry.get('colour'),
                'faces': None if facts.get('faces') is None else sum(w >= subject.FACE_WIDTH for w in facts['faces']),
                'thumb': self.thumb_path(item_id).exists(),
                'pick': marks.get(item_id, {}).get('pick'),
                'adjust': adjust.get(item_id, {'exposure': 0, 'warmth': 0}),
                'clip': self.clip_of(item_id, choices) if entry['kind'] == 'video' and 'error' not in facts else None,
                'story': item_id in in_story,
                'words': words.get(item_id, ''),
                'joined': item_id in joined,
                'place': places.get(item_id, ''),
                'note': notes.get(item_id),
            })
        items.sort(key=lambda i: (i['time'] is None, i['time'] or 0, i['file'].lower()))
        stacks = similar.groups(items)
        stack_of = {item_id: n for n, ids in enumerate(stacks) for item_id in ids}
        for item in items:
            item['stack'] = stack_of.get(item['id'])
            del item['print'], item['colour'], item['time'], item['faces']
        days = sorted({i['day'] for i in items if i['day']})
        return {
            'name': self.name,
            'own': ' '.join(own) if own else None,
            'looks': self.looks(),
            'items': items,
            'stacks': len(stacks),
            'days': [{'day': d, 'label': timeline.day_label(d)} for d in days],
            'progress': dict(self.progress),
            'publish': dict(self.publish_progress),
            'story_song': choices.get('story', {}).get('song'),
            'story_intro': choices.get('story', {}).get('intro', ''),
            'story_outro': choices.get('story', {}).get('outro', ''),
            'story_intro_photo': choices.get('story', {}).get('intro_photo'),
            'story_title': self.story_title(choices),
            'story_outro_photo': choices.get('story', {}).get('outro_photo'),
            'export': {**self.export_progress, 'folder': str(self.export_folder()), 'format': self.export_format(),
                       'ready': (self.export_folder() / 'media.json').exists()},
        }
