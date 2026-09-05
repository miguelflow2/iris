"""Ecoute le port serie Bluetooth des lunettes (SPP, COM4).

Windows expose ce port parce que les lunettes annoncent le profil serie classique :
    BTHENUM\\{00001101-...}_VID&000105D6_PID&000A\\...65A29F5CF444...
L'adresse dans l'identifiant est bien la leur.

Ce canal est bien plus confortable que le Bluetooth basse energie : un flux d'octets, sans
decoupage en caracteristiques. S'il porte les memes trames `bc 73 ...`, on tient la voie par
laquelle IRIS pourra commander les lunettes.

Ce programme n'ECRIT RIEN. Il ouvre, il ecoute, il decoupe ce qui ressemble a des trames.
Ouvrir le port etablit la liaison serie : c'est deja une information s'il refuse.
"""
import sys
import time
from datetime import datetime

import serial

from trames_lunettes import MAGIE, decrire, lire

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM4"
DUREE = int(sys.argv[2]) if len(sys.argv) > 2 else 60


def decouper(tampon: bytearray):
    """Sort les trames completes du tampon. Ce qui reste attend la suite."""
    trames = []
    while True:
        debut = tampon.find(MAGIE)
        if debut < 0:
            tampon.clear()
            break
        if debut:
            del tampon[:debut]
        if len(tampon) < 6:
            break
        longueur = int.from_bytes(tampon[2:4], "little")
        if longueur > 512:  # une longueur absurde : ce n'etait pas un debut de trame
            del tampon[:1]
            continue
        if len(tampon) < 6 + longueur:
            break
        trames.append(bytes(tampon[:6 + longueur]))
        del tampon[:6 + longueur]
    return trames


print("Ouverture de {} ...".format(PORT), flush=True)
try:
    lien = serial.Serial(PORT, baudrate=115200, timeout=0.5)
except Exception as exc:
    print("REFUSE : {} — {}".format(type(exc).__name__, exc), flush=True)
    print("Un port serie Bluetooth ne s'ouvre que si l'appareil accepte la liaison.", flush=True)
    sys.exit(1)

print("Ouvert. Ecoute {} s. Manipulez les lunettes.".format(DUREE), flush=True)
depart = time.time()
tampon = bytearray()
brut = bytearray()
trames = 0

try:
    while time.time() - depart < DUREE:
        octets = lien.read(256)
        if not octets:
            continue
        instant = "{:6.1f}s".format(time.time() - depart)
        brut += octets
        print("{} brut  {}".format(instant, octets.hex()), flush=True)
        tampon += octets
        for trame in decouper(tampon):
            trames += 1
            lu = lire(trame)
            print("{} TRAME {}  somme {}  -> {}".format(
                instant, trame.hex(), "juste" if lu and lu["crc_valide"] else "FAUSSE", decrire(trame)), flush=True)
finally:
    lien.close()

print("\n=== BILAN ===", flush=True)
print("  {} octet(s) recus, {} trame(s) reconnue(s)".format(len(brut), trames), flush=True)
if brut and not trames:
    lisible = "".join(chr(o) if 32 <= o < 127 else "." for o in brut[:400])
    print("  Rien au format `bc`. Debut du flux, en texte : " + lisible, flush=True)
if not brut:
    print("  Silence complet : le port s'ouvre mais rien n'y circule sans qu'on parle d'abord.", flush=True)
