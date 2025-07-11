import os
import asyncio
import queue
import re
import logging
import typing
import time
from threading import Thread
import edge_tts
import platform 
IS_WINDOWS = platform.system() == "Windows"

# --- Module Level Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(module)s - %(message)s')

# --- Constants ---
# Max characters to send to TTS API in a single request.
TEXT_CHUNK_SIZE = 2500
# Timeout for waiting for a chunk from the producer thread (in seconds).
CONSUMER_TIMEOUT = 30
# Timeout for the entire TTS stream generation for a single text chunk (in seconds).
PRODUCER_STREAM_TIMEOUT = 60
# Increased queue size to prevent back-pressure from a slow consumer causing false timeouts.
QUEUE_MAX_SIZE = 100

class TTSEngineError(Exception):
    """Custom exception for TTSEngine specific errors, like timeouts or generation failures."""
    pass

class TTSEngine:
    """
    A fault-tolerant, streaming Text-to-Speech engine using Microsoft Edge's TTS service.
    This class encapsulates the complexity of running an async TTS library within a sync context,
    with added robustness for handling long texts, timeouts, and multi-threading risks.
    """

    def __init__(self, voice: str, rate: str = "+0%", volume: str = "+0%"):
        self.voice = voice
        self.rate = self._validate_percent_string(rate, "rate")
        self.volume = self._validate_percent_string(volume, "volume")

    @staticmethod
    def _validate_percent_string(value: str, name: str) -> str:
        """Validates that a string is a valid percentage format for edge-tts."""
        if not isinstance(value, str) or not re.match(r"^[+-]\d{1,3}%$", value):
            raise ValueError(
                f"Invalid format for TTS {name}. Expected format like '+10%', got '{value}'."
            )
        return value

    def _chunk_text(self, text: str) -> typing.Generator[str, None, None]:
        """
        Splits text into chunks, respecting paragraph and word boundaries.
        This is crucial for generating high-quality audio without unnatural pauses or cut-off words.
        """
        if not text:
            return

        paragraphs = text.split('\n')
        current_chunk = ""

        for p in paragraphs:
            # If a single paragraph is too large, it must be force-split.
            if len(p) >= TEXT_CHUNK_SIZE:
                # First, yield any preceding text in the current chunk.
                if current_chunk:
                    yield current_chunk
                    current_chunk = ""
                
                # Split the oversized paragraph by word boundaries.
                start = 0
                while start < len(p):
                    # Find the last space within the chunk size limit.
                    end = p.rfind(' ', start, start + TEXT_CHUNK_SIZE)
                    if end == -1 or end <= start:
                        # No space found, force cut.
                        end = start + TEXT_CHUNK_SIZE
                    yield p[start:end]
                    start = end + 1 # +1 to skip the space
                continue
            
            # If adding the next paragraph fits, append it.
            if len(current_chunk) + len(p) + 1 < TEXT_CHUNK_SIZE:
                current_chunk += p + "\n"
            # Otherwise, yield the current chunk and start a new one.
            else:
                yield current_chunk
                current_chunk = p + "\n"
        
        # Yield any remaining text in the last chunk.
        if current_chunk.strip():
            yield current_chunk

    def stream(self, text: str, rate: str = None, volume: str = None) -> typing.Generator[bytes, None, None]:
        """
        Generates an audio stream from text. This is a generator function that manages a producer
        thread and ensures its cleanup, even if the consumer (client) disconnects prematurely.
        """
        if not text or not text.strip():
            return

        final_rate = self._validate_percent_string(rate, "rate") if rate else self.rate
        final_volume = self._validate_percent_string(volume, "volume") if volume else self.volume
        audio_queue = queue.Queue(maxsize=QUEUE_MAX_SIZE)

        def _safe_put(item):
            """Puts an item into the queue, discarding an old one if the queue is full."""
            try:
                audio_queue.put_nowait(item)
            except queue.Full:
                logging.warning("TTS audio_queue is full. Discarding oldest chunk to make space for a critical message.")
                try:
                    audio_queue.get_nowait() # Discard one old item.
                    audio_queue.put_nowait(item) # Retry putting the new item.
                except queue.Empty:
                    pass # Should not happen, but defensive.

        async def _produce_audio():
            """The async producer function that runs in a separate thread."""

            # --- HÀM TRỢ GIÚP MỚI ---
            # Hàm này nhận một đoạn text, stream nó và đưa vào queue.
            # Đây là một 'coroutine' hoàn chỉnh.
            async def stream_and_queue_chunk(text_chunk_to_stream):
                communicate = edge_tts.Communicate(text_chunk_to_stream, self.voice, rate=final_rate, volume=final_volume)
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_queue.put(chunk["data"])

            # --- LOGIC CHÍNH ĐÃ ĐƯỢC SỬA LẠI ---
            try:
                # Lặp qua từng đoạn văn bản lớn
                for text_chunk in self._chunk_text(text):
                    if not text_chunk.strip():
                        continue
                    
                    # Với mỗi đoạn, chúng ta gọi hàm trợ giúp ở trên VÀ
                    # áp dụng timeout cho TOÀN BỘ quá trình thực thi của nó.
                    await asyncio.wait_for(
                        stream_and_queue_chunk(text_chunk),
                        timeout=PRODUCER_STREAM_TIMEOUT
                    )

            except asyncio.TimeoutError:
                logging.error(f"TTS stream generation for a chunk timed out after {PRODUCER_STREAM_TIMEOUT}s.")
                _safe_put(TTSEngineError("Quá trình tạo giọng đọc cho một đoạn bị quá giờ."))
            except Exception as e:
                logging.error(f"An exception occurred in the TTS producer thread: {e}", exc_info=True)
                _safe_put(TTSEngineError(f"Không thể tạo giọng đọc do lỗi: {type(e).__name__}"))
            finally:
                _safe_put(None)

        def _run_producer_thread():
            """Target for the producer thread to safely run the asyncio event loop."""
            # --- BLOCK CODE SỬA LỖI CHO WINDOWS ---
            if IS_WINDOWS:
                try:
                    import winloop
                    asyncio.set_event_loop_policy(winloop.EventLoopPolicy())
                except ImportError:
                    logging.warning("winloop not installed, TTS might fail on Windows.")
            # --- KẾT THÚC BLOCK SỬA LỖI ---
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(_produce_audio())
            except Exception as e:
                logging.error(f"Critical error in producer thread supervisor: {e}")
                _safe_put(TTSEngineError("Luồng xử lý giọng đọc đã gặp lỗi nghiêm trọng."))
            finally:
                loop.close()

        producer_thread = Thread(target=_run_producer_thread, daemon=True)
        producer_thread.start()

        try:
            # Consumer loop in the main thread with timeout.
            while True:
                try:
                    chunk = audio_queue.get(timeout=CONSUMER_TIMEOUT)
                    if chunk is None: break
                    if isinstance(chunk, Exception): raise chunk
                    yield chunk
                except queue.Empty:
                    logging.error("TTS consumer timed out. The producer thread is unresponsive or dead.")
                    raise TTSEngineError("Quá trình tạo giọng đọc không phản hồi, vui lòng thử lại.")
        finally:
            # This block is crucial. It runs even if the client disconnects.
            logging.debug("TTS consumer loop finished or terminated. Cleaning up producer thread.")
            # Drain the queue to unblock the producer if it's stuck on put().
            while not audio_queue.empty():
                try:
                    audio_queue.get_nowait()
                except queue.Empty:
                    break
            # Wait for the producer thread to finish its work and exit.
            producer_thread.join(timeout=5.0)
            if producer_thread.is_alive():
                logging.warning("TTS producer thread did not terminate cleanly after cleanup.")

def create_tts_engine() -> typing.Optional[TTSEngine]:
    """
    Factory function to create a pre-configured TTSEngine instance.
    Reads configuration from environment variables. Raises error on failure.
    """
    try:
        voice = os.getenv('TTS_VOICE', 'vi-VN-HoaiMyNeural')
        rate = os.getenv('TTS_RATE', '+0%')
        volume = os.getenv('TTS_VOLUME', '+0%')
        
        engine = TTSEngine(voice=voice, rate=rate, volume=volume)
        logging.info(f"TTS Engine created successfully with voice='{voice}', rate='{rate}', volume='{volume}'")
        return engine
    except ValueError as e:
        logging.critical(f"FATAL: Could not create TTSEngine due to invalid configuration. {e}")
        raise # Re-raise the exception to be caught by the application's main entry point.

# --- Singleton Instance ---
# A single, shared instance is created. If it fails, `default_engine` will be None,
# and the application can check for this to disable TTS functionality gracefully.
#try:
#    default_engine = create_tts_engine()
#except Exception:
#    default_engine = None
#    logging.critical("TTS Engine failed to initialize during module import. TTS functionality will be disabled.")