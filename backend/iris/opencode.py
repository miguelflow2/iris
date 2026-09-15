"""IRIS confie la programmation à OpenCode.

« Iris, corrige le bogue dans mon site » : IRIS ne se met pas à écrire du code elle-même dans le
fil de la conversation, elle envoie un ouvrier — OpenCode — travailler dans UN dossier précis, puis
elle rend compte de ce qu'il a fait. OpenCode n'est pas un moteur de plus à côté d'OpenRouter : ce
n'est pas la même couche. OpenRouter fournit un modèle ; OpenCode CONSOMME un fournisseur pour
modifier des fichiers. On ne les met jamais dans la même liste.

L'ÉTAT DE LA MACHINE AU 5 SEPTEMBRE 2026 — ce module est DORMANT
-----------------------------------------------------------------
L'outil en ligne de commande `opencode` n'est installé nulle part : rien dans le PATH, pas de
`~/.opencode`, pas de paquet npm global. Ce qui est là, c'est l'application de bureau (Electron,
installée le 28 août) et le kit de greffons `@opencode-ai/*` en 1.18.23 — l'application n'embarque
aucun binaire en ligne de commande, et elle n'expose aucun port documenté. Donc aujourd'hui, et
c'est le chemin de loin le plus emprunté, ce service répond une phrase en français et ne lance
RIEN. Il ne s'agit pas d'un drapeau qu'on peut oublier de mettre à jour : `disponible` est faux
tant qu'aucun binaire n'est trouvé sur le disque, point.

Et IRIS n'installe pas OpenCode à la place de Miguel. Installer un agent qui écrit des fichiers,
c'est une décision qui se prend sciemment, dans un terminal, par la personne qui en assume les
conséquences.

CE QUE CE MODULE PEUT PROMETTRE, ET CE QU'IL NE PEUT PAS
---------------------------------------------------------
Il PEUT : refuser de partir tant qu'un humain n'a pas approuvé un dossier précis ; refuser un
dossier hors de la liste blanche ; imposer sa propre politique à OpenCode sans toucher au fichier
de configuration de Miguel ; constater après coup ce qui a changé, fichier par fichier ; dire
« il n'a rien modifié » avec la même netteté que « c'est fait ».

Il NE PEUT PAS empêcher OpenCode d'écrire ailleurs sur l'ordinateur. Une fois lancé, le processus
tourne sous la session Windows de Miguel, avec ses droits. Il n'existe pas ici de bac à sable sans
dépendance nouvelle, et `external_directory: "deny"` revient à demander à l'agent qu'on surveille
de se surveiller lui-même. Le périmètre est une DÉCLARATION et un DÉTECTEUR, pas une prison —
et la phrase de confirmation le dit, au lieu de le masquer.

POURQUOI LE PÉRIMÈTRE FAIT PARTIE DE L'ACCORD
----------------------------------------------
Défaut trouvé le 5 septembre 2026 dans `telephonie.py` : l'accord donné pour un brouillon préparé
sur l'iPhone — où c'est Miguel qui appuie sur Envoyer — restait valable si la voie basculait
ensuite sur un service payant qui envoie tout seul. Approuver un geste ne vaut pas approuver un
autre geste. Ici, la variable n'est pas la voie mais le DOSSIER : un accord donné pour
`Documents/IRIS/site-flowcare` ne doit jamais valoir pour `Downloads/startup/iris`. L'empreinte
couvre donc le dossier RÉSOLU, et le périmètre est revérifié au moment d'agir, pas seulement au
moment de demander.

Ce n'est pas une crainte théorique. Le journal d'OpenCode
(`~/.local/share/opencode/log/opencode.log`) montre qu'il a déjà travaillé sur le backend d'IRIS :
on y lit ses appels à `http://127.0.0.1:8765/api/transcribe`. Le dossier qu'il faut le plus
sûrement lui interdire est celui où il est déjà allé tout seul.

TROU CONNU, ET IL N'EST PAS DANS CE MODULE
-------------------------------------------
Aucune confirmation ne passe par la voix : rien dans `backend/iris/voice/` n'écoute l'événement
« chat.confirm ». Une demande dictée qui ouvrirait une modale ouvrirait une modale que personne ne
regarde, laquelle expirerait au bout de 180 secondes sur un « refusé » silencieux. Donc quand la
demande vient de la voix, ce module répond « valide-le à l'écran » AU LIEU d'ouvrir cette modale
invisible. C'est une condition sur un paramètre qui existe déjà (`source`), pas une modification
de la voix — la voix ne dépend de rien d'écrit ici.

CE MODULE N'IMPORTE RIEN DU RESTE D'IRIS
-----------------------------------------
Ni la voix, ni la traduction, ni les commandes rapides, ni même la configuration : il reçoit
`settings`, un lanceur de processus et un registre, et c'est tout. C'est délibéré. La voix a subi
une panne totale le 5 septembre 2026, elle vient d'être réparée, et Miguel présente le 8 : rien de
ce qui est écrit ici ne doit pouvoir la faire retomber. Tant que personne ne câble ce service dans
`main.py`, l'importer ne change strictement rien au comportement d'IRIS.

LA SERRURE
----------
Même dispositif que `courriel.py` et `telephonie.py`, volontairement identique : `executer()`
n'accepte pas un chantier, il accepte une `Autorisation`, et une `Autorisation` ne se fabrique
qu'avec un sceau privé au module que seule `demander_accord()` détient. Elle est liée à
l'empreinte du chantier, ne sert qu'une fois, et expire au bout de cinq minutes.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any, Awaitable, Callable, Iterable

log = logging.getLogger("iris.opencode")

DUREE_ACCORD = 300.0  # un oui vaut cinq minutes, comme pour un SMS : le temps de se raviser
DUREE_MAX_DEFAUT = 600.0  # dix minutes : au-delà, un agent qui « travaille encore » tourne en rond
DUREE_MAX_PLANCHER = 30.0
DUREE_MAX_PLAFOND = 3600.0
DELAI_GIT = 15.0  # git status sur un gros dépôt, pas une connexion réseau

# Un inventaire du dossier avant et après : c'est ce qui permet de dire « il n'a rien modifié »
# sans dépendre de git, et la majorité des dossiers où IRIS travaille ne sont pas versionnés
# (~/Documents/IRIS n'en contient aucun). La borne évite qu'un dossier avec un node_modules oublié
# fasse marcher IRIS pendant une minute avant même de commencer.
MAX_FICHIERS_INVENTAIRE = 20_000
MAX_FICHIERS_NOMMES = 40  # au-delà, on donne le compte, pas la liste : personne ne lit 300 noms

DOSSIERS_IGNORES = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", ".next", ".nuxt", "target", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".gradle", ".idea", ".vscode", "vendor", ".turbo", ".cache",
}

GENRES = {
    "correction": "corriger",
    "ajout": "ajouter quelque chose",
    "revue": "relire",
    "tache": "travailler",
}
GENRE_DEFAUT = "tache"

ConfirmFn = Callable[[str, str], Awaitable[bool]]  # (titre, détail) -> approuvé ? — celle de ToolContext


MODE_EMPLOI = (
    "OpenCode n'est pas installé sur cet ordinateur, alors je ne peux pas encore lui confier de "
    "travail de programmation. L'application de bureau OpenCode est bien là, mais elle n'apporte "
    "pas l'outil en ligne de commande dont j'ai besoin. Il faut l'installer toi-même, dans un "
    "terminal, en suivant les instructions de opencode.ai — je n'installe rien sur ton ordinateur "
    "à ta place : un programme qui a le droit de modifier tes fichiers, c'est toi qui décides de "
    "le poser. Quand ce sera fait, redis-le-moi. En attendant, si tu me montres le fichier, je "
    "peux corriger le code moi-même."
)

EXPLICATION_SURVEILLANCE = (
    "Je ne peux pas l'empêcher d'écrire ailleurs sur ton ordinateur : il tourne avec tes droits. "
    "Je le surveille et je te dis tout ce qui a changé, mais je ne l'enferme pas."
)


# --------------------------------------------------------------------------- erreurs
class ErreurOpenCode(Exception):
    """Toute erreur d'ici porte une phrase française, destinée à être lue ou dite à l'utilisateur."""


class OpenCodeIndisponible(ErreurOpenCode):
    """Le service n'est pas utilisable. C'est l'état normal aujourd'hui : il le DIT, il ne plante pas."""


class CheminRefuse(ErreurOpenCode):
    """Le dossier demandé sort du périmètre autorisé, ou n'est pas un dossier de travail valable."""


