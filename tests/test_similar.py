import unittest

from PIL import ImageEnhance

from studio import similar
from tests.helpers import picture


def item(id_, mark, time=None, kind='photo', colour=None):
    return {'id': id_, 'kind': kind, 'print': mark, 'time': time, 'colour': colour}


FAR = (1 << 64) - 1  # a fingerprint 64 bits away from 0


class ColourPrint(unittest.TestCase):
    def test_a_burst_shot_is_near_and_another_scene_far(self):
        a = picture(1)
        nudged = a.crop((6, 0, 400, 300)).resize((400, 300))
        self.assertLessEqual(similar.colour_distance(similar.colour_print(a), similar.colour_print(nudged)), similar.BURST_COLOUR)
        self.assertGreater(similar.colour_distance(similar.colour_print(a), similar.colour_print(picture(7))), similar.BURST_COLOUR)

    def test_wide_and_tall_never_match(self):
        a = picture(1)
        self.assertEqual(similar.colour_distance(similar.colour_print(a), similar.colour_print(a.rotate(90, expand=True))), float('inf'))


class Fingerprint(unittest.TestCase):
    def test_a_slightly_brighter_copy_is_close_and_another_scene_is_far(self):
        a = picture(1)
        brighter = ImageEnhance.Brightness(a).enhance(1.08)
        smaller = a.resize((200, 150))
        other = picture(7)
        fa = similar.fingerprint(a)
        self.assertLessEqual(similar.distance(fa, similar.fingerprint(brighter)), similar.COPY_BITS)
        self.assertLessEqual(similar.distance(fa, similar.fingerprint(smaller)), similar.COPY_BITS)
        self.assertGreater(similar.distance(fa, similar.fingerprint(other)), similar.SIMILAR_BITS)


class Groups(unittest.TestCase):
    def test_near_shots_close_in_time_stack(self):
        stacks = similar.groups([item('a', 0b1111, 0), item('b', 0b0111, 30), item('c', ~0 & (2**128 - 1), 60)])
        self.assertEqual(stacks, [['a', 'b']])

    def test_same_look_far_apart_in_time_doesnt_stack(self):
        far = similar.SIMILAR_SECONDS + 1
        self.assertEqual(similar.groups([item('a', 0, 0), item('b', (1 << 10) - 1, far)]), [])

    def test_a_received_copy_stacks_with_the_original_only_when_nearly_identical(self):
        self.assertEqual(similar.groups([item('mine', 0, 100), item('copy', 0b11, None)]), [['mine', 'copy']])
        self.assertEqual(similar.groups([item('mine', 0, 100), item('copy', (1 << 10) - 1, None)]), [])

    def test_burst_shots_stack_by_colour_when_the_fingerprint_is_far(self):
        near = similar.colour_print(picture(1))
        self.assertEqual(similar.groups([item('a', 0, 0, colour=near), item('b', FAR, 2, colour=near)]), [['a', 'b']])

    def test_colour_alone_needs_the_shots_close_in_time(self):
        near = similar.colour_print(picture(1))
        later = similar.BURST_SECONDS + 1
        self.assertEqual(similar.groups([item('a', 0, 0, colour=near), item('b', FAR, later, colour=near)]), [])

    def test_a_different_number_of_people_never_stacks(self):
        one, two = item('one', 0, 0), item('two', 0, 2)
        one['faces'], two['faces'] = 1, 2
        self.assertEqual(similar.groups([one, two]), [])
        two['faces'] = 1
        self.assertEqual(similar.groups([one, two]), [['one', 'two']])

    def test_unknown_face_counts_dont_split(self):
        mine, copy = item('mine', 0, 0), item('copy', 0, None)
        mine['faces'], copy['faces'] = 2, None
        self.assertEqual(similar.groups([mine, copy]), [['mine', 'copy']])

    def test_photos_and_videos_never_stack_together(self):
        self.assertEqual(similar.groups([item('p', 0, 0), item('v', 0, 0, 'video')]), [])

    def test_files_without_a_fingerprint_are_left_alone(self):
        self.assertEqual(similar.groups([item('a', None, 0), item('b', None, 0)]), [])


if __name__ == '__main__':
    unittest.main()
