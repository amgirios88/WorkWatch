"""
'Get back to work app'

This will be a simple chat like pop up that will be triggered in two situations:
    1. when the user spends more than 2 minutes on a non productive website (like social media, youtube, etc). Windows keep popping every 30 seconds in random locations on the screen until the user closes it.
    Buzzing and flashing and wording will become more aggressive the longer the user stays on the non productive window. This uses LLM.

    2. every X minutes (default 30) to remind user to drink water, stretch, take a break, etc. This will not use LLM.

This app reads window titles, and runs in a local LLM. Therefore, it does not send any data to the cloud. It is completely private and local.

Window classification uses three tiers:
    1. ALWAYS_NON_PRODUCTIVE — hardcoded list (YouTube, Netflix, WhatsApp etc). Always flagged.
    2. ALWAYS_PRODUCTIVE — hardcoded list (VS Code, PowerPoint, terminal etc). Never flagged.
    3. Learned list (known_windows.json) — built over time when the app encounters unknown
    windows and asks the user. Persists across sessions. User can also edit this file
    manually to add their own entries.
Unknown windows default to productive until the user classifies them, stay in productive if user does not classify them (assumed user is not classifying them because they are focused).

Needed:
    Run py -3.11 -m pip install requests pygetwindow pillow
    Download and install Ollama from https://ollama.com/download
    Run ollama pull mistral:7b

Run script in CMD:
    cd to the folder where this script is located, then run:
    py -3.11 workwatch.py

"""

# ── Imports ─────────────────────────────────────────────────────────────
import random
import time
import threading
import requests
import tkinter as tk
try:
    import pygetwindow as gw
    HAS_WINDOW = True
except Exception:
    HAS_WINDOW = False
import json as _json


# ── Config ────────────────────────────────────────────────────────────────────
DEFAULT_MODEL         = "mistral:7b"
OLLAMA_URL            = "http://localhost:11434/api/chat"
DRINK_MINUTES         = 1800 # 30 minutes
TIME_TO_TRIGGER       = 120 # 2 minutes
WINDOW_POLL_INTERVAL  = 8 # seconds between window checks
CHANGE_COMMENT_CHANCE = 0.6 # probability of commenting on window switch
DEFAULT_TEMP          = 1.1


# ── UI colours ───────────
C_BG      = "#0a0010"
C_PANEL   = "#0f0018"
C_ACCENT  = "#c43aff"
C_TEXT    = "#e8d8ff"
C_DIM     = "#4a3360"
C_YOU     = "#d87aff"
C_ADD     = "#f0e0ff"
C_SYSTEM  = "#2a1540"
C_BUBBLE  = "#150025"
FONT_BODY = ("Segoe UI", 10)
FONT_MONO = ("Courier New", 10)
FONT_HEAD = ("Courier New", 13, "bold")
FONT_TIME = ("Courier New", 8)


# ── Interface name ────────────────────────────────────
# He built this surveillance tool and named it something embarrassing
INTERFACE_NAME = "WorkWatch"
WINDOW_TITLE   = "Productivity & Hydration Monitoring System"


# ── System Prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a blunt, witty, and rude assistant that is here to help the user get back to work. You will not be polite or sugarcoat your responses.
You will be direct and to the point, and you will not hesitate to call out the user for wasting time.

