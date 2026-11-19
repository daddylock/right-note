import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw


class RightNoteApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id='com.daniil.rightnote')
        self.connect('activate', self.on_activate)

    def on_activate(self, app):
        win = Adw.ApplicationWindow(application=app)
        win.set_title("Right Note")
        win.set_default_size(700, 500)

        # Текстовое поле
        text_view = Gtk.TextView()
        text_view.set_wrap_mode(Gtk.WrapMode.WORD)
        text_view.set_margin_top(12)
        text_view.set_margin_bottom(12)
        text_view.set_margin_start(12)
        text_view.set_margin_end(12)

        # Обёртка для скролла
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_child(text_view)

        win.set_content(scrolled)
        win.present()


if __name__ == "__main__":
    app = RightNoteApp()
    app.run(None)