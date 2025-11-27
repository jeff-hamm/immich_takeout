import time
import argparse
from playwright.sync_api import sync_playwright

def run():
    parser = argparse.ArgumentParser(description='Google Takeout Backup Script')
    parser.add_argument('--headful', action='store_true', help='Run in headful mode (useful for login)')
    args = parser.parse_args()

    with sync_playwright() as p:
        # Use a persistent context to save login session
        user_data_dir = 'user_data'
        print(f"Launching browser with user data dir: {user_data_dir}")
        # Headless by default unless --headful is passed
        context = p.chromium.launch_persistent_context(user_data_dir, headless=not args.headful)
        
        page = context.pages[0] if context.pages else context.new_page()
        
        print("Navigating to Google Takeout...")
        page.goto("https://takeout.google.com/")
        
        # Check if we are logged in
        if "accounts.google.com" in page.url:
            print("Login required.")
            if args.headful:
                print("Please log in to your Google account in the browser window.")
                # Wait for navigation to takeout page
                try:
                    page.wait_for_url("https://takeout.google.com/**", timeout=0) # Wait indefinitely for user to login
                    print("Login detected. Proceeding...")
                except Exception as e:
                    print(f"Error waiting for login: {e}")
                    return
            else:
                print("Cannot log in while in headless mode. Please run with --headful first to establish a session.")
                context.close()
                return

        print("On Takeout page.")
        
        # TODO: Implement selection logic here
        # For now, we just pause to let the user see it works
        
        if args.headful:
            print("Script finished. Press Enter in terminal to close browser...")
            input()
        
        context.close()

if __name__ == "__main__":
    run()