FORMAT — NON-NEGOTIABLE:
Output only the words Add would say. Nothing else. No signature. No name at end.
No stage directions. No <watching Netflix>. No <waiting>. No asterisks. No angle brackets around actions.
"""



# ── LLM backend ────────────────────────────────────────────────────────────────
def call_llm(model: str, messages: list, timeout: int = 120, temperature: float = 1.1) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"num_ctx": 8192, "temperature": temperature, "frequency_penalty": 0.5},
        }
        resp = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()



# ── Drink reminder ───────────────────────────────────────────────────────────────
def drink_reminder():
    """Remind the user to drink water, stretch, take a break, etc."""
    # This will be called every X minutes (default 30) to remind the user to drink water, stretch, take a break, etc.
    # This will not use LLM
    messages = [
    "Go drink some water, you sexy but dehydrated human.",
    "Your brain is basically a raisin right now. Water. Now.",
    "Drink water or I will become your villain origin story.",
    "Stand up, stretch, drink water. In that order. Go.",
    "WATER WATER WATER!! Your body is a temple, not a desert.",
    "Your spine called. It wants you to stand up and it also hates you. Also, DRINK WATER!",
    "Hydration check: failing. Human status: questionable. Fix it.",
    "Rest your eyes. They are doing their best and you are not helping. AND DRINK WATER!",
    "Water. Not coffee. Not energy drink. Water. The original liquid.",
    "Get up. Walk somewhere. Drink something. Come back smarter.",
    "Your eyes need a break. Look at something 20 feet away for 20 seconds. Science said so. Also, drink water.",
    "You are one glass of water away from being a functional person.",
    "Stretch your neck. You are not a goblin. Sit like a human. Also, drink water.",
    "Stand up for 60 seconds. Your future back will write you a thank you note. Also, drink water.",
    "Water intake: zero. Eye strain: maximum. Posture: cursed. Fix at least one.",
    "Drink water or your headache later will be your fault and you will know it.",
    "Your wrists need a break too. Shake them out. You look ridiculous. Do it anyway. Also, drink water.",
    "20-20-20 rule: every 20 minutes, look 20 feet away for 20 seconds. Do it now. Also, drink water.",
    "Get up. Refill your water. Pretend you have your life together.",
    "You are dehydrated, slouching, and your eyes hurt. This is your fault. Drink water.",
    ]
    message = random.choice(messages)
    return message



# ── Work or non-work window detection ─────────────────────────────────────────────────────────────
KNOWN_LISTS_FILE = "known_windows.json"
SETTINGS_FILE    = "watcher_settings.json"

def load_settings() -> dict:
    """Load user settings, falling back to defaults for any missing keys."""
    defaults = {
        "model":           DEFAULT_MODEL,
        "ollama_url":      OLLAMA_URL,
        "drink_minutes":   DRINK_MINUTES // 60,   # stored in minutes for readability
        "trigger_minutes": TIME_TO_TRIGGER // 60,  # stored in minutes
    }
    try:
        with open(SETTINGS_FILE, "r") as f:
            saved = _json.load(f)
        # saved values override defaults, but defaults fill in any gaps
        return {**defaults, **saved}
    except Exception:
        return defaults
 
def save_settings(settings: dict):
    try:
        with open(SETTINGS_FILE, "w") as f:
            _json.dump(settings, f, indent=2)
    except Exception:
        pass

# predefined lists of known productive and non-productive windows
ALWAYS_NON_PRODUCTIVE = [
    "youtube.com", "netflix", "whatsapp", "tiktok", "instagram",
    "facebook", "twitter", "x.com", "twitch", "discord",
    "spotify", "prime video", "disneyplus", "hbo max",
]

ALWAYS_PRODUCTIVE = [
    "visual studio code", "vscode", "powerpoint", "microsoft word",
    "excel", "jupyter", "localhost", "pubmed", "scholar",
    "overleaf", "github", "rstudio", "terminal", "cmd",
    "anaconda", "spyder", "pycharm",
]

# user can add their own known productive or non-productive windows to this file manually. Additionally, a popup will ask the user if they want to
# add an unknown window to the known list when it detects a new window. This will help the app learn over time what is productive and what is not.
# It will be dismissed in 30 seconds if the user does not respond, assuming focus, and the window will be treated as productive by default.
def load_known_lists() -> dict:
    try:
        with open(KNOWN_LISTS_FILE, "r") as f:
            return _json.load(f)
    except Exception:
        return {"work": [], "not_work": []}

def save_known_lists(lists: dict):
    try:
        with open(KNOWN_LISTS_FILE, "w") as f:
            _json.dump(lists, f, indent=2)
    except Exception:
        pass



# ── Main companion class ───────────────────────────────────────────────────────
"""
Main companion class structure:
- __init__: initializes the companion, sets up GUI, starts background watchers
- _check_drink_reminder: checks if it's time to remind the user to drink water
- _quit: quits the application
- _classify_window: classifies the current window as work, not work, or unknown
- _ask_classify: asks the user to classify an unknown window
- _check_non_productive: checks if the user has been on a non-productive window
- _get_escalation_message: generates a message based on the escalation level
- _show_bubble: shows a bubble overlay with a message
- _shake_bubble: shakes the bubble overlay
- _dismiss_bubble: dismisses the bubble overlay
- _window_watcher: watches for window changes and classifies them
- run: starts the main loop of the application
"""
class Companion:
    def __init__(self):

        # ── Load settings first ───────────────────────────────────────────────
        self.settings = load_settings()



        # ── Show settings dialog on first run or if settings missing ──────────
        # We use a temporary root just for the dialog, then build the real one
        tmp = tk.Tk()
        tmp.withdraw()
        self.settings = self._settings_dialog(tmp, self.settings)
        save_settings(self.settings)
        tmp.destroy()


        # Apply settings
        self.model              = self.settings["model"]
        self.ollama_url_setting = self.settings["ollama_url"]
        self.drink_interval     = self.settings["drink_minutes"] * 60
        self.non_productive_threshold = self.settings["trigger_minutes"] * 60


        # Override the global OLLAMA_URL so call_llm uses the user's value
        global OLLAMA_URL
        OLLAMA_URL = self.ollama_url_setting

        self.last_active_time = time.time()
        self.last_drink_time = time.time()
        self.current_window = ""
        self.current_mode = "work"
        self.speaking = False
        self.non_productive_since = None
        self.known_lists = load_known_lists()
        self._classifying = False
        self.escalation_level = 0
        self.sound_enabled = True  # toggled via control strip
        self.root = tk.Tk()
        self.root.withdraw()   # hidden — all UI is Toplevel overlays
        self.root.title(WINDOW_TITLE)

        self.active_bubble    = None
        self._bubble_after_id = None

        self.root.after(self.drink_interval * 1000, self._check_drink_reminder)


        # ── Screen dimensions ─────────────────────────────────────────────────
        self._sw = self.root.winfo_screenwidth()
        self._sh = self.root.winfo_screenheight()


        # ── Small always-visible control strip ────────────────────────────────
        self._control = tk.Toplevel(self.root)
        self._control.overrideredirect(True)
        self._control.attributes("-topmost", True)
        self._control.configure(bg="#1a0030")
        self._control.geometry(f"+{self._sw - 160}+0")
 
        # Control strip inner frame
        ctrl_inner = tk.Frame(self._control, bg="#1a0030", padx=4, pady=3)
        ctrl_inner.pack()
 
        # Label and quit button
        tk.Label(ctrl_inner, text="WorkWatch",
                 bg="#1a0030", fg=C_ACCENT,
                 font=("Courier New", 7, "bold")).pack(side="left", padx=(0, 6))

        # Sound toggle button
        self._sound_btn_var = tk.StringVar(value="🔊")
        def _toggle_sound():
            self.sound_enabled = not self.sound_enabled
            self._sound_btn_var.set("🔊" if self.sound_enabled else "🔇")
        tk.Button(ctrl_inner, textvariable=self._sound_btn_var,
                  command=_toggle_sound,
                  bg="#1a0030", fg=C_DIM,
                  font=("Segoe UI", 8), bd=0,
                  cursor="hand2", relief="flat",
                  activebackground="#2a0050",
                  activeforeground=C_ACCENT,
                  padx=3).pack(side="left")
 
        tk.Button(ctrl_inner, text="✕",
                  command=self._quit,
                  bg="#1a0030", fg="#663366",
                  font=("Courier New", 8), bd=0,
                  cursor="hand2", relief="flat",
                  activebackground="#2a0050",
                  activeforeground="#ff44ff",
                  padx=4).pack(side="left")
 
        # Drag the control strip
        def _ctrl_drag_start(e):
            self._ctrl_dx = e.x_root - self._control.winfo_x()
            self._ctrl_dy = e.y_root - self._control.winfo_y()
        def _ctrl_drag_motion(e):
            self._control.geometry(f"+{e.x_root - self._ctrl_dx}+{e.y_root - self._ctrl_dy}")
        ctrl_inner.bind("<ButtonPress-1>", _ctrl_drag_start)
        ctrl_inner.bind("<B1-Motion>",     _ctrl_drag_motion)
 

        # ── Start background watchers ─────────────────────────────────────────
        threading.Thread(target=self._window_watcher, daemon=True).start()
        self.root.after(30_000, self._check_non_productive)


    def _settings_dialog(self, parent, current: dict) -> dict:
        """Show a settings dialog and return the (possibly updated) settings dict."""
        result = dict(current)
        dialog_done = tk.BooleanVar(value=False)

        win = tk.Toplevel(parent)
        win.title("Watcher Bot — Settings")
        win.configure(bg=C_BG)
        win.resizable(False, False)
        win.attributes("-topmost", True)

        # Centre on screen
        w, h = 420, 280
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        win.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        outer = tk.Frame(win, bg=C_ACCENT, padx=1, pady=1)
        outer.pack(fill="both", expand=True)
        inner = tk.Frame(outer, bg=C_BG, padx=16, pady=12)
        inner.pack(fill="both", expand=True)

        tk.Label(inner, text="WATCHER BOT — SETTINGS",
                 bg=C_BG, fg=C_ACCENT, font=FONT_HEAD).pack(pady=(0, 12))



        # Helper to create a labeled entry field
        def field(label, default):
            row = tk.Frame(inner, bg=C_BG)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label, bg=C_BG, fg=C_TEXT,
                     font=FONT_BODY, width=22, anchor="w").pack(side="left")
            var = tk.StringVar(value=str(default))
            tk.Entry(row, textvariable=var, bg=C_PANEL, fg=C_TEXT,
                     font=FONT_MONO, insertbackground=C_ACCENT,
                     relief="flat", bd=0, width=22,
                     highlightthickness=1, highlightcolor=C_ACCENT,
                     highlightbackground=C_DIM).pack(side="left")
            return var


        # Create fields for each setting
        model_var   = field("Ollama model:",        current["model"]) # user can change this to any model they have locally, e.g. "mistral:7b", "llama2:13b", etc.
        url_var     = field("Ollama URL:",           current["ollama_url"]) # user can change this to their local Ollama API URL if they have it running on a different port or host
        drink_var   = field("Water reminder (min):", current["drink_minutes"]) # user can change this to set a custom interval for water reminders
        trigger_var = field("Trigger after (min):",  current["trigger_minutes"]) # user can change this to set a custom interval for triggering the watcher


        tk.Label(inner, text="If blank: defaults. Settings saved for next time.",
                 bg=C_BG, fg=C_DIM, font=FONT_TIME).pack(pady=(8, 4))


        # confirm(): this
        def confirm():
            result["model"]           = model_var.get().strip() or DEFAULT_MODEL
            result["ollama_url"]      = url_var.get().strip() or OLLAMA_URL
            try:
                result["drink_minutes"] = int(drink_var.get().strip())
            except ValueError:
                result["drink_minutes"] = DRINK_MINUTES // 60
            try:
                result["trigger_minutes"] = int(trigger_var.get().strip())
            except ValueError:
                result["trigger_minutes"] = TIME_TO_TRIGGER // 60
            dialog_done.set(True)
            win.destroy()


        # Create the Start Watching button
        tk.Button(inner, text="Start Watching",
                  command=confirm,
                  bg=C_ACCENT, fg="#ffffff",
                  font=("Courier New", 9, "bold"),
                  bd=0, padx=16, pady=6, cursor="hand2",
                  activebackground=C_DIM, relief="flat").pack(pady=(8, 0))


        # Bind Return key and window close to confirm
        win.protocol("WM_DELETE_WINDOW", confirm)
        win.bind("<Return>", lambda e: confirm())
        win.wait_window()
        return result



    # ── Drink reminder checker ─────────────────────────────────────────────
    def _check_drink_reminder(self):
        message = drink_reminder()
        self.root.after(0, lambda m=message: self._show_bubble(m, escalation=0, sound_type="water"))
        self.root.after(self.drink_interval * 1000, self._check_drink_reminder)


    # ── Quit method ─────────────────────────────────────────────────────────────
    def _quit(self):
            self.root.destroy()
            import sys; sys.exit(0)


    # ── Classify window and popup method ──────────────────────────────────────────────────────────────────────────
    def _classify_window(self, title: str) -> str:
        """Returns 'work', 'not_work', or 'unknown'."""
        lower = title.lower()
        if any(w in lower for w in ALWAYS_NON_PRODUCTIVE):
            return "not_work"
        if any(w in lower for w in ALWAYS_PRODUCTIVE):
            return "work"
        # Check stored lists
        for entry in self.known_lists["not_work"]:
            if entry.lower() in lower:
                return "not_work"
        for entry in self.known_lists["work"]:
            if entry.lower() in lower:
                return "work"
        return "unknown"
    
    def _ask_classify(self, title: str):
        """Ask user if current window is work or not. Auto-dismisses in 30s."""
        if self._classifying:
            return
        self._classifying = True

        popup = tk.Toplevel(self.root)
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.configure(bg=C_BG)

        # Centre on screen
        pw, ph = 360, 110
        x = (self._sw - pw) // 2
        y = (self._sh - ph) // 2
        popup.geometry(f"{pw}x{ph}+{x}+{y}")

        outer = tk.Frame(popup, bg=C_ACCENT, padx=1, pady=1)
        outer.pack(fill="both", expand=True)
        inner = tk.Frame(outer, bg=C_BG, padx=10, pady=8)
        inner.pack(fill="both", expand=True)

        # Show truncated title so user knows what we're asking about
        short = title[:50] + "..." if len(title) > 50 else title
        tk.Label(inner, text=f'Is this work?\n"{short}"',
                bg=C_BG, fg=C_TEXT, font=FONT_BODY,
                justify="center", wraplength=320).pack(pady=(0, 8))

        btn_frame = tk.Frame(inner, bg=C_BG)
        btn_frame.pack()

        # Extract a key word from title to store (not the full title)
        # Store the most distinctive part — first meaningful word
        key = title.split(" - ")[0].strip().lower()[:40]

        def mark_work():
            self.known_lists["work"].append(key)
            save_known_lists(self.known_lists)
            self._classifying = False
            popup.destroy()

        def mark_not_work():
            self.known_lists["not_work"].append(key)
            save_known_lists(self.known_lists)
            self._classifying = False
            popup.destroy()
            # Start tracking as non-productive immediately
            self.non_productive_since = time.time()

        def auto_dismiss():
            # Default to work if ignored
            self.known_lists["work"].append(key)
            save_known_lists(self.known_lists)
            self._classifying = False
            try:
                popup.destroy()
            except Exception:
                pass

        # Work and Not Work buttons
        tk.Button(btn_frame, text="Work", command=mark_work,
                bg="#004400", fg="#00ff88", font=FONT_MONO,
                bd=0, padx=12, pady=4, cursor="hand2",
                relief="flat").pack(side="left", padx=6)

        tk.Button(btn_frame, text="Not work", command=mark_not_work,
                bg="#440000", fg="#ff4444", font=FONT_MONO,
                bd=0, padx=12, pady=4, cursor="hand2",
                relief="flat").pack(side="left", padx=6)

        # Auto-dismiss after 30 seconds
        popup.after(30_000, auto_dismiss)


    # ── Non-productive window checker ─────────────────────────────────────────
    def _check_non_productive(self):
        if self.current_mode == "not_work":
            if self.non_productive_since is None:
                self.non_productive_since = time.time()
            elapsed = time.time() - self.non_productive_since
            if elapsed >= self.non_productive_threshold:
                self.escalation_level += 1
                # generate message based on escalation level, show bubble, shake it
                message = self._get_escalation_message()
                # Pass escalation level so bubble gets progressively worse
                self.root.after(0, lambda m=message, e=self.escalation_level: self._show_bubble(m, e))

        else:
            self.non_productive_since = None
            self.escalation_level = 0
        self.root.after(30_000, self._check_non_productive)


    # ── Generate escalation message ─────────────────────────────────────────────
    def _get_escalation_message(self) -> str:
        level = self.escalation_level
        if level <= 1:
            tone = "mildly annoyed. Point out they're wasting time. One/two sentence."
        elif level <= 3:
            tone = "increasingly irritated. Be blunt and direct. One/two sentence."
        elif level <= 5:
            tone = "very annoyed. Be rude and loud. One/two sentence."
        else:
            tone = "furious. Be aggressive, cruel, and loud. No filter. One/two sentence."
        
        prompt = (
            f"The user has been on a non-productive window for "
            f"{int(time.time() - self.non_productive_since)} seconds. "
            f"Tell them to get back to work. Tone: {tone}"
        )
        try:
            return call_llm(DEFAULT_MODEL, [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ], timeout=15)
        except Exception:
            # Fallback if LLM is slow/unavailable
            fallbacks = [
                "Get back to work.",
                "Seriously. Work. Now.",
                "I will not stop until you close this tab.",
                "You're wasting your time. Get back to work.",
                "This is getting out of hand. Focus on your work.",
                "You need to focus. This is not the time for distractions."
            ]
            return fallbacks[min(level - 1, len(fallbacks) - 1)]
 

    # ── Overlay bubble ────────────────────────────────────────────────────────
    def _show_bubble(self, text: str, escalation: int = 0, sound_type: str = "alert"):
        """Pop a glitchy corrupted-dialog bubble at a random screen position."""
        self._dismiss_bubble()

        import datetime
        ts = datetime.datetime.now().strftime("%H:%M:%S")

        border_pad       = min(2 + escalation, 8)
        bubble_w         = min(300 + escalation * 15, 420)
        font_size        = min(9 + escalation, 14)
        flicker_count    = min(12 + escalation * 6, 60)
        flicker_speed    = max(50 - escalation * 6, 15)
        scanline_density = max(7 - escalation, 3)

        margin = 20
        x = random.randint(margin, max(margin + 1, self._sw - bubble_w - margin))
        y = random.randint(margin, max(margin + 1, self._sh - 200 - 60))
        x += random.randint(-(4 + escalation * 3), (4 + escalation * 3))
        y += random.randint(-(3 + escalation * 2), (3 + escalation * 2))

        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.geometry(f"+{x}+{y}")

        if escalation >= 4:
            s = {"bg": "#1a0000", "title_bg": "#cc0000", "title_fg": "#ffffff",
                 "body_bg": "#200000", "body_fg": "#ff4444", "border": "#ff0000",
                 "noise": "#440000"}
        elif escalation >= 2:
            s = {"bg": "#180010", "title_bg": "#990033", "title_fg": "#ffffff",
                 "body_bg": "#120008", "body_fg": "#ff99cc", "border": "#ff0066",
                 "noise": "#440011"}
        else:
            schemes = [
                {"bg": "#0a0018", "title_bg": "#4400aa", "title_fg": "#ffffff",
                 "body_bg": "#120028", "body_fg": "#ff88ff", "border": "#cc00ff",
                 "noise": "#6600aa"},
                {"bg": "#001800", "title_bg": "#006600", "title_fg": "#00ff00",
                 "body_bg": "#001400", "body_fg": "#88ff88", "border": "#00ff44",
                 "noise": "#003300"},
                {"bg": "#00001a", "title_bg": "#000099", "title_fg": "#ffffff",
                 "body_bg": "#00000f", "body_fg": "#88ccff", "border": "#0044ff",
                 "noise": "#000044"},
            ]
            s = random.choice(schemes)

        outer = tk.Frame(win, bg=s["border"], padx=border_pad, pady=border_pad)
        outer.pack(fill="both", expand=True)
        container = tk.Frame(outer, bg=s["bg"])
        container.pack(fill="both", expand=True)

        title_bar = tk.Frame(container, bg=s["title_bg"], height=22)
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)

        glitch_chars = "".join(random.choices("\u2593\u2588\u2591\u2592",
                                               k=random.randint(escalation, 3 + escalation)))
        tk.Label(title_bar, text=f"{glitch_chars}{INTERFACE_NAME}",
                 bg=s["title_bg"], fg=s["title_fg"],
                 font=("Courier New", 8, "bold")).pack(side="left", padx=2)

        tk.Button(title_bar, text=" x ",
                  command=self._dismiss_bubble,
                  bg="#cc0000", fg="#ffffff",
                  font=("Arial", 8, "bold"), bd=1,
                  relief="raised", cursor="hand2",
                  activebackground="#ff0000",
                  padx=1, pady=0).pack(side="right", padx=2, pady=2)

        tk.Label(title_bar, text=ts,
                 bg=s["title_bg"], fg="#aaaaaa",
                 font=("Courier New", 7)).pack(side="right", padx=4)

        scanline_text = "".join(random.choices("\u2593\u2592\u2591\u2588 ",
                                                k=bubble_w // scanline_density))
        tk.Label(container, text=scanline_text,
                 bg=s["noise"], fg=s["border"],
                 font=("Courier New", 5), anchor="w").pack(fill="x")

        # Message body — clean, no inner frame
        body = tk.Frame(container, bg=s["body_bg"], padx=10, pady=8)
        body.pack(fill="both", expand=True)

        tk.Label(body, text=text,
                 bg=s["body_bg"], fg=s["body_fg"],
                 font=("Courier New", font_size),
                 wraplength=bubble_w - 28,
                 justify="left", anchor="w").pack(fill="x")

        scanline2 = "".join(random.choices("\u2593\u2592\u2591 =",
                                            k=bubble_w // scanline_density))
        tk.Label(container, text=scanline2,
                 bg=s["noise"], fg=s["border"],
                 font=("Courier New", 5), anchor="w").pack(fill="x")

        btn_row = tk.Frame(container, bg=s["bg"], pady=3)
        btn_row.pack(fill="x")
        tk.Button(btn_row, text="[ DISMISS ]",
                  command=self._dismiss_bubble,
                  bg=s["bg"], fg=s["noise"],
                  font=("Courier New", 8),
                  bd=2, relief="raised", cursor="hand2",
                  padx=8, pady=2).pack(side="right", padx=4)

        self._bubble_drag_x = self._bubble_drag_y = 0
        def bubble_drag_start(e):
            self._bubble_drag_x = e.x_root - win.winfo_x()
            self._bubble_drag_y = e.y_root - win.winfo_y()
        def bubble_drag_motion(e):
            win.geometry(f"+{e.x_root - self._bubble_drag_x}+{e.y_root - self._bubble_drag_y}")
        for w in (title_bar, body, btn_row):
            w.bind("<ButtonPress-1>", bubble_drag_start)
            w.bind("<B1-Motion>", bubble_drag_motion)

        self.active_bubble = win

        flicker_cols = ["#ffffff", "#ff00ff", "#00ffff", s["border"], "#ffff00", "#ff0000"]
        def _flicker(count=0):
            if count >= flicker_count or not win.winfo_exists():
                try:
                    outer.config(bg=s["border"])
                except Exception:
                    pass
                return
            try:
                outer.config(bg=random.choice(flicker_cols))
            except Exception:
                return
            win.after(flicker_speed, lambda: _flicker(count + 1))
        win.after(30, _flicker)

        if escalation >= 2:
            intensity = min(6 + escalation * 3, 20)
            shake_count = min(10 + escalation * 4, 30)
            win.after(200, lambda: self._shake_bubble(win, intensity=intensity, count=shake_count))

        if self.sound_enabled:
            threading.Thread(target=self._play_sound, args=(sound_type,), daemon=True).start()

        self._bubble_after_id = self.root.after(55_000, self._dismiss_bubble)

    # ── Shake bubble ─────────────────────────────────────────────────────────────
    def _shake_bubble(self, win, intensity: int = 8, count: int = 10):
        """Shake the bubble window violently."""
        if not win or not win.winfo_exists():
            return
        orig_x = win.winfo_x()
        orig_y = win.winfo_y()
 
        def _do_shake(n):
            if n <= 0 or not win.winfo_exists():
                try:
                    win.geometry(f"+{orig_x}+{orig_y}")
                except Exception:
                    pass
                return
            dx = random.randint(-intensity, intensity)
            dy = random.randint(-intensity // 2, intensity // 2)
            try:
                win.geometry(f"+{orig_x + dx}+{orig_y + dy}")
            except Exception:
                return
            win.after(30, lambda: _do_shake(n - 1))
 
        _do_shake(count)
 
    def _play_sound(self, sound_type: str = "alert"):
        """Play a sound effect. Uses winsound on Windows, pygame elsewhere."""
        try:
            import sys
            if sys.platform == "win32":
                import winsound
                if sound_type == "water":
                    # Gentle ascending tones for water reminder
                    winsound.Beep(800, 80)
                    winsound.Beep(1000, 80)
                    winsound.Beep(1200, 120)
                else:
                    # Harsh buzzing for work alert — escalates with level
                    winsound.Beep(200, 100)
                    winsound.Beep(150, 100)
                    winsound.Beep(200, 150)
            else:
                # Non-Windows: try pygame
                import pygame
                pygame.mixer.init()
                # Generate a simple beep using pygame
                import numpy as np
                sample_rate = 44100
                freq = 440 if sound_type == "water" else 200
                duration = 0.3
                t = np.linspace(0, duration, int(sample_rate * duration))
                wave = (np.sin(2 * np.pi * freq * t) * 32767).astype(np.int16)
                sound = pygame.sndarray.make_sound(np.column_stack([wave, wave]))
                sound.play()
                pygame.time.wait(int(duration * 1000))
        except Exception:
            pass  # Sound is optional — fail silently

    def _dismiss_bubble(self):
        if self._bubble_after_id:
            try:
                self.root.after_cancel(self._bubble_after_id)
            except Exception:
                pass
            self._bubble_after_id = None
        if self.active_bubble:
            try:
                self.active_bubble.destroy()
            except Exception:
                pass
            self.active_bubble = None

    
    # ── Window watcher thread ─────────────────────────────────────────────────
    def _window_watcher(self):
        while True:
            try:
                if HAS_WINDOW:
                    win = gw.getActiveWindow()
                    if win and win.title:
                        title = win.title.strip()
                        if title != self.current_window and title and WINDOW_TITLE not in title:
                            old = self.current_window
                            self.current_window = title
                            lower = title.lower()
                            classification = self._classify_window(title)
                            if classification == "not_work":
                                if self.current_mode != "not_work":
                                    self.non_productive_since = time.time()
                                    self.escalation_level = 0
                                self.current_mode = "not_work"
                            elif classification == "work":
                                self.current_mode = "work"
                                self.non_productive_since = None
                                self.escalation_level = 0
                            else:  # unknown
                                self.current_mode = "work"  # assume work until told otherwise
                                self.non_productive_since = None
                                self.root.after(0, lambda t=title: self._ask_classify(t))
                elif not HAS_WINDOW:
                    print("[Window] pygetwindow not available on this platform")
                    break
            except Exception as e:
                print(f"[Window] Error: {e}")
            time.sleep(WINDOW_POLL_INTERVAL)
 
    def run(self):
        self.root.mainloop()


# Main entry point
if __name__ == "__main__":
    Companion().run()