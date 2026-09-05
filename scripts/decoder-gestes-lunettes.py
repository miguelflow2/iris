"""Capture guidée : associer chaque geste physique à son code dans le protocole des lunettes.

STRICTEMENT PASSIF, comme l'écoute simple : rien n'est envoyé aux lunettes.

Le principe : le script vous dit quoi faire et quand, puis étiquette lui-même les trames reçues
pendant chaque fenêtre. À la fin, il affiche la correspondance geste → code. C'est ce tableau
qui permettra ensuite à IRIS de réagir aux boutons et aux mouvements de tête.

Format de trame, établi le 2026-09-04 et corrigé le 2026-09-05 :
    bc <type> <longueur (2, petit-boutiste)> <CRC-16/MODBUS (2)> <données>
Les octets de contrôle sont AVANT les données, pas après. Le décodage vit dans
backend/iris/lunettes_trames.py, et il est gardé par des tests.
  · type 0x59 : flux continu à haute fréquence (télémétrie), ignoré ici, il noierait le reste ;
  · type 0x73 : événements rares — ce sont eux qui portent les gestes.

Usage : backend/.venv/Scripts/python scripts/decoder-gestes-lunettes.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ADRESSE_DEFAUT = "65:A2:9F:5C:F4:44"
CANAL_EVENEMENTS = "de5bf729-d711-4e47-af26-65e3012a5dc7"
TYPE_TELEMETRIE = 0x59  # flux continu : écarté du relevé des gestes

# Chaque geste est présenté, puis on écoute pendant `duree` secondes.
GESTES = [
    ("Repos — ne touchez à rien", 6.0),
    ("Appui COURT sur le bouton principal", 6.0),
    ("Appui LONG sur le bouton principal (2 secondes)", 7.0),
    ("DOUBLE appui sur le bouton principal", 6.0),
    ("Montez le VOLUME", 6.0),
    ("Baissez le VOLUME", 6.0),
    ("METTEZ les lunettes sur votre tête", 6.0),
    ("HOCHEZ la tête (oui), trois fois", 7.0),
    ("SECOUEZ la tête (non), trois fois", 7.0),
    ("RETIREZ les lunettes et posez-les", 6.0),
]


def annoncer(numero: int, total: int) -> None:
    """Dit le numéro de l'étape à voix haute.

    Sans repère sonore, il faudrait garder les yeux sur l'écran tout en manipulant les lunettes —
    or plusieurs gestes consistent justement à les mettre sur la tête. La voix installée sur ce
    poste est anglophone : on ne lui fait dire qu'un numéro, ce qu'elle prononce correctement."""
    try:
        import subprocess

        subprocess.Popen(
            ["powershell", "-NoProfile", "-Command",
             "Add-Type -AssemblyName System.Speech; "
             "$v = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
             "$v.Rate = 1; $v.Speak('Step {} of {}')".format(numero, total)],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        pass


def bip(frequence: int = 880, duree: int = 180) -> None:
    """Un bip aigu ouvre la fenêtre, un bip grave la referme."""
    try:
        import winsound

        winsound.Beep(frequence, duree)
    except Exception:
        pass


def adresse() -> str:
    fichier = Path(os.path.expandvars(r"%APPDATA%\IRIS\iris-data\settings.json"))
    try:
        data = json.loads(fichier.read_text(encoding="utf-8"))
        return (data.get("glasses") or {}).get("address") or ADRESSE_DEFAUT
    except Exception:
        return ADRESSE_DEFAUT


def decoupe(donnees: bytes) -> list[bytes]:
    """Sépare les trames collées dans un même paquet BLE."""
    trames, i = [], 0
    while i + 4 <= len(donnees):
        if donnees[i] != 0xBC:
            i += 1
            continue
        longueur = int.from_bytes(donnees[i + 2 : i + 4], "little")
        fin = i + 4 + longueur + 2
        if fin > len(donnees):
            trames.append(donnees[i:])
            break
        trames.append(donnees[i:fin])
        i = fin
    return trames or [donnees]


def signature(trame: bytes) -> str:
    """Ce qui identifie l'événement : le type, et la charge utile — pas la somme de contrôle.

    Correction du 5 septembre 2026. Cette fonction lisait `trame[4:8]`, c'est-à-dire les deux
    octets de contrôle SUIVIS des deux premiers octets de données. Les « codes de geste c0 80 et
    c6 d0 » notés dans docs/LUNETTES-DIAGNOSTIC.md étaient donc des CRC : ils changent à chaque
    trame parce qu'ils dépendent du contenu, ce qui donnait l'illusion de codes qui alternent.

    Le format réel, vérifié en reconstruisant à l'identique une trame reçue :
        bc | type | longueur (2, petit-boutiste) | CRC-16/MODBUS du contenu (2) | contenu
    """
    if len(trame) < 6 or trame[0] != 0xBC:
        return trame.hex(" ")[:32]
    longueur = int.from_bytes(trame[2:4], "little")
    contenu = trame[6:6 + longueur]
    return f"type 0x{trame[1]:02x} · {contenu.hex(' ') or '(vide)'}"


async def main() -> int:
    try:
        from bleak import BleakClient
    except ImportError:
        print("bleak absent : lancez avec backend/.venv/Scripts/python")
        return 1

    cible = adresse()
    releve: dict[str, list[bytes]] = defaultdict(list)
    geste_courant = {"nom": "(préparation)"}

    def au_signal(_sender, data: bytearray) -> None:
        for trame in decoupe(bytes(data)):
            if len(trame) > 1 and trame[1] == TYPE_TELEMETRIE:
                continue  # flux continu, sans rapport avec les gestes
            releve[geste_courant["nom"]].append(trame)

    print(f"Capture guidée des gestes — lunettes {cible}")
    print("Rien n'est envoyé aux lunettes : écoute seule.\n")
    print("Préparez-vous : le script vous dira quoi faire, un geste à la fois.")
    print("Faites le geste UNE SEULE FOIS, au début de la fenêtre, puis ne touchez plus à rien.\n")

    # Attendre que les lunettes se montrent, puis se connecter A L'OBJET RENVOYE PAR LE BALAYAGE.
    #
    # Premiere tentative : on balayait, on voyait les lunettes, puis on passait leur ADRESSE a
    # BleakClient — qui refaisait sa propre recherche. Entre les deux, la fenetre d'annonce s'etait
    # refermee, et la connexion echouait sur un « appareil introuvable » alors qu'on venait de les
    # voir. find_device_by_address rend l'objet lui-meme : plus de seconde recherche, plus de course.
    from bleak import BleakScanner

    print("Recherche des lunettes... reveillez-les (eteignez-les puis rallumez-les).", flush=True)
    appareil = None
    for essai in range(45):  # jusqu'a six minutes
        appareil = await BleakScanner.find_device_by_address(cible, timeout=8.0)
        if appareil is not None:
            break
        print("  ... toujours rien ({} s ecoulees)".format((essai + 1) * 8), flush=True)
    if appareil is None:
        print("Les lunettes ne se sont pas montrees. Elles sont peut-etre dans leur etui, ou")
        print("deja connectees a un telephone qui les garde pour lui.")
        return 1
    print("Trouvees. Connexion immediate...", flush=True)

    try:
        async with BleakClient(appareil, timeout=30.0) as client:
            if not client.is_connected:
                print("Connexion refusée.")
                return 1
            # On s'abonne a TOUT ce qui notifie, pas au seul canal connu. Constat reel : apres
            # un redemarrage, les lunettes n'exposaient plus de5bf729 et la capture s'arretait
            # net alors que la connexion, elle, avait reussi.
            abonnes = []
            for service in client.services:
                for car in service.characteristics:
                    if 'notify' in car.properties or 'indicate' in car.properties:
                        try:
                            await client.start_notify(car, au_signal)
                            abonnes.append(str(car.uuid).split('-')[0][-4:])
                        except Exception:
                            pass
            print('Services exposes : ' + ', '.join(sorted({str(sv.uuid).split('-')[0][-4:] for sv in client.services})), flush=True)
            if not abonnes:
                print('Aucun canal de notification : rien a ecouter.', flush=True)
                return 1
            print('A l ecoute sur : ' + ', '.join(abonnes) + NL, flush=True)
            await asyncio.sleep(2.0)

            print("  Dix secondes pour vous installer, les lunettes a portee de main.")
            await asyncio.sleep(10.0)

            for numero, (nom, duree) in enumerate(GESTES, 1):
                annoncer(numero, len(GESTES))
                for compte in (3, 2, 1):
                    print(f"\r  {numero}/{len(GESTES)} - {nom} ... dans {compte}   ", end="", flush=True)
                    bip(440, 90)
                    await asyncio.sleep(0.9)
                geste_courant["nom"] = nom
                bip(1320, 250)
                print(f"\r  {numero}/{len(GESTES)} - {nom} : MAINTENANT" + " " * 20)
                await asyncio.sleep(duree)
                bip(330, 120)
                recues = len(releve[nom])
                print(f"      -> {recues} trame(s) recue(s)")
                geste_courant["nom"] = "(entre deux gestes)"
                await asyncio.sleep(1.5)

            pass  # la deconnexion coupe les abonnements
    except Exception as exc:
        print(f"\nÉchec : {type(exc).__name__}: {exc}")
        return 1

    # ------------------------------------------------------------------ résultat
    print("\n" + "=" * 78)
    print("  CORRESPONDANCE GESTE → CODE")
    print("=" * 78)

    bruit = {signature(t) for t in releve.get("Repos — ne touchez à rien", [])}
    bruit |= {signature(t) for t in releve.get("(entre deux gestes)", [])}

    lignes_doc = []
    for nom, _duree in GESTES:
        trames = releve.get(nom, [])
        signatures = sorted({signature(t) for t in trames} - bruit)
        if nom.startswith("Repos"):
            print(f"\n  {nom}")
            print(f"     bruit de fond : {len(bruit)} signature(s) écartée(s) de l'analyse")
            continue
        print(f"\n  {nom}")
        if not signatures:
            print("     aucun code propre à ce geste")
            continue
        for s in signatures:
            exemple = next(t for t in trames if signature(t) == s)
            print(f"     {s}")
            print(f"        trame complète : {exemple.hex(' ')}")
            lignes_doc.append(f"| {nom} | `{s}` | `{exemple.hex(' ')}` |")

    sortie = Path("release") / "lunettes-gestes.md"
    sortie.parent.mkdir(exist_ok=True)
    sortie.write_text(
        "# Lunettes M01 Pro — correspondance geste → code\n\n"
        f"Relevé du {datetime.now():%Y-%m-%d %H:%M}. Canal `{CANAL_EVENEMENTS}`.\n"
        "Format : `bc <type> <longueur 2 octets> <données> <2 octets de contrôle>`.\n\n"
        "| Geste | Signature | Trame complète |\n|---|---|---|\n" + "\n".join(lignes_doc) + "\n",
        encoding="utf-8",
    )
    print(f"\n\nTableau enregistré dans {sortie}")
    print("\nUn geste sans code propre passe probablement par le Bluetooth classique")
    print("(profil AVRCP ou port série COM4) plutôt que par ce canal.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
