import asyncio
import io
import os
import tempfile
import httpx
import pyttsx3
from typing import Optional
from core.config import settings
from core.logging import get_logger

log = get_logger(__name__)

# Cache for the Whisper model
_whisper_model = None

class VoiceIO:
    @staticmethod
    def _get_whisper():
        global _whisper_model
        if _whisper_model is None:
            # Check for ffmpeg which is required for whisper to load audio
            import shutil
            if not shutil.which("ffmpeg"):
                log.error("voice.stt.missing_ffmpeg", 
                          detail="ffmpeg not found in PATH. STT will fail. Install with 'brew install ffmpeg'")
                return None

            import whisper
            log.info("voice.stt.loading_model", model=settings.whisper_model_size)
            _whisper_model = whisper.load_model(settings.whisper_model_size)
        return _whisper_model

    @classmethod
    async def transcribe(cls, audio_bytes: bytes, format: str = "webm") -> str:
        """Transcribe audio bytes using local Whisper model."""
        try:
            with tempfile.NamedTemporaryFile(suffix=f".{format}", delete=False) as tf:
                tf.write(audio_bytes)
                temp_path = tf.name

            model = await asyncio.to_thread(cls._get_whisper)
            result = await asyncio.to_thread(model.transcribe, temp_path)
            
            os.remove(temp_path)
            return result.get("text", "").strip()
        except Exception as e:
            log.warning("voice.stt.failed", error=str(e))
            return ""

    @classmethod
    async def synthesise(cls, text: str) -> bytes:
        """Convert text to speech, preferring ElevenLabs with fallback to native macOS 'say'."""
        if settings.elevenlabs_api_key:
            try:
                return await cls._synthesise_elevenlabs(text)
            except Exception as e:
                log.warning("voice.tts.elevenlabs_failed", error=str(e))
        
        # Fallback to macOS native 'say' command (highly reliable)
        return await cls._synthesise_macos_say(text)

    @classmethod
    async def _synthesise_elevenlabs(cls, text: str) -> bytes:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{settings.elevenlabs_voice_id}"
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": settings.elevenlabs_api_key
        }
        data = {
            "text": text,
            "model_id": "eleven_monolingual_v1",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.5}
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=data, headers=headers)
            resp.raise_for_status()
            return resp.content

    @classmethod
    async def _synthesise_macos_say(cls, text: str) -> bytes:
        """Native macOS TTS using the 'say' command."""
        import subprocess
        try:
            with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as tf:
                temp_path = tf.name
            
            # Use 'say' to generate high-quality AIFF
            # We use AIFF-C because browsers handle it well or we can convert if needed
            process = await asyncio.create_subprocess_exec(
                "say", text, "-o", temp_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            await process.wait()
            
            with open(temp_path, "rb") as f:
                data = f.read()
            os.remove(temp_path)
            
            # Browser check: Audio() handles AIFF in Safari/Chrome on Mac.
            # If not, we could pipe through ffmpeg here if we had it.
            return data
        except Exception as e:
            log.error("voice.tts.macos_say_failed", error=str(e))
            return b""
