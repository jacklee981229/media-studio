"""Where Media Studio keeps things. The environment overrides are for the tests and for Claude's own copy on 4712."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRIPS = Path(os.environ.get('MEDIA_STUDIO_TRIPS') or Path(os.environ['USERPROFILE']) / 'Pictures' / 'Trips')
CACHE = Path(os.environ.get('MEDIA_STUDIO_CACHE') or Path(os.environ['LOCALAPPDATA']) / 'MediaStudio')
PORT = int(os.environ.get('MEDIA_STUDIO_PORT') or 4710)
# Songs Jack may use under his clips: music he has the right to publish, put here by him.
MUSIC = Path(os.environ.get('MEDIA_STUDIO_MUSIC') or Path(os.environ['USERPROFILE']) / 'Music' / 'Media Studio')
MUSIC_TYPES = {'.mp3', '.m4a', '.aac', '.wav', '.flac', '.ogg'}
FFMPEG = ROOT / 'tools' / 'ffmpeg' / 'ffmpeg.exe'
FFPROBE = ROOT / 'tools' / 'ffmpeg' / 'ffprobe.exe'
WEB = ROOT / 'web'

PHOTO_TYPES = {'.heic', '.heif', '.jpg', '.jpeg', '.png'}
VIDEO_TYPES = {'.mov', '.mp4', '.m4v'}