class AutorisationInvalide(ErreurOpenCode):
    """Levée dès qu'on tente d'agir sans un accord valide, à jour, non consommé, pour CE dossier."""


# --------------------------------------------------------------------------- lancement de processus
@dataclass(frozen=True)
class Resultat:
    """Ce que rend un lancement de programme.

    `expire` n'est pas un échec : c'est « il n'avait pas fini ». La différence compte, parce qu'un
    agent arrêté en cours de route a déjà modifié des fichiers, et qu'IRIS ne doit ni prétendre
    qu'il a réussi, ni prétendre qu'il n'a rien fait.
    """

    code: int = 0
    sortie: str = ""
    expire: bool = False
    introuvable: bool = False  # le programme lui-même n'existe pas (git absent, binaire effacé)


# (argv, dossier de travail, délai en secondes, variables d'environnement à ajouter) -> Resultat.
# Injecté, exactement comme `client_http` dans telephonie.py : aucun test de ce module ne lance de
# processus, ni OpenCode, ni git.
Lanceur = Callable[[list[str], "Path | None", float, "dict[str, str] | None"], Resultat]


def _lanceur_par_defaut(argv: list[str], dossier: Path | None, delai: float,
                        env: dict[str, str] | None = None) -> Resultat:
    """Le vrai lancement. Import local : `subprocess` n'a rien à charger tant que rien ne tourne."""
    import subprocess

    environnement = dict(os.environ)
    if env:
        environnement.update(env)
    args = list(argv)
    # Sous Windows, `shutil.which` rend souvent un `.cmd` (installation npm). CreateProcess ne sait
    # pas exécuter un script de commandes : sans ce détour, on récolte un « application Win32 non
    # valide » incompréhensible au lieu d'un lancement.
    if os.name == "nt" and args and args[0].lower().endswith((".cmd", ".bat")):
        args = ["cmd", "/c", *args]
    try:
        proc = subprocess.run(
            args,
            cwd=str(dossier) if dossier else None,
            capture_output=True,
            text=True,
            timeout=max(1.0, float(delai)),
            encoding="utf-8",
            errors="replace",
            env=environnement,
        )
    except subprocess.TimeoutExpired as depassement:
        partiel = (depassement.stdout or "") if isinstance(depassement.stdout, str) else ""
        return Resultat(code=-1, sortie=partiel, expire=True)
    except FileNotFoundError:
        return Resultat(code=-1, sortie="", introuvable=True)
    except OSError as erreur:  # droits, exécutable corrompu : ça se dit, ça ne remonte pas brut
        return Resultat(code=-1, sortie=str(erreur))
    sortie = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    return Resultat(code=int(proc.returncode), sortie=sortie.strip())


# --------------------------------------------------------------------------- où est OpenCode
def _candidats_binaire() -> list[Path]:
    """Emplacements d'installation connus, dans l'ordre où on les rencontre en pratique."""
    maison = Path.home()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    noms = ["opencode.cmd", "opencode.exe", "opencode"] if os.name == "nt" else ["opencode"]
    dossiers = [
        maison / ".opencode" / "bin",
        maison / ".bun" / "bin",
        maison / ".local" / "bin",
        Path(appdata) / "npm" if appdata else None,
        Path(local) / "Programs" / "opencode" if local else None,
    ]
    return [d / n for d in dossiers if d is not None for n in noms]


def trouver_opencode() -> str:
    """Cherche le binaire. Rend "" s'il n'y en a pas — et ne lève JAMAIS.

    C'est le chemin le plus emprunté du module : sur cette machine il rend "" à chaque appel. Une
    exception ici deviendrait une erreur technique affichée à quelqu'un qui a simplement demandé
    à IRIS de corriger un bogue.
    """
    try:
        trouve = shutil.which("opencode")
        if trouve:
            return str(Path(trouve))
        for candidat in _candidats_binaire():
            try:
                if candidat.is_file():
                    return str(candidat)
            except OSError:
                continue
    except Exception as exc:  # PATH exotique, lecteur réseau déconnecté : ce n'est pas une panne
        log.warning("Recherche d'OpenCode impossible : %s", exc)
    return ""


# --------------------------------------------------------------------------- le périmètre
_VARIABLE_NON_RESOLUE = re.compile(r"%[^%\\/]+%")
_CONTROLE = re.compile(r"[\r\n\x00]")
_LECTEUR_RELATIF = re.compile(r"^[A-Za-z]:[^\\/]")


