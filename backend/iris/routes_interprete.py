"""Routes du mode interprète (interface F du chantier du 2026-09-13), et la voix de l'autre langue.

Branché par main._brancher_modules, derrière l'authentification. La logique du mode — qui a parlé,
fil des tours, empêchements — vit dans traduction.py (ServiceInterprete) ; l'écoute du micro dans
voice/listener.py (_boucle_traduction). Ce fichier traduit HTTP <-> service, branche la voix
(interception de priorité 30), referme l'interprète dès que le mode confidentiel ou le mode local
s'allume, et porte la seule pièce qu'aucun autre module ne savait fournir : UNE VOIX QUI PARLE LA
LANGUE DE L'AUTRE PERSONNE.

Pourquoi une voix à part. La voix d'IRIS (voice/tts.py) est faite pour le propriétaire : elle écrit
les nombres en toutes lettres en français et impose sa langue au moteur premium. Elle déformerait
« See you at three ». Les voix installées dans Windows, elles, existent langue par langue — sur la
machine de développement, le 13 septembre 2026 : deux voix anglaises (Canada), une anglaise
(États-Unis), trois françaises (Canada), aucune espagnole. `VoixAutreLangue` les énumère, rend la
phrase EN MÉMOIRE (aucun fichier : c'est la parole d'une conversation privée ; mesuré 0,07 à 0,14 s
par phrase) et la joue sur la sortie choisie. Quand aucune voix de la langue n'existe, l'interprète
le dit à l'ouverture et affiche la traduction au lieu de prétendre la lire.

Services attachés à ctx : ctx.interprete (ServiceInterprete), ctx.interprete.voix (VoixAutreLangue).
"""
from __future__ import annotations

import asyncio
import logging
import queue
import sys
import threading
import time
from typing import Any, Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .traduction import RefusInterprete, ServiceInterprete

log = logging.getLogger("iris.interprete")

# ---------------------------------------------------------------- voix de Windows
# Langue principale d'un identifiant de langue Windows (LCID & 0x3FF) -> code court d'IRIS.
LANGUES_LCID = {0x09: "en", 0x0C: "fr", 0x0A: "es", 0x16: "pt", 0x10: "it", 0x07: "de"}
REGIONS_LCID = {
    0x1009: "Canada", 0x0409: "États-Unis", 0x0809: "Royaume-Uni", 0x0C09: "Australie", 0x4009: "Inde",
    0x0C0C: "Canada", 0x040C: "France", 0x080C: "Belgique", 0x100C: "Suisse",
    0x0C0A: "Espagne", 0x040A: "Espagne", 0x080A: "Mexique",
    0x0416: "Brésil", 0x0816: "Portugal", 0x0410: "Italie", 0x0407: "Allemagne",
}
# Les deux registres de voix. Les voix récentes (celles qu'on ajoute dans Paramètres › Heure et
# langue › Voix) ne sont PAS listées par défaut par SAPI : il faut ouvrir leur catégorie
# explicitement. Vérifié sur la machine de développement : elles se rendent en mémoire comme les autres.
CATEGORIES_VOIX = (
    (True, r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices"),
    (False, r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech\Voices"),
)
TAUX_RENDU = 22050
FORMAT_22KHZ_16BIT_MONO = 22  # SpeechAudioFormatType.SAFT22kHz16BitMono
# SpeechVoiceSpeakFlags.SVSFIsNotXML : la phrase vient d'une conversation, jamais d'un balisage à interpréter.
SANS_BALISAGE = 16
ATTENTE_LISTE_S = 8.0
REPLI_LUNETTES = ("Sortie des lunettes introuvable : la traduction pour l'autre personne sort par le "
                  "haut-parleur de l'ordinateur.")


def lire_lcid(attribut: object) -> int | None:
    """« 1009 » ou « 409;9 » -> l'identifiant de langue. SAPI le donne en hexadécimal."""
    try:
        return int(str(attribut or "").split(";")[0].strip(), 16)
    except ValueError:
        return None


def langue_de_lcid(lcid: int | None) -> str:
    return LANGUES_LCID.get(lcid & 0x3FF, "") if lcid else ""


def nom_affichable(nom: str) -> str:
    """« Microsoft Linda » -> « Linda » : le nom de l'éditeur n'apporte rien à l'écran."""
    propre = str(nom or "").replace("Microsoft", "").replace("Desktop", "").strip(" -")
    return propre or str(nom or "").strip()


def classer_voix(voix: list[dict], langue: str) -> list[dict]:
    """Les voix de cette langue, la meilleure d'abord : variante canadienne, puis voix récente
    (plus naturelle que les voix « Desktop » historiques), puis l'ordre de Windows."""
    candidates = [(i, v) for i, v in enumerate(voix or []) if v.get("langue") == langue]
    candidates.sort(key=lambda iv: (iv[1].get("region") != "Canada", not iv[1].get("recente"), iv[0]))
    return [v for _i, v in candidates]


class VoixAutreLangue:
    """Parle la langue de l'autre personne avec une voix installée dans Windows.

    Un seul fil de travail possède tout ce qui touche à la synthèse de Windows (objets COM liés à
    leur fil) : il énumère les voix, rend la phrase en mémoire, puis la joue. `parler` ne bloque
    jamais l'appelant ; `parle` est vrai tant qu'une phrase est en file ou en cours, et l'écoute s'en
    sert pour ne pas se traduire elle-même (alternat). `lister`, `synthetiser` et `jouer` sont
    injectables : les tests n'ouvrent ni synthèse, ni haut-parleur. `actif=False` (synthèse vocale
    désactivée, comme dans les tests) interdit tout accès réel au matériel."""

    def __init__(
        self,
        settings: Any,
        hub: Any = None,
        actif: bool = True,
        lister: Callable[[], list[dict]] | None = None,
        synthetiser: Callable[[dict, str], tuple[bytes, int]] | None = None,
        jouer: Callable[[bytes, int, str, Callable[[], bool]], str] | None = None,
    ):
        self.settings = settings
        self.hub = hub
        self.actif = actif
        self._lister = lister
        self._synthetiser = synthetiser
        self._jouer = jouer
        self._file: "queue.Queue[tuple | None]" = queue.Queue()
        self._fil: threading.Thread | None = None
        self._verrou = threading.Lock()
        self._liste: list[dict] | None = None
        self._generation = 0
        self._en_cours = 0
        self.raison: str | None = None
        self._moteur = None  # SAPI.SpVoice, créé dans le fil de travail
        self._jetons: dict[str, Any] = {}

    # ------------------------------------------------------------ état
    @property
    def parle(self) -> bool:
        return self._en_cours > 0

    def voix(self) -> list[dict]:
        if self._liste is None:
            self.rafraichir()
        return list(self._liste or [])

    def rafraichir(self) -> list[dict]:
        if self._lister is None and not self.actif:
            self._liste = []
            self.raison = "Synthèse vocale désactivée sur ce poste."
            return []
        if self.parle and self._liste is not None:
            # Le fil est occupé à jouer une phrase : on n'attend pas derrière elle (l'appelant peut
            # être le fil audio de l'écoute), la liste connue suffit.
            return list(self._liste)
        fait = threading.Event()
        boite: dict = {}
        self._assurer_fil()
        self._file.put(("lister", fait, boite))
        if not fait.wait(ATTENTE_LISTE_S):
            log.warning("liste des voix non obtenue en %.0f s (une phrase est peut-être en cours)", ATTENTE_LISTE_S)
            return list(self._liste or [])
        self._liste = list(boite.get("voix") or [])
        return list(self._liste)

    def pour_langue(self, langue: str) -> dict | None:
        classees = classer_voix(self.voix(), langue)
        return classees[0] if classees else None

    def disponible(self, langue: str) -> bool:
        return self.pour_langue(langue) is not None

    def nom_voix(self, langue: str) -> str | None:
        """Ce que l'écran affiche : la langue et la variante, pas le prénom de la voix. Les prénoms
        des voix de Windows ne disent rien à l'utilisateur, et l'un d'eux (une voix française du
        Canada) porte le nom d'un fournisseur d'IA — le masque de marque l'interdit à l'écran."""
        voix = self.pour_langue(langue)
        if voix is None:
            return None
        from .traduction import nom_langue

        nom = f"Voix de l'ordinateur en {nom_langue(langue)}"
        return f"{nom} ({voix['region']})" if voix.get("region") else nom

    # ------------------------------------------------------------ parler
    def parler(self, texte: str, langue: str, sortie: str = "pc") -> bool:
        """Met la phrase en file. Rend False quand aucune voix de cette langue ne peut la dire."""
        propre = (texte or "").strip()
        voix = self.pour_langue(langue)
        if voix is None or not propre:
            return False
        if self._jouer is None and not self.actif:
            return False  # synthèse désactivée : aucun périphérique ne s'ouvre, jamais
        self._assurer_fil()
        with self._verrou:
            self._en_cours += 1
            generation = self._generation
        self._file.put(("parler", generation, propre, voix, sortie))
        return True

    def arreter(self) -> None:
        """Coupe la phrase en cours et oublie celles qui attendent."""
        with self._verrou:
            self._generation += 1
        gardees = []
        try:
            while True:
                element = self._file.get_nowait()
                if element is not None and element[0] == "parler":
                    with self._verrou:
                        self._en_cours = max(0, self._en_cours - 1)
                else:
                    gardees.append(element)
        except queue.Empty:
            pass
        for element in gardees:
            self._file.put(element)

    def fermer(self) -> None:
        self.arreter()
        if self._fil is not None:
            self._file.put(None)

    # ------------------------------------------------------------ le fil de travail
    def _assurer_fil(self) -> None:
        with self._verrou:
            if self._fil is None or not self._fil.is_alive():
                self._fil = threading.Thread(target=self._tourner, name="iris-voix-autre", daemon=True)
                self._fil.start()

    def _tourner(self) -> None:
        if self._lister is None or self._synthetiser is None:
            try:  # objets COM : initialiser COM dans CE fil
                import comtypes

                comtypes.CoInitialize()
            except Exception:
                pass
        while True:
            element = self._file.get()
            if element is None:
                return
            if element[0] == "lister":
                _quoi, fait, boite = element
                try:
                    boite["voix"] = (self._lister or self._lister_windows)()
                    self.raison = None
                except Exception as exc:
                    boite["voix"] = []
                    self.raison = "Les voix installées sur cet ordinateur n'ont pas pu être lues."
                    log.warning("énumération des voix de Windows impossible : %s", exc)
                finally:
                    fait.set()
                continue
            _quoi, generation, texte, voix, sortie = element
            try:
                if generation != self._generation:
                    continue  # arrêtée avant d'avoir commencé
                pcm, taux = (self._synthetiser or self._synthetiser_windows)(voix, texte)
                if generation != self._generation or not pcm:
                    continue
                self._publier("interprete.voix", etat="debut", sortie=sortie, langue=voix.get("langue"))
                reelle = (self._jouer or self._jouer_sortie)(pcm, taux, sortie, lambda g=generation: g != self._generation)
                self._publier("interprete.voix", etat="fin", sortie=reelle or sortie, langue=voix.get("langue"))
            except Exception as exc:
                log.warning("voix de l'autre langue en erreur : %s", exc)
                self._publier("interprete.voix", etat="erreur", sortie=sortie,
                              raison="La traduction n'a pas pu être lue à voix haute pour l'autre personne.")
            finally:
                with self._verrou:
                    self._en_cours = max(0, self._en_cours - 1)

    # ------------------------------------------------------------ Windows (matériel réel)
    def _lister_windows(self) -> list[dict]:
        if sys.platform != "win32":
            return []
        import comtypes.client

        trouvees: list[dict] = []
        vues: set[tuple[str, str]] = set()
        jetons: dict[str, Any] = {}
        for recente, categorie in CATEGORIES_VOIX:
            try:
                cat = comtypes.client.CreateObject("SAPI.SpObjectTokenCategory")
                cat.SetId(categorie, False)
                liste = cat.EnumerateTokens()
            except Exception as exc:
                log.info("catégorie de voix absente (%s) : %s", categorie.rsplit("\\", 2)[-2], exc)
                continue
            for i in range(liste.Count):
                try:
                    jeton = liste.Item(i)
                    nom = nom_affichable(jeton.GetAttribute("Name"))
                    lcid = lire_lcid(jeton.GetAttribute("Language"))
                    ident = str(jeton.Id)
                except Exception:
                    continue
                langue = langue_de_lcid(lcid)
                if not langue or (nom.lower(), langue) in vues:
                    continue  # la même voix peut figurer dans les deux registres
                vues.add((nom.lower(), langue))
                jetons[ident] = jeton
                trouvees.append({"id": ident, "nom": nom, "langue": langue,
                                 "region": REGIONS_LCID.get(lcid or 0, ""), "recente": recente})
        self._jetons = jetons
        return trouvees

    def _synthetiser_windows(self, voix: dict, texte: str) -> tuple[bytes, int]:
        import comtypes.client

        jeton = self._jetons.get(voix.get("id", ""))
        if jeton is None:
            self._lister_windows()
            jeton = self._jetons.get(voix.get("id", ""))
        if jeton is None:
            raise RuntimeError("voix introuvable (désinstallée ?)")
        if self._moteur is None:
            self._moteur = comtypes.client.CreateObject("SAPI.SpVoice")
        flux = comtypes.client.CreateObject("SAPI.SpMemoryStream")
        forme = comtypes.client.CreateObject("SAPI.SpAudioFormat")
        forme.Type = FORMAT_22KHZ_16BIT_MONO
        flux.Format = forme
        moteur = self._moteur
        moteur.Voice = jeton
        # Vitesse normale, et c'est voulu : le débit rapide choisi par le propriétaire (jusqu'à 3×
        # pour une personne non voyante) n'est pas celui d'un inconnu qui entend IRIS pour la première fois.
        moteur.Rate = 0
        moteur.Volume = 100
        moteur.AudioOutputStream = flux
        moteur.Speak(texte, SANS_BALISAGE)
        return bytes(bytearray(flux.GetData())), TAUX_RENDU

    def _jouer_sortie(self, pcm: bytes, taux: int, sortie: str, doit_arreter: Callable[[], bool]) -> str:
        """Joue le PCM sur la sortie voulue. Rend la sortie réellement utilisée (« pc » en repli)."""
        import sounddevice as sd

        from .voice.elevenlabs import VERROU_PORTAUDIO, Reechantillonneur

        # Sous le verrou partagé des voix : tant que ce flux est ouvert, l'écoute ne doit pas fermer
        # PortAudio pour ré-énumérer (voir elevenlabs.VERROU_PORTAUDIO — corruption du tas sinon).
        with VERROU_PORTAUDIO:
            device, taux_ouvert, reelle = self._peripherique(sd, sortie, taux)
            convertisseur = Reechantillonneur(taux, taux_ouvert)
            pas = 2 * max(1, taux // 10)  # 0,1 s : l'arrêt est entendu en un dixième de seconde
            utile = len(pcm) - (len(pcm) % 2)
            flux = sd.RawOutputStream(samplerate=taux_ouvert, channels=1, dtype="int16", device=device)
            with flux as sortie_audio:
                for debut in range(0, utile, pas):
                    if doit_arreter():
                        break
                    morceau = convertisseur.convertir(pcm[debut:min(debut + pas, utile)])
                    if morceau:
                        sortie_audio.write(morceau)
        return reelle

    def _peripherique(self, sd: Any, sortie: str, taux: int) -> tuple[int | None, int, str]:
        """(index, fréquence, sortie réelle). « lunettes » suit la même règle que les autres voix
        (elevenlabs.classer_sorties) ; introuvables, on le dit et on sort par le haut-parleur par défaut."""
        if sortie == "lunettes":
            u = self.settings.user
            voulu = (u.audio_output_device or "").strip() or (getattr(u.glasses, "name", "") or "").strip()
            if voulu:
                try:
                    from .voice.elevenlabs import classer_sorties, micro_mains_libres
                    from .voice.listener import score_hote

                    apis = sd.query_hostapis()
                    devices = list(sd.query_devices())
                    noms: list[str] = []
                    scores: list[int] = []
                    index: list[int] = []
                    for idx, dev in enumerate(devices):
                        if int(dev.get("max_output_channels", 0) or 0) <= 0:
                            continue
                        try:
                            hote = apis[int(dev.get("hostapi", -1))].get("name") or ""
                        except Exception:
                            hote = ""
                        noms.append(dev.get("name") or "")
                        scores.append(score_hote(hote))
                        index.append(idx)
                    for position in classer_sorties(noms, voulu.lower(), micro_mains_libres(self.settings), scores):
                        idx = index[position]
                        natif = int(float(devices[idx].get("default_samplerate") or 0))
                        for essai in (taux, natif):
                            if essai <= 0:
                                continue
                            try:
                                sd.check_output_settings(device=idx, samplerate=essai, channels=1, dtype="int16")
                                return idx, essai, "lunettes"
                            except Exception:
                                continue
                except Exception as exc:
                    log.info("sortie des lunettes non trouvée (%s)", exc)
            self._publier("interprete.voix", etat="repli", sortie="pc", raison=REPLI_LUNETTES)
        try:
            sd.check_output_settings(device=None, samplerate=taux, channels=1, dtype="int16")
            return None, taux, "pc"
        except Exception:
            try:
                natif = int(float(sd.query_devices(kind="output").get("default_samplerate") or 0))
            except Exception:
                natif = 0
            return None, natif or 48000, "pc"

    def _publier(self, type_: str, **donnees: Any) -> None:
        if self.hub is None:
            return
        try:
            self.hub.publish(type_, **donnees)
        except Exception:
            pass


# ---------------------------------------------------------------- routes
class DemarrerIn(BaseModel):
    langue_autre: str | None = None
    sortie_autre: str | None = None


class TexteIn(BaseModel):
    qui: str = ""
    texte: str = ""
    langue: str | None = None  # la langue de L'AUTRE personne, quel que soit « qui »


def _http(exc: RefusInterprete) -> HTTPException:
    return HTTPException(status_code=exc.statut, detail=exc.detail)


AGENT_VALIDE_S = 5.0


def moteur_de_traduction(ctx: Any) -> str | None:
    """Le moteur qui recevra la traduction, choisi comme le fait le chat (ChatService.demander_court)."""
    chat = getattr(ctx, "chat", None)
    try:
        routeur = chat.router
        agent, _raison = routeur.select("traduction", False, routeur.available(chat.secrets), "auto")
        return agent
    except Exception:
        return None


def fabriquer_verificateur(ctx: Any) -> Callable[[], None]:
    """ctx.consent.check("transcript") avant chaque envoi de texte au moteur. Lève si refusé.

    Une IA locale n'est pas soumise au consentement d'envoi externe, et le mode local n'autorise
    qu'elle : il faut donc connaître le moteur. Le choisir interroge le coffre des clés pour chaque
    moteur, à chaque phrase ; on garde ce choix quelques secondes (et on le refait dès que le mode
    local change), mais le CONSENTEMENT, lui, est relu à chaque envoi."""
    memoire: dict[str, Any] = {"agent": None, "a": float("-inf"), "local": None}

    def verifier() -> None:
        local = bool(ctx.settings.user.local_only)
        maintenant = time.monotonic()
        if maintenant - memoire["a"] > AGENT_VALIDE_S or memoire["local"] != local:
            memoire.update(agent=moteur_de_traduction(ctx), a=maintenant, local=local)
        ctx.consent.check("transcript", agent=memoire["agent"])

    return verifier


def creer_routeur(ctx: Any) -> APIRouter:
    traduction = getattr(ctx, "traduction", None)
    if traduction is None:
        raise RuntimeError("le service de traduction n'est pas construit")
    tts = getattr(ctx, "tts", None)
    ecoute = getattr(ctx, "voice", None)
    voix = VoixAutreLangue(ctx.settings, ctx.hub, actif=bool(getattr(tts, "_audio_enabled", True)))
    # Toute traduction (simple ou interprète) vérifie désormais le consentement « transcript » avant
    # d'envoyer le texte : c'est la règle d'IRIS, et le chemin vocal historique ne la vérifiait pas.
    traduction.verifier_envoi = fabriquer_verificateur(ctx)
    service = ServiceInterprete(
        traduction,
        ctx.settings,
        hub=ctx.hub,
        voix=voix,
        ecoute=ecoute,
        audio_autorise=lambda: ctx.consent.is_granted("audio_raw") and not ctx.settings.user.local_only,
        parler_moi=(lambda texte: tts.speak(texte, force=True)) if tts is not None else None,
    )
    # Attaché tout de suite : la page téléphone, l'écran et les autres équipes le trouvent par
    # getattr(ctx, "interprete", None) avant même le démarrage.
    ctx.interprete = service

    def brancher_voix() -> None:
        if ecoute is not None and hasattr(ecoute, "ajouter_interception"):
            ecoute.ajouter_interception("interprete", service.interception, priorite=30)

    def debrancher_voix() -> None:
        if ecoute is not None and hasattr(ecoute, "retirer_interception"):
            ecoute.retirer_interception("interprete")

    # Branchée dès maintenant (fonction synchrone, sans boucle requise) : « mode interprète anglais »
    # doit marcher dès la première commande vocale, sans attendre la fin du démarrage.
    brancher_voix()

    routeur = APIRouter()

    @routeur.get("/api/interprete/etat")
    async def interprete_etat():
        return await asyncio.to_thread(service.etat)

    @routeur.post("/api/interprete/demarrer")
    async def interprete_demarrer(body: DemarrerIn | None = None):
        corps = body or DemarrerIn()
        try:
            return await asyncio.to_thread(service.demarrer, corps.langue_autre, corps.sortie_autre)
        except RefusInterprete as exc:
            raise _http(exc)

    @routeur.post("/api/interprete/arreter")
    async def interprete_arreter():
        return await asyncio.to_thread(service.arreter, "demande")

    @routeur.post("/api/interprete/texte")
    async def interprete_texte(body: TexteIn):
        try:
            return await service.traduire_texte(body.qui, body.texte, body.langue)
        except RefusInterprete as exc:
            raise _http(exc)

    veille: dict[str, Any] = {"tache": None}

    async def veiller_reglages() -> None:
        """Mode confidentiel ou mode local allumé : l'interprète se referme dans la seconde."""
        file = ctx.hub.subscribe()
        try:
            while True:
                evenement = await file.get()
                if evenement.get("type") in ("privacy.mode", "settings.updated"):
                    try:
                        service.appliquer_reglages()
                    except Exception as exc:
                        log.warning("réglages non appliqués à l'interprète : %s", exc)
        finally:
            ctx.hub.unsubscribe(file)

    def demarrage() -> None:
        brancher_voix()
        try:
            veille["tache"] = asyncio.get_running_loop().create_task(veiller_reglages())
        except RuntimeError:
            veille["tache"] = None

    async def arret() -> None:
        debrancher_voix()
        tache = veille.pop("tache", None)
        if tache is not None:
            tache.cancel()
            try:
                await tache
            except (asyncio.CancelledError, Exception):
                pass
        try:
            if service.actif:
                service.arreter("arret")
        finally:
            voix.fermer()

    routeur.iris_demarrage = demarrage  # type: ignore[attr-defined]
    routeur.iris_arret = arret  # type: ignore[attr-defined]
    return routeur
