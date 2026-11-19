#!/bin/bash

# Абсолютный путь к папке проекта (замени, если папка называется иначе)
APP_DIR="$HOME/projects/right-note"
PYTHON_BIN="$APP_DIR/venv/bin/python3"
MAIN_PY="$APP_DIR/main.py"

echo "Установка MIME-типа для .rnote..."

# 1. Создаем MIME-тип
mkdir -p ~/.local/share/mime/packages
cat > ~/.local/share/mime/packages/right-note.xml << EOF
<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
    <mime-type type="application/x-right-note">
        <comment>Right Note Document</comment>
        <glob pattern="*.rnote"/>
    </mime-type>
</mime-info>
EOF

update-mime-database ~/.local/share/mime/

# 2. Создаем .desktop файл
mkdir -p ~/.local/share/applications
cat > ~/.local/share/applications/right-note.desktop << EOF
[Desktop Entry]
Name=Right Note
Comment=Comfortable notes with Markdown
Exec=$PYTHON_BIN $MAIN_PY %f
Icon=accessories-text-editor
Terminal=false
Type=Application
Categories=Utility;TextEditor;
MimeType=application/x-right-note;
StartupNotify=true
EOF

# 3. Устанавливаем ассоциацию по умолчанию
xdg-mime default right-note.desktop application/x-right-note
update-desktop-database ~/.local/share/applications/

echo "✅ Готово! Теперь файлы .rnote открываются в Right Note."
