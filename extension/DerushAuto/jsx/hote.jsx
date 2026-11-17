// hote.jsx - partie du panneau Derush Auto qui agit dans Premiere Pro
var INDEX = {};

function esc(s) { return String(s).replace(/\\/g, "\\\\").replace(/"/g, '\\"'); }

function nomFichier(p) { return String(p).replace(/^.*[\\\/]/, "").toLowerCase(); }

function indexer(dossier, liste) {
  for (var i = 0; i < dossier.children.numItems; i++) {
    var c = dossier.children[i];
    if (c.type === ProjectItemType.BIN) { indexer(c, liste); }
    else if (c.type === ProjectItemType.CLIP) {
      var p = c.getMediaPath();
      if (p && /\.(mp4|mov|mxf|mts|m2ts|m4v|avi|mkv|braw|r3d)$/i.test(p)) { INDEX[p] = c; liste.push(p); }
    }
  }
}

function aDesRushsDirects(b) {
  for (var i = 0; i < b.children.numItems; i++)
    if (b.children[i].type === ProjectItemType.CLIP) return true;
  return false;
}

function aDesSousChutiers(b) {
  for (var i = 0; i < b.children.numItems; i++)
    if (b.children[i].type === ProjectItemType.BIN) return true;
  return false;
}

// un chutier qui ne contient que des sous-chutiers (ex. "Rushs") est un simple
// dossier de rangement : ce sont ses sous-chutiers qui deviennent les parties du film
function ajouterChutier(b, morceaux) {
  if (b.name === "Derush Auto") return;
  if (!aDesRushsDirects(b) && aDesSousChutiers(b)) {
    for (var i = 0; i < b.children.numItems; i++)
      if (b.children[i].type === ProjectItemType.BIN) ajouterChutier(b.children[i], morceaux);
    return;
  }
  var l = [];
  indexer(b, l);
  if (!l.length) return;
  l.sort(function (a, c) { return nomFichier(a) < nomFichier(c) ? -1 : 1; }); // ordre de tournage
  var q = [];
  for (var j = 0; j < l.length; j++) q.push('"' + esc(l[j]) + '"');
  morceaux.push('"' + esc(b.name) + '":[' + q.join(",") + "]");
}

// renvoie {"chutier": ["chemin1", ...], ...}
function listerChutiers() {
  try {
    INDEX = {};
    var racine = app.project.rootItem, morceaux = [];
    for (var i = 0; i < racine.children.numItems; i++)
      if (racine.children[i].type === ProjectItemType.BIN) ajouterChutier(racine.children[i], morceaux);
    return "{" + morceaux.join(",") + "}";
  } catch (e) { return "ERREUR:" + e; }
}

function chutierSortie() {
  var r = app.project.rootItem;
  for (var i = 0; i < r.children.numItems; i++)
    if (r.children[i].name === "Derush Auto" && r.children[i].type === ProjectItemType.BIN) return r.children[i];
  return r.createBin("Derush Auto");
}

function vider(seq) {
  var groupes = [seq.videoTracks, seq.audioTracks];
  for (var g = 0; g < 2; g++)
    for (var t = 0; t < groupes[g].numTracks; t++) {
      var cl = groupes[g][t].clips;
      for (var k = cl.numItems - 1; k >= 0; k--) cl[k].remove(0, 0);
    }
}

function poser(piste, item, entree, sortie, temps) {
  item.setInPoint(entree, 4);
  item.setOutPoint(sortie, 4);
  piste.overwriteClip(item, temps);
  item.clearInPoint(4);
  item.clearOutPoint(4);
}

// d = {nom, clips:[{fichier, entree, sortie, moments?, camera_b?}], marqueurs, musique?}
function creerSequence(texte) {
  try {
    var d = eval("(" + texte + ")");
    if (!d.clips.length) return "vide";
    if (!INDEX[d.clips[0].fichier]) listerChutiers();
    var premier = INDEX[d.clips[0].fichier];
    if (!premier) return "ERREUR:rush introuvable dans le projet";
    var bin = chutierSortie();
    // séquence aux réglages du premier rush (résolution, cadence)
    var seq = app.project.createNewSequenceFromClips(d.nom, [premier], bin);
    vider(seq);
    var t = 0, poses = 0;
    for (var i = 0; i < d.clips.length; i++) {
      var c = d.clips[i], item = INDEX[c.fichier];
      if (!item) continue;
      poser(seq.videoTracks[0], item, c.entree, c.sortie, t);
      // deuxième caméra calée par le son, sur V2
      if (c.camera_b && INDEX[c.camera_b.fichier] && seq.videoTracks.numTracks > 1) {
        var inB = c.entree - c.camera_b.decalage, dec = 0;
        if (inB < 0) { dec = -inB; inB = 0; }
        var outB = c.sortie - c.camera_b.decalage;
        if (outB > inB) poser(seq.videoTracks[1], INDEX[c.camera_b.fichier], inB, outB, t + dec);
      }
      if (d.marqueurs && c.moments)
        for (var m = 0; m < c.moments.length; m++)
          if (c.moments[m] >= c.entree && c.moments[m] <= c.sortie)
            seq.markers.createMarker(t + c.moments[m] - c.entree).name = "Moment fort";
      t += c.sortie - c.entree;
      poses++;
    }
    if (d.musique) {
      app.project.importFiles([d.musique], true, bin, false);
      for (var k = bin.children.numItems - 1; k >= 0; k--) {
        var it = bin.children[k];
        if (it.type === ProjectItemType.CLIP && it.getMediaPath() === d.musique) {
          seq.audioTracks[seq.audioTracks.numTracks - 1].overwriteClip(it, 0);
          break;
        }
      }
    }
    try { app.project.openSequence(seq.sequenceID); } catch (e2) {}
    return "ok:" + poses;
  } catch (e) { return "ERREUR:" + e; }
}
