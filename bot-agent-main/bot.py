import telebot
from telebot import types
import subprocess
import urllib.parse 
import urllib.request 
import xml.etree.ElementTree as ET 
import os 
import sys
import json
import pyautogui 
from datetime import datetime 
import time 
from wakeonlan import send_magic_packet
import cv2 
import numpy as np 
import threading 
import psutil
import socket
import platform
import re
import pyperclip

# ==========================================
# CONFIGURATION
# ==========================================
BOT_TOKEN = "8760364563:AAHVw6GEZpUtyEeqCRw1vLoAaBFCtdLUkgk"

# List of authorized Telegram User IDs (e.g. [123456789, 987654321]).
# If left empty [], ANY user can control the bot.
# Send command 'MYID' in bot chat to find your Telegram User ID!
AUTHORIZED_USERS = []

# Enter the MAC address of the target PC for Wake-on-LAN
TARGET_MAC_ADDRESS = "YOUR_MAC_ADDRESS_HERE" 

# The exact location of Steam on your PC
STEAM_PATH = r"C:\Program Files (x86)\Steam\steam.exe"

bot = telebot.TeleBot(BOT_TOKEN)

# PID file used to track & kill previous bot instances on startup
PID_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.pid")

# --- Global Screen Recording Setup ---
is_recording = False
video_writer = None
record_thread = None
video_filename = ""
record_start_time = None

def is_authorized(message):
    if not AUTHORIZED_USERS:
        return True
    user_id = message.from_user.id
    if user_id in AUTHORIZED_USERS:
        return True
    else:
        bot.reply_to(
            message,
            f"🚫 *Access Denied*\nYour Telegram User ID is: `{user_id}`.\n"
            "To grant access, add this ID to `AUTHORIZED_USERS` in `bot.py`.",
            parse_mode="Markdown"
        )
        return False

def start_recording():
    global is_recording, video_writer, video_filename
    screen_size = tuple(pyautogui.size())
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    current_dir = os.path.abspath(os.getcwd())
    video_filename = os.path.join(current_dir, f"screen_record_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4")
    video_writer = cv2.VideoWriter(video_filename, fourcc, 10.0, screen_size)
    
    while is_recording:
        t0 = time.time()
        img = pyautogui.screenshot()
        frame = np.array(img)
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        video_writer.write(frame)
        elapsed = time.time() - t0
        sleep_time = max(0, 0.1 - elapsed)
        time.sleep(sleep_time)
        
    video_writer.release()

