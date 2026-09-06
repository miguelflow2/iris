"""Interpréter un « oui » ou un « non » dit à voix haute.

Séparé du reste pour une raison simple : c'est la brique qui décide si un courriel part ou non, si
un identifiant est importé ou non. Elle doit être juste, et elle doit être testable sans micro.

Règle prudente : dans le doute, ce n'est PAS un oui. Un accord ambigu ne fait rien partir.
"""
from __future__ import annotations

import unicodedata

_OUI = (
    "oui", "ouais", "ouaip", "vas y", "vas-y", "d accord", "daccord", "accord", "confirme",
    "confirme", "je confirme", "envoie", "envoi", "fais le", "fais-le", "vas le faire",
    "c est bon", "c est ca", "parfait", "ok", "okay", "yes", "go", "bien sur", "exact",
    "exactement", "tout a fait", "absolument", "je veux", "s il te plait fais le",
)
_NON = (
    "non", "nan", "annule", "annuler", "laisse", "laisse tomber", "surtout pas", "pas maintenant",
    "pas ca", "arrete", "arrete tout", "no", "stop", "negatif", "n envoie pas", "n envoie rien",
    "attends", "pas encore", "oublie", "oublie ca", "n importe pas", "pas la peine",
)


def _plat(texte: str) -> str:
    sans = "".join(c for c in unicodedata.normalize("NFD", texte or "") if unicodedata.category(c) != "Mn")
    garde = "".join(c if c.isalnum() or c == " " else " " for c in sans.lower())
    return " ".join(garde.split())


def interpreter_accord(texte: str) -> bool | None:
    """True si c'est un oui, False si c'est un non, None si ce n'est ni l'un ni l'autre.

    None veut dire « redemande » : ni oui ni non, on ne devine pas. Le « non » est cherché en
    premier, parce que « non, pas ça » contient aussi des mots plutôt positifs, et qu'en cas de
    doute il vaut mieux ne rien faire."""
    plat = _plat(texte)
    if not plat:
        return None
    mots = plat.split()
    # Refus d'abord : « n envoie pas » l'emporte sur « envoie ».
    for expr in _NON:
        if expr in plat or expr in mots:
            return False
    for expr in _OUI:
        if expr == plat or expr in mots or (" " in expr and expr in plat):
            return True
    return None
