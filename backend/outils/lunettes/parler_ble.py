"""Envoyer des trames aux lunettes sur le canal ou elles parlent vraiment.

Le port serie COM4 s'est revele etre un echo local de Windows : tout ce qu'on y ecrit revient
identique, y compris des octets absurdes. Ce n'etait donc pas un canal vers les lunettes.

Le vrai canal est en Bluetooth basse energie, service `de5bf728` :
    de5bf729  notification  <- c'est par la qu'arrivent les trames de batterie
    de5bf72a  ecriture      <- c'est donc par la qu'il faut repondre

On envoie uniquement des trames de la commande 0x73, sous-commande 0x05 : celle par laquelle les
lunettes annoncent d'elles-memes leur batterie. Leur demander ce qu'elles racontent deja de leur
plein gre ne peut rien casser. Aucun balayage des autres commandes : c'est ainsi qu'on tombe sur
une ecriture de micrologiciel, et Miguel n'a qu'une paire.
"""
import asyncio
from datetime import datetime

from bleak import BleakClient

from trames_lunettes import decrire, fabriquer, lire

ADRESSE = "65:A2:9F:5C:F4:44"
ECRITURE = "de5bf72a-d711-4e47-af26-65e3012a5dc7"

recu = []
depart = None


def noter(canal, donnees):
    brut = bytes(donnees)
    lu = lire(brut)
    detail = decrire(brut) if lu else "".join(chr(o) if 32 <= o < 127 else "." for o in brut)
    ligne = "{:6.1f}s <- {:<6} {:<26} {}".format(
        (datetime.now() - depart).total_seconds(), canal, brut.hex(), detail)
    recu.append((canal, brut))
    print(ligne, flush=True)


ESSAIS = [
    ("sous-commande 05 seule", 0x73, bytes([0x05])),
    ("commande 73 sans contenu", 0x73, b""),
    ("sous-commande 05, valeur nulle", 0x73, bytes([0x05, 0x00, 0x00])),
    ("sous-commande 05, deux octets", 0x73, bytes([0x05, 0x00])),
]


async def principal():
    global depart
    print("Connexion...", flush=True)
    async with BleakClient(ADRESSE, timeout=30.0) as client:
        car_ecriture = None
        for service in client.services:
            for car in service.characteristics:
                court = str(car.uuid).split("-")[0][-4:]
                if str(car.uuid).lower() == ECRITURE:
                    car_ecriture = car
                if "notify" in car.properties or "indicate" in car.properties:
                    try:
                        await client.start_notify(car, lambda s, d, c=court: noter(c, d))
                    except Exception:
                        pass
        if car_ecriture is None:
            print("Caracteristique d'ecriture introuvable.", flush=True)
            return
        sans_reponse = "write-without-response" in car_ecriture.properties
        print("Ecriture sur {} ({}).".format(ECRITURE.split("-")[0], ", ".join(car_ecriture.properties)), flush=True)

        depart = datetime.now()
        for nom, commande, contenu in ESSAIS:
            trame = fabriquer(commande, contenu)
            avant = len(recu)
            print("\n  -> {:<32} {}".format(nom, trame.hex()), flush=True)
            try:
                await client.write_gatt_char(car_ecriture, trame, response=not sans_reponse)
            except Exception as exc:
                print("     REFUSE : {}".format(exc), flush=True)
                continue
            await asyncio.sleep(3.0)
            if len(recu) == avant:
                print("     (aucune reponse)", flush=True)

        print("\n  ... ecoute finale de 20 s", flush=True)
        avant = len(recu)
        await asyncio.sleep(20)
        print("  {} paquet(s) pendant l'ecoute finale".format(len(recu) - avant), flush=True)

    print("\n=== BILAN ===", flush=True)
    print("  {} paquet(s) recus au total".format(len(recu)), flush=True)
    echos = sum(1 for _, brut in recu if any(brut == fabriquer(c, p) for _, c, p in ESSAIS))
    print("  dont {} echo(s) de nos propres trames".format(echos), flush=True)
    for canal, brut in recu:
        print("    {} {}".format(canal, brut.hex()), flush=True)


try:
    asyncio.run(principal())
except Exception as exc:
    print("ECHEC :", type(exc).__name__, exc, flush=True)
