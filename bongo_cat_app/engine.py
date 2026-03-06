#!/usr/bin/env python3
"""
Bongo Cat Monitoring Engine - Wayland/Hyprland compatible
Based on the original implementation, with pynput replaced by evdev
for Linux/Wayland/Hyprland support.

Fix: device.grab() is NOT used, so the keyboard remains usable.

Requirements:
    pip install evdev psutil pyserial

Permissions:
    sudo usermod -a -G input $USER   (then log out and back in)
"""

import time
import serial
import serial.tools.list_ports
import threading
from collections import deque
import psutil
import datetime
from typing import Callable, Any

# ---------------------------------------------------------------------------
# Wayland-compatible keyboard detection
# ---------------------------------------------------------------------------
USING_EVDEV = False
try:
    from evdev import InputDevice, categorize, ecodes, list_devices
    USING_EVDEV = True
    print("[engine] Using evdev for keyboard input (Wayland/Linux compatible)")
except ImportError:
    try:
        from pynput import keyboard as pynput_keyboard
        print("[engine] Using pynput for keyboard input (X11/Windows/Mac)")
    except ImportError:
        print("[engine] WARNING: Neither evdev nor pynput found. Keyboard detection disabled.")
        print("[engine] Install evdev:  pip install evdev")


def _find_keyboard_devices():
    keyboards = []
    try:
        for path in list_devices():
            try:
                device = InputDevice(path)
                caps = device.capabilities()
                if ecodes.EV_KEY in caps and ecodes.KEY_A in caps.get(ecodes.EV_KEY, []):
                    keyboards.append(device)
                    print(f"[engine] Found keyboard: {device.name} at {device.path}")
            except Exception:
                pass
    except Exception as e:
        print(f"[engine] Error enumerating input devices: {e}")
        print("[engine]   sudo usermod -a -G input $USER  (then re-login)")
    return keyboards


class _KeyboardMonitor:
    def __init__(self, on_keypress: Callable):
        self.callback = on_keypress
        self._threads = []
        self._running = False

    def start(self):
        self._running = True
        if USING_EVDEV:
            self._start_evdev()
        else:
            self._start_pynput()

    def stop(self):
        self._running = False

    def _start_evdev(self):
        devices = _find_keyboard_devices()
        if not devices:
            print("[engine] No keyboard devices found. Check /dev/input/ permissions.")
            return
        for device in devices:
            t = threading.Thread(target=self._evdev_listener, args=(device,), daemon=True)
            t.start()
            self._threads.append(t)

    def _evdev_listener(self, device):
        # NO device.grab() — keyboard must remain usable by the rest of the system
        try:
            for event in device.read_loop():
                if not self._running:
                    break
                if event.type == ecodes.EV_KEY:
                    key_event = categorize(event)
                    if key_event.keystate == 1:  # key-down only
                        self.callback()
        except OSError as e:
            print(f"[engine] evdev error on {device.name}: {e}")

    def _start_pynput(self):
        try:
            def on_press(key):
                self.callback()
            listener = pynput_keyboard.Listener(on_press=on_press)
            listener.daemon = True
            listener.start()
            self._threads.append(listener)
        except Exception as e:
            print(f"[engine] pynput error: {e}")


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

