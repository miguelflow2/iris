"""Envoi de courriels par IRIS.

Un courriel parti ne se rattrape pas. C'est la seule action d'IRIS qui sorte de la machine, qui
soit adressée à un être humain, et qui n'ait aucun bouton « annuler ». Tout ce module est écrit
autour de cette phrase.

POURQUOI UNE CLASSE `Autorisation` PLUTÔT QU'UN DRAPEAU `confirme=True`
----------------------------------------------------------------------
Un booléen se transmet par erreur. Il suffit d'un appelant distrait, d'un `**kwargs` recopié,
d'une valeur par défaut inversée un jour de refonte, et le message part. Le drapeau ne porte
aucune trace de QUI a dit oui, ni à QUOI, ni QUAND — il dit seulement « quelqu'un, quelque part,
a dû vérifier ». Ce n'est pas une garantie, c'est une convention entre développeurs, et une
convention finit toujours par être oubliée.

Ici, `Postier.envoyer()` n'accepte pas un message : il accepte une `Autorisation`. Et une
`Autorisation` ne peut pas être fabriquée par un appelant, même bien intentionné : son
constructeur exige un sceau privé au module (`_SCEAU`), que seule `Postier.demander_accord()`
possède — et `demander_accord()` ne le donne qu'après qu'un humain a répondu oui. Écrire un envoi
non confirmé ne demande donc pas de la discipline : cela demande de modifier ce fichier.

L'autorisation porte en plus trois garanties qu'un booléen ne peut pas porter :
- elle est liée à l'empreinte du message approuvé, donc elle ne peut pas servir à en envoyer un autre ;
- elle ne sert qu'une fois, donc un `retry` ne double pas le message ;
- elle expire, parce qu'un accord donné il y a une heure ne dit rien de l'intention d'aujourd'hui.

Elle est consommée AVANT la connexion SMTP, jamais après : si l'envoi échoue à mi-chemin, on ne
sait pas si le serveur a déjà accepté le message. Redemander l'accord coûte une phrase ; envoyer
deux fois coûte une explication au destinataire.

CE QUI DIFFÈRE DU `Facteur` DU SERVEUR DE LICENCES
-------------------------------------------------
`server/licences/courriel.py` avale ses échecs : il dépose un `.eml` et continue, parce qu'un
abonnement payé doit être créé même si le courriel ne part pas. Pour une assistante, ce serait un
mensonge. Ici un échec lève `EnvoiEchoue` avec un message qui dit quoi faire. IRIS doit pouvoir
dire « je n'ai pas réussi à l'envoyer », jamais « c'est envoyé » quand le message dort quelque part.

Le mot de passe ne transite ni par `settings.json`, ni par une variable d'environnement, ni par un
journal : il vit dans `security/secrets.py` (trousseau Windows, ou fichier chiffré AES-256-GCM).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import smtplib
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid, parseaddr
from typing import Any, Awaitable, Callable, Iterable, Sequence

log = logging.getLogger("iris.courriel")

# Clé sous laquelle le coffre range le compte d'envoi : username = adresse, password = mot de
# passe d'application. Même forme que les comptes web, donc rien de neuf à apprendre au coffre.
NOM_COFFRE = "courriel"

DELAI_SMTP = 20  # secondes ; au-delà, c'est un port bloqué, pas un serveur lent
DUREE_ACCORD = 300.0  # un oui vaut cinq minutes : le temps de se raviser sans avoir à tout redicter
MAX_DESTINATAIRES = 20  # garde-fou : un modèle qui hallucine une liste de diffusion ne fait pas d'envoi de masse

# Serveurs SMTP connus, pour n'avoir à demander que l'adresse et le mot de passe. Seul Gmail est
# réellement éprouvé dans ce dépôt (voir server/README.md) ; les autres sont des valeurs d'usage,
# et restent surchargeables par les réglages.
FOURNISSEURS: dict[str, tuple[str, int]] = {
    "gmail.com": ("smtp.gmail.com", 587),
    "googlemail.com": ("smtp.gmail.com", 587),
    "outlook.com": ("smtp-mail.outlook.com", 587),
    "hotmail.com": ("smtp-mail.outlook.com", 587),
    "live.com": ("smtp-mail.outlook.com", 587),
    "yahoo.com": ("smtp.mail.yahoo.com", 587),
    "yahoo.fr": ("smtp.mail.yahoo.com", 587),
    "icloud.com": ("smtp.mail.me.com", 587),
    "me.com": ("smtp.mail.me.com", 587),
}

# Volontairement stricte : pas d'espace, pas de virgule, pas de chevron, un point dans le domaine.
# Une adresse exotique refusée se corrige à la main ; une adresse acceptée à tort part chez un inconnu.
_ADRESSE = re.compile(r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+@[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$")
_CONTROLE = re.compile(r"[\r\n\x00]")

ConfirmFn = Callable[[str, str], Awaitable[bool]]  # (titre, détail) -> approuvé ? — même signature que ToolContext.confirm

MODE_EMPLOI_GMAIL = (
    "Pour Gmail : activez la validation en deux étapes sur le compte, générez un mot de passe "
    "d'application sur myaccount.google.com/apppasswords (16 caractères), puis donnez-le à IRIS. "
    "Le mot de passe habituel du compte Google ne fonctionne plus depuis 2022."
)


# --------------------------------------------------------------------------- erreurs
class ErreurCourriel(Exception):
    """Toute erreur de ce module porte un message en français, destiné à être lu à l'utilisateur."""


