import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from studio import config, export, looks, meta
from tests.helpers import hdr_clip


def probe(path: Path) -> dict:
    out = subprocess.run([str(config.FFPROBE), '-v', 'error', '-print_format', 'json', '-show_format', '-show_streams', str(path)],
                         capture_output=True, check=True).stdout
    return json.loads(out)


class Names(unittest.TestCase):
    def test_numbers_in_timeline_order(self):
        items = [{'id': 'img_9'}, {'id': 'img_1'}, {'id': '9916ba93'}]
        self.assertEqual(export.names(items), {'img_9': '001', 'img_1': '002', '9916ba93': '003'})
        self.assertEqual(export.names([{'id': str(n)} for n in range(1200)])['1199'], '1200')
        self.assertEqual(export.names([{'id': str(n)} for n in range(1200)])['0'], '0001')

    def test_largest_on_top_the_rest_in_a_folder(self):
        self.assertEqual(export.photo_files('007'), {'640': 'photos/smaller/007_640.webp',
                                                     '1280': 'photos/smaller/007_1280.webp', '2048': 'photos/007.webp'})


class Commands(unittest.TestCase):
    def test_sound_choices(self):
        mute = export.clip_command('ffmpeg', 'in.mov', 'out.mp4', 3, 7, True, 'look.cube', 'mute')
        self.assertIn('-an', mute)
        own = export.clip_command('ffmpeg', 'in.mov', 'out.mp4', 3, 7, True, None, 'original')
        self.assertIn('0:a:0?', own)
        song = export.clip_command('ffmpeg', 'in.mov', 'out.mp4', 3, 7, False, None, 'music', 'song.mp3', 40)
        self.assertEqual(song[song.index('song.mp3') - 5:song.index('song.mp3') + 1], ['-ss', '40.000', '-t', '7.000', '-i', 'song.mp3'])
        self.assertIn('1:a:0', song)
        for cmd in (mute, own, song):
            self.assertIn('-map_metadata', cmd)

    def test_the_look_goes_in_only_when_there_is_one(self):
        self.assertIn('lut3d=file=look.cube', export.video_filter(True, 'look.cube'))
        self.assertNotIn('lut3d', export.video_filter(True, None))
        self.assertIn('tonemap', export.video_filter(True, None))
        self.assertNotIn('tonemap', export.video_filter(False, None))

    def test_cube_files_have_every_point(self):
        text = looks.cube('A')
        lines = text.strip().split('\n')
        self.assertEqual(lines[0], f'LUT_3D_SIZE {looks.SIZE}')
        self.assertEqual(len(lines) - 1, looks.SIZE ** 3)


class RealClip(unittest.TestCase):
    def test_hdr_clip_comes_out_sdr_short_and_without_metadata(self):
        work = Path(tempfile.mkdtemp())
        src = hdr_clip(work / 'IMG_0001.MOV', seconds=3)
        (work / 'look.cube').write_text(looks.cube('A'))
        entry = export.export_video(str(config.FFMPEG), str(src), str(work / 'out'), 'img_0001', 1.0, 1.5, True,
                                    str(work), 'look.cube', 'mute')
        made = probe(work / 'out' / 'img_0001.mp4')
        video = made['streams'][0]
        self.assertEqual((video['codec_name'], video['pix_fmt'], video.get('color_transfer')), ('h264', 'yuv420p', 'bt709'))
        self.assertAlmostEqual(float(made['format']['duration']), 1.5, delta=0.1)
        self.assertEqual(len(made['streams']), 1)
        self.assertNotIn('creation_time', made['format'].get('tags', {}))
        self.assertEqual(entry['poster'], 'videos/img_0001.webp')
        self.assertTrue((work / 'out' / 'img_0001.webp').exists())
        self.assertFalse(meta.video_meta(made)['hdr'])


if __name__ == '__main__':
    unittest.main()
