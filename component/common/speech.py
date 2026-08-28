from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from util.audio_helper import AudioPlayer
from util.byteplus_tts_helper import BytePlusTTS


class SpeechService:
    """Prepare and play task announcements."""

    def __init__(self, audio_dir="output/tasks") -> None:
        self.tts = BytePlusTTS()
        self.player = AudioPlayer()
        self.audio_dir = Path(audio_dir)

    def _tts(self):
        return self.tts

    def _player(self):
        return self.player

    def audio_path(self, task, stop, stop_index):
        label = re.sub(r"[^a-z0-9]+", "_", stop["poi_name"].casefold()).strip("_")
        return self.audio_dir / task["id"] / f"{stop_index:02d}_{label or 'poi'}.mp3"

    def label_path(self, label):
        safe_label = re.sub(r"[^a-z0-9]+", "_", label.casefold()).strip("_")
        return self.audio_dir / f"{safe_label or 'speech'}.mp3"

    def prepare(self, task, stop, stop_index):
        return self._tts().synthesize_mp3(
            stop["content"],
            self.audio_path(task, stop, stop_index),
        )

    def play(self, audio_path):
        self._player().play_mp3(audio_path)

    def speak(self, text, label):
        """Synthesize and play one standalone announcement."""
        audio_path = self._tts().synthesize_mp3(text, self.label_path(label))
        self._player().play_mp3(audio_path)
        return audio_path
