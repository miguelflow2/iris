"""Routeur d'agents : choisit l'agent le plus adapté à une demande (règles explicables)."""
from __future__ import annotations

import re

from .config import Settings

PC_KEYWORDS = [
    "ouvre", "ouvrir", "lance", "lancer", "démarre", "demarre", "ferme", "fermer", "capture", "écran", "ecran",
    "fichier", "dossier", "mon ordinateur", "mon ordi", "mon pc", "exécute", "execute", "commande", "terminal",
    "verrouille", "état du système", "etat du systeme", "batterie", "processeur", "mémoire vive", "trouve le fichier",
    "open ", "launch ", "screenshot", "my computer", "run ", "folder",
    "lancement", "lance-moi", "lance moi", "mets ", "met de la", "mets de la", "joue", "écris", "ecris", "crée", "cree",
    "tape", "clique", "appuie", "affiche", "va sur", "vas sur", "youtube", "google", "musique", "vidéo", "video",
    "navigateur", "chrome", "spotify", "explorateur", "bloc-notes", "notepad", "développe", "developpe", "code-moi",
    "site web", "application", "programme", "installe", "ouvre",
]
CODE_KEYWORDS = [
    "code", "bug", "script", "python", "javascript", "typescript", "compile", "build", "git", "fonction", "erreur",
    "stack", "api", "sql", "regex", "programme", "debug", "débug", "test unitaire", "refactor", "classe", "variable",
    "docker", "npm", "pip", "commit", "branche", "branch",
]
WEB_KEYWORDS = [
    "cherche sur le web", "recherche sur internet", "actualité", "actualites", "nouvelles", "météo", "meteo",
    "dernières", "dernieres", "quoi de neuf", "prix de", "aujourd'hui", "cette semaine", "news", "latest",
    "resultat du match", "résultat du match", "bourse",
]
VISION_KEYWORDS = ["image", "photo", "regarde", "vois", "qu'est-ce que c'est", "identifie", "traduis ce texte"]


class NoAgentAvailable(Exception):
    pass


def _has(text: str, keywords: list[str]) -> bool:
    return any(k in text for k in keywords)


class AgentRouter:
    def __init__(self, settings: Settings):
        self.settings = settings

    def available(self, secrets) -> list[str]:
        out = []
        from .connectors import AGENT_META

        for name, cfg in self.settings.user.agents.items():
            meta = AGENT_META.get(name)
            if not meta or not cfg.active:
                continue
            if meta["needs_key"] and not secrets.has_api_key(name):
                continue
            # « vela » ne réclame pas de clé à l'utilisateur, mais il lui faut le jeton d'appareil
            # obtenu auprès du relais. Sans lui, router une demande ici mènerait droit à l'échec.
            if name == "vela" and not secrets.has_api_key("vela"):
                continue
            if name == "custom" and not cfg.base_url:
                continue
            out.append(name)
        return out

    def select(self, text: str, has_images: bool, available: list[str], requested: str = "auto") -> tuple[str, str]:
        user = self.settings.user
        if user.local_only:
            local = [a for a in available if user.agents[a].local]
            if requested not in ("auto", "", None) and requested in local:
                return requested, "choisi manuellement (mode local)"
            if local:
                return local[0], "mode 100 % local : seule une IA locale est autorisée"
            raise NoAgentAvailable(
                "Mode 100 % local activé : configurez une IA locale (Ollama, LM Studio…) ou désactivez ce mode."
            )
        if not available:
            raise NoAgentAvailable("Aucune IA n'est prête. Activez-en une et ajoutez sa clé API dans Réglages › Moteurs IA.")
        if requested not in ("auto", "", None):
            if requested in available:
                return requested, "choisi manuellement"
            raise NoAgentAvailable(f"L'IA demandée ({requested}) n'est pas configurée.")
        if user.routing_mode == "manual":
            default = user.default_agent if user.default_agent in available else available[0]
            return default, "moteur par défaut (routage manuel)"

        low = re.sub(r"\s+", " ", (text or "").lower())

        def prefer(order: list[str], reason: str) -> tuple[str, str] | None:
            for name in order:
                if name in available:
                    return name, reason
            return None

        if _has(low, PC_KEYWORDS):
            hit = prefer(["vela", "openrouter", "claude", "gpt"], "action sur l'ordinateur : moteur avec outils système")
            if hit:
                return hit
        if _has(low, CODE_KEYWORDS):
            hit = prefer(["vela", "openrouter", "claude", "gpt", "custom", "gemini"], "demande liée au code")
            if hit:
                return hit
        if has_images or _has(low, VISION_KEYWORDS):
            hit = prefer(["vela", "openrouter", "claude", "gpt", "gemini"], "analyse visuelle")
            if hit:
                return hit
        if _has(low, WEB_KEYWORDS):
            hit = prefer(["vela", "openrouter", "gemini", "gpt", "claude"], "information récente")
            if hit:
                return hit
        default = user.default_agent if user.default_agent in available else available[0]
        return default, "moteur par défaut"
