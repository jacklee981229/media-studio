"""The local web server behind the Studio's window. It answers only on 127.0.0.1, and only to its own pages."""
import hashlib
import json
import os
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ProcessPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import config, looks, pictures
from .trip import FULL, Trip, full_music, music, trips

def build_id() -> str:
    """A fingerprint of the running code. start.cmd compares it with the code on disk and replaces a copy left
    running from before an update, which would otherwise serve the new page with old answers."""
    digest = hashlib.sha1()
    for path in sorted([config.ROOT / 'main.py', *(config.ROOT / 'studio').glob('*.py')]):
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


STATIC = {'/': ('index.html', 'text/html; charset=utf-8'),
          '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
          '/app.css': ('app.css', 'text/css; charset=utf-8')}
# The window pings every 20 s; with no window open for this long and nothing running, the server stops itself.
IDLE_SECONDS = 10 * 60
CHUNK = 1024 * 1024


class Studio:
    """What the server keeps between requests: open trips and the worker processes."""

    def __init__(self):
        self.trips = {}
        self.lock = threading.Lock()
        self.pool = None
        self.quick_pool = None
        self.jobs = threading.Lock()
        self.previews = OrderedDict()
        self.last_ping = time.monotonic()

    def workers(self) -> ProcessPoolExecutor:
        """For long jobs: thumbnails and exports."""
        with self.lock:
            if self.pool is None:
                self.pool = ProcessPoolExecutor(max_workers=max(2, min(8, (os.cpu_count() or 4) - 2)))
            return self.pool

    def quick(self) -> ProcessPoolExecutor:
        """For what Jack is waiting to see (a photo opened, a look sample), so it never queues behind a long job."""
        with self.lock:
            if self.quick_pool is None:
                self.quick_pool = ProcessPoolExecutor(max_workers=2)
            return self.quick_pool

    def trip(self, name):
        """The open trip by folder name, or None. Names come only from the trips folder's own listing."""
        if not isinstance(name, str) or name not in {t['name'] for t in trips() if t['ready']}:
            return None
        with self.lock:
            if name not in self.trips:
                self.trips[name] = Trip(name)
            return self.trips[name]

    def refresh(self, trip: Trip) -> None:
        """Scan the trip and make missing thumbnails, in the background, unless that's already under way."""
        with self.jobs:
            if trip.progress['running']:
                return
            trip.progress = {'done': 0, 'total': 0, 'running': True}

        def work():
            try:
                trip.scan()
                trip.make_thumbs(self.workers())
            finally:
                trip.progress['running'] = False

        threading.Thread(target=work, daemon=True).start()

    def preview(self, trip: Trip, item_id: str, base, settings: tuple) -> bytes:
        """A photo's preview, the last few dozen kept in memory so stepping back and forth is instant."""
        key = (trip.name, item_id, base.stat().st_mtime_ns, settings)
        with self.lock:
            if key in self.previews:
                self.previews.move_to_end(key)
                return self.previews[key]
        body = pictures.preview_bytes(str(base), *settings)
        with self.lock:
            self.previews[key] = body
            while len(self.previews) > 48:
                self.previews.popitem(last=False)
        return body

    def export(self, trip: Trip) -> None:
        """Export the trip's kept photos in the background, unless an export is already under way."""
        with self.jobs:
            if trip.export_progress['running']:
                return
            trip.export_progress = {**trip.export_progress, 'running': True}
        threading.Thread(target=trip.export, args=(self.workers(),), daemon=True).start()

    def publish(self, trip: Trip) -> None:
        """Publish the trip's story in the background, unless that or an export is already under way."""
        with self.jobs:
            if trip.publish_progress['running'] or trip.export_progress['running']:
                return
            trip.publish_progress = {**trip.publish_progress, 'running': True}
        threading.Thread(target=trip.publish, args=(self.workers(),), daemon=True).start()

    def busy(self) -> bool:
        with self.lock:
            open_trips = list(self.trips.values())
        return any(t.progress['running'] or t.export_progress['running'] or t.publish_progress['running'] for t in open_trips)


def allowed_hosts(port: int) -> set:
    return {f'127.0.0.1:{port}', f'localhost:{port}'}


def byte_range(header, size: int):
    """(start, end) inclusive from a Range header, or None for the whole file. Raises ValueError when unsatisfiable."""
    match = re.fullmatch(r'bytes=(\d*)-(\d*)', header or '')
    if not match or (not match[1] and not match[2]):
        return None
    if match[1]:
        start = int(match[1])
        end = min(int(match[2]), size - 1) if match[2] else size - 1
    else:
        start, end = max(0, size - int(match[2])), size - 1
    if start > end or start >= size:
        raise ValueError('unsatisfiable range')
    return start, end


