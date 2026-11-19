import os
os.environ["GTK_THEME"] = "Adwaita"

import gi
import json
import datetime

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, GLib, Gdk

NOTES_DIR = os.path.expanduser("~/RightNote")
CONFIG_DIR = os.path.expanduser("~/.local/share/right-note")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# --- ОБНОВЛЕННЫЙ CSS ДЛЯ КРАСОТЫ ---
CUSTOM_CSS = """
window {
    background-color: @theme_bg_color;
}

/* Сайдбар теперь как карточка */
.sidebar-box {
    background-color: alpha(@theme_fg_color, 0.03);
    margin: 8px 4px 8px 8px;
    border-radius: 12px;
    border: 1px solid alpha(@theme_fg_color, 0.08);
}

/* Кнопки в сайдбаре */
.sidebar-btn {
    background: transparent;
    border: none;
    border-radius: 6px;
    margin: 2px;
}
.sidebar-btn:hover {
    background: alpha(@theme_fg_color, 0.1);
}

/* Строки в списке заметок */
.note-row {
    padding: 8px 12px;
    margin: 2px 6px;
    border-radius: 8px;
}
.note-row:selected {
    background-color: alpha(@theme_selected_bg_color, 0.9);
    color: @theme_selected_fg_color;
}

/* Контейнер редактора (отступы от краев) */
.editor-container {
    padding: 8px 8px 8px 0;
}

/* Само поле ввода (как карточка) */
.note-text {
    font-size: 15px;
    font-family: "Cantarell", "Inter", sans-serif;
    padding: 24px;
    border-radius: 12px;
    border: 1px solid alpha(@theme_fg_color, 0.08);
    background-color: @theme_base_color;
}

/* Разделитель (почти невидимый) */
paned > separator {
    min-width: 2px;
    background-color: transparent;
}

@media (prefers-color-scheme: dark) {
    .note-text {
        background-color: #1e1e1e;
        color: #e0e0e0;
    }
    window {
        background-color: #121212;
    }
}

@media (prefers-color-scheme: light) {
    .note-text {
        background-color: #ffffff;
        color: #1e1e1e;
    }
    window {
        background-color: #f5f5f5;
    }
}
"""

def load_css():
    provider = Gtk.CssProvider()
    provider.load_from_data(CUSTOM_CSS.encode('utf-8'))
    display = Gdk.Display.get_default()
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )

class RightNoteApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id='com.daniil.rightnote')
        self.connect('activate', self.on_activate)
        os.makedirs(NOTES_DIR, exist_ok=True)
        os.makedirs(CONFIG_DIR, exist_ok=True)
        self._setup_actions()
        
        self.dirty = False
        self.is_loading = False
        self.current_file = None
        self.pending_select = None  # Для переключения после удаления

    def _setup_actions(self):
        actions = [
            ("new",      self.new_note,      ["<Control>n"]),
            ("open",     self.open_file,     ["<Control>o"]),
            ("save_as",  self.save_file_as,  ["<Control><Shift>s"]),
            ("delete",   self.delete_note,   ["<Control>Delete"]),
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
        load_css()

        self.win = Adw.ApplicationWindow(application=app)
        self.win.set_default_size(650, 500)
        self.win.connect("close-request", self.on_close)

        header = Adw.HeaderBar()
        self.save_label = Gtk.Label(label="Сохранено")
        self.save_label.add_css_class("dim-label")
        header.pack_end(self.save_label)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)

        main = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        main.set_position(220)
        main.set_resize_start_child(False)
        main.set_wide_handle(True)
        main.set_vexpand(True)
        main.set_hexpand(True)
        toolbar_view.set_content(main)
        self.win.set_content(toolbar_view)

        # ---- САЙДБАР ----
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sidebar.add_css_class("sidebar-box")
        sidebar.set_size_request(160, -1)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_box.set_margin_top(8)
        btn_box.set_margin_bottom(8)
        btn_box.set_margin_start(8)
        btn_box.set_margin_end(8)

        btn_new = Gtk.Button(icon_name="document-new-symbolic")
        btn_new.set_tooltip_text("Новая заметка (Ctrl+N)")
        btn_new.add_css_class("sidebar-btn")
        btn_new.connect("clicked", lambda _: self.new_note())
        
        btn_open = Gtk.Button(icon_name="document-open-symbolic")
        btn_open.set_tooltip_text("Открыть заметку (Ctrl+O)")
        btn_open.add_css_class("sidebar-btn")
        btn_open.connect("clicked", lambda _: self.open_file())
        
        btn_save = Gtk.Button(icon_name="document-save-as-symbolic")
        btn_save.set_tooltip_text("Сохранить как... (Ctrl+Shift+S)")
        btn_save.add_css_class("sidebar-btn")
        btn_save.connect("clicked", lambda _: self.save_file_as())

        btn_del = Gtk.Button(icon_name="user-trash-symbolic")
        btn_del.set_tooltip_text("Удалить заметку (Ctrl+Delete)")
        btn_del.add_css_class("sidebar-btn")
        btn_del.connect("clicked", lambda _: self.delete_note())

        btn_box.append(btn_new)
        btn_box.append(btn_open)
        btn_box.append(btn_save)
        btn_box.append(btn_del)
        sidebar.append(btn_box)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(4)
        sep.set_margin_bottom(4)
        sidebar.append(sep)

        # ---- ДЕРЕВО ----
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

        main.set_start_child(sidebar)

        # ---- РЕДАКТОР ----
        editor_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        editor_container.add_css_class("editor-container")
        editor_container.set_hexpand(True)
        editor_container.set_vexpand(True)

        self.text_view = Gtk.TextView()
        self.text_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self.text_view.add_css_class("note-text") # Класс для красоты
        self.text_view.get_buffer().connect("changed", self.on_text_changed)

        editor_scroll = Gtk.ScrolledWindow()
        editor_scroll.set_child(self.text_view)
        editor_scroll.set_vexpand(True)
        editor_scroll.set_hexpand(True)
        editor_container.append(editor_scroll)
        main.set_end_child(editor_container)

        self.monitor = self.notes_dir.monitor_directory(Gio.FileMonitorFlags.NONE, None)
        self.monitor.connect("changed", self._on_dir_changed)

        GLib.timeout_add_seconds(2, self.auto_save)

        last = self._load_config().get("last_file")
        if last and os.path.exists(last):
            self.load_file(last)
        else:
            self.new_note()

        self.win.present()

    # ---------- Логика именования ----------
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

    # ---------- Дерево ----------
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
            
            # Если мы удалили заметку, переключаемся на следующую
            if self.pending_select is not None:
                idx = self.pending_select
                self.pending_select = None
                if idx >= 0 and idx < self.notes_store.get_n_items():
                    def select_pending():
                        self.is_loading = True
                        self.selection_model.set_selected(idx)
                        self.is_loading = False
                        # Загружаем принудительно, если смена выделения не сработала
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
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.add_css_class("note-row")
        expander = Gtk.TreeExpander()
        image = Gtk.Image()
        label = Gtk.Label(xalign=0)
        label.set_ellipsize(3)
        box.append(expander)
        box.append(image)
        box.append(label)
        
        gesture = Gtk.GestureClick()
        gesture.connect("pressed", self._on_item_pressed, list_item)
        box.add_controller(gesture)
        
        list_item.set_child(box)

    def _bind_tree_item(self, factory, list_item):
        box = list_item.get_child()
        expander = box.get_first_child()
        image = expander.get_next_sibling()
        label = image.get_next_sibling()
        
        tree_row = list_item.get_item()
        file = tree_row.get_item()
        
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

    # ---------- Действия ----------
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

    def auto_save(self):
        if not self.is_loading:
            self._save_current()
        return True

    def on_close(self, window):
        if not self.is_loading:
            self._save_current()
        if self.current_file:
            self._save_config({"last_file": self.current_file})
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
        
        # Определяем, какую заметку выделить после удаления
        if n_items > 1:
            # Если удаляем последнюю в списке, выделяем предыдущую
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
        
        # Если удалили всё, создаем новую
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
    RightNoteApp().run(None)