class BongoCatEngine:
    """Bongo Cat engine — original logic with Wayland keyboard support."""

    def __init__(self, config_manager=None):
        self.config = config_manager
        self.tray   = None

        if self.config:
            conn = self.config.get_connection_settings()
            self.port     = conn.get('com_port', 'AUTO')
            self.baudrate = conn.get('baudrate', 115200)
            beh = self.config.get_behavior_settings()
            self.idle_timeout  = beh.get('idle_timeout_seconds', 1.0)
            self.sleep_timeout = beh.get('sleep_timeout_minutes', 1) * 60
            print(f"⏰ Timeouts: Idle={self.idle_timeout}s, Sleep={self.sleep_timeout}s")
            if hasattr(self.config, 'add_change_callback'):
                self.config.add_change_callback(self._on_config_change)
        else:
            self.port          = 'AUTO'
            self.baudrate      = 115200
            self.idle_timeout  = 1.0
            self.sleep_timeout = 60

        self.serial_conn = None
        self.running     = False

        # Animation control
        self.last_sent_speed      = -1
        self.last_sent_state      = ""
        self.last_command_time    = 0
        self.min_command_interval = 0.5

        # Keystroke tracking
        t = time.time()
        self.keystroke_buffer    = deque(maxlen=50)
        self.last_keystroke_time = t
        self.typing_active       = False
        self.idle_start_time     = t
        self.sleep_start_time    = None

        # WPM
        self.wpm_history     = deque(maxlen=2)
        self.raw_wpm_history = deque(maxlen=3)
        self.current_wpm     = 0
        self.max_wpm         = 200
        self.chars_per_word  = 5.0
        self.min_animation_speed = 500
        self.max_animation_speed = 40

        # WPM thresholds (based on original)
        self.slow_threshold   = 20
        self.normal_threshold = 40
        self.fast_threshold   = 65
        self.streak_threshold = 85

        # State machine
        self.current_state     = "IDLE"
        self.last_sent_state   = "IDLE"
        self.last_streak_state = False

        # Timing
        self.update_interval       = 0.08
        self.stats_update_interval = 0.5  # aggiorna display ogni 500ms
        self.last_stats_update     = 0

        # System stats
        self.cpu_percent            = 0
        self.ram_percent            = 0
        self.system_monitor_running = False
        self.system_monitor_thread  = None

        self.idle_progression_started = False

        self._data_lock   = threading.Lock()
        self._serial_lock = threading.Lock()

        self._keyboard_monitor = _KeyboardMonitor(self._on_keystroke)

    # --- public interface required by main.py ---

    def set_tray_reference(self, tray):
        self.tray = tray
        print("🔗 Engine connected to system tray for status updates")

    def start_monitoring(self):
        """Called by main.py on the main thread. Blocks until stopped."""
        self._start_internal()
        try:
            while self.running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass

    def stop_monitoring(self):
        self._stop_internal()

    # --- config ---

    def _on_config_change(self, key: str, value: Any):
        if key == "behavior.idle_timeout_seconds":
            self.idle_timeout = value
        elif key == "behavior.sleep_timeout_minutes":
            self.sleep_timeout = value * 60

    # --- serial ---

    def _find_port(self):
        if self.port and self.port != 'AUTO':
            return self.port
        for p in serial.tools.list_ports.comports():
            desc = (p.description or "").lower()
            hwid  = (p.hwid or "").lower()
            if any(x in desc or x in hwid for x in ["cp210", "ch340", "ftdi", "esp32", "uart", "usb serial"]):
                print(f"[engine] Auto-detected ESP32 at: {p.device}")
                return p.device
        return None

    def _connect(self):
        port = self._find_port()
        if not port:
            return False
        try:
            with self._serial_lock:
                self.serial_conn = serial.Serial(port, self.baudrate, timeout=1)
            print(f"[engine] Connected to ESP32 at {port}")
            if self.tray:
                try:
                    self.tray.update_connection_status(True, port)
                except Exception:
                    pass
            return True
        except serial.SerialException as e:
            print(f"[engine] Serial connection error: {e}")
            return False

    def send_command(self, command: str):
        try:
            with self._serial_lock:
                if self.serial_conn and self.serial_conn.is_open:
                    self.serial_conn.write(f"{command}\n".encode('utf-8'))
                    self.serial_conn.flush()
                    print(f"[serial] >> {command}")
        except serial.SerialException as e:
            print(f"[engine] Serial write error: {e}")
            self.serial_conn = None

    # --- keyboard callback ---

    def _on_keystroke(self):
        t = time.time()
        with self._data_lock:
            self.keystroke_buffer.append(t)
            self.last_keystroke_time      = t
            self.typing_active            = True
            self.idle_start_time          = t
            self.idle_progression_started = False

    # --- WPM ---

    def _calculate_wpm(self) -> float:
        now = time.time()
        with self._data_lock:
            keystrokes = list(self.keystroke_buffer)

        if len(keystrokes) < 2:
            return 0.0

        # Finestra corta (5s) per risposta rapida
        window = 5.0
        recent = [t for t in keystrokes if now - t <= window]
        if len(recent) < 2:
            return 0.0

        time_span = recent[-1] - recent[0]
        if time_span < 0.2:
            return 0.0

        raw_wpm = (len(recent) / self.chars_per_word) / (time_span / 60.0)
        # Smoothing minimo: solo 2 campioni per reattivita'
        self.raw_wpm_history.append(raw_wpm)
        smoothed = sum(self.raw_wpm_history) / len(self.raw_wpm_history)
        return min(smoothed, self.max_wpm)

    def _wpm_to_speed(self, wpm: float) -> int:
        if wpm <= 0:
            return self.min_animation_speed
        ratio = min(wpm, self.max_wpm) / self.max_wpm
        speed = int(self.min_animation_speed - ratio * (self.min_animation_speed - self.max_animation_speed))
        return max(self.max_animation_speed, min(self.min_animation_speed, speed))

    # --- system stats ---

    def _system_monitor_loop(self):
        # Prima chiamata senza interval per inizializzare il contatore interno di psutil
        psutil.cpu_percent(interval=None)
        time.sleep(1.0)  # aspetta 1s per avere un delta valido
        while self.system_monitor_running:
            # interval=None = non bloccante, usa il delta dall'ultima chiamata
            cpu = psutil.cpu_percent(interval=None)
            if cpu is not None:
                self.cpu_percent = cpu
            self.ram_percent = psutil.virtual_memory().percent
            time.sleep(1.0)

    def _get_time_str(self) -> str:
        now = datetime.datetime.now()
        if self.config and self.config.get_setting("display", "time_format_24h"):
            return now.strftime("%H:%M")
        return now.strftime("%I:%M%p")

    # --- state machine ---

    def _determine_state(self, wpm: float, time_since_key: float) -> str:
        if time_since_key > self.sleep_timeout:
            return "SLEEP"
        if time_since_key > self.idle_timeout:
            return "IDLE"
        if wpm >= self.streak_threshold:
            return "STREAK"
        if wpm >= self.fast_threshold:
            return "FAST"
        if wpm >= self.normal_threshold:
            return "NORMAL"
        if wpm >= self.slow_threshold:
            return "SLOW"
        return "TYPING"

    def _send_animation_update(self, state: str, wpm: float):
        now   = time.time()
        speed = self._wpm_to_speed(wpm)

        if now - self.last_command_time < self.min_command_interval:
            return

        state_changed = (state != self.last_sent_state)
        speed_changed = (speed != self.last_sent_speed)
        stats_due     = (now - self.last_stats_update >= self.stats_update_interval)

        # Se non c'è nulla da fare, esci
        if not state_changed and not speed_changed and not stats_due:
            return

        if state == "SLEEP":
            if state_changed:
                self.send_command("SLEEP")
        elif state == "IDLE":
            if state_changed:
                self.send_command("IDLE")
        else:
            if speed_changed:
                self.send_command(f"SPEED:{speed}")
            if state_changed:
                self.send_command(f"STATE:{state}")

        # Stats periodiche - usa STATS: combinato che chiama updateSystemStats() sul firmware
        if stats_due:
            # Il firmware parsa STATS:CPU:x,RAM:y,WPM:z e chiama updateSystemStats()
            # che aggiorna le label LVGL (CPU:/RAM:/WPM: separati aggiornano solo variabili)
            self.send_command(f"STATS:CPU:{int(self.cpu_percent)},RAM:{int(self.ram_percent)},WPM:{int(wpm)}")
            if not self.config or self.config.get_setting("display", "show_time") is not False:
                self.send_command(f"TIME:{self._get_time_str()}")
            self.last_stats_update = now

        self.last_sent_state   = state
        self.last_sent_speed   = speed
        self.last_command_time = now

    # --- main loop ---

    def _main_loop(self):
        while self.running and not self.serial_conn:
            if not self._connect():
                print("[engine] ESP32 not found, retrying in 5s...")
                time.sleep(5)

        while self.running:
            if not self.serial_conn or not self.serial_conn.is_open:
                print("[engine] Connection lost, reconnecting...")
                time.sleep(2)
                self._connect()
                continue

            with self._data_lock:
                time_since_key = time.time() - self.last_keystroke_time

            wpm   = self._calculate_wpm()
            state = self._determine_state(wpm, time_since_key)
            self._send_animation_update(state, wpm)

            time.sleep(self.update_interval)

    # --- start / stop ---

    def _start_internal(self):
        print("[engine] Starting Bongo Cat engine...")
        self.running = True

        self.system_monitor_running = True
        self.system_monitor_thread  = threading.Thread(
            target=self._system_monitor_loop, daemon=True)
        self.system_monitor_thread.start()

        self._keyboard_monitor.start()

        self._loop_thread = threading.Thread(target=self._main_loop, daemon=True)
        self._loop_thread.start()

        print("[engine] Engine started.")

    def _stop_internal(self):
        print("[engine] Stopping...")
        self.running = False
        self.system_monitor_running = False
        self._keyboard_monitor.stop()
        with self._serial_lock:
            if self.serial_conn and self.serial_conn.is_open:
                self.serial_conn.close()
        print("[engine] Engine stopped.")
