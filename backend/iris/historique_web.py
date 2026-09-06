"""Retrouver un site dans l'historique de navigation, pour qu'IRIS sache OÙ aller.

Demande de Miguel : « lorsque je lui demande de se connecter à un compte, elle doit aller fouiller
l'historique web et le retrouver, ensuite exécuter la commande ». Ce module fait la première
moitié : identifier le site. La seconde est déjà en place, c'est `web_login`, qui remplit le
formulaire avec les identifiants du coffre sans jamais les montrer au modèle.

CE QUE CE MODULE NE FAIT PAS, ET POURQUOI CE N'EST PAS NÉGOCIABLE.

Il ne lit AUCUN mot de passe enregistré dans le navigateur. La raison n'est pas juridique, elle est
dans la nature du produit : IRIS s'active à la voix. Si elle pouvait sortir n'importe quel mot de
passe sur commande parlée, le mot « Iris » deviendrait la seule chose entre un inconnu et le compte
bancaire de son propriétaire — un inconnu assis à la même table, ou dans la même salle de
présentation. Le coffre (`security/secrets.py`) reste donc le seul chemin vers un identifiant, et
il est délibéré : on y dépose un site une fois, sciemment.

CE QUI EN SORT, ET CE QUI N'EN SORT PAS. Un historique de navigation est intime. Ce module ne rend
jamais l'historique : il rend une poignée de sites qui correspondent à ce qui a été demandé, sans
les adresses complètes ni leurs paramètres — un lien de réinitialisation de mot de passe, un jeton
de session ou un identifiant de commande vivent justement dans une adresse complète.
"""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

log = logging.getLogger("iris.historique")

# Chrome compte les microsecondes depuis le 1er janvier 1601. Unix compte les secondes depuis 1970.
EPOQUE_CHROME = datetime(1601, 1, 1, tzinfo=timezone.utc)

# Les sites qu'on ne propose jamais : ils ne sont pas des « comptes » et pollueraient la réponse.
BRUIT = (
    "google.com/search", "bing.com/search", "duckduckgo.com/", "localhost", "127.0.0.1",
    "newtab", "chrome-extension", "chrome://", "edge://", "about:",
)

MAX_RESULTATS = 8  # au-delà, ce n'est plus une réponse, c'est un déversement d'historique


@dataclass(frozen=True)
class SiteTrouve:
    """Un site retenu. Volontairement pauvre : le domaine, le titre, et de quoi juger."""

    domaine: str
    titre: str
    visites: int
    derniere_visite: str  # ISO, ou "" si illisible

    def en_dict(self) -> dict:
        return {
            "domaine": self.domaine,
            "titre": self.titre,
            "visites": self.visites,
            "derniere_visite": self.derniere_visite,
        }

    def resume(self) -> str:
        quand = f", vu {self.derniere_visite[:10]}" if self.derniere_visite else ""
        return f"{self.domaine} ({self.titre[:60]}, {self.visites} visite(s){quand})"


def _dossiers_navigateurs() -> list[Path]:
    """Les fichiers d'historique des navigateurs installés, profils multiples compris."""
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    if not local.is_dir():
        return []
    racines = [
        local / "Google" / "Chrome" / "User Data",
        local / "Microsoft" / "Edge" / "User Data",
        local / "BraveSoftware" / "Brave-Browser" / "User Data",
        local / "Chromium" / "User Data",
    ]
    trouves: list[Path] = []
    for racine in racines:
        if not racine.is_dir():
            continue
        for profil in racine.iterdir():
            # « Default », « Profile 1 », « Profile 2 »… Les autres dossiers ne sont pas des profils.
            if not profil.is_dir():
                continue
            if profil.name != "Default" and not profil.name.startswith("Profile"):
                continue
            fichier = profil / "History"
            if fichier.is_file():
                trouves.append(fichier)
    return trouves


def _instant(valeur: int) -> str:
    """Convertit un horodatage Chrome en ISO. Chaîne vide si la valeur n'a aucun sens."""
    try:
        if not valeur or valeur <= 0:
            return ""
        moment = EPOQUE_CHROME + timedelta(microseconds=int(valeur))
        if moment.year < 1990 or moment.year > 2100:
            return ""
        return moment.isoformat()
    except (OverflowError, ValueError, TypeError):
        return ""


