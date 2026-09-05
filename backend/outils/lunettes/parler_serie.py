"""Parler aux lunettes sur leur port serie, prudemment.

Le port s'ouvre, mais rien n'y circule spontanement : c'est un protocole question-reponse. Il faut
demander.

CE QU'ON ENVOIE, ET POURQUOI SEULEMENT CA. On reste dans la commande 0x73, la seule qu'on ait
observee, et dans sa sous-commande 0x05, celle par laquelle les lunettes annoncent d'elles-memes
leur batterie. Demander ce qu'elles racontent deja de leur plein gre ne peut rien casser.

CE QU'ON N'ENVOIE PAS. Aucun balayage des autres commandes. Sur ces puces, c'est exactement comme
ca qu'on tombe sur une commande d'ecriture de micrologiciel ou de retour en usine. Miguel n'a
qu'une paire de lunettes et il presente son produit le 8 septembre. Le balayage viendra quand on
saura ce qu'on ecrit — pas avant.
"""
import sys
import time

import serial

from trames_lunettes import fabriquer, lire

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM4"

# (nom, commande, contenu) — tous dans la famille deja observee.
ESSAIS = [
    ("sous-commande 05 seule", 0x73, bytes([0x05])),
    ("commande 73 sans contenu", 0x73, b""),
    ("meme forme, valeur nulle", 0x73, bytes([0x05, 0x00, 0x00])),
    ("sous-commande 05, deux octets", 0x73, bytes([0x05, 0x00])),
]


def ecouter(lien, secondes, tampon):
    fin = time.time() + secondes
    recu = bytearray()
    while time.time() < fin:
        octets = lien.read(256)
        if octets:
            recu += octets
            fin = time.time() + 1.0  # on prolonge tant que ca parle
    if recu:
        tampon += recu
        print("     <- {}".format(recu.hex()), flush=True)
        lu = lire(bytes(recu))
        if lu:
            print("     somme {} | commande 0x{:02x} | contenu {}".format(
                "juste" if lu["crc_valide"] else "FAUSSE", lu["commande"], lu["contenu"].hex()), flush=True)
    else:
        print("     (silence)", flush=True)
    return len(recu)


print("Ouverture de {} ...".format(PORT), flush=True)
lien = serial.Serial(PORT, baudrate=115200, timeout=0.3)
print("Ouvert.\n", flush=True)

tampon = bytearray()
reponses = 0
try:
    for nom, commande, contenu in ESSAIS:
        trame = fabriquer(commande, contenu)
        print("  -> {:<26} {}".format(nom, trame.hex()), flush=True)
        lien.reset_input_buffer()
        lien.write(trame)
        lien.flush()
        if ecouter(lien, 3.0, tampon):
            reponses += 1

    # Une derniere ecoute passive : certaines puces repondent avec du retard.
    print("\n  ... ecoute finale de 10 s", flush=True)
    ecouter(lien, 10.0, tampon)
finally:
    lien.close()

print("\n=== BILAN ===", flush=True)
print("  {} essai(s) sur {} ont provoque une reponse".format(reponses, len(ESSAIS)), flush=True)
print("  {} octet(s) recus au total".format(len(tampon)), flush=True)
if not tampon:
    print("  Aucune reponse. Le canal serie accepte l'ecriture mais ne repond pas a cette", flush=True)
    print("  commande : soit 0x73 n'est qu'une notification descendante, soit les lunettes", flush=True)
    print("  attendent une ouverture de session qu'on ne connait pas encore.", flush=True)