class CourrielNonConfigure(ErreurCourriel):
    pass


class AdresseInvalide(ErreurCourriel):
    pass


class AutorisationInvalide(ErreurCourriel):
    """Levée quand on tente d'envoyer sans un accord valide, à jour et non encore utilisé."""


class EnvoiEchoue(ErreurCourriel):
    """L'envoi n'a pas abouti. IRIS doit le dire, jamais prétendre le contraire."""


class ModeLocalActif(ErreurCourriel):
    pass


# --------------------------------------------------------------------------- validation
def _sans_controle(texte: str) -> str:
    """Retire CR/LF et NUL : c'est ce qui permettrait d'injecter un en-tête (un Cci, par exemple)."""
    return _CONTROLE.sub(" ", texte or "").strip()


def valider_adresse(brut: str) -> str:
    """Renvoie l'adresse seule (sans nom d'affichage) ou lève `AdresseInvalide`."""
    brut = (brut or "").strip()
    if not brut:
        raise AdresseInvalide("Adresse de destinataire vide.")
    if _CONTROLE.search(brut):
        raise AdresseInvalide(f"Adresse refusée (retour à la ligne interdit) : {brut!r}")
    # On ne garde que la partie « a@b.c » : un nom d'affichage venu d'un modèle n'a aucune valeur
    # pour l'acheminement, et c'est par lui que passeraient les caractères douteux.
    _nom, adresse = parseaddr(brut)
    adresse = (adresse or "").strip()
    if not adresse or not _ADRESSE.match(adresse) or len(adresse) > 254:
        raise AdresseInvalide(f"« {brut} » n'est pas une adresse de courriel valide.")
    return adresse


def _liste_adresses(valeur: str | Sequence[str] | None) -> tuple[str, ...]:
    """Accepte « a@b.c, d@e.f », une liste, ou rien. Dédoublonne en gardant l'ordre dicté."""
    if valeur is None:
        brutes: Iterable[str] = ()
    elif isinstance(valeur, str):
        brutes = re.split(r"[;,]", valeur)
    else:
        brutes = valeur
    vues: list[str] = []
    for morceau in brutes:
        morceau = (morceau or "").strip()
        if not morceau:
            continue
        adresse = valider_adresse(morceau)
        if adresse.lower() not in [v.lower() for v in vues]:
            vues.append(adresse)
    return tuple(vues)