def _lire_profil(fichier: Path, motifs: list[str], depuis_jours: int) -> list[SiteTrouve]:
    """Interroge UNE copie de l'historique. Une copie, parce que le fichier est verrouillé tant que
    le navigateur tourne — et on ne demande pas à quelqu'un de fermer Chrome pour parler à IRIS."""
    if not motifs:
        return []
    copie = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tampon:
            copie = Path(tampon.name)
        shutil.copy2(fichier, copie)
        # Le journal d'écriture peut contenir les visites les plus récentes.
        for suffixe in ("-wal", "-shm"):
            voisin = fichier.with_name(fichier.name + suffixe)
            if voisin.is_file():
                shutil.copy2(voisin, copie.with_name(copie.name + suffixe))

        conditions = " OR ".join(["url LIKE ? OR title LIKE ?"] * len(motifs))
        parametres: list[object] = []
        for motif in motifs:
            parametres.extend([f"%{motif}%", f"%{motif}%"])
        borne = ""
        if depuis_jours > 0:
            debut = datetime.now(timezone.utc) - timedelta(days=depuis_jours)
            parametres.append(int((debut - EPOQUE_CHROME).total_seconds() * 1_000_000))
            borne = " AND last_visit_time > ?"

        lignes = []
        with sqlite3.connect(f"file:{copie}?mode=ro", uri=True, timeout=5) as cx:
            cx.row_factory = sqlite3.Row
            lignes = cx.execute(
                f"SELECT url, title, visit_count, last_visit_time FROM urls "
                f"WHERE ({conditions}){borne} ORDER BY visit_count DESC, last_visit_time DESC LIMIT 400",
                parametres,
            ).fetchall()
    except (sqlite3.Error, OSError) as exc:
        log.debug("historique illisible (%s) : %s", fichier.parent.name, exc)
        return []
    finally:
        for chemin in (copie, copie.with_name(copie.name + "-wal") if copie else None,
                       copie.with_name(copie.name + "-shm") if copie else None):
            if chemin is not None:
                try:
                    chemin.unlink(missing_ok=True)
                except OSError:
                    pass

    # On regroupe par DOMAINE : vingt pages d'un même site sont un seul site, pas vingt réponses.
    par_domaine: dict[str, dict] = {}
    for ligne in lignes:
        url = ligne["url"] or ""
        if any(bruit in url.lower() for bruit in BRUIT):
            continue
        domaine = (urlsplit(url).hostname or "").lower().removeprefix("www.")
        if not domaine or "." not in domaine:
            continue
        entree = par_domaine.setdefault(domaine, {"titre": "", "visites": 0, "quand": 0})
        entree["visites"] += int(ligne["visit_count"] or 0)
        instant = int(ligne["last_visit_time"] or 0)
        if instant > entree["quand"]:
            entree["quand"] = instant
            entree["titre"] = (ligne["title"] or "").strip()
    return [
        SiteTrouve(domaine=d, titre=v["titre"], visites=v["visites"], derniere_visite=_instant(v["quand"]))
        for d, v in par_domaine.items()
    ]


def chercher(terme: str, depuis_jours: int = 0, limite: int = MAX_RESULTATS) -> list[SiteTrouve]:
    """Les sites de l'historique qui correspondent à `terme`, du plus fréquenté au moins.

    `depuis_jours` = 0 veut dire « tout l'historique ». Le regroupement se fait par domaine, entre
    tous les navigateurs et tous les profils : quelqu'un qui a deux profils Chrome ne devrait pas
    avoir à savoir lequel."""
    motifs = [m for m in (terme or "").strip().lower().split() if len(m) >= 3]
    if not motifs:
        return []
    fusion: dict[str, SiteTrouve] = {}
    for fichier in _dossiers_navigateurs():
        for site in _lire_profil(fichier, motifs, depuis_jours):
            ancien = fusion.get(site.domaine)
            if ancien is None:
                fusion[site.domaine] = site
            else:
                fusion[site.domaine] = SiteTrouve(
                    domaine=site.domaine,
                    titre=ancien.titre or site.titre,
                    visites=ancien.visites + site.visites,
                    derniere_visite=max(ancien.derniere_visite, site.derniere_visite),
                )
    classe = sorted(fusion.values(), key=lambda s: (-s.visites, s.derniere_visite), reverse=False)
    return classe[: max(1, min(limite, MAX_RESULTATS))]


def disponible() -> bool:
    """Y a-t-il seulement un historique à consulter sur cette machine ?"""
    return bool(_dossiers_navigateurs())


def pourquoi_indisponible() -> str:
    """La phrase à dire quand il n'y a rien à fouiller. Jamais une erreur technique."""
    if disponible():
        return ""
    return ("Je ne trouve aucun historique de navigation sur cet ordinateur. "
            "Dis-moi l'adresse du site et je m'y rends directement.")
