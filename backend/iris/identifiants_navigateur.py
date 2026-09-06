"""Importer dans le coffre d'IRIS les identifiants déjà enregistrés dans le navigateur.

Demande de Miguel, le 5 septembre 2026 : « je ne dois pas avoir à tout remplir moi-même, elle le
fait elle-même, elle est intelligente ». Il a raison. Registrer chaque site à la main dans le
coffre d'IRIS était une corvée injustifiée : ses mots de passe sont déjà dans Chrome. Ce module les
y lit, une fois, sur son ordre, et les dépose dans le coffre chiffré d'IRIS
(`security/secrets.py`). Ensuite `web_login` s'en sert, et le modèle ne les voit jamais.

QUATRE RÈGLES, dans l'ordre où elles comptent.

1. LE MOT DE PASSE NE SORT JAMAIS EN CLAIR D'ICI. Il est lu, puis remis au coffre, et c'est tout.
   Jamais journalisé, jamais renvoyé à l'appelant, jamais prononcé, jamais affiché. Les fonctions
   publiques ne rendent que des NOMS de sites et d'utilisateurs. IRIS s'active à la voix : un mot de
   passe qu'elle pourrait dire tout haut serait un mot de passe qu'un inconnu dans la pièce pourrait
   lui faire dire.

2. CE QUI EST MONTRÉ EST EXACTEMENT CE QUI EST IMPORTÉ. La confirmation et l'import partent de la
   MÊME règle de correspondance. Le 5 septembre 2026, une relecture adverse a montré l'inverse : la
   confirmation nommait douze sites pendant que l'import en écrivait davantage. Un consentement qui
   porte sur un sous-ensemble de l'action n'est pas un consentement.

3. ON MATCHE LE DOMAINE, PAS UNE SOUS-CHAÎNE, PAS L'UTILISATEUR. « paypal » ne doit pas attraper
   « mypaypal-arnaque.com » (sous-chaîne) ni tout le trousseau parce que l'adresse de Miguel, qui
   sert d'identifiant partout, contient un mot cherché.

4. C'EST L'ORDINATEUR DE MIGUEL QUI DÉCHIFFRE, SOUS SON COMPTE. Windows chiffre ces mots de passe
   avec DPAPI, lié au compte de session : sur une autre machine, ils sont illisibles. Ce module ne
   fait que ce que Chrome fait déjà pour son propriétaire. Et il ne déchiffre QUE les entrées qui
   correspondent à la demande — jamais tout le trousseau pour n'en montrer que les noms.
"""
from __future__ import annotations

import base64
import contextlib
import ctypes
import ctypes.wintypes
import json
import logging
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

log = logging.getLogger("iris.identifiants")

# Au-delà, ce n'est plus « connecte-moi à un site » mais un import de masse : on redemande un terme
# plus précis plutôt que de vider tout le trousseau dans le coffre.
MAX_CORRESPONDANCES = 15


@dataclass(frozen=True)
class Identifiant:
    """Un identifiant trouvé. Il PORTE le mot de passe le temps de le remettre au coffre, mais
    aucune de ses méthodes publiques ne le rend, et son `repr` le masque."""

    domaine: str
    utilisateur: str
    _secret: str  # jamais exposé : ni repr, ni log, ni en_dict

    def __repr__(self) -> str:  # pour qu'un log accidentel ne trahisse rien
        return f"Identifiant(domaine={self.domaine!r}, utilisateur={self.utilisateur!r}, secret=***)"

    def en_dict(self) -> dict:
        return {"domaine": self.domaine, "utilisateur": self.utilisateur}


# --------------------------------------------------------------------------- correspondance
def _correspond(domaine: str, motif: str) -> bool:
    """Le motif désigne-t-il ce site ? On matche le DOMAINE, par étiquette, jamais par sous-chaîne.

    « netlify » -> app.netlify.com (étiquette). « paypal » -> paypal.com, mais PAS
    mypaypal-arnaque.com (sous-chaîne refusée). « app.netlify.com » -> lui-même (égalité)."""
    d = (domaine or "").lower()
    m = (motif or "").lower()
    if not d or not m:
        return False
    return d == m or d.endswith("." + m) or m in d.split(".")


def _domaine_de(url: str) -> str:
    return (urlsplit(url or "").hostname or "").lower().removeprefix("www.")