def _domaine(adresse: str) -> str:
    return adresse.rsplit("@", 1)[-1].lower() if "@" in adresse else ""


def _sans_secret(texte: str, *secrets: str) -> str:
    """Efface les secrets d'un texte destiné à un journal ou à l'écran.

    Le mot de passe n'a aucune raison d'apparaître dans une réponse SMTP, mais un message d'erreur
    finit souvent recopié dans un rapport de bogue ou lu à voix haute. On ne parie pas là-dessus.
    """
    propre = texte or ""
    for secret in secrets:
        secret = (secret or "").strip()
        if len(secret) < 4:
            continue
        for variante in {secret, secret.replace(" ", ""), re.sub(r"\s+", " ", secret)}:
            if variante:
                propre = propre.replace(variante, "•••")
    return propre


# --------------------------------------------------------------------------- brouillon
@dataclass(frozen=True)
class Brouillon:
    """Un message prêt, mais non envoyé. C'est ce qu'IRIS lit à voix haute avant de demander l'accord.

    Gelé (`frozen`) pour que ce qui a été approuvé soit exactement ce qui part : l'empreinte est
    calculée à la construction et revérifiée au moment de l'envoi.
    """

    expediteur: str
    destinataires: tuple[str, ...]
    sujet: str
    corps: str
    cc: tuple[str, ...] = ()
    empreinte: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "empreinte", self.calculer_empreinte())

    def calculer_empreinte(self) -> str:
        brut = "\x1f".join(
            [self.expediteur, ",".join(self.destinataires), ",".join(self.cc), self.sujet, self.corps]
        )
        return hashlib.sha256(brut.encode("utf-8")).hexdigest()

    @property
    def tous_les_destinataires(self) -> tuple[str, ...]:
        return self.destinataires + self.cc

    def titre(self) -> str:
        """Titre de la fenêtre de confirmation : il doit contenir à QUI, c'est ce qui se vérifie d'abord."""
        qui = ", ".join(self.destinataires)
        return f"Envoyer un courriel à {qui}"

    def apercu(self) -> str:
        """Le message entier, tel qu'il partira. Rien d'abrégé : on ne confirme pas un résumé."""
        lignes = [f"De : {self.expediteur}", f"À : {', '.join(self.destinataires)}"]
        if self.cc:
            lignes.append(f"Copie : {', '.join(self.cc)}")
        lignes += [f"Objet : {self.sujet}", "", self.corps]
        return "\n".join(lignes)

    def pour_la_voix(self) -> str:
        """Version lisible à voix haute, pour qu'IRIS relise le brouillon avant de demander l'accord."""
        qui = " et ".join(self.destinataires)
        copie = f", avec une copie à {' et '.join(self.cc)}" if self.cc else ""
        return f"Courriel à {qui}{copie}. Objet : {self.sujet}. Message : {self.corps}"

    def message(self) -> EmailMessage:
        m = EmailMessage()
        m["From"] = self.expediteur
        m["To"] = ", ".join(self.destinataires)
        if self.cc:
            m["Cc"] = ", ".join(self.cc)
        m["Subject"] = self.sujet
        m["Date"] = formatdate(localtime=True)
        # Domaine explicite : sans lui, make_msgid met le nom de la machine de Miguel dans un
        # en-tête que tous les destinataires liront.
        m["Message-ID"] = make_msgid(domain=_domaine(parseaddr(self.expediteur)[1]) or "localhost")
        m.set_content(self.corps)
        return m

    def eml(self) -> str:
        """Le message brut, pour l'afficher ou l'archiver sans rien envoyer."""
        return self.message().as_string()


# --------------------------------------------------------------------------- autorisation
_SCEAU = object()  # jeton privé au module : seule `Postier.demander_accord` le détient


