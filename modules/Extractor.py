import logging
import json
import re
import os
import cloudscraper
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import requests

# --- Module Level Configuration & Initialization ---

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(module)s - %(message)s')

SESSION = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'mobile': False
    }
)
SESSION.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'
})
REQUEST_TIMEOUT = 20  # seconds

# Refined regex patterns for post-processing to be more specific and avoid false positives
TEXT_CLEANUP_PATTERNS = [
    re.compile(r'^\s*Nguồn:.*', re.IGNORECASE | re.MULTILINE),
    re.compile(r'^\s*(Text được lấy tại|Đọc truyện tại|Tìm truyện tại).*', re.IGNORECASE | re.MULTILINE),
    re.compile(r'^\s*([=-]|\*|_|—|–){3,}\s*$', re.MULTILINE),  # Lines with only separators
    re.compile(r'^\s*(o o o)\s*$', re.IGNORECASE | re.MULTILINE),
    re.compile(r'\b(truyenfull|sstruyen|tangthuvien|metruyencv)\.(vn|com)\b', re.IGNORECASE),
]

SITE_CONFIG = {}
REQUIRED_CONFIG_KEYS = {'title', 'content', 'next_url', 'prev_url'}

def load_configs():
    """
    Loads and validates site configurations from an external JSON file.
    Only valid configurations are loaded into the application.
    """
    global SITE_CONFIG
    config_path = os.path.join(os.path.dirname(__file__), 'selectors.json')
    validated_configs = {}
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            raw_configs = json.load(f)
    except FileNotFoundError:
        logging.critical(f"Configuration file not found at {config_path}. Extractor will not function.")
        return
    except json.JSONDecodeError:
        logging.critical(f"Error decoding JSON from {config_path}. Please check for syntax errors.")
        return

    for domain, config in raw_configs.items():
        missing_keys = REQUIRED_CONFIG_KEYS - set(config.keys())
        if not missing_keys:
            validated_configs[domain] = config
        else:
            logging.error(f"Configuration for domain '{domain}' is invalid. Missing required keys: {missing_keys}")
            
    SITE_CONFIG = validated_configs
    logging.info(f"Successfully loaded and validated {len(SITE_CONFIG)} site configurations.")


# Load configurations when the module is imported
load_configs()


def fetch_and_parse(url: str) -> dict | None:
    """
    Fetches, parses, and cleans a story chapter from a supported URL, ensuring high data quality.

    This function implements a robust multi-step process:
    1. Fetches HTML content using a persistent session.
    2. Extracts critical data (title, content block, nav links) first.
    3. Cleans unwanted HTML elements from within the content block.
    4. Refines the extracted text using regex to remove clutter and repeated titles.

    Args:
        url: The URL of the chapter to parse.

    Returns:
        A dictionary containing clean data on success, or None on failure.
    """
    try:
        parsed_url = urlparse(url)
        domain = parsed_url.netloc.replace('www.', '')
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        
        if domain not in SITE_CONFIG:
            logging.warning(f"Domain not supported: {domain}")
            return None
    except Exception as e:
        logging.error(f"Invalid URL provided: {url}. Error: {e}")
        return None

    config = SITE_CONFIG[domain]
    logging.info(f"Using config for domain: {domain}")

    try:
        response = SESSION.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        #with open("debug_output.html", "w", encoding="utf-8") as f:
        #   f.write(soup.prettify())
    except (requests.exceptions.RequestException, cloudscraper.exceptions.CloudflareException) as e:
        logging.error(f"Network or Cloudflare error fetching {url}: {e}")
        return None

    try:
        def get_absolute_url(selector: str) -> str | None:
            element = soup.select_one(selector)
            if not element:
                return None
            
            href = element.get('href')
            if not href or href.strip() == '#' or href.lower().strip().startswith('javascript:'):
                return None
                
            return urljoin(base_url, href.strip())

        # STEP 1: EXTRACT all required elements before any modification
        title_element = soup.select_one(config['title'])
        content_element = soup.select_one(config['content'])

        if not content_element:
            logging.error(f"Critical failure: Content selector '{config['content']}' not found for {url}.")
            return None

        title = title_element.get_text(strip=True) if title_element else "Không rõ tiêu đề"
        next_url = get_absolute_url(config['next_url'])
        prev_url = get_absolute_url(config['prev_url'])

        # STEP 2: CLEAN UP unwanted HTML tags *within* the content block
        if config.get('junk_selectors'):
            for selector in config['junk_selectors']:
                for element in content_element.select(selector):
                    element.decompose()

        # STEP 3: REFINE the extracted text
        content_text = content_element.get_text(separator='\n', strip=True)

        # 3.1: Remove repeated title from the beginning of the content
        if title != "Không rõ tiêu đề":
            # Use replace with count=1 to only remove the first occurrence
            content_text = content_text.replace(title, '', 1)

        # 3.2: Apply regex patterns to remove junk text
        for pattern in TEXT_CLEANUP_PATTERNS:
            content_text = pattern.sub('', content_text)

        # 3.3: Normalize whitespace
        content_text = re.sub(r'\n{3,}', '\n\n', content_text).strip()

        return {
            'title': title,
            'content': content_text,
            'next_url': next_url,
            'prev_url': prev_url
        }
    except Exception as e:
        logging.error(f"Parsing error for {url}, possibly due to layout change. Error: {e}", exc_info=True)
        return None