# --------------------------------------------------------------------------- DPAPI (sans dépendance)
class _BlobDonnees(ctypes.Structure):
    _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi_dechiffrer(chiffre: bytes) -> bytes:
    """CryptUnprotectData : ne réussit que sous le compte Windows qui a chiffré la donnée."""
    entree = _BlobDonnees(len(chiffre), ctypes.cast(ctypes.c_char_p(chiffre), ctypes.POINTER(ctypes.c_char)))
    sortie = _BlobDonnees()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(entree), None, None, None, None, 0, ctypes.byref(sortie)
    )
    if not ok:
        raise OSError("CryptUnprotectData a échoué : cette donnée n'a pas été chiffrée par ce compte Windows.")
    try:
        return ctypes.string_at(sortie.pbData, sortie.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(sortie.pbData)


# --------------------------------------------------------------------------- lecture des profils
def _profils() -> list[Path]:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    if not local.is_dir():
        return []
    racines = [
        local / "Google" / "Chrome" / "User Data",
        local / "Microsoft" / "Edge" / "User Data",
        local / "BraveSoftware" / "Brave-Browser" / "User Data",
        local / "Chromium" / "User Data",
    ]
    profils: list[Path] = []
    for racine in racines:
        if not racine.is_dir():
            continue
        for profil in racine.iterdir():
            if profil.is_dir() and (profil.name == "Default" or profil.name.startswith("Profile")):
                if (profil / "Login Data").is_file():
                    profils.append(profil)
    return profils


def _cle_aes(user_data: Path) -> bytes | None:
    """La clé AES du navigateur, tirée de « Local State » et déballée par DPAPI. None si absente.

    TOUT est dans le try, décodage base64 compris. Un « Local State » corrompu (base64 invalide ->
    binascii.Error, sous-classe de ValueError) faisait autrement échouer l'import de TOUS les sites
    de TOUS les navigateurs — défaut trouvé par une relecture adverse le 5 septembre 2026."""
    etat = user_data / "Local State"
    if not etat.is_file():
        return None
    try:
        brut = json.loads(etat.read_text(encoding="utf-8"))
        chiffre = base64.b64decode(brut["os_crypt"]["encrypted_key"])
        if not chiffre.startswith(b"DPAPI"):
            return None
        return _dpapi_dechiffrer(chiffre[5:])  # les 5 premiers octets sont l'étiquette « DPAPI »
    except (json.JSONDecodeError, KeyError, OSError, ValueError):
        return None


def _dechiffrer_valeur(valeur: bytes, cle_aes: bytes | None, dpapi=_dpapi_dechiffrer, aes_gcm=None) -> str:
    """Déchiffre un mot de passe stocké. Deux formats coexistent selon l'âge de l'entrée.

    `dpapi` et `aes_gcm` sont injectables pour que les tests n'aient besoin ni de Windows ni de
    Chrome. Aucune branche ne met le clair dans une exception : en cas d'échec, on rend « »."""
    if not valeur:
        return ""
    if valeur[:3] in (b"v10", b"v11"):
        if not cle_aes:
            return ""
        nonce, corps = valeur[3:15], valeur[15:]
        if aes_gcm is None:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM

            aes_gcm = lambda cle, n, c: AESGCM(cle).decrypt(n, c, None)  # noqa: E731
        try:
            return aes_gcm(cle_aes, nonce, corps).decode("utf-8", "replace")
        except Exception:
            return ""
    try:
        return dpapi(valeur).decode("utf-8", "replace")
    except OSError:
        return ""


@contextlib.contextmanager
def _base_copiee(fichier: Path):
    """Ouvre en lecture une COPIE de la base : le fichier est verrouillé tant que le navigateur
    tourne, et on ne demande pas à Miguel de fermer Chrome pour se connecter. La copie est toujours
    supprimée, même en cas d'erreur."""
    copie = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tampon:
            copie = Path(tampon.name)
        shutil.copy2(fichier, copie)
        with sqlite3.connect(f"file:{copie}?mode=ro", uri=True, timeout=5) as cx:
            cx.row_factory = sqlite3.Row
            yield cx
    finally:
        if copie is not None:
            try:
                copie.unlink(missing_ok=True)
            except OSError:
                pass


def _entrees(motif: str | None = None) -> list[dict]:
    """Les (domaine, utilisateur) de tous les profils, SANS rien déchiffrer.

    C'est ce qui construit la confirmation. Ne toucher à aucun mot de passe ici est double gain :
    la confirmation n'a pas à déchiffrer quoi que ce soit, et on ne matérialise jamais un trousseau
    en clair juste pour en montrer les noms."""
    vus: set[tuple[str, str]] = set()
    sortie: list[dict] = []
    for profil in _profils():
        try:
            with _base_copiee(profil / "Login Data") as cx:
                lignes = cx.execute(
                    "SELECT origin_url, username_value FROM logins "
                    "WHERE blacklisted_by_user = 0 AND username_value <> ''"
                ).fetchall()
        except (sqlite3.Error, OSError) as exc:
            log.debug("identifiants illisibles (%s) : %s", profil.name, exc)
            continue
        for ligne in lignes:
            domaine = _domaine_de(ligne["origin_url"])
            if not domaine or (motif is not None and not _correspond(domaine, motif)):
                continue
            cle = (domaine, ligne["username_value"])
            if cle not in vus:
                vus.add(cle)
                sortie.append({"domaine": domaine, "utilisateur": ligne["username_value"]})
    return sortie


def _identifiants(motif: str, dpapi=_dpapi_dechiffrer, aes_gcm=None) -> list[Identifiant]:
    """Les identifiants qui correspondent à `motif`, AVEC le secret. On ne déchiffre QUE les lignes
    qui correspondent : le trousseau entier n'est jamais mis en clair en mémoire."""
    resultats: list[Identifiant] = []
    for profil in _profils():
        cle = _cle_aes(profil.parent)
        try:
            with _base_copiee(profil / "Login Data") as cx:
                lignes = cx.execute(
                    "SELECT origin_url, username_value, password_value FROM logins "
                    "WHERE blacklisted_by_user = 0 AND username_value <> ''"
                ).fetchall()
        except (sqlite3.Error, OSError) as exc:
            log.debug("identifiants illisibles (%s) : %s", profil.name, exc)
            continue
        for ligne in lignes:
            domaine = _domaine_de(ligne["origin_url"])
            if not domaine or not _correspond(domaine, motif):
                continue
            secret = _dechiffrer_valeur(ligne["password_value"], cle, dpapi=dpapi, aes_gcm=aes_gcm)
            if secret:
                resultats.append(Identifiant(domaine=domaine, utilisateur=ligne["username_value"], _secret=secret))
    return resultats


# --------------------------------------------------------------------------- ce que voit le reste d'IRIS
def disponible() -> bool:
    return bool(_profils())


def noms_correspondants(terme: str) -> list[dict]:
    """Les (domaine, utilisateur) enregistrés qui correspondent à `terme`, SANS mots de passe.

    Sert à construire la confirmation : ce qui est montré à Miguel est EXACTEMENT ce que
    `importer_dans_le_coffre` écrira, parce que les deux passent par `_correspond`."""
    motif = (terme or "").strip().lower()
    if not motif:
        return []
    entrees = _entrees(motif)
    entrees.sort(key=lambda e: (e["domaine"], e["utilisateur"]))
    return entrees


def importer_dans_le_coffre(terme: str, secrets, dpapi=_dpapi_dechiffrer, aes_gcm=None) -> dict:
    """Copie dans le coffre d'IRIS les identifiants du navigateur qui correspondent à `terme`.

    Le mot de passe va DIRECTEMENT du navigateur au coffre, sans jamais transiter par une valeur de
    retour, un journal ou un message. On ne rend que le compte de ce qui a été importé et les noms
    des sites."""
    motif = (terme or "").strip().lower()
    if not motif:
        return {"importes": 0, "sites": [], "message": "Dis-moi le nom du site à retrouver."}
    importes, noms = 0, []
    for ident in _identifiants(motif, dpapi=dpapi, aes_gcm=aes_gcm):
        try:
            secrets.set_site(ident.domaine, ident.utilisateur, ident._secret)
            importes += 1
            if ident.domaine not in noms:
                noms.append(ident.domaine)
        except Exception as exc:
            # On ne journalise QUE le type : `set_site` vient de recevoir le mot de passe en
            # argument, et l'objet exception d'un coffre futur pourrait le porter dans son message.
            log.warning("échec de l'import de %s : %s", ident.domaine, type(exc).__name__)
    if not importes:
        return {"importes": 0, "sites": [],
                "message": f"Je n'ai trouvé aucun identifiant enregistré pour « {terme} » dans ton navigateur."}
    return {"importes": importes, "sites": noms,
            "message": f"J'ai récupéré {importes} identifiant(s) depuis ton navigateur : {', '.join(noms)}."}
