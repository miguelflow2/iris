"""Ecoute longue : associer chaque paquet des lunettes a un geste physique.

Les deux sondes precedentes ont montre que les paquets ne sont NI periodiques NI declenches par le
volume de Windows : 100 secondes d'ecoute, zero paquet. Or IRIS en avait recu trois en vingt
secondes juste apres une connexion. Ils repondent donc a autre chose, et la seule facon de le
savoir est de provoquer ce quelque chose : toucher les lunettes, les porter, les poser.

Ce programme ne fait qu'ECOUTER. Il n'ecrit rien vers les lunettes. Chaque paquet est horodate a
la seconde pres pour qu'on puisse le rapprocher du geste qui l'a produit.
"""
import asyncio
from datetime import datetime
from pathlib import Path

from bleak import BleakClient

ADRESSE = "65:A2:9F:5C:F4:44"
DUREE = 180
JOURNAL = Path(__file__).with_name("lunettes-paquets.txt")

depart = None
lignes = []


def noter(canal, donnees):
    brut = bytes(donnees)
    lisible = "".join(chr(o) if 32 <= o < 127 else "." for o in brut)
    ligne = "{:6.1f}s  {:<6} len={:<3} {:<32} {}".format(
        (datetime.now() - depart).total_seconds(), canal, len(brut), brut.hex(), lisible
    )
    lignes.append(ligne)
    print(ligne, flush=True)
    JOURNAL.write_text("\n".join(lignes), encoding="utf-8")


async def principal():
    global depart
    async with BleakClient(ADRESSE, timeout=30.0) as client:
        abonnes = []
        for service in client.services:
            for car in service.characteristics:
                if "notify" in car.properties or "indicate" in car.properties:
                    court = str(car.uuid).split("-")[0][-4:]
                    try:
                        await client.start_notify(car, lambda s, d, c=court: noter(c, d))
                        abonnes.append(court)
                    except Exception:
                        pass
        depart = datetime.now()
        print("ECOUTE {} s — canaux : {}".format(DUREE, ", ".join(abonnes)), flush=True)
        print("Faites vos gestes maintenant. Chaque paquet sera horodate.", flush=True)
        await asyncio.sleep(DUREE)
        print("\nFIN — {} paquet(s). Journal : {}".format(len(lignes), JOURNAL), flush=True)
        if not lignes:
            JOURNAL.write_text("aucun paquet en {} s".format(DUREE), encoding="utf-8")


try:
    asyncio.run(principal())
except Exception as exc:
    print("ECHEC :", type(exc).__name__, exc, flush=True)
