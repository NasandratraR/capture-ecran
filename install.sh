#!/bin/sh
# Installe (ou met à jour) Capture d'écran pour l'utilisateur courant.
set -e
cd "$(dirname "$0")"
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications"
install -m 755 capture.py "$HOME/.local/bin/capture-ecran"
sed "s|@HOME@|$HOME|g" capture-ecran.desktop.in > "$HOME/.local/share/applications/capture-ecran.desktop"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
echo "Installé : $HOME/.local/bin/capture-ecran"
