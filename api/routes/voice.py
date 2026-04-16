import base64
import time
from fastapi import APIRouter, UploadFile, File, Form
from modalities.voice import VoiceIO
from orchestration.react_loop import run_orchestrated
from core.schemas import TaskRequest, APIResponse
from core.logging import get_logger
from uuid import uuid4

log = get_logger(__name__)
router = APIRouter(prefix="/voice")

@router.post("/transcribe", response_model=APIResponse)
async def voice_to_task(audio: UploadFile = File(...)):
    """Convert audio to text, execute task, and return audio response."""
    start_time = time.monotonic()
    trace_id = str(uuid4())
    
    # 1. Transcribe audio
    content = await audio.read()
    transcript = await VoiceIO.transcribe(content)
    
    if not transcript:
        return APIResponse(
            success=True, 
            data={"transcript": "", "response": "I couldn't hear you clearly.", "audio": ""},
            message="No speech detected"
        )
    
    # 2. Execute task via Orchestrator
    req = TaskRequest(
        user_input=transcript,
        session_id="voice_session",
        user_id="default_user",
        trace_id=trace_id
    )
    # We pass an empty history for now or could load session history
    result = await run_orchestrated(req, [], time.monotonic())
    
    # 3. Synthesize response
    audio_bytes = await VoiceIO.synthesise(result.answer)
    
    # Determine mime type
    mime_type = "audio/mpeg" 
    if audio_bytes and audio_bytes.startswith(b"FORM"):
        mime_type = "audio/x-aiff"
    elif audio_bytes and audio_bytes.startswith(b"OggS"):
        mime_type = "audio/ogg"
    
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8") if audio_bytes else ""
    
    log.info("voice.interaction.complete", trace_id=trace_id, duration_ms=int((time.monotonic()-start_time)*1000))
    
    data = {
        "transcript": transcript,
        "response": result.answer,
        "audio": audio_b64,
        "mime_type": mime_type
    }
    return APIResponse(success=True, data=data, message="Voice capture handled")

@router.get("/status", response_model=APIResponse)
async def voice_status():
    from core.config import settings
    data = {
        "stt": f"whisper-{settings.whisper_model_size}",
        "tts": "elevenlabs" if settings.elevenlabs_api_key else "macos-say",
        "ready": True
    }
    return APIResponse(success=True, data=data)
