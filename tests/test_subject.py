import tempfile
import unittest
from pathlib import Path

from studio import meta, subject
from tests.helpers import face_xmp, picture, save_photo


class Faces(unittest.TestCase):
    def test_iphone_face_regions_are_read(self):
        self.assertEqual(meta.faces(face_xmp(0.046, 0.03)), [0.046, 0.03])
        self.assertEqual(meta.faces(face_xmp()), [])
        self.assertIsNone(meta.faces(None))

    def test_faces_come_out_of_a_real_heic(self):
        path = save_photo(Path(tempfile.mkdtemp()) / 'IMG_1.HEIC', picture(1), 'HEIF', xmp=face_xmp(0.05),
                          make='Apple', model='iPhone 14 Pro Max')
        self.assertEqual(meta.read_photo(path)['faces'], [0.05])


class Classify(unittest.TestCase):
    def test_a_face_makes_a_portrait(self):
        self.assertEqual(subject.classify({'faces': [0.03]}, 'photo', 'mine')[0], subject.PORTRAIT)

    def test_only_tiny_faces_is_a_landscape(self):
        self.assertEqual(subject.classify({'faces': [0.01, 0.015]}, 'photo', 'mine')[0], subject.LANDSCAPE)

    def test_no_faces_is_a_landscape(self):
        self.assertEqual(subject.classify({'faces': None}, 'photo', 'mine')[0], subject.LANDSCAPE)
        self.assertEqual(subject.classify({'faces': []}, 'photo', 'mine')[0], subject.LANDSCAPE)

    def test_received_photos_without_face_facts_count_as_portraits(self):
        self.assertEqual(subject.classify({'faces': None}, 'photo', 'received')[0], subject.PORTRAIT)

    def test_videos_have_no_subject(self):
        self.assertEqual(subject.classify({}, 'video', 'mine'), (None, None))


if __name__ == '__main__':
    unittest.main()
