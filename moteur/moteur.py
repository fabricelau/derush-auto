#!/usr/bin/env python3
# moteur.py - moteur d'analyse pour le panneau Premiere "Dérush Auto" (Mac et PC)
import json, subprocess, os, threading, shutil
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np, cv2

REGLAGES = dict(largeur=320, min_dur=2.0, seuil_trem=6.0, vmax=30.0,
                seuil_flou=40.0, sombre=25, crame=235, marge=0.15,
                parole_ratio=0.6, discours_min=60)

ICI = Path(__file__).resolve().parent
_VISAGES = None


def ffmpeg():
    # ffmpeg livré à côté du moteur, sinon celui du système
    for nom in ("ffmpeg.exe", "ffmpeg"):
        p = ICI / nom
        if p.exists():
            return str(p)
    if shutil.which("ffmpeg"):
        return shutil.which("ffmpeg")
    try:  # ffmpeg fourni par le paquet imageio-ffmpeg (installé par l'installateur)
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def visages():
    global _VISAGES
    if _VISAGES is None:
        _VISAGES = False
        nom = "haarcascade_frontalface_default.xml"
        candidats = [ICI / nom]
        if hasattr(cv2, "data"):
            candidats.append(Path(cv2.data.haarcascades) / nom)
        for p in candidats:
            if p.exists():
                c = cv2.CascadeClassifier(str(p))
                if not c.empty():
                    _VISAGES = c
                    break
    return _VISAGES


def compter_visages(g):
    v = visages()
    return len(v.detectMultiScale(g, 1.2, 5, minSize=(24, 24))) if v else 0


def lisser(x, n):
    n = max(1, int(n))
    return np.convolve(x, np.ones(n) / n, mode="same")


# ---------- analyse image ----------
def mouvement_camera(prev, g):
    # mouvement global de la caméra entre deux images (en pixels),
    # robuste aux gens qui bougent dans le cadre (RANSAC sur des points suivis)
    pts = cv2.goodFeaturesToTrack(prev, maxCorners=200, qualityLevel=0.01, minDistance=8)
    if pts is None or len(pts) < 8:
        return (0.0, 0.0)
    nxt, st, _ = cv2.calcOpticalFlowPyrLK(prev, g, pts, None, winSize=(21, 21), maxLevel=3)
    ok = st.ravel() == 1
    if ok.sum() < 8:
        return (0.0, 0.0)
    m, _ = cv2.estimateAffinePartial2D(pts[ok], nxt[ok], method=cv2.RANSAC, ransacReprojThreshold=2.0)
    if m is None:
        d = np.median(nxt[ok] - pts[ok], axis=0).ravel()
        return (float(d[0]), float(d[1]))
    return (float(m[0, 2]), float(m[1, 2]))


def analyser_image(path, r):
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    if fps <= 1 or fps > 300:
        fps = 25.0
    mv, flou, lum, vis = [], [], [], []
    prev = None
    i = n = 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        g = cv2.resize(g, (r["largeur"], int(g.shape[0] * r["largeur"] / g.shape[1])))
        flou.append(cv2.Laplacian(g, cv2.CV_64F).var())
        lum.append(g.mean())
        if i % 6 == 0:  # visages : une image sur 6 pour aller vite
            n = compter_visages(g)
        vis.append(n)
        mv.append((0.0, 0.0) if prev is None else mouvement_camera(prev, g))
        prev = g
        i += 1
    cap.release()
    return fps, np.array(mv, float).reshape(-1, 2), np.array(flou), np.array(lum), np.array(vis)


