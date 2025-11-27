#!/usr/bin/env python3
"""
Check Google Takeout login status using Playwright
Returns exit code 0 if logged in, exit code 1 if login required
"""
import os
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

BROWSER_PROFILE = os.getenv("BROWSER_PROFILE", "/home/kasm-user/.config/google-chrome")
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
SLEEP_MULTIPLIER = float(os.getenv("SLEEP_MULTIPLIER", "0.5"))
PROTECTED_PAGE_URL = os.getenv("PROTECTED_PAGE_URL", "https://takeout.google.com")
LOGIN_REDIRECT_URL = os.getenv("LOGIN_REDIRECT_URL", "accounts.google.com")
LOGIN_PAGE_LOCATOR = os.getenv("LOGIN_PAGE_LOCATOR", "input[type=\"email\"]")


def check_login():
    """Check if user is logged in to Google Takeout."""
    profile_dir = BROWSER_PROFILE
    
    # Check if profile exists
    if not os.path.exists(profile_dir):
        print(f"[ERROR] Browser profile not found: {profile_dir}")
        return False
    
    with sync_playwright() as p:
        print(f"[INFO] Using browser profile: {profile_dir}")
        print(f"[INFO] Checking login status...")
        
        # Launch browser with persistent context
        context = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=HEADLESS,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox'
            ]
        )
        page = context.pages[0] if context.pages else context.new_page()
        
        # Check if already logged in by visiting protected page
        page.goto(PROTECTED_PAGE_URL)
        page.wait_for_load_state("networkidle")
        time.sleep(2 * SLEEP_MULTIPLIER)
        
        # Check if we're on the sign-in page
        is_logged_in = True
        if LOGIN_REDIRECT_URL in page.url or page.locator(LOGIN_PAGE_LOCATOR).count() > 0:
            is_logged_in = False
        
        context.close()
        return is_logged_in


def main():
    if check_login():
        print(f"[SUCCESS] User is already logged in to {PROTECTED_PAGE_URL}!")
        sys.exit(0)
    else:
        print(f"[INFO] Login required for {PROTECTED_PAGE_URL}!")
        sys.exit(1)


if __name__ == "__main__":
    main()
