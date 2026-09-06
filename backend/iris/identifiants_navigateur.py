"""Importer dans le coffre d'IRIS les identifiants déjà enregistrés dans le navigateur.

Demande de Miguel, le 5 septembre 2026 : « je ne dois pas avoir à tout remplir moi-même, elle le
fait elle-même, elle est intelligente ». Il a raison. Registrer chaque site à la main dans le
coffre d'IRIS était une corvée injustifiée : ses mots de passe sont déjà dans Chrome. Ce module les
y lit, une fois, sur son ordre, et les dépose dans le coffre chiffré d'IRIS
(`security/secrets.py`). Ensuite `web_login` s'en sert, et le modèle ne les voit jamais.

TROIS RÈGLES, dans l'ordre où elles comptent.

1. LE MOT DE PASSE NE SORT JAMAIS EN CLAIR D'ICI. Il est lu, puis remis au coffre, et c'est tout.
   Il n'est jamais journalisé, jamais renvoyé à l'appelant, jamais prononcé, jamais affiché. Les
   fonctions publiques ne rendent que des NOMS de sites et des noms d'utilisateur — jamais un
   secret. C'est la règle qui protège Miguel : IRIS s'active à la voix, et un mot de passe qu'elle
   pourrait dire à voix haute serait un mot de passe qu'un inconnu dans la pièce pourrait lui faire
   dire.

2. C'EST L'ORDINATEUR DE MIGUEL QUI DÉCHIFFRE, SOUS SON COMPTE. Windows chiffre ces mots de passe
   avec DPAPI, lié au compte de session : personne d'autre, sur une autre machine, ne peut les
   lire. Ce module ne fait donc que ce que Chrome fait déjà pour son propriétaire.

3. RIEN N'EST IMPORTÉ SANS ACCORD. Ce module lit et déchiffre ; c'est l'outil, plus haut, qui
   demande la confirmation avant d'écrire quoi que ce soit dans le coffre.
"""
from __future__ import annotations

import base64
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
        """Ce qu'on peut montrer : le site et l'utilisateur. Jamais le secret."""
        return {"domaine": self.domaine, "utilisateur": self.utilisateur}


# --------------------------------------------------------------------------- DPAPI (sans dépendance)
class _BlobDonnees(ctypes.Structure):
    _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi_dechiffrer(chiffre: bytes) -> bytes:
    """CryptUnprotectData : ne réussit que sous le compte Windows qui a chiffré la donnée.

    Appelé par ctypes plutôt que par win32crypt : une dépendance de moins, et surtout ça garde ce
    module lisible pour qui voudra vérifier qu'il ne fait que déchiffrer, rien d'autre."""
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


# --------------------------------------------------------------------------- les profils du navigateur
def _profils() -> list[Path]:
    """Les dossiers de profil qui contiennent un fichier « Login Data »."""
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
    """La clé AES du navigateur, tirée de « Local State » et déballée par DPAPI. None si absente."""
    etat = user_data / "Local State"
    if not etat.is_file():
        return None
    try:
        brut = json.loads(etat.read_text(encoding="utf-8"))
        encodee = brut["os_crypt"]["encrypted_key"]
    except (json.JSONDecodeError, KeyError, OSError):
        return None
    chiffre = base64.b64decode(encodee)
    if not chiffre.startswith(b"DPAPI"):
        return None
    return _dpapi_dechiffrer(chiffre[5:])  # les 5 premiers octets sont l'étiquette « DPAPI »


def _dechiffrer_valeur(valeur: bytes, cle_aes: bytes | None, dpapi=_dpapi_dechiffrer, aes_gcm=None) -> str:
    """Déchiffre un mot de passe stocké. Deux formats coexistent selon l'âge de l'entrée.

    `dpapi` et `aes_gcm` sont injectables pour que les tests n'aient besoin ni de Windows ni de
    Chrome. En production, `aes_gcm` reste None et on utilise `cryptography`."""
    if not valeur:
        return ""
    # Format récent : « v10 » ou « v11 », puis nonce (12) + chiffré + étiquette GCM (16).
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
    # Ancien format : DPAPI directement.
    try:
        return dpapi(valeur).decode("utf-8", "replace")
    except OSError:
        return ""


def _lire_profil(profil: Path, user_data: Path, dpapi=_dpapi_dechiffrer, aes_gcm=None) -> list[Identifiant]:
    """Les identifiants d'UN profil. Passe par une copie : « Login Data » est verrouillé tant que le
    navigateur tourne, et on ne demande pas à Miguel de fermer Chrome pour se connecter."""
    source = profil / "Login Data"
    copie = None
    trouves: list[Identifiant] = []
    try:
        cle = _cle_aes(user_data)
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tampon:
            copie = Path(tampon.name)
        shutil.copy2(source, copie)
        with sqlite3.connect(f"file:{copie}?mode=ro", uri=True, timeout=5) as cx:
            cx.row_factory = sqlite3.Row
            lignes = cx.execute(
                "SELECT origin_url, username_value, password_value FROM logins "
                "WHERE blacklisted_by_user = 0 AND username_value <> ''"
            ).fetchall()
        for ligne in lignes:
            secret = _dechiffrer_valeur(ligne["password_value"], cle, dpapi=dpapi, aes_gcm=aes_gcm)
            if not secret:
                continue
            domaine = (urlsplit(ligne["origin_url"] or "").hostname or "").lower().removeprefix("www.")
            if not domaine:
                continue
            trouves.append(Identifiant(domaine=domaine, utilisateur=ligne["username_value"], _secret=secret))
    except (sqlite3.Error, OSError) as exc:
        log.debug("identifiants illisibles (%s) : %s", profil.name, exc)
    finally:
        if copie is not None:
            try:
                copie.unlink(missing_ok=True)
            except OSError:
                pass
    return trouves


def _tous(dpapi=_dpapi_dechiffrer, aes_gcm=None) -> list[Identifiant]:
    resultats: list[Identifiant] = []
    for profil in _profils():
        resultats.extend(_lire_profil(profil, profil.parent, dpapi=dpapi, aes_gcm=aes_gcm))
    return resultats


# --------------------------------------------------------------------------- ce que voit le reste d'IRIS
def disponible() -> bool:
    return bool(_profils())


def sites_pour(terme: str, dpapi=_dpapi_dechiffrer, aes_gcm=None) -> list[dict]:
    """Les sites enregistrés qui correspondent à `terme`, SANS mots de passe.

    Sert à répondre « pour quel compte ? » quand plusieurs collent. On ne rend que domaine +
    utilisateur : de quoi choisir, rien de secret."""
    motif = (terme or "").strip().lower()
    if not motif:
        return []
    vus, sortie = set(), []
    for ident in _tous(dpapi=dpapi, aes_gcm=aes_gcm):
        if motif in ident.domaine or motif in ident.utilisateur.lower():
            cle = (ident.domaine, ident.utilisateur)
            if cle not in vus:
                vus.add(cle)
                sortie.append(ident.en_dict())
    return sortie[:12]


def importer_dans_le_coffre(terme: str, secrets, dpapi=_dpapi_dechiffrer, aes_gcm=None) -> dict:
    """Copie dans le coffre d'IRIS les identifiants du navigateur qui correspondent à `terme`.

    Le mot de passe va DIRECTEMENT du navigateur au coffre, sans jamais transiter par une valeur de
    retour, un journal ou un message. On ne rend que le compte de ce qui a été importé et les noms
    des sites — jamais un secret."""
    motif = (terme or "").strip().lower()
    if not motif:
        return {"importes": 0, "sites": [], "message": "Dis-moi le nom du site à retrouver."}
    importes, noms = 0, []
    for ident in _tous(dpapi=dpapi, aes_gcm=aes_gcm):
        if motif not in ident.domaine and motif not in ident.utilisateur.lower():
            continue
        try:
            # Le nom sous lequel le site vit dans le coffre : son domaine. web_login le retrouve ainsi.
            secrets.set_site(ident.domaine, ident.utilisateur, ident._secret)
            importes += 1
            if ident.domaine not in noms:
                noms.append(ident.domaine)
        except Exception as exc:
            log.warning("échec de l'import de %s : %s", ident.domaine, exc)
    if not importes:
        return {"importes": 0, "sites": [],
                "message": f"Je n'ai trouvé aucun identifiant enregistré pour « {terme} » dans ton navigateur."}
    return {"importes": importes, "sites": noms,
            "message": f"J'ai récupéré {importes} identifiant(s) depuis ton navigateur : {', '.join(noms)}."}
