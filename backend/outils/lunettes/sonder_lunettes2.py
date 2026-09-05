"""Deuxieme sonde : comprendre CE QUI DECLENCHE les paquets des lunettes.

Premiere sonde : ecriture acceptee sur l'UART Nordic, aucune reponse, et surtout aucun paquet
spontane en 12 secondes — alors qu'IRIS en recevait un toutes les dix secondes environ, tous sur
le meme canal de40f729, avec la meme forme :

    bc 73 03 00 5e 61 05 56 00
    bc 73 03 00 5e 91 05 55 00
    bc 73 03 00 5f 01 05 54 00

L'avant-dernier octet descend de 1 a chaque fois : 86, 85, 84. Ca ressemble a un niveau qu'on
baisse — le volume, le plus probablement. Cette sonde teste l'hypothese : on ecoute longtemps, on
manipule le volume de Windows au milieu, et on regarde si un paquet tombe au bon moment.

On ne fait qu'ecouter et bouger le volume du PC. Aucune ecriture vers les lunettes.
"""
import asyncio
import subprocess
from datetime import datetime

from bleak import BleakClient

ADRESSE = "65:A2:9F:5C:F4:44"
recu = []
depart = None


def t():
    return "{:5.1f}s".format((datetime.now() - depart).total_seconds())


def noter(canal, donnees):
    brut = bytes(donnees)
    lisible = "".join(chr(o) if 32 <= o < 127 else "." for o in brut)
    recu.append((t(), canal, brut.hex()))
    print("  {} <- {:<6} {:<26} {}".format(t(), canal, brut.hex(), lisible), flush=True)


def volume(direction, fois=1):
    """Monte ou baisse le volume de Windows en simulant la touche multimedia."""
    code = 0xAF if direction == "haut" else 0xAE
    script = (
        "$s = New-Object -ComObject WScript.Shell; "
        "1..{} | ForEach-Object {{ $s.SendKeys([char]{}) }}".format(fois, code)
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, timeout=15)
    except Exception as exc:
        print("  (volume {} impossible : {})".format(direction, exc), flush=True)


async def principal():
    global depart
    print("Connexion...", flush=True)
    async with BleakClient(ADRESSE, timeout=30.0) as client:
        # Les caracteristiques, prises comme objets : les lire par chaine d'UUID levait une TypeError.
        cars = {}
        for service in client.services:
            for car in service.characteristics:
                court = str(car.uuid).split("-")[0][-4:]
                cars[court] = car
                if "notify" in car.properties or "indicate" in car.properties:
                    try:
                        await client.start_notify(car, lambda s, d, c=court: noter(c, d))
                    except Exception:
                        pass

        print("\n=== IDENTITE ===", flush=True)
        for court in ("2a00", "2a25", "2a26", "2a27", "2a23", "ae10", "4a02", "fee3"):
            car = cars.get(court)
            if car is None or "read" not in car.properties:
                continue
            try:
                brut = bytes(await client.read_gatt_char(car))
                lisible = "".join(chr(o) if 32 <= o < 127 else "." for o in brut)
                print("  {} : {:<24} {}".format(court, brut.hex() or "(vide)", lisible), flush=True)
            except Exception as exc:
                print("  {} : illisible ({})".format(court, type(exc).__name__), flush=True)

        depart = datetime.now()
        print("\n=== ECOUTE 100 s, avec provocations ===", flush=True)

        etapes = [
            (10, "silence de reference", None),
            (10, "VOLUME BAS x3", lambda: volume("bas", 3)),
            (10, "VOLUME HAUT x3", lambda: volume("haut", 3)),
            (10, "VOLUME BAS x1", lambda: volume("bas", 1)),
            (60, "silence final — touchez les lunettes maintenant", None),
        ]
        for duree, nom, action in etapes:
            marque = len(recu)
            print("\n  [{}] {}".format(t(), nom), flush=True)
            if action:
                action()
            await asyncio.sleep(duree)
            n = len(recu) - marque
            print("  [{}] -> {} paquet(s) pendant cette etape".format(t(), n), flush=True)

        print("\n=== BILAN ===", flush=True)
        print("  {} paquet(s)".format(len(recu)), flush=True)
        canaux = {}
        for _, canal, _ in recu:
            canaux[canal] = canaux.get(canal, 0) + 1
        for canal, n in sorted(canaux.items(), key=lambda x: -x[1]):
            print("  {} : {}".format(canal, n), flush=True)


try:
    asyncio.run(principal())
except Exception as exc:
    print("ECHEC :", type(exc).__name__, exc, flush=True)
