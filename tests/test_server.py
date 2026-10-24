import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from studio import config, server, store
from tests.helpers import picture, save_photo


class Ranges(unittest.TestCase):
    def test_ranges(self):
        self.assertIsNone(server.byte_range(None, 100))
        self.assertEqual(server.byte_range('bytes=0-', 100), (0, 99))
        self.assertEqual(server.byte_range('bytes=10-19', 100), (10, 19))
        self.assertEqual(server.byte_range('bytes=90-500', 100), (90, 99))
        self.assertEqual(server.byte_range('bytes=-10', 100), (90, 99))
        with self.assertRaises(ValueError):
            server.byte_range('bytes=100-', 100)


class Requests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(tempfile.mkdtemp())
        cls.saved = config.TRIPS, config.CACHE, config.MUSIC
        config.TRIPS, config.CACHE, config.MUSIC = root / 'Trips', root / 'cache', root / 'music'
        save_photo(config.TRIPS / 'Trip' / 'originals' / 'IMG_1.HEIC', picture(1), 'HEIF')
        (root / 'secret.txt').write_text('private')
        cls.studio = server.Studio()
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), None)
        cls.port = cls.httpd.server_address[1]
        cls.httpd.RequestHandlerClass = server.make_handler(cls.studio, cls.port)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        config.TRIPS, config.CACHE, config.MUSIC = cls.saved

    def call(self, path, body=None, host=None, kind='application/json'):
        request = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', method='POST' if body is not None else 'GET',
                                         data=json.dumps(body).encode() if body is not None else None)
        request.add_header('Host', host or f'127.0.0.1:{self.port}')
        if body is not None:
            request.add_header('Content-Type', kind)
        try:
            with urllib.request.urlopen(request) as answer:
                return answer.status, answer.read()
        except urllib.error.HTTPError as error:
            with error:
                return error.code, error.read()

    def test_lists_trips(self):
        status, body = self.call('/api/trips')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['trips'], [{'name': 'Trip', 'ready': True}])

    def test_other_hosts_are_refused(self):
        self.assertEqual(self.call('/api/trips', host='evil.example')[0], 403)
        self.assertEqual(self.call('/api/trips', host=f'192.168.1.5:{self.port}')[0], 403)

    def test_changes_only_as_json(self):
        self.assertEqual(self.call('/api/refresh', {'trip': 'Trip'}, kind='text/plain')[0], 415)
        self.assertEqual(self.call('/api/refresh', [])[0], 400)

    def test_marking(self):
        self.call('/api/refresh', {'trip': 'Trip'})
        trip = self.studio.trip('Trip')
        for _ in range(50):
            if not trip.progress['running'] and trip.entries:
                break
            threading.Event().wait(0.1)
        self.assertEqual(self.call('/api/mark', {'trip': 'Trip', 'ids': ['img_1'], 'pick': 'yes'})[0], 200)
        self.assertEqual(trip.marks(), {'img_1': {'pick': 'yes'}})
        self.assertEqual(self.call('/api/mark', {'trip': 'Trip', 'ids': ['../x'], 'pick': 'yes'})[0], 400)
        self.assertEqual(self.call('/api/adjust', {'trip': 'Trip', 'id': 'img_1', 'exposure': 0.3, 'warmth': 0.1})[0], 200)
        self.assertEqual(self.call('/api/adjust', {'trip': 'Trip', 'id': 'img_1', 'exposure': 9})[0], 400)
        plain = self.call('/preview?trip=Trip&id=img_1&plain=1')
        shaped = self.call('/preview?trip=Trip&id=img_1')
        self.assertEqual((plain[0], shaped[0]), (200, 200))
        self.assertNotEqual(plain[1], shaped[1])

    def test_looks(self):
        self.assertEqual([l['id'] for l in json.loads(self.call('/api/looks')[1])['looks']], ['A', 'B', 'C', 'D'])
        self.call('/api/refresh', {'trip': 'Trip'})
        trip = self.studio.trip('Trip')
        for _ in range(50):
            if not trip.progress['running'] and trip.entries:
                break
            threading.Event().wait(0.1)
        status, body = self.call('/look?trip=Trip&id=img_1&look=C&for=portrait')
        self.assertEqual((status, body[:2]), (200, b'\xff\xd8'))
        self.assertEqual(self.call('/look?trip=Trip&id=img_1&look=../../x&for=portrait')[0], 404)
        self.assertEqual(self.call('/look?trip=Trip&id=img_1&look=C&for=../x')[0], 404)
        self.assertEqual(self.call('/api/look', {'trip': 'Trip', 'for': 'landscape', 'look': 'C'})[0], 200)
        self.assertEqual(self.call('/api/look', {'trip': 'Trip', 'for': 'landscape', 'look': 'nope'})[0], 400)
        self.assertEqual(self.call('/api/subject', {'trip': 'Trip', 'ids': ['img_1'], 'subject': 'portrait'})[0], 200)
        self.assertEqual(self.call('/api/subject', {'trip': 'Trip', 'ids': ['img_1'], 'subject': 'cat'})[0], 400)
        self.assertEqual(json.loads(self.call('/api/export-format', {'trip': 'Trip', 'format': 'jpeg'})[1]), {'format': 'jpeg'})
        self.assertEqual(self.call('/api/export-format', {'trip': 'Trip', 'format': '../x'})[0], 400)
        self.call('/api/export-format', {'trip': 'Trip', 'format': 'webp'})

    def test_hello_names_the_build(self):
        hello = json.loads(self.call('/api/hello')[1])
        self.assertEqual(hello, {'app': 'media-studio', 'build': server.build_id()})

    def test_paths_in_requests_lead_nowhere(self):
        self.assertEqual(self.call('/api/trip?trip=..')[0], 404)
        self.assertEqual(self.call('/api/trip?trip=../secret.txt')[0], 404)
        self.assertEqual(self.call('/thumb?trip=Trip&id=../../secret')[0], 404)
        self.assertEqual(self.call('/video?trip=Trip&id=..%5C..%5Csecret')[0], 404)

    def test_page_and_files(self):
        self.assertEqual(self.call('/')[0], 200)
        self.assertEqual(self.call('/app.js')[0], 200)
        self.assertEqual(self.call('/../main.py')[0], 404)


class Store(unittest.TestCase):
    def test_write_then_read(self):
        path = Path(tempfile.mkdtemp()) / 'a' / 'data.json'
        store.write_json(path, {'picks': ['img_1', '云南']})
        self.assertEqual(store.read_json(path), {'picks': ['img_1', '云南']})
        self.assertFalse(path.with_name('data.json.tmp').exists())

    def test_missing_or_broken_gives_the_default(self):
        folder = Path(tempfile.mkdtemp())
        (folder / 'bad.json').write_text('{not json')
        self.assertEqual(store.read_json(folder / 'bad.json', {}), {})
        self.assertIsNone(store.read_json(folder / 'none.json'))


if __name__ == '__main__':
    unittest.main()