# --- Helper Functions ---
def get_ip_info():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "127.0.0.1"
        
    try:
        req = urllib.request.Request("https://api.ipify.org?format=json", headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = resp.read().decode('utf-8')
            import json
            public_ip = json.loads(data).get('ip', 'Unavailable')
    except Exception:
        public_ip = "Unavailable"
        
    return local_ip, public_ip

def get_system_status():
    cpu_usage = psutil.cpu_percent(interval=0.5)
    cpu_count = psutil.cpu_count(logical=True)
    mem = psutil.virtual_memory()
    mem_used_gb = mem.used / (1024**3)
    mem_total_gb = mem.total / (1024**3)
    
    try:
        disk = psutil.disk_usage('C:\\')
        disk_used_gb = disk.used / (1024**3)
        disk_total_gb = disk.total / (1024**3)
        disk_str = f"{disk_used_gb:.1f} / {disk_total_gb:.1f} GB ({disk.percent}%)"
    except Exception:
        disk_str = "N/A"
        
    battery = psutil.sensors_battery()
    if battery:
        batt_str = f"{battery.percent}% {'🔌 (Plugged In)' if battery.power_plugged else '🔋 (On Battery)'}"
    else:
        batt_str = "🖥️ Desktop / Plugged In"
        
    boot_time = datetime.fromtimestamp(psutil.boot_time())
    uptime_seconds = (datetime.now() - boot_time).total_seconds()
    hours, remainder = divmod(int(uptime_seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s"
    
    local_ip, public_ip = get_ip_info()
    
    status_text = (
        "💻 *System Status Report*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ *CPU Usage:* `{cpu_usage}%` ({cpu_count} threads)\n"
        f"🧠 *RAM Usage:* `{mem_used_gb:.2f} / {mem_total_gb:.2f} GB` ({mem.percent}%)\n"
        f"💾 *Disk (C:):* `{disk_str}`\n"
        f"🔋 *Power Status:* {batt_str}\n"
        f"⏱️ *Uptime:* `{uptime_str}`\n"
        f"🏠 *Local IP:* `{local_ip}`\n"
        f"🌐 *Public IP:* `{public_ip}`\n"
        f"🖥️ *Host:* `{platform.node()}` ({platform.system()} {platform.release()})"
    )
    return status_text

def capture_webcam():
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        return None, "Camera not accessible or device in use."
    
    for _ in range(5):
        ret, frame = cap.read()
        
    ret, frame = cap.read()
    cap.release()
    
    if not ret or frame is None:
        return None, "Failed to grab frame from webcam."
        
    current_dir = os.path.abspath(os.getcwd())
    filepath = os.path.join(current_dir, f"webcam_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
    cv2.imwrite(filepath, frame)
    return filepath, None

def get_clipboard_text():
    try:
        res = subprocess.run(["powershell", "-Command", "Get-Clipboard"], capture_output=True, text=True, timeout=5)
        text = res.stdout.strip() if res.stdout else "Clipboard is empty or non-text."
        return text
    except Exception as e:
        return f"Error reading clipboard: {e}"

def set_clipboard_text(text):
    try:
        clean_text = text.replace("'", "''")
        subprocess.run(["powershell", "-Command", f"Set-Clipboard -Value '{clean_text}'"], capture_output=True, text=True, timeout=5)
        return True
    except Exception:
        return False

def send_windows_notification(title, text):
    try:
        ps_cmd = f"""
        [void] [System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms")
        $objNotifyIcon = New-Object System.Windows.Forms.NotifyIcon
        $objNotifyIcon.Icon = [System.Drawing.SystemIcons]::Information
        $objNotifyIcon.BalloonTipTitle = "{title}"
        $objNotifyIcon.BalloonTipText = "{text}"
        $objNotifyIcon.Visible = $True
        $objNotifyIcon.ShowBalloonTip(5000)
        """
        subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, timeout=5)
        return True
    except Exception:
        return False

def find_and_click_generate_code_button():
    pyautogui.FAILSAFE = False
    current_dir = os.path.abspath(os.getcwd())
    img_screen = pyautogui.screenshot()
    img_bgr = cv2.cvtColor(np.array(img_screen), cv2.COLOR_RGB2BGR)
    screen_h, screen_w = img_bgr.shape[:2]

    # 1. Template Matching (if template file exists)
    template_path = os.path.join(current_dir, "generate_code_btn.png")
    if os.path.exists(template_path):
        tpl = cv2.imread(template_path)
        if tpl is not None:
            res = cv2.matchTemplate(img_bgr, tpl, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
            if max_val >= 0.70:
                h, w = tpl.shape[:2]
                cx = max_loc[0] + w // 2
                cy = max_loc[1] + h // 2
                pyautogui.moveTo(cx, cy, duration=0.5)
                pyautogui.click()
                return True, f"Clicked '+ Generate Code' button (Template Match: {max_val*100:.0f}%)", cx, cy

    # 2. Dynamic HSV Blue Contour Detection (#1a73e8 Google Primary Blue)
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    lower_blue = np.array([100, 140, 140])
    upper_blue = np.array([115, 255, 255])
    mask = cv2.inRange(hsv, lower_blue, upper_blue)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if 60 <= w <= 350 and 20 <= h <= 80:
            aspect_ratio = w / float(h)
            if 2.0 <= aspect_ratio <= 7.0:
                if 100 <= y <= screen_h * 0.8:
                    candidates.append((x, y, w, h))

    if candidates:
        candidates.sort(key=lambda b: (b[1], b[0]))
        best = candidates[0]
        cx = best[0] + best[2] // 2
        cy = best[1] + best[3] // 2
        pyautogui.moveTo(cx, cy, duration=0.5)
        pyautogui.click()
        return True, f"Clicked '+ Generate Code' button (HSV Blue Detection)", cx, cy

    # 3. Dynamic Ratio Fallback based on screen resolution
    cx = int(screen_w * 0.69)
    cy = int(screen_h * 0.40)
    pyautogui.moveTo(cx, cy, duration=0.5)
    pyautogui.click()
    return False, f"Clicked estimated position ({cx}, {cy})", cx, cy


def get_remote_desktop_access_code(click_x, click_y):
    """
    Finds and clicks the Chrome Remote Desktop 'Copy' icon on screen,
    and returns the extracted 12-digit access code from clipboard.
    Uses:
    1. OpenCV template matching & contour detection to find the exact Copy icon
    2. Fallback multi-offset button clicks
    3. Keyboard navigation (Tab -> Enter / Space)
    4. Text selection & Ctrl+C
    """
    def parse_code(raw_text):
        if not raw_text:
            return None
        clean = str(raw_text).strip()
        # Look for 12 digits (e.g. '1234 5678 9012' or '1234-5678-9012' or '123456789012')
        match = re.search(r'\b(\d{4})[\s\-]?(\d{4})[\s\-]?(\d{4})\b', clean)
        if match:
            return f"{match.group(1)} {match.group(2)} {match.group(3)}"
        digits = re.sub(r'\D', '', clean)
        if len(digits) == 12:
            return f"{digits[:4]} {digits[4:8]} {digits[8:]}"
        return None

    def read_clipboard():
        try:
            val = pyperclip.paste()
            code = parse_code(val)
            if code:
                return code
        except Exception:
            pass
        return None

    pyautogui.FAILSAFE = False

    # Pass 1: Full-screen multi-scale template matching with the uploaded copy icon image
    try:
        current_dir = os.path.abspath(os.getcwd())
        img_screen = pyautogui.screenshot()
        img_bgr = cv2.cvtColor(np.array(img_screen), cv2.COLOR_RGB2BGR)
        img_gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        screen_h, screen_w = img_gray.shape[:2]

        templates_to_check = ["copy_code_btn.png", "copy_icon_cropped.png"]
        best_val = -1
        best_point = None

        for t_name in templates_to_check:
            t_path = os.path.join(current_dir, t_name)
            if not os.path.exists(t_path):
                continue
            tpl = cv2.imread(t_path, cv2.IMREAD_GRAYSCALE)
            if tpl is None:
                continue

            for scale in [0.75, 0.85, 1.0, 1.15, 1.25]:
                resized = cv2.resize(tpl, (0, 0), fx=scale, fy=scale)
                if resized.shape[0] > screen_h or resized.shape[1] > screen_w:
                    continue
                res = cv2.matchTemplate(img_gray, resized, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                if max_val > best_val:
                    best_val = max_val
                    best_point = (max_loc[0] + resized.shape[1] // 2, max_loc[1] + resized.shape[0] // 2)

        print(f"[+] Copy icon match confidence: {best_val:.2f} at {best_point}", flush=True)
        if best_val >= 0.55 and best_point:
            pyperclip.copy("")
            pyautogui.moveTo(best_point[0], best_point[1], duration=0.3)
            pyautogui.click()
            time.sleep(0.5)
            code = read_clipboard()
            if code:
                print(f"[+] Access code copied via template match: {code}", flush=True)
                return code
            # Try second click in case of focus requirement
            pyautogui.click()
            time.sleep(0.5)
            code = read_clipboard()
            if code:
                return code
    except Exception as e:
        print(f"[~] Template match for copy icon failed: {e}", flush=True)

    # Pass 2: Multi-offset click & keyboard interaction attempts
    for attempt_round in range(2):
        try:
            pyperclip.copy("")
        except Exception:
            pass

        # Strategy A: Probe likely button positions on the right of click_x
        for offset_x in [140, 160, 180, 200, 120, 220, 100, 240]:
            for offset_y in [0, -10, 10, -20, 20]:
                pyautogui.moveTo(click_x + offset_x, click_y + offset_y, duration=0.15)
                pyautogui.click()
                time.sleep(0.3)
                code = read_clipboard()
                if code:
                    return code

        # Strategy B: Focus code container and Tab into the Copy button
        pyautogui.moveTo(click_x, click_y, duration=0.2)
        pyautogui.click()
        time.sleep(0.2)
        pyautogui.press('tab')
        time.sleep(0.2)
        pyautogui.press('enter')
        time.sleep(0.3)
        code = read_clipboard()
        if code:
            return code

        pyautogui.press('space')
        time.sleep(0.3)
        code = read_clipboard()
        if code:
            return code

        # Strategy C: Triple-click the text and copy via Ctrl+C
        for probe_x in [click_x - 40, click_x, click_x + 30]:
            pyautogui.moveTo(probe_x, click_y, duration=0.2)
            pyautogui.click(clicks=3, interval=0.1)
            time.sleep(0.2)
            pyautogui.hotkey('ctrl', 'c')
            time.sleep(0.3)
            code = read_clipboard()
            if code:
                return code

        if attempt_round == 0:
            time.sleep(2)

    return None


def send_code_to_telegram_desktop(access_code):
    """
    Activates Telegram Desktop window if running,
    focuses the chat message bar, pastes the copied code and hits Enter.
    """
    try:
        import win32gui
        import win32con

        telegram_hwnd = None
        def enum_win(hwnd, extra):
            nonlocal telegram_hwnd
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if "telegram" in title.lower():
                    telegram_hwnd = hwnd

        win32gui.EnumWindows(enum_win, None)

        if telegram_hwnd:
            win32gui.ShowWindow(telegram_hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(telegram_hwnd)
            time.sleep(0.6)

            rect = win32gui.GetWindowRect(telegram_hwnd)
            left, top, right, bottom = rect
            width = right - left
            height = bottom - top

            # Telegram message input is in the bottom area of the active chat
            input_x = left + int(width * 0.60)
            input_y = bottom - 35

            pyautogui.moveTo(input_x, input_y, duration=0.3)
            pyautogui.click()
            time.sleep(0.3)

            # Paste the copied access code and send
            pyperclip.copy(f"{access_code}")
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.25)
            pyautogui.press('enter')
            print(f"[+] Access code successfully pasted into Telegram Desktop window!", flush=True)
            return True
        else:
            print("[~] Telegram Desktop window not found for UI paste.", flush=True)
    except Exception as e:
        print(f"[!] Telegram Desktop UI send error: {e}", flush=True)
    return False

def handle_animo_start_adventure(message):
    bot.reply_to(message, "⏳ *Animo launched!* Waiting 45 seconds for in-game loading & updates to complete...", parse_mode="Markdown")
    time.sleep(45)
    
    pyautogui.FAILSAFE = False
    screen_w, screen_h = pyautogui.size()
    click_x = screen_w / 2
    click_y = screen_h * 0.83  # Center bottom area for 'Start Adventure'
    
    bot.reply_to(message, "🖱️ *Attempt 1:* Focusing game window & clicking 'Start Adventure'...", parse_mode="Markdown")
    pyautogui.moveTo(click_x, click_y, duration=0.5)
    pyautogui.click()
    pyautogui.click()
    pyautogui.press('space')
    pyautogui.press('enter')
    
    bot.reply_to(message, "⏳ Waiting 15 seconds to ensure loading completes...", parse_mode="Markdown")
    time.sleep(15)
    
    bot.reply_to(message, "🖱️ *Attempt 2:* Confirming 'Start Adventure' click...", parse_mode="Markdown")
    pyautogui.moveTo(click_x, click_y, duration=0.3)
    pyautogui.click()
    pyautogui.press('space')
    pyautogui.press('enter')
    
    bot.reply_to(message, "✅ *'Start Adventure' auto-clicked!* Capturing game screenshot...", parse_mode="Markdown")
    time.sleep(3)
    
    try:
        current_dir = os.path.abspath(os.getcwd())
        file_name = os.path.join(current_dir, f"animo_game_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        pyautogui.screenshot(file_name)
        with open(file_name, 'rb') as photo:
            bot.send_photo(
                message.chat.id, 
                photo, 
                caption="🎮 *Animo Game Ready!* Here is your live game screen.",
                parse_mode="Markdown"
            )
    except Exception as e:
        bot.reply_to(message, f"⚠️ Clicked 'Start Adventure', but could not capture screenshot: {e}")

def login_steam_account(user, pwd, message=None):
    if message:
        bot.reply_to(message, f"🔄 Logging into Steam account `{user}`...", parse_mode="Markdown")
        
    os.system("taskkill /f /im steam.exe >nul 2>&1")
    time.sleep(3)
    
    # 1. Launch Steam with -login parameters (Command-Line Login)
    try:
        subprocess.Popen([STEAM_PATH, "-login", user, pwd])
    except Exception as e:
        if message:
            bot.reply_to(message, f"⚠️ Note starting Steam CLI: {e}")
            
    if message:
        bot.reply_to(message, "⏳ Waiting 12 seconds for Steam to launch & authenticate...")
    time.sleep(12)
    
    # 2. GUI Input & Clipboard Paste Fallback (Guarantees '+' symbol in password is pasted 100% accurately)
    try:
        pyautogui.FAILSAFE = False
        set_clipboard_text(user)
        pyautogui.hotkey('ctrl', 'a')
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.5)
        
        pyautogui.press('tab')
        time.sleep(0.5)
        
        set_clipboard_text(pwd)
        pyautogui.hotkey('ctrl', 'a')
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.5)
        
        pyautogui.press('enter')
    except Exception:
        pass
        
    if message:
        bot.reply_to(message, f"✅ Steam authentication command sent for `{user}`!", parse_mode="Markdown")

def get_vibe_search_query(user_query):
    raw = user_query.strip()
    q = raw.lower()
    
    for prefix in ['play songs ', 'play song ', 'play ', 'songs ', 'song ']:
        if q.startswith(prefix):
            raw = raw[len(prefix):].strip()
            q = raw.lower()
            break
            
    if not q or q in ['songs', 'song', 'latest', 'latest songs', 'music', 'vibe']:
        return "Latest Hit Trending Songs Vibe Playlist"
    elif 'anime' in q:
        return "Latest Trending Anime Songs Openings Vibe"
    elif 'english' in q:
        return "Latest Hit English Songs Vibe Pop Playlist"
    elif 'tamil' in q:
        return "Latest Trending Tamil Hit Songs Vibe"
    elif 'hindi' in q:
        return "Latest Trending Hindi Songs Vibe"
    elif 'kpop' in q or 'k-pop' in q:
        return "Latest Trending Kpop Hit Songs Vibe"
    elif 'malayalam' in q:
        return "Latest Trending Malayalam Hit Songs Vibe"
    elif 'telugu' in q:
        return "Latest Trending Telugu Hit Songs Vibe"
    else:
        if 'song' not in q and 'music' not in q and 'ost' not in q:
            return f"{raw} song"
        return raw

def play_youtube_video_smart(search_query, message):
    encoded_song = urllib.parse.quote(search_query)
    # &sp=EgIQAQ== strictly filters YouTube search results to Videos ONLY (excludes ads & channel banners)
    url = f"https://www.youtube.com/results?search_query={encoded_song}&sp=EgIQAQ=="
    
    bot.reply_to(message, f"🎵 Searching for *'{search_query}'* on YouTube (Video Mode)...", parse_mode="Markdown")
    
    try:
        subprocess.Popen(f'start /max chrome "{url}"', shell=True)
        
        bot.reply_to(message, "⏳ Waiting 6 seconds for video search results to load...", parse_mode="Markdown")
        time.sleep(6)
        
        pyautogui.FAILSAFE = False
        screen_width, screen_height = pyautogui.size()
        
        # Click the first actual Video result (Y = ~38% screen height avoids header ads)
        click_x = int(screen_width * 0.38)
        click_y = int(screen_height * 0.38)
        
        bot.reply_to(message, "🖱️ Opening top video result...", parse_mode="Markdown")
        pyautogui.moveTo(click_x, click_y, duration=0.5)
        pyautogui.click()
        
        # Wait 7 seconds for the video player & potential ad to start
        bot.reply_to(message, "⏳ Waiting 7 seconds for video player & ad check...", parse_mode="Markdown")
        time.sleep(7)
        
        # 1. Attempt to click YouTube "Skip Ad" button if an ad is playing (~84% width, ~70% height)
        skip_ad_x = int(screen_width * 0.84)
        skip_ad_y = int(screen_height * 0.70)
        
        pyautogui.moveTo(skip_ad_x, skip_ad_y, duration=0.3)
        pyautogui.click()
        time.sleep(1)
        
        # 2. Focus video player & activate Fullscreen ('f' key)
        player_center_x = int(screen_width / 2)
        player_center_y = int(screen_height * 0.45)
        pyautogui.click(player_center_x, player_center_y)
        time.sleep(0.5)
        
        pyautogui.press('f') # Press 'f' for YouTube Fullscreen
        time.sleep(0.5)
        pyautogui.press('k') # Ensure unpaused
        
        bot.reply_to(message, f"▶️ *Now Playing in Fullscreen:* `{search_query}`", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ YouTube Play Error: {e}")

def find_and_click_spotify_play_button():
    img_screen = pyautogui.screenshot()
    img_bgr = cv2.cvtColor(np.array(img_screen), cv2.COLOR_RGB2BGR)
    screen_h, screen_w = img_bgr.shape[:2]

    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    lower_green = np.array([35, 140, 140])
    upper_green = np.array([85, 255, 255])
    
    mask = cv2.inRange(hsv, lower_green, upper_green)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    candidates = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if 20 <= w <= 120 and 20 <= h <= 120:
            aspect_ratio = w / float(h)
            if 0.6 <= aspect_ratio <= 1.5:
                candidates.append((x, y, w, h))

    if candidates:
        candidates.sort(key=lambda b: b[2]*b[3], reverse=True)
        best = candidates[0]
        cx = best[0] + best[2] // 2
        cy = best[1] + best[3] // 2
        
        pyautogui.FAILSAFE = False
        pyautogui.moveTo(cx, cy, duration=0.4)
        pyautogui.click()
        return True, f"Clicked Spotify Green Play Button at ({cx}, {cy})"

    # Fallback offset adjusted for Ultrawide (2560px) & 1080p screens
    fallback_x = int(screen_w * 0.21) if screen_w > 2000 else int(screen_w * 0.27)
    fallback_y = int(screen_h * 0.38)
    
    pyautogui.FAILSAFE = False
    pyautogui.moveTo(fallback_x, fallback_y, duration=0.4)
    pyautogui.click()
    return False, f"Clicked estimated Play position ({fallback_x}, {fallback_y})"

def play_spotify_song(search_query, message):
    encoded_query = urllib.parse.quote(search_query)
    spotify_uri = f"spotify:search:{encoded_query}"
    
    bot.reply_to(message, f"🟢 Launching Spotify Desktop & searching for *'{search_query}'*...", parse_mode="Markdown")
    
    try:
        os.startfile(spotify_uri)
        
        bot.reply_to(message, "⏳ Waiting 5 seconds for Spotify search results to load...", parse_mode="Markdown")
        time.sleep(5)
        
        bot.reply_to(message, "🖱️ Scanning screen for Spotify Green Play Button...", parse_mode="Markdown")
        found, click_msg = find_and_click_spotify_play_button()
        
        bot.reply_to(message, f"✅ {click_msg}\n▶️ *Now Playing on Spotify:* `{search_query}`", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Spotify Error: {e}")

def fetch_netmirror_tamil_movies(page=0):
    """
    Fetches the live list of Tamil movies & series directly from NetMirror:
    URL: https://netmirror.center/explore/all?dubbing=Tamil&title=Tamil
    """
    url = f"https://api2.imdb3.shop/api/movies/list/filter?page={page}&dubbing=Tamil&sort_by=date"
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://netmirror.center/explore/all?dubbing=Tamil&title=Tamil',
            'Content-Type': 'application/json'
        }
    )
    movies = []
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            results = data.get('results') or data.get('data') or []
            for item in results:
                raw_title = item.get('title') or item.get('name') or ''
                if not raw_title:
                    continue
                clean_title = re.sub(r'\s*\[.*?\]', '', raw_title).strip()
                year = item.get('year') or (item.get('release_date', '')[:4] if item.get('release_date') else '')
                media_type = item.get('media_type') or ('Movie' if item.get('type') == 1 else 'Series')
                movies.append({
                    'title': clean_title if clean_title else raw_title,
                    'raw_title': raw_title.strip(),
                    'year': year,
                    'media_type': media_type,
                    'id': item.get('id')
                })
    except Exception as e:
        print(f"[!] NetMirror fetch error: {e}", flush=True)
    return movies


def search_netmirror_movies(query):
    """Searches NetMirror for a specific movie title."""
    enc = urllib.parse.quote(query.lower().strip())
    url = f"https://api2.imdb4.shop/api/search2/{enc}?page=0"
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Referer': 'https://netmirror.center/',
            'Content-Type': 'application/json'
        }
    )
    movies = []
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            results = data.get('results') or []
            for item in results:
                raw_title = item.get('title') or item.get('name') or ''
                if not raw_title:
                    continue
                clean_title = re.sub(r'\s*\[.*?\]', '', raw_title).strip()
                year = item.get('year') or (item.get('release_date', '')[:4] if item.get('release_date') else '')
                movies.append({
                    'title': clean_title if clean_title else raw_title,
                    'raw_title': raw_title.strip(),
                    'year': year,
                    'id': item.get('id')
                })
    except Exception as e:
        print(f"[!] NetMirror search error: {e}", flush=True)
    return movies


def handle_movie_search(original_text, message):
    cmd = original_text.strip()
    query = ""
    for prefix in ["SEARCH MOVIES", "SEARCH MOVIE", "MOVIES", "MOVIE", "TAMIL MOVIES", "LATEST MOVIES", "NEW MOVIES"]:
        if cmd.upper().startswith(prefix):
            query = cmd[len(prefix):].strip()
            break

    # 1. If specific movie name requested (e.g., "MOVIE ANIMALS" or "MOVIE REPORTING LIVE")
    if query:
        bot.reply_to(message, f"🔍 Searching NetMirror for *'{query}'*...", parse_mode="Markdown")
        results = search_netmirror_movies(query)

        # Filter for Tamil or top matching titles
        tamil_matches = [m for m in results if "tamil" in m['raw_title'].lower()]
        target_list = tamil_matches if tamil_matches else results

        if target_list:
            resp = (
                f"🎬 *NetMirror Search Results for '{query.title()}':*\n"
                f"🌐 `https://netmirror.center/explore/all?dubbing=Tamil&title=Tamil`\n"
                "━━━━━━━━━━━━━━━━━━━━━\n\n"
            )
            for idx, m in enumerate(target_list[:12], 1):
                y_str = f" ({m['year']})" if m['year'] else ""
                resp += f"{idx}. 🍿 *{m['raw_title']}*{y_str}\n"
        else:
            resp = f"❌ No matching movies found on NetMirror for *'{query}'*."

        bot.reply_to(message, resp, parse_mode="Markdown")
        return

    # 2. General "MOVIES" command -> Fetch all Tamil movies from NetMirror
    bot.reply_to(message, "🎬 Fetching latest Tamil movies from NetMirror...", parse_mode="Markdown")
    movies = fetch_netmirror_tamil_movies(page=0)

    if not movies:
        bot.reply_to(
            message,
            "⚠️ Could not fetch movies from NetMirror right now.\n"
            "🌐 Check website directly:\nhttps://netmirror.center/explore/all?dubbing=Tamil&title=Tamil"
        )
        return

    resp = (
        "🎬 *NetMirror — Latest Tamil Movies & Series*\n"
        "🌐 `https://netmirror.center/explore/all?dubbing=Tamil&title=Tamil`\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    # List the movies cleanly as requested by user
    for idx, m in enumerate(movies[:20], 1):
        y_str = f" ({m['year']})" if m['year'] else ""
        resp += f"{idx}. 🍿 *{m['raw_title']}*{y_str}\n"

    resp += (
        "\n━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 *Tip:* Send `MOVIE [Name]` (e.g. `MOVIE Animals`) to search for any title on NetMirror!"
    )

    bot.reply_to(message, resp, parse_mode="Markdown")

# --- Keyboards ---
def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(row_width=3, resize_keyboard=True)
    markup.add(
        types.KeyboardButton("📊 STATUS"),
        types.KeyboardButton("📸 SCREENSHOT"),
        types.KeyboardButton("📷 WEBCAM")
    )
    markup.add(
        types.KeyboardButton("🎥 REC START"),
        types.KeyboardButton("🛑 REC STOP"),
        types.KeyboardButton("🌐 REMOTE DESKTOP")
    )
    markup.add(
        types.KeyboardButton("🔊 VOL UP"),
        types.KeyboardButton("🔉 VOL DOWN"),
        types.KeyboardButton("🔇 MUTE")
    )
    markup.add(
        types.KeyboardButton("⏯️ PLAY/PAUSE"),
        types.KeyboardButton("⏭️ NEXT"),
        types.KeyboardButton("⏮️ PREV")
    )
    markup.add(
        types.KeyboardButton("⚡ POWER MENU"),
        types.KeyboardButton("📂 FILES"),
        types.KeyboardButton("📋 CLIPBOARD")
    )
    markup.add(
        types.KeyboardButton("🎬 MOVIES"),
        types.KeyboardButton("📰 NEWS"),
        types.KeyboardButton("🏏 CRICKET")
    )
    markup.add(
        types.KeyboardButton("❓ HELP")
    )
    return markup

def get_power_keyboard():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        types.KeyboardButton("🔒 LOCK PC"),
        types.KeyboardButton("💤 SLEEP PC")
    )
    markup.add(
        types.KeyboardButton("🔄 RESTART PC"),
        types.KeyboardButton("🛑 SHUTDOWN PC")
    )
    markup.add(
        types.KeyboardButton("❌ CANCEL SHUTDOWN"),
        types.KeyboardButton("⬅️ MAIN MENU")
    )
    return markup

# --- Command Handlers ---
@bot.message_handler(commands=["start", "help"])
def start(message):
    if not is_authorized(message):
        return
    bot.reply_to(
        message,
        "🤖 *PC Automation & Remote Agent Ready!*\n\n"
        "Use the quick menu buttons below or send any command:\n\n"
        "🔹 *System Monitoring & Control*\n"
        "• `STATUS` / `SYSINFO` - Detailed hardware & network status\n"
        "• `PROCESSES` / `TASKLIST` - Top processes\n"
        "• `KILL [Process Name/PID]` - Terminate process\n"
        "• `MYID` - Display your Telegram User ID\n\n"
        "🔹 *Media & Camera*\n"
        "• `TAKE SCREENSHOT` / `SCREENSHOT DOC` - Grab screen\n"
        "• `TAKE WEBCAM PHOTO` / `WEBCAM` - Capture webcam snapshot\n"
        "• `SCREEN RECORD START / OFF` - Screen video recording\n"
        "• `OPEN CAMERA` / `TOGGLE MIC`\n"
        "• `VOL UP` / `VOL DOWN` / `MUTE` / `PLAY/PAUSE` / `NEXT` / `PREV`\n"
        "• `PLAY SONG [Name / Tamil / English]` - Play YouTube song\n\n"
        "🔹 *Files & Clipboard*\n"
        "• `DIR [Path]` / `LS [Path]` - List folder contents\n"
        "• `DOWNLOAD [Path]` - Send file from PC to Telegram\n"
        "• Upload any photo/doc to chat -> Saved to `./downloads/`\n"
        "• `CLIPBOARD` / `GET CLIPBOARD` - Read PC clipboard\n"
        "• `SET CLIPBOARD [Text]` - Set PC clipboard\n\n"
        "🔹 *Power & Launchers*\n"
        "• `POWER MENU` / `LOCK` / `SLEEP` / `RESTART` / `SHUTDOWN` / `PC ON`\n"
        "• `SHUTDOWN IN [minutes]` / `CANCEL SHUTDOWN`\n"
        "• `OPEN CHROME` / `OPEN BRAVE` / `OPEN REMOTE DESKTOP`\n"
        "• `PLAY [Account] [Game]` / `LOGIN STEAM` / `OPEN STEAM`\n"
        "• `CLOSE ALL` / `CLOSE [App]`\n"
        "• `CMD [Command]` / `TERMINAL [Command]` / `PS [Command]`\n"
        "• `NOTIFY [Title] | [Message]` - Send Windows notification popup\n"
        "• `ENABLE AUTOSTART` / `DISABLE AUTOSTART`\n"
        "• `NEWS` / `CRICKET NEWS`",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

@bot.message_handler(content_types=['document', 'photo', 'audio', 'video'])
def handle_incoming_files(message):
    if not is_authorized(message):
        return
    try:
        downloads_dir = os.path.join(os.path.abspath(os.getcwd()), "downloads")
        os.makedirs(downloads_dir, exist_ok=True)
        
        if message.document:
            file_info = bot.get_file(message.document.file_id)
            file_name = message.document.file_name or f"file_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        elif message.photo:
            file_info = bot.get_file(message.photo[-1].file_id)
            file_name = f"photo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        elif message.audio:
            file_info = bot.get_file(message.audio.file_id)
            file_name = message.audio.file_name or f"audio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp3"
        elif message.video:
            file_info = bot.get_file(message.video.file_id)
            file_name = message.video.file_name or f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
        else:
            return
            
        bot.reply_to(message, "⏳ Downloading file to PC...")
        downloaded_file = bot.download_file(file_info.file_path)
        save_path = os.path.join(downloads_dir, file_name)
        with open(save_path, 'wb') as new_file:
            new_file.write(downloaded_file)
            
        bot.reply_to(
            message,
            f"📥 *File Successfully Saved to PC!*\n\n"
            f"📄 *File Name:* `{file_name}`\n"
            f"📁 *Saved Location:* `{save_path}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        bot.reply_to(message, f"❌ File Download Error: {e}")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    global is_recording, record_thread, video_filename, record_start_time
    
    if not is_authorized(message):
        return
        
    original_text = message.text.strip()
    command = original_text.upper() 

    # --- Steam Accounts & Games ---
    steam_accounts = {
        "DHANEESH014": {"user": "dhaneesh014", "pass": "gds0149+"},
        "DHANEESH": {"user": "dhaneesh014", "pass": "gds0149+"}
    }
    
    steam_games = {
        "ANIIMO": "APP_ID_HERE", 
        "ANIMO": "APP_ID_HERE", 
        "GTA": "271590",
        "PUBG": "578080",
        "CSGO": "730"
    }

    # --- MY ID ---
    if command in ["MYID", "MY ID", "ID", "/MYID"]:
        bot.reply_to(
            message,
            f"👤 *Your Telegram Details:*\n\n"
            f"• *User ID:* `{message.from_user.id}`\n"
            f"• *Username:* `@{message.from_user.username}`\n"
            f"• *Chat ID:* `{message.chat.id}`",
            parse_mode="Markdown"
        )

    # --- SYSTEM STATUS & MONITORING ---
    elif command in ["📊 STATUS", "STATUS", "SYSINFO", "SYSTEM STATUS", "SYSTEM"]:
        bot.reply_to(message, "⏳ Gathering system metrics...")
        status_report = get_system_status()
        bot.reply_to(message, status_report, parse_mode="Markdown")

    elif command in ["PROCESSES", "TASKLIST", "TOP PROCESSES"]:
        bot.reply_to(message, "⏳ Scanning processes...")
        try:
            procs = []
            for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
                try:
                    procs.append(p.info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            top_mem = sorted(procs, key=lambda x: x['memory_percent'] or 0, reverse=True)[:10]
            
            msg = "📋 *Top 10 Processes by Memory Usage:*\n\n"
            for p in top_mem:
                name = p['name']
                pid = p['pid']
                mem = p['memory_percent'] or 0
                msg += f"🔹 `{name}` (PID: `{pid}`) - `{mem:.1f}%` RAM\n"
            bot.reply_to(message, msg, parse_mode="Markdown")
        except Exception as e:
            bot.reply_to(message, f"❌ Process listing error: {e}")

    elif command.startswith("KILL "):
        target = original_text[5:].strip()
        bot.reply_to(message, f"🛑 Attempting to terminate: `{target}`...", parse_mode="Markdown")
        try:
            if target.isdigit():
                pid = int(target)
                p = psutil.Process(pid)
                p.terminate()
                bot.reply_to(message, f"✅ Process PID `{pid}` killed successfully.", parse_mode="Markdown")
            else:
                exe_name = target if target.lower().endswith(".exe") else f"{target}.exe"
                os.system(f"taskkill /f /im {exe_name} >nul 2>&1")
                bot.reply_to(message, f"✅ Termination command sent for `{exe_name}`.", parse_mode="Markdown")
        except Exception as e:
            bot.reply_to(message, f"❌ Kill Error: {e}")

    # --- WEBCAM PHOTO ---
    elif command in ["📷 WEBCAM", "TAKE WEBCAM PHOTO", "WEBCAM", "WEBCAM PHOTO", "WEBCAM SNAPSHOT"]:
        bot.reply_to(message, "📷 Capturing webcam photo...")
        filepath, err = capture_webcam()
        if filepath and os.path.exists(filepath):
            try:
                with open(filepath, 'rb') as photo:
                    bot.send_photo(message.chat.id, photo, caption="📷 Webcam Snapshot")
            except Exception as e:
                bot.reply_to(message, f"❌ Error sending photo: {e}")
        else:
            bot.reply_to(message, f"❌ Webcam Error: {err}")

    # --- SCREENSHOT & RECORDING ---
    elif command in ["📸 SCREENSHOT", "TAKE SCREENSHOT", "SCREENSHOT"]:
        bot.reply_to(message, "📸 Taking screenshot...")
        try:
            current_dir = os.path.abspath(os.getcwd())
            file_name = os.path.join(current_dir, f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
            pyautogui.screenshot(file_name) 
            with open(file_name, 'rb') as photo:
                bot.send_photo(message.chat.id, photo, caption="📸 Desktop Screenshot")
            bot.reply_to(message, f"✅ Screenshot saved at:\n`{file_name}`", parse_mode="Markdown")
        except Exception as e:
            bot.reply_to(message, f"❌ Screenshot Error: {e}")

    elif command in ["SCREENSHOT DOC", "SCREENSHOT DOCUMENT"]:
        bot.reply_to(message, "📸 Taking full-resolution screenshot document...")
        try:
            current_dir = os.path.abspath(os.getcwd())
            file_name = os.path.join(current_dir, f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
            pyautogui.screenshot(file_name) 
            with open(file_name, 'rb') as doc:
                bot.send_document(message.chat.id, doc, caption="📸 Desktop Uncompressed Screenshot")
        except Exception as e:
            bot.reply_to(message, f"❌ Screenshot Error: {e}")

    elif command in ["🎥 REC START", "SCREEN RECORD START"]:
        if not is_recording:
            is_recording = True
            record_start_time = datetime.now()
            record_thread = threading.Thread(target=start_recording, daemon=True)
            record_thread.start()
            bot.reply_to(message, "🎥 Screen recording started in background...")
        else:
            bot.reply_to(message, "⚠️ Screen recording is already running!")

    elif command in ["🛑 REC STOP", "SCREEN RECORD OFF", "SCREEN RECORD STOP"]:
        if is_recording:
            is_recording = False
            bot.reply_to(message, "⏳ Finalizing screen recording video...")
            if record_thread is not None:
                record_thread.join(timeout=10) 
            bot.reply_to(message, f"✅ Screen recording stopped!\n📁 Saved at:\n`{video_filename}`", parse_mode="Markdown")
            
            if os.path.exists(video_filename) and os.path.getsize(video_filename) > 0:
                try:
                    if os.path.getsize(video_filename) < 50 * 1024 * 1024:
                        bot.reply_to(message, "📤 Uploading screen video to Telegram...")
                        with open(video_filename, 'rb') as video_file:
                            bot.send_video(message.chat.id, video_file, caption="🎥 Screen Recording Video")
                except Exception as e:
                    bot.reply_to(message, f"⚠️ Note: Video saved locally but could not upload to Telegram: {e}")
        else:
            bot.reply_to(message, "⚠️ No active screen recording found.")

    elif command in ["LOCATION", "SCREEN RECORD LOCATION", "SCREENSHOT LOCATION", "📂 FILES"]:
        current_dir = os.path.abspath(os.getcwd())
        bot.reply_to(
            message,
            f"📁 *Bot Working Directory:*\n`{current_dir}`\n\n"
            f"Use `DIR` to list directory contents or `DOWNLOAD [filename]` to retrieve files.",
            parse_mode="Markdown"
        )

    # --- FILE EXPLORER & DOWNLOAD ---
    elif command == "DIR" or command.startswith("DIR ") or command == "LS" or command.startswith("LS "):
        parts = original_text.split(" ", 1)
        target_path = parts[1].strip() if len(parts) > 1 else os.getcwd()
        if not os.path.exists(target_path):
            bot.reply_to(message, f"❌ Path does not exist: `{target_path}`", parse_mode="Markdown")
        else:
            try:
                items = os.listdir(target_path)
                folders = [f"📁 {item}" for item in items if os.path.isdir(os.path.join(target_path, item))]
                files = [f"📄 {item}" for item in items if os.path.isfile(os.path.join(target_path, item))]
                all_items = sorted(folders) + sorted(files)
                
                resp = f"📂 *Contents of:* `{target_path}`\n\n"
                if not all_items:
                    resp += "*(Directory is empty)*"
                else:
                    count = 0
                    for line in all_items:
                        if len(resp) > 3800:
                            resp += f"\n...and {len(all_items) - count} more items."
                            break
                        resp += f"{line}\n"
                        count += 1
                bot.reply_to(message, resp, parse_mode="Markdown")
            except Exception as e:
                bot.reply_to(message, f"❌ Directory listing error: {e}")

    elif command.startswith("DOWNLOAD "):
        target_path = original_text[9:].strip()
        if not os.path.isabs(target_path):
            target_path = os.path.join(os.getcwd(), target_path)
            
        if not os.path.exists(target_path) or not os.path.isfile(target_path):
            bot.reply_to(message, f"❌ File not found: `{target_path}`", parse_mode="Markdown")
        else:
            file_size_mb = os.path.getsize(target_path) / (1024 * 1024)
            if file_size_mb > 49:
                bot.reply_to(message, f"⚠️ File is too large ({file_size_mb:.1f} MB) for Telegram Bot API limit (50 MB).")
            else:
                bot.reply_to(message, f"📤 Sending `{os.path.basename(target_path)}` ({file_size_mb:.2f} MB)...", parse_mode="Markdown")
                try:
                    with open(target_path, 'rb') as f:
                        bot.send_document(message.chat.id, f)
                except Exception as e:
                    bot.reply_to(message, f"❌ Download error: {e}")

    # --- CLIPBOARD MANAGEMENT ---
    elif command in ["📋 CLIPBOARD", "CLIPBOARD", "GET CLIPBOARD"]:
        clip_text = get_clipboard_text()
        if len(clip_text) > 3800:
            clip_text = clip_text[:3800] + "\n...[Truncated]"
        bot.reply_to(message, f"📋 *PC Clipboard Content:*\n```\n{clip_text}\n```", parse_mode="Markdown")

    elif command.startswith("SET CLIPBOARD "):
        text_to_set = original_text[14:].strip()
        if set_clipboard_text(text_to_set):
            bot.reply_to(message, f"✅ Clipboard updated with text:\n`{text_to_set}`", parse_mode="Markdown")
        else:
            bot.reply_to(message, "❌ Failed to set clipboard.")

    # --- NOTIFICATION POPUP ---
    elif command.startswith("NOTIFY ") or command.startswith("ALERT "):
        payload = original_text.split(" ", 1)[1] if " " in original_text else ""
        if "|" in payload:
            title, msg_text = payload.split("|", 1)
        else:
            title, msg_text = "Telegram Bot Alert", payload
        
        send_windows_notification(title.strip(), msg_text.strip())
        bot.reply_to(message, f"🔔 Notification popup displayed on PC:\n*Title:* {title}\n*Message:* {msg_text}", parse_mode="Markdown")

    # --- CAMERA & MIC ---
    elif command in ["OPEN CAMERA", "TURN ON CAMERA"]:
        try:
            subprocess.Popen('start microsoft.windows.camera:', shell=True)
            bot.reply_to(message, "📷 Camera app launched.")
        except Exception as e:
            bot.reply_to(message, f"❌ Camera Error: {e}")

    elif command in ["TOGGLE MIC", "TURN ON MIC", "TURN OFF MIC"]:
        try:
            pyautogui.hotkey('win', 'alt', 'm')
            bot.reply_to(message, "🎙️ Mic toggled on/off via Windows shortcut.")
        except Exception as e:
            bot.reply_to(message, f"❌ Mic Error: {e}")

    # --- MEDIA & VOLUME CONTROL ---
    elif command in ["🔊 VOL UP", "VOL UP", "VOLUME UP"]:
        pyautogui.press('volumeup', presses=5)
        bot.reply_to(message, "🔊 System Volume Increased (+10%)")

    elif command in ["🔉 VOL DOWN", "VOL DOWN", "VOLUME DOWN"]:
        pyautogui.press('volumedown', presses=5)
        bot.reply_to(message, "🔉 System Volume Decreased (-10%)")

    elif command in ["🔇 MUTE", "MUTE", "UNMUTE"]:
        pyautogui.press('volumemute')
        bot.reply_to(message, "🔇 Volume Muted / Unmuted")

    elif command in ["⏯️ PLAY/PAUSE", "PLAY/PAUSE", "PLAY", "PAUSE"]:
        pyautogui.press('playpause')
        bot.reply_to(message, "⏯️ Media Play/Pause Toggled")

    elif command in ["⏭️ NEXT", "NEXT", "NEXT TRACK"]:
        pyautogui.press('nexttrack')
        bot.reply_to(message, "⏭️ Next Media Track")

    elif command in ["⏮️ PREV", "PREV", "PREVIOUS TRACK"]:
        pyautogui.press('prevtrack')
        bot.reply_to(message, "⏮️ Previous Media Track")

    # --- POWER MENU & CONTROLS ---
    elif command in ["⚡ POWER MENU", "POWER MENU", "POWER"]:
        bot.reply_to(message, "⚡ *PC Power Management Menu*", parse_mode="Markdown", reply_markup=get_power_keyboard())

    elif command in ["🔒 LOCK PC", "LOCK", "LOCK PC"]:
        bot.reply_to(message, "🔒 Locking PC workstation...")
        os.system("rundll32.exe user32.dll,LockWorkStation")

    elif command in ["💤 SLEEP PC", "SLEEP", "SLEEP PC"]:
        bot.reply_to(message, "💤 Putting PC to sleep...")
        os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")

    elif command in ["🔄 RESTART PC", "RESTART", "RESTART PC"]:
        bot.reply_to(message, "🔄 PC is restarting in 5 seconds...")
        os.system("shutdown /r /t 5")

    elif command in ["🛑 SHUTDOWN PC", "PC OFF", "PC SHUTDOWN", "SHUTDOWN"]:
        bot.reply_to(message, "⚠️ PC is shutting down in 5 seconds...")
        os.system("shutdown /s /t 5")

    elif command in ["❌ CANCEL SHUTDOWN", "CANCEL SHUTDOWN"]:
        os.system("shutdown /a")
        bot.reply_to(message, "✅ Any pending shutdown/restart has been cancelled.")

    elif command.startswith("SHUTDOWN IN "):
        parts = command.split()
        if len(parts) >= 3 and parts[2].isdigit():
            mins = int(parts[2])
            secs = mins * 60
            os.system(f"shutdown /s /t {secs}")
            bot.reply_to(message, f"⏰ PC scheduled to shut down in `{mins}` minutes ({secs} seconds). Send `CANCEL SHUTDOWN` to abort.", parse_mode="Markdown")
        else:
            bot.reply_to(message, "⚠️ Invalid format. Example: `SHUTDOWN IN 10`")

    elif command in ["PC ON", "PC START"]:
        try:
            send_magic_packet(TARGET_MAC_ADDRESS)
            bot.reply_to(message, f"✅ Wake-on-LAN signal sent to MAC: `{TARGET_MAC_ADDRESS}`.", parse_mode="Markdown")
        except Exception as e:
            bot.reply_to(message, f"❌ Failed to send Wake-on-LAN signal: {e}")

    elif command == "⬅️ MAIN MENU":
        bot.reply_to(message, "🏠 Returning to Main Menu", reply_markup=get_main_keyboard())

    # --- AUTOSTART SETUP ---
    elif command in ["ENABLE AUTOSTART", "AUTOSTART ON"]:
        try:
            startup_path = os.path.join(os.environ["APPDATA"], r"Microsoft\Windows\Start Menu\Programs\Startup")
            bat_file_path = os.path.join(startup_path, "telegram_bot_autostart.bat")
            current_dir = os.path.abspath(os.getcwd())
            bat_content = f"""@echo off\ncd /d "{current_dir}"\nstart cmd /k "python bot.py"\n"""
            with open(bat_file_path, "w") as bat_file:
                bat_file.write(bat_content)
            bot.reply_to(message, f"✅ Auto-Start Successfully Enabled!\n📁 Startup Script: `{bat_file_path}`", parse_mode="Markdown")
        except Exception as e:
            bot.reply_to(message, f"❌ Failed to enable Auto-Start: {e}")

    elif command in ["DISABLE AUTOSTART", "AUTOSTART OFF"]:
        try:
            startup_path = os.path.join(os.environ["APPDATA"], r"Microsoft\Windows\Start Menu\Programs\Startup")
            bat_file_path = os.path.join(startup_path, "telegram_bot_autostart.bat")
            if os.path.exists(bat_file_path):
                os.remove(bat_file_path)
                bot.reply_to(message, "✅ Auto-Start disabled. Startup batch file removed.")
            else:
                bot.reply_to(message, "ℹ️ Auto-Start startup batch file was not found.")
        except Exception as e:
            bot.reply_to(message, f"❌ Failed to disable Auto-Start: {e}")

    # --- TERMINAL & POWERSHELL COMMANDS ---
    elif command.startswith("CMD ") or command.startswith("TERMINAL ") or command.startswith("PS "):
        is_ps = command.startswith("PS ")
        cmd_to_run = original_text.split(" ", 1)[1] if " " in original_text else ""
        if cmd_to_run:
            shell_name = "PowerShell" if is_ps else "Command Prompt"
            bot.reply_to(message, f"⚙️ Running `{shell_name}` command:\n`{cmd_to_run}`", parse_mode="Markdown")
            try:
                if is_ps:
                    full_cmd = f"powershell -Command \"{cmd_to_run}\""
                else:
                    full_cmd = cmd_to_run
                    
                result = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=30)
                output = result.stdout.strip() if result.stdout else result.stderr.strip()
                if not output: 
                    output = "✅ Command executed successfully (No output returned)."
                    
                if len(output) > 3800:
                    current_dir = os.path.abspath(os.getcwd())
                    out_file = os.path.join(current_dir, f"cmd_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
                    with open(out_file, "w", encoding="utf-8") as f:
                        f.write(output)
                    with open(out_file, "rb") as doc:
                        bot.send_document(message.chat.id, doc, caption="🖥️ Output exceeded limit, attached full text output.")
                else:
                    bot.reply_to(message, f"🖥️ *{shell_name} Output:*\n```\n{output}\n```", parse_mode="Markdown")
            except subprocess.TimeoutExpired:
                bot.reply_to(message, "❌ Command timed out after 30 seconds.")
            except Exception as e:
                bot.reply_to(message, f"❌ Terminal Error: {e}")
        else:
            bot.reply_to(message, "⚠️ Please provide a command. Example: `CMD ipconfig` or `PS Get-Process`")

    # --- NEWS & CRICKET ---
    elif command in ["🏏 CRICKET", "CRICKET NEWS", "CRICKET SCORE", "LIVE CRICKET"]:
        bot.reply_to(message, "🏏 Fetching live cricket scores... Please wait.")
        try:
            url = "http://static.cricinfo.com/rss/livescores.xml"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            html = urllib.request.urlopen(req, timeout=5).read()
            root = ET.fromstring(html)
            score_list = "🏏 *Live Cricket Scores:*\n━━━━━━━━━━━━━━━━━━━━━\n\n"
            count = 1
            for item in root.findall('./channel/item'):
                if count > 8: break
                title = item.find('title').text
                score_list += f"🔹 {title}\n\n"
                count += 1
            bot.reply_to(message, score_list, parse_mode="Markdown")
        except Exception as e:
            bot.reply_to(message, f"❌ Error fetching cricket scores: {e}")

    elif command in ["📰 NEWS", "NEWS"] or command.endswith(" NEWS") or command in ["SEND NEWS", "TODAY NEWS"]:
        topic = command.replace(" NEWS", "").replace("📰 ", "").strip() if "NEWS" in command else ""
        if not topic or topic in ["SEND", "TODAY", "📰"]: 
            url = "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en"
            title_text = "🌍 *Today's Top News Summary:*"
        else:
            encoded_topic = urllib.parse.quote(topic)
            url = f"https://news.google.com/rss/search?q={encoded_topic}&hl=en-IN&gl=IN&ceid=IN:en"
            title_text = f"📰 *Top {topic.title()} News:*"
            
        bot.reply_to(message, f"📰 Fetching news updates... Please wait.")
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            html = urllib.request.urlopen(req, timeout=5).read()
            root = ET.fromstring(html)
            news_list = f"{title_text}\n━━━━━━━━━━━━━━━━━━━━━\n\n"
            count = 1
            for item in root.findall('./channel/item'):
                if count > 7: break
                title = item.find('title').text
                news_list += f"🔹 {title}\n\n"
                count += 1
            if count == 1: news_list += "No news items found for this topic."
            bot.reply_to(message, news_list, parse_mode="Markdown")
        except Exception as e:
            bot.reply_to(message, f"❌ Error fetching news: {e}")

    # --- REMOTE DESKTOP ---
    elif command in ["🌐 REMOTE DESKTOP", "OPEN REMOTE DESKTOP", "REMOTE DESKTOP"]:
        bot.reply_to(message, "🌐 Opening Chrome Remote Desktop...")
        try:
            url = "https://remotedesktop.google.com/support"
            subprocess.Popen(f'start /max chrome "{url}"', shell=True)
            
            bot.reply_to(message, "⏳ Waiting 10 seconds for Chrome Remote Desktop page to load...")
            time.sleep(10)
            
            bot.reply_to(message, "🖱️ Scanning screen for '+ Generate Code' button...")
            success, click_msg, click_x, click_y = find_and_click_generate_code_button()
            
            bot.reply_to(message, f"✅ {click_msg}\n⏳ Waiting 10 seconds for the Access Code to generate...")
            time.sleep(10) 
            
            bot.reply_to(message, "📋 Copying Access Code from screen...")
            access_code = get_remote_desktop_access_code(click_x, click_y)
            
            if access_code:
                response_text = (
                    "🔐 *Remote Desktop Access Code:*\n\n"
                    f"`{access_code}`\n\n"
                    "👆 _Tap or click the code above to copy it directly!_\n"
                    "⏱️ _Code expires in 5 minutes._"
                )
                bot.reply_to(message, response_text, parse_mode="Markdown")
                # Also automate Telegram Desktop window (bring to front, paste & send)
                send_code_to_telegram_desktop(access_code)
            else:
                bot.reply_to(
                    message, 
                    "⚠️ *Could not copy code automatically!*\n"
                    "Please ensure Chrome is in the foreground and the page generated the code.",
                    parse_mode="Markdown"
                )
        except Exception as e:
            bot.reply_to(message, f"❌ Remote Desktop Error: {e}")

    # --- CLOSE APPLICATIONS ---
    elif command.startswith("CLOSE "):
        target = original_text[6:].strip().upper()
        
        app_exe_map = {
            "CHROME": "chrome.exe",
            "BRAVE": "brave.exe",
            "STEAM": "steam.exe",
            "DISCORD": "discord.exe",
            "NOTEPAD": "notepad.exe",
            "VLC": "vlc.exe",
            "VISUAL STUDIO": "Code.exe",
            "VS CODE": "Code.exe",
            "EDGE": "msedge.exe",
            "TELEGRAM": "Telegram.exe"
        }
        
        if target in ["ALL", "ALL TABS", "ALL APPS"]:
            bot.reply_to(message, "🧹 Closing all common applications and browser tabs...")
            apps_to_kill = ["chrome.exe", "brave.exe", "msedge.exe", "steam.exe", "discord.exe", "vlc.exe", "notepad.exe", "Code.exe"]
            for exe in apps_to_kill:
                os.system(f"taskkill /f /im {exe} >nul 2>&1")
            bot.reply_to(message, "✅ All common applications and tabs closed.")
            
        elif target in app_exe_map:
            exe_name = app_exe_map[target]
            bot.reply_to(message, f"🛑 Closing {target}...")
            os.system(f"taskkill /f /im {exe_name} >nul 2>&1")
            bot.reply_to(message, f"✅ `{target}` closed successfully.", parse_mode="Markdown")
            
        else:
            exe_name = target.lower() if target.endswith(".exe") else f"{target.lower()}.exe"
            bot.reply_to(message, f"🛑 Attempting to close `{exe_name}`...", parse_mode="Markdown")
            os.system(f"taskkill /f /im {exe_name} >nul 2>&1")
            bot.reply_to(message, f"✅ Command sent to close `{target}`.", parse_mode="Markdown")

    # --- MOVIE SEARCH & DISCOVERY ---
    elif (
        command.startswith("SEARCH MOVIES")
        or command.startswith("SEARCH MOVIE")
        or command.startswith("MOVIE ")
        or command.startswith("MOVIES ")
        or command in ["🎬 MOVIES", "MOVIES", "MOVIE", "TAMIL MOVIES", "LATEST MOVIES", "NEW MOVIES", "SEARCH MOVIES", "SEARCH MOVIE"]
    ):
        handle_movie_search(original_text, message)

    # --- PLAY SONG & MUSIC (SPOTIFY & YOUTUBE) ---
    elif command.startswith("PLAY YOUTUBE ") or command.startswith("YOUTUBE "):
        raw_query = original_text.replace("PLAY YOUTUBE", "").replace("YOUTUBE", "").strip()
        search_query = get_vibe_search_query(raw_query)
        play_youtube_video_smart(search_query, message)

    elif (
        command.startswith("PLAY SONG") 
        or command.startswith("PLAY SONGS") 
        or command.startswith("PLAY MUSIC")
        or command.startswith("SPOTIFY")
        or command.startswith("PLAY SPOTIFY")
        or command in ["PLAY SONGS", "PLAY SONG", "MUSIC", "SONGS", "SONG", "SPOTIFY"]
        or command.endswith(" SONGS") 
        or command.endswith(" SONG") 
        or (command.startswith("PLAY ") and not command.split(" ")[1] in steam_accounts and command not in ["PLAY ANIIMO", "PLAY ANIMO"])
    ):
        raw_query = original_text.replace("PLAY SPOTIFY", "").replace("SPOTIFY", "").strip()
        if not raw_query: raw_query = original_text
        search_query = get_vibe_search_query(raw_query)
        play_spotify_song(search_query, message)

    # --- ANIMO DIRECT LAUNCHER ---
    elif command in ["ANIIMO", "ANIMO", "OPEN ANIIMO", "OPEN ANIMO", "PLAY ANIIMO", "PLAY ANIMO", "START ANIIMO", "START ANIMO"]:
        bot.reply_to(message, "🎮 Launching Animo game...")
        try:
            pyautogui.press('win')
            time.sleep(1)
            pyautogui.write("Animo", interval=0.1)
            time.sleep(2)
            pyautogui.press('enter')
            handle_animo_start_adventure(message)
        except Exception as e:
            bot.reply_to(message, f"❌ Animo Launch Error: {e}")

    # --- STEAM GAME LAUNCHER WITH ACCOUNT ---
    elif command.startswith("PLAY "):
        parts = original_text.split(" ", 2)
        if len(parts) >= 3:
            account_name = parts[1].strip().upper()
            game_name = parts[2].strip()
            
            if account_name not in steam_accounts:
                bot.reply_to(message, f"❌ Account '{account_name}' not found. Please check your spelling.")
                return
                
            user = steam_accounts[account_name]["user"]
            pwd = steam_accounts[account_name]["pass"]

            try:
                login_steam_account(user, pwd, message)
                
                bot.reply_to(message, f"⏳ Waiting 5 seconds to launch '{game_name}'...")
                time.sleep(5) 
                
                game_upper = game_name.upper()
                if game_upper in steam_games and steam_games[game_upper] != "APP_ID_HERE":
                    app_id = steam_games[game_upper]
                    os.startfile(f"steam://run/{app_id}")
                    bot.reply_to(message, f"🎮 Launching {game_name} via Steam ID...")
                else:
                    pyautogui.press('win')
                    time.sleep(1)
                    pyautogui.write(game_name, interval=0.1)
                    time.sleep(2)
                    pyautogui.press('enter')
                    bot.reply_to(message, f"✅ '{game_name}' launched via Windows search!")

                if game_upper in ["ANIIMO", "ANIMO"]:
                    handle_animo_start_adventure(message)
                    
            except Exception as e:
                bot.reply_to(message, f"❌ Error: {e}")
        else:
            bot.reply_to(message, "⚠️ Invalid format. Use: `PLAY DHANEESH014 ANIIMO`", parse_mode="Markdown")

    # --- LOGIN STEAM ---
    elif command.startswith("LOGIN STEAM "):
        account_name = original_text[12:].strip().upper()
        if account_name in steam_accounts:
            user = steam_accounts[account_name]["user"]
            pwd = steam_accounts[account_name]["pass"]
            
            try:
                login_steam_account(user, pwd, message)
            except Exception as e:
                bot.reply_to(message, f"❌ Error logging into Steam: {e}")
        else:
            bot.reply_to(message, f"❌ Account '{account_name}' not found in your list.")

    # --- OPEN STEAM GAMES ---
    elif command.startswith("OPEN STEAM "):
        game_name = original_text[11:].strip()
        game_upper = game_name.upper()
        
        try:
            if game_upper in steam_games and steam_games[game_upper] != "APP_ID_HERE":
                app_id = steam_games[game_upper]
                os.startfile(f"steam://run/{app_id}")
                bot.reply_to(message, f"🎮 Launching {game_name} directly via Steam ID...")
            else:
                bot.reply_to(message, f"🔍 Searching for '{game_name}' on PC and launching...")
                pyautogui.press('win')
                time.sleep(1)
                pyautogui.write(game_name, interval=0.1)
                time.sleep(2) 
                pyautogui.press('enter')
                bot.reply_to(message, f"✅ '{game_name}' launched via Windows search!")
                
            if game_upper in ["ANIIMO", "ANIMO"]:
                handle_animo_start_adventure(message)
                
        except Exception as e:
            bot.reply_to(message, f"❌ Steam error: {e}")

    # --- CHROME & BRAVE BROWSERS ---
    elif command.startswith("OPEN CHROME") or command.startswith("OPEN BRAVE"):
        if command.startswith("OPEN CHROME"):
            browser_exe = "chrome"
            query_raw = original_text[11:].strip()
            browser_name = "Chrome"
        else:
            browser_exe = "brave"
            query_raw = original_text[10:].strip()
            browser_name = "Brave"
            
        direct_sites = {
            "YOUTUBE": "https://www.youtube.com",
            "WHATSAPP": "https://web.whatsapp.com",
            "TELEGRAM": "https://web.telegram.org",
            "INSTAGRAM": "https://www.instagram.com",
            "FACEBOOK": "https://www.facebook.com",
            "TWITTER": "https://twitter.com",
            "X": "https://twitter.com",
            "GMAIL": "https://mail.google.com",
            "AMAZON": "https://www.amazon.in",
            "FLIPKART": "https://www.flipkart.com",
            "NETFLIX": "https://www.netflix.com",
            "CHATGPT": "https://chat.openai.com",
            "CLAUDE": "https://claude.ai",
            "GITHUB": "https://github.com"
        }
        
        try:
            if query_raw:
                query_upper = query_raw.upper()
                
                if query_upper in direct_sites:
                    url = direct_sites[query_upper]
                    bot.reply_to(message, f"🌐 Launching {query_raw} directly in {browser_name}...")
                elif query_raw.startswith("http") or query_raw.startswith("www.") or ("." in query_raw and " " not in query_raw):
                    url = query_raw
                else:
                    encoded_query = urllib.parse.quote(query_raw)
                    url = f"https://www.google.com/search?q={encoded_query}"
                    
                subprocess.Popen(f'start /max {browser_exe} "{url}"', shell=True)
                bot.reply_to(message, f"✅ {browser_name} opened with: {query_raw}")
            else:
                subprocess.Popen(f"start /max {browser_exe}", shell=True)
                bot.reply_to(message, f"✅ {browser_name} opened.")
        except Exception as e:
            bot.reply_to(message, f"❌ Browser error: {e}")

    # --- UNIVERSAL OPEN ---
    elif command.startswith("OPEN "):
        app_to_open = original_text[5:].strip() 
        apps_and_websites = {
            "DISCORD": "discord:",       
            "STEAM": "steam:",           
            "VALORANT": "riotclient://"  
        }
        try:
            if app_to_open.upper() in apps_and_websites:
                target = apps_and_websites[app_to_open.upper()]
                os.startfile(target) 
                bot.reply_to(message, f"🎮 Launching application: {app_to_open}")
            elif os.path.exists(app_to_open):
                os.startfile(app_to_open)
                bot.reply_to(message, f"📂 Opened location on PC:\n`{app_to_open}`", parse_mode="Markdown")
            else:
                subprocess.Popen(f'start "" "{app_to_open}"', shell=True)
                bot.reply_to(message, f"✅ Attempting to open: {app_to_open}")
        except Exception as e:
            bot.reply_to(message, f"❌ Error opening {app_to_open}: {e}")

    else:
        bot.reply_to(
            message,
            "❌ Unknown command.\nTap /help or check the quick menu keyboard.",
            reply_markup=get_main_keyboard()
        )

PID_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.pid")


def write_pid_file():
    """Write the current process PID to the PID file."""
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def remove_pid_file():
    """Remove the PID file on clean exit."""
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except OSError:
        pass


def kill_existing_instances():
    """Kill any running bot.py instances — via PID file and by scanning Python processes."""
    current_pid = os.getpid()
    parent_pid = None
    try:
        parent_pid = psutil.Process(current_pid).ppid()
    except Exception:
        pass

    script_path = os.path.abspath(__file__).lower()
    script_name = os.path.basename(__file__).lower()
    python_exes = {'python.exe', 'pythonw.exe', 'py.exe', 'python3.exe', 'python', 'python3'}
    killed_any = False

    # --- Pass 1: Kill via PID file (fast path) ---
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                old_pid = int(f.read().strip())
            if old_pid != current_pid and old_pid != parent_pid:
                try:
                    old_proc = psutil.Process(old_pid)
                    p_name = (old_proc.name() or '').lower()
                    if p_name in python_exes and old_proc.is_running():
                        print(f"[!] Terminating previous bot instance (PID {old_pid})...", flush=True)
                        if platform.system() == "Windows":
                            subprocess.run(["taskkill", "/F", "/PID", str(old_pid)], capture_output=True)
                        else:
                            old_proc.kill()
                            old_proc.wait(timeout=5)
                        killed_any = True
                except psutil.NoSuchProcess:
                    pass
                except Exception as e:
                    print(f"[!] Could not terminate PID {old_pid}: {e}", flush=True)
        except Exception:
            pass
        finally:
            remove_pid_file()

    # --- Pass 2: Scan ALL Python processes for any untracked bot.py instances ---
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if proc.pid == current_pid or proc.pid == parent_pid:
                continue

            p_name = (proc.info.get('name') or '').lower()
            # CRITICAL: Only check python interpreter executables! Never kill powershell, cmd, ide, etc.
            if p_name not in python_exes:
                continue

            cmdline = [str(arg).lower() for arg in (proc.info.get('cmdline') or [])]
            # Ignore inline scripts like python -c "..."
            if '-c' in cmdline:
                continue

            # Verify that this python process is executing bot.py
            is_bot = any(
                arg == script_name
                or arg.endswith('\\' + script_name)
                or arg.endswith('/' + script_name)
                or arg == script_path
                for arg in cmdline
            )

            if is_bot:
                print(f"[!] Found existing bot instance (PID {proc.pid}), killing...", flush=True)
                if platform.system() == "Windows":
                    subprocess.run(["taskkill", "/F", "/PID", str(proc.pid)], capture_output=True)
                else:
                    try:
                        proc.terminate()
                        proc.wait(timeout=3)
                    except psutil.TimeoutExpired:
                        proc.kill()
                killed_any = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    if killed_any:
        print("[+] Existing instances stopped. Waiting for Telegram session to clear...", flush=True)
        time.sleep(3)


if __name__ == "__main__":
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')

    kill_existing_instances()  # Kill any previous instance
    write_pid_file()           # Claim ownership with current PID

    import atexit
    atexit.register(remove_pid_file)  # Clean up PID file on exit

    print("[+] Telegram PC Automation & Control Agent running...", flush=True)

    # Retry loop: handles residual 409 Conflict if Telegram API hasn't fully
    # released the previous session yet.
    for attempt in range(1, 10):
        try:
            bot.infinity_polling(skip_pending=True)
            break  # clean exit
        except Exception as e:
            err = str(e)
            if "409" in err or "Conflict" in err:
                wait = 3
                print(f"[!] 409 Conflict (session releasing). Retrying in {wait}s... (attempt {attempt}/10)", flush=True)
                time.sleep(wait)
            else:
                print(f"[!] Fatal error: {type(e).__name__}: {e}", flush=True)
                raise