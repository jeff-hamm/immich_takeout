#!/usr/bin/env python3
"""
Download Google Takeout files using browser cookies
Usage: python3 download_takeout.py <takeout_url> <cookies_file>
"""
import sys
import os
import re
import requests
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import http.cookiejar as cookielib

DOWNLOAD_DIR = Path("/mnt/user/jumpdrive/gdrive/Takeout")


def load_cookies_from_file(cookies_file):
    """Load cookies from Netscape format cookies.txt file."""
    cookie_jar = cookielib.MozillaCookieJar(cookies_file)
    cookie_jar.load(ignore_discard=True, ignore_expires=True)
    return cookie_jar


def load_cookies_from_string(cookie_string):
    """Parse cookie string from browser dev tools into a cookie jar."""
    cookie_jar = requests.cookies.RequestsCookieJar()
    
    # Parse cookie string format: "name1=value1; name2=value2; ..."
    for cookie in cookie_string.split(';'):
        cookie = cookie.strip()
        if '=' in cookie:
            name, value = cookie.split('=', 1)
            cookie_jar.set(name.strip(), value.strip(), domain='.google.com', path='/')
    
    return cookie_jar


def get_takeout_links(takeout_url, cookies):
    """Fetch the Takeout page and extract all download links."""
    print(f"[INFO] Fetching Takeout page: {takeout_url}")
    
    session = requests.Session()
    session.cookies = cookies
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    response = session.get(takeout_url, headers=headers)
    
    if response.status_code != 200:
        print(f"[ERROR] Failed to fetch page: {response.status_code}")
        return []
    
    # Extract download links - Google Takeout uses specific patterns
    # Look for links containing 'takeout-download' or direct download URLs
    download_pattern = r'https://[^"\']+takeout-download[^"\']+'
    links = re.findall(download_pattern, response.text)
    
    # Also try to find download URLs in a different format
    if not links:
        # Try alternative pattern for direct download links
        download_pattern2 = r'https://doc-[^"\']+\.zip[^"\']+'
        links = re.findall(download_pattern2, response.text)
    
    # Clean up links (remove HTML entities, etc.)
    cleaned_links = []
    for link in links:
        link = link.replace('&amp;', '&')
        link = link.split('"')[0].split("'")[0]
        if link not in cleaned_links:
            cleaned_links.append(link)
    
    print(f"[INFO] Found {len(cleaned_links)} download link(s)")
    return cleaned_links


def download_file(url, cookies, destination):
    """Download a file from URL using cookies."""
    filename = destination.name
    
    if destination.exists():
        print(f"[INFO] File already exists, skipping: {filename}")
        return True
    
    print(f"[INFO] Downloading: {filename}")
    
    session = requests.Session()
    session.cookies = cookies
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        # Stream the download
        response = session.get(url, headers=headers, stream=True, timeout=30)
        response.raise_for_status()
        
        # Get file size if available
        total_size = int(response.headers.get('content-length', 0))
        total_size_mb = total_size / (1024 * 1024)
        
        print(f"[INFO] Size: {total_size_mb:.2f} MB")
        
        # Download with progress
        downloaded = 0
        with open(destination, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        progress = (downloaded / total_size) * 100
                        print(f"\r[INFO] Progress: {progress:.1f}%", end='', flush=True)
        
        print(f"\n[INFO] Downloaded: {filename}")
        return True
        
    except Exception as e:
        print(f"\n[ERROR] Failed to download {filename}: {e}")
        if destination.exists():
            destination.unlink()
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 download_takeout.py <takeout_url> [cookies_file]")
        print("\nExample:")
        print("  python3 download_takeout.py 'https://takeout.google.com/manage/...' cookies.txt")
        print("  python3 download_takeout.py 'https://takeout.google.com/manage/...'")
        print("\nIf no cookies file is provided, you'll be prompted to paste cookies from browser dev tools.")
        sys.exit(1)
    
    takeout_url = sys.argv[1]
    cookies_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    
    # Load cookies from file or prompt for input
    if cookies_file and os.path.exists(cookies_file):
        print(f"[INFO] Loading cookies from: {cookies_file}")
        cookies = load_cookies_from_file(cookies_file)
    else:
        if cookies_file:
            print(f"[WARNING] Cookies file not found: {cookies_file}")
        print("[INFO] Please paste your cookie string from browser dev tools")
        print("[INFO] (Go to Dev Tools -> Application/Storage -> Cookies -> copy all as 'name=value; name=value; ...')")
        print("[INFO] Or right-click on a request in Network tab -> Copy -> Copy cookies")
        print("\nPaste cookies and press Enter:")
        cookie_string = input().strip()
        
        if not cookie_string:
            print("[ERROR] No cookies provided!")
            sys.exit(1)
        
        print(f"[INFO] Loading cookies from input")
        cookies = load_cookies_from_string(cookie_string)
    
    print(f"[INFO] Fetching download links...")
    links = get_takeout_links(takeout_url, cookies)
    
    if not links:
        print("[ERROR] No download links found!")
        print("[INFO] The page might require different parsing or the cookies might be expired.")
        sys.exit(1)
    
    print(f"\n[INFO] Starting download of {len(links)} file(s) to {DOWNLOAD_DIR}")
    print("=" * 60)
    
    success_count = 0
    for i, link in enumerate(links, 1):
        print(f"\n[INFO] File {i}/{len(links)}")
        
        # Try to extract filename from URL or use a numbered pattern
        try:
            # Look for filename in URL
            if 'takeout-' in link:
                filename_match = re.search(r'(takeout-[^&?/]+\.zip)', link)
                if filename_match:
                    filename = filename_match.group(1)
                else:
                    filename = f"takeout-download-{i:03d}.zip"
            else:
                filename = f"takeout-download-{i:03d}.zip"
        except:
            filename = f"takeout-download-{i:03d}.zip"
        
        destination = DOWNLOAD_DIR / filename
        
        if download_file(link, cookies, destination):
            success_count += 1
    
    print("\n" + "=" * 60)
    print(f"[INFO] Download complete: {success_count}/{len(links)} files downloaded")
    
    if success_count < len(links):
        print("[WARNING] Some files failed to download. Check the logs above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
