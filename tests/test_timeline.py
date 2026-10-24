import unittest
from datetime import timedelta

from studio import timeline


class Taken(unittest.TestCase):
    def test_photo_with_offset(self):
        when = timeline.taken({'taken': '2026:10:14 15:01:38', 'offset': '+08:00'})
        self.assertEqual(when.isoformat(), '2026-10-14T15:01:38+08:00')

    def test_photo_without_offset_is_read_as_utc8(self):
        self.assertEqual(timeline.taken({'taken': '2026:10:14 23:59:00'}).utcoffset(), timedelta(hours=8))

    def test_other_offsets_keep_their_local_day(self):
        when = timeline.taken({'taken': '2026:10:14 01:00:00', 'offset': '-05:30'})
        self.assertEqual(when.strftime('%Y-%m-%d'), '2026-10-14')
        self.assertEqual(when.utcoffset(), -timedelta(hours=5, minutes=30))

    def test_iphone_video(self):
        when = timeline.taken({'created': '2026-10-15T09:13:34+0800'})
        self.assertEqual(when.isoformat(), '2026-10-15T09:13:34+08:00')

    def test_nothing_or_nonsense(self):
        self.assertIsNone(timeline.taken({}))
        self.assertIsNone(timeline.taken({'taken': '0000:00:00 00:00:00'}))
        self.assertIsNone(timeline.taken({'created': 'yesterday'}))

    def test_day_label(self):
        self.assertEqual(timeline.day_label('2026-10-14'), '10月14日 周三')


if __name__ == '__main__':
    unittest.main()