class Autorisation:
    """La preuve qu'un humain a dit oui à CE message-là, il y a moins de cinq minutes.

    Impossible à fabriquer depuis l'extérieur du module : le constructeur exige `_SCEAU`. C'est ce
    qui rend un envoi non confirmé structurellement impossible plutôt que simplement déconseillé.
    """

    __slots__ = ("brouillon", "empreinte", "_accorde_a", "_consomme")

    def __init__(self, brouillon: Brouillon, sceau: Any) -> None:
        if sceau is not _SCEAU:
            raise AutorisationInvalide(
                "Une autorisation d'envoi ne se fabrique pas : elle s'obtient par "
                "Postier.demander_accord(), qui attend la réponse de l'utilisateur."
            )
        self.brouillon = brouillon
        self.empreinte = brouillon.empreinte
        self._accorde_a = time.monotonic()
        self._consomme = False

    @property
    def perimee(self) -> bool:
        return (time.monotonic() - self._accorde_a) > DUREE_ACCORD

    @property
    def utilisable(self) -> bool:
        return not self._consomme and not self.perimee and self.empreinte == self.brouillon.calculer_empreinte()

    def consommer(self) -> Brouillon:
        """Rend le brouillon approuvé, une seule fois. Toute anomalie lève au lieu d'envoyer."""
        if self._consomme:
            raise AutorisationInvalide(
                "Cet accord a déjà servi à envoyer ce message. Pour le renvoyer, il faut le confirmer à nouveau."
            )
        if self.perimee:
            raise AutorisationInvalide(
                "L'accord a plus de cinq minutes. Je préfère te redemander avant d'envoyer."
            )
        if self.empreinte != self.brouillon.calculer_empreinte():
            raise AutorisationInvalide(
                "Le message a changé depuis que tu l'as approuvé. Je n'envoie pas un texte que tu n'as pas relu."
            )
        self._consomme = True
        return self.brouillon


# --------------------------------------------------------------------------- réglages
@dataclass
class ReglagesCourriel:
    """Réglages non secrets. Le mot de passe n'est PAS ici : il ne doit jamais toucher settings.json."""

    smtp_hote: str = ""
    smtp_port: int = 0
    tls: bool = True
    nom_expediteur: str = ""
    signature: str = ""


def _champ(source: Any, nom: str, defaut: Any) -> Any:
    """Lit un champ que la source soit un modèle pydantic, un dataclass ou un dict."""
    if source is None:
        return defaut
    if isinstance(source, dict):
        valeur = source.get(nom, defaut)
    else:
        valeur = getattr(source, nom, defaut)
    return defaut if valeur in (None, "") else valeur


def _fabrique_par_defaut(hote: str, port: int, ssl: bool) -> Any:
    if ssl:
        return smtplib.SMTP_SSL(hote, port, timeout=DELAI_SMTP)
    return smtplib.SMTP(hote, port, timeout=DELAI_SMTP)


# --------------------------------------------------------------------------- service
class Postier:
    """Le service d'envoi. Trois gestes : dire s'il est configuré, préparer, envoyer un accord.

    `fabrique_smtp` existe pour les tests : les tests de ce module ne touchent jamais le réseau.
    """

    def __init__(self, settings: Any, secrets: Any, fabrique_smtp: Callable[[str, int, bool], Any] | None = None):
        self.settings = settings
        self.secrets = secrets
        self._fabrique = fabrique_smtp or _fabrique_par_defaut

    # ------------------------------------------------------------------ état
    @property
    def _user(self) -> Any:
        return getattr(self.settings, "user", None)

    @property
    def mode_local(self) -> bool:
        return bool(getattr(self._user, "local_only", False))

    def _compte(self) -> tuple[str, str]:
        """(adresse, mot de passe) depuis le coffre, ou ('', '')."""
        try:
            creds = self.secrets.get_site(NOM_COFFRE) or {}
        except Exception as exc:  # coffre verrouillé, trousseau absent : ce n'est pas une raison de planter
            log.warning("Coffre illisible pour le compte courriel : %s", exc)
            return "", ""
        return (creds.get("username") or "").strip(), (creds.get("password") or "").strip()

    @property
    def configure(self) -> bool:
        adresse, mdp = self._compte()
        return bool(adresse and mdp) and not self.mode_local

    def reglages(self) -> ReglagesCourriel:
        """Réglages effectifs : ceux de l'utilisateur, complétés par le serveur connu du domaine."""
        brut = getattr(self._user, "courriel", None)  # présent seulement une fois CourrielConfig ajouté à config.py
        adresse, _mdp = self._compte()
        hote_defaut, port_defaut = FOURNISSEURS.get(_domaine(adresse), ("", 587))
        return ReglagesCourriel(
            smtp_hote=str(_champ(brut, "smtp_hote", hote_defaut)),
            # `or port_defaut` : un port à 0 (valeur par défaut d'un réglage jamais rempli) n'est
            # pas un choix de l'utilisateur, c'est un champ vide.
            smtp_port=int(_champ(brut, "smtp_port", port_defaut) or port_defaut),
            tls=bool(_champ(brut, "tls", True)),
            nom_expediteur=_sans_controle(str(_champ(brut, "nom_expediteur", ""))),
            signature=str(_champ(brut, "signature", "")),
        )

    def etat(self) -> dict:
        """État affichable. Ne renvoie jamais le mot de passe, même masqué côté serveur."""
        adresse, mdp = self._compte()
        r = self.reglages()
        return {
            "configure": self.configure,
            "adresse": adresse,
            # mask() rend un EXTRAIT du secret : quatre caracteres au debut, quatre a la fin.
            # Sur un mot de passe court, choisi par la personne plutot que genere, c'est deja trop,
            # et la docstring promettait le contraire.
            "secret": "\u2022" * 8 if mdp else "",
            "smtp_hote": r.smtp_hote,
            "smtp_port": r.smtp_port,
            "tls": r.tls,
            "nom_expediteur": r.nom_expediteur,
            "mode_local": self.mode_local,
            "mode_emploi": "" if (adresse and mdp) else MODE_EMPLOI_GMAIL,
        }

    # ------------------------------------------------------------------ compte
    def configurer(self, adresse: str, mot_de_passe: str) -> dict:
        """Range le compte d'envoi dans le coffre. Le mot de passe ne ressort jamais d'ici."""
        adresse = valider_adresse(adresse)
        # Google affiche le mot de passe d'application en quatre groupes de quatre ; collé tel
        # quel avec ses espaces, il est refusé par le serveur. On les retire une bonne fois.
        mdp = re.sub(r"\s+", "", mot_de_passe or "")
        if not mdp:
            raise ErreurCourriel("Mot de passe d'application manquant. " + MODE_EMPLOI_GMAIL)
        self.secrets.set_site(NOM_COFFRE, adresse, mdp)
        avertissement = ""
        if _domaine(adresse) in ("gmail.com", "googlemail.com") and len(mdp) != 16:
            avertissement = (
                "Attention : un mot de passe d'application Google fait exactement 16 lettres. "
                "Celui-ci n'en fait pas 16 — s'il s'agit du mot de passe habituel du compte, il sera refusé."
            )
        log.info("Compte courriel enregistré pour %s (le secret reste dans le coffre).", adresse)
        etat = self.etat()
        etat["avertissement"] = avertissement
        return etat

    def oublier(self) -> dict:
        self.secrets.delete_site(NOM_COFFRE)
        return self.etat()

    # ------------------------------------------------------------------ brouillon
    def preparer(
        self,
        destinataires: str | Sequence[str],
        sujet: str,
        corps: str,
        cc: str | Sequence[str] | None = None,
        signature: bool = True,
    ) -> Brouillon:
        """Mode brouillon : construit le message et n'envoie RIEN. Aucune connexion n'est ouverte."""
        if self.mode_local:
            raise ModeLocalActif(
                "Le mode local est actif : rien ne quitte cet ordinateur, donc aucun courriel ne peut partir. "
                "Désactivez « mode local » dans les réglages si vous voulez que j'envoie ce message."
            )
        adresse, mdp = self._compte()
        if not adresse or not mdp:
            raise CourrielNonConfigure(
                "Aucun compte d'envoi n'est configuré, je ne peux donc pas envoyer de courriel. "
                + MODE_EMPLOI_GMAIL
                + " Je ne peux pas le faire à ta place : cela demande d'entrer dans ton compte Google."
            )

        vers = _liste_adresses(destinataires)
        copies = tuple(a for a in _liste_adresses(cc) if a.lower() not in [v.lower() for v in vers])
        if not vers:
            raise AdresseInvalide("Aucun destinataire : je ne sais pas à qui écrire.")
        if len(vers) + len(copies) > MAX_DESTINATAIRES:
            raise AdresseInvalide(
                f"{len(vers) + len(copies)} destinataires, c'est au-delà de ce que j'envoie sans qu'on en reparle "
                f"(maximum {MAX_DESTINATAIRES}). Dis-moi qui garder."
            )

        sujet = _sans_controle(sujet)
        if not sujet:
            raise ErreurCourriel("Un courriel sans objet n'est pas un courriel. Donne-moi un objet.")
        corps = (corps or "").replace("\r\n", "\n")
        if not corps.strip():
            raise ErreurCourriel("Le message est vide : je n'envoie pas une page blanche.")

        r = self.reglages()
        if signature and r.signature.strip():
            corps = corps.rstrip() + "\n\n" + r.signature.strip()
        expediteur = formataddr((r.nom_expediteur, adresse)) if r.nom_expediteur else adresse
        return Brouillon(expediteur=expediteur, destinataires=vers, sujet=sujet, corps=corps, cc=copies)

    # ------------------------------------------------------------------ accord
    async def demander_accord(self, brouillon: Brouillon, confirmer: ConfirmFn) -> Autorisation | None:
        """Seule fabrique d'`Autorisation` du programme. Renvoie None si l'utilisateur n'a pas dit oui.

        `confirmer` est la fonction de ToolContext : elle publie la demande à l'écran et renvoie
        False si personne ne répond dans les 180 secondes. Un silence vaut donc un refus, et c'est
        le bon sens de l'échec pour un message qu'on ne peut pas rattraper.
        """
        if confirmer is None:
            raise AutorisationInvalide("Aucun moyen de demander confirmation : je n'envoie rien.")
        approuve = bool(await confirmer(brouillon.titre(), brouillon.apercu()))
        if not approuve:
            log.info("Envoi refusé ou non confirmé (%d destinataire(s)).", len(brouillon.destinataires))
            return None
        return Autorisation(brouillon, _SCEAU)

    # ------------------------------------------------------------------ envoi
    def envoyer(self, autorisation: Autorisation) -> dict:
        """Envoie le message approuvé. N'accepte QUE des `Autorisation` — jamais un brouillon nu.

        Lève `EnvoiEchoue` si le message n'est pas parti : IRIS doit pouvoir dire « je n'ai pas
        réussi », jamais laisser croire que c'est fait.
        """
        if not isinstance(autorisation, Autorisation):
            raise AutorisationInvalide(
                "Je n'envoie pas ce courriel : il n'a pas été confirmé. "
                "Demande-moi de te le relire, puis confirme l'envoi."
            )
        # Consommé avant d'ouvrir la connexion : en cas de coupure en plein envoi, on ne sait pas
        # si le serveur a accepté le message. Redemander est gênant ; envoyer deux fois est pire.
        brouillon = autorisation.consommer()

        adresse, mdp = self._compte()
        if not adresse or not mdp:
            raise CourrielNonConfigure("Le compte d'envoi a disparu du coffre entre-temps. " + MODE_EMPLOI_GMAIL)
        if parseaddr(brouillon.expediteur)[1].lower() != adresse.lower():
            raise EnvoiEchoue(
                "Le compte d'envoi a changé depuis que ce message a été approuvé. Je ne l'envoie pas "
                "depuis une autre adresse que celle que tu as vue."
            )

        r = self.reglages()
        if not r.smtp_hote:
            raise CourrielNonConfigure(
                f"Je ne connais pas le serveur d'envoi du domaine « {_domaine(adresse)} ». "
                "Renseigne l'hôte SMTP et son port dans les réglages."
            )

        message = brouillon.message()
        try:
            serveur = self._fabrique(r.smtp_hote, r.smtp_port, r.smtp_port == 465)
            with serveur:
                if r.tls and r.smtp_port != 465:
                    serveur.starttls()
                serveur.login(adresse, mdp)  # le mot de passe ne sort jamais de cette ligne
                refuses = serveur.send_message(message) or {}
        except Exception as erreur:
            explication = self._expliquer(erreur, adresse, mdp, r)
            log.error("Envoi impossible vers %s : %s", ", ".join(brouillon.destinataires), _sans_secret(str(erreur), mdp))
            # `from None` : la chaîne d'exceptions recopie le dialogue serveur dans les journaux,
            # et ce dialogue n'a pas à être relu par qui que ce soit.
            raise EnvoiEchoue(explication) from None

        recus = [a for a in brouillon.tous_les_destinataires if a not in refuses]
        if refuses:
            log.warning("Destinataires refusés : %s", ", ".join(refuses))
        return {
            "ok": not refuses,
            "envoye": True,
            "destinataires": list(recus),
            "refuses": {a: str(v) for a, v in refuses.items()},
            "sujet": brouillon.sujet,
            "message": self._compte_rendu(brouillon, recus, refuses),
        }

    async def envoyer_apres_accord(
        self,
        destinataires: str | Sequence[str],
        sujet: str,
        corps: str,
        confirmer: ConfirmFn,
        cc: str | Sequence[str] | None = None,
    ) -> dict:
        """Le chemin complet, celui qu'appelle l'outil `send_email` : préparer, faire confirmer, envoyer.

        Aucun raccourci n'est possible ici : sans accord, il n'y a rien à passer à `envoyer()`.
        """
        brouillon = self.preparer(destinataires, sujet, corps, cc=cc)
        accord = await self.demander_accord(brouillon, confirmer)
        if accord is None:
            return {
                "ok": False,
                "envoye": False,
                "destinataires": list(brouillon.destinataires),
                "message": "Je n'ai rien envoyé : l'envoi n'a pas été confirmé.",
            }
        return await asyncio.to_thread(self.envoyer, accord)

    def tester_connexion(self) -> dict:
        """Vérifie identifiants et réseau SANS envoyer le moindre message."""
        adresse, mdp = self._compte()
        if not adresse or not mdp:
            raise CourrielNonConfigure("Aucun compte d'envoi à tester. " + MODE_EMPLOI_GMAIL)
        r = self.reglages()
        if not r.smtp_hote:
            raise CourrielNonConfigure(f"Serveur d'envoi inconnu pour « {_domaine(adresse)} ».")
        try:
            serveur = self._fabrique(r.smtp_hote, r.smtp_port, r.smtp_port == 465)
            with serveur:
                if r.tls and r.smtp_port != 465:
                    serveur.starttls()
                serveur.login(adresse, mdp)
        except Exception as erreur:
            raise EnvoiEchoue(self._expliquer(erreur, adresse, mdp, r)) from None
        return {"ok": True, "adresse": adresse, "message": f"Connexion réussie à {r.smtp_hote} avec {adresse}."}

    # ------------------------------------------------------------------ messages d'erreur
    @staticmethod
    def _compte_rendu(brouillon: Brouillon, recus: list[str], refuses: dict) -> str:
        if not recus:
            return "Aucun destinataire n'a accepté le message."
        phrase = f"Courriel envoyé à {', '.join(recus)} — objet : « {brouillon.sujet} »."
        if refuses:
            phrase += (
                f" En revanche le serveur a refusé {', '.join(refuses)} : "
                "vérifie l'orthographe de cette ou ces adresses, elles n'ont rien reçu."
            )
        return phrase

    def _expliquer(self, erreur: Exception, adresse: str, mdp: str, r: ReglagesCourriel) -> str:
        """Transforme une exception SMTP en phrase qui dit quoi faire. Jamais d'identifiant dedans."""
        detail = _sans_secret(str(erreur), mdp) or type(erreur).__name__
        gmail = "gmail" in (r.smtp_hote or "").lower()

        if isinstance(erreur, smtplib.SMTPAuthenticationError) or "5.7.8" in detail or "not accepted" in detail.lower():
            if gmail:
                return (
                    f"Google a refusé l'identification de {adresse}. Rien n'est parti. Trois causes, dans l'ordre :\n"
                    "1. ce n'est pas un mot de passe d'application — le mot de passe habituel du compte Google "
                    "ne fonctionne plus depuis 2022 ;\n"
                    "2. la validation en deux étapes n'est pas activée sur ce compte : sans elle, la page "
                    "myaccount.google.com/apppasswords n'existe même pas ;\n"
                    "3. le mot de passe d'application a été révoqué — Google les annule tous dès que le mot de "
                    "passe du compte change. Il faut en générer un nouveau et me le redonner.\n"
                    f"Réponse du serveur : {detail}"
                )
            return (
                f"Le serveur {r.smtp_hote} a refusé l'identification de {adresse}. Rien n'est parti. "
                "Vérifiez le mot de passe (chez la plupart des fournisseurs il faut un mot de passe "
                f"d'application, pas celui du compte). Réponse du serveur : {detail}"
            )

        if "5.4.5" in detail or "quota" in detail.lower():
            return (
                "Le quota d'envoi journalier du compte est atteint (environ 500 destinataires par jour chez "
                "Gmail, moins en envoi automatisé). Le message n'est pas parti ; réessayez dans quelques heures. "
                f"Réponse du serveur : {detail}"
            )

        if isinstance(erreur, smtplib.SMTPSenderRefused):
            return (
                f"Le serveur a refusé d'expédier au nom de {adresse}. Gmail n'accepte que l'adresse avec laquelle "
                "on s'est identifié, ou un alias déclaré dans Gmail › Paramètres › Comptes › « Envoyer des "
                f"messages en tant que ». Rien n'a été envoyé. Réponse du serveur : {detail}"
            )

        if isinstance(erreur, smtplib.SMTPRecipientsRefused):
            return (
                "Aucun destinataire n'a été accepté par le serveur : les adresses sont probablement mal "
                f"orthographiées. Rien n'a été envoyé. Réponse du serveur : {detail}"
            )

        if isinstance(erreur, smtplib.SMTPNotSupportedError):
            return (
                f"Le serveur {r.smtp_hote} n'accepte pas le chiffrement STARTTLS sur le port {r.smtp_port}. "
                "Essayez le port 465 (SSL direct) dans les réglages. Rien n'a été envoyé. "
                f"Détail : {detail}"
            )

        if isinstance(erreur, (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, OSError)):
            return (
                f"Impossible de joindre {r.smtp_hote} sur le port {r.smtp_port}. Rien n'a été envoyé. À vérifier, "
                "dans cet ordre : la connexion internet ; le pare-feu ou l'antivirus, qui bloquent souvent le "
                f"port {r.smtp_port} en sortie ; le réseau utilisé (beaucoup de réseaux d'entreprise et d'hôtels "
                "ferment le port 587). Si le 587 est bloqué, essayez le port 465 dans les réglages. "
                f"Détail technique : {detail}"
            )

        return (
            f"L'envoi a échoué et le message n'est pas parti. Détail technique : {detail}. "
            "Redis-moi de l'envoyer si tu veux que je réessaie."
        )
