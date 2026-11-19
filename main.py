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
        self.win.set_default_size(600, 450)
        self.win.connect("close-request", self.on_close)
        self.dirty = False
        self.current_file = None

        # ---- HeaderBar ----
        header = Adw.HeaderBar()
        self.save_label = Gtk.Label(label="Сохранено")
        self.save_label.add_css_class("dim-label")
        header.pack_end(self.save_label)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)

        # ---- Paned (разделитель) ----
        main = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        main.set_position(200)
        main.set_resize_start_child(False)
        main.set_vexpand(True)
        main.set_hexpand(True)
        toolbar_view.set_content(main)
        self.win.set_content(toolbar_view)

        # ---- САЙДБАР ----
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sidebar.set_size_request(160, -1)

        # Кнопки
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_box.set_margin_top(6)
        btn_box.set_margin_bottom(6)
        btn_box.set_margin_start(6)
        btn_box.set_margin_end(6)

        btn_new = Gtk.Button(icon_name="document-new-symbolic")
        btn_new.set_tooltip_text("Новая заметка (Ctrl+N)")
        btn_new.connect("clicked", lambda _: self.new_note())
        
        btn_open = Gtk.Button(icon_name="document-open-symbolic")
        btn_open.set_tooltip_text("Открыть заметку (Ctrl+O)")
        btn_open.connect("clicked", lambda _: self.open_file())
        
        btn_save = Gtk.Button(icon_name="document-save-as-symbolic")
        btn_save.set_tooltip_text("Сохранить как... (Ctrl+Shift+S)")
        btn_save.connect("clicked", lambda _: self.save_file_as())

        btn_box.append(btn_new)
        btn_box.append(btn_open)
        btn_box.append(btn_save)
        sidebar.append(btn_box)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sidebar.append(sep)

        # ---- ДЕРЕВО ЗАМЕТОК ----
        self.notes_dir = Gio.File.new_for_path(NOTES_DIR)
        
        # Создаем хранилище файлов
        self.notes_store = self._load_dir(self.notes_dir)
        
        # Дерево
        self.tree_model = Gtk.TreeListModel.new(self.notes_store, False, False, self._create_child_model)
        self.selection_model = Gtk.SingleSelection.new(self.tree_model)
        
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._setup_tree_item)
        factory.connect("bind", self._bind_tree_item)
        
        self.list_view = Gtk.ListView.new(self.selection_model, factory)
        self.list_view.connect("activate", self.on_tree_item_activated)
        
        notes_scroll = Gtk.ScrolledWindow()
        notes_scroll.set_child(self.list_view)
        notes_scroll.set_vexpand(True)
        sidebar.append(notes_scroll)

        main.set_start_child(sidebar)

        # ---- РЕДАКТОР ----
        editor_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        editor_box.set_hexpand(True)
        editor_box.set_vexpand(True)

        self.text_view = Gtk.TextView()
        self.text_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self.text_view.set_margin_top(12)
        self.text_view.set_margin_bottom(12)
        self.text_view.set_margin_start(12)
        self.text_view.set_margin_end(12)
        self.text_view.get_buffer().connect("changed", self.on_text_changed)

        editor_scroll = Gtk.ScrolledWindow()
        editor_scroll.set_child(self.text_view)
        editor_scroll.set_vexpand(True)
        editor_scroll.set_hexpand(True)
        editor_box.append(editor_scroll)
        main.set_end_child(editor_box)

        # Мониторинг папки (чтобы дерево обновлялось само)
        self.monitor = self.notes_dir.monitor_directory(Gio.FileMonitorFlags.NONE, None)
        self.monitor.connect("changed", self._on_dir_changed)

        GLib.timeout_add_seconds(2, self.auto_save)

        last = self._load_config().get("last_file")
        if last and os.path.exists(last):
            self.load_file(last)
        else:
            self.new_note()

        self.win.present()

    # ---------- Логика дерева ----------
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
        except Exception as e:
            print("Ошибка чтения папки:", e)
        return store

    def _create_child_model(self, file):
        if file.query_file_type(Gio.FileQueryInfoFlags.NONE, None) == Gio.FileType.DIRECTORY:
            return self._load_dir(file)
        return None

    def _on_dir_changed(self, monitor, file, other_file, event_type):
        if event_type in (Gio.FileMonitorEvent.CREATED, Gio.FileMonitorEvent.DELETED):
            new_store = self._load_dir(self.notes_dir)
            self.notes_store.remove_all()
            for f in new_store:
                self.notes_store.append(f)

    def _setup_tree_item(self, factory, list_item):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        expander = Gtk.TreeExpander()
        image = Gtk.Image()
        label = Gtk.Label(xalign=0)
        label.set_ellipsize(3)
        box.append(expander)
        box.append(image)
        box.append(label)
        list_item.set_child(box)

    def _bind_tree_item(self, factory, list_item):
        box = list_item.get_child()
        expander = box.get_first_child()
        image = expander.get_next_sibling()
        label = image.get_next_sibling()
        
        tree_row = list_item.get_item()
        file = tree_row.get_item() # Это Gio.File
        
        expander.set_list_row(tree_row)
        
        if file.query_file_type(Gio.FileQueryInfoFlags.NONE, None) == Gio.FileType.DIRECTORY:
            expander.set_hide_expander(False)
            image.set_from_icon_name("folder-symbolic")
            label.set_text(file.get_basename())
        else:
            expander.set_hide_expander(True)
            image.set_from_icon_name("text-x-generic-symbolic")
            name = file.get_basename()
            if name.endswith(".rnote"):
                name = name[:-6]
            label.set_text(name)

    def on_tree_item_activated(self, list_view, position):
        model = list_view.get_model()
        tree_row = model.get_item(position)
        file = tree_row.get_item()
        if file.query_file_type(Gio.FileQueryInfoFlags.NONE, None) == Gio.FileType.REGULAR:
            self.load_file(file.get_path())

    # ---------- Обработчики ----------
    def on_text_changed(self, buf):
        self.dirty = True
        self.save_label.set_text("● Не сохранено")
        self.save_label.remove_css_class("dim-label")

    def auto_save(self):
        if self.dirty and self.current_file:
            self._write_file(self.current_file)
            self.dirty = False
            self.save_label.set_text("Сохранено ✓")
            self.save_label.add_css_class("dim-label")
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
        self.save_label.set_text("Сохранено ✓")
        self.text_view.grab_focus()

    def load_file(self, path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.text_view.get_buffer().set_text(data.get("body", ""))
            self.current_file = path
            self.dirty = False
            self.update_title()
            self.save_label.set_text("Сохранено ✓")
            self.save_label.add_css_class("dim-label")
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