# ---------- analyse son ----------
def lire_audio(path, sr=16000):
    cmd = [ffmpeg(), "-v", "quiet", "-i", str(path), "-vn", "-ac", "1",
           "-ar", str(sr), "-f", "s16le", "-"]
    try:
        raw = subprocess.run(cmd, capture_output=True, check=True,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except Exception:
        return np.zeros(0, np.int16)
    return np.frombuffer(raw, np.int16)


def detecter_parole(pcm, fps, n, sr=16000):
    # pour chaque image : True si quelqu'un parle
    if len(pcm) == 0 or n == 0:
        return np.zeros(n, bool)
    import webrtcvad
    vad, fr = webrtcvad.Vad(2), 480  # trames de 30 ms
    b = pcm.tobytes()
    v = np.array([vad.is_speech(b[k * fr * 2:(k + 1) * fr * 2], sr) for k in range(len(pcm) // fr)])
    if not len(v):
        return np.zeros(n, bool)
    idx = (np.arange(n) * sr / fps / fr).astype(int).clip(0, len(v) - 1)
    return v[idx]


def moments_forts(pcm, sr=16000):
    # pics d'énergie sonore (applaudissements, rires) -> secondes
    if len(pcm) == 0:
        return []
    a = pcm.astype(np.float32) / 32768
    t = int(sr * 0.5)
    e = np.array([np.sqrt(np.mean(a[k:k + t] ** 2)) for k in range(0, len(a) - t, t)])
    if len(e) < 3:
        return []
    seuil = max(np.median(e) * 3, 0.02)
    return [round(k * 0.5, 1) for k in range(1, len(e) - 1)
            if e[k] > seuil and e[k] >= e[k - 1] and e[k] >= e[k + 1]]


# ---------- découpe d'un rush ----------
def passages(ok, fps, r):
    res, debut = [], None
    for i, v in enumerate(list(ok) + [False]):
        if v and debut is None:
            debut = i
        elif not v and debut is not None:
            a, b = debut / fps + r["marge"], i / fps - r["marge"]
            if b - a >= r["min_dur"]:
                res.append((a, b))
            debut = None
    return res


def decouper_rush(path, r=None):
    r = dict(REGLAGES, **(r or {}))
    fps, mv, flou, lum, vis = analyser_image(path, r)
    n = len(mv)
    duree = n / fps
    pcm = lire_audio(path)
    parole = detecter_parole(pcm, fps, n)
    infos = dict(fichier=str(path), fps=fps, duree=round(duree, 2), moments=moments_forts(pcm))
    if n < 2:
        infos.update(discours=False, segments=[])
        return infos

    # discours : parole continue -> rush gardé en entier
    if duree >= r["discours_min"] and parole.mean() >= r["parole_ratio"]:
        infos["discours"] = True
        infos["segments"] = [dict(entree=0.0, sortie=round(duree, 2), note=1.0,
                                  visages=round(float(vis.mean()), 2), discours=True)]
        return infos

    # tremblement = écart entre le mouvement brut et le mouvement lissé
    dx, dy = mv[:, 0], mv[:, 1]
    lx, ly = lisser(dx, fps * 0.5), lisser(dy, fps * 0.5)
    secousse = lisser(np.hypot(dx - lx, dy - ly), fps * 0.3)
    vitesse = np.hypot(lx, ly)
    nettete = lisser(flou, fps * 0.3)
    lumi = lisser(lum, fps * 0.5)

    ok = ((secousse < r["seuil_trem"]) & (vitesse < r["vmax"]) &
          (nettete > r["seuil_flou"]) & (lumi > r["sombre"]) & (lumi < r["crame"]))
    ok = lisser(ok.astype(float), fps * 0.3) > 0.5  # bouche les micro-trous

    segs = []
    for a, b in passages(ok, fps, r):
        i, j = int(a * fps), int(b * fps)
        stab = 1 / (1 + secousse[i:j].mean())
        net = min(1.0, nettete[i:j].mean() / max(r["seuil_flou"] * 4, 1))
        v = float(vis[i:j].mean())
        note = 0.5 * stab + 0.3 * net + 0.2 * min(1.0, v)
        segs.append(dict(entree=round(a, 2), sortie=round(b, 2), note=round(float(note), 3),
                         visages=round(v, 2), discours=False))
    infos["discours"] = False
    infos["segments"] = segs
    return infos


# ---------- synchro, rythme, montage ----------
def enveloppe(pcm, pas=160):
    a = np.abs(pcm[: len(pcm) // pas * pas].astype(np.float32)).reshape(-1, pas).mean(1)
    return (a - a.mean()) / (a.std() + 1e-9)  # 100 valeurs par seconde


def synchro(fa, fb, max_dec=600):
    # décalage (s) tel que temps_A = temps_B + décalage, et fiabilité 0..1
    a, b = enveloppe(lire_audio(fa)), enveloppe(lire_audio(fb))
    if len(a) < 300 or len(b) < 300:
        return 0.0, 0.0
    n = 1 << int(np.ceil(np.log2(len(a) + len(b))))
    c = np.fft.irfft(np.fft.rfft(a, n) * np.conj(np.fft.rfft(b, n)), n)
    c = np.concatenate([c[-(len(b) - 1):], c[:len(a)]])
    lags = np.arange(-(len(b) - 1), len(a))
    garde = np.abs(lags) <= max_dec * 100
    k = int(np.argmax(np.where(garde, c, -np.inf)))
    fiab = c[k] / min(len(a), len(b))
    return float(lags[k] / 100.0), float(fiab)


def temps_musique(path):
    import librosa
    y, sr = librosa.load(path, sr=22050, mono=True)
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
    return float(np.atleast_1d(tempo)[0]), librosa.frames_to_time(beats, sr=sr).tolist()


def repartir(liste, k):
    t = max(1, int(np.ceil(len(liste) / k)))
    return [liste[i * t:(i + 1) * t] for i in range(k)]


def monter(chutiers, ordre, duree, mode="film", musique=None, synchro_cam=True):
    beats = temps_musique(musique)[1] if (mode == "clip" and musique) else []
    if beats and len(beats) > 4:
        pas = float(np.median(np.diff(beats))) * 2
    else:
        pas = 5.0 if mode == "film" else 2.5

    vus, parts = {}, []
    for nom in ordre:
        k = ordre.count(nom)
        i = vus.get(nom, 0)
        vus[nom] = i + 1
        segs = [dict(s, fichier=r["fichier"], chutier=nom, rang=j)
                for j, r in enumerate(chutiers.get(nom, [])) for s in r["segments"]]
        parts.append(repartir(segs, k)[i] if segs else [])

    dispo = [sum(s["sortie"] - s["entree"] for s in p) or 1 for p in parts]
    budgets = [duree * d / sum(dispo) for d in dispo]

    clips = []
    for p, budget in zip(parts, budgets):
        choisis, total = [], 0.0
        if mode == "film":
            for s in p:
                if s["discours"]:  # discours en entier dans le film
                    choisis.append(dict(s))
                    total += s["sortie"] - s["entree"]
        autres = sorted([s for s in p if not s["discours"]], key=lambda s: -s["note"])
        for s in autres:
            if total >= budget:
                break
            long = min(pas, s["sortie"] - s["entree"])
            milieu = (s["entree"] + s["sortie"]) / 2
            choisis.append(dict(s, entree=round(milieu - long / 2, 2), sortie=round(milieu + long / 2, 2)))
            total += long
        choisis.sort(key=lambda s: (s["rang"], s["entree"]))
        clips += choisis

    if synchro_cam and mode == "film":
        for c in clips:
            if not c.get("discours"):
                continue
            for r in chutiers.get(c["chutier"], []):
                if r["fichier"] == c["fichier"] or r["duree"] < 30:
                    continue
                dec, fiab = synchro(c["fichier"], r["fichier"])
                if fiab > 0.3:
                    c["camera_b"] = dict(fichier=r["fichier"], decalage=dec)
                    break

    if beats:  # caler les coupes du clip sur les temps de la musique
        t, b = 0.0, 0
        for c in clips:
            long = c["sortie"] - c["entree"]
            cible = t + long
            while b < len(beats) - 1 and beats[b] < cible:
                b += 1
            vrai = max(0.5, beats[b] - t)
            c["sortie"] = round(c["entree"] + min(vrai, long + 0.5), 3)
            t += c["sortie"] - c["entree"]
    return clips


# ---------- serveur local pour le panneau ----------
ETAT = dict(en_cours=False, fait=0, total=0, resultat=None, erreur=None)


def cache_ou_analyse(f, r):
    p = Path(f)
    cache = p.with_suffix(p.suffix + ".derush.json")
    try:
        if cache.exists() and cache.stat().st_mtime >= p.stat().st_mtime:
            ancien = json.loads(cache.read_text(encoding="utf-8"))
            if ancien.get("reglages") == r:
                return ancien
    except Exception:
        pass
    res = decouper_rush(p, r)
    res["reglages"] = r
    try:
        cache.write_text(json.dumps(res), encoding="utf-8")
    except OSError:
        pass
    return res


def lancer_analyse(chutiers, reglages):
    r = dict(REGLAGES, **(reglages or {}))
    fichiers = list(dict.fromkeys(f for l in chutiers.values() for f in l))
    ETAT.update(en_cours=True, fait=0, total=len(fichiers), resultat=None, erreur=None)
    res = {}
    try:
        with ProcessPoolExecutor(max_workers=max(1, (os.cpu_count() or 2) - 1)) as ex:
            futs = {ex.submit(cache_ou_analyse, f, r): f for f in fichiers}
            for fu in as_completed(futs):
                res[futs[fu]] = fu.result()
                ETAT["fait"] += 1
        ETAT["resultat"] = {nom: [res[f] for f in l] for nom, l in chutiers.items()}
    except Exception as e:
        ETAT["erreur"] = str(e)
    ETAT["en_cours"] = False


class Serveur(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _rep(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(b)

    def do_OPTIONS(self):
        self._rep(200, {})

    def do_GET(self):
        self._rep(200, ETAT if self.path == "/etat" else {"ok": True})

    def do_POST(self):
        d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0) or 0)) or b"{}")
        try:
            if self.path == "/analyser":
                if ETAT["en_cours"]:
                    return self._rep(409, {"erreur": "analyse déjà en cours"})
                threading.Thread(target=lancer_analyse,
                                 args=(d["chutiers"], d.get("reglages")), daemon=True).start()
                return self._rep(200, {"lance": True})
            if self.path == "/monter":
                if not ETAT["resultat"]:
                    return self._rep(400, {"erreur": "lance d'abord l'analyse"})
                clips = monter(ETAT["resultat"], d["ordre"], float(d["duree"]),
                               d.get("mode", "film"), d.get("musique"), d.get("synchro", True))
                return self._rep(200, {"clips": clips})
            self._rep(404, {"erreur": "inconnu"})
        except Exception as e:
            self._rep(500, {"erreur": str(e)})


if __name__ == "__main__":
    import sys
    try:
        serveur = HTTPServer(("127.0.0.1", 8765), Serveur)
    except OSError:
        sys.exit(0)  # déjà lancé
    try:
        import mise_a_jour
        ETAT["version"] = mise_a_jour.version_locale()
        mise_a_jour.demarrer(ETAT, serveur)
    except Exception as e:
        ETAT["mise_a_jour_erreur"] = str(e)
    if sys.stdout:
        print(f"Moteur Derush Auto {ETAT.get('version', '')} pret sur http://localhost:8765")
    serveur.serve_forever()
