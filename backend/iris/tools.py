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
    hub: Any = None  # EventHub : pour publier des événements (ex. glasses.photo -> rafraîchit la galerie)
    courriel: Any = None  # Postier : envoi de courriels, jamais sans accord
    telephonie: Any = None  # Telephoniste : SMS et appels, jamais sans accord
    traduction: Any = None  # ServiceTraduction : traduire une conversation, tour par tour
    # VoiceListener : c'est LUI qui sait si un micro écoute vraiment. Sans lui, l'outil de traduction
    # marche encore (il arme le service), mais il ne peut plus dire « l'écoute est arrêtée » — et
    # promettre une traduction à quelqu'un dont le micro est fermé est le pire des ratés.
    voice: Any = None
    # ServiceOpenCode : déléguer le TRAVAIL DE PROGRAMMATION à OpenCode, l'agent de code de la
    # machine. Ce n'est pas un moteur de plus à côté d'OpenRouter — OpenCode consomme des
    # fournisseurs, il n'en est pas un. Tant qu'il n'est pas installé, ce champ reste None et
    # l'outil n'est même pas offert au modèle : IRIS se comporte exactement comme avant.
    opencode: Any = None
    # D'où vient la demande : « text », « voice », « task »… ChatService le connaît déjà et le
    # passait sans l'utiliser ici. Il sert à une seule chose, mais elle est décisive : AUCUNE
    # demande de confirmation n'est visible depuis la voix (rien dans voice/ n'écoute
    # « chat.confirm », telephonie.py:53 documente déjà le même trou pour le SMS). Ouvrir un modal
    # qu'on ne verra pas, c'est attendre 180 secondes puis refuser en silence.
    source: str = "text"


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
        "Pour développer une application ou un site, écris chaque fichier avec cet outil puis lance les commandes nécessaires avec run_command. "
        "Un chemin relatif se lit depuis le dossier de projets (~/Documents/IRIS) ; seuls ce dossier, le Bureau, Documents et "
        "Téléchargements sont accessibles. Remplacer un fichier existant, ou écrire hors du dossier de projets, demande confirmation.",
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
        "démarrer un serveur, git, etc. Explique en une phrase ce que fait la commande dans 'reason'. Les commandes dangereuses demandent confirmation. "
        "La commande tourne dans 'cwd' (défaut : le dossier de projets ~/Documents/IRIS) ; donne le dossier du projet plutôt que de faire cd.",
        _obj(
            {
                "command": {"type": "string"},
                "reason": {"type": "string", "description": "Ce que fait la commande, en langage simple"},
                "cwd": {"type": "string", "description": "Dossier de travail (dans le périmètre : dossier de projets, Bureau, Documents, Téléchargements)"},
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
        "read_screen_text",
        "Lit TOUT le texte affiché à l'écran, VERBATIM et dans l'ordre de lecture (de haut en bas, de "
        "gauche à droite), par OCR hors-ligne. Aucun modèle de vision : le texte est restitué exactement, "
        "sans résumé ni omission ni invention, et l'outil fonctionne en mode 100 % local. À utiliser dès "
        "qu'un utilisateur (en particulier malvoyant) demande « lis-moi l'écran », « décris l'écran » ou "
        "« qu'est-ce qu'il y a à l'écran » : donne-lui les mots exacts plutôt que de les deviner.",
        _obj({}),
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
        "Lance un appel téléphonique vers un numéro. L'utilisateur doit l'approuver avant que ça sonne. "
        "Si IRIS a sa propre ligne téléphonique, l'appel part de cette ligne et IRIS dit le texte de "
        "« message » au décroché ; sans ligne, c'est le composeur du téléphone de l'utilisateur qui s'ouvre.",
        _obj({
            "numero": {"type": "string"},
            "message": {"type": "string", "description": "Ce qu'IRIS dit au décroché quand elle appelle depuis sa propre ligne. Facultatif."},
        }, ["numero"]),
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
        "lunettes_photo",
        "Prend une photo avec la CAMÉRA des lunettes VELA et rapatrie l'image EN LOCAL sur "
        "l'ordinateur — elle ne part jamais chez un tiers. À utiliser dès qu'on demande « prends "
        "une photo », « capture ce que je vois », « qu'est-ce que je regarde », « photographie ça ». "
        "Sur la paire AUDIO (sans caméra), l'outil le dit franchement au lieu d'inventer une image ; "
        "tant que le format de trame caméra n'est pas confirmé sur le vrai matériel, il refuse aussi "
        "d'écrire des octets non prouvés (protège la puce) — relaie alors son explication telle quelle. "
        "reconnaissance=true prépare l'image pour une analyse, qui reste elle aussi locale.",
        _obj({"reconnaissance": {"type": "boolean", "description": "Préparer l'image pour analyse (défaut : non)"}}),
    ),
    ToolSpec(
        "traduire_conversation",
        "Ouvre le MODE TRADUCTION : IRIS écoute en continu la personne en face, traduit ce qu'elle "
        "dit à voix haute, et propose quoi répondre. À utiliser dès qu'on te demande de traduire ce "
        "que quelqu'un dit, de suivre une conversation dans une autre langue, ou de servir "
        "d'interprète (« traduis ce qu'il dit », « je parle avec un anglophone »). Précise la langue "
        "de l'interlocuteur si elle est nommée ; sans précision, c'est l'anglais. La traduction est "
        "CONSÉCUTIVE : elle arrive après chaque phrase, pas pendant. Réponds ensuite exactement par "
        "la phrase que l'outil te renvoie, sans rien y ajouter : elle dit aussi comment sortir.",
        _obj({"langue": {"type": "string", "description": "Langue de l'interlocuteur : « anglais », « espagnol », « en », « es »…"}}),
    ),
    ToolSpec(
        "arreter_traduction",
        "Ferme le mode traduction. À utiliser quand on demande d'arrêter de traduire. "
        "(À la voix, « Iris, arrête » referme le mode sans passer par toi.)",
        _obj({}),
    ),
    ToolSpec(
        "traduire_ma_reponse",
        "Traduit CE QUE L'UTILISATEUR veut dire, vers la langue de son interlocuteur — l'autre sens "
        "que traduire_conversation. À utiliser pour « comment je lui dis que… », « traduis-lui que… ». "
        "La phrase traduite s'AFFICHE et n'est pas lue à voix haute : la synthèse d'IRIS n'a pas de "
        "paramètre de langue et déformerait une phrase étrangère. Donne-la telle quelle dans ta réponse.",
        _obj({"texte": {"type": "string", "description": "Ce que l'utilisateur veut dire, dans sa langue"}}, ["texte"]),
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
        "retrouver_site",
        "Cherche dans l'historique de navigation à quel site correspond une demande vague "
        "(« connecte-moi à mon cégep », « ouvre mon compte de paiement »). Rends les domaines "
        "trouvés pour choisir. À utiliser AVANT web_login quand on ne sait pas encore l'adresse exacte.",
        _obj({"terme": {"type": "string", "description": "Ce que l'utilisateur a dit du site"}}, ["terme"]),
    ),
    ToolSpec(
        "importer_identifiants",
        "Récupère depuis le navigateur de l'utilisateur les identifiants d'un site et les dépose "
        "dans le coffre, pour pouvoir s'y connecter ensuite avec web_login. À utiliser quand "
        "web_login dit qu'un site n'est pas enregistré, mais que l'utilisateur s'y connecte "
        "habituellement dans son navigateur. Tu ne vois jamais le mot de passe, et l'utilisateur "
        "doit confirmer l'import.",
        _obj({"terme": {"type": "string", "description": "Nom ou domaine du site (ex. netlify, omnivox)"}}, ["terme"]),
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
    ToolSpec(
        "deleguer_programmation",
        "Confie un travail de PROGRAMMATION à OpenCode, l'agent de code installé sur cet ordinateur : "
        "corriger un bogue, ajouter une fonctionnalité, remanier du code dans un projet qui existe déjà "
        "(« corrige le bogue dans mon site », « ajoute une page à flowcare »). Préfère-le à write_file et "
        "run_command dès qu'il s'agit de modifier un projet existant : OpenCode lit le code avant d'écrire. "
        "Tu DOIS donner le dossier du projet — c'est le dossier que l'utilisateur approuve, pas ta phrase. "
        "Si tu ne sais pas duquel il s'agit, demande-le-lui AVANT d'appeler l'outil : ne devine pas un chemin.",
        _obj(
            {
                "dossier": {"type": "string", "description": "Chemin du projet, ex. ~/Documents/IRIS/site-flowcare"},
                "consigne": {"type": "string", "description": "Ce qu'OpenCode doit faire, complet et autonome"},
                # Ce mot entre dans la phrase que l'utilisateur lit avant d'approuver
                # (« Envoyer OpenCode corriger dans site-flowcare ») : c'est là toute son utilité.
                "genre": {"type": "string", "enum": ["correction", "ajout", "revue", "tache"],
                          "description": "Nature du travail ; sert à annoncer ce qu'on confie"},
            },
            ["dossier", "consigne"],
        ),
    ),
]


# Groupes d'outils : tout exposer à chaque demande poussait le modèle vers la souris et les captures d'écran
# pour des tâches qui n'en ont aucun besoin (trace réelle : une simple demande YouTube a fini en clics à l'aveugle).
SCREEN_TOOLS = {"take_screenshot", "read_screen_text", "screen_info", "mouse_move", "mouse_click", "mouse_drag", "scroll", "find_on_screen", "click_text"}
# Filet de sécurité d'accessibilité : dès que le contrôle d'écran est autorisé (computer_use), ces
# deux outils de LECTURE restent offerts même quand la demande n'a pas été classée « écran ». Sans
# cela, « lis-moi l'écran » mal détecté laissait IRIS répondre sans jamais regarder l'écran.
SCREEN_READ_TOOLS = {"take_screenshot", "read_screen_text"}
KEYBOARD_TOOLS = {"type_text", "press_keys"}
# Tous les outils du navigateur. « web_back » et « web_press » y manquaient : en mode 100 % local,
# le modèle se voyait encore offrir deux outils web, alors que la promesse est que rien ne sort.
WEB_TOOLS = {"web_search", "web_open", "web_login", "web_read", "web_click", "web_fill",
             "web_screenshot", "web_back", "web_press"}


# --------------------------------------------------------------------- délégation à OpenCode
# Le service vit dans `iris/opencode.py`. Ces quelques fonctions sont le SEUL point de contact
# entre lui et le reste d'IRIS, et elles acceptent plusieurs noms de méthodes à dessein : le
# service a été écrit en parallèle de ce câblage, et une faute de nom ici rejouerait exactement
# l'incident du 5 septembre 2026 — deux modules entiers, écrits et testés, restés inutilisables
# toute une journée parce que personne ne les avait branchés. Le jour où les noms sont figés, on
# peut réduire ces listes à un seul nom ; il ne faut pas supprimer l'indirection sans le vérifier.
NOMS_UTILISABLE = ("utilisable", "disponible", "est_disponible", "pret", "configure")
NOMS_RAISON = ("pourquoi_pas_pret", "pourquoi_indisponible", "raison_indisponible", "pourquoi")
NOMS_DELEGATION = ("deleguer_apres_accord", "executer_apres_accord", "confier_apres_accord", "deleguer")

# Ce que dit IRIS quand le service est là mais qu'il ne sait pas expliquer son propre silence.
# Constat du 5 septembre 2026 : aucun binaire `opencode` sur cette machine, ni dans le PATH ni
# ailleurs. Seuls le kit de greffons et le SDK 1.18.23 sont posés, plus l'application de bureau,
# qui n'embarque aucun exécutable en ligne de commande.
OPENCODE_ABSENT = (
    "OpenCode n'est pas installé sur cet ordinateur : je ne peux pas déléguer la programmation "
    "pour l'instant. Je peux encore écrire les fichiers moi-même si tu veux."
)

# La conséquence, assumée, du trou de confirmation vocale : rien dans voice/ n'écoute
# « chat.confirm ». Un accord demandé pendant que Miguel parle ne s'affiche que dans la fenêtre
# d'IRIS. Plutôt que d'ouvrir un modal que personne ne regarde — 180 secondes d'attente puis un
# refus silencieux —, on le dit tout de suite, à voix haute, ce qui est la seule chose utile.
PAS_A_LA_VOIX = (
    "Je peux confier ça à OpenCode, mais pas depuis la voix : tu dois approuver le dossier à "
    "l'écran. Ouvre la fenêtre d'IRIS et redemande-le-moi là, je m'en occupe tout de suite."
)


def _premier_membre(objet: Any, noms: tuple[str, ...]) -> Any:
    """Le premier attribut existant parmi `noms`. Renvoie la VALEUR, pas le nom : un booléen
    faux (`utilisable = False`) doit être rendu tel quel, pas confondu avec « absent »."""
    for nom in noms:
        if hasattr(objet, nom):
            return getattr(objet, nom)
    return None


def _valeur_ou_appel(membre: Any) -> Any:
    """Accepte indifféremment une méthode `utilisable()` ou une propriété `utilisable`."""
    return membre() if callable(membre) else membre


def opencode_utilisable(service: Any) -> bool:
    """OpenCode peut-il vraiment travailler maintenant ? Au moindre doute : non.

    C'est cette fonction qui garde la fonctionnalité INACTIVE par construction, et pas un drapeau
    de configuration qu'on peut oublier de poser."""
    if service is None:
        return False
    membre = _premier_membre(service, NOMS_UTILISABLE)
    if membre is None:
        return False
    try:
        return bool(_valeur_ou_appel(membre))
    except Exception:
        return False


def opencode_raison(service: Any) -> str:
    """La phrase que le service donne pour expliquer qu'il ne peut pas travailler, en français."""
    membre = _premier_membre(service, NOMS_RAISON)
    try:
        raison = _valeur_ou_appel(membre) if membre is not None else ""
    except Exception:
        raison = ""
    return str(raison or "").strip() or OPENCODE_ABSENT


def parametres_delegation(deleguer: Any) -> set[str]:
    """Les paramètres que la méthode de délégation accepte réellement.

    On les lit au lieu de les supposer : `Contremaitre.deleguer_apres_accord` prend
    (genre, dossier, consigne, confirmer, source) et `genre` n'a pas de valeur par défaut. Appeler
    seulement par (dossier, consigne, confirmer) lèverait un TypeError au moment précis où Miguel
    demande de corriger un bogue — c'est-à-dire jamais pendant les tests, toujours en démonstration.
    """
    import inspect

    try:
        return set(inspect.signature(deleguer).parameters)
    except (TypeError, ValueError):  # objet non introspectable
        return set()


async def _appeler_delegation(deleguer: Any, *, genre: str, dossier: str, consigne: str,
                              confirmer: ConfirmFn, source: str) -> Any:
    """Appelle la délégation par mot-clé quand la méthode nomme ses paramètres, sinon dans l'ordre
    (dossier, consigne, confirmer) — celui de `envoyer_sms_apres_accord`."""
    import inspect

    parametres = parametres_delegation(deleguer)
    if {"dossier", "consigne"} <= parametres:
        arguments: dict[str, Any] = {"dossier": dossier, "consigne": consigne}
        if "genre" in parametres:
            arguments["genre"] = genre
        if "source" in parametres:
            arguments["source"] = source
        nom_confirme = next((n for n in ("confirmer", "confirm", "confirmation") if n in parametres), None)
        if nom_confirme:
            arguments[nom_confirme] = confirmer
        retour = deleguer(**arguments)
    else:
        retour = deleguer(dossier, consigne, confirmer)
    if inspect.isawaitable(retour):
        retour = await retour
    return retour


def tool_specs(ctx: ToolContext, *, screen: bool = True, keyboard: bool = True, web: bool = True) -> list[ToolSpec]:
    specs = list(TOOL_SPECS)
    if ctx.create_task is None:
        specs = [s for s in specs if s.name != "create_task"]
    # OpenCode absent = outil absent de la liste, donc IRIS strictement identique à ce qu'elle est
    # aujourd'hui. On ne montre pas au modèle une porte qui ne s'ouvre pas : il l'essaierait au lieu
    # d'écrire les fichiers lui-même, et une démonstration se jouerait sur un message d'erreur.
    # `getattr` et non `ctx.opencode` : plusieurs tests construisent un contexte minimal.
    if not opencode_utilisable(getattr(ctx, "opencode", None)):
        specs = [s for s in specs if s.name != "deleguer_programmation"]
    exclus: set[str] = set()
    if not screen:
        exclus |= SCREEN_TOOLS
        # Le contrôle d'écran est activé dans les réglages : on garde toujours les outils de lecture
        # (capture + OCR verbatim), pour qu'un « lis-moi l'écran » non détecté ne soit jamais muet.
        computer_use = bool(getattr(getattr(getattr(ctx, "settings", None), "user", None), "computer_use", False))
        if computer_use:
            exclus -= SCREEN_READ_TOOLS
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

    if name in ("find_on_screen", "click_text", "read_screen_text"):
        from .pc import actions as _a

        if not await asyncio.to_thread(_a.ocr_available):
            return _err(OCR_INDISPO)
    if True:
        policy = ctx.settings.user.confirm_commands
        if name in ("mouse_move", "mouse_click", "mouse_drag", "scroll", "find_on_screen", "click_text", "screen_info", "read_screen_text") and not ctx.settings.user.computer_use:
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

        # Déléguer la programmation à OpenCode. Même serrure que le courriel et le SMS : le service
        # n'accepte pas une intention, il n'accepte qu'un accord — et l'accord porte sur le DOSSIER
        # RÉSOLU, pas sur la phrase dite. Un oui donné pour « Documents/IRIS/site-flowcare » ne doit
        # jamais rester valable si la cible devient le dépôt d'IRIS lui-même : le journal d'OpenCode
        # montre qu'il a déjà travaillé sur ce backend (appels à 127.0.0.1:8765), et un agent envoyé
        # « corriger mon site » qui lit un .env lit aussi les clés ElevenLabs et de licence.
        if name == "deleguer_programmation":
            service = getattr(ctx, "opencode", None)
            if service is None:
                return _err("La délégation à OpenCode n'est pas branchée sur cet appareil.")
            if not opencode_utilisable(service):
                return _err(opencode_raison(service))
            dossier = (args.get("dossier") or "").strip()
            consigne = (args.get("consigne") or "").strip()
            if not dossier:
                return _err(
                    "Il manque le dossier du projet. Demande-le à l'utilisateur avant de rappeler "
                    "l'outil : c'est le dossier qu'il approuve, et le deviner serait envoyer un "
                    "agent modifier des fichiers au hasard."
                )
            if not consigne:
                return _err("Il manque la consigne : dis à OpenCode ce qu'il doit faire, complètement.")
            deleguer = _premier_membre(service, NOMS_DELEGATION)
            if deleguer is None or not callable(deleguer):
                return _err(
                    "Le service OpenCode est là mais ne sait pas déléguer : aucune méthode "
                    f"parmi {', '.join(NOMS_DELEGATION)}. C'est un défaut de câblage, pas un refus."
                )
            source = getattr(ctx, "source", "text") or "text"
            # Le trou vocal. Le service sait déjà le traiter — sa phrase est meilleure que la nôtre,
            # elle NOMME le dossier —, alors on le laisse faire dès qu'il accepte `source`. Sinon
            # on refuse ici, parce que le pire des comportements serait d'ouvrir une modale que
            # Miguel ne verra pas : 180 secondes d'attente, puis un « refusé » silencieux qui
            # ressemble à une panne. Ce n'est pas une erreur d'outil, c'est une phrase à relayer.
            if source == "voice" and "source" not in parametres_delegation(deleguer):
                return PAS_A_LA_VOIX
            try:
                resultat = await _appeler_delegation(
                    deleguer, genre=(args.get("genre") or "tache").strip().lower(),
                    dossier=dossier, consigne=consigne, confirmer=ctx.confirm, source=source,
                )
            except Exception as exc:
                # Périmètre refusé, dossier inexistant, consigne vide : le service parle français et
                # ses messages sont écrits pour être lus à voix haute. On les relaie tels quels.
                return _err(str(exc) or f"Délégation impossible : {exc!r}")
            if isinstance(resultat, dict):
                # Le dossier que le service a RÉSOLU fait foi ; la chaîne dite par le modèle ne
                # désigne pas forcément le même endroit (mesuré : un chemin « \\?\… » se normalise
                # en tout autre chose).
                cible = str(resultat.get("dossier") or dossier)
                accorde = bool(resultat.get("ok"))
                # Le registre chaîné répond déjà à « qu'a fait IRIS » pour le courriel et les
                # commandes. Le service y écrit lui-même dès qu'il a reçu le registre — trois
                # entrées, opencode_delegue / opencode_termine / opencode_refus. On ne trace donc
                # ici QUE s'il ne peut pas le faire : deux lignes pour un seul geste rendraient le
                # journal illisible, et un journal illisible ne prouve plus rien.
                if getattr(service, "registre", None) is None:
                    ctx.consent.log(
                        "opencode_termine" if accorde else "opencode_refuse",
                        agent=ctx.agent, detail=f"{cible} — {consigne[:200]}",
                    )
                phrase = resultat.get("message") or resultat.get("phrase")
                if phrase:
                    # À la voix, un « non » du service n'est pas un échec d'outil : c'est le
                    # renvoi vers l'écran, la seule chose utile à dire. Le marquer en erreur ferait
                    # répondre « je n'ai pas réussi », qui est faux et décourageant.
                    if accorde or source == "voice":
                        return str(phrase)
                    return _err(str(phrase))
                return json.dumps(resultat, ensure_ascii=False)
            return str(resultat)

        if name in ("envoyer_sms", "passer_un_appel"):
            if ctx.telephonie is None:
                return _err("Le service de téléphonie n'est pas disponible.")
            try:
                if name == "envoyer_sms":
                    resultat = await ctx.telephonie.envoyer_sms_apres_accord(
                        args.get("numero", ""), args.get("message", ""), ctx.confirm)
                else:
                    resultat = await ctx.telephonie.appeler_apres_accord(
                        args.get("numero", ""), ctx.confirm, message=args.get("message", ""))
            except Exception as exc:
                return _err(str(exc))
            return json.dumps(resultat, ensure_ascii=False)

        # Traduire une conversation. Deux objets peuvent la porter, et l'ordre compte : l'écoute
        # (`ctx.voice`) sait si un micro tourne vraiment, le service tout seul l'ignore — et
        # promettre une traduction à quelqu'un dont le micro est fermé est le pire des ratés.
        if name in ("traduire_conversation", "arreter_traduction", "traduire_ma_reponse"):
            service = ctx.traduction if ctx.traduction is not None else getattr(ctx.voice, "traduction", None)
            if service is None:
                return _err("La traduction n'est pas disponible : le service n'est pas branché sur cet appareil.")
            try:
                if name == "traduire_conversation":
                    langue = (args.get("langue") or "").strip()
                    if ctx.voice is not None:
                        return ctx.voice.demander_traduction(langue).get("phrase") or "Mode traduction ouvert."
                    return service.demarrer(langue)
                if name == "arreter_traduction":
                    if ctx.voice is not None:
                        return ctx.voice.arreter_traduction("demande").get("phrase") or "C'est fini."
                    return service.arreter("demande")
                texte = (args.get("texte") or "").strip()
                if not texte:
                    return _err("Il manque la phrase à traduire.")
                resultat = await service.traduire_ma_reponse(texte)
            except Exception as exc:
                return _err(f"Traduction impossible : {exc}")
            if not getattr(resultat, "ok", False):
                return _err(getattr(resultat, "raison", "") or "Je n'ai pas réussi à traduire.")
            return f"À lui dire : {resultat.traduction}"

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
            if name == "lunettes_photo":
                # La caméra réutilise la connexion BLE existante (elle n'en rouvre pas). Le module
                # est honnête par construction : il lève CameraIndisponible sur la paire audio, et
                # ProtocoleNonConfirme tant que l'en-tête de trame n'est pas prouvé (sauf mode
                # exploration). On relaie ces messages tels quels — jamais une image inventée.
                from .lunettes_camera import (
                    CameraLunettes, CameraIndisponible, ProtocoleNonConfirme,
                )

                cam = CameraLunettes(ctx.glasses)
                try:
                    res = await cam.prendre_photo(reconnaissance=bool(args.get("reconnaissance")))
                except (CameraIndisponible, ProtocoleNonConfirme) as exc:
                    return _err(str(exc))
                except Exception as exc:
                    return _err("Photo impossible : {}".format(exc))
                if res.ok and res.chemin:
                    ctx.consent.log("lunettes_photo", agent=ctx.agent, detail=res.chemin)
                    # Comme la route HTTP du bouton : prévenir l'UI pour qu'elle rafraîchisse la
                    # galerie même quand la photo a été demandée à la voix. Gardé sur hub présent.
                    if getattr(ctx, "hub", None) is not None:
                        ctx.hub.publish("glasses.photo", chemin=res.chemin, octets=res.octets)
                    return "{} Fichier : {}".format(res.constat, res.chemin)
                # Pas d'image reconstituée : on rend le constat honnête (paquets reçus, format à
                # confirmer), pas un faux succès.
                return res.constat
        if name == "retrouver_site":
            from . import historique_web

            if not historique_web.disponible():
                return historique_web.pourquoi_indisponible()
            sites = historique_web.chercher(args.get("terme", ""))
            if not sites:
                return f"Je n'ai rien trouvé dans l'historique pour « {args.get('terme','')} ». Dis-moi l'adresse et j'y vais."
            return json.dumps([s.en_dict() for s in sites], ensure_ascii=False)

        if name == "importer_identifiants":
            from . import identifiants_navigateur as _idn

            if not _idn.disponible():
                return _err("Aucun navigateur avec des identifiants enregistrés n'a été trouvé sur cet ordinateur.")
            terme = (args.get("terme") or "").strip()
            # noms_correspondants ne déchiffre RIEN et applique la même règle que l'import : ce qu'on
            # montre à l'utilisateur est donc exactement ce qui sera écrit. Un Local State abîmé ne
            # doit pas non plus faire tomber l'outil.
            try:
                correspondances = _idn.noms_correspondants(terme)
            except Exception as exc:
                return _err(f"Je n'ai pas pu lire les identifiants du navigateur : {type(exc).__name__}.")
            if not correspondances:
                return f"Je n'ai trouvé aucun identifiant enregistré pour « {terme} » dans ton navigateur."
            if len(correspondances) > _idn.MAX_CORRESPONDANCES:
                return (f"« {terme} » correspond à {len(correspondances)} comptes différents. "
                        "Précise le site (par exemple son adresse) pour que je n'en importe pas trop d'un coup.")
            # On NOMME chaque compte, en entier : domaine ET utilisateur. Refus = rien n'est importé.
            libelle = ", ".join(f"{c['domaine']} ({c['utilisateur']})" for c in correspondances)
            approuve = await ctx.confirm("Récupérer des identifiants du navigateur", f"{libelle} — vers le coffre d'IRIS")
            if not approuve:
                return "Je n'ai rien importé : tu n'as pas confirmé."
            resultat = await asyncio.to_thread(_idn.importer_dans_le_coffre, terme, ctx.secrets)
            if resultat["importes"]:
                ctx.consent.log("identifiants_importes", agent=ctx.agent, detail=", ".join(resultat["sites"]))
            return resultat["message"]

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
                    # Mur de vérification humaine : IRIS ne le résout JAMAIS. Elle le dit et propose
                    # que l'utilisateur fasse la vérification lui-même (aucun contournement de CAPTCHA).
                    if r.get("verification_humaine"):
                        return _err(f"{r['verification_humaine']} (page : {r['url']})")
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
        if name == "read_screen_text":
            # Comme find_on_screen : OCR local, aucune image ne sort de la machine. On rend le texte
            # tel quel, sans le faire relire par un modèle qui pourrait le résumer ou l'inventer.
            texte = await asyncio.to_thread(actions.read_screen_text)
            return texte or "L'écran ne contient aucun texte lisible pour l'instant."
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
            try:
                return await asyncio.to_thread(actions.open_path, args.get("path", ""))
            except actions.HorsPerimetre as exc:
                return _err(str(exc))
        if name == "search_files":
            found = await asyncio.to_thread(
                actions.search_files, args.get("query", ""), args.get("folder"), int(args.get("max_results") or 20)
            )
            return "\n".join(found) if found else "Aucun fichier trouvé."
        if name == "list_directory":
            items = await asyncio.to_thread(actions.list_directory, args.get("path", "~"))
            return json.dumps(items, ensure_ascii=False)
        if name == "read_file":
            try:
                return await asyncio.to_thread(actions.read_file, args.get("path", ""))
            except actions.HorsPerimetre as exc:
                return _err(str(exc))
        if name == "write_file":
            # Jusqu'au 6 septembre 2026, on ne demandait l'accord que si confirm_commands valait
            # « always » — et le réglage par défaut est « dangerous ». Un modèle pouvait donc
            # remplacer n'importe quel fichier existant, n'importe où, sans qu'on le voie. Deux
            # cas demandent maintenant TOUJOURS l'accord, quel que soit le réglage : un fichier qui
            # existe déjà (on l'écrase), et un chemin hors du dossier de projets (ce n'est pas le
            # territoire d'IRIS). Et l'accord porte sur le chemin RÉSOLU, pas sur la phrase du
            # modèle : « site/../../Bureau/x » doit s'afficher comme le Bureau, pas comme le site.
            try:
                cible = await asyncio.to_thread(actions.resoudre_dans_perimetre, args.get("path", ""))
            except actions.HorsPerimetre as exc:
                return _err(str(exc))
            path = str(cible)
            ajout = bool(args.get("append"))
            existe = await asyncio.to_thread(cible.exists)
            if existe:
                titre = "Compléter un fichier existant" if ajout else "Remplacer un fichier existant"
            elif not actions.dans_dossier_projets(cible):
                titre = "Écrire un fichier hors du dossier de projets"
            elif policy == "always":
                titre = "Écrire un fichier"
            else:
                titre = None
            if titre is not None:
                approved = await ctx.confirm(titre, path)
                if not approved:
                    return _err("L'utilisateur a refusé l'écriture de ce fichier.")
            try:
                result = await asyncio.to_thread(actions.write_file, path, args.get("content", ""), ajout)
            except actions.HorsPerimetre as exc:
                return _err(str(exc))
            ctx.consent.log("file_written", agent=ctx.agent, detail=path)
            return result
        if name == "run_command":
            command = args.get("command", "")
            reason = args.get("reason", "")
            cwd = args.get("cwd") or None
            if needs_confirmation(policy, command):
                approved = await ctx.confirm(f"Exécuter une commande : {reason or 'sans description'}", command)
                if not approved:
                    return _err("L'utilisateur a refusé l'exécution de cette commande.")
            timeout = int(args.get("timeout") or 60)
            try:
                result = await asyncio.to_thread(actions.run_command, command, timeout, cwd)
            except actions.HorsPerimetre as exc:
                return _err(str(exc))
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
