"""Outils exposés à Claude pour agir sur l'ordinateur et sur IRIS (mémoire, tâches).
Chaque outil passe par la porte de consentement / confirmation avant tout effet sensible."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .capture import CaptureIndicator
from .config import Settings
from .connectors.base import ToolSpec
from .consent import ConsentGate, ConsentRequired, LocalOnlyMode
from .memory import MemoryService
from .pc import actions

ConfirmFn = Callable[[str, str], Awaitable[bool]]  # (titre, détail) -> approuvé ?
TaskCreateFn = Callable[[str, str, str], Awaitable[dict]]  # (titre, instructions, agent)


@dataclass
class ToolContext:
    settings: Settings
    consent: ConsentGate
    capture: CaptureIndicator
    memory: MemoryService
    agent: str
    confirm: ConfirmFn
    create_task: TaskCreateFn | None = None
    routines: Any = None
    watches: Any = None  # WatchService : surveillance d'une page dans la durée
    reminders: Any = None
    web: Any = None
    glasses: Any = None  # GlassesService : les lunettes VELA
    courriel: Any = None  # Postier : envoi de courriels, jamais sans accord
    telephonie: Any = None  # Telephoniste : SMS et appels, jamais sans accord


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        "open_application",
        "Ouvre ou lance une application installée sur l'ordinateur (ex. 'navigateur', 'VS Code', 'Chrome', 'Bloc-notes', 'Explorateur', 'Terminal', 'Spotify').",
        _obj({"name": {"type": "string", "description": "Nom de l'application"}}, ["name"]),
    ),
    ToolSpec(
        "open_url",
        "Ouvre un SITE web par son adresse (ex. https://www.radio-canada.ca). "
        "NE L'UTILISE PAS pour une vidéo, une musique, une chanson ni une recherche YouTube : utilise play_youtube.",
        _obj({"url": {"type": "string"}}, ["url"]),
    ),
    ToolSpec(
        "play_youtube",
        "À utiliser pour TOUTE demande de vidéo, musique, chanson ou clip (« mets », « lance », « joue », « écoute »), "
        "même si l'utilisateur dit d'abord « ouvre YouTube » : cet outil cherche et lance directement la vidéo. "
        "Un seul appel suffit ; ne prends aucune capture d'écran ensuite. "
        "Si l'utilisateur n'a pas dit quoi écouter, demande-le-lui d'abord au lieu d'appeler l'outil.",
        _obj({"query": {"type": "string", "description": "Titre, artiste ou description"}}, ["query"]),
    ),
    ToolSpec(
        "open_path",
        "Ouvre un fichier ou un dossier avec l'application par défaut du système.",
        _obj({"path": {"type": "string", "description": "Chemin absolu ou ~/… ; variables d'environnement acceptées"}}, ["path"]),
    ),
    ToolSpec(
        "search_files",
        "Recherche des fichiers ou dossiers dont le nom contient un texte, dans le dossier personnel ou un dossier donné.",
        _obj(
            {
                "query": {"type": "string"},
                "folder": {"type": "string", "description": "Dossier de départ (défaut : dossier personnel)"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            ["query"],
        ),
    ),
    ToolSpec(
        "list_directory",
        "Liste le contenu d'un dossier (nom, type, taille, date).",
        _obj({"path": {"type": "string"}}, ["path"]),
    ),
    ToolSpec(
        "read_file",
        "Lit le contenu d'un fichier texte (code, config, notes…).",
        _obj({"path": {"type": "string"}}, ["path"]),
    ),
    ToolSpec(
        "write_file",
        "Crée ou remplace un fichier texte (code source, page web, script, document…). Crée les dossiers manquants. "
        "Pour développer une application ou un site, écris chaque fichier avec cet outil puis lance les commandes nécessaires avec run_command.",
        _obj(
            {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "append": {"type": "boolean", "description": "Ajouter à la fin au lieu de remplacer"},
            },
            ["path", "content"],
        ),
    ),
    ToolSpec(
        "run_command",
        "Exécute une commande shell (PowerShell sous Windows) et renvoie sa sortie : installer des dépendances, lancer un build, "
        "démarrer un serveur, git, etc. Explique en une phrase ce que fait la commande dans 'reason'. Les commandes dangereuses demandent confirmation.",
        _obj(
            {
                "command": {"type": "string"},
                "reason": {"type": "string", "description": "Ce que fait la commande, en langage simple"},
                "timeout": {"type": "integer", "minimum": 5, "maximum": 600, "description": "Délai max en secondes (défaut 60)"},
            },
            ["command", "reason"],
        ),
    ),
    ToolSpec(
        "type_text",
        "Tape du texte au clavier dans la fenêtre active (barre d'adresse, champ de recherche, éditeur…). Combine avec press_keys pour valider.",
        _obj({"text": {"type": "string"}}, ["text"]),
    ),
    ToolSpec(
        "press_keys",
        "Envoie une touche ou un raccourci clavier à la fenêtre active : 'enter', 'ctrl+l', 'alt+tab', 'win+d', 'ctrl+t', 'f5', 'space'…",
        _obj({"combo": {"type": "string"}}, ["combo"]),
    ),
    ToolSpec(
        "take_screenshot",
        "Prend une capture de l'écran principal et te la renvoie en image pour voir ce que l'utilisateur voit (vérifier un résultat, lire une page). "
        "Nécessite le consentement 'captures d'écran'.",
        _obj({}),
    ),
    ToolSpec(
        "screen_info",
        "Taille de l'écran et échelle de la capture. Les coordonnées que tu donnes aux outils souris sont celles de la capture d'écran (take_screenshot), converties automatiquement.",
        _obj({}),
    ),
    ToolSpec(
        "mouse_move",
        "Déplace la souris à une position (coordonnées de la capture d'écran).",
        _obj({"x": {"type": "number"}, "y": {"type": "number"}}, ["x", "y"]),
    ),
    ToolSpec(
        "mouse_click",
        "Clique à une position de la capture d'écran (gauche par défaut, 'right' pour le menu contextuel, clicks=2 pour un double-clic). Sans x/y : clique à la position actuelle.",
        _obj({"x": {"type": "number"}, "y": {"type": "number"}, "button": {"type": "string", "enum": ["left", "right", "middle"]}, "clicks": {"type": "integer", "minimum": 1, "maximum": 3}}),
    ),
    ToolSpec(
        "mouse_drag",
        "Glisser-déposer du point (x1,y1) au point (x2,y2), coordonnées de la capture.",
        _obj({"x1": {"type": "number"}, "y1": {"type": "number"}, "x2": {"type": "number"}, "y2": {"type": "number"}}, ["x1", "y1", "x2", "y2"]),
    ),
    ToolSpec(
        "scroll",
        "Fait défiler la molette : amount négatif = vers le bas, positif = vers le haut (ex. -5). Optionnellement à une position.",
        _obj({"amount": {"type": "integer"}, "x": {"type": "number"}, "y": {"type": "number"}}, ["amount"]),
    ),
    ToolSpec(
        "find_on_screen",
        "Lit le texte affiché à l'écran (OCR hors-ligne) et renvoie les zones contenant le texte cherché avec leurs coordonnées (x, y) prêtes pour mouse_click. Idéal pour trouver un bouton, un menu ou un lien par son libellé.",
        _obj({"text": {"type": "string"}}, ["text"]),
    ),
    ToolSpec(
        "click_text",
        "Clique directement sur un texte visible à l'écran (bouton « Jouer », onglet, lien…). Plus fiable que des coordonnées devinées.",
        _obj({"text": {"type": "string"}, "button": {"type": "string", "enum": ["left", "right"]}, "clicks": {"type": "integer", "minimum": 1, "maximum": 2}, "occurrence": {"type": "integer", "minimum": 1}}, ["text"]),
    ),
    ToolSpec(
        "list_applications",
        "Cherche dans les applications et jeux installés (menu Démarrer, Microsoft Store, Steam) par nom approximatif. Utilise ensuite open_application avec le nom exact.",
        _obj({"query": {"type": "string"}}, ["query"]),
    ),
    ToolSpec(
        "create_routine",
        "Crée une routine vocale : une phrase déclencheur qui rejoue une séquence d'actions (outils open_application, open_url, play_youtube, open_path, run_command, type_text, press_keys, click_text…). Exemple : « mode travail » → ouvre VS Code, Spotify et le dossier projet.",
        _obj({"name": {"type": "string"}, "trigger": {"type": "string", "description": "Phrase que l'utilisateur dira"}, "steps": {"type": "array", "items": {"type": "object", "properties": {"tool": {"type": "string"}, "args": {"type": "object"}}, "required": ["tool"]}}}, ["name", "steps"]),
    ),
    ToolSpec(
        "run_routine",
        "Exécute une routine enregistrée par son nom ou sa phrase déclencheur.",
        _obj({"name": {"type": "string"}}, ["name"]),
    ),
    ToolSpec(
        "create_watch",
        "Met en place une SURVEILLANCE DURABLE d'une page ou d'une conversation web (ex. un fil de discussion avec un "
        "fournisseur). IRIS la relit régulièrement, analyse les nouveaux messages au regard des critères donnés, et "
        "prévient l'utilisateur à la voix dès qu'ils sont remplis. À utiliser quand la demande contient « surveille », "
        "« garde un œil », « préviens-moi si », « en permanence ». IRIS ne peut jamais acheter ni répondre toute seule : "
        "elle prépare la décision et l'utilisateur confirme. Demande l'adresse exacte de la page si tu ne l'as pas.",
        _obj(
            {
                "name": {"type": "string", "description": "Nom court, ex. « fournisseur Alibaba »"},
                "url": {"type": "string", "description": "Adresse complète de la page à surveiller"},
                "criteria": {"type": "string", "description": "Ce qui doit déclencher l'alerte, avec les chiffres exacts"},
                "interval_min": {"type": "integer", "description": "Minutes entre deux vérifications (15 par défaut, 2 minimum)"},
                "site": {"type": "string", "description": "Nom d'un compte web enregistré à ouvrir avant de lire (facultatif)"},
            },
            ["name", "url", "criteria"],
        ),
    ),
    ToolSpec("list_watches", "Liste les surveillances en cours et leurs dernières alertes.", _obj({})),
    ToolSpec(
        "stop_watch",
        "Arrête une surveillance en cours, par son identifiant ou son nom.",
        _obj({"watch": {"type": "string", "description": "Identifiant ou nom de la veille"}}, ["watch"]),
    ),
    ToolSpec(
        "set_reminder",
        "Programme un rappel annoncé à voix haute : dans N minutes, ou à une heure ('15:30', 'demain 09:00').",
        _obj({"text": {"type": "string"}, "minutes": {"type": "number"}, "at": {"type": "string"}}, ["text"]),
    ),
    ToolSpec(
        "envoyer_courriel",
        "Envoie un courriel au nom de l'utilisateur. Il verra le message en entier et devra l'approuver "
        "avant tout envoi : tu ne peux pas contourner cette étape, et tu ne dois pas essayer. Écris le "
        "message toi-même, complet et prêt à partir — pas un canevas à trous.",
        _obj({
            "destinataires": {"type": "string", "description": "Une ou plusieurs adresses, séparées par des virgules"},
            "sujet": {"type": "string"},
            "corps": {"type": "string", "description": "Le message complet, tel qu'il partira"},
            "copie": {"type": "string", "description": "Adresses en copie, facultatif"},
        }, ["destinataires", "sujet", "corps"]),
    ),
    ToolSpec(
        "envoyer_sms",
        "Envoie un message texte. Comme pour le courriel, l'utilisateur voit le texte et doit l'approuver. "
        "Un SMS coûte de l'argent à chaque envoi : ne l'utilise que si on te le demande.",
        _obj({
            "numero": {"type": "string", "description": "Numéro du destinataire"},
            "message": {"type": "string", "description": "Le texte complet"},
        }, ["numero", "message"]),
    ),
    ToolSpec(
        "passer_un_appel",
        "Lance un appel téléphonique vers un numéro. L'utilisateur doit l'approuver avant que ça sonne.",
        _obj({"numero": {"type": "string"}}, ["numero"]),
    ),
    ToolSpec(
        "lunettes_etat",
        "État des lunettes VELA : connectées ou non, nom, adresse, et niveau de batterie. "
        "Utilise-le dès qu'on te parle des lunettes — leur charge n'est connue que par ce moyen.",
        _obj({}),
    ),
    ToolSpec(
        "lunettes_envoyer",
        "Envoie une trame aux lunettes VELA sur leur canal de commande. À n'utiliser que si "
        "l'utilisateur demande explicitement d'envoyer quelque chose aux lunettes. Le protocole est "
        "connu (en-tête 0xBC, longueur, CRC-16/MODBUS), mais AUCUNE commande montante n'a jamais "
        "obtenu de réponse : dis-le honnêtement plutôt que de laisser croire à un effet.",
        _obj({
            "commande": {"type": "integer", "description": "Octet de commande, 0-255. Seule 0x73 (115) est connue."},
            "contenu": {"type": "string", "description": "Contenu en hexadécimal, ex. '050000'. Vide si aucun."},
        }, ["commande"]),
    ),
    ToolSpec(
        "web_search",
        "Cherche sur le web et renvoie le texte des résultats. Aucune fenêtre ne s'ouvre : l'utilisateur ne voit que ta réponse. "
        "Utilise-le dès que la réponse dépend d'une information que tu n'as pas de façon certaine : actualité, prix, horaires, "
        "météo, résultat sportif, fait daté, ou tout ce qui a pu changer depuis ton entraînement. Mieux vaut chercher que deviner.",
        _obj({"query": {"type": "string", "description": "Ce qu'il faut chercher"}}, ["query"]),
    ),
    ToolSpec(
        "web_open",
        "Ouvre une page web dans le navigateur piloté par IRIS (Chrome) et renvoie son titre. Pour naviguer sur un site (Omnivox, portails, formulaires), préfère les outils web_* au contrôle d'écran.",
        _obj({"url": {"type": "string"}}, ["url"]),
    ),
    ToolSpec(
        "web_login",
        "Se connecte à un site enregistré par l'utilisateur (ex. 'omnivox') avec ses identifiants stockés dans le coffre : IRIS remplit le formulaire elle-même, tu ne vois jamais le mot de passe. Si un contrôle de sécurité (captcha) apparaît, l'utilisateur le résout dans la fenêtre. Utilise-le d'abord quand la demande concerne un site enregistré.",
        _obj({"site": {"type": "string", "description": "Nom du site enregistré (ex. omnivox)"}}, ["site"]),
    ),
    ToolSpec(
        "web_read",
        "Lit la page courante : URL, titre, texte visible (résumé) et liste des éléments cliquables (liens, boutons). À appeler après chaque navigation pour savoir quoi cliquer.",
        _obj({}),
    ),
    ToolSpec(
        "web_click",
        "Clique sur un lien ou un bouton de la page courante par son libellé (ex. 'Mes notes', 'Horaire', 'Connexion') ou un sélecteur CSS.",
        _obj({"target": {"type": "string"}}, ["target"]),
    ),
    ToolSpec(
        "web_fill",
        "Remplit un champ de la page courante (par libellé, placeholder, nom ou sélecteur CSS) avec une valeur ; submit=true pour valider avec Entrée. Ne l'utilise jamais pour un mot de passe : utilise web_login.",
        _obj({"target": {"type": "string"}, "value": {"type": "string"}, "submit": {"type": "boolean"}}, ["target", "value"]),
    ),
    ToolSpec("web_press", "Appuie sur une touche dans le navigateur piloté (Enter, Escape, Tab, PageDown…).", _obj({"key": {"type": "string"}}, ["key"])),
    ToolSpec("web_back", "Revient à la page précédente du navigateur piloté.", _obj({})),
    ToolSpec(
        "web_screenshot",
        "Capture de la page courante du navigateur piloté (image) pour voir la mise en page quand le texte ne suffit pas.",
        _obj({}),
    ),
    ToolSpec(
        "system_status",
        "État de l'ordinateur : système, fenêtre active, CPU, mémoire, disque, batterie, heure.",
        _obj({}),
    ),
    ToolSpec("lock_computer", "Verrouille la session de l'utilisateur.", _obj({})),
    ToolSpec(
        "remember",
        "Enregistre une information durable dans la mémoire IRIS de l'utilisateur (préférence, fait, décision, promesse).",
        _obj({"text": {"type": "string"}}, ["text"]),
    ),
    ToolSpec(
        "search_memory",
        "Recherche dans la mémoire IRIS de l'utilisateur (notes, faits, décisions passées).",
        _obj({"query": {"type": "string"}}, ["query"]),
    ),
    ToolSpec(
        "create_task",
        "Lance une tâche longue en arrière-plan (recherche approfondie, rédaction, développement complet). L'utilisateur sera prévenu vocalement à la fin. "
        "À utiliser quand la demande prendrait plusieurs minutes et que l'utilisateur n'attend pas de réponse immédiate.",
        _obj(
            {
                "title": {"type": "string", "description": "Titre court"},
                "instructions": {"type": "string", "description": "Instructions complètes et autonomes pour la tâche"},
            },
            ["title", "instructions"],
        ),
    ),
]


# Groupes d'outils : tout exposer à chaque demande poussait le modèle vers la souris et les captures d'écran
# pour des tâches qui n'en ont aucun besoin (trace réelle : une simple demande YouTube a fini en clics à l'aveugle).
SCREEN_TOOLS = {"take_screenshot", "screen_info", "mouse_move", "mouse_click", "mouse_drag", "scroll", "find_on_screen", "click_text"}
KEYBOARD_TOOLS = {"type_text", "press_keys"}
# Tous les outils du navigateur. « web_back » et « web_press » y manquaient : en mode 100 % local,
# le modèle se voyait encore offrir deux outils web, alors que la promesse est que rien ne sort.
WEB_TOOLS = {"web_search", "web_open", "web_login", "web_read", "web_click", "web_fill",
             "web_screenshot", "web_back", "web_press"}


def tool_specs(ctx: ToolContext, *, screen: bool = True, keyboard: bool = True, web: bool = True) -> list[ToolSpec]:
    specs = list(TOOL_SPECS)
    if ctx.create_task is None:
        specs = [s for s in specs if s.name != "create_task"]
    exclus: set[str] = set()
    if not screen:
        exclus |= SCREEN_TOOLS
    if not keyboard:
        exclus |= KEYBOARD_TOOLS
    if not web:
        exclus |= WEB_TOOLS
    return [s for s in specs if s.name not in exclus]


OCR_INDISPO = (
    "La lecture de l'écran (OCR) n'est pas disponible sur cet ordinateur. "
    "Ne clique surtout pas à l'aveugle avec mouse_click : utilise les outils directs "
    "(play_youtube, open_url, open_application, press_keys), ou explique à l'utilisateur ce qu'il doit faire lui-même."
)


def _err(message: str) -> dict:
    return {"content": message, "is_error": True}


def needs_confirmation(policy: str, command: str) -> bool:
    if policy == "never":
        return False
    if policy == "always":
        return True
    return actions.is_dangerous_command(command)


def make_tool_runner(ctx: ToolContext) -> Callable[[str, dict], Awaitable[Any]]:
    async def run(name: str, args: dict) -> Any:
        result = await _run_inner(ctx, name, args or {})
        if ctx.routines is not None and not (isinstance(result, dict) and result.get("is_error")):
            ctx.routines.record(name, args or {})
        return result

    return run


async def _run_inner(ctx: ToolContext, name: str, args: dict) -> Any:

    if name in ("find_on_screen", "click_text"):
        from .pc import actions as _a

        if not await asyncio.to_thread(_a.ocr_available):
            return _err(OCR_INDISPO)
    if True:
        policy = ctx.settings.user.confirm_commands
        if name in ("mouse_move", "mouse_click", "mouse_drag", "scroll", "find_on_screen", "click_text", "screen_info") and not ctx.settings.user.computer_use:
            return _err("Le contrôle d'écran est désactivé dans Paramètres › Contrôle de l'ordinateur.")
        # Courriel, SMS, appel : trois actions qu'on ne rattrape pas. Le module refuse
        # structurellement d'agir sans un accord obtenu juste avant — ce n'est pas un drapeau qu'on
        # peut oublier de poser, c'est un objet que seule la confirmation produit.
        if name == "envoyer_courriel":
            if ctx.courriel is None:
                return _err("Le service de courriel n'est pas disponible.")
            try:
                resultat = await ctx.courriel.envoyer_apres_accord(
                    args.get("destinataires", ""), args.get("sujet", ""), args.get("corps", ""),
                    ctx.confirm, cc=args.get("copie") or None,
                )
            except Exception as exc:
                return _err(str(exc))
            if resultat.get("envoye"):
                ctx.consent.log("courriel_envoye", agent=ctx.agent, detail=", ".join(resultat.get("destinataires", [])))
            return json.dumps(resultat, ensure_ascii=False)

        if name in ("envoyer_sms", "passer_un_appel"):
            if ctx.telephonie is None:
                return _err("Le service de téléphonie n'est pas disponible.")
            try:
                if name == "envoyer_sms":
                    resultat = await ctx.telephonie.envoyer_sms_apres_accord(
                        args.get("numero", ""), args.get("message", ""), ctx.confirm)
                else:
                    resultat = await ctx.telephonie.appeler_apres_accord(args.get("numero", ""), ctx.confirm)
            except Exception as exc:
                return _err(str(exc))
            return json.dumps(resultat, ensure_ascii=False)

        if name.startswith("lunettes_"):
            if ctx.glasses is None:
                return _err("Le service des lunettes n'est pas disponible.")
            if name == "lunettes_etat":
                etat = ctx.glasses.status()
                if not etat.get("connected"):
                    return "Les lunettes ne sont pas connectées. Dernière connue : " + str((etat.get("remembered") or {}).get("name") or "aucune")
                appareil = etat.get("device") or {}
                charge = etat.get("battery")
                return "Lunettes {} ({}) connectées. Batterie : {}.".format(
                    appareil.get("name", "?"), appareil.get("address", "?"),
                    "{} %".format(charge) if charge is not None else "pas encore annoncée (elles l'envoient d'elles-mêmes, environ une fois par dizaine de minutes)")
            if name == "lunettes_envoyer":
                try:
                    contenu = bytes.fromhex((args.get("contenu") or "").replace(" ", ""))
                except ValueError:
                    return _err("Le contenu doit être de l'hexadécimal, par exemple « 050000 ».")
                try:
                    resultat = await ctx.glasses.envoyer_trame(int(args.get("commande", 0)), contenu)
                except ValueError as exc:
                    return _err(str(exc))
                except Exception as exc:
                    return _err("Envoi impossible : {}".format(exc))
                return json.dumps(resultat, ensure_ascii=False)
        if name.startswith("web_"):
            if ctx.web is None:
                return _err("Navigateur piloté indisponible.")
            try:
                if name == "web_search":
                    r = await asyncio.to_thread(ctx.web.search, args.get("query", ""))
                    ctx.consent.log("web_navigation", agent=ctx.agent, detail="recherche : " + r["query"])
                    return json.dumps(r, ensure_ascii=False)
                if name == "web_open":
                    r = await asyncio.to_thread(ctx.web.open, args.get("url", ""))
                    ctx.consent.log("web_navigation", agent=ctx.agent, detail=r["url"])
                    return f"Page ouverte : {r['title']} — {r['url']}. Appelle web_read pour voir le contenu."
                if name == "web_login":
                    r = await asyncio.to_thread(ctx.web.login, args.get("site", ""))
                    ctx.consent.log("web_login", agent=ctx.agent, detail=f"{r['site']} → {r['status']}")
                    status = r["status"]
                    if status in ("logged_in", "already_logged_in"):
                        return f"Connecté à {r['site']} ({r['title']}) — {r['url']}. Appelle web_read pour voir le contenu."
                    if status == "no_login_form":
                        return f"Aucun formulaire de connexion sur {r['url']} (peut-être déjà connecté). Appelle web_read."
                    return _err(f"Connexion à {r['site']} non confirmée (page : {r['url']}). {'Un contrôle de sécurité a été affiché : demande à l’utilisateur de le résoudre dans la fenêtre du navigateur puis réessaie.' if r.get('captcha') else 'Vérifie les identifiants dans Paramètres › Comptes web.'}")
                if name == "web_read":
                    r = await asyncio.to_thread(ctx.web.read)
                    return json.dumps(r, ensure_ascii=False)
                if name == "web_click":
                    r = await asyncio.to_thread(ctx.web.click, args.get("target", ""))
                    ctx.consent.log("web_navigation", agent=ctx.agent, detail=r["url"])
                    return f"Cliqué sur « {r['clicked']} » → {r['title']} — {r['url']}. Appelle web_read pour voir le contenu."
                if name == "web_fill":
                    r = await asyncio.to_thread(ctx.web.fill, args.get("target", ""), args.get("value", ""), bool(args.get("submit")))
                    return f"Champ « {r['filled']} » rempli. Page : {r['url']}"
                if name == "web_press":
                    r = await asyncio.to_thread(ctx.web.press, args.get("key", "Enter"))
                    return f"Touche {r['pressed']} envoyée. Page : {r['url']}"
                if name == "web_back":
                    r = await asyncio.to_thread(ctx.web.back)
                    return f"Retour : {r['title']} — {r['url']}"
                if name == "web_screenshot":
                    try:
                        ctx.consent.check("screen", agent=ctx.agent)
                    except (ConsentRequired, LocalOnlyMode):
                        return _err("Les captures ne sont pas autorisées (consentement « Captures d'écran »).")
                    r = await asyncio.to_thread(ctx.web.screenshot)
                    ctx.capture.pulse_screen()
                    return {"content": [{"type": "image", "source": {"type": "base64", "media_type": r["media_type"], "data": r["data"]}}, {"type": "text", "text": f"Capture de {r['url']}"}], "is_error": False}
            except Exception as exc:
                return _err(f"Navigateur : {exc}")
        if name == "screen_info":
            return json.dumps(await asyncio.to_thread(actions.screen_size))
        if name == "mouse_move":
            return await asyncio.to_thread(actions.mouse_move, float(args.get("x")), float(args.get("y")))
        if name == "mouse_click":
            x, y = args.get("x"), args.get("y")
            return await asyncio.to_thread(actions.mouse_click, float(x) if x is not None else None, float(y) if y is not None else None, args.get("button") or "left", int(args.get("clicks") or 1))
        if name == "mouse_drag":
            return await asyncio.to_thread(actions.mouse_drag, float(args["x1"]), float(args["y1"]), float(args["x2"]), float(args["y2"]))
        if name == "scroll":
            x, y = args.get("x"), args.get("y")
            return await asyncio.to_thread(actions.scroll, int(args.get("amount") or -5), float(x) if x is not None else None, float(y) if y is not None else None)
        if name == "find_on_screen":
            hits = await asyncio.to_thread(actions.find_on_screen, args.get("text", ""))
            if not hits:
                return "Texte introuvable à l'écran. Prends une capture d'écran pour voir ce qui est affiché, ou essaie un autre libellé."
            return json.dumps(hits, ensure_ascii=False)
        if name == "click_text":
            return await asyncio.to_thread(actions.click_text, args.get("text", ""), args.get("button") or "left", int(args.get("clicks") or 1), int(args.get("occurrence") or 1))
        if name == "list_applications":
            from .pc.apps import index

            hits = await asyncio.to_thread(index.search, args.get("query", ""), 8)
            return json.dumps([{"name": h["name"], "kind": h["kind"]} for h in hits], ensure_ascii=False) if hits else "Aucune application correspondante."
        if name == "create_routine":
            if ctx.routines is None:
                return _err("Routines indisponibles.")
            routine = ctx.routines.create(args.get("name", ""), args.get("trigger") or args.get("name", ""), args.get("steps") or [])
            return f"Routine « {routine['name']} » enregistrée ({len(routine['steps'])} étapes). Déclencheur : « {routine['trigger']} »."
        if name == "run_routine":
            if ctx.routines is None:
                return _err("Routines indisponibles.")
            routine = ctx.routines.find_by_name(args.get("name", ""))
            if not routine:
                return _err(f"Aucune routine nommée « {args.get('name', '')} ».")
            results = await ctx.routines.run(routine, lambda n, a: _run_inner(ctx, n, a))
            ok = sum(1 for r in results if r["ok"])
            return f"Routine « {routine['name']} » exécutée : {ok}/{len(results)} étapes réussies."
        if name == "set_reminder":
            if ctx.reminders is None:
                return _err("Rappels indisponibles.")
            item = ctx.reminders.create(args.get("text", ""), args.get("minutes"), args.get("at"))
            return f"Rappel programmé pour {item['due_at'][11:16]} le {item['due_at'][:10]} : {item['text']}"

        if name == "open_application":
            return await asyncio.to_thread(actions.open_application, args.get("name", ""))
        if name == "open_url":
            return await asyncio.to_thread(actions.open_url, args.get("url", ""))
        if name == "play_youtube":
            result = await asyncio.to_thread(actions.play_youtube, args.get("query", ""))
            playing = result["playing"]
            return f"Lecture lancée : « {playing['title']} » ({playing['channel']}) — {playing['url']}"
        if name == "open_path":
            return await asyncio.to_thread(actions.open_path, args.get("path", ""))
        if name == "search_files":
            found = await asyncio.to_thread(
                actions.search_files, args.get("query", ""), args.get("folder"), int(args.get("max_results") or 20)
            )
            return "\n".join(found) if found else "Aucun fichier trouvé."
        if name == "list_directory":
            items = await asyncio.to_thread(actions.list_directory, args.get("path", "~"))
            return json.dumps(items, ensure_ascii=False)
        if name == "read_file":
            return await asyncio.to_thread(actions.read_file, args.get("path", ""))
        if name == "write_file":
            path = args.get("path", "")
            if policy == "always":
                approved = await ctx.confirm("Écrire un fichier", path)
                if not approved:
                    return _err("L'utilisateur a refusé l'écriture de ce fichier.")
            result = await asyncio.to_thread(actions.write_file, path, args.get("content", ""), bool(args.get("append")))
            ctx.consent.log("file_written", agent=ctx.agent, detail=path)
            return result
        if name == "run_command":
            command = args.get("command", "")
            reason = args.get("reason", "")
            if needs_confirmation(policy, command):
                approved = await ctx.confirm(f"Exécuter une commande : {reason or 'sans description'}", command)
                if not approved:
                    return _err("L'utilisateur a refusé l'exécution de cette commande.")
            timeout = int(args.get("timeout") or 60)
            result = await asyncio.to_thread(actions.run_command, command, timeout)
            ctx.consent.log("command_executed", agent=ctx.agent, detail=command)
            return f"Code de retour : {result['code']}\n{result['output']}"
        if name == "type_text":
            return await asyncio.to_thread(actions.type_text, args.get("text", ""))
        if name == "press_keys":
            return await asyncio.to_thread(actions.press_keys, args.get("combo", ""))
        if name == "take_screenshot":
            try:
                ctx.consent.check("screen", agent=ctx.agent)
            except ConsentRequired:
                return _err(
                    "L'utilisateur n'a pas autorisé les captures d'écran. Demande-lui d'activer le consentement "
                    "« Captures d'écran » dans Confidentialité, puis réessaie."
                )
            except LocalOnlyMode:
                return _err("Mode 100 % local : aucune image ne peut être envoyée à un agent externe.")
            shot = await asyncio.to_thread(actions.take_screenshot)
            ctx.capture.pulse_screen()
            ctx.consent.log("external_send", data_type="screen", agent=ctx.agent, detail="capture d'écran envoyée à l'agent")
            return {
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": shot["media_type"], "data": shot["data"]}},
                    {"type": "text", "text": f"Capture d'écran {shot['width']}x{shot['height']} prise."},
                ],
                "is_error": False,
            }
        if name == "system_status":
            status = await asyncio.to_thread(actions.system_status)
            return json.dumps(status, ensure_ascii=False)
        if name == "lock_computer":
            return await asyncio.to_thread(actions.lock_computer)
        if name in ("create_watch", "list_watches", "stop_watch"):
            if ctx.watches is None:
                return _err("La surveillance n'est pas disponible.")
            if name == "create_watch":
                try:
                    w = ctx.watches.create(
                        args.get("name", ""), args.get("url", ""), args.get("criteria", ""),
                        int(args.get("interval_min") or 15), args.get("site", ""),
                    )
                except ValueError as exc:
                    return _err(str(exc))
                return (
                    f"Surveillance « {w['name']} » lancée : je relis la page toutes les {w['interval_min']} minutes et "
                    "je te préviens dès que tes critères sont remplis. Je ne conclurai aucun achat sans ton accord."
                )
            if name == "list_watches":
                items = ctx.watches.list()
                if not items:
                    return "Aucune surveillance en cours."
                return "\n".join(
                    f"- {w['name']} ({'active' if w['active'] else 'arrêtée'}, toutes les {w['interval_min']} min, "
                    f"{w['alerts']} alerte(s)) : {w['criteria'][:90]}"
                    for w in items
                )
            cible = (args.get("watch") or "").strip().lower()
            for w in ctx.watches.list():
                if cible in (w["id"].lower(), w["name"].lower()) or cible in w["name"].lower():
                    ctx.watches.stop(w["id"])
                    return f"Surveillance « {w['name']} » arrêtée."
            return _err("Surveillance introuvable. Demande « liste mes surveillances » pour voir les noms.")

        if name == "remember":
            item = ctx.memory.add(args.get("text", ""), source=ctx.agent, kind="fact")
            return f"Mémorisé (id {item['id'][:8]})."
        if name == "search_memory":
            hits = ctx.memory.search(args.get("query", ""), limit=8)
            if not hits:
                return "Aucun souvenir correspondant."
            return "\n".join(f"- [{h['created_at'][:10]}] {h['text']}" for h in hits)
        if name == "create_task":
            if ctx.create_task is None:
                return _err("Les tâches en arrière-plan ne sont pas disponibles ici.")
            task = await ctx.create_task(args.get("title", "Tâche"), args.get("instructions", ""), ctx.agent)
            return f"Tâche « {task['title']} » lancée (id {task['id'][:8]}). L'utilisateur sera prévenu à la fin."
        return _err(f"Outil inconnu : {name}")
