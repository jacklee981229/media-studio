import tempfile
import unittest
from pathlib import Path

from studio import meta
from tests.helpers import hdr_clip, picture, save_photo


class Photos(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_iphone_heic(self):
        path = save_photo(self.dir / 'IMG_0001.HEIC', picture(1), 'HEIF', make='Apple', model='iPhone 14 Pro Max',
                          taken='2026:10:14 15:01:38', offset='+08:00', gps=(25.5, 102.75))
        facts = meta.read_photo(path)
        self.assertEqual((facts['make'], facts['model']), ('Apple', 'iPhone 14 Pro Max'))
        self.assertEqual((facts['taken'], facts['offset']), ('2026:10:14 15:01:38', '+08:00'))
        self.assertEqual(facts['gps'], [25.5, 102.75])
        self.assertEqual((facts['width'], facts['height']), (400, 300))

    def test_received_jpeg_has_no_camera(self):
        facts = meta.read_photo(save_photo(self.dir / 'a1b2.jpg', picture(2), 'JPEG'))
        self.assertIsNone(facts['make'])
        self.assertIsNone(facts['taken'])
        self.assertIsNone(facts['gps'])

    def test_binary_scraps_where_text_belongs_are_dropped(self):
        facts = meta.read_photo(save_photo(self.dir / 'odd.jpg', picture(3), 'JPEG', offset='\x00\x06\x01\x03\x00\x03'))
        self.assertIsNone(facts['offset'])

    def test_screenshot_comment(self):
        facts = meta.read_photo(save_photo(self.dir / 'shot.png', picture(4), 'PNG', comment='Screenshot'))
        self.assertEqual(facts['comment'], 'Screenshot')

    def test_sideways_jpeg_reports_its_upright_size(self):
        path = self.dir / 'side.jpg'
        from PIL import Image
        exif = Image.Exif()
        exif[0x0112] = 6
        picture(5).save(path, 'JPEG', exif=exif.tobytes())
        facts = meta.read_photo(path)
        self.assertEqual((facts['width'], facts['height']), (300, 400))


class Videos(unittest.TestCase):
    def test_probe_answer(self):
        probe = {
            'format': {'duration': '12.345', 'tags': {
                'com.apple.quicktime.make': 'Apple', 'com.apple.quicktime.model': 'iPhone 14 Pro Max',
                'com.apple.quicktime.creationdate': '2026-10-15T09:13:34+0800',
                'com.apple.quicktime.location.ISO6709': '+25.0453+102.7097+1890.000/'}},
            'streams': [{'codec_type': 'video', 'codec_name': 'hevc', 'width': 3840, 'height': 2160,
                         'color_transfer': 'arib-std-b67', 'side_data_list': [{'rotation': -90}]}],
        }
        facts = meta.video_meta(probe)
        self.assertEqual((facts['width'], facts['height']), (2160, 3840))
        self.assertTrue(facts['hdr'])
        self.assertEqual(facts['duration'], 12.35)
        self.assertEqual(facts['gps'], [25.0453, 102.7097])
        self.assertEqual(facts['created'], '2026-10-15T09:13:34+0800')

    def test_received_video(self):
        facts = meta.video_meta({'format': {'duration': '5'}, 'streams': [{'codec_type': 'video', 'codec_name': 'h264', 'width': 848, 'height': 480}]})
        self.assertFalse(facts['hdr'])
        self.assertIsNone(facts['make'])
        self.assertIsNone(facts['created'])

    def test_real_hdr_clip(self):
        facts = meta.read_video(hdr_clip(Path(tempfile.mkdtemp()) / 'IMG_0002.MOV'))
        self.assertTrue(facts['hdr'])
        self.assertEqual((facts['width'], facts['height']), (320, 240))


if __name__ == '__main__':
    unittest.main()
