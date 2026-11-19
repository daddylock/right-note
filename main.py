import gi
import json
import os
import datetime

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, GLib

APP_DIR = os.path.expanduser("~/.local/share/right-note")
DEFAULT_FILE = os.path.join(APP_DIR, "current.rnote")


class RightNoteApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id='com.daniil.rightnote')
        self.connect('activate', self.on_activate)
        os.makedirs(APP_DIR, exist_ok=True)

    def on_activate(self, app):
        self.win = Adw.ApplicationWindow(application=app)
        self.win.set_default_size(450, 350)
        self.win.connect("close-request", self.on_close)

        self.current_file = DEFAULT_FILE
        self.dirty = False

        # ---- HeaderBar (за неё можно тащить окно) ----
        header = Adw.HeaderBar()
        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)

        # Основной layout: сайдбар + редактор
        main = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        toolbar_view.set_content(main)
        self.win.set_content(toolbar_view)

        # ---- Сайдбар ----
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        self.menu_list = Gtk.ListBox()
        self.menu_list.add_css_class("navigation-sidebar")
        self.menu_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.menu_list.connect("row-activated", self.on_menu_action)

        menu_items = [
            ("new",     "📄  Новая"),
            ("open",    "📂  Открыть"),
            ("save_as", "💾  Сохранить как…"),
        ]

        for action_id, label in menu_items:
            row = Gtk.ListBoxRow()
            row.action_id = action_id
            lbl = Gtk.Label(label=label, xalign=0)
            lbl.set_margin_top(6)
            lbl.set_margin_bottom(6)
            lbl.set_margin_start(10)
            lbl.set_margin_end(10)
            row.set_child(lbl)
            self.menu_list.append(row)

        sidebar_scroll = Gtk.ScrolledWindow()
        sidebar_scroll.set_child(self.menu_list)
        sidebar_scroll.set_vexpand(True)
        sidebar.append(sidebar_scroll)
        sidebar.set_size_request(160, -1)
        main.set_start_child(sidebar)

        # ---- Редактор ----
        editor_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.text_view = Gtk.TextView()
        self.text_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self.text_view.set_margin_top(10)
        self.text_view.set_margin_bottom(10)
        self.text_view.set_margin_start(10)
        self.text_view.set_margin_end(10)
        self.text_view.get_buffer().connect("changed", self.on_text_changed)

        editor_scroll = Gtk.ScrolledWindow()
        editor_scroll.set_child(self.text_view)
        editor_box.append(editor_scroll)
        main.set_end_child(editor_box)

        # Загружаем последнюю заметку
        self.load_from(self.current_file)
        self.update_title()

        # Автосохранение каждые 2 секунды
        GLib.timeout_add_seconds(2, self.auto_save)

        self.win.present()

    def update_title(self):
        name = os.path.basename(self.current_file)
        if name == "current.rnote":
            self.win.set_title("Right Note")
        else:
            self.win.set_title(f"Right Note — {name}")

    def on_text_changed(self, buf):
        self.dirty = True

    def auto_save(self):
        if self.dirty:
            self._write_file(self.current_file)
            self.dirty = False
        return True  # таймер продолжает работать

    def on_close(self, window):
        if self.dirty:
            self._write_file(self.current_file)
        return False  # разрешаем закрытие

    def on_menu_action(self, listbox, row):
        action = row.action_id
        if action == "new":
            self.new_note()
        elif action == "open":
            self.open_file()
        elif action == "save_as":
            self.save_file_as()

    def new_note(self):
        self.text_view.get_buffer().set_text("")
        self.current_file = DEFAULT_FILE
        self.update_title()

    def load_from(self, path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.text_view.get_buffer().set_text(data.get("body", ""))
            self.dirty = False
        except FileNotFoundError:
            pass
        except Exception as e:
            print("Ошибка загрузки:", e)

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
        path = file.get_path()
        self.current_file = path
        self.load_from(path)
        self.update_title()

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

    def _write_file(self, path):
        buf = self.text_view.get_buffer()
        body = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        now = datetime.datetime.now().isoformat(timespec="seconds")
        data = {
            "version": 1,
            "format": "right-note",
            "title": os.path.splitext(os.path.basename(path))[0],
            "created": now,
            "modified": now,
            "body": body,
            "attachments": [],
            "links": [],
            "tags": [],
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    app = RightNoteApp()
    app.run(None)