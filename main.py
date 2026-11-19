import os
import sys
import gi
import json
import datetime
import subprocess

# Жестко требуем GTK 4 и Adwaita
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

# Пытаемся подключить WebKit 6.0 (для GTK4)
WEBKIT_AVAILABLE = False
try:
    gi.require_version('WebKit', '6.0')
    from gi.repository import WebKit
    WEBKIT_AVAILABLE = True
except (ValueError, ImportError):
    print("⚠️ WebKit 6.0 не найден. Просмотр Markdown будет отключен.")

from gi.repository import Gtk, Adw, Gio, GLib, Gdk

# Импорты для работы с текстом и хоткеями
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

def load_css():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    css_path = os.path.join(base_dir, "style.css")
    if os.path.exists(css_path):
        provider = Gtk.CssProvider()
        provider.load_from_path(css_path)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

class SettingsWindow(Adw.PreferencesWindow):
    def __init__(self, parent_app):
        super().__init__(transient_for=parent_app.win, modal=True)
        self.app = parent_app
        self.set_title("Настройки")
        self.set_default_size(400, 300)

        page = Adw.PreferencesPage()
        self.add(page)

        group = Adw.PreferencesGroup(title="Глобальный хоткей")
        page.add(group)

        self.switch_enabled = Adw.SwitchRow(title="Включить хоткей")
        self.switch_enabled.set_active(self.app.config.get("hotkey_enabled", True))
        self.switch_enabled.connect("notify::active", self.on_switch_toggle)
        group.add(self.switch_enabled)

        self.entry_hotkey = Adw.EntryRow(title="Комбинация (например, Ctrl+Alt+N)")
        self.entry_hotkey.set_text(self.app.config.get("hotkey_combo", "<ctrl>+<alt>+n"))
        self.entry_hotkey.connect("changed", self.on_hotkey_changed)
        group.add(self.entry_hotkey)

    def on_switch_toggle(self, switch, pspec=None):
        self.app.config["hotkey_enabled"] = switch.get_active()
        self.app.save_config()
        self.app.restart_hotkey_listener()

    def on_hotkey_changed(self, entry):
        self.app.config["hotkey_combo"] = entry.get_text()
        self.app.save_config()
        self.app.restart_hotkey_listener()


class RightNoteApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id='com.daniil.rightnote',
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.connect('activate', self.on_activate)
        self.connect('command-line', self.on_command_line)
        
        os.makedirs(NOTES_DIR, exist_ok=True)
        os.makedirs(CONFIG_DIR, exist_ok=True)
        
        self.dirty = False
        self.is_loading = False
        self.current_file = None
        self.pending_select = None
        self.hotkey_listener = None
        self.win = None
        
        self.config = self._load_config()
        if "hotkey_combo" not in self.config:
            self.config["hotkey_combo"] = "<ctrl>+<alt>+n"
        if "hotkey_enabled" not in self.config:
            self.config["hotkey_enabled"] = True
            
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
        ]
        for name, handler, accels in actions:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda *_, h=handler: h())
            self.add_action(action)
            self.set_accels_for_action(f"app.{name}", accels)

    def quit_app(self):
        if self.hotkey_listener:
            self.hotkey_listener.stop()
        if self.win:
            self.win.close()
        else:
            self.quit()

    def on_activate(self, app=None):
        if self.win:
            self.win.present()
            return

        load_css()

        self.win = Adw.ApplicationWindow(application=self)
        self.win.set_default_size(850, 600)
        self.win.connect("close-request", self.on_close)

        # --- ШАПКА ---
        header = Adw.HeaderBar()
        
        self.btn_view = Gtk.ToggleButton(icon_name="view-reveal-symbolic")
        self.btn_view.set_tooltip_text("Переключить Редактор / Просмотр")
        self.btn_view.connect("toggled", self.on_view_toggled)
        header.pack_start(self.btn_view)

        self.save_label = Gtk.Label(label="Сохранено")
        self.save_label.add_css_class("dim-label")
        self.save_label.add_css_class("save-status")
        header.pack_end(self.save_label)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)

        # --- ОСНОВНОЙ ЛЭЙАУТ ---
        main = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        main.set_position(250)
        main.set_resize_start_child(False)
        main.set_wide_handle(True)
        main.set_vexpand(True)
        main.set_hexpand(True)
        toolbar_view.set_content(main)
        self.win.set_content(toolbar_view)

        # --- САЙДБАР ---
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sidebar.add_css_class("sidebar-box")
        sidebar.add_css_class("floating-panel")
        sidebar.set_size_request(200, -1)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        btn_box.set_margin_top(10)
        btn_box.set_margin_bottom(10)
        btn_box.set_margin_start(10)
        btn_box.set_margin_end(10)
        btn_box.set_homogeneous(True)

        btn_new = Gtk.Button(icon_name="document-new-symbolic")
        btn_new.set_tooltip_text("Новая заметка (Ctrl+N)")
        btn_new.add_css_class("sidebar-btn")
        btn_new.add_css_class("flat")
        btn_new.connect("clicked", lambda _: self.new_note())
        
        btn_open = Gtk.Button(icon_name="document-open-symbolic")
        btn_open.set_tooltip_text("Открыть заметку (Ctrl+O)")
        btn_open.add_css_class("sidebar-btn")
        btn_open.add_css_class("flat")
        btn_open.connect("clicked", lambda _: self.open_file())
        
        btn_save = Gtk.Button(icon_name="document-save-as-symbolic")
        btn_save.set_tooltip_text("Сохранить как... (Ctrl+Shift+S)")
        btn_save.add_css_class("sidebar-btn")
        btn_save.add_css_class("flat")
        btn_save.connect("clicked", lambda _: self.save_file_as())

        btn_del = Gtk.Button(icon_name="user-trash-symbolic")
        btn_del.set_tooltip_text("Удалить заметку (Ctrl+Delete)")
        btn_del.add_css_class("sidebar-btn")
        btn_del.add_css_class("flat")
        btn_del.connect("clicked", lambda _: self.delete_note())

        btn_settings = Gtk.Button(icon_name="emblem-system-symbolic")
        btn_settings.set_tooltip_text("Настройки (Ctrl+,)")
        btn_settings.add_css_class("sidebar-btn")
        btn_settings.add_css_class("flat")
        btn_settings.connect("clicked", lambda _: self.open_settings())

        btn_box.append(btn_new)
        btn_box.append(btn_open)
        btn_box.append(btn_save)
        btn_box.append(btn_del)
        btn_box.append(btn_settings)
        sidebar.append(btn_box)

        # Дерево заметок
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
        notes_scroll.set_margin_top(4)
        notes_scroll.set_margin_bottom(8)
        sidebar.append(notes_scroll)

        main.set_start_child(sidebar)

        # --- РЕДАКТОР / ПРОСМОТР (STACK) ---
        editor_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        editor_container.add_css_class("editor-container")
        editor_container.set_hexpand(True)
        editor_container.set_vexpand(True)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_hexpand(True)
        self.stack.set_vexpand(True)
        
        # 1. Редактор (TextView)
        editor_scroll = Gtk.ScrolledWindow()
        editor_scroll.add_css_class("editor-card")
        editor_scroll.add_css_class("floating-panel")
        editor_scroll.set_vexpand(True)
        editor_scroll.set_hexpand(True)
        
        self.text_view = Gtk.TextView()
        self.text_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self.text_view.add_css_class("note-text")
        self.text_view.set_vexpand(True)
        self.text_view.set_hexpand(True)
        self.text_view.get_buffer().connect("changed", self.on_text_changed)
        editor_scroll.set_child(self.text_view)

        # 2. Просмотр (WebKit 6.0)
        if WEBKIT_AVAILABLE:
            self.web_view = WebKit.WebView()
            self.web_view.set_background_color(Gdk.RGBA(0, 0, 0, 0)) 
            web_scroll = Gtk.ScrolledWindow()
            web_scroll.add_css_class("floating-panel")
            web_scroll.set_vexpand(True)
            web_scroll.set_hexpand(True)
            web_scroll.set_child(self.web_view)
            preview_widget = web_scroll
        else:
            preview_widget = Gtk.Label(label="WebKit не установлен. Просмотр недоступен.")
            preview_widget.set_margin_top(20)

        self.stack.add_named(editor_scroll, "editor")
        self.stack.add_named(preview_widget, "preview")
        editor_container.append(self.stack)
        main.set_end_child(editor_container)

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

    # --- ЛОГИКА ПЕРЕКЛЮЧЕНИЯ РЕЖИМОВ ---
    def on_view_toggled(self, btn):
        # Используем idle_add, чтобы GTK успел выделить место и не ломал редактор
        if btn.get_active():
            GLib.idle_add(self.stack.set_visible_child_name, "preview")
            GLib.idle_add(self.update_preview)
        else:
            GLib.idle_add(self.stack.set_visible_child_name, "editor")
            GLib.idle_add(self.text_view.grab_focus)

    def update_preview(self):
        if not WEBKIT_AVAILABLE or not MARKDOWN_AVAILABLE:
            return

        buf = self.text_view.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        
        html_body = markdown.markdown(text, extensions=['fenced_code', 'tables', 'nl2br'])
        
        is_dark = Adw.StyleManager.get_default().get_dark()
        bg_color = "#1e1e1e" if is_dark else "#ffffff"
        fg_color = "#e0e0e0" if is_dark else "#1a1a1a"
        code_bg = "rgba(255,255,255,0.1)" if is_dark else "rgba(0,0,0,0.05)"
        
        html = f"""
        <html>
        <head>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
                font-size: 16px;
                line-height: 1.6;
                color: {fg_color};
                background-color: {bg_color};
                padding: 24px;
                word-wrap: break-word;
            }}
            h1, h2, h3, h4 {{ border-bottom: 1px solid rgba(128,128,128,0.2); padding-bottom: 0.3em; margin-top: 1.2em; }}
            code {{ background-color: {code_bg}; padding: 0.2em 0.4em; border-radius: 4px; font-family: monospace; }}
            pre code {{ display: block; padding: 1em; overflow: auto; }}
            a {{ color: #3584e4; text-decoration: none; }}
            a:hover {{ text-decoration: underline; }}
            blockquote {{ border-left: 4px solid #3584e4; margin: 0; padding-left: 1em; color: #888; }}
            img {{ max-width: 100%; border-radius: 8px; }}
            table {{ border-collapse: collapse; width: 100%; }}
            th, td {{ border: 1px solid rgba(128,128,128,0.2); padding: 8px; }}
        </style>
        </head>
        <body>
        {html_body}
        </body>
        </html>
        """
        self.web_view.load_html(html, None)

    # --- НАСТРОЙКИ И ХОТКЕИ ---
    def open_settings(self):
        if self.win:
            SettingsWindow(self).present()

    def save_config(self):
        self._save_config(self.config)

    def restart_hotkey_listener(self):
        if not PYNPUT_AVAILABLE:
            print("pynput не установлен. Хоткеи недоступны.")
            return
            
        if self.hotkey_listener:
            self.hotkey_listener.stop()
            self.hotkey_listener = None
            
        if not self.config.get("hotkey_enabled", True):
            return
            
        combo = self.config.get("hotkey_combo", "<ctrl>+<alt>+n")
        try:
            self.hotkey_listener = keyboard.GlobalHotKeys({
                combo: self.on_hotkey_triggered
            })
            self.hotkey_listener.start()
            print(f"Хоткей {combo} активирован.")
        except Exception as e:
            print(f"Ошибка настройки хоткея: {e}")

    def on_hotkey_triggered(self):
        GLib.idle_add(self.trigger_add_clipboard)

    def trigger_add_clipboard(self):
        if self.win:
            self.win.present()
            self.btn_view.set_active(False) 
        
        text, is_html = self._get_clipboard_text()
        if not text:
            return
            
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
                html_primary = subprocess.run(["xclip", "-o", "-selection", "primary", "-t", "text/html"], 
                                      capture_output=True, text=True, timeout=2)
                if html_primary.stdout:
                    return html_primary.stdout, True
                    
                html_clip = subprocess.run(["xclip", "-o", "-selection", "clipboard", "-t", "text/html"], 
                                      capture_output=True, text=True, timeout=2)
                if html_clip.stdout:
                    return html_clip.stdout, True

                text_primary = subprocess.run(["xclip", "-o", "-selection", "primary"], 
                                      capture_output=True, text=True, timeout=2)
                if text_primary.stdout:
                    return text_primary.stdout, False
                    
            except FileNotFoundError:
                print("⚠️ xclip не установлен.")
            except Exception:
                pass

        if PYPERCLIP_AVAILABLE:
            try:
                text = pyperclip.paste()
                if text:
                    return text, False
            except Exception:
                pass
                
        return "", False

    def insert_external_text(self, text):
        if not self.win:
            self.on_activate()
        
        if not self.current_file:
            self.new_note()
            
        buf = self.text_view.get_buffer()
        if buf.get_char_count() > 0:
            buf.insert_at_cursor("\n\n")
            
        buf.insert_at_cursor(text)
        
        self.win.present()
        self.text_view.grab_focus()
        buf.place_cursor(buf.get_end_iter())
        self.text_view.scroll_to_iter(buf.get_end_iter(), 0.0, False, 0.0, 0.0)
        self.dirty = True
        self.save_label.set_text("● Не сохранено")
        self.save_label.remove_css_class("dim-label")

    # --- ФАЙЛОВЫЕ ОПЕРАЦИИ ---
    def _get_next_note_path(self):
        base = "Новая заметка"
        path = os.path.join(NOTES_DIR, f"{base}.rnote")
        if not os.path.exists(path):
            return path, base
            
        counter = 2
        while True:
            name = f"{base} {counter}"
            path = os.path.join(NOTES_DIR, f"{name}.rnote")
            if not os.path.exists(path):
                return path, name
            counter += 1

    def _load_dir(self, file):
        store = Gio.ListStore.new(Gio.File)
        try:
            enumerator = file.enumerate_children("standard::name,standard::type", Gio.FileQueryInfoFlags.NONE, None)
            for info in enumerator:
                child = file.get_child(info.get_name())
                if info.get_file_type() == Gio.FileType.DIRECTORY:
                    store.append(child)
                elif info.get_file_type() == Gio.FileType.REGULAR and child.get_basename().endswith(".rnote"):
                    store.append(child)
        except Exception:
            pass
        return store

    def _create_child_model(self, file):
        if file.query_file_type(Gio.FileQueryInfoFlags.NONE, None) == Gio.FileType.DIRECTORY:
            return self._load_dir(file)
        return None

    def _on_dir_changed(self, monitor, file, other_file, event_type):
        if event_type in (Gio.FileMonitorEvent.CREATED, Gio.FileMonitorEvent.DELETED, Gio.FileMonitorEvent.MOVED_IN, Gio.FileMonitorEvent.MOVED_OUT):
            self.is_loading = True
            current_path = self.current_file
            
            new_store = self._load_dir(self.notes_dir)
            self.notes_store.remove_all()
            for f in new_store:
                self.notes_store.append(f)
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
                            if f and f.query_file_type(Gio.FileQueryInfoFlags.NONE, None) == Gio.FileType.REGULAR:
                                self.load_file(f.get_path())
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
        box.append(image)
        box.append(label)
        
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
            if name.endswith(".rnote"):
                name = name[:-6]
            label.set_text(name)

    def _on_item_pressed(self, gesture, n_press, x, y, list_item):
        tree_row = list_item.get_item()
        if not tree_row:
            return
        file = tree_row.get_item()
        if not file:
            return
            
        if file.query_file_type(Gio.FileQueryInfoFlags.NONE, None) == Gio.FileType.DIRECTORY:
            return
            
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
        if self.is_loading:
            return
        tree_row = model.get_item(position)
        if tree_row is None:
            return
        file = tree_row.get_item()
        if file is None:
            return
        
        if file.query_file_type(Gio.FileQueryInfoFlags.NONE, None) == Gio.FileType.REGULAR:
            path = file.get_path()
            if path == self.current_file:
                return
            
            self._save_current()
            self.load_file(path)

    def _get_body(self):
        buf = self.text_view.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def _cleanup_empty_current(self):
        if self.current_file and not self._get_body().strip():
            if os.path.exists(self.current_file):
                try:
                    os.remove(self.current_file)
                except Exception:
                    pass

    def _save_current(self):
        if self.dirty and self.current_file:
            body = self._get_body()
            if body.strip():
                self._write_file(self.current_file)
            else:
                self._cleanup_empty_current()
            self.dirty = False
            self.save_label.set_text("Сохранено ✓")
            self.save_label.add_css_class("dim-label")

    def on_text_changed(self, buf):
        if self.is_loading:
            return
        self.dirty = True
        self.save_label.set_text("● Не сохранено")
        self.save_label.remove_css_class("dim-label")
        
        if self.btn_view.get_active():
            self.update_preview()

    def auto_save(self):
        if not self.is_loading:
            self._save_current()
        return True

    def on_close(self, window):
        if not self.is_loading:
            self._save_current()
        if self.current_file:
            self.config["last_file"] = self.current_file
            self.save_config()
        return False

    def new_note(self):
        if self.is_loading:
            return
            
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
        if not self.current_file:
            return
            
        selected = self.selection_model.get_selected()
        n_items = self.notes_store.get_n_items()
        
        if n_items > 1:
            self.pending_select = selected if selected < n_items - 1 else n_items - 2
        else:
            self.pending_select = -1

        try:
            if os.path.exists(self.current_file):
                os.remove(self.current_file)
        except Exception as e:
            print("Ошибка удаления:", e)
            return
            
        self.current_file = None
        self.is_loading = True
        self.text_view.get_buffer().set_text("")
        self.is_loading = False
        self.dirty = False
        
        if self.pending_select == -1:
            self.new_note()

    def load_file(self, path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            self.is_loading = True
            self.text_view.get_buffer().set_text(data.get("body", ""))
            self.is_loading = False
            
            self.current_file = path
            self.dirty = False
            self.update_title()
            self.save_label.set_text("Сохранено ✓")
            self.save_label.add_css_class("dim-label")
            
            if self.btn_view.get_active():
                self.update_preview()
                
        except Exception as e:
            print("Ошибка загрузки:", e)

    def update_title(self):
        if self.current_file:
            name = os.path.splitext(os.path.basename(self.current_file))[0]
            self.win.set_title(f"Right Note — {name}")
        else:
            self.win.set_title("Right Note")

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
                    except Exception as e:
                        print("Ошибка переименования:", e)
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
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return
        self._save_current()
        self.load_file(file.get_path())

    def save_file_as(self):
        dialog = Gtk.FileDialog()
        dialog.set_title("Сохранить заметку")
        dialog.set_initial_name("note.rnote")
        dialog.save(self.win, None, self.on_save_done)

    def on_save_done(self, dialog, result):
        try:
            file = dialog.save_finish(result)
        except GLib.Error:
            return
        path = file.get_path()
        if not path.endswith(".rnote"):
            path += ".rnote"
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
            with open(path, 'r', encoding='utf-8') as f:
                created = json.load(f).get("created", now)
        except Exception:
            pass
        data = {
            "version": 1, "format": "right-note",
            "title": os.path.splitext(os.path.basename(path))[0],
            "created": created, "modified": now,
            "body": body, "attachments": [], "links": [], "tags": [],
        }
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_config(self):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_config(self, data):
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f)
        except Exception:
            pass

if __name__ == "__main__":
    app = RightNoteApp()
    app.run(sys.argv)