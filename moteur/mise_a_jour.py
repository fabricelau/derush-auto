# mise_a_jour.py - mise à jour automatique de Derush Auto depuis GitHub
import io, json, os, shutil, ssl, subprocess, sys, tempfile, threading, time, zipfile
import urllib.request
from pathlib import Path

DEPOT = "fabricelau/derush-auto"
BRANCHE = "main"
URL_VERSION = f"https://raw.githubusercontent.com/{DEPOT}/{BRANCHE}/version.json"
URL_ZIP = f"https://github.com/{DEPOT}/archive/refs/heads/{BRANCHE}.zip"
INTERVALLE = 6 * 3600  # vérifie toutes les 6 heures

ICI = Path(__file__).resolve().parent


def dossier_extensions():
    if sys.platform == "win32":
        return Path(os.environ["APPDATA"]) / "Adobe" / "CEP" / "extensions"
    return Path.home() / "Library" / "Application Support" / "Adobe" / "CEP" / "extensions"


def version_locale():
    try:
        return json.loads((ICI / "version.json").read_text(encoding="utf-8"))["version"]
    except Exception:
        return "0"


def comparer(a, b):
    pa = [int(x) for x in str(a).split(".") if x.isdigit()]
    pb = [int(x) for x in str(b).split(".") if x.isdigit()]
    return (pa > pb) - (pa < pb)


def telecharger(url):
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "DerushAuto", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
        return r.read()


def installer(etat):
    distante = json.loads(telecharger(URL_VERSION + f"?t={int(time.time())}"))
    nouvelle = distante["version"]
    if comparer(nouvelle, version_locale()) <= 0:
        return False
    etat["mise_a_jour"] = f"Téléchargement de la version {nouvelle}…"
    archive = zipfile.ZipFile(io.BytesIO(telecharger(URL_ZIP)))
    with tempfile.TemporaryDirectory() as tmp:
        archive.extractall(tmp)
        racine = next(Path(tmp).iterdir())  # derush-auto-main/
        src_moteur = racine / "moteur"
        src_ext = racine / "extension" / "DerushAuto"

        # nouveaux outils Python éventuels
        anciens = (ICI / "requirements.txt").read_text() if (ICI / "requirements.txt").exists() else ""
        nouveaux = (src_moteur / "requirements.txt").read_text()
        if nouveaux != anciens:
            py = sys.executable.replace("pythonw.exe", "python.exe")
            subprocess.run([py, "-m", "pip", "install", "--user", "--upgrade", "-q",
                            "-r", str(src_moteur / "requirements.txt")],
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

        # panneau Premiere
        cible_ext = dossier_extensions() / "DerushAuto"
        if src_ext.exists():
            cible_ext.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src_ext, cible_ext, dirs_exist_ok=True)

        # moteur (version.json en dernier)
        for f in src_moteur.iterdir():
            if f.is_file() and f.name != "version.json":
                shutil.copy2(f, ICI / f.name)
        shutil.copy2(racine / "version.json", ICI / "version.json")
    etat["mise_a_jour"] = f"Version {nouvelle} installée : redémarre Premiere pour en profiter."
    return True


def redemarrer():
    # relance le moteur avec le nouveau code
    args = [sys.executable, str(ICI / "moteur.py")]
    if sys.platform == "win32":
        subprocess.Popen(args, creationflags=0x00000008 | 0x00000200)  # détaché
        os._exit(0)
    os.execv(sys.executable, args)


REVEIL = threading.Event()


def verifier_maintenant():
    REVEIL.set()


def boucle(etat, serveur):
    REVEIL.wait(20)  # laisse l'ordinateur finir de démarrer
    while True:
        REVEIL.clear()
        try:
            if not etat.get("en_cours") and installer(etat):
                time.sleep(3)
                while etat.get("en_cours"):  # jamais pendant une analyse
                    time.sleep(10)
                serveur.server_close()
                redemarrer()
        except Exception as e:
            etat["mise_a_jour_erreur"] = str(e)
        REVEIL.wait(INTERVALLE)  # ou plus tôt si le panneau le demande


def demarrer(etat, serveur):
    threading.Thread(target=boucle, args=(etat, serveur), daemon=True).start()
