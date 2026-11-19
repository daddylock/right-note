import gi
import json
import os
import datetime

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, GLib

NOTES_DIR = os.path.expanduser("~/RightNote")
CONFIG_DIR = os.path.expanduser("~/.local/share/right-note")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")


class RightNoteApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id='com.daniil.rightnote')
        self.connect('activate', self.on_activate)
        os.makedirs(NOTES_DIR, exist_ok=True)
        os.makedirs(CONFIG_DIR, exist_ok=True)
        self._setup_actions()

    def _setup_actions(self):
        actions = [
            ("new",      self.new_note,      ["<Control>n"]),
            ("open",     self.open_file,     ["<Control>o"]),
            ("save_as",  self.save_file_as,  ["<Control><Shift>s"]),
            ("quit",     self.quit_app,      ["<Control>q"]),
        ]
        for name, handler, accels in actions:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda *_, h=handler: h())
            self.add_action(action)
            self.set_accels_for_action(f"app.{name}", accels)

    def quit_app(self):
        if self.win:
            self.win.close()
        else:
            self.quit()

    def on_activate(self, app):
        self.win = Adw.ApplicationWindow(application=app)
        self.win.set_default_size(550, 400)
        self.win.connect("close-request", self.on_close)
        self.dirty = False
        self.current_file = None

        # ---- HeaderBar ----
        header = Adw.HeaderBar()
        self.save_label = Gtk.Label(label="")
        self.save_label.add_css_class("dim-label")
        header.pack_end(self.save_label)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)

        # ---- Paned (разделитель двигается!) ----
        main = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        main.set_position(160)
        main.set_resize_start_child(False)   # сайдбар не растёт сам
        main.set_shrink_start_child(True)    # но может сжиматься
        main.set_vexpand(True)
        toolbar_view.set_content(main)
        self.win.set_content(toolbar_view)

        # ---- Сайдбар ----
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sidebar.set_size_request(160, -1)

        # Меню сверху
        menu_list = Gtk.ListBox()
        menu_list.add_css_class("navigation-sidebar")
        menu_list.set_selection_mode(Gtk.SelectionMode.NONE)
        menu_list.connect("row-activated", self.on_menu_action)

        for aid, label, shortcut in [
            ("new",     "📄 Новая",              "<Control>n"),
            ("open",    "📂 Открыть",            "<Control>o"),
            ("save_as", "💾 Сохранить как…",     "<Control><Shift>s"),
        ]:
            menu_list.append(self._make_menu_row(aid, label, shortcut))

        sidebar.append(menu_list)

        # Разделитель
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(6)
        sep.set_margin_bottom(6)
        sidebar.append(sep)

        # Заголовок «Заметки»
        notes_header = Gtk.Label(label="ЗАМЕТКИ", xalign=0)
        notes_header.add_css_class("dim-label")
        notes_header.add_css_class("caption")
        notes_header.set_margin_start(12)
        notes_header.set_margin_bottom(4)
        sidebar.append(notes_header)

        # Список заметок
        self.notes_list = Gtk.ListBox()
        self.notes_list.add_css_class("navigation-sidebar")
        self.notes_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.notes_list.connect("row-selected", self.on_note_selected)

        notes_scroll = Gtk.ScrolledWindow()
        notes_scroll.set_child(self.notes_list)
        notes_scroll.set_vexpand(True)
        sidebar.append(notes_scroll)

        main.set_start_child(sidebar)

        # ---- Редактор (теперь растягивается!) ----
        editor_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        editor_box.set_hexpand(True)
        editor_box.set_vexpand(True)

        self.text_view = Gtk.TextView()
        self.text_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self.text_view.set_margin_top(10)
        self.text_view.set_margin_bottom(10)
        self.text_view.set_margin_start(10)
        self.text_view.set_margin_end(10)
        self.text_view.get_buffer().connect("changed", self.on_text_changed)

        editor_scroll = Gtk.ScrolledWindow()
        editor_scroll.set_child(self.text_view)
        editor_scroll.set_vexpand(True)   # ← ГЛАВНЫЙ ФИКС
        editor_scroll.set_hexpand(True)
        editor_box.append(editor_scroll)
        main.set_end_child(editor_box)

        GLib.timeout_add_seconds(2, self.auto_save)
        self.refresh_notes_list()

        # Открываем последнюю или создаём новую
        last = self._load_config().get("last_file")
        if last and os.path.exists(last):
            self.load_file(last)
        else:
            notes = self._list_notes()
            if notes:
                self.load_file(notes[0])
            else:
                self.new_note()

        self.win.present()

    # ---------- Вспомогательные ----------
    def _make_menu_row(self, action_id, label, shortcut):
        row = Gtk.ListBoxRow()
        row.action_id = action_id
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lbl = Gtk.Label(label=label, xalign=0)
        lbl.set_hexpand(True)
        box.append(lbl)
        if shortcut:
            sl = Gtk.ShortcutLabel.new(shortcut)
            sl.add_css_class("dim-label")
            box.append(sl)
        box.set_margin_top(6); box.set_margin_bottom(6)
        box.set_margin_start(10); box.set_margin_end(10)
        row.set_child(box)
        row.set_tooltip_text(label.replace("\n", " "))
        return row

    def _list_notes(self):
        if not os.path.isdir(NOTES_DIR):
            return []
        files = [os.path.join(NOTES_DIR, f) for f in os.listdir(NOTES_DIR)
                 if f.endswith(".rnote")]
        files.sort(key=os.path.getmtime, reverse=True)
        return files

    def refresh_notes_list(self):
        child = self.notes_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.notes_list.remove(child)
            child = nxt
        for path in self._list_notes():
            row = Gtk.ListBoxRow()
            row.file_path = path
            name = os.path.splitext(os.path.basename(path))[0]
            lbl = Gtk.Label(label=f"📄 {name}", xalign=0)
            lbl.set_ellipsize(3)  # Pango.EllipsizeMode.END
            lbl.set_margin_top(6); lbl.set_margin_bottom(6)
            lbl.set_margin_start(10); lbl.set_margin_end(10)
            row.set_child(lbl)
            self.notes_list.append(row)
        # Выделяем текущую
        if self.current_file:
            child = self.notes_list.get_first_child()
            while child:
                if getattr(child, "file_path", None) == self.current_file:
                    self.notes_list.select_row(child)
                    break
                child = child.get_next_sibling()

    # ---------- Обработчики ----------
    def on_menu_action(self, listbox, row):
        if row is None:
            return
        {"new": self.new_note,
         "open": self.open_file,
         "save_as": self.save_file_as}[row.action_id]()

    def on_note_selected(self, listbox, row):
        if row is None or not hasattr(row, "file_path"):
            return
        if row.file_path == self.current_file:
            return
        if self.dirty and self.current_file:
            self._write_file(self.current_file)
        self.load_file(row.file_path)

    def on_text_changed(self, buf):
        self.dirty = True
        self.save_label.set_text("● Не сохранено")
        self.save_label.remove_css_class("success")

    def auto_save(self):
        if self.dirty and self.current_file:
            self._write_file(self.current_file)
            self.dirty = False
            self.save_label.set_text("✓ Сохранено")
            self.save_label.add_css_class("success")
            self.refresh_notes_list()
        return True

    def on_close(self, window):
        if self.dirty and self.current_file:
            self._write_file(self.current_file)
        if self.current_file:
            self._save_config({"last_file": self.current_file})
        return False

    # ---------- Действия ----------
    def new_note(self):
        if self.dirty and self.current_file:
            self._write_file(self.current_file)
        name = datetime.datetime.now().strftime("Заметка %Y-%m-%d %H-%M-%S")
        path = os.path.join(NOTES_DIR, f"{name}.rnote")
        counter = 1
        while os.path.exists(path):
            path = os.path.join(NOTES_DIR, f"{name} ({counter}).rnote")
            counter += 1
        self.current_file = path
        self.text_view.get_buffer().set_text("")
        self._write_file(path)
        self.dirty = False
        self.update_title()
        self.refresh_notes_list()
        self.save_label.set_text("✓ Сохранено")
        self.save_label.add_css_class("success")
        self.text_view.grab_focus()

    def load_file(self, path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.text_view.get_buffer().set_text(data.get("body", ""))
            self.current_file = path
            self.dirty = False
            self.update_title()
            self.save_label.set_text("✓ Сохранено")
            self.save_label.add_css_class("success")
            self.refresh_notes_list()
        except Exception as e:
            print("Ошибка загрузки:", e)

    def update_title(self):
        if self.current_file:
            name = os.path.splitext(os.path.basename(self.current_file))[0]
            self.win.set_title(f"Right Note — {name}")
        else:
            self.win.set_title("Right Note")

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
        self.refresh_notes_list()

    # ---------- Запись / конфиг ----------
    def _write_file(self, path):
        buf = self.text_view.get_buffer()
        body = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
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
    RightNoteApp().run(None)