def racines_interdites_par_defaut() -> tuple[Path, ...]:
    """Ce qui reste interdit MÊME s'il est imbriqué dans un dossier autorisé.

    La liste noire prime sur la liste blanche : autoriser `~/Documents` ne doit pas autoriser
    `~/Documents/.ssh` par ricochet, et autoriser un jour `~/Downloads/startup` ne doit surtout pas
    ouvrir le dépôt d'IRIS.

    Le dépôt d'IRIS y figure pour une raison constatée, pas par principe : le journal d'OpenCode
    montre qu'il a déjà tourné dessus (appels à 127.0.0.1:8765). Le dossier de données y figure
    parce qu'il contient `.env`, `settings.json` et `iris.db` — un agent envoyé « corriger mon
    site » qui lit `.env` lit aussi les clés ElevenLabs et de licence.
    """
    interdits: list[Path] = []
    maison = Path.home()
    for brut in (
        os.environ.get("SystemRoot"),
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramW6432"),
        os.environ.get("ProgramFiles(x86)"),
        os.environ.get("ProgramData"),
    ):
        if brut:
            interdits.append(Path(brut))
    for relatif in (".ssh", ".aws", ".gnupg", ".config", ".local/share/opencode", "AppData"):
        interdits.append(maison / relatif)
    try:
        # backend/iris/opencode.py -> backend/iris -> backend -> la racine du dépôt d'IRIS.
        interdits.append(Path(__file__).resolve().parents[2])
    except (IndexError, OSError):
        pass
    resolus: list[Path] = []
    for chemin in interdits:
        try:
            resolus.append(chemin.expanduser().resolve())
        except OSError:
            continue
    return tuple(dict.fromkeys(resolus))


def _normaliser(brut: str) -> Path:
    """Transforme une chaîne en chemin absolu utilisable, ou lève avec une phrase française.

    Chaque refus correspond à un piège mesuré sur cette machine (Python 3.13, Windows 10), pas à
    une précaution imaginée.
    """
    chemin = (brut or "").strip().strip('"')
    if not chemin:
        raise CheminRefuse("Tu ne m'as pas dit dans quel dossier travailler. Je ne devine pas.")
    if _CONTROLE.search(chemin):
        raise CheminRefuse("Ce chemin contient un retour à la ligne : je ne l'accepte pas.")
    if _VARIABLE_NON_RESOLUE.search(chemin):
        # « %USERPROFILE%\site » arrive tel quel quand un modèle recopie une variable d'un fichier
        # de configuration. Non résolue, elle désigne un dossier littéralement nommé « %…% ».
        raise CheminRefuse(
            f"« {chemin} » contient une variable d'environnement que personne n'a remplacée. "
            "Donne-moi le chemin complet du dossier."
        )
    plat = chemin.replace("/", "\\")
    if plat.startswith("\\\\?\\") or plat.startswith("\\\\.\\"):
        # Mesuré : Path(r'\\?\C:\...\..\..\Windows').resolve() rend « C:Users\Windows », qui n'est
        # ni le chemin de départ ni une réponse de confinement valable. Un chemin périphérique
        # casse la normalisation sur laquelle repose tout le reste : il se refuse d'emblée.
        raise CheminRefuse(
            "Ce chemin est écrit en notation périphérique (\\\\?\\ ou \\\\.\\). Je ne sais pas le "
            "vérifier de façon fiable, donc je ne travaille pas dedans. Donne-moi le chemin normal."
        )
    if plat.startswith("\\\\"):
        raise CheminRefuse(
            "Ce dossier est sur un partage réseau. Je n'envoie pas OpenCode travailler ailleurs que "
            "sur cet ordinateur : ce qui s'y passe ne se surveille pas, et ne se répare pas."
        )
    if _LECTEUR_RELATIF.match(chemin):
        # « C:site » n'est pas C:\site : mesuré, ça se résout contre le dossier courant du backend,
        # c'est-à-dire dans le dépôt d'IRIS.
        raise CheminRefuse(
            f"« {chemin} » n'est pas un chemin complet : il désigne un dossier relatif au lecteur, "
            "pas à sa racine. Écris-le en entier, avec la barre après les deux-points."
        )
    try:
        etendu = Path(os.path.expanduser(chemin))
    except Exception:
        raise CheminRefuse(f"« {chemin} » n'est pas un chemin de dossier.") from None
    if not (etendu.is_absolute() or PureWindowsPath(chemin).is_absolute()):
        raise CheminRefuse(
            f"« {chemin} » est un chemin relatif : il dépendrait du dossier depuis lequel je "
            "tourne, et ce n'est pas celui auquel tu penses. Donne-moi le chemin complet."
        )
    try:
        # C'est `resolve()` qui fait le vrai travail : il règle les « .. », la casse (mesuré :
        # .../IRIS/x devient ...\iris\x), les noms courts 8.3 (C:/PROGRA~1 -> C:\Program Files),
        # les liens symboliques ET les jonctions Windows. On ne s'appuie jamais sur `is_symlink()`,
        # qui rend False sur une jonction — mesuré sur « C:\Users\migue\Application Data », qui
        # pointe pourtant vers AppData\Roaming.
        return etendu.resolve()
    except OSError as erreur:
        raise CheminRefuse(f"Je n'arrive pas à vérifier ce chemin : {erreur}") from None


def _sous(cible: Path, racine: Path) -> bool:
    try:
        return cible == racine or cible.is_relative_to(racine)
    except (OSError, ValueError):
        return False


def resoudre_dossier(
    chemin: str,
    racines_autorisees: Iterable[Path | str],
    racines_interdites: Iterable[Path | str] = (),
) -> Path:
    """Rend le dossier RÉSOLU si et seulement s'il est dans le périmètre. Sinon lève `CheminRefuse`.

    Le résultat de cette fonction est le seul chemin utilisé ensuite — jamais la phrase dite par
    Miguel, jamais celle produite par un modèle. On a mesuré qu'ils peuvent désigner deux choses
    différentes ; c'est le résolu qui est approuvé, et c'est lui qui part dans l'empreinte.
    """
    cible = _normaliser(chemin)

    if cible.parent == cible:
        raise CheminRefuse(
            f"« {cible} » est la racine d'un disque. Je n'envoie personne travailler à la racine : "
            "tout l'ordinateur y est."
        )
    if cible == Path.home():
        # Volontairement une égalité, pas un préfixe : ~/Documents/IRIS/site doit rester possible.
        raise CheminRefuse(
            "C'est ton dossier personnel en entier. Un agent lâché là-dedans touche tes documents, "
            "tes clés et tes réglages. Nomme-moi le dossier du projet."
        )

    # La liste noire d'abord : elle prime, même sur un dossier explicitement autorisé.
    for interdit in racines_interdites:
        racine = interdit if isinstance(interdit, Path) else Path(str(interdit))
        if _sous(cible, racine):
            raise CheminRefuse(
                f"Je ne fais pas travailler OpenCode dans « {cible} » : ce dossier est protégé "
                f"({racine}). Il contient soit mes propres réglages et mes clés, soit le système. "
                "OpenCode est déjà venu dans mon backend une fois tout seul ; ça n'arrivera plus "
                "sur ma demande."
            )

    racines = [r if isinstance(r, Path) else Path(str(r)) for r in racines_autorisees]
    if not racines:
        raise CheminRefuse(
            "Tu ne m'as encore autorisé aucun dossier de travail. Tant que tu ne m'en as pas nommé "
            "un, je n'envoie OpenCode nulle part. Dis-moi quel dossier il a le droit de modifier, "
            "et je le retiendrai."
        )
    if not any(_sous(cible, racine) for racine in racines):
        liste = ", ".join(str(r) for r in racines[:4])
        raise CheminRefuse(
            f"« {cible} » n'est pas dans les dossiers que tu m'as autorisés ({liste}). "
            "Je n'y envoie pas OpenCode. Si c'est bien là que tu veux travailler, ajoute ce dossier "
            "à la liste, en le disant explicitement."
        )

    # L'existence en dernier, et sans jamais créer : « corrige le bogue dans mon site » sur un
    # chemin mal orthographié doit dire « je ne le trouve pas », pas fabriquer un dossier vide et
    # y lâcher un agent qui inventera un projet entier.
    try:
        if not cible.exists():
            raise CheminRefuse(
                f"Je ne trouve pas « {cible} ». Je ne le crée pas : si le nom est approximatif, "
                "OpenCode travaillerait dans un dossier vide. Vérifie le chemin."
            )
        if not cible.is_dir():
            raise CheminRefuse(f"« {cible} » est un fichier, pas un dossier de travail.")
    except OSError as erreur:
        raise CheminRefuse(f"Je n'arrive pas à lire « {cible} » : {erreur}") from None
    return cible


