#!/usr/bin/env python3
"""
Bongo Cat System Tray Integration
Uses AppIndicator3 directly for Wayland/Hyprland/Waybar compatibility
"""

import gi
gi.require_version('AppIndicator3', '0.1')
gi.require_version('Gtk', '3.0')
from gi.repository import AppIndicator3, Gtk, GLib

import threading
import sys
import os
import tempfile
from typing import Optional, Callable
from PIL import Image, ImageDraw


class BongoCatSystemTray:
    """System tray integration using AppIndicator3 natively (Wayland/Hyprland compatible)"""

    def __init__(self, config_manager=None, engine=None, on_exit_callback: Optional[Callable] = None):
        self.config = config_manager
        self.engine = engine
        self.on_exit_callback = on_exit_callback

        self.running = False
        self.settings_gui = None
        self._icon_tmp = None
        self._indicator = None
        self._gtk_thread = None

        # Status tracking
        self.connection_status = "disconnected"
        self.last_wpm = 0
        self.typing_active = False

        self._create_indicator()

    # ------------------------------------------------------------------ #
    #  Icon creation                                                       #
    # ------------------------------------------------------------------ #

    def _get_icon_path(self) -> str:
        """Find or generate icon, return path to PNG file"""
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS if hasattr(sys, '_MEIPASS') else os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(__file__)

        candidates = [
            os.path.join(base_path, "assets", "tray_icon.png"),
            os.path.join(base_path, "assets", "tray_icon.ico"),
            "assets/tray_icon.png",
            "bongo_cat_app/assets/tray_icon.png",
        ]

        for path in candidates:
            if os.path.exists(path):
                print(f"🎨 Using icon: {path}")
                img = Image.open(path).resize((64, 64), Image.Resampling.LANCZOS).convert("RGBA")
                tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
                img.save(tmp.name)
                return tmp.name

        print("🎨 Generating cat icon")
        img = self._create_cat_icon()
        tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        img.save(tmp.name)
        return tmp.name

    def _create_cat_icon(self, size=64) -> Image.Image:
        """Generate a simple cat face icon"""
        image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        m = size // 8
        draw.ellipse([m, m, size - m, size - m],
                     fill=(100, 100, 100, 255), outline=(50, 50, 50, 255), width=2)

        es = size // 6
        draw.polygon([(m, m + es), (m + es, m), (m + es * 2, m + es)],
                     fill=(100, 100, 100, 255))
        draw.polygon([(size - m - es * 2, m + es), (size - m - es, m), (size - m, m + es)],
                     fill=(100, 100, 100, 255))

        ey = m + size // 4
        ez = size // 12
        draw.ellipse([m + size // 4 - ez, ey - ez, m + size // 4 + ez, ey + ez], fill=(0, 0, 0, 255))
        draw.ellipse([size - m - size // 4 - ez, ey - ez, size - m - size // 4 + ez, ey + ez], fill=(0, 0, 0, 255))

        ny = ey + size // 8
        ns = size // 20
        draw.polygon([(size // 2, ny - ns), (size // 2 - ns, ny + ns), (size // 2 + ns, ny + ns)],
                     fill=(255, 100, 100, 255))

        return image

    # ------------------------------------------------------------------ #
    #  Indicator setup                                                     #
    # ------------------------------------------------------------------ #

    def _create_indicator(self):
        """Create AppIndicator3 indicator and GTK menu"""
        self._icon_path = self._get_icon_path()

        self._indicator = AppIndicator3.Indicator.new(
            "BongoCat",
            self._icon_path,
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS
        )
        self._indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self._indicator.set_title("Bongo Cat - Typing Monitor")

        self._rebuild_menu()

    def _rebuild_menu(self):
        """Build (or rebuild) the GTK context menu"""
        menu = Gtk.Menu()

        # Header (non-clickable label)
        header = Gtk.MenuItem(label="🐱 Bongo Cat Monitor")
        header.set_sensitive(False)
        menu.append(header)

        menu.append(Gtk.SeparatorMenuItem())

        # Connection status (non-clickable)
        self._status_item = Gtk.MenuItem(label=self._connection_label())
        self._status_item.set_sensitive(False)
        menu.append(self._status_item)

        # Reconnect
        reconnect_item = Gtk.MenuItem(label="Reconnect")
        reconnect_item.connect("activate", lambda _: self.reconnect_device())
        reconnect_item.set_sensitive(self.connection_status != "connected")
        menu.append(reconnect_item)

        # Disconnect
        disconnect_item = Gtk.MenuItem(label="Disconnect")
        disconnect_item.connect("activate", lambda _: self.disconnect_device())
        disconnect_item.set_sensitive(self.connection_status == "connected")
        menu.append(disconnect_item)

        menu.append(Gtk.SeparatorMenuItem())

        # Settings
        settings_item = Gtk.MenuItem(label="Settings…")
        settings_item.connect("activate", lambda _: self.show_settings())
        menu.append(settings_item)

        menu.append(Gtk.SeparatorMenuItem())

        # Autostart toggle
        self._autostart_item = Gtk.CheckMenuItem(label="Start on login")
        self._autostart_item.set_active(self._get_autostart())
        self._autostart_item.connect("toggled", self._on_autostart_toggled)
        menu.append(self._autostart_item)

        # Notifications toggle
        self._notif_item = Gtk.CheckMenuItem(label="Show Notifications")
        self._notif_item.set_active(self._get_notifications())
        self._notif_item.connect("toggled", self._on_notifications_toggled)
        menu.append(self._notif_item)

        menu.append(Gtk.SeparatorMenuItem())

        # Exit
        exit_item = Gtk.MenuItem(label="Exit")
        exit_item.connect("activate", lambda _: self.exit_application())
        menu.append(exit_item)

        menu.show_all()
        self._indicator.set_menu(menu)
        self._menu = menu

    # ------------------------------------------------------------------ #
    #  GTK main loop management                                           #
    # ------------------------------------------------------------------ #

    def start_detached(self):
        """Start GTK main loop in a background daemon thread"""
        if self.running:
            return
        self.running = True
        print("🚀 Starting AppIndicator3 tray (detached)…")
        self._gtk_thread = threading.Thread(target=Gtk.main, daemon=True, name="gtk-tray")
        self._gtk_thread.start()

    def start(self):
        """Start GTK main loop (blocking — use from main thread)"""
        self.running = True
        print("🚀 Starting AppIndicator3 tray…")
        Gtk.main()

    def stop(self):
        """Stop the GTK main loop"""
        if self.running:
            self.running = False
            print("🛑 Stopping tray…")
            GLib.idle_add(Gtk.main_quit)

    def run_in_background(self):
        """Convenience: start detached and return thread"""
        self.start_detached()
        return self._gtk_thread

    # ------------------------------------------------------------------ #
    #  Status helpers                                                      #
    # ------------------------------------------------------------------ #

    def _connection_label(self) -> str:
        labels = {
            "connected":    "✓ Connected to ESP32",
            "connecting":   "~ Connecting…",
            "disconnected": "✗ Disconnected",
            "error":        "! Connection Error",
        }
        return labels.get(self.connection_status, "? Unknown")

    def update_connection_status(self, status, port=None):
        """Accept both old-style (bool, port) and new-style (str) calls from engine"""
        if isinstance(status, bool):
            # Called as update_connection_status(True, port) from engine.py
            self.connection_status = "connected" if status else "disconnected"
        else:
            self.connection_status = status
        tooltip = f"Bongo Cat - {self._connection_label()}"
        GLib.idle_add(self._indicator.set_title, tooltip)
        GLib.idle_add(self._rebuild_menu)

    def update_typing_status(self, active: bool, wpm: float = 0):
        self.typing_active = active
        self.last_wpm = wpm
        if active:
            GLib.idle_add(self._indicator.set_title, f"Bongo Cat - Typing ({wpm:.0f} WPM)")
        else:
            GLib.idle_add(self._indicator.set_title, "Bongo Cat - Idle")

    def refresh_menu(self):
        GLib.idle_add(self._rebuild_menu)

    def on_config_change(self, key: str, value):
        if key.startswith('startup.'):
            self.refresh_menu()

    # ------------------------------------------------------------------ #
    #  Config helpers                                                      #
    # ------------------------------------------------------------------ #

    def _get_autostart(self) -> bool:
        if self.config:
            return self.config.get_startup_settings().get('start_on_login', False)
        return False

    def _get_notifications(self) -> bool:
        if self.config:
            return self.config.get_startup_settings().get('show_notifications', True)
        return True

    def _on_autostart_toggled(self, widget):
        if self.config:
            self.config.set_setting('startup', 'start_on_login', widget.get_active())
            self.config.save_config()

    def _on_notifications_toggled(self, widget):
        if self.config:
            self.config.set_setting('startup', 'show_notifications', widget.get_active())
            self.config.save_config()

    # ------------------------------------------------------------------ #
    #  Actions                                                             #
    # ------------------------------------------------------------------ #

    def show_notification(self, title: str, message: str):
        """Send desktop notification via notify-send (most reliable on Wayland)"""
        if not self._get_notifications():
            return
        try:
            import subprocess
            subprocess.Popen(
                ["notify-send", "--app-name=BongoCat", title, message],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception as e:
            print(f"⚠️ Notification error: {e}")

    def show_settings(self, *_):
        """Open settings GUI in a separate thread (tkinter must own its thread)"""
        def _run():
            try:
                import tkinter as tk
                from gui import BongoCatSettingsGUI

                root = tk.Tk()
                root.withdraw()
                gui = BongoCatSettingsGUI(
                    config_manager=self.config,
                    engine=self.engine,
                    on_close_callback=self._on_settings_closed,
                    parent_root=root
                )
                self.settings_gui = gui
                gui.show()
                if hasattr(gui, 'window') and gui.window:
                    gui.window.mainloop()
            except Exception as e:
                print(f"❌ Settings error: {e}")
                self.show_notification("Error", f"Failed to open settings: {e}")

        if self.settings_gui is None:
            t = threading.Thread(target=_run, daemon=True, name="settings-gui")
            t.start()
        else:
            print("⚠️ Settings already open")

    def _on_settings_closed(self):
        self.settings_gui = None

    def reconnect_device(self, *_):
        if not self.engine:
            return

        def _reconnect():
            self.update_connection_status("connecting")
            self.show_notification("Bongo Cat", "Attempting to reconnect…")
            if self.engine.serial_conn and self.engine.serial_conn.is_open:
                self.engine.disconnect_serial()
            if self.engine.connect_serial():
                self.update_connection_status("connected")
                self.show_notification("Bongo Cat", "Reconnected to ESP32!")
            else:
                self.update_connection_status("error")
                self.show_notification("Bongo Cat", "Failed to reconnect. Check USB connection.")

        threading.Thread(target=_reconnect, daemon=True).start()

    def disconnect_device(self, *_):
        if self.engine:
            self.engine.disconnect_serial()
            self.update_connection_status("disconnected")
            self.show_notification("Bongo Cat", "Disconnected from ESP32")

    def exit_application(self, *_):
        self.show_notification("Bongo Cat", "Goodbye! 👋")
        self.stop()
        if self.on_exit_callback:
            self.on_exit_callback()
        else:
            sys.exit(0)

    # ------------------------------------------------------------------ #
    #  Cleanup                                                             #
    # ------------------------------------------------------------------ #

    def __del__(self):
        if self._icon_tmp and os.path.exists(self._icon_tmp):
            try:
                os.unlink(self._icon_tmp)
            except Exception:
                pass


# --------------------------------------------------------------------------- #
#  Standalone test                                                             #
# --------------------------------------------------------------------------- #

def main():
    print("🧪 Testing Bongo Cat System Tray (AppIndicator3)…")
    tray = BongoCatSystemTray()
    print("📱 Tray started — check your bar's tray area")
    print("🛑 Use 'Exit' from the tray menu to close")
    try:
        tray.start()
    except KeyboardInterrupt:
        tray.stop()
    print("✅ Done")


if __name__ == "__main__":
    main()
