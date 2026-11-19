import gi
import json
import os
import datetime

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, GLib


class RightNoteApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id='com.daniil.rightnote')
        self.connect('activate', self.on_activate)

    def on_activate(self, app):
        self.win = Adw.ApplicationWindow(application=app)
        self.win.set_title("Right Note")
        self.win.set_default_size(950, 600)

        # Основной горизонтальный layout: сайдбар слева + редактор справа
        main = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.win.set_content(main)

        # ---- САЙДБАР ----
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        sidebar_title = Gtk.Label(label="Right Note", xalign=0)
        sidebar_title.add_css_class("title-4")
        sidebar_title.set_margin_top(12)
        sidebar_title.set_margin_bottom(12)
        sidebar_title.set_margin_start(12)
        sidebar_title.set_margin_end(12)
        sidebar.append(sidebar_title)

        # Список пунктов меню (потом станет деревом заметок)
        self.menu_list = Gtk.ListBox()
        self.menu_list.add_css_class("navigation-sidebar")
        self.menu_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.menu_list.connect("row-activated", self.on_menu_action)

        menu_items = [
            ("new",     "📄  Новая заметка"),
            ("open",    "📂  Открыть"),
            ("save",    "💾  Сохранить"),
            ("save_as", "💾  Сохранить как…"),
        ]

        for action_id, label in menu_items:
            row = Gtk.ListBoxRow()
            row.action_id = action_id
            lbl = Gtk.Label(label=label, xalign=0)
            lbl.set_margin_top(8)
            lbl.set_margin_bottom(8)
            lbl.set_margin_start(12)
            lbl.set_margin_end(12)
            row.set_child(lbl)
            self.menu_list.append(row)

        sidebar_scroll = Gtk.ScrolledWindow()
        sidebar_scroll.set_child(self.menu_list)
        sidebar_scroll.set_vexpand(True)
        sidebar.append(sidebar_scroll)
        sidebar.set_size_request(230, -1)

        main.set_start_child(sidebar)

        # ---- РЕДАКТОР ----
        editor_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.text_view = Gtk.TextView()
        self.text_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self.text_view.set_margin_top(12)
        self.text_view.set_margin_bottom(12)
        self.text_view.set_margin_start(12)
        self.text_view.set_margin_end(12)

        editor_scroll = Gtk.ScrolledWindow()
        editor_scroll.set_child(self.text_view)
        editor_box.append(editor_scroll)
        main.set_end_child(editor_box)

        self.current_file = None
        self.win.present()

    # ---- Обработка меню ----
    def on_menu_action(self, listbox, row):
        action = row.action_id
        if action == "new":
            self.new_note()
        elif action == "open":
            self.open_file()
        elif action == "save":
            self.save_file()
        elif action == "save_as":
            self.save_file_as()

    # ---- Действия ----
    def new_note(self):
        self.text_view.get_buffer().set_text("")
        self.current_file = None
        self.win.set_title("Right Note — Новая заметка")

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
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.text_view.get_buffer().set_text(data.get("body", ""))
            self.current_file = path
            self.win.set_title(f"Right Note — {os.path.basename(path)}")
        except Exception as e:
            print("Ошибка открытия:", e)

    def save_file(self):
        if self.current_file is None:
            self.save_file_as()
            return
        self._write_file(self.current_file)

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
        self._write_file(path)
        self.current_file = path
        self.win.set_title(f"Right Note — {os.path.basename(path)}")

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