# --------------------------------------------------------------------------- inventaire du dossier
def inventaire(dossier: Path, max_fichiers: int = MAX_FICHIERS_INVENTAIRE) -> tuple[dict[str, tuple[int, int]], bool]:
    """Photographie du dossier : {chemin relatif: (taille, date de modification)}, et « complet ? ».

    C'est la seule façon honnête de répondre à « qu'est-ce qu'il a modifié ? » quand le dossier
    n'est pas versionné — et c'est le cas courant, pas l'exception : les quatre projets de
    ~/Documents/IRIS ne sont sous git ni les uns ni les autres.

    `.git` est ignoré volontairement : un commit fait bouger des centaines de fichiers internes qui
    ne sont pas « ce qu'OpenCode a modifié ». Le commit lui-même est détecté à part, par le SHA de
    HEAD.
    """
    trouves: dict[str, tuple[int, int]] = {}
    complet = True
    pile = [dossier]
    while pile:
        courant = pile.pop()
        try:
            with os.scandir(courant) as entrees:
                for entree in entrees:
                    if len(trouves) >= max_fichiers:
                        return trouves, False
                    try:
                        # follow_symlinks=False : un lien qui pointe vers le dossier parent
                        # ferait tourner cette boucle jusqu'à la fin des temps.
                        if entree.is_dir(follow_symlinks=False):
                            if entree.name not in DOSSIERS_IGNORES:
                                pile.append(Path(entree.path))
                            continue
                        info = entree.stat(follow_symlinks=False)
                        relatif = Path(entree.path).relative_to(dossier).as_posix()
                        trouves[relatif] = (int(info.st_size), int(info.st_mtime_ns))
                    except (OSError, ValueError):
                        continue
        except OSError:
            complet = False
            continue
    return trouves, complet


def comparer(avant: dict[str, tuple[int, int]], apres: dict[str, tuple[int, int]]) -> dict[str, list[str]]:
    """Ce qui a bougé entre les deux photographies."""
    ajoutes = sorted(set(apres) - set(avant))
    supprimes = sorted(set(avant) - set(apres))
    modifies = sorted(f for f in set(avant) & set(apres) if avant[f] != apres[f])
    return {"ajoutes": ajoutes, "modifies": modifies, "supprimes": supprimes}


def _compter(changements: dict[str, list[str]]) -> int:
    return sum(len(v) for v in changements.values())


def _dire_changements(changements: dict[str, list[str]]) -> str:
    """« 3 fichiers modifiés, 1 ajouté » — la phrase qui se lit à voix haute."""
    morceaux = []
    for cle, mot in (("modifies", "modifié"), ("ajoutes", "ajouté"), ("supprimes", "supprimé")):
        nombre = len(changements.get(cle) or [])
        if nombre:
            morceaux.append(f"{nombre} fichier{'s' if nombre > 1 else ''} {mot}{'s' if nombre > 1 else ''}")
    return ", ".join(morceaux)


# --------------------------------------------------------------------------- le chantier
def _dossier_court(dossier: Path) -> str:
    """Les deux derniers segments : « IRIS\\site-flowcare ». Assez pour reconnaître, assez court pour être dit."""
    parties = dossier.parts
    return str(Path(*parties[-2:])) if len(parties) > 2 else str(dossier)


@dataclass(frozen=True)
class Chantier:
    """Un travail préparé, mais NON lancé. C'est ce qu'IRIS fait relire avant de demander l'accord.

    Gelé, et son empreinte calculée à la construction puis revérifiée au moment d'agir : ce qui a
    été approuvé est exactement ce qui part. Le champ qui compte le plus dans cette empreinte est
    `dossier` — le chemin RÉSOLU. Un accord donné pour un dossier ne vaut pas pour un autre.
    """

    genre: str
    dossier: Path  # toujours le chemin résolu, jamais la phrase dite
    consigne: str
    duree_max: float = DUREE_MAX_DEFAUT
    sous_git: bool = False
    arbre_propre: bool = False
    tete_git: str = ""  # SHA de HEAD avant l'intervention, pour savoir où revenir
    identifiant: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    empreinte: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "empreinte", self.calculer_empreinte())

    def calculer_empreinte(self) -> str:
        parts = [
            self.genre,
            str(self.dossier),
            self.consigne,
            f"{self.duree_max:.0f}",
            "git" if self.sous_git else "sans-git",
            "propre" if self.arbre_propre else "sale",
        ]
        return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()

    @property
    def minutes(self) -> int:
        return max(1, int(round(self.duree_max / 60)))

    def titre(self) -> str:
        """Le titre nomme le DOSSIER, parce que c'est ce qui se vérifie d'abord et d'un coup d'œil."""
        return f"Envoyer OpenCode {GENRES.get(self.genre, 'travailler')} dans {_dossier_court(self.dossier)}"

    def phrase_du_filet(self) -> str:
        """Ce qu'on pourra défaire, dit franchement — c'est ce qui décide d'un oui ou d'un non."""
        if not self.sous_git:
            return (
                "Ce dossier n'est pas sous git : je noterai tout ce qu'il touche, mais je ne "
                "pourrai pas tout remettre comme avant."
            )
        if not self.arbre_propre:
            return (
                "Ce dossier est sous git, mais tu as déjà des modifications non enregistrées : si "
                "je dois revenir en arrière, je ne saurai plus distinguer ton travail du sien. "
                "Enregistre d'abord, ce serait plus sûr."
            )
        return "Ce dossier est sous git et tout est enregistré : revenir en arrière restera possible."

    def apercu(self) -> str:
        """Le détail affiché. Rien d'abrégé, et surtout pas la limite de ce que je sais garantir."""
        return "\n".join([
            f"Dossier : {self.dossier}",
            f"Consigne : {self.consigne}",
            "",
            f"Il pourra modifier les fichiers et lancer des commandes dans ce dossier, "
            f"pendant {self.minutes} minutes au plus.",
            self.phrase_du_filet(),
            EXPLICATION_SURVEILLANCE,
        ])

    def pour_la_voix(self) -> str:
        return (
            f"J'envoie OpenCode {GENRES.get(self.genre, 'travailler')} dans "
            f"{_dossier_court(self.dossier)}. {self.phrase_du_filet()}"
        )

    def en_dict(self) -> dict:
        return {
            "id": self.identifiant,
            "genre": self.genre,
            "dossier": str(self.dossier),
            "consigne": self.consigne,
            "duree_max_s": self.duree_max,
            "sous_git": self.sous_git,
            "arbre_propre": self.arbre_propre,
            "tete_git": self.tete_git,
            "empreinte": self.empreinte,
        }


# --------------------------------------------------------------------------- autorisation
_SCEAU = object()  # jeton privé au module : seule `Contremaitre.demander_accord` le détient


class Autorisation:
    """La preuve qu'un humain a dit oui à CE chantier-là, dans CE dossier-là, il y a moins de 5 min.

    Impossible à fabriquer depuis l'extérieur : le constructeur exige `_SCEAU`. C'est ce qui rend
    une délégation non confirmée structurellement impossible plutôt que simplement déconseillée.
    """

    __slots__ = ("chantier", "empreinte", "_accorde_a", "_consomme")

    def __init__(self, chantier: Chantier, sceau: Any) -> None:
        if sceau is not _SCEAU:
            raise AutorisationInvalide(
                "Une autorisation ne se fabrique pas : elle s'obtient par "
                "Contremaitre.demander_accord(), qui attend la réponse de l'utilisateur."
            )
        self.chantier = chantier
        self.empreinte = chantier.empreinte
        self._accorde_a = time.monotonic()
        self._consomme = False

    @property
    def perimee(self) -> bool:
        return (time.monotonic() - self._accorde_a) > DUREE_ACCORD

    @property
    def utilisable(self) -> bool:
        return not self._consomme and not self.perimee and self.empreinte == self.chantier.calculer_empreinte()

    def consommer(self) -> Chantier:
        """Rend le chantier approuvé, une seule fois. Toute anomalie lève au lieu de lancer quoi que ce soit."""
        if self._consomme:
            raise AutorisationInvalide(
                "Cet accord a déjà servi. Pour relancer OpenCode, il faut le confirmer à nouveau."
            )
        if self.perimee:
            raise AutorisationInvalide(
                "L'accord a plus de cinq minutes. Je préfère te redemander avant d'envoyer OpenCode."
            )
        if self.empreinte != self.chantier.calculer_empreinte():
            raise AutorisationInvalide(
                "Le travail a changé depuis que tu l'as approuvé — le dossier, la consigne ou la "
                "durée. Je ne lance rien que tu n'as pas relu."
            )
        self._consomme = True
        return self.chantier


# --------------------------------------------------------------------------- politique imposée
def politique_iris() -> dict:
    """La configuration qu'IRIS impose à OpenCode le temps d'un lancement.

    Elle passe par la variable d'environnement OPENCODE_CONFIG_CONTENT — c'est ainsi que le SDK
    officiel la transmet — et JAMAIS par le fichier `~/.config/opencode/opencode.jsonc` : les
    réglages de Miguel lui appartiennent, IRIS n'y écrit pas.

    `share: "disabled"` avant tout le reste : le défaut d'OpenCode permet de publier une session,
    et le code d'un client n'a pas à devenir une page web.

    Pourquoi `edit` et `bash` sont sur "allow" et non sur "ask" : en lancement unique, un « ask »
    attend une réponse sur l'API HTTP à laquelle nous ne sommes pas connectés — l'agent resterait
    figé jusqu'au délai, ce qui est exactement la panne qu'on cherche à éviter. L'accord humain a
    déjà été donné, et il portait sur le dossier. Le jour où IRIS pilotera `opencode serve` et
    saura router `permission.updated` vers le ConfirmFn existant, ces deux valeurs repasseront
    à "ask" et chaque écriture sera demandée.
    """
    return {
        "share": "disabled",
        "permission": {
            "edit": "allow",
            "bash": "allow",
            # Un agent qui va chercher sur le web peut aussi y envoyer. Rien ne le justifie ici.
            "webfetch": "deny",
            "external_directory": "deny",
        },
    }


# --------------------------------------------------------------------------- le service
class Contremaitre:
    """Le service. Quatre gestes : dire s'il est utilisable, préparer, faire confirmer, rendre compte.

    `lanceur` et `chercheur` existent pour les tests : aucun test de ce module ne lance de
    processus — ni OpenCode, ni git — et aucun ne dépend de ce qui est installé sur la machine.
    """

    def __init__(
        self,
        settings: Any,
        lanceur: Lanceur | None = None,
        chercheur: Callable[[], str] | None = None,
        registre: Any = None,  # ConsentGate : trace la délégation ET le refus
        hub: Any = None,  # EventHub : prévient le bureau qu'un agent travaille
        horloge: Callable[[], float] = time.monotonic,
        racines_interdites: Iterable[Path | str] | None = None,
    ):
        self.settings = settings
        self._lanceur = lanceur or _lanceur_par_defaut
        self._chercheur = chercheur or trouver_opencode
        self.registre = registre
        self.hub = hub
        self._horloge = horloge
        # Injectable pour la même raison que le lanceur : sous Windows, pytest crée ses dossiers
        # temporaires dans ~/AppData/Local/Temp, c'est-à-dire à l'intérieur d'une des racines
        # interdites par défaut. Un test ne doit pas dépendre de l'endroit où le système range ses
        # fichiers jetables. En production, on ne passe rien et la liste du module s'applique.
        self._interdits = list(racines_interdites) if racines_interdites is not None else None

    # ------------------------------------------------------------------ état
    @property
    def _user(self) -> Any:
        return getattr(self.settings, "user", None)

    @property
    def _section(self) -> Any:
        return getattr(self._user, "opencode", None)  # absente tant que config.py n'a pas la section

    @property
    def mode_local(self) -> bool:
        return bool(getattr(self._user, "local_only", False))

    @property
    def chemin_binaire(self) -> str:
        """Toujours redemandé : Miguel peut installer OpenCode pendant qu'IRIS tourne."""
        try:
            return self._chercheur() or ""
        except Exception as exc:  # un chercheur injecté peut se tromper ; ce n'est pas une panne d'IRIS
            log.warning("Recherche du binaire OpenCode impossible : %s", exc)
            return ""

    @property
    def installe(self) -> bool:
        """Y a-t-il un binaire sur le disque ? Constaté à chaque appel, jamais mémorisé."""
        return bool(self.chemin_binaire)

    @property
    def disponible(self) -> bool:
        """Utilisable ici et maintenant. Faux par construction tant qu'aucun binaire n'existe.

        Ce n'est pas un drapeau qu'on peut oublier de mettre à jour : c'est exactement la négation
        de `pourquoi_pas_pret()`, donc les deux ne peuvent pas se contredire.
        """
        return not self.pourquoi_pas_pret()

    @property
    def _actif(self) -> bool:
        section = self._section
        if section is None:
            return True
        valeur = section.get("actif", True) if isinstance(section, dict) else getattr(section, "actif", True)
        return bool(valeur) if valeur is not None else True

    def duree_max(self) -> float:
        section = self._section
        brut = None
        if section is not None:
            brut = section.get("duree_max_minutes") if isinstance(section, dict) else getattr(section, "duree_max_minutes", None)
        try:
            secondes = float(brut) * 60 if brut else DUREE_MAX_DEFAUT
        except (TypeError, ValueError):
            secondes = DUREE_MAX_DEFAUT
        return min(DUREE_MAX_PLAFOND, max(DUREE_MAX_PLANCHER, secondes))

    def racines_interdites(self) -> list[Path]:
        """La liste noire : celle du module (sauf si on en a injecté une), plus le dossier de données.

        Le dossier de données s'y ajoute TOUJOURS, même quand la liste est injectée : c'est là que
        vivent `.env`, `settings.json` et `iris.db`. Un agent envoyé « corriger mon site » qui lit
        `.env` lit aussi les clés ElevenLabs et de licence.
        """
        source = racines_interdites_par_defaut() if self._interdits is None else self._interdits
        interdits: list[Path] = []
        for brut in source:
            try:
                interdits.append(Path(str(brut)).expanduser().resolve())
            except OSError:
                continue
        donnees = getattr(self.settings, "data_dir", None)
        if donnees:
            try:
                interdits.append(Path(donnees).expanduser().resolve())
            except OSError:
                pass
        return list(dict.fromkeys(interdits))

    def racines(self) -> list[Path]:
        """Les dossiers que Miguel a explicitement autorisés. Vide par défaut, et c'est voulu.

        Tant qu'aucun dossier n'est nommé, IRIS ne délègue rien. Le périmètre ne se déduit jamais
        de la phrase dite : « corrige mon site » ne désigne pas un dossier, il désigne une idée.
        """
        section = self._section
        brut: Any = None
        if section is not None:
            brut = section.get("racines") if isinstance(section, dict) else getattr(section, "racines", None)
        if not brut:
            brut = getattr(self._user, "opencode_racines", None)
        racines: list[Path] = []
        for entree in brut or []:
            try:
                racines.append(_normaliser(str(entree)))
            except CheminRefuse as refus:
                # Une racine mal écrite dans settings.json ne doit pas empêcher les autres de
                # fonctionner, ni faire planter l'affichage des réglages.
                log.warning("Racine OpenCode ignorée (%s) : %s", entree, refus)
        return list(dict.fromkeys(racines))

    def pourquoi_pas_pret(self) -> str:
        """La phrase que la voix dit quand rien n'est possible. Vide si le service est prêt.

        C'est aujourd'hui la sortie normale de ce module : elle est écrite pour être lue à voix
        haute par quelqu'un qui vient de demander de corriger un bogue, pas pour un journal.
        """
        if not self._actif:
            return (
                "La délégation à OpenCode est désactivée dans les réglages. Réactive-la si tu veux "
                "que je confie du travail de programmation."
            )
        if not self.chemin_binaire:
            return MODE_EMPLOI
        if self.mode_local:
            return (
                "Le mode local est actif. OpenCode envoie ton code source au fournisseur d'IA qu'il "
                "utilise, et c'est exactement ce que le mode local interdit. Je ne le lance pas."
            )
        if not self.racines():
            return (
                "OpenCode est bien installé, mais tu ne m'as autorisé aucun dossier de travail. "
                "Dis-moi dans quel dossier il a le droit de modifier des fichiers — je ne le "
                "déduis pas de la conversation, je veux que tu me le nommes."
            )
        return ""

    def etat(self) -> dict:
        """État affichable. Aucune exception ne sort d'ici, même si tout est cassé."""
        binaire = self.chemin_binaire
        return {
            "installe": bool(binaire),
            "chemin": binaire,
            "disponible": self.disponible,
            "actif": self._actif,
            "mode_local": self.mode_local,
            "racines": [str(r) for r in self.racines()],
            "duree_max_minutes": int(self.duree_max() // 60),
            "politique": politique_iris(),
            "explication": self.pourquoi_pas_pret(),
        }

    # ------------------------------------------------------------------ git
    def _git(self, dossier: Path, *args: str) -> Resultat:
        try:
            return self._lanceur(["git", *args], dossier, DELAI_GIT, None)
        except Exception as exc:  # git absent, PATH cassé : ce n'est pas une raison de ne rien faire
            log.warning("git indisponible dans %s : %s", dossier, exc)
            return Resultat(code=-1, introuvable=True)

    def _etat_git(self, dossier: Path) -> tuple[bool, bool, str]:
        """(sous git ?, arbre propre ?, SHA de HEAD). Jamais d'exception : le pire cas est « pas de git »."""
        statut = self._git(dossier, "status", "--porcelain")
        if statut.introuvable or statut.code != 0:
            return False, False, ""
        propre = not (statut.sortie or "").strip()
        tete = self._git(dossier, "rev-parse", "HEAD")
        sha = (tete.sortie or "").strip().splitlines()[0].strip() if tete.code == 0 and tete.sortie else ""
        return True, propre, sha[:40]

    # ------------------------------------------------------------------ préparation
    def _garde(self) -> None:
        """Tout ce qui doit être vrai avant même de préparer. Lève une phrase française, sinon rien."""
        raison = self.pourquoi_pas_pret()
        if raison:
            raise OpenCodeIndisponible(raison)

    def preparer(self, genre: str, dossier: str, consigne: str, duree_max: float | None = None) -> Chantier:
        """Construit le chantier et ne lance RIEN d'autre que la lecture de l'état git du dossier."""
        self._garde()
        consigne_propre = " ".join((consigne or "").split())
        if not consigne_propre:
            raise ErreurOpenCode(
                "Tu ne m'as pas dit quoi corriger. Un agent envoyé sans consigne précise fait ce "
                "qu'il croit utile, et c'est comme ça qu'un site marche moins bien après."
            )
        cible = resoudre_dossier(dossier, self.racines(), self.racines_interdites())
        sous_git, propre, tete = self._etat_git(cible)
        duree = self.duree_max() if duree_max is None else min(DUREE_MAX_PLAFOND, max(DUREE_MAX_PLANCHER, float(duree_max)))
        propose = (genre or "").strip().lower()
        return Chantier(
            genre=propose if propose in GENRES else GENRE_DEFAUT,
            dossier=cible,
            consigne=consigne_propre,
            duree_max=duree,
            sous_git=sous_git,
            arbre_propre=propre,
            tete_git=tete,
        )

    # ------------------------------------------------------------------ accord
    async def demander_accord(self, chantier: Chantier, confirmer: ConfirmFn) -> Autorisation | None:
        """Seule fabrique d'`Autorisation` du programme. Rend None si l'utilisateur n'a pas dit oui.

        `confirmer` est la fonction de ToolContext : elle publie la demande à l'écran et rend False
        si personne ne répond dans les 180 secondes. Un silence vaut donc un refus.
        """
        if confirmer is None:
            raise AutorisationInvalide("Aucun moyen de te demander confirmation : je ne lance rien.")
        approuve = bool(await confirmer(chantier.titre(), chantier.apercu()))
        if not approuve:
            # Le refus est tracé autant que l'accord : un journal qui ne montre que les succès ne
            # prouve rien.
            self._tracer("opencode_refus", chantier)
            log.info("OpenCode : délégation non confirmée pour %s", chantier.dossier)
            return None
        return Autorisation(chantier, _SCEAU)

    # ------------------------------------------------------------------ action
    def executer(self, autorisation: Autorisation) -> dict:
        """Lance OpenCode sur le chantier approuvé. N'accepte QUE des `Autorisation`."""
        if not isinstance(autorisation, Autorisation):
            raise AutorisationInvalide(
                "Je ne lance rien : ça n'a pas été confirmé. Demande-moi de te relire ce que je "
                "compte confier à OpenCode, puis confirme."
            )
        # Vérifié AVANT de consommer l'accord : un refus de périmètre ne doit pas brûler un oui.
        # Et revérifié ICI, pas seulement à la préparation : entre l'accord et l'action, la liste
        # des dossiers autorisés a pu changer, ou le dossier disparaître. C'est le défaut trouvé
        # dans telephonie.py, transposé : un accord ne vaut que pour ce qu'il nommait.
        self._garde()
        chantier = autorisation.chantier
        resolu = resoudre_dossier(str(chantier.dossier), self.racines(), self.racines_interdites())
        if resolu != chantier.dossier:
            raise CheminRefuse(
                f"Le dossier approuvé ({chantier.dossier}) ne désigne plus le même endroit "
                f"({resolu}). Je ne lance rien."
            )
        chantier = autorisation.consommer()

        journal = self._ouvrir_journal(chantier)  # écrit AVANT le lancement : si IRIS meurt, la trace reste
        self._tracer("opencode_delegue", chantier)
        self._publier("opencode.debut", chantier=chantier.en_dict())

        avant, complet = inventaire(chantier.dossier)
        debut = self._horloge()
        try:
            resultat = self._lanceur(
                self._argv(chantier),
                chantier.dossier,
                chantier.duree_max,
                {"OPENCODE_CONFIG_CONTENT": json.dumps(politique_iris(), ensure_ascii=False)},
            )
        except Exception as erreur:  # OpenCode effacé entre-temps, droits refusés
            log.error("Lancement d'OpenCode impossible : %s", erreur)
            resultat = Resultat(code=-1, sortie=str(erreur), introuvable=True)
        duree = max(0.0, self._horloge() - debut)
        apres, complet_apres = inventaire(chantier.dossier)
        changements = comparer(avant, apres)
        commit = self._commit_ajoute(chantier)

        compte_rendu = self._rediger(chantier, resultat, changements, duree, commit,
                                     partiel=not (complet and complet_apres))
        self._fermer_journal(journal, compte_rendu)
        compte_rendu["journal"] = str(journal) if journal else ""
        self._tracer("opencode_termine", chantier, detail_supplementaire=_dire_changements(changements) or "aucun changement")
        self._publier("opencode.fin", **{k: compte_rendu[k] for k in ("ok", "termine", "expire", "modifie", "message")})
        return compte_rendu

    def _argv(self, chantier: Chantier) -> list[str]:
        """La ligne de commande.

        Le dossier est épinglé par le CWD du processus, pas par une option : le nom exact de
        l'option (`--directory` ? `--cwd` ?) a été lu dans le SDK, jamais vérifié contre un binaire
        — il n'y en a aucun sur cette machine. Le CWD, lui, ne dépend d'aucun contrat. Le jour où
        OpenCode sera installé, c'est cette méthode qu'il faudra confronter à `opencode --help`.
        """
        return [self.chemin_binaire, "run", chantier.consigne]

    def _commit_ajoute(self, chantier: Chantier) -> bool:
        """OpenCode a-t-il enregistré un commit ? L'inventaire ignore .git, il ne le verrait pas."""
        if not chantier.sous_git or not chantier.tete_git:
            return False
        tete = self._git(chantier.dossier, "rev-parse", "HEAD")
        if tete.code != 0 or not tete.sortie:
            return False
        return tete.sortie.strip().splitlines()[0].strip()[:40] != chantier.tete_git

    # ------------------------------------------------------------------ compte rendu
    def _rediger(self, chantier: Chantier, resultat: Resultat, changements: dict[str, list[str]],
                 duree: float, commit: bool, partiel: bool) -> dict:
        """Transforme un code de retour en phrase honnête.

        Trois issues, trois phrases différentes, et aucune ne doit pouvoir passer pour une autre :
        il a fini, il a échoué, il n'avait pas fini. Et dans les trois cas, ce qui a changé sur le
        disque a changé — un échec n'annule rien.
        """
        nombre = _compter(changements)
        modifie = nombre > 0 or commit
        resume = _dire_changements(changements)
        ou = _dossier_court(chantier.dossier)
        base = {
            "ok": False,
            "termine": False,
            "expire": bool(resultat.expire),
            "modifie": modifie,
            "dossier": str(chantier.dossier),
            "id": chantier.identifiant,
            "duree_s": round(duree, 1),
            "changements": {cle: valeurs[:MAX_FICHIERS_NOMMES] for cle, valeurs in changements.items()},
            "nb_changements": nombre,
            "commit": commit,
            "inventaire_partiel": partiel,
            "sortie": (resultat.sortie or "")[-2000:],
        }

        if resultat.introuvable:
            base["message"] = (
                "Je n'ai pas réussi à lancer OpenCode : le programme a disparu entre le moment où "
                "tu as dit oui et maintenant. "
            ) + ("Rien n'a été fait." if not modifie else f"Et pourtant quelque chose a bougé : {resume}.")
            return base

        if resultat.expire:
            # Un délai dépassé n'est PAS un échec, et surtout pas une annulation. Ce qui est écrit
            # est écrit. Le dire autrement laisserait Miguel croire son dossier intact.
            suite = (
                f"Il avait déjà touché à quelque chose : {resume}. Rien n'a été annulé."
                if modifie else "Il n'avait encore rien modifié."
            )
            base["message"] = (
                f"J'ai arrêté OpenCode au bout de {chantier.minutes} minutes : il n'avait pas fini. "
                f"{suite}"
            )
            return base

        if resultat.code != 0:
            detail = _premieres_lignes(resultat.sortie)
            suite = (
                f" Attention : il avait quand même modifié des choses ({resume}), et ça reste en place."
                if modifie else f" Rien n'a été modifié dans {ou}."
            )
            base["message"] = f"OpenCode s'est arrêté sur une erreur (code {resultat.code}).{suite}" + (
                f" Il a dit : {detail}" if detail else ""
            )
            return base

        base["termine"] = True
        base["ok"] = True
        if not modifie:
            # Le compte rendu le plus facile à maquiller, donc celui qu'on écrit le plus nettement.
            base["message"] = (
                f"OpenCode a terminé sans rien modifier dans {ou}. Ou bien il n'y avait rien à "
                "changer, ou bien il n'a pas trouvé quoi faire avec ma consigne."
            )
            if partiel:
                base["message"] += " (Le dossier est trop gros pour que je l'inspecte en entier.)"
            return base

        phrase = f"C'est fait : {resume} dans {ou}."
        if commit:
            phrase += " Il a aussi enregistré un commit."
        if chantier.sous_git:
            phrase += " Tu peux voir le détail avec git, ou me demander de revenir en arrière."
        else:
            phrase += " Ce dossier n'est pas sous git : j'ai gardé la liste de ce qu'il a touché."
        if partiel:
            phrase += " (Le dossier est trop gros pour que je l'inspecte en entier : il peut y avoir plus.)"
        base["message"] = phrase
        return base

    # ------------------------------------------------------------------ chemin complet
    async def deleguer_apres_accord(
        self,
        genre: str,
        dossier: str,
        consigne: str,
        confirmer: ConfirmFn,
        source: str = "text",
    ) -> dict:
        """Le chemin qu'appellera l'outil : préparer, faire confirmer, lancer, rendre compte.

        Aucun raccourci n'est possible : sans accord, il n'y a rien à passer à `executer()`.
        """
        chantier = self.preparer(genre, dossier, consigne)
        if (source or "").lower() in ("voice", "voix_telephone"):
            # Aucune confirmation ne passe par la voix aujourd'hui : rien dans backend/iris/voice/
            # n'écoute « chat.confirm ». Ouvrir la modale ici, ce serait faire attendre Miguel
            # 180 secondes devant un écran qu'il ne regarde pas, pour finir sur un « refusé »
            # silencieux. On le dit tout de suite, à voix haute, où il l'entendra.
            self._tracer("opencode_refus", chantier, detail_supplementaire="demandé à la voix")
            return {
                "ok": False,
                "termine": False,
                "expire": False,
                "modifie": False,
                "dossier": str(chantier.dossier),
                "message": (
                    f"Je peux confier ça à OpenCode dans {_dossier_court(chantier.dossier)}, mais "
                    "il faut que tu valides à l'écran : il va modifier des fichiers, et je ne "
                    "demande pas ce genre d'accord à la voix. Ouvre ma fenêtre et redemande-le-moi là."
                ),
            }
        accord = await self.demander_accord(chantier, confirmer)
        if accord is None:
            return {
                "ok": False,
                "termine": False,
                "expire": False,
                "modifie": False,
                "dossier": str(chantier.dossier),
                "message": "Je n'ai rien lancé : ça n'a pas été confirmé.",
            }
        # OpenCode travaille plusieurs minutes : hors de la boucle, sinon la voix se fige tout ce temps.
        return await asyncio.to_thread(self.executer, accord)

    # ------------------------------------------------------------------ traces
    def _dossier_journal(self) -> Path | None:
        donnees = getattr(self.settings, "data_dir", None)
        if not donnees:
            return None
        try:
            racine = Path(donnees) / "opencode"
            racine.mkdir(parents=True, exist_ok=True)
            return racine
        except OSError as exc:
            log.warning("Journal des interventions indisponible : %s", exc)
            return None

    def _ouvrir_journal(self, chantier: Chantier) -> Path | None:
        """Un dossier par intervention, écrit AVANT le lancement.

        Si IRIS est fermée pendant qu'OpenCode travaille, il doit rester sur le disque de quoi
        répondre à « qu'est-ce qu'elle a lancé, où, et pourquoi ? ».
        """
        racine = self._dossier_journal()
        if racine is None:
            return None
        try:
            dossier = racine / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{chantier.identifiant}"
            dossier.mkdir(parents=True, exist_ok=True)
            (dossier / "chantier.json").write_text(
                json.dumps(chantier.en_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return dossier
        except OSError as exc:
            log.warning("Impossible d'ouvrir le journal d'intervention : %s", exc)
            return None

    def _fermer_journal(self, dossier: Path | None, compte_rendu: dict) -> None:
        if dossier is None:
            return
        try:
            (dossier / "compte-rendu.json").write_text(
                json.dumps(compte_rendu, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:  # une trace qui échoue ne doit pas empêcher IRIS de répondre
            log.warning("Compte rendu non écrit dans %s : %s", dossier, exc)

    def _tracer(self, evenement: str, chantier: Chantier, detail_supplementaire: str = "") -> None:
        """Inscrit au registre chaîné. La CONSIGNE n'y va pas en entier, le dossier si.

        Le registre s'exporte en CSV et se lit à l'écran ; il est tronqué à 500 caractères et n'est
        pas chiffré. Ce qu'il doit prouver, c'est où IRIS a envoyé un agent, et quand.
        """
        if self.registre is None:
            return
        detail = f"{chantier.genre} dans {chantier.dossier}"
        if detail_supplementaire:
            detail += f" — {detail_supplementaire}"
        try:
            self.registre.log(evenement, agent="opencode", detail=detail)
        except Exception as exc:
            log.warning("Registre indisponible pour %s : %s", evenement, exc)

    def _publier(self, type_: str, **donnees: Any) -> None:
        if self.hub is None:
            return
        try:
            self.hub.publish(type_, **donnees)
        except Exception as exc:
            log.warning("Publication %s impossible : %s", type_, exc)


def _premieres_lignes(sortie: str, combien: int = 3) -> str:
    lignes = [ligne.strip() for ligne in (sortie or "").strip().splitlines() if ligne.strip()]
    return " / ".join(lignes[-combien:])[:400]
