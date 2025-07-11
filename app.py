import os
import hashlib
import logging
from pathlib import Path

from flask import Flask, request, Response, stream_with_context, jsonify, render_template
from dotenv import load_dotenv

# --- Architectural Module Imports (Following Best Practices) ---
from modules import (
    setup_cache_directory,
    get_path_from_key,
    check_cache_exists,
    stream_from_cache,
    touch_cache_file,
    fetch_and_parse,
    create_tts_engine,
    TTSEngineError,
)

# --- Initialization & Configuration ---
load_dotenv()
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')

# --- Resilient Application Startup ---
# Create TTS engine instance via factory function
tts_engine = create_tts_engine()
try:
    # Ensure cache directory exists on startup
    setup_cache_directory()
except OSError as e:
    app.logger.critical(f"FATAL: Could not create or access cache directory. {e}", exc_info=True)
    # The application can still run but will fail on any cache operation.

if not tts_engine:
    app.logger.critical("TTS Engine failed to initialize. TTS functionality will be disabled.")


# --- Constants and In-Memory Caches ---
MAX_CONTENT_LENGTH = int(os.getenv('MAX_CONTENT_LENGTH', 200000))
# Using a simple dictionary for the metadata cache, as logic is now handled manually.
metadata_cache = {}


# --- Helper Functions ---
def get_metadata_with_cache(url: str):
    """
    Manually implements a cache for metadata that *only* stores successful results.
    This prevents caching `None` or incomplete data, making the app more resilient.
    """
    if url in metadata_cache:
        app.logger.info(f"Metadata cache HIT for: {url}")
        return metadata_cache[url]

    app.logger.info(f"Metadata cache MISS for: {url}")
    metadata = fetch_and_parse(url)

    # Only cache valid, complete results to avoid poisoning the cache.
    if metadata and metadata.get('content'):
        metadata_cache[url] = metadata

    return metadata


# --- API Endpoints ---
@app.route('/')
def serve_frontend():
    """Serves the main frontend application."""
    return render_template('index.html')


@app.route('/api/metadata')
def get_metadata():
    """Provides chapter metadata, using a robust, failure-resistant cache."""
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'URL không được để trống.'}), 400

    try:
        metadata = get_metadata_with_cache(url)
        if metadata and metadata.get('title'):
            return jsonify({
                'title': metadata.get('title'),
                'next_url': metadata.get('next_url'),
                'prev_url': metadata.get('prev_url'),
            }), 200
        else:
            # Trả về lỗi có cấu trúc
            return jsonify({
                'error_code': 'METADATA_EXTRACTION_FAILED',
                'message': 'Bot không tìm thấy tiêu đề từ link này. Mẹ thử kiểm tra lại link nhé.'
            }), 422
    except Exception as e:
        app.logger.error(f"Error fetching metadata for {url}: {e}", exc_info=True)
        return jsonify({'error': 'Đã có lỗi xảy ra khi lấy thông tin truyện.'}), 500


@app.route('/api/read')
def read_stream():
    """Streams audio with robust file-based locking, caching, and error handling."""
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'URL không được để trống.'}), 400

    if not tts_engine:
         return jsonify({'error': 'Dịch vụ đọc truyện đang tạm thời gián đoạn. Mẹ có thể nghe lại các truyện đã có sẵn.'}), 503

    cache_key = hashlib.md5(url.encode()).hexdigest()
    final_path = get_path_from_key(cache_key)

    if check_cache_exists(final_path):
        app.logger.info(f"Cache HIT for URL: {url}")
        touch_cache_file(final_path) # Critical for LRU cleanup logic
        return Response(stream_with_context(stream_from_cache(final_path)), mimetype='audio/mpeg')

    # Use robust file-based locking for multi-process environments (like Gunicorn)
    lock_path = final_path.with_suffix('.lock')
    if lock_path.exists():
        return jsonify({'error': 'Truyện này đang được chuẩn bị. Mẹ vui lòng thử lại sau vài giây.'}), 429

    try:
        lock_path.touch() # Create lock file
        app.logger.info(f"Cache MISS and LOCK acquired for URL: {url}")

        metadata = get_metadata_with_cache(url)
        if not metadata or not metadata.get('content'):
            # Trả về lỗi có cấu trúc
            return jsonify({
                'error_code': 'CONTENT_EXTRACTION_FAILED',
                'message': 'Bot không đọc được nội dung từ link này. Có thể trang web đã thay đổi hoặc không được hỗ trợ.'
            }), 422

        content = metadata['content']
        if len(content) > MAX_CONTENT_LENGTH:
            content = content[:MAX_CONTENT_LENGTH]
            content += "\n\nBot nói: Chương này quá dài, bot chỉ đọc một phần thôi nhé."
            app.logger.warning(f"Content for {url} truncated to {MAX_CONTENT_LENGTH} characters.")

        def generate_and_cache():
            temp_path = final_path.with_suffix('.mp3.tmp')
            success = False
            try:
                with temp_path.open('wb') as f:
                    for chunk in tts_engine.stream(content):
                        f.write(chunk)
                        yield chunk
                # If loop completes without error, rename and mark as success
                temp_path.rename(final_path)
                success = True
                app.logger.info(f"Cache SAVED successfully for URL: {url}")
            finally:
                # This cleanup is now safe: only deletes temp file on failure or cancellation.
                if not success and temp_path.exists():
                    app.logger.warning(f"Generation for {url} failed/cancelled. Cleaning up temp file.")
                    temp_path.unlink()

        return Response(stream_with_context(generate_and_cache()), mimetype='audio/mpeg')

    except Exception as e:
        app.logger.error(f"Outer exception in /api/read for {url}: {e}", exc_info=True)
        # This will be caught by the generic 500 handler
        raise
    finally:
        # Always release the lock file
        if lock_path.exists():
            lock_path.unlink()
            app.logger.info(f"LOCK released for URL: {url}")


# --- Global Error Handlers ---
@app.errorhandler(TTSEngineError)
def handle_tts_engine_error(error):
    """Handles specific, known errors from the TTS engine gracefully."""
    app.logger.error(f"TTSEngineError caught: {error}")
    return jsonify({'error': f'Lỗi từ hệ thống đọc truyện: {error}'}), 503

@app.errorhandler(404)
def not_found_error(error):
    """Handles 404 Not Found errors for both API and regular paths."""
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Không tìm thấy tài nguyên API.'}), 404
    return "<h1>404 Not Found</h1><p>Trang bạn tìm không tồn tại.</p>", 404

@app.errorhandler(500)
def internal_error(error):
    """Handles generic 500 Internal Server Error."""
    app.logger.error(f"Internal Server Error caught by handler: {error}", exc_info=True)
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Máy chủ gặp lỗi, bot không thể xử lý yêu cầu này.'}), 500
    return "<h1>500 Internal Server Error</h1><p>Máy chủ đã gặp sự cố.</p>", 500


# --- Main Execution Block ---
if __name__ == '__main__':
    # Use environment variables for production-ready configuration
    port = int(os.environ.get('PORT', 5001))
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() in ['true', '1', 't']
    app.run(debug=debug_mode, host='0.0.0.0', port=port)