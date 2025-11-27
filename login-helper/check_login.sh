#!/bin/bash

echo "[INFO] Checking Google login status..."

# Run Python script in headless mode to check login
python3 /app/check_login.py > /tmp/login_check.log 2>&1
LOGIN_EXIT_CODE=$?

# Check if login was successful
if [ $LOGIN_EXIT_CODE -eq 0 ]; then
    echo "[SUCCESS] User is already logged in!"
    echo "[INFO] Container can exit - no manual login needed"
    cat /tmp/login_check.log
    exit 0
elif [ $LOGIN_EXIT_CODE -eq 1 ]; then
    echo "[INFO] Login required - browser will open for manual login"
    echo ""
    echo "=========================================="
    echo "Please log in to Google Takeout:"
    echo "1. Open browser to: http://${SERVER_IP}:${VNC_PORT}/"
    echo "2. User/Password: kasm_user/${VNC_PW}"
    echo "3. Browser will open to: ${PROTECTED_PAGE_URL}"
    echo "4. Complete the Google login process"
    echo "=========================================="
    echo ""
    
    # Start VNC/Kasm services in background
    /dockerstartup/kasm_default_profile.sh 
    /dockerstartup/vnc_startup.sh &
    VNC_PID=$!
    
    # Wait for VNC to start
    sleep 5
    
    # Periodically check if login is complete
    echo "[INFO] Monitoring login status (checking every 30 seconds)..."
    while true; do
        sleep 30
        python3 /app/check_login.py > /tmp/login_check.log 2>&1
        CHECK_EXIT_CODE=$?
        
        if [ $CHECK_EXIT_CODE -eq 0 ]; then
            echo "[SUCCESS] Login complete!"
            cat /tmp/login_check.log
            echo "[INFO] Shutting down VNC and exiting..."
            kill $VNC_PID 2>/dev/null
            exit 0
        else
            echo "[INFO] Still waiting for login... ($(date '+%Y-%m-%d %H:%M:%S'))"
        fi
    done
else
    echo "[ERROR] Unexpected result from login check"
    cat /tmp/login_check.log
    exit 1
fi
