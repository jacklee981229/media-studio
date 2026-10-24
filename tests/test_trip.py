import hashlib
import os
import tempfile
import unittest
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image

from studio import config, store, trip
from tests.helpers import face_xmp, hdr_clip, picture, save_photo

PHONE = {'make': 'Apple', 'model': 'iPhone 14 Pro Max', 'offset': '+08:00'}


def fingerprint_folder(folder: Path) -> dict:
    return {str(p.relative_to(folder)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in sorted(folder.rglob('*')) if p.is_file()}


class Ids(unittest.TestCase):
    def test_names_become_ids(self):
        ids = trip.assign_ids([Path('IMG_6057.HEIC'), Path('a1b2.jpg')])
        self.assertEqual(ids, {Path('IMG_6057.HEIC'): 'img_6057', Path('a1b2.jpg'): 'a1b2'})

    def test_live_photo_video_is_left_out(self):
        ids = trip.assign_ids([Path('IMG_1.HEIC'), Path('IMG_1.MOV')])
        self.assertEqual(ids, {Path('IMG_1.HEIC'): 'img_1', Path('IMG_1.MOV'): None})

    def test_same_name_twice_gets_the_extension(self):
        ids = trip.assign_ids([Path('IMG_2.HEIC'), Path('IMG_2.JPG'), Path('IMG_2.PNG')])
        self.assertEqual(sorted(ids.values()), ['img_2-heic', 'img_2-jpg', 'img_2-png'])

    def test_subfolders_keep_ids_apart(self):
        ids = trip.assign_ids([Path('a/IMG_3.HEIC'), Path('b/IMG_3.HEIC')])
        self.assertEqual(sorted(ids.values()), ['a~img_3', 'b~img_3'])


class WholeTrip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp())
        cls.saved = config.TRIPS, config.CACHE, config.MUSIC
        config.TRIPS, config.CACHE, config.MUSIC = cls.root / 'Trips', cls.root / 'cache', cls.root / 'music'
        o = config.TRIPS / '2026-10 Test' / 'originals'
        save_photo(o / 'IMG_0001.HEIC', picture(1), 'HEIF', taken='2026:10:14 10:00:00', gps=(25.0, 102.0), **PHONE)
        save_photo(o / 'IMG_0002.HEIC', picture(1).rotate(1), 'HEIF', taken='2026:10:14 10:00:05', **PHONE)
        save_photo(o / 'IMG_0003.HEIC', picture(9), 'HEIF', taken='2026:10:15 08:00:00', **PHONE)
        save_photo(o / 'IMG_0004.HEIC', picture(12), 'HEIF', xmp=face_xmp(0.05), taken='2026:10:15 09:00:00', **PHONE)
        save_photo(o / '9916ba93-f41c.jpg', picture(5).resize((1280, 960)), 'JPEG')
        save_photo(o / 'canon.jpg', picture(6), 'JPEG', make='Canon', model='EOS R7', taken='2026:10:14 11:00:00')
        hdr_clip(o / 'IMG_0005.MOV')
        cls.before = fingerprint_folder(o)
        cls.trip = trip.Trip('2026-10 Test')
        cls.trip.scan()
        with ProcessPoolExecutor(max_workers=2) as pool:
            cls.trip.make_thumbs(pool)
        cls.view = cls.trip.view()
        cls.by_id = {i['id']: i for i in cls.view['items']}

    @classmethod
    def tearDownClass(cls):
        config.TRIPS, config.CACHE, config.MUSIC = cls.saved

    def test_originals_are_untouched(self):
        self.assertEqual(fingerprint_folder(self.trip.originals), self.before)

    def test_only_the_choices_and_the_export_are_written_beside_the_originals(self):
        self.assertLessEqual({p.name for p in self.trip.folder.iterdir()}, {'originals', 'studio.json', 'export'})

    def test_export(self):
        self.trip.mark(['img_0001', 'img_0004', 'canon', 'img_0005'], 'yes')
        self.trip.adjust('img_0004', 0.4, 0.2)
        with ProcessPoolExecutor(max_workers=2) as pool:
            self.trip.export(pool)
            first = {str(p.relative_to(self.trip.export_folder() / 'photos')).replace(chr(92), '/'): p.read_bytes() for p in (self.trip.export_folder() / 'photos').rglob('*') if p.is_file()}
            listed = store.read_json(self.trip.export_folder() / 'media.json')
            # Only kept photos, in timeline order; the kept video as a clip with its cover.
            self.assertEqual([p['id'] for p in listed['photos']], ['img_0001', 'canon', 'img_0004'])
            self.assertEqual((listed['videos'][0]['id'], listed['videos'][0]['file']), ('img_0005', 'videos/001.mp4'))
            self.assertTrue((self.trip.export_folder() / listed['videos'][0]['poster']).exists())
            # Named by trip, capture date and time, then the width.
            self.assertEqual(sorted(first), sorted([f'{n}.webp' for n in ('001', '002', '003')] +
                                                   [f'smaller/{n}_{w}.webp' for n in ('001', '002', '003') for w in (640, 1280)]))
            self.assertEqual(listed['photos'][1]['files'], {'640': 'photos/smaller/002_640.webp', '1280': 'photos/smaller/002_1280.webp', '2048': 'photos/002.webp'})
            entry = listed['photos'][0]
            self.assertEqual(entry['taken'], '2026-10-14T10:00:00+08:00')
            self.assertEqual((entry['width'], entry['height']), (400, 300))
            with Image.open(self.trip.export_folder() / entry['files']['640']) as im:
                exif = im.getexif()
                self.assertEqual(exif.get_ifd(0x8769).get(0x9003), '2026:10:14 10:00:00')
                self.assertEqual(dict(exif.get_ifd(0x8825)), {})
                self.assertNotIn(0x0110, exif)
            # The same choices give the same files; a photo no longer kept leaves the export.
            self.trip.export(pool)
            again = {str(p.relative_to(self.trip.export_folder() / 'photos')).replace(chr(92), '/'): p.read_bytes() for p in (self.trip.export_folder() / 'photos').rglob('*') if p.is_file()}
            self.assertEqual(first, again)
            self.trip.mark(['canon'], None)
            self.trip.export(pool)
            # Taking canon (002) out renumbers img_0004 to 002; 003 is gone.
            self.assertEqual(sorted([p.name for p in (self.trip.export_folder() / 'photos').rglob('*.webp')]), ['001.webp', '001_1280.webp', '001_640.webp', '002.webp', '002_1280.webp', '002_640.webp'])
            self.assertEqual([p['id'] for p in store.read_json(self.trip.export_folder() / 'media.json')['photos']], ['img_0001', 'img_0004'])
            # A kept file that fails this time keeps its last good export, on disk and in the list.
            original = self.trip.originals / 'IMG_0004.HEIC'
            saved = original.read_bytes()
            original.write_bytes(b'not a photo')
            try:
                self.trip.export(pool)
            finally:
                original.write_bytes(saved)
                os.utime(original, ns=(self.before['IMG_0004.HEIC'][1], self.before['IMG_0004.HEIC'][1]))
            self.assertEqual(self.trip.export_progress['failed'], 1)
            self.assertTrue((self.trip.export_folder() / 'photos' / 'smaller' / '002_640.webp').exists())
            self.assertIn('img_0004', [p['id'] for p in store.read_json(self.trip.export_folder() / 'media.json')['photos']])
            self.trip.export(pool)
            self.assertEqual(self.trip.export_progress['failed'], 0)
            # As JPEG: one full-size file per kept photo in its own folder; the website's files and list stay.
            website = store.read_json(self.trip.export_folder() / 'media.json')['photos']
            webp = {str(p.relative_to(self.trip.export_folder() / 'photos')).replace(chr(92), '/'): p.read_bytes() for p in (self.trip.export_folder() / 'photos').rglob('*') if p.is_file()}
            self.assertEqual(self.trip.export_format(), 'webp')
            self.trip.set_export_format('jpeg')
            self.assertEqual(self.trip.view()['export']['format'], 'jpeg')
            self.trip.export(pool)
            jpegs = self.trip.export_folder() / 'jpeg'
            self.assertEqual(sorted(p.name for p in jpegs.iterdir()), ['001.jpg', '002.jpg'])
            with Image.open(jpegs / '001.jpg') as im:
                self.assertEqual((im.format, im.size), ('JPEG', (400, 300)))
                exif = im.getexif()
                self.assertEqual(exif.get_ifd(0x8769).get(0x9003), '2026:10:14 10:00:00')
                self.assertEqual(dict(exif.get_ifd(0x8825)), {})
                self.assertNotIn(0x0110, exif)
            self.assertEqual(store.read_json(self.trip.export_folder() / 'media.json')['photos'], website)
            self.assertEqual({str(p.relative_to(self.trip.export_folder() / 'photos')).replace(chr(92), '/'): p.read_bytes() for p in (self.trip.export_folder() / 'photos').rglob('*') if p.is_file()}, webp)
            self.trip.mark(['img_0001'], None)
            self.trip.export(pool)
            self.assertEqual([p.name for p in jpegs.iterdir()], ['001.jpg'])
            with self.assertRaises(ValueError):
                self.trip.set_export_format('png')
            self.trip.set_export_format('webp')
        self.assertEqual(self.trip.export_progress['failed'], 0)
        self.assertEqual(fingerprint_folder(self.trip.originals), self.before)

    def test_picks_are_kept(self):
        self.trip.mark(['img_0003', 'img_0004'], 'yes')
        self.trip.mark(['img_0004'], 'no')
        view = {i['id']: i for i in self.trip.view()['items']}
        self.assertEqual((view['img_0003']['pick'], view['img_0004']['pick']), ('yes', 'no'))
        self.assertEqual(trip.Trip('2026-10 Test').marks()['img_0003'], {'pick': 'yes'})

    def test_clearing_a_mark_removes_it(self):
        self.trip.mark(['canon'], 'yes')
        self.trip.mark(['canon'], None)
        self.assertNotIn('canon', self.trip.marks())

    def test_adjustments_are_kept_and_shape_the_photo(self):
        self.trip.adjust('img_0003', 0.5, -0.2)
        self.assertEqual({i['id']: i for i in self.trip.view()['items']}['img_0003']['adjust'], {'exposure': 0.5, 'warmth': -0.2})
        self.trip.set_look('landscape', 'C')
        self.assertEqual(self.trip.develop_settings('img_0003'), ('C', 1.0, 0.5, -0.2))
        self.trip.set_look('portrait', 'A')
        self.assertEqual(self.trip.develop_settings('img_0004'), ('A', 0.4, 0, 0))
        self.trip.adjust('img_0003', 0, 0)
        self.assertNotIn('img_0003', self.trip.adjustments())
        for exposure, warmth in ((3, 0), (0, -1.5), ('1', 0), (True, 0)):
            with self.assertRaises(ValueError):
                self.trip.adjust('img_0003', exposure, warmth)

    def test_clips_start_in_the_middle_until_jack_chooses(self):
        clip = self.trip.clip_of('img_0005')
        self.assertEqual((clip['start'], clip['length'], clip['sound'], clip['chosen']), (0.0, 1.0, 'mute', False))
        self.trip.set_clip('img_0005', {'start': 0, 'sound': 'original'})
        self.assertEqual(self.trip.clip_of('img_0005')['sound'], 'original')
        self.assertTrue(self.trip.clip_of('img_0005')['chosen'])
        for changes in ({'start': -1}, {'start': 99}, {'sound': 'loud'}, {'music': 'not-there.mp3'}, {'music_start': '3'}):
            with self.assertRaises(ValueError):
                self.trip.set_clip('img_0005', changes)
        with self.assertRaises(ValueError):
            self.trip.set_clip('img_0001', {'start': 0})

    def test_songs_come_only_from_the_music_folder(self):
        trip.music()  # makes the folder
        (config.MUSIC / 'Soft Morning.mp3').write_bytes(b'ID3')
        (config.MUSIC / 'notes.txt').write_text('x')
        self.assertEqual(trip.music(), ['Soft Morning.mp3'])
        self.trip.set_clip('img_0005', {'sound': 'music', 'music': 'Soft Morning.mp3', 'music_start': 12.5})
        self.assertEqual(self.trip.clip_of('img_0005')['music'], 'Soft Morning.mp3')
        self.trip.set_clip('img_0005', {'sound': 'mute'})

    def test_portraits_and_landscapes_keep_their_own_look_beside_the_picks(self):
        self.trip.mark(['img_0003'], 'yes')
        self.trip.set_look('landscape', 'B')
        self.trip.set_look('portrait', 'A')
        self.assertEqual(trip.Trip('2026-10 Test').looks(), {'portrait': 'A', 'landscape': 'B'})
        self.assertEqual(self.trip.marks()['img_0003'], {'pick': 'yes'})
        self.trip.mark(['img_0003'], 'no')
        self.assertEqual(self.trip.looks()['landscape'], 'B')
        self.trip.set_look('portrait', None)
        self.assertEqual(self.trip.view()['looks'], {'portrait': None, 'landscape': 'B'})
        for kind, look in (('portrait', 'Z'), ('people', 'A')):
            with self.assertRaises(ValueError):
                self.trip.set_look(kind, look)

    def test_subjects_are_guessed_and_can_be_changed(self):
        self.assertEqual(self.by_id['img_0004']['subject'], 'portrait')
        self.assertEqual(self.by_id['img_0003']['subject'], 'landscape')
        self.assertIsNone(self.by_id['img_0005']['subject'])
        self.trip.set_subject(['img_0003'], 'portrait')
        changed = {i['id']: i for i in self.trip.view()['items']}['img_0003']
        self.assertEqual((changed['subject'], changed['subject_reason']), ('portrait', '你改的'))
        self.trip.set_subject(['img_0003'], None)
        self.assertEqual({i['id']: i for i in self.trip.view()['items']}['img_0003']['subject'], 'landscape')
        with self.assertRaises(ValueError):
            self.trip.set_subject(['img_0003'], 'people')

    def test_bad_marks_are_refused(self):
        for ids, pick in ((['nope'], 'yes'), (['img_0001'], 'maybe'), ('img_0001', 'yes'), ([], 'yes')):
            with self.assertRaises(ValueError):
                self.trip.mark(ids, pick)

    def test_sources(self):
        self.assertEqual(self.view['own'], 'Apple iPhone 14 Pro Max')
        self.assertEqual(self.by_id['img_0001']['source'], 'mine')
        self.assertEqual(self.by_id['9916ba93-f41c']['source'], 'received')
        self.assertEqual(self.by_id['canon']['source'], 'received')

    def test_timeline_order_and_days(self):
        ids = [i['id'] for i in self.view['items']]
        self.assertEqual(ids[:5], ['img_0001', 'img_0002', 'canon', 'img_0003', 'img_0004'])
        self.assertEqual([d['day'] for d in self.view['days']], ['2026-10-14', '2026-10-15'])
        self.assertIsNone(self.by_id['9916ba93-f41c']['day'])

    def test_look_alikes_stack(self):
        self.assertIsNotNone(self.by_id['img_0001']['stack'])
        self.assertEqual(self.by_id['img_0001']['stack'], self.by_id['img_0002']['stack'])
        self.assertIsNone(self.by_id['img_0003']['stack'])

    def test_every_file_has_a_thumbnail(self):
        self.assertTrue(all(i['thumb'] for i in self.view['items']))

    def test_hdr_video(self):
        video = self.by_id['img_0005']
        self.assertEqual(video['kind'], 'video')
        self.assertTrue(video['hdr'])

    def test_rescan_reuses_the_cache(self):
        again = trip.Trip('2026-10 Test')
        again.scan()
        self.assertEqual(again.entries['img_0001']['print'], self.trip.entries['img_0001']['print'])


if __name__ == '__main__':
    unittest.main()
