"""Écoute passive des lunettes : décoder leur protocole en les manipulant.

STRICTEMENT PASSIF. Ce script n'écrit RIEN dans les lunettes. Il s'abonne à tous les canaux
de notification et affiche ce qui en sort, horodaté. Aucun risque : on regarde, on ne touche pas.

Écrire sur les canaux de commande d'une puce JieLi sans connaître le protocole pourrait
déclencher n'importe quoi, y compris un effacement. Tant qu'on n'a pas décodé, on écoute.

Mode d'emploi :
  1. Lunettes allumées, sorties de l'étui.
  2. Lancer : backend/.venv/Scripts/python scripts/ecoute-lunettes.py
  3. Pendant les 90 secondes, manipuler les lunettes une action à la fois, en notant l'ordre :
       appui court sur le bouton, appui long, double appui, mettre/retirer les lunettes,
       toucher le pavé tactile s'il y en a un, changer le volume.
  4. Comparer les trames reçues avec la liste des gestes : c'est ce qui donne le protocole.

Sortie enregistrée dans release/lunettes-trames.txt pour analyse ultérieure.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ADRESSE_DEFAUT = "65:A2:9F:5C:F4:44"
DUREE = 90.0

# Ce qu'on sait des canaux, d'après le relevé du 2026-09-04 (voir docs/LUNETTES-DIAGNOSTIC.md).
CANAUX = {
    "0000ae02": "JieLi — réponse principale",
    "0000ae04": "JieLi — réponse secondaire",
    "0000ae05": "JieLi — indication",
    "0000ae3c": "JieLi — canal secondaire",
    "6e400003": "Série sur BLE — sortie",
    "de5bf729": "Propriétaire — sortie",
    "00004a02": "Propriétaire (service 3802)",
    "0000fee3": "Propriétaire (service FEE1)",
    "00002a05": "Standard — changement de service",
}


def adresse() -> str:
    fichier = Path(os.path.expandvars(r"%APPDATA%\IRIS\iris-data\settings.json"))
    try:
        data = json.loads(fichier.read_text(encoding="utf-8"))
        return (data.get("glasses") or {}).get("address") or ADRESSE_DEFAUT
    except Exception:
        return ADRESSE_DEFAUT


def lisible(donnees: bytes) -> str:
    """Rend la trame lisible : hexadécimal, plus le texte s'il y en a."""
    hexa = donnees.hex(" ")
    texte = "".join(chr(b) if 32 <= b < 127 else "." for b in donnees)
    return f"{hexa:<48}  |{texte}|"


async def main() -> int:
    try:
        from bleak import BleakClient
    except ImportError:
        print("bleak absent : lancez avec backend/.venv/Scripts/python")
        return 1

    cible = adresse()
    sortie = Path("release") / "lunettes-trames.txt"
    sortie.parent.mkdir(exist_ok=True)
    journal = sortie.open("w", encoding="utf-8")

    def note(ligne: str) -> None:
        print(ligne)
        journal.write(ligne + "\n")
        journal.flush()

    note(f"Écoute passive des lunettes {cible} — {datetime.now():%Y-%m-%d %H:%M:%S}")
    note("Aucune donnée n'est envoyée aux lunettes. Écoute seule.\n")

    debut = None
    compteur = {"n": 0}

    def au_signal(canal: str, libelle: str):
        def rappel(_sender, data: bytearray) -> None:
            compteur["n"] += 1
            ecoule = (datetime.now() - debut).total_seconds() if debut else 0.0
            note(f"[{ecoule:6.2f}s] {libelle:34} {lisible(bytes(data))}")

        return rappel

    try:
        async with BleakClient(cible, timeout=30.0) as client:
            if not client.is_connected:
                note("Connexion refusée.")
                return 1
            note("Connecté. Abonnement aux canaux…\n")

            abonnes = 0
            for service in client.services:
                for c in service.characteristics:
                    if "notify" not in c.properties and "indicate" not in c.properties:
                        continue
                    court = str(c.uuid)[:8].lower()
                    libelle = CANAUX.get(court, f"inconnu {court}")
                    try:
                        await client.start_notify(c, au_signal(str(c.uuid), libelle))
                        abonnes += 1
                        note(f"  abonné : {c.uuid}  {libelle}")
                    except Exception as exc:
                        note(f"  refusé  : {c.uuid}  ({type(exc).__name__})")

            if not abonnes:
                note("\nAucun canal d'écoute disponible.")
                return 1

            debut = datetime.now()
            note(f"\n{abonnes} canaux écoutés pendant {DUREE:.0f} secondes.")
            note("MANIPULEZ LES LUNETTES MAINTENANT, une action à la fois, en notant l'ordre :")
            note("  appui court · appui long · double appui · les mettre · les retirer · volume\n")

            reste = DUREE
            while reste > 0:
                await asyncio.sleep(min(10.0, reste))
                reste -= 10.0
                if reste > 0:
                    note(f"  … {reste:.0f} s restantes ({compteur['n']} trames reçues)")

            note(f"\nTerminé : {compteur['n']} trames reçues.")
            if compteur["n"] == 0:
                note("Aucune trame. Deux explications : les lunettes n'émettent rien tant qu'on ne")
                note("leur a pas envoyé de commande, ou les gestes passent par le Bluetooth classique")
                note("(profil AVRCP) plutôt que par ces canaux. Dans ce cas, c'est COM4 qu'il faut écouter.")
    except Exception as exc:
        note(f"Échec : {type(exc).__name__}: {exc}")
        return 1
    finally:
        journal.close()

    print(f"\nTrames enregistrées dans {sortie}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
