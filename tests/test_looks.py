import unittest

from PIL import ImageChops, ImageStat

from studio import looks
from tests.helpers import picture


def difference(a, b) -> float:
    return sum(ImageStat.Stat(ImageChops.difference(a.convert('RGB'), b.convert('RGB'))).mean) / 3


class Looks(unittest.TestCase):
    def test_strength_zero_leaves_the_photo_as_shot(self):
        im = picture(3)
        self.assertLess(difference(im, looks.apply(im, 'B', 0)), 0.6)

    def test_no_look_returns_the_photo_itself(self):
        im = picture(3)
        self.assertIs(looks.apply(im, None), im)

    def test_every_look_changes_the_photo_and_each_differently(self):
        im = picture(3)
        shown = {k: looks.apply(im, k) for k in looks.LOOKS}
        for k, out in shown.items():
            self.assertGreater(difference(im, out), 1, k)
        keys = list(shown)
        for n, a in enumerate(keys):
            for b in keys[n + 1:]:
                self.assertGreater(difference(shown[a], shown[b]), 1, f'{a} vs {b}')

    def test_looks_stay_gentle(self):
        """A look shifts the mood; it never turns a photo into a different picture."""
        im = picture(3)
        for k in looks.LOOKS:
            self.assertLess(difference(im, looks.apply(im, k)), 25, k)

    def test_white_stays_white_and_black_stays_dark(self):
        for k in looks.LOOKS:
            colour = looks.recipe(looks.LOOKS[k])
            self.assertGreater(min(colour(1.0, 1.0, 1.0)), 0.93, k)
            self.assertLess(max(colour(0.0, 0.0, 0.0)), 0.12, k)

    def test_develop_without_changes_is_the_photo_as_shot(self):
        im = picture(4)
        self.assertLess(difference(im, looks.develop(im, None, 1.0, 0, 0)), 0.01)

    def test_exposure_brightens_and_darkens_but_white_stays_white(self):
        im = picture(4)
        mean = lambda x: sum(ImageStat.Stat(x).mean) / 3
        self.assertGreater(mean(looks.develop(im, None, 1.0, 0.7, 0)), mean(im) + 5)
        self.assertLess(mean(looks.develop(im, None, 1.0, -0.7, 0)), mean(im) - 5)
        self.assertEqual(looks._adjust_table(1.0, 0.0)[255], 255)

    def test_warmth_moves_red_against_blue(self):
        im = picture(4)
        warm = ImageStat.Stat(looks.develop(im, None, 1.0, 0, 1)).mean
        cool = ImageStat.Stat(looks.develop(im, None, 1.0, 0, -1)).mean
        self.assertGreater(warm[0] - warm[2], cool[0] - cool[2] + 5)

    def test_every_look_has_a_name_and_an_idea(self):
        for entry in looks.summary():
            self.assertTrue(entry['name'] and entry['idea'])


if __name__ == '__main__':
    unittest.main()
