#!/bin/bash
cd "$(dirname "$0")"
echo ""
echo " ==== Installation de Derush Auto (Mac) ===="
echo ""

PY=""
for c in /Library/Frameworks/Python.framework/Versions/Current/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  if [ -x "$c" ] && "$c" -c "import sys" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo " Python n'est pas installe. Je t'ouvre la page de telechargement :"
  echo " installe Python, puis relance Installer-Mac.command."
  open "https://www.python.org/downloads/macos/"
  read -p " Appuie sur Entree pour fermer..."
  exit 1
fi

DEST="$HOME/Library/Application Support/DerushAuto"
EXT="$HOME/Library/Application Support/Adobe/CEP/extensions"

echo " [1/4] Copie du moteur..."
mkdir -p "$DEST"
cp -R moteur/. "$DEST/"
cp version.json "$DEST/version.json"

echo " [2/4] Installation des outils d'analyse (quelques minutes)..."
"$PY" -m pip install --user --upgrade -q -r "$DEST/requirements.txt" 2>/dev/null \
  || "$PY" -m pip install --user --upgrade -q --break-system-packages -r "$DEST/requirements.txt" \
  || { echo " Echec de l'installation des outils. Verifie ta connexion et relance."; read -p " Entree pour fermer..."; exit 1; }

echo " [3/4] Installation du panneau dans Premiere..."
mkdir -p "$EXT"
rm -rf "$EXT/DerushAuto"
cp -R extension/DerushAuto "$EXT/"
xattr -dr com.apple.quarantine "$EXT/DerushAuto" "$DEST" 2>/dev/null
for v in 9 10 11 12 13; do defaults write com.adobe.CSXS.$v PlayerDebugMode 1; done

echo " [4/4] Demarrage automatique du moteur..."
PL="$HOME/Library/LaunchAgents/com.fabrice.derushauto.plist"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PL" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.fabrice.derushauto</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>$DEST/moteur.py</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardErrorPath</key><string>$DEST/moteur.log</string>
</dict></plist>
PLIST
launchctl unload "$PL" 2>/dev/null
launchctl load "$PL"

echo ""
echo " ==== C'est installe ! ===="
echo " 1. Redemarre Premiere Pro."
echo " 2. Menu Fenetre > Extensions > Derush Auto."
echo " Le moteur demarre tout seul a chaque allumage du Mac"
echo " et se met a jour automatiquement."
echo ""
read -p " Appuie sur Entree pour fermer..."
