#!/usr/bin/env python3
"""
Bongo Cat Settings GUI
GTK3-based configuration interface — uses system theme automatically
"""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib

from typing import Optional, Callable


class BongoCatSettingsGUI:
    """Settings GUI built with GTK3 (inherits system theme)"""

    def __init__(self, config_manager=None, engine=None,
                 on_close_callback: Optional[Callable] = None,
                 parent_root=None):  # parent_root ignored (tkinter compat param)
        self.config = config_manager
        self.engine = engine
        self.on_close_callback = on_close_callback

        self.window = None
        self.widgets = {}
        self.changes_made = False
        self.updating_from_config = False

    # ------------------------------------------------------------------ #
    #  Public API (same interface as original)                            #
    # ------------------------------------------------------------------ #

    def show(self):
        if self.window and self.window.get_visible():
            self.window.present()
            return
        self._build_window()
        self.load_current_settings()
        self.window.show_all()
        self.window.present()

    def mainloop(self):
        """Compatibility shim — GTK loop is already running via tray."""
        pass

    # ------------------------------------------------------------------ #
    #  Window construction                                                #
    # ------------------------------------------------------------------ #

    def _build_window(self):
        self.window = Gtk.Window(title="Bongo Cat Settings")
        self.window.set_default_size(520, 580)
        self.window.set_resizable(True)
        self.window.connect("delete-event", self._on_delete_event)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.window.add(outer)

        # ── Notebook ────────────────────────────────────────────────────
        notebook = Gtk.Notebook()
        notebook.set_margin_top(10)
        notebook.set_margin_bottom(6)
        notebook.set_margin_start(10)
        notebook.set_margin_end(10)
        outer.pack_start(notebook, True, True, 0)

        self._build_display_tab(notebook)
        self._build_behavior_tab(notebook)
        self._build_connection_tab(notebook)
        self._build_startup_tab(notebook)

        # ── Button bar ──────────────────────────────────────────────────
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        outer.pack_start(sep, False, False, 0)

        btn_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_bar.set_margin_top(8)
        btn_bar.set_margin_bottom(10)
        btn_bar.set_margin_start(12)
        btn_bar.set_margin_end(12)
        outer.pack_start(btn_bar, False, False, 0)

        btn_reset = Gtk.Button(label="Reset to Defaults")
        btn_reset.connect("clicked", lambda _: self._reset_to_defaults())
        btn_bar.pack_start(btn_reset, False, False, 0)

        # right-aligned buttons
        right = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_bar.pack_end(right, False, False, 0)

        btn_cancel = Gtk.Button(label="Cancel")
        btn_cancel.connect("clicked", lambda _: self._cancel())
        right.pack_start(btn_cancel, False, False, 0)

        btn_apply = Gtk.Button(label="Apply")
        btn_apply.get_style_context().add_class("suggested-action")
        btn_apply.connect("clicked", lambda _: self._apply_settings())
        right.pack_start(btn_apply, False, False, 0)

        btn_save = Gtk.Button(label="Save")
        btn_save.get_style_context().add_class("suggested-action")
        btn_save.connect("clicked", lambda _: self._save_settings())
        right.pack_start(btn_save, False, False, 0)

    # ------------------------------------------------------------------ #
    #  Tab helpers                                                        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _tab_box():
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)
        return box

    @staticmethod
    def _group(label: str) -> tuple:
        """Return (frame_widget, inner_box) for a labelled group."""
        frame = Gtk.Frame(label=f"  {label}  ")
        frame.set_label_align(0.02, 0.5)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        inner.set_margin_top(10)
        inner.set_margin_bottom(10)
        inner.set_margin_start(12)
        inner.set_margin_end(12)
        frame.add(inner)
        return frame, inner

    def _check(self, label: str, key: str, box: Gtk.Box):
        cb = Gtk.CheckButton(label=label)
        cb.connect("toggled", lambda w: self._mark_changed())
        self.widgets[key] = cb
        box.pack_start(cb, False, False, 0)

    # ------------------------------------------------------------------ #
    #  Display tab                                                        #
    # ------------------------------------------------------------------ #

    def _build_display_tab(self, nb: Gtk.Notebook):
        page = self._tab_box()
        nb.append_page(page, Gtk.Label(label="Display"))

        # Elements group
        f, inner = self._group("Display Elements")
        page.pack_start(f, False, False, 0)
        self._check("Show CPU Usage",    'show_cpu',  inner)
        self._check("Show RAM Usage",    'show_ram',  inner)
        self._check("Show WPM Counter",  'show_wpm',  inner)
        self._check("Show Clock",        'show_time', inner)

        # Time format group
        f2, inner2 = self._group("Time Format")
        page.pack_start(f2, False, False, 0)

        self.widgets['time_format'] = Gtk.ComboBoxText()
        self.widgets['time_format'].append("24", "24-hour format (14:30)")
        self.widgets['time_format'].append("12", "12-hour format (2:30 PM)")
        self.widgets['time_format'].set_active(0)
        self.widgets['time_format'].connect("changed", lambda w: self._mark_changed())
        inner2.pack_start(self.widgets['time_format'], False, False, 0)

        # Preview label
        self.widgets['preview_label'] = Gtk.Label(
            label="Changes will be applied to your Bongo Cat display")
        self.widgets['preview_label'].set_halign(Gtk.Align.START)
        self.widgets['preview_label'].get_style_context().add_class("dim-label")
        page.pack_start(self.widgets['preview_label'], False, False, 4)

    # ------------------------------------------------------------------ #
    #  Behavior tab                                                       #
    # ------------------------------------------------------------------ #

    def _build_behavior_tab(self, nb: Gtk.Notebook):
        page = self._tab_box()
        nb.append_page(page, Gtk.Label(label="Behavior"))

        # Sleep
        f, inner = self._group("Sleep Settings")
        page.pack_start(f, False, False, 0)

        inner.pack_start(Gtk.Label(label="Sleep timeout (minutes):", xalign=0), False, False, 0)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.widgets['sleep_timeout'] = Gtk.Adjustment(value=1, lower=1, upper=60, step_increment=1)
        scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=self.widgets['sleep_timeout'])
        scale.set_digits(0)
        scale.set_hexpand(True)
        self.widgets['sleep_timeout'].connect("value-changed", self._on_sleep_changed)
        self.widgets['sleep_label'] = Gtk.Label(label="1 minute")
        self.widgets['sleep_label'].set_width_chars(12)
        row.pack_start(scale, True, True, 0)
        row.pack_start(self.widgets['sleep_label'], False, False, 0)
        inner.pack_start(row, False, False, 0)

        # Idle
        f2, inner2 = self._group("Animation Settings")
        page.pack_start(f2, False, False, 0)

        inner2.pack_start(Gtk.Label(label="Idle timeout before stopping animations:", xalign=0), False, False, 0)

        row2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.widgets['idle_timeout'] = Gtk.Adjustment(value=3.0, lower=0.5, upper=10.0, step_increment=0.5)
        scale2 = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=self.widgets['idle_timeout'])
        scale2.set_digits(1)
        scale2.set_hexpand(True)
        self.widgets['idle_timeout'].connect("value-changed", self._on_idle_changed)
        self.widgets['idle_label'] = Gtk.Label(label="3.0 seconds")
        self.widgets['idle_label'].set_width_chars(12)
        row2.pack_start(scale2, True, True, 0)
        row2.pack_start(self.widgets['idle_label'], False, False, 0)
        inner2.pack_start(row2, False, False, 0)

    # ------------------------------------------------------------------ #
    #  Connection tab                                                     #
    # ------------------------------------------------------------------ #

    def _build_connection_tab(self, nb: Gtk.Notebook):
        page = self._tab_box()
        nb.append_page(page, Gtk.Label(label="Connection"))

        f, inner = self._group("Serial Port Settings")
        page.pack_start(f, False, False, 0)

        # Port row
        port_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        port_row.pack_start(Gtk.Label(label="Port:", xalign=0), False, False, 0)
        self.widgets['com_port'] = Gtk.ComboBoxText.new_with_entry()
        for p in ("AUTO", "/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyACM0", "/dev/ttyACM1"):
            self.widgets['com_port'].append_text(p)
        self.widgets['com_port'].set_active(0)
        self.widgets['com_port'].connect("changed", lambda w: self._mark_changed())
        port_row.pack_start(self.widgets['com_port'], True, True, 0)
        btn_scan = Gtk.Button(label="Scan")
        btn_scan.connect("clicked", lambda _: self._scan_ports())
        port_row.pack_start(btn_scan, False, False, 0)
        inner.pack_start(port_row, False, False, 0)

        # Baudrate row
        baud_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        baud_row.pack_start(Gtk.Label(label="Baudrate:", xalign=0), False, False, 0)
        self.widgets['baudrate'] = Gtk.ComboBoxText()
        for b in ("9600", "19200", "38400", "57600", "115200"):
            self.widgets['baudrate'].append_text(b)
        self.widgets['baudrate'].set_active(4)  # 115200
        self.widgets['baudrate'].connect("changed", lambda w: self._mark_changed())
        baud_row.pack_start(self.widgets['baudrate'], False, False, 0)
        inner.pack_start(baud_row, False, False, 0)

        # Options group
        f2, inner2 = self._group("Connection Options")
        page.pack_start(f2, False, False, 0)

        self._check("Auto-reconnect if connection lost", 'auto_reconnect', inner2)

        timeout_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        timeout_row.pack_start(Gtk.Label(label="Timeout:", xalign=0), False, False, 0)
        self.widgets['conn_timeout'] = Gtk.ComboBoxText()
        for t in ("1", "2", "3", "5", "10", "15", "30"):
            self.widgets['conn_timeout'].append_text(t)
        self.widgets['conn_timeout'].set_active(3)  # 5s
        self.widgets['conn_timeout'].connect("changed", lambda w: self._mark_changed())
        timeout_row.pack_start(self.widgets['conn_timeout'], False, False, 0)
        timeout_row.pack_start(Gtk.Label(label="seconds"), False, False, 0)
        inner2.pack_start(timeout_row, False, False, 0)

    # ------------------------------------------------------------------ #
    #  Startup tab                                                        #
    # ------------------------------------------------------------------ #

    def _build_startup_tab(self, nb: Gtk.Notebook):
        page = self._tab_box()
        nb.append_page(page, Gtk.Label(label="Startup"))

        f, inner = self._group("Startup Behavior")
        page.pack_start(f, False, False, 0)

        self._check("Start on login",               'start_on_login',    inner)
        self._check("Start minimized to tray",      'start_minimized',   inner)
        self._check("Show notifications",           'show_notifications', inner)

        # Status group
        f2, inner2 = self._group("Status")
        page.pack_start(f2, False, False, 0)

        self.widgets['status_label'] = Gtk.Label(label="", xalign=0)
        self.widgets['status_label'].get_style_context().add_class("dim-label")
        inner2.pack_start(self.widgets['status_label'], False, False, 0)
        self._update_status_info()

    # ------------------------------------------------------------------ #
    #  Settings load / save                                               #
    # ------------------------------------------------------------------ #

    def load_current_settings(self):
        if not self.config:
            return
        self.updating_from_config = True
        try:
            d = self.config.get_display_settings()
            self.widgets['show_cpu'].set_active(d.get('show_cpu', True))
            self.widgets['show_ram'].set_active(d.get('show_ram', True))
            self.widgets['show_wpm'].set_active(d.get('show_wpm', True))
            self.widgets['show_time'].set_active(d.get('show_time', True))
            self.widgets['time_format'].set_active_id(
                '24' if d.get('time_format_24h', True) else '12')

            b = self.config.get_behavior_settings()
            self.widgets['sleep_timeout'].set_value(b.get('sleep_timeout_minutes', 1))
            self.widgets['idle_timeout'].set_value(b.get('idle_timeout_seconds', 3.0))

            c = self.config.get_connection_settings()
            port = c.get('com_port', 'AUTO')
            entry = self.widgets['com_port'].get_child()
            if entry:
                entry.set_text(port)
            baud = str(c.get('baudrate', 115200))
            self._set_combotext(self.widgets['baudrate'], baud)
            self.widgets['auto_reconnect'].set_active(c.get('auto_reconnect', True))
            self._set_combotext(self.widgets['conn_timeout'], str(c.get('timeout_seconds', 5)))

            s = self.config.get_startup_settings()
            self.widgets['start_on_login'].set_active(s.get('start_on_login', False))
            self.widgets['start_minimized'].set_active(s.get('start_minimized', True))
            self.widgets['show_notifications'].set_active(s.get('show_notifications', True))

            self._update_slider_labels()
        finally:
            self.updating_from_config = False

    @staticmethod
    def _set_combotext(combo: Gtk.ComboBoxText, value: str):
        model = combo.get_model()
        for i, row in enumerate(model):
            if row[0] == value:
                combo.set_active(i)
                return
        combo.set_active(0)

    def _collect_settings(self) -> dict:
        baud_text = self.widgets['baudrate'].get_active_text() or "115200"
        timeout_text = self.widgets['conn_timeout'].get_active_text() or "5"
        port_entry = self.widgets['com_port'].get_child()
        port = port_entry.get_text() if port_entry else "AUTO"
        return {
            'display': {
                'show_cpu':         self.widgets['show_cpu'].get_active(),
                'show_ram':         self.widgets['show_ram'].get_active(),
                'show_wpm':         self.widgets['show_wpm'].get_active(),
                'show_time':        self.widgets['show_time'].get_active(),
                'time_format_24h':  self.widgets['time_format'].get_active_id() == '24',
            },
            'behavior': {
                'sleep_timeout_minutes': int(self.widgets['sleep_timeout'].get_value()),
                'idle_timeout_seconds':  round(self.widgets['idle_timeout'].get_value(), 1),
            },
            'connection': {
                'com_port':       port,
                'baudrate':       int(baud_text),
                'auto_reconnect': self.widgets['auto_reconnect'].get_active(),
                'timeout_seconds': int(timeout_text),
            },
            'startup': {
                'start_on_login':    self.widgets['start_on_login'].get_active(),
                'start_minimized':   self.widgets['start_minimized'].get_active(),
                'show_notifications': self.widgets['show_notifications'].get_active(),
            },
        }

    def _apply_settings(self):
        if not self.config:
            self._error("No configuration manager available")
            return
        try:
            s = self._collect_settings()
            for section, values in s.items():
                for key, val in values.items():
                    self.config.set_setting(section, key, val)

            if self.engine and hasattr(self.engine, 'apply_all_config_to_arduino'):
                try:
                    self.engine.apply_all_config_to_arduino()
                except Exception as e:
                    print(f"⚠️ Arduino apply error: {e}")

            self.changes_made = False
            self._update_preview()
            self._info("Settings applied successfully!")
        except Exception as e:
            self._error(f"Failed to apply settings: {e}")

    def _save_settings(self):
        self._apply_settings()
        if self.config:
            if self.config.save_config():
                if self.engine and hasattr(self.engine, 'save_config_to_arduino'):
                    self.engine.save_config_to_arduino()
                self._info("Settings saved!")
            else:
                self._error("Failed to save settings to file")

    def _cancel(self):
        if self.changes_made:
            if self._ask("Discard all changes?"):
                self.load_current_settings()
                self.changes_made = False
                self._update_preview()
        else:
            self._close()

    def _reset_to_defaults(self):
        if self._ask("Reset all settings to defaults?"):
            if self.config:
                self.config.reset_to_defaults()
                self.load_current_settings()
                self.changes_made = True
                self._update_preview()

    # ------------------------------------------------------------------ #
    #  UI helpers                                                         #
    # ------------------------------------------------------------------ #

    def _mark_changed(self):
        if self.updating_from_config:
            return
        self.changes_made = True
        self._update_preview()

    def _on_sleep_changed(self, adj):
        v = int(adj.get_value())
        self.widgets['sleep_label'].set_text(f"{v} minute{'s' if v != 1 else ''}")
        self._mark_changed()

    def _on_idle_changed(self, adj):
        v = adj.get_value()
        self.widgets['idle_label'].set_text(f"{v:.1f} second{'s' if v != 1.0 else ''}")
        self._mark_changed()

    def _update_slider_labels(self):
        self._on_sleep_changed(self.widgets['sleep_timeout'])
        self._on_idle_changed(self.widgets['idle_timeout'])

    def _update_preview(self):
        lbl = self.widgets.get('preview_label')
        if not lbl:
            return
        if self.changes_made:
            lbl.set_text("● Settings modified — click Apply or Save to update")
        else:
            lbl.set_text("Changes will be applied to your Bongo Cat display")

    def _update_status_info(self):
        lbl = self.widgets.get('status_label')
        if lbl and self.config:
            lbl.set_text(f"Config file: {self.config.config_file}")

    def _scan_ports(self):
        try:
            import serial.tools.list_ports
            ports = ["AUTO"] + [p.device for p in serial.tools.list_ports.comports()]
            combo = self.widgets['com_port']
            combo.remove_all()
            for p in ports:
                combo.append_text(p)
            combo.set_active(0)
            self._info(f"Found {len(ports)-1} serial port(s)")
        except Exception as e:
            self._error(f"Scan failed: {e}")

    # ------------------------------------------------------------------ #
    #  Dialogs                                                            #
    # ------------------------------------------------------------------ #

    def _dialog(self, dtype, msg):
        d = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=dtype,
            buttons=Gtk.ButtonsType.OK,
            text=msg,
        )
        d.run()
        d.destroy()

    def _info(self, msg):
        self._dialog(Gtk.MessageType.INFO, msg)

    def _error(self, msg):
        self._dialog(Gtk.MessageType.ERROR, msg)

    def _ask(self, msg) -> bool:
        d = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=msg,
        )
        resp = d.run()
        d.destroy()
        return resp == Gtk.ResponseType.YES

    # ------------------------------------------------------------------ #
    #  Window lifecycle                                                   #
    # ------------------------------------------------------------------ #

    def _on_delete_event(self, window, event):
        if self.changes_made:
            d = Gtk.MessageDialog(
                transient_for=self.window,
                modal=True,
                message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.NONE,
                text="You have unsaved changes. Save before closing?",
            )
            d.add_buttons("Discard", Gtk.ResponseType.NO,
                          "Cancel",  Gtk.ResponseType.CANCEL,
                          "Save",    Gtk.ResponseType.YES)
            resp = d.run()
            d.destroy()
            if resp == Gtk.ResponseType.YES:
                self._save_settings()
                self._close()
            elif resp == Gtk.ResponseType.NO:
                self._close()
            # CANCEL → do nothing, keep window open
            return True  # prevent default close
        self._close()
        return True

    def _close(self):
        if self.window:
            self.window.hide()
            self.window = None
        if self.on_close_callback:
            self.on_close_callback()


# --------------------------------------------------------------------------- #
#  Standalone test                                                             #
# --------------------------------------------------------------------------- #

def main():
    print("🧪 Testing Settings GUI (GTK3)…")
    try:
        from config import ConfigManager
        config = ConfigManager()
    except Exception:
        config = None

    gui = BongoCatSettingsGUI(config_manager=config)
    gui.show()
    Gtk.main()
    print("✅ Done")


if __name__ == "__main__":
    main()
