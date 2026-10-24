import unittest

from studio import source

PHONE = {'make': 'Apple', 'model': 'iPhone 14 Pro Max', 'width': 4032, 'height': 3024, 'format': 'HEIF'}


class OwnCamera(unittest.TestCase):
    def test_the_camera_with_most_files_is_jacks(self):
        metas = [PHONE, PHONE, {'make': 'Apple', 'model': 'iPhone 15'}, {'make': None, 'model': None}]
        self.assertEqual(source.own_camera(metas), ('Apple', 'iPhone 14 Pro Max'))

    def test_no_camera_anywhere(self):
        self.assertIsNone(source.own_camera([{'width': 1280}, {}]))


class Classify(unittest.TestCase):
    own = ('Apple', 'iPhone 14 Pro Max')

    def test_jacks_phone(self):
        kind, reason = source.classify(PHONE, 'photo', self.own)
        self.assertEqual(kind, source.MINE)
        self.assertIn('iPhone 14 Pro Max', reason)

    def test_a_friends_camera_is_received(self):
        kind, reason = source.classify({'make': 'Canon', 'model': 'EOS R7'}, 'photo', self.own)
        self.assertEqual(kind, source.RECEIVED)
        self.assertIn('Canon', reason)

    def test_whatsapp_sized_photo_without_camera(self):
        kind, reason = source.classify({'format': 'JPEG', 'width': 1280, 'height': 960}, 'photo', self.own)
        self.assertEqual(kind, source.RECEIVED)
        self.assertIn('WhatsApp', reason)

    def test_large_photo_with_camera_facts_stripped(self):
        kind, reason = source.classify({'format': 'JPEG', 'width': 6960, 'height': 4640}, 'photo', self.own)
        self.assertEqual(kind, source.RECEIVED)
        self.assertNotIn('WhatsApp', reason)

    def test_screenshots(self):
        self.assertEqual(source.classify({**PHONE, 'comment': 'Screenshot'}, 'photo', self.own)[0], source.SCREENSHOT)
        self.assertEqual(source.classify({'format': 'PNG', 'width': 1290, 'height': 2796}, 'photo', self.own)[0], source.SCREENSHOT)

    def test_video_without_camera_is_received(self):
        self.assertEqual(source.classify({'format': 'h264', 'width': 848, 'height': 480}, 'video', self.own)[0], source.RECEIVED)

    def test_jacks_video(self):
        self.assertEqual(source.classify({'make': 'Apple', 'model': 'iPhone 14 Pro Max'}, 'video', self.own)[0], source.MINE)


if __name__ == '__main__':
    unittest.main()
