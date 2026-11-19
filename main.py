import os
import sys
import gi
import json
import datetime
import subprocess
import re

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

WEBKIT_AVAILABLE = False
try:
    gi.require_version('WebKit', '6.0')
    from gi.repository import WebKit
    WEBKIT_AVAILABLE = True
except (ValueError, ImportError):
    print("⚠️ WebKit 6.0 не найден.")

from gi.repository import Gtk, Adw, Gio, GLib, Gdk

try:
    from pynput import keyboard
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False

try:
    import pyperclip
    PYPERCLIP_AVAILABLE = True
except ImportError:
    PYPERCLIP_AVAILABLE = False

try:
    import markdown
    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False

NOTES_DIR = os.path.expanduser("~/RightNote")
CONFIG_DIR = os.path.expanduser("~/.local/share/right-note")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
WEBKIT_DATA_DIR = os.path.join(CONFIG_DIR, "webkit_data")

def load_css():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    css_path = os.path.join(base_dir, "style.css")
    if os.path.exists(css_path):
        provider = Gtk.CssProvider()
        provider.load_from_path(css_path)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

class HotkeyRow(Adw.ActionRow):
    def __init__(self, app):
        super().__init__(title="Глобальный хоткей")
        self.app = app
        self.is_listening = False
        
        self.btn = Gtk.Button(label="Изменить")
        self.btn.add_css_class("flat")
        self.btn.valign = Gtk.Align.CENTER
        self.btn.connect("clicked", self.start_listening)
        self.add_suffix(self.btn)
        self.update_label()
        
        self.key_ctrl = Gtk.EventControllerKey()
        self.key_ctrl.connect("key-pressed", self.on_key_pressed)
        self.add_controller(self.key_ctrl)

    def update_label(self):
        current_combo = self.app.config.get("hotkey_combo", "<ctrl>+<alt>+n")
        display_combo = current_combo.replace("<ctrl>", "Ctrl").replace("<alt>", "Alt").replace("<shift>", "Shift").replace("<cmd>", "Win").replace("+", " + ")
        self.set_subtitle(display_combo.upper())

    def start_listening(self, btn):
        self.is_listening = True
        self.set_subtitle("Нажмите комбинацию...")
        self.btn.set_visible(False)

    def on_key_pressed(self, controller, keyval, keycode, state):
        if not self.is_listening:
            return False
        if keyval in (Gdk.KEY_Control_L, Gdk.KEY_Control_R, Gdk.KEY_Alt_L, Gdk.KEY_Alt_R, 
                      Gdk.KEY_Shift_L, Gdk.KEY_Shift_R, Gdk.KEY_Super_L, Gdk.KEY_Super_R):
            return True
        key_name = Gdk.keyval_name(keyval).lower()
        if key_name == "escape":
            self.is_listening = False
            self.btn.set_visible(True)
            self.update_label()
            return True
        if len(key_name) > 1 and not (key_name.startswith("f") and key_name[1:].isdigit()):
            key_name = f"<{key_name}>"

        combo = []
        if state & Gdk.ModifierType.CONTROL_MASK: combo.append("<ctrl>")
        if state & Gdk.ModifierType.ALT_MASK: combo.append("<alt>")
        if state & Gdk.ModifierType.SHIFT_MASK: combo.append("<shift>")
        if state & Gdk.ModifierType.SUPER_MASK: combo.append("<cmd>")
        
        combo.append(key_name)
        final_combo = "+".join(combo)
        
        self.app.config["hotkey_combo"] = final_combo
        self.app.save_config()
        self.app.restart_hotkey_listener()
        
        self.is_listening = False
        self.btn.set_visible(True)
        self.update_label()
        return True

class SettingsWindow(Adw.PreferencesWindow):
    def __init__(self, parent_app):
        super().__init__(transient_for=parent_app.win, modal=True)
        self.app = parent_app
        self.set_title("Настройки")
        self.set_default_size(450, 400)

        page = Adw.PreferencesPage()
        self.add(page)

        group_hotkey = Adw.PreferencesGroup(title="Глобальный хоткей")
        page.add(group_hotkey)
        self.switch_enabled = Adw.SwitchRow(title="Включить хоткей")
        self.switch_enabled.set_active(self.app.config.get("hotkey_enabled", True))
        self.switch_enabled.connect("notify::active", lambda s, p: self.save_setting("hotkey_enabled", s.get_active()))
        group_hotkey.add(self.switch_enabled)
        group_hotkey.add(HotkeyRow(self.app))

        group_links = Adw.PreferencesGroup(title="Ссылки и веб-контент")
        page.add(group_links)
        
        self.combo_links = Adw.ComboRow(title="Открывать ссылки")
        model = Gtk.StringList.new(["Во внешнем браузере", "Внутри приложения"])
        self.combo_links.set_model(model)
        current_behavior = self.app.config.get("link_behavior", "external")
        self.combo_links.set_selected(0 if current_behavior == "external" else 1)
        self.combo_links.connect("notify::selected", self.on_link_behavior_changed)
        group_links.add(self.combo_links)

        group_dock = Adw.PreferencesGroup(title="Веб-панель (Отдельное окно)")
        page.add(group_dock)

        self.entry_dock_url = Adw.EntryRow(title="URL для панели (например, chat.deepseek.com)")
        self.entry_dock_url.set_text(self.app.config.get("webapp_url", "https://chat.deepseek.com"))
        self.entry_dock_url.connect("changed", lambda e: self.save_setting("webapp_url", e.get_text()))
        group_dock.add(self.entry_dock_url)

    def save_setting(self, key, value):
        self.app.config[key] = value
        self.app.save_config()
        if key == "webapp_url":
            if hasattr(self.app, 'webapp_win') and self.app.webapp_win:
                self.app.load_webapp_url()

    def on_link_behavior_changed(self, combo, pspec):
        selected = combo.get_selected()
        behavior = "external" if selected == 0 else "internal"
        self.save_setting("link_behavior", behavior)


class RightNoteApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id='com.daniil.rightnote',
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.connect('activate', self.on_activate)
        self.connect('command-line', self.on_command_line)
        
        os.makedirs(NOTES_DIR, exist_ok=True)
        os.makedirs(CONFIG_DIR, exist_ok=True)
        os.makedirs(WEBKIT_DATA_DIR, exist_ok=True) 
        
        self.dirty = False
        self.is_loading = False
        self.current_file = None
        self.pending_select = None
        self.hotkey_listener = None
        self.win = None
        self.webapp_win = None # Окно веб-панели
        
        self.config = self._load_config()
        if "hotkey_combo" not in self.config: self.config["hotkey_combo"] = "<ctrl>+<alt>+n"
        if "hotkey_enabled" not in self.config: self.config["hotkey_enabled"] = True
        if "link_behavior" not in self.config: self.config["link_behavior"] = "external"
        if "webapp_url" not in self.config: self.config["webapp_url"] = "https://chat.deepseek.com"
            
        self._setup_actions()

    def on_command_line(self, app, command_line):
        args = command_line.get_arguments()
        if len(args) > 1 and args[1] == "--add-clipboard":
            self.trigger_add_clipboard()
            return 0
        self.activate()
        return 0

    def _setup_actions(self):
        actions = [
            ("new",      self.new_note,      ["<Control>n"]),
            ("open",     self.open_file,     ["<Control>o"]),
            ("save_as",  self.save_file_as,  ["<Control><Shift>s"]),
            ("delete",   self.delete_note,   ["<Control>Delete"]),
            ("quit",     self.quit_app,      ["<Control>q"]),
            ("settings", self.open_settings, ["<Control>comma"]),
            ("bold",     lambda: self.insert_markdown("**", "**"), ["<Control>b"]),
            ("italic",   lambda: self.insert_markdown("*", "*"),   ["<Control>i"]),
        ]
        for name, handler, accels in actions:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda *_, h=handler: h())
            self.add_action(action)
            self.set_accels_for_action(f"app.{name}", accels)

    def quit_app(self):
        if self.hotkey_listener:
            self.hotkey_listener.stop()
        if self.webapp_win:
            self.webapp_win.destroy()
        if self.win:
            self.win.close()
        else:
            self.quit()

    def on_activate(self, app=None):
        if self.win:
            self.win.present()
            return

        load_css()

        if WEBKIT_AVAILABLE:
            self.network_session = WebKit.NetworkSession.new(
                os.path.join(WEBKIT_DATA_DIR, "cache"),
                WEBKIT_DATA_DIR
            )

        self.win = Adw.ApplicationWindow(application=self)
        self.win.set_default_size(1000, 650)
        self.win.connect("close-request", self.on_close)

        header = Adw.HeaderBar()
        
        self.btn_back = Gtk.Button(icon_name="go-previous-symbolic")
        self.btn_back.set_tooltip_text("Вернуться к заметке")
        self.btn_back.set_visible(False)
        self.btn_back.connect("clicked", lambda _: self.update_preview())
        header.pack_start(self.btn_back)

        self.btn_view = Gtk.ToggleButton(icon_name="view-reveal-symbolic")
        self.btn_view.set_tooltip_text("Показать/Скрыть исходный код")
        self.btn_view.connect("toggled", self.on_view_toggled)
        header.pack_start(self.btn_view)

        self.btn_webapp = Gtk.ToggleButton(icon_name="web-browser-symbolic")
        self.btn_webapp.set_tooltip_text("Открыть веб-панель в отдельном окне")
        self.btn_webapp.connect("toggled", self.on_webapp_toggled)
        header.pack_start(self.btn_webapp)

        self.save_label = Gtk.Label(label="Сохранено")
        self.save_label.add_css_class("dim-label")
        self.save_label.add_css_class("save-status")
        header.pack_end(self.save_label)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)

        # Основной макет теперь только Сайдбар + Редактор
        main_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        main_paned.set_position(250)
        main_paned.set_resize_start_child(False)
        main_paned.set_wide_handle(True)
        main_paned.set_vexpand(True)
        main_paned.set_hexpand(True)
        toolbar_view.set_content(main_paned)
        self.win.set_content(toolbar_view)

        # --- ЛЕВАЯ ЧАСТЬ: САЙДБАР ---
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sidebar.add_css_class("sidebar-box")
        sidebar.add_css_class("floating-panel")
        sidebar.set_size_request(200, -1)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        btn_box.set_margin_top(10); btn_box.set_margin_bottom(10)
        btn_box.set_margin_start(10); btn_box.set_margin_end(10)
        btn_box.set_homogeneous(True)

        btn_new = Gtk.Button(icon_name="document-new-symbolic")
        btn_new.add_css_class("sidebar-btn"); btn_new.add_css_class("flat")
        btn_new.connect("clicked", lambda _: self.new_note())
        
        btn_open = Gtk.Button(icon_name="document-open-symbolic")
        btn_open.add_css_class("sidebar-btn"); btn_open.add_css_class("flat")
        btn_open.connect("clicked", lambda _: self.open_file())
        
        btn_save = Gtk.Button(icon_name="document-save-as-symbolic")
        btn_save.add_css_class("sidebar-btn"); btn_save.add_css_class("flat")
        btn_save.connect("clicked", lambda _: self.save_file_as())

        btn_del = Gtk.Button(icon_name="user-trash-symbolic")
        btn_del.add_css_class("sidebar-btn"); btn_del.add_css_class("flat")
        btn_del.connect("clicked", lambda _: self.delete_note())

        btn_settings = Gtk.Button(icon_name="emblem-system-symbolic")
        btn_settings.add_css_class("sidebar-btn"); btn_settings.add_css_class("flat")
        btn_settings.connect("clicked", lambda _: self.open_settings())

        for b in (btn_new, btn_open, btn_save, btn_del, btn_settings):
            btn_box.append(b)
        sidebar.append(btn_box)

        self.notes_dir = Gio.File.new_for_path(NOTES_DIR)
        self.notes_store = self._load_dir(self.notes_dir)
        self.tree_model = Gtk.TreeListModel.new(self.notes_store, False, False, self._create_child_model)
        self.selection_model = Gtk.SingleSelection.new(self.tree_model)
        self.selection_model.connect("selection-changed", self.on_selection_changed)
        
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._setup_tree_item)
        factory.connect("bind", self._bind_tree_item)
        self.list_view = Gtk.ListView.new(self.selection_model, factory)
        
        notes_scroll = Gtk.ScrolledWindow()
        notes_scroll.set_child(self.list_view)
        notes_scroll.set_vexpand(True)
        sidebar.append(notes_scroll)
        main_paned.set_start_child(sidebar)

        # --- ПРАВАЯ ЧАСТЬ: РЕДАКТОР ---
        editor_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        editor_container.add_css_class("editor-container")
        editor_container.set_hexpand(True)
        editor_container.set_vexpand(True)

        format_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        format_box.set_margin_top(6); format_box.set_margin_bottom(6)
        format_box.set_margin_start(12); format_box.set_margin_end(12)
        format_box.set_halign(Gtk.Align.START)

        btn_bold = Gtk.Button(icon_name="format-text-bold-symbolic")
        btn_bold.add_css_class("flat"); btn_bold.connect("clicked", lambda _: self.insert_markdown("**", "**"))
        btn_italic = Gtk.Button(icon_name="format-text-italic-symbolic")
        btn_italic.add_css_class("flat"); btn_italic.connect("clicked", lambda _: self.insert_markdown("*", "*"))
        btn_h1 = Gtk.Button(label="H1")
        btn_h1.add_css_class("flat"); btn_h1.connect("clicked", lambda _: self.insert_markdown("# ", ""))
        self.btn_link = Gtk.Button(icon_name="insert-link-symbolic")
        self.btn_link.add_css_class("flat"); self.btn_link.connect("clicked", self.on_link_clicked)
        btn_code = Gtk.Button(icon_name="utilities-terminal-symbolic")
        btn_code.add_css_class("flat"); btn_code.connect("clicked", lambda _: self.insert_markdown("`", "`"))
        self.btn_check = Gtk.ToggleButton(icon_name="checkbox-checked-symbolic")
        self.btn_check.add_css_class("flat"); self.btn_check.connect("toggled", self.on_check_toggled)

        for b in (btn_bold, btn_italic, btn_h1, self.btn_link, btn_code, self.btn_check):
            format_box.append(b)
        editor_container.append(format_box)

        self.editor_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.editor_paned.set_position(450)
        self.editor_paned.set_wide_handle(True)
        self.editor_paned.set_vexpand(True)
        
        self.editor_scroll = Gtk.ScrolledWindow()
        self.editor_scroll.add_css_class("editor-card")
        self.editor_scroll.add_css_class("floating-panel")
        self.editor_scroll.set_vexpand(True); self.editor_scroll.set_hexpand(True)
        
        self.text_view = Gtk.TextView()
        self.text_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self.text_view.add_css_class("note-text")
        self.text_view.set_vexpand(True); self.text_view.set_hexpand(True)
        self.text_view.get_buffer().connect("changed", self.on_text_changed)
        
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self.on_key_pressed)
        self.text_view.add_controller(key_ctrl)
        self.editor_scroll.set_child(self.text_view)
        
        self.web_scroll = Gtk.ScrolledWindow()
        self.web_scroll.add_css_class("floating-panel")
        self.web_scroll.set_vexpand(True); self.web_scroll.set_hexpand(True)

        if WEBKIT_AVAILABLE:
            self.web_view = WebKit.WebView(network_session=self.network_session)
            bg = Gdk.RGBA(); bg.parse("rgba(0,0,0,0)")
            self.web_view.set_background_color(bg)
            self.web_view.connect("decide-policy", self.on_decide_policy)
            self.web_scroll.set_child(self.web_view)
        else:
            lbl = Gtk.Label(label="WebKit не установлен.")
            self.web_scroll.set_child(lbl)

        self.editor_paned.set_start_child(self.editor_scroll)
        self.editor_paned.set_end_child(self.web_scroll)
        editor_container.append(self.editor_paned)
        
        main_paned.set_end_child(editor_container)

        self.monitor = self.notes_dir.monitor_directory(Gio.FileMonitorFlags.NONE, None)
        self.monitor.connect("changed", self._on_dir_changed)

        GLib.timeout_add_seconds(2, self.auto_save)

        last = self.config.get("last_file")
        if last and os.path.exists(last):
            self.load_file(last)
        else:
            self.new_note()

        self.restart_hotkey_listener()
        self.win.present()

        # --- WEBAPP (ОТДЕЛЬНОЕ ОКНО) ---
    def create_webapp_window(self):
        self.webapp_win = Adw.Window(transient_for=self.win)
        self.webapp_win.set_default_size(450, 700)
        self.webapp_win.set_title("Веб-панель")
        
        # Обработка закрытия окна крестиком
        def on_webapp_close(*args):
            self.btn_webapp.set_active(False)
            self.webapp_win = None
            return False
            
        self.webapp_win.connect("close-request", on_webapp_close)

        # Создаем шапку (HeaderBar), за которую можно будет таскать окно
        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_show_title(True)
        toolbar_view.add_top_bar(header)

        if WEBKIT_AVAILABLE:
            self.webapp_view = WebKit.WebView(network_session=self.network_session)
            # Кладем веб-вьюху внутрь ToolbarView, а не напрямую в окно
            toolbar_view.set_content(self.webapp_view)
            self.load_webapp_url()

        self.webapp_win.set_content(toolbar_view)

    def load_webapp_url(self):
        url = self.config.get("webapp_url", "https://chat.deepseek.com")
        if not url.startswith("http"):
            url = "https://" + url
        if WEBKIT_AVAILABLE and self.webapp_view:
            self.webapp_view.load_uri(url)

    def on_webapp_toggled(self, btn):
        if btn.get_active():
            if not self.webapp_win:
                self.create_webapp_window()
            self.webapp_win.present()
        else:
            if self.webapp_win:
                self.webapp_win.close()

    # --- ССЫЛКИ И ВНУТРЕННИЙ БРАУЗЕР ---
    def on_decide_policy(self, web_view, decision, decision_type):
        if decision_type == WebKit.PolicyDecisionType.NAVIGATION_ACTION:
            nav_action = decision.get_navigation_action()
            request = nav_action.get_request()
            uri = request.get_uri()
            
            if uri.startswith("http") and nav_action.get_mouse_button() > 0:
                behavior = self.config.get("link_behavior", "external")
                if behavior == "external":
                    subprocess.Popen(["xdg-open", uri])
                    decision.ignore()
                    return True
                elif behavior == "internal":
                    self.btn_back.set_visible(True)
        return False

    # --- ЛОГИКА ЧЕК-ЛИСТА И ENTER ---
    def on_key_pressed(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Return:
            buf = self.text_view.get_buffer()
            insert_iter = buf.get_iter_at_mark(buf.get_insert())
            start_iter = insert_iter.copy()
            start_iter.set_line_offset(0)
            line_text = buf.get_text(start_iter, insert_iter, False)
            
            if line_text.strip() == "- [ ]":
                buf.delete(start_iter, insert_iter)
                buf.insert_at_cursor("\n")
                return True
            elif line_text.strip().startswith("- [ ] ") or line_text.strip().startswith("- [x] "):
                buf.insert_at_cursor("\n- [ ] ")
                GLib.timeout_add(50, self._scroll_to_cursor)
                return True
        return False

    def _scroll_to_cursor(self):
        buf = self.text_view.get_buffer()
        insert_iter = buf.get_iter_at_mark(buf.get_insert())
        self.text_view.scroll_to_iter(insert_iter, 0.1, False, 0.0, 0.0)
        return False

    def on_check_toggled(self, btn):
        if btn.get_active():
            buf = self.text_view.get_buffer()
            insert_iter = buf.get_iter_at_mark(buf.get_insert())
            start_iter = insert_iter.copy()
            start_iter.set_line_offset(0)
            line_text = buf.get_text(start_iter, insert_iter, False)
            
            if not line_text.strip().startswith("- [ ] "):
                buf.insert_at_cursor("- [ ] ")
            self.text_view.grab_focus()
        else:
            self.text_view.grab_focus()

    def on_link_clicked(self, btn):
        buf = self.text_view.get_buffer()
        selected_text = ""
        if buf.get_has_selection():
            start, end = buf.get_selection_bounds()
            selected_text = buf.get_text(start, end, False)
        
        dialog = Gtk.Dialog(transient_for=self.win, modal=True, title="Вставить ссылку")
        dialog.add_button("Отмена", Gtk.ResponseType.CANCEL)
        dialog.add_button("ОК", Gtk.ResponseType.OK)
        
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(12); box.set_margin_bottom(12); box.set_margin_start(12); box.set_margin_end(12)
        
        entry_text = Gtk.Entry(placeholder_text="Текст ссылки")
        entry_text.set_text(selected_text)
        entry_url = Gtk.Entry(placeholder_text="URL (https://...)")
        
        box.append(entry_text)
        box.append(entry_url)
        dialog.get_content_area().append(box)
        
        dialog.connect("response", self.on_link_response, entry_text, entry_url)
        dialog.present()

    def on_link_response(self, dialog, response, entry_text, entry_url):
        if response == Gtk.ResponseType.OK:
            text = entry_text.get_text().strip()
            url = entry_url.get_text().strip()
            if text and url:
                md_link = f"[{text}]({url})"
                buf = self.text_view.get_buffer()
                if buf.get_has_selection():
                    start, end = buf.get_selection_bounds()
                    buf.delete(start, end)
                buf.insert_at_cursor(md_link)
                self.text_view.grab_focus()
        dialog.destroy()

    def insert_markdown(self, prefix, suffix):
        buf = self.text_view.get_buffer()
        if buf.get_has_selection():
            start, end = buf.get_selection_bounds()
            text = buf.get_text(start, end, False)
            buf.delete(start, end)
            buf.insert_at_cursor(prefix + text + suffix)
        else:
            buf.insert_at_cursor(prefix + suffix)
            cursor_pos = buf.get_property("cursor-position")
            cursor_iter = buf.get_iter_at_offset(cursor_pos - len(suffix))
            buf.place_cursor(cursor_iter)
        self.text_view.grab_focus()

    # --- АНИМАЦИЯ ГЛАЗА ---
    def on_view_toggled(self, btn):
        if btn.get_active():
            self.animate_paned(0)
            self.btn_view.set_tooltip_text("Показать исходный код")
        else:
            self.animate_paned(450)
            self.btn_view.set_tooltip_text("Скрыть исходный код")
            self.text_view.grab_focus()

    def animate_paned(self, target_pos):
        start_pos = self.editor_paned.get_position()
        if start_pos == target_pos: return
        if target_pos > 0: self.editor_scroll.set_visible(True)

        target = Adw.CallbackAnimationTarget.new(lambda val: self.editor_paned.set_position(int(val)))
        anim = Adw.TimedAnimation.new(self.editor_paned, start_pos, target_pos, 250, target)
        anim.set_easing(Adw.Easing.EASE_OUT_CUBIC)
        
        def on_done():
            if target_pos == 0:
                self.editor_scroll.set_visible(False)
                
        anim.connect("done", lambda *args: on_done())
        anim.play()

    def update_preview(self):
        if not WEBKIT_AVAILABLE or not MARKDOWN_AVAILABLE:
            return

        self.btn_back.set_visible(False) 
        
        buf = self.text_view.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        html_body = markdown.markdown(text, extensions=['fenced_code', 'tables', 'nl2br'])
        html_body = re.sub(r'<li>\s*\[\s*\]\s*', '<li><input type="checkbox" disabled> ', html_body)
        html_body = re.sub(r'<li>\s*\[[xX]\]\s*', '<li><input type="checkbox" checked disabled> ', html_body)
        
        is_dark = Adw.StyleManager.get_default().get_dark()
        bg_color = "#1e1e1e" if is_dark else "#ffffff"
        fg_color = "#e0e0e0" if is_dark else "#1a1a1a"
        code_bg = "rgba(255,255,255,0.1)" if is_dark else "rgba(0,0,0,0.05)"
        
        html = f"""
        <html><head><style>
            body {{ font-family: sans-serif; font-size: 16px; line-height: 1.7; color: {fg_color}; background-color: {bg_color}; padding: 24px; word-wrap: break-word; }}
            h1, h2, h3, h4 {{ border-bottom: 1px solid rgba(128,128,128,0.2); padding-bottom: 0.3em; margin-top: 1.2em; }}
            code {{ background-color: {code_bg}; padding: 0.2em 0.4em; border-radius: 4px; font-family: monospace; }}
            pre code {{ display: block; padding: 1em; overflow: auto; }}
            a {{ color: #5a9aff; text-decoration: none; }}
            a:hover {{ text-decoration: underline; }}
            blockquote {{ border-left: 4px solid #5a9aff; margin: 0; padding-left: 1em; color: #888; }}
            img {{ max-width: 100%; border-radius: 8px; }}
            table {{ border-collapse: collapse; width: 100%; }}
            th, td {{ border: 1px solid rgba(128,128,128,0.2); padding: 8px; }}
            input[type="checkbox"] {{ margin-right: 8px; }}
            ul {{ padding-left: 20px; }}
        </style></head><body>{html_body}</body></html>
        """
        self.web_view.load_html(html, "file:///")

    def open_settings(self):
        if self.win:
            SettingsWindow(self).present()

    def save_config(self):
        self._save_config(self.config)

    def restart_hotkey_listener(self):
        if not PYNPUT_AVAILABLE: return
        if self.hotkey_listener:
            self.hotkey_listener.stop()
            self.hotkey_listener = None
        if not self.config.get("hotkey_enabled", True): return
        combo = self.config.get("hotkey_combo", "<ctrl>+<alt>+n")
        try:
            self.hotkey_listener = keyboard.GlobalHotKeys({combo: self.on_hotkey_triggered})
            self.hotkey_listener.start()
        except Exception as e:
            print(f"Ошибка хоткея: {e}")

    def on_hotkey_triggered(self):
        GLib.idle_add(self.trigger_add_clipboard)

    def trigger_add_clipboard(self):
        if self.win:
            self.win.present()
            self.btn_view.set_active(False)
        
        text, is_html = self._get_clipboard_text()
        if not text: return
            
        if is_html:
            try:
                from markdownify import markdownify as md
                final_text = md(text, heading_style="ATX")
            except ImportError:
                final_text = text
        else:
            final_text = text
        self.insert_external_text(final_text)

    def _get_clipboard_text(self):
        if sys.platform == "linux":
            try:
                html_primary = subprocess.run(["xclip", "-o", "-selection", "primary", "-t", "text/html"], capture_output=True, text=True, timeout=2)
                if html_primary.stdout: return html_primary.stdout, True
                html_clip = subprocess.run(["xclip", "-o", "-selection", "clipboard", "-t", "text/html"], capture_output=True, text=True, timeout=2)
                if html_clip.stdout: return html_clip.stdout, True
                text_primary = subprocess.run(["xclip", "-o", "-selection", "primary"], capture_output=True, text=True, timeout=2)
                if text_primary.stdout: return text_primary.stdout, False
            except Exception: pass
        if PYPERCLIP_AVAILABLE:
            try:
                text = pyperclip.paste()
                if text: return text, False
            except Exception: pass
        return "", False

    def insert_external_text(self, text):
        if not self.win: self.on_activate()
        if not self.current_file: self.new_note()
            
        buf = self.text_view.get_buffer()
        if buf.get_char_count() > 0: buf.insert_at_cursor("\n\n")
        buf.insert_at_cursor(text)
        
        self.win.present()
        self.text_view.grab_focus()
        buf.place_cursor(buf.get_end_iter())
        self.text_view.scroll_to_iter(buf.get_end_iter(), 0.0, False, 0.0, 0.0)
        self.dirty = True
        self.save_label.set_text("● Не сохранено")
        self.save_label.remove_css_class("dim-label")

    def _get_next_note_path(self):
        base = "Новая заметка"
        path = os.path.join(NOTES_DIR, f"{base}.rnote")
        if not os.path.exists(path): return path, base
        counter = 2
        while True:
            name = f"{base} {counter}"
            path = os.path.join(NOTES_DIR, f"{name}.rnote")
            if not os.path.exists(path): return path, name
            counter += 1

    def _load_dir(self, file):
        store = Gio.ListStore.new(Gio.File)
        try:
            enumerator = file.enumerate_children("standard::name,standard::type", Gio.FileQueryInfoFlags.NONE, None)
            for info in enumerator:
                child = file.get_child(info.get_name())
                if info.get_file_type() == Gio.FileType.DIRECTORY: store.append(child)
                elif info.get_file_type() == Gio.FileType.REGULAR and child.get_basename().endswith(".rnote"): store.append(child)
        except Exception: pass
        return store

    def _create_child_model(self, file):
        if file.query_file_type(Gio.FileQueryInfoFlags.NONE, None) == Gio.FileType.DIRECTORY: return self._load_dir(file)
        return None

    def _on_dir_changed(self, monitor, file, other_file, event_type):
        if event_type in (Gio.FileMonitorEvent.CREATED, Gio.FileMonitorEvent.DELETED, Gio.FileMonitorEvent.MOVED_IN, Gio.FileMonitorEvent.MOVED_OUT):
            self.is_loading = True
            current_path = self.current_file
            new_store = self._load_dir(self.notes_dir)
            self.notes_store.remove_all()
            for f in new_store: self.notes_store.append(f)
            self.is_loading = False
            
            if self.pending_select is not None:
                idx = self.pending_select
                self.pending_select = None
                if idx >= 0 and idx < self.notes_store.get_n_items():
                    def select_pending():
                        self.is_loading = True
                        self.selection_model.set_selected(idx)
                        self.is_loading = False
                        tree_row = self.tree_model.get_item(idx)
                        if tree_row:
                            f = tree_row.get_item()
                            if f and f.query_file_type(Gio.FileQueryInfoFlags.NONE, None) == Gio.FileType.REGULAR: self.load_file(f.get_path())
                        return False
                    GLib.idle_add(select_pending)
                    return

            if current_path and os.path.exists(current_path):
                def select_current():
                    for i in range(self.notes_store.get_n_items()):
                        if self.notes_store.get_item(i).get_path() == current_path:
                            self.is_loading = True
                            self.selection_model.set_selected(i)
                            self.is_loading = False
                            break
                    return False
                GLib.idle_add(select_current)

    def _setup_tree_item(self, factory, list_item):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.add_css_class("note-row")
        image = Gtk.Image()
        label = Gtk.Label(xalign=0)
        label.set_ellipsize(3)
        box.append(image); box.append(label)
        gesture = Gtk.GestureClick()
        gesture.connect("pressed", self._on_item_pressed, list_item)
        box.add_controller(gesture)
        list_item.set_child(box)

    def _bind_tree_item(self, factory, list_item):
        box = list_item.get_child()
        image = box.get_first_child()
        label = image.get_next_sibling()
        tree_row = list_item.get_item()
        file = tree_row.get_item()
        
        if file.query_file_type(Gio.FileQueryInfoFlags.NONE, None) == Gio.FileType.DIRECTORY:
            image.set_from_icon_name("folder-symbolic")
            label.set_text(file.get_basename())
        else:
            image.set_from_icon_name("text-x-generic-symbolic")
            name = file.get_basename()
            if name.endswith(".rnote"): name = name[:-6]
            label.set_text(name)

    def _on_item_pressed(self, gesture, n_press, x, y, list_item):
        tree_row = list_item.get_item()
        if not tree_row: return
        file = tree_row.get_item()
        if not file: return
        if file.query_file_type(Gio.FileQueryInfoFlags.NONE, None) == Gio.FileType.DIRECTORY: return
        path = file.get_path()
        if n_press == 1:
            if path != self.current_file:
                self._save_current()
                self.load_file(path)
            self.is_loading = True
            self.selection_model.set_selected(list_item.get_position())
            self.is_loading = False
        elif n_press == 2:
            self.rename_note(file)

    def on_selection_changed(self, model, position, n_items):
        if self.is_loading: return
        tree_row = model.get_item(position)
        if tree_row is None: return
        file = tree_row.get_item()
        if file is None: return
        if file.query_file_type(Gio.FileQueryInfoFlags.NONE, None) == Gio.FileType.REGULAR:
            path = file.get_path()
            if path == self.current_file: return
            self._save_current()
            self.load_file(path)

    def _get_body(self):
        buf = self.text_view.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def _cleanup_empty_current(self):
        if self.current_file and not self._get_body().strip():
            if os.path.exists(self.current_file):
                try: os.remove(self.current_file)
                except Exception: pass

    def _save_current(self):
        if self.dirty and self.current_file:
            body = self._get_body()
            if body.strip(): self._write_file(self.current_file)
            else: self._cleanup_empty_current()
            self.dirty = False
            self.save_label.set_text("Сохранено ✓")
            self.save_label.add_css_class("dim-label")

    def on_text_changed(self, buf):
        if self.is_loading: return
        self.dirty = True
        self.save_label.set_text("● Не сохранено")
        self.save_label.remove_css_class("dim-label")
        self.update_preview()

    def auto_save(self):
        if not self.is_loading: self._save_current()
        return True

    def on_close(self, window):
        if not self.is_loading: self._save_current()
        if self.current_file:
            self.config["last_file"] = self.current_file
            self.save_config()
        return False

    def new_note(self):
        if self.is_loading: return
        self._save_current()
        path, name = self._get_next_note_path()
        self.current_file = path
        self.is_loading = True
        self.text_view.get_buffer().set_text("")
        self.is_loading = False
        self.dirty = False
        self.update_title()
        self.save_label.set_text("Сохранено ✓")
        self.text_view.grab_focus()

    def delete_note(self):
        if not self.current_file: return
        selected = self.selection_model.get_selected()
        n_items = self.notes_store.get_n_items()
        if n_items > 1: self.pending_select = selected if selected < n_items - 1 else n_items - 2
        else: self.pending_select = -1
        try:
            if os.path.exists(self.current_file): os.remove(self.current_file)
        except Exception as e:
            print("Ошибка удаления:", e)
            return
        self.current_file = None
        self.is_loading = True
        self.text_view.get_buffer().set_text("")
        self.is_loading = False
        self.dirty = False
        if self.pending_select == -1: self.new_note()

    def load_file(self, path):
        try:
            with open(path, 'r', encoding='utf-8') as f: data = json.load(f)
            self.is_loading = True
            self.text_view.get_buffer().set_text(data.get("body", ""))
            self.is_loading = False
            self.current_file = path
            self.dirty = False
            self.update_title()
            self.save_label.set_text("Сохранено ✓")
            self.save_label.add_css_class("dim-label")
            self.update_preview()
        except Exception as e:
            print("Ошибка загрузки:", e)

    def update_title(self):
        if self.current_file:
            name = os.path.splitext(os.path.basename(self.current_file))[0]
            self.win.set_title(f"Right Note — {name}")
        else: self.win.set_title("Right Note")

    def rename_note(self, file):
        dialog = Gtk.Dialog(transient_for=self.win, modal=True)
        dialog.set_title("Переименовать")
        entry = Gtk.Entry()
        entry.set_text(os.path.splitext(file.get_basename())[0])
        entry.set_margin_top(12); entry.set_margin_bottom(12)
        entry.set_margin_start(12); entry.set_margin_end(12)
        dialog.get_content_area().append(entry)
        dialog.add_button("Отмена", Gtk.ResponseType.CANCEL)
        dialog.add_button("ОК", Gtk.ResponseType.OK)
        dialog.connect("response", self.on_rename_response, file)
        dialog.present()

    def on_rename_response(self, dialog, response, file):
        if response == Gtk.ResponseType.OK:
            entry = dialog.get_content_area().get_first_child()
            new_name = entry.get_text().strip()
            if new_name:
                old_path = file.get_path()
                new_path = os.path.join(os.path.dirname(old_path), new_name + ".rnote")
                if old_path != new_path:
                    try:
                        os.rename(old_path, new_path)
                        if self.current_file == old_path:
                            self.current_file = new_path
                            self.update_title()
                    except Exception as e: print("Ошибка переименования:", e)
        dialog.destroy()

    def open_file(self):
        dialog = Gtk.FileDialog()
        dialog.set_title("Открыть заметку")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        f = Gtk.FileFilter()
        f.set_name("Right Note (*.rnote)")
        f.add_pattern("*.rnote")
        filters.append(f)
        dialog.set_filters(filters)
        dialog.open(self.win, None, self.on_open_done)

    def on_open_done(self, dialog, result):
        try: file = dialog.open_finish(result)
        except GLib.Error: return
        self._save_current()
        self.load_file(file.get_path())

    def save_file_as(self):
        dialog = Gtk.FileDialog()
        dialog.set_title("Сохранить заметку")
        dialog.set_initial_name("note.rnote")
        dialog.save(self.win, None, self.on_save_done)

    def on_save_done(self, dialog, result):
        try: file = dialog.save_finish(result)
        except GLib.Error: return
        path = file.get_path()
        if not path.endswith(".rnote"): path += ".rnote"
        self.current_file = path
        self._write_file(path)
        self.dirty = False
        self.update_title()
        self.save_label.set_text("Сохранено ✓")

    def _write_file(self, path):
        body = self._get_body()
        now = datetime.datetime.now().isoformat(timespec="seconds")
        created = now
        try:
            with open(path, 'r', encoding='utf-8') as f: created = json.load(f).get("created", now)
        except Exception: pass
        data = {
            "version": 1, "format": "right-note",
            "title": os.path.splitext(os.path.basename(path))[0],
            "created": created, "modified": now,
            "body": body, "attachments": [], "links": [], "tags": [],
        }
        parent = os.path.dirname(path)
        if parent: os.makedirs(parent, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_config(self):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f: return json.load(f)
        except Exception: return {}

    def _save_config(self, data):
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f: json.dump(data, f)
        except Exception: pass

if __name__ == "__main__":
    app = RightNoteApp()
    app.run(sys.argv)