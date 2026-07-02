import os
import re
import sys
import json
import time
import requests
import urllib.parse
from bs4 import BeautifulSoup
import pyarabic.araby as araby
from progress.bar import IncrementalBar

# Configuration
BASE_URL = "https://dorar.net"
START_URL = "https://dorar.net/tafseer"
DELAY = 0.2  # delay in seconds
RETRY_DELAY = 5
MAX_RETRIES = 3
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROGRESS_FILE = os.path.join(PROJECT_DIR, "progress.json")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'ar,en-US;q=0.9,en;q=0.8',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
}

def extract_verse_range(soup):
    card = soup.find('div', class_='card-body amiri')
    if not card:
        card = soup.find(class_='amiri_custom_content')
    if not card:
        return None
        
    pattern = re.compile(r'(?:الآيات|الآية|الآيتان|الآيتين)\s*[:]?\s*[\(]?\s*(\d+)\s*(?:[-–—]\s*(\d+))?\s*[\)]?')
    
    # Traverse tags to find the verse range heading
    for tag in card.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'b', 'strong', 'p', 'div']):
        text = tag.get_text(strip=True)
        # Skip section headings to avoid false matches
        if any(w in text for w in ['تفسير', 'بلاغة', 'إعراب', 'غريب', 'فوائد', 'الفوائد', 'معنى', 'المعنى']):
            continue
            
        match = pattern.search(text)
        if match:
            start = match.group(1)
            end = match.group(2)
            if end is None:
                end = start
            return f"{start}-{end}"
            
    return None

def is_next_page_same_surah(current_surah_num, next_path):
    parsed = urllib.parse.urlparse(next_path)
    path = parsed.path.strip('/')
    parts = path.split('/')
    if len(parts) >= 2 and parts[0] == 'tafseer':
        try:
            next_surah_num = int(parts[1])
            if next_surah_num == current_surah_num:
                return True
        except ValueError:
            pass
    return False

def fetch_surah_list():
    print("Fetching Surah list from Dorar.net...")
    try:
        response = requests.get(START_URL, headers=HEADERS, timeout=15)
        if response.status_code != 200:
            print(f"Error fetching index page: {response.status_code}")
            sys.exit(1)
            
        soup = BeautifulSoup(response.text, 'html.parser')
        surahs = []
        pattern = re.compile(r'^/tafseer/(\d+)$')
        for anchor in soup.find_all('a', href=True):
            href = anchor['href']
            match = pattern.match(href)
            if match:
                surah_num = int(match.group(1))
                name_with_tashkeel = anchor.get_text(strip=True)
                name_clean = araby.strip_tashkeel(name_with_tashkeel)
                name_clean = re.sub(r'[\/\\:\*\?"<>\|]', '', name_clean)
                name_clean = re.sub(r'\s+', ' ', name_clean).strip()
                surahs.append({
                    'num': surah_num,
                    'name': name_clean,
                    'path': href
                })
        
        # Sort and de-duplicate
        surahs.sort(key=lambda x: x['num'])
        seen = set()
        unique_surahs = []
        for s in surahs:
            if s['num'] not in seen:
                seen.add(s['num'])
                unique_surahs.append(s)
                
        return unique_surahs
    except requests.exceptions.RequestException as exc:
        print(f"Failed to fetch Surah list: {exc}")
        sys.exit(1)

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return set(data.get('completed_surahs', []))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Warning: failed to read progress file '{PROGRESS_FILE}': {exc}")
            return set()
    return set()

def save_progress(completed_set):
    try:
        with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
            json.dump({'completed_surahs': list(completed_set)}, f, ensure_ascii=False, indent=2)
    except OSError as exc:
        print(f"Failed to save progress: {exc}")


def fetch_page(url):
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
        except requests.exceptions.RequestException as exc:
            last_error = exc
            print(f"\nRequest failed ({attempt}/{MAX_RETRIES}) for {url}: {exc}")
            time.sleep(RETRY_DELAY)
            continue

        if response.status_code == 404:
            return None
        if response.status_code == 200:
            return response

        last_error = RuntimeError(f"HTTP {response.status_code}")
        print(f"\nUnexpected status ({attempt}/{MAX_RETRIES}) for {url}: {response.status_code}")
        time.sleep(RETRY_DELAY)

    raise RuntimeError(f"Failed to fetch {url} after {MAX_RETRIES} attempts: {last_error}")


def find_next_page_path(soup):
    for anchor in soup.find_all('a', href=True):
        text = anchor.get_text(strip=True)
        if 'التالي' in text:
            return anchor['href']
    return None


def page_filename(page_num, soup):
    if page_num == 0:
        return "المقدمة.html"

    verse_range = extract_verse_range(soup)
    return f"{verse_range}.html" if verse_range else f"صفحة-{page_num}.html"


def write_html_file(surah_dir, filename, html):
    file_path = os.path.join(surah_dir, filename)
    with open(file_path, 'w', encoding='utf-8') as output_file:
        output_file.write(html)

def download_surah(surah):
    surah_num = surah['num']
    surah_name = surah['name']
    
    folder_name = f"{surah_num} {surah_name}"
    surah_dir = os.path.join(PROJECT_DIR, folder_name)
    os.makedirs(surah_dir, exist_ok=True)
    
    current_path = f"/tafseer/{surah_num}"
    page_num = 0
    
    while current_path:
        time.sleep(DELAY)
        url = urllib.parse.urljoin(BASE_URL, current_path)
        response = fetch_page(url)
        if response is None:
            break

        soup = BeautifulSoup(response.text, 'html.parser')
        next_path = find_next_page_path(soup)
        write_html_file(surah_dir, page_filename(page_num, soup), response.text)

        if next_path and is_next_page_same_surah(surah_num, next_path):
            current_path = next_path
            page_num += 1
        else:
            current_path = None

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    
    surahs = fetch_surah_list()
    if not surahs:
        print("No Surahs found!")
        return
        
    completed_surahs = load_progress()
    to_process = [s for s in surahs if s['num'] not in completed_surahs]
    
    print(f"Total Surahs: {len(surahs)}")
    print(f"Already completed: {len(completed_surahs)}")
    print(f"Remaining to process: {len(to_process)}")
    
    if not to_process:
        print("All Surahs downloaded successfully!")
        return
        
    bar = IncrementalBar('Progress', max=len(surahs))
    bar.goto(len(completed_surahs))
    
    for surah in to_process:
        print(f"\rDownloading Surah {surah['num']}: {surah['name']}...", end='', flush=True)
        try:
            download_surah(surah)
        except RuntimeError as exc:
            print(f"\nFailed to download Surah {surah['num']} ({surah['name']}): {exc}")
            continue

        completed_surahs.add(surah['num'])
        save_progress(completed_surahs)
        bar.next()
        
    bar.finish()
    print("\nDownload completed successfully!")

if __name__ == '__main__':
    main()
