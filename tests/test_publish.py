import unittest
from datetime import datetime, timezone

from studio import publish


class Names(unittest.TestCase):
    def test_address(self):
        self.assertEqual(publish.address('2026-10 Yunnan'), 'yunnan-2026')
        self.assertEqual(publish.address('2027-04 Japan Kansai'), 'japan-kansai-2027')
        self.assertEqual(publish.address('Penang'), 'penang')
        with self.assertRaises(ValueError):
            publish.address('2026-10 云南')

    def test_title(self):
        self.assertEqual(publish.title('2026-10 Yunnan'), 'Yunnan')
        self.assertEqual(publish.title('Penang'), 'Penang')


class Files(unittest.TestCase):
    def test_draft_is_a_travel_post_in_malaysia_time(self):
        text = publish.draft('Yunnan', datetime(2026, 10, 24, 13, 5, 7, 123, tzinfo=timezone.utc))
        self.assertEqual(text, '---\ntitle: "Yunnan"\ndate: 2026-10-24T21:05:07+08:00\ntopic: travel\ntags: []\n'
                               'cover: ./cover.webp\ndraft: true\n---\n')

    def test_opening_and_closing_words_only_when_written(self):
        told = publish.story('yunnan-2026', [], intro='出发啦。', outro='  ')
        self.assertEqual((told.get('intro'), 'outro' in told), ('出发啦。', False))

    def test_story_keeps_only_what_the_site_reads(self):
        moments = [{'id': 'img_1', 'width': 2048, 'height': 1536, 'taken': None, 'words': '', 'extra': 1}]
        self.assertEqual(publish.story('yunnan-2026', moments),
                         {'folder': 'yunnan-2026', 'moments': [{'id': 'img_1', 'width': 2048, 'height': 1536, 'taken': None, 'words': ''}]})
