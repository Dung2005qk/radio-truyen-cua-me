"""
Đây là file khởi tạo cho package 'modules'.

Nó đóng vai trò là giao diện công khai (public API) cho package,
giúp các phần khác của ứng dụng (như app.py) có thể import
các chức năng cần thiết một cách gọn gàng mà không cần biết
chi tiết về cấu trúc file bên trong.
"""

# Các import được sắp xếp theo thứ tự alphabet của module
from .Cache_manager import (
    check_cache_exists,
    get_path_from_key,
    run_cleanup_routine,
    setup_cache_directory,
    stream_from_path as stream_from_cache,
    touch_cache_file,
)
from .Extractor import fetch_and_parse
from .Tts import TTSEngine, TTSEngineError, create_tts_engine

# Định nghĩa __all__ là một best practice trong Python.
# Nó khai báo rõ những tên nào sẽ được import khi có lệnh `from modules import *`
# và giúp các công cụ phân tích code hiểu rõ giao diện của package.
# Danh sách được sắp xếp theo thứ tự alphabet.
__all__ = [
    "TTSEngine",
    "TTSEngineError",
    "check_cache_exists",
    "create_tts_engine",
    "fetch_and_parse",
    "get_path_from_key",
    "run_cleanup_routine",
    "setup_cache_directory",
    "stream_from_cache",
    "touch_cache_file",
]