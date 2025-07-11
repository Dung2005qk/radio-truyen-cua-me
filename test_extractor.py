# test_extractor.py
import logging
from modules.Extractor import fetch_and_parse

# Cấu hình logging để thấy được thông báo
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(module)s - %(message)s')

# --- CHỌN MỘT URL ĐỂ TEST ---
# Bắt đầu với một trang bạn nghĩ là "dễ" nhất, ví dụ truyenfull.vn
# (Hãy đảm bảo URL này vẫn tồn tại)
# TEST_URL = "https://truyenfull.vn/vo-luyen-dinh-phong/chuong-1/"
TEST_URL = "https://truyenfull.vision/my-dung-su-xuyen-qua-lam-nong-phu-lam-giau-nuoi-con/chuong-1/" # Một trang khác để thử
# TEST_URL = "https://dtruyen.vn/kiem-lai-phong-than/chuong-1/"

def run_test():
    print(f"--- Bắt đầu kiểm tra với URL: {TEST_URL} ---")
    
    # Gọi trực tiếp hàm fetch_and_parse
    metadata = fetch_and_parse(TEST_URL)
    
    print("\n--- Kết quả trả về ---")
    if metadata:
        print(f"  Tiêu đề: {metadata.get('title')}")
        print(f"  Link sau: {metadata.get('next_url')}")
        print(f"  Link trước: {metadata.get('prev_url')}")
        # In ra 300 ký tự đầu tiên của nội dung để kiểm tra
        content_preview = metadata.get('content', '')[:300]
        print(f"  Nội dung (preview):\n---\n{content_preview}...\n---")
    else:
        print("  Hàm fetch_and_parse trả về None. Không thể lấy dữ liệu.")
        
    print("\n--- Kiểm tra hoàn tất ---")

if __name__ == '__main__':
    run_test()