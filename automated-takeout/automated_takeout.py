#!/usr/bin/env python3
"""
Automated Google Takeout creator using Playwright
Creates album exports and saves them to Google Drive
Uses album_state.yml to track which albums to export and how to group them
"""
import os
import sys
import time
import re
from datetime import datetime
from pathlib import Path
import yaml
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

BROWSER_PROFILE = os.getenv("BROWSER_PROFILE", "/browser-profile")
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
SERVER_IP = os.getenv("SERVER_IP", "127.0.0.1")
VNC_PORT = os.getenv("VNC_PORT", "6901")
TAKEOUT_URL = os.getenv("TAKEOUT_URL", "https://takeout.google.com/settings/takeout/custom/photos")
SLEEP_MULTIPLIER = float(os.getenv("SLEEP_MULTIPLIER", "1"))
STATE_FILE = Path(__file__).parent / "album_state.yml"


def load_album_state():
    """Load album state from YAML file."""
    if not STATE_FILE.exists():
        print(f"[ERROR] State file not found: {STATE_FILE}")
        sys.exit(1)
    
    with open(STATE_FILE, 'r') as f:
        state = yaml.safe_load(f)
    
    return state


def save_album_state(state):
    """Save album state to YAML file."""
    with open(STATE_FILE, 'w') as f:
        yaml.dump(state, f, default_flow_style=False, sort_keys=False)


def is_photos_from_year(album_name):
    """Check if album name matches 'Photos from YYYY' pattern."""
    return bool(re.match(r'^Photos from \d{4}$', album_name))


def get_year_from_album_name(album_name):
    """Extract year from 'Photos from YYYY' album name."""
    match = re.match(r'^Photos from (\d{4})$', album_name)
    return int(match.group(1)) if match else None


def update_album_in_state(state, album_name, album_list_from_page):
    """
    Update or add album to state file.
    Returns True if album was added/updated, False if skipped.
    """
    current_year = datetime.now().year
    
    # Check if album exists in state
    album_entry = next((a for a in state['albums'] if a['name'] == album_name), None)
    
    if album_entry:
        return True  # Album already exists
    
    # Album not in state - add it
    print(f"[INFO] New album found: {album_name}")
    
    # Determine if large and frequency
    is_large = False
    frequency = "Export once"
    
    if is_photos_from_year(album_name):
        is_large = True
        year = get_year_from_album_name(album_name)
        if year == current_year:
            frequency = "Export every 2 months for 1 year"
    
    # Create new album entry
    new_album = {
        'name': album_name,
        'last_export_date': None,
        'is_large': is_large,
        'export_frequency': frequency
    }
    
    state['albums'].append(new_album)
    
    # Add to large_albums list if applicable
    if is_large and album_name not in state['large_albums']:
        state['large_albums'].append(album_name)
    
    save_album_state(state)
    return True


def get_albums_to_export(state):
    """
    Organize albums into groups for export.
    Returns: (large_albums, small_albums_batch)
    """
    large_albums = []
    small_albums = []
    
    for album in state['albums']:
        album_name = album['name']
        is_large = album['is_large']
        
        # Check if export is needed based on last_export_date and frequency
        # For now, we'll export all albums that haven't been exported
        if album['last_export_date'] is None:
            if is_large:
                large_albums.append(album_name)
            else:
                small_albums.append(album_name)
    
    return large_albums, small_albums


def deselect_all_albums(page):
    """Click 'Deselect all' button to uncheck all albums."""
    try:
        # Close any overlays or modals that might be blocking
        try:
            page.keyboard.press("Escape")
            time.sleep(0.5 * SLEEP_MULTIPLIER)
        except:
            pass
        
        deselect_btn = page.locator('button[aria-label="Deselect all"]').first
        if deselect_btn.is_visible():
            # Try force click to bypass intercepting elements
            deselect_btn.click(force=True)
            time.sleep(1 * SLEEP_MULTIPLIER)
            print("[INFO] Deselected all albums")
    except Exception as e:
        print(f"[WARNING] Could not deselect all: {e}")


def select_albums(modal, album_names):
    """Select specific albums by their names within a modal."""
    # First, deselect all albums by clicking the "Deselect all" button
    try:
        deselect_btn = modal.locator('button:has-text("Deselect all")').first
        if deselect_btn.count() > 0:
            deselect_btn.click(force=True)
            time.sleep(1 * SLEEP_MULTIPLIER)
            print("[INFO] Deselected all albums")
    except Exception as e:
        print(f"[WARNING] Could not deselect all: {e}")
    
    selected_count = 0
    
    for album_name in album_names:
        try:
            # Checkboxes have name attribute matching album name (may have leading/trailing space)
            # Try exact match first, then with trimmed name
            checkbox = None
            
            # Try exact match
            if modal.locator(f'input[name="{album_name}"]').count() > 0:
                checkbox = modal.locator(f'input[name="{album_name}"]').first
            # Try with leading space
            elif modal.locator(f'input[name=" {album_name}"]').count() > 0:
                checkbox = modal.locator(f'input[name=" {album_name}"]').first
            # Try with trailing space  
            elif modal.locator(f'input[name="{album_name} "]').count() > 0:
                checkbox = modal.locator(f'input[name="{album_name} "]').first
            # Try with both
            elif modal.locator(f'input[name=" {album_name} "]').count() > 0:
                checkbox = modal.locator(f'input[name=" {album_name} "]').first
            
            if checkbox:
                if not checkbox.is_checked():
                    checkbox.check(force=True)
                    time.sleep(0.5 * SLEEP_MULTIPLIER)
                    selected_count += 1
                    print(f"[INFO] Selected: {album_name}")
                else:
                    print(f"[INFO] Already selected: {album_name}")
            else:
                print(f"[WARNING] Album not found: {album_name}")
        except Exception as e:
            print(f"[ERROR] Failed to select {album_name}: {e}")
    
    print(f"[INFO] Selected {selected_count}/{len(album_names)} albums")
    return selected_count