def make_handler(studio: Studio, port: int, stop=None):
    hosts = allowed_hosts(port)
    build = build_id()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        # ---- answers

        def send(self, status, body=b'', kind='application/json; charset=utf-8', headers=None):
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(body)

        def json(self, data, status=200):
            self.send(status, json.dumps(data, ensure_ascii=False).encode())

        def fail(self, status, message):
            self.json({'error': message}, status)

        def file(self, path, kind, cache='no-cache'):
            try:
                body = path.read_bytes()
            except OSError:
                return self.fail(404, 'Not here yet.')
            self.send(200, body, kind, {'Cache-Control': cache})

        # ---- checks every request passes

        def safe(self) -> bool:
            # Another website open in Chrome may send requests here; the Host and the JSON-only POSTs keep it out.
            if self.headers.get('Host') not in hosts:
                self.fail(403, 'Not allowed.')
                return False
            return True

        def query(self):
            url = urlparse(self.path)
            return url.path, {k: v[0] for k, v in parse_qs(url.query).items()}

        # ---- GET

        def do_GET(self):
            if not self.safe():
                return
            path, q = self.query()
            if path in STATIC:
                name, kind = STATIC[path]
                return self.file(config.WEB / name, kind)
            if path == '/api/hello':
                return self.json({'app': 'media-studio', 'build': build})
            if path == '/api/ping':
                studio.last_ping = time.monotonic()
                return self.json({'ok': True})
            if path == '/api/trips':
                return self.json({'trips': trips(), 'folder': str(config.TRIPS)})
            if path == '/api/looks':
                return self.json({'looks': looks.summary()})
            if path == '/api/music':
                return self.json({'songs': music(), 'folder': str(config.MUSIC)})
            if path == '/api/full-music':
                return self.json({'songs': full_music(), 'folder': str(config.MUSIC / FULL)})
            if path == '/music':
                # A song by its name in the music folder's own listing, never a path from the request.
                name = q.get('name')
                if q.get('full'):
                    known = name in [s['name'] for s in full_music()]
                    return self.video(config.MUSIC / FULL / name, 'audio/mpeg') if known else self.fail(404, 'No such song.')
                return self.video(config.MUSIC / name, 'audio/mpeg') if name in music() else self.fail(404, 'No such song.')
            trip = studio.trip(q.get('trip'))
            if trip is None:
                return self.fail(404, 'No such trip.')
            if path == '/api/trip':
                return self.json(trip.view())
            item_id = q.get('id')
            original = trip.path_of(item_id) if item_id else None
            if original is None:
                return self.fail(404, 'No such file.')
            if path == '/thumb':
                return self.file(trip.thumb_path(item_id), 'image/jpeg', 'max-age=3600')
            if path == '/preview':
                return self.preview(trip, item_id, original, q.get('plain') == '1')
            if path == '/look':
                return self.look(trip, item_id, original, q.get('look') or None, q.get('for'))
            if path == '/video':
                return self.video(original)
            self.fail(404, 'Not found.')

        do_HEAD = do_GET

        def preview(self, trip, item_id, original, plain):
            """The photo as it will come out (its look and adjustments), or as shot when `plain`."""
            if trip.entries[item_id]['kind'] != 'photo':
                return self.fail(404, 'Videos have no preview.')
            base = trip.base_path(item_id)
            try:
                if not base.exists():
                    studio.quick().submit(pictures.photo_base, str(original), str(base)).result()
                if plain:
                    return self.file(base, 'image/jpeg', 'max-age=3600')
                # Drawn right here, not in a worker: this process keeps the colour tables warm, so each slider move
                # costs about a tenth of a second instead of a worker's cold start.
                body = studio.preview(trip, item_id, base, trip.develop_settings(item_id))
            except Exception:
                return self.fail(500, "Couldn't open this photo.")
            self.send(200, body, 'image/jpeg', {'Cache-Control': 'max-age=3600'})

        def look(self, trip, item_id, original, look_id, kind):
            if trip.entries[item_id]['kind'] != 'photo' or (look_id and look_id not in looks.LOOKS) or kind not in looks.STRENGTH:
                return self.fail(404, 'No such look.')
            strength = looks.STRENGTH[kind]
            out = trip.look_path(item_id, look_id, strength)
            if not out.exists():
                try:
                    studio.quick().submit(pictures.photo_look, str(original), str(out), look_id, strength).result()
                except Exception:
                    return self.fail(500, "Couldn't open this photo.")
            self.file(out, 'image/jpeg', 'max-age=3600')

        def video(self, original, kind='video/mp4'):
            """The original video (or a song), in pieces as the player asks, so it can seek."""
            try:
                size = original.stat().st_size
            except OSError:
                return self.fail(404, 'This file is gone.')
            try:
                span = byte_range(self.headers.get('Range'), size)
            except ValueError:
                return self.send(416, headers={'Content-Range': f'bytes */{size}'})
            start, end = span or (0, size - 1)
            self.send_response(206 if span else 200)
            # Chrome plays an iPhone .MOV when it's offered as MP4: the two share one file structure. Songs of any
            # kind play when offered as audio; Chrome reads the actual format from the file.
            self.send_header('Content-Type', kind)
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Length', str(end - start + 1))
            if span:
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.end_headers()
            if self.command == 'HEAD':
                return
            try:
                with open(original, 'rb') as f:
                    f.seek(start)
                    left = end - start + 1
                    while left > 0:
                        chunk = f.read(min(CHUNK, left))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)
            except (ConnectionError, OSError):
                pass  # the player moved on and closed the connection

        # ---- POST: changes, JSON only

        def do_POST(self):
            if not self.safe():
                return
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                return self.fail(415, 'JSON only.')
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get('Content-Length') or 0), 65536)) or b'{}')
            except ValueError:
                return self.fail(400, 'Bad JSON.')
            if not isinstance(body, dict):
                return self.fail(400, 'Send a JSON object.')
            path, _ = self.query()
            if path == '/api/quit' and stop:
                self.json({'ok': True})
                threading.Thread(target=stop, daemon=True).start()
                return
            trip = studio.trip(body.get('trip'))
            if trip is None:
                return self.fail(404, 'No such trip.')
            if path == '/api/refresh':
                studio.refresh(trip)
                return self.json(trip.view())
            if path == '/api/look':
                try:
                    trip.set_look(body.get('for'), body.get('look'))
                except ValueError as error:
                    return self.fail(400, str(error))
                return self.json({'looks': trip.looks()})
            if path == '/api/subject':
                try:
                    trip.set_subject(body.get('ids'), body.get('subject'))
                except ValueError as error:
                    return self.fail(400, str(error))
                return self.json({'ok': True})
            if path == '/api/mark':
                try:
                    trip.mark(body.get('ids'), body.get('pick'))
                except ValueError as error:
                    return self.fail(400, str(error))
                return self.json({'ok': True})
            if path == '/api/clip':
                try:
                    trip.set_clip(body.get('id'), {k: body[k] for k in ('start', 'sound', 'music', 'music_start') if k in body})
                except ValueError as error:
                    return self.fail(400, str(error))
                return self.json({'clip': trip.clip_of(body['id'])})
            if path == '/api/story-text':
                try:
                    trip.set_story_text(body.get('which'), body.get('words'))
                except ValueError as error:
                    return self.fail(400, str(error))
                return self.json({'ok': True})
            if path == '/api/story-title':
                try:
                    trip.set_story_title(body.get('title'))
                except ValueError as error:
                    return self.fail(400, str(error))
                return self.json({'ok': True})
            if path == '/api/story-back':
                try:
                    trip.set_story_back(body.get('which'), body.get('id'))
                except ValueError as error:
                    return self.fail(400, str(error))
                return self.json({'ok': True})
            if path == '/api/story-song':
                try:
                    trip.set_story_song(body.get('song'))
                except ValueError as error:
                    return self.fail(400, str(error))
                return self.json({'ok': True})
            if path == '/api/story':
                try:
                    if body.get('remove_note'):
                        trip.remove_story_note(body.get('id'))
                    else:
                        trip.set_story(body.get('id'), body.get('chosen'), body.get('words'), body.get('joined'), body.get('place'),
                                       body.get('note'))
                except ValueError as error:
                    return self.fail(400, str(error))
                return self.json({'ok': True})
            if path == '/api/export-format':
                try:
                    trip.set_export_format(body.get('format'))
                except ValueError as error:
                    return self.fail(400, str(error))
                return self.json({'format': trip.export_format()})
            if path == '/api/publish':
                studio.publish(trip)
                return self.json(trip.view())
            if path == '/api/export':
                studio.export(trip)
                return self.json(trip.view())
            if path == '/api/open-export':
                # Only ever the trip's own export folder, opened in File Explorer.
                if trip.export_folder().is_dir():
                    os.startfile(trip.export_folder())
                return self.json({'ok': True})
            if path == '/api/adjust':
                try:
                    trip.adjust(body.get('id'), body.get('exposure', 0), body.get('warmth', 0))
                except ValueError as error:
                    return self.fail(400, str(error))
                return self.json({'ok': True})
            self.fail(404, 'Not found.')

    return Handler


def serve(port: int, on_ready=None) -> None:
    studio = Studio()
    server = ThreadingHTTPServer(('127.0.0.1', port), None)
    server.RequestHandlerClass = make_handler(studio, port, stop=server.shutdown)
    server.daemon_threads = True

    def watch_idle():
        while True:
            time.sleep(30)
            if time.monotonic() - studio.last_ping > IDLE_SECONDS and not studio.busy():
                server.shutdown()
                return

    threading.Thread(target=watch_idle, daemon=True).start()
    if on_ready:
        on_ready()
    try:
        server.serve_forever()
    finally:
        server.server_close()
        for pool in (studio.pool, studio.quick_pool):
            if pool:
                pool.shutdown(cancel_futures=True)
