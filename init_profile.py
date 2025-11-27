#!/usr/bin/env python3
"""
Initialize Google auth profile for Takeout automation
Run this ONCE to create a profile with Google authentication
"""
import os
from playwright.sync_api import sync_playwright

PROFILE_DIR = os.getenv("BROWSER_PROFILE", "/tmp/takeout-profile")

def main():
    print(f"[INFO] Initializing Google auth profile")
    print(f"[INFO] Profile directory: {PROFILE_DIR}")
    print(f"[INFO] Opening browser for login...")
    
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=False,  # Always visible for login
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox'
            ]
        )
        
        page = context.pages[0] if context.pages else context.new_page()
        
        print("\n" + "="*60)
        print("INSTRUCTIONS:")
        print("1. The browser window should now be open")
        print("2. Log in to your Google account")
        print("3. Navigate to https://takeout.google.com")
        print("4. Make sure you can see the Takeout page")
        print("5. Press Enter in this terminal when done")
        print("="*60 + "\n")
        
        page.goto("https://takeout.google.com")
        
        input("Press Enter once you're logged in and can see takeout.google.com...")
        
        # Verify login
        page.goto("https://takeout.google.com")
        page.wait_for_load_state("networkidle")
        
        if "accounts.google.com" in page.url:
            print("[ERROR] Still on login page. Profile not saved correctly.")
            context.close()
            return False
        
        print("[SUCCESS] Profile initialized successfully!")
        print(f"[INFO] Profile saved to: {PROFILE_DIR}")
        print(f"\n[INFO] You can now run:")
        print(f"  BROWSER_PROFILE='{PROFILE_DIR}' python3 automated_takeout.py")
        
        context.close()
        return True

if __name__ == "__main__":
    main()