def create_album_export(page, album_names, export_name):
    """Create a Takeout export for specific albums."""
    print(f"\n[INFO] Creating export: {export_name}")
    print(f"[INFO] Albums: {len(album_names)}")
    
    try:
        # Go to Google Takeout page
        page.goto(TAKEOUT_URL)
        page.wait_for_load_state("domcontentloaded")
        time.sleep(2 * SLEEP_MULTIPLIER)
        
        # First, deselect all Google services
        print("[INFO] Deselecting all Google services...")
        try:
            deselect_btn = page.locator('button[aria-label="Deselect all"]').first
            if deselect_btn.is_visible():
                deselect_btn.click(force=True)
                time.sleep(1 * SLEEP_MULTIPLIER)
        except Exception as e:
            print(f"[WARNING] Could not deselect all services: {e}")
        
        # Select only Google Photos
        print("[INFO] Selecting Google Photos service...")
        try:
            photos_checkbox = page.locator('input[name="Google Photos"]').first
            if not photos_checkbox.is_checked():
                photos_checkbox.check(force=True)
                time.sleep(1 * SLEEP_MULTIPLIER)
        except Exception as e:
            print(f"[ERROR] Could not select Google Photos: {e}")
            return False
        
        # Now click "All photo albums included" or similar text to configure which albums
        print("[INFO] Configuring album selection...")
        
        # Debug: Show what buttons/text we can find related to photos
        try:
            # Look for any element containing "photo" or "album"
            photo_elements = page.locator('text=/photo|album/i').all()
            print(f"[DEBUG] Found {len(photo_elements)} elements with 'photo' or 'album'")
            for i, elem in enumerate(photo_elements[:5]):
                try:
                    text = elem.inner_text()[:50]  # First 50 chars
                    print(f"  {i+1}. {text}")
                except:
                    pass
        except Exception as e:
            print(f"[DEBUG] Error listing photo elements: {e}")
        
        # Try multiple possible button texts
        clicked = False
        for button_text in ["All photo albums included", "Multiple formats", "All photos", "Include all"]:
            try:
                button = page.locator(f'text="{button_text}"').first
                if button.count() > 0:
                    print(f"[DEBUG] Found button: {button_text}")
                    button.click()
                    time.sleep(2 * SLEEP_MULTIPLIER)
                    clicked = True
                    break
            except:
                pass
        
        if not clicked:
            print("[ERROR] Could not find album configuration button")
            return False
        
        # Wait for the modal with title "Google Photos content options"
        print("[DEBUG] Waiting for album selection modal...")
        try:
            page.wait_for_selector('div[role="dialog"]:has-text("Google Photos content options")', timeout=10000)
            print("[DEBUG] Modal appeared, waiting for checkboxes to load...")
            # Wait for album checkboxes to be present in the modal
            page.wait_for_selector('div[role="dialog"] input[type="checkbox"][name]', timeout=10000)
            time.sleep(2 * SLEEP_MULTIPLIER)  # Give extra time for all albums to render
            print("[DEBUG] Checkboxes loaded")
        except Exception as e:
            print(f"[WARNING] Could not detect modal or checkboxes: {e}")
        
        # Get the modal element
        modal = page.locator('div[role="dialog"]').first
        
        # Debug: List all available albums in the modal
        try:
            all_checkboxes = modal.locator('input[type="checkbox"][name]').all()
            print(f"[DEBUG] Found {len(all_checkboxes)} album checkboxes in modal")
            if len(all_checkboxes) > 0:
                print("[DEBUG] First 10 album names:")
                for i, cb in enumerate(all_checkboxes[:10]):
                    name = cb.get_attribute('name')
                    print(f"  {i+1}. '{name}'")
        except Exception as e:
            print(f"[DEBUG] Could not list albums: {e}")
        
        # Select specific albums
        selected = select_albums(modal, album_names)
        
        if selected == 0:
            print(f"[ERROR] No albums were selected for {export_name}")
            return False
        
        # Click OK to confirm selection
        print("[INFO] Confirming album selection...")
        # Scroll modal to bottom to make OK/Cancel buttons visible
        try:
            modal_content = page.locator('div[role="dialog"]:visible').first
            modal_content.evaluate('el => el.scrollTo(0, el.scrollHeight)')
            time.sleep(1 * SLEEP_MULTIPLIER)
        except Exception as e:
            print(f"[DEBUG] Could not scroll modal: {e}")
        
        # Find OK button - it's a div[role="button"] containing OK span, not a <button> element
        ok_button = page.locator('div[role="dialog"]:visible div[role="button"]:has(span:text-is("OK"))')
        print(f"[DEBUG] Found {ok_button.count()} OK buttons after scroll")
        ok_button.last.click()
        time.sleep(2 * SLEEP_MULTIPLIER)
        
        # Click "Next step"
        print("[INFO] Proceeding to delivery options...")
        page.locator('button:has-text("Next step")').first.click()
        page.wait_for_load_state("domcontentloaded", timeout=60000)
        time.sleep(2 * SLEEP_MULTIPLIER)
        
        # Select "Add to Drive" - Drive is the default delivery method, so skip if not available
        print("[INFO] Checking delivery method...")
        add_to_drive_radio = page.locator('input[value="DRIVE"]')
        if add_to_drive_radio.count() > 0:
            print("[DEBUG] Found DRIVE radio input, selecting...")
            if not add_to_drive_radio.first.is_checked():
                add_to_drive_radio.first.click()
                time.sleep(1 * SLEEP_MULTIPLIER)
        else:
            print("[DEBUG] No DRIVE radio input found, assuming Drive is default")
        
        # Set export frequency to "Export once"
        export_once = page.locator('text="Export once"').first
        if export_once.is_visible():
            export_once.click()
            time.sleep(1 * SLEEP_MULTIPLIER)
        
        # Set file size (50GB max recommended)
        try:
            size_dropdown = page.locator('select').filter(has_text="50 GB").first
            if size_dropdown.is_visible():
                size_dropdown.select_option("50")
                time.sleep(1 * SLEEP_MULTIPLIER)
        except:
            print("[WARNING] Could not set file size, using default")
        
        # Create export
        print(f"[INFO] Creating export '{export_name}'...")
        page.locator('button:has-text("Create export")').first.click()
        time.sleep(2 * SLEEP_MULTIPLIER)
        
        # Wait for confirmation - check for multiple possible messages
        print("[DEBUG] Waiting for export confirmation...")
        try:
            page.wait_for_selector('text=/export is being created|creating a copy/i', timeout=10000)
            print(f"[SUCCESS] Export '{export_name}' created successfully!")
            return True
        except:
            print("[DEBUG] Standard confirmation not found, checking page content...")
            # If we're back at the main Takeout page with services listed, export was likely created
            if page.locator('text=/manage your exports/i').count() > 0 or page.locator('text=/Google Photos/i').count() > 0:
                print(f"[SUCCESS] Export '{export_name}' appears to have been created!")
                return True
            raise
        
    except PlaywrightTimeout as e:
        print(f"[ERROR] Failed to create export '{export_name}': {e}")
        return False
    except Exception as e:
        print(f"[ERROR] Unexpected error for '{export_name}': {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print(f"[INFO] Starting automated Takeout creation")
    
    # Load album state
    state = load_album_state()
    print(f"[INFO] Loaded {len(state['albums'])} albums from state file")
    
    # Get albums to export
    large_albums, small_albums = get_albums_to_export(state)
    
    print(f"\n[INFO] Albums to export:")
    print(f"  - Large albums (individual exports): {len(large_albums)}")
    print(f"  - Small albums (combined export): {len(small_albums)}")
    
    if len(large_albums) == 0 and len(small_albums) == 0:
        print("[INFO] No albums need to be exported!")
        return
    
    # Use gphotos-downloader Chrome profile
    profile_dir = BROWSER_PROFILE
    
    # Check if profile exists
    if not os.path.exists(profile_dir):
        print(f"[ERROR] Browser profile not found: {profile_dir}")
        print(f"[INFO] Make sure the gphotos-downloader Chrome service is set up")
        sys.exit(1)
    
    with sync_playwright() as p:
        print(f"\n[INFO] Using browser profile: {profile_dir}")
        print(f"[INFO] Headless mode: {HEADLESS}")
        
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
        
        # Check if already logged in by visiting Takeout
        page.goto(TAKEOUT_URL, timeout=60000)
        page.wait_for_load_state("domcontentloaded")
        time.sleep(2 * SLEEP_MULTIPLIER)
        
        # Check if we're on the sign-in page
        if "accounts.google.com" in page.url or page.locator('input[type="email"]').count() > 0:
            print("\n" + "="*70)
            print("[WARNING] Google login required!")
            print("="*70)
            print(f"\nTo log in:")
            print(f"1. Start the Chrome VNC service:")
            print(f"   cd ~/stacks/gphotos-downloader")
            print(f"   docker-compose --profile relogin up -d chrome")
            print(f"\n2. Open in your browser:")
            print(f"   http://{SERVER_IP}:{VNC_PORT}/")
            print(f"\n3. Log in to Google Photos in the VNC browser")
            print(f"\n4. Once logged in, stop the Chrome service:")
            print(f"   docker-compose down chrome")
            print(f"\n5. Re-run this script")
            print("\n" + "="*70)
            context.close()
            sys.exit(1)
        else:
            print("[INFO] Already logged in!")
        
        # Create exports
        success_count = 0
        total_exports = len(large_albums) + (1 if len(small_albums) > 0 else 0)
        
        # Create individual exports for large albums
        for i, album_name in enumerate(large_albums, 1):
            print(f"\n[{i}/{total_exports}] Processing large album: {album_name}")
            if create_album_export(page, [album_name], f"Large Album - {album_name}"):
                success_count += 1
                # Update state
                for album in state['albums']:
                    if album['name'] == album_name:
                        album['last_export_date'] = datetime.now().isoformat()
                        break
                save_album_state(state)
                
                print(f"[INFO] Waiting {int(5 * SLEEP_MULTIPLIER)} seconds before next export...")
                time.sleep(5 * SLEEP_MULTIPLIER)
            else:
                print(f"[WARNING] Failed to export: {album_name}")
        
        # Create combined export for small albums
        if len(small_albums) > 0:
            print(f"\n[{total_exports}/{total_exports}] Processing small albums batch")
            export_name = f"Small Albums Batch ({len(small_albums)} albums)"
            if create_album_export(page, small_albums, export_name):
                success_count += 1
                # Update state for all small albums
                for album in state['albums']:
                    if album['name'] in small_albums:
                        album['last_export_date'] = datetime.now().isoformat()
                save_album_state(state)
            else:
                print(f"[WARNING] Failed to export small albums batch")
        
        print(f"\n[INFO] Completed! {success_count}/{total_exports} exports created")
        
        # Keep browser open for a bit to see results
        print(f"[INFO] Waiting {int(10 * SLEEP_MULTIPLIER)} seconds before closing...")
        time.sleep(10 * SLEEP_MULTIPLIER)
        
        context.close()


if __name__ == "__main__":
    main()
