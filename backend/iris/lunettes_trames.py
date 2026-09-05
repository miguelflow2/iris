"""Le protocole des lunettes VELA, decode.

Quatre trames observees ont suffi. La somme de controle est un CRC-16/MODBUS petit-boutiste
calcule sur le CONTENU SEUL — trouve par recherche exhaustive sur quatorze variantes de CRC et six
decoupages possibles de la trame, une seule combinaison colle sur les quatre trames.

    bc | 73 | LL LL | CC CC | contenu
    ^    ^     ^       ^      ^
    |    |     |       |      donnees
    |    |     |       CRC-16/MODBUS du contenu, petit-boutiste
    |    |     longueur du contenu, petit-boutiste
    |    commande
    marque de debut

Contenu observe : `05 BB 00`, ou BB descend de 86 a 83 sur une demi-heure. Une batterie.

Ce module sert a deux choses : LIRE ce que les lunettes racontent, et FABRIQUER des trames
valides. La seconde est ce qui permettra a IRIS de les commander.
"""

MAGIE = 0xBC


def crc_modbus(donnees: bytes) -> int:
    """CRC-16/MODBUS : polynome 0x8005 inverse (0xA001), depart 0xFFFF, entree et sortie inversees."""
    reg = 0xFFFF
    for octet in donnees:
        reg ^= octet
        for _ in range(8):
            reg = (reg >> 1) ^ 0xA001 if reg & 1 else reg >> 1
    return reg


def fabriquer(commande: int, contenu: bytes) -> bytes:
    """Construit une trame valide, prete a etre envoyee aux lunettes."""
    return (bytes([MAGIE, commande])
            + len(contenu).to_bytes(2, "little")
            + crc_modbus(contenu).to_bytes(2, "little")
            + contenu)


def lire(trame: bytes) -> dict | None:
    """Decompose une trame recue. None si elle est mal formee ou si la somme ne tombe pas juste."""
    if len(trame) < 6 or trame[0] != MAGIE:
        return None
    longueur = int.from_bytes(trame[2:4], "little")
    contenu = trame[6:6 + longueur]
    if len(contenu) != longueur:
        return None
    attendu = int.from_bytes(trame[4:6], "little")
    return {
        "commande": trame[1],
        "contenu": contenu,
        "crc_valide": crc_modbus(contenu) == attendu,
        "reste": trame[6 + longueur:],
    }


def decrire(trame: bytes) -> str:
    """Ce qu'on croit comprendre d'une trame, en francais. Le peu qu'on sait est dit tel quel."""
    lu = lire(trame)
    if lu is None:
        return "trame illisible : " + trame.hex()
    mot = "commande 0x{:02x}".format(lu["commande"])
    if not lu["crc_valide"]:
        return mot + " — SOMME FAUSSE, contenu " + lu["contenu"].hex()
    contenu = lu["contenu"]
    # Seule interpretation etablie a ce jour : 0x73 / sous-commande 0x05 porte la batterie.
    if lu["commande"] == 0x73 and len(contenu) == 3 and contenu[0] == 0x05:
        return "batterie : {} %".format(contenu[1])
    return mot + ", contenu " + contenu.hex() + " (sens inconnu)"


def batterie(trame: bytes) -> int | None:
    """Le niveau de batterie annoncé par une trame, ou None si elle dit autre chose.

    Les lunettes n'exposent AUCUNE caractéristique de batterie standard : la lecture GATT
    habituelle renvoie vide, et IRIS affichait donc « batterie inconnue » en permanence. Le
    niveau ne circule que dans cette trame maison, et c'est le seul moyen de le connaître."""
    lu = lire(trame)
    if not lu or not lu["crc_valide"] or lu["commande"] != 0x73:
        return None
    contenu = lu["contenu"]
    if len(contenu) != 3 or contenu[0] != 0x05:
        return None
    niveau = contenu[1]
    return niveau if 0 <= niveau <= 100 else None


if __name__ == "__main__":
    OBSERVEES = [
        "bc7303005e61055600",
        "bc7303005e91055500",
        "bc7303005f01055400",
        "bc7303005d31055300",
    ]
    print("=== Relecture des trames reellement observees ===")
    for hexa in OBSERVEES:
        trame = bytes.fromhex(hexa)
        lu = lire(trame)
        print("  {}  somme {}  ->  {}".format(
            hexa, "juste" if lu and lu["crc_valide"] else "FAUSSE", decrire(trame)))

    print("\n=== Aller-retour : ce qu'on fabrique se relit-il ? ===")
    for commande, contenu in ((0x73, bytes([0x05, 99, 0x00])), (0x73, b""), (0x01, bytes([0x00]))):
        trame = fabriquer(commande, contenu)
        lu = lire(trame)
        etat = "OK" if lu and lu["crc_valide"] and lu["contenu"] == contenu else "CASSE"
        print("  0x{:02x} + {:<10} -> {:<24} {}".format(commande, contenu.hex() or "(vide)", trame.hex(), etat))

    print("\n=== Preuve : une trame fabriquee est identique a celle observee ===")
    refaite = fabriquer(0x73, bytes([0x05, 86, 0x00]))
    print("  fabriquee : " + refaite.hex())
    print("  observee  : " + OBSERVEES[0])
    print("  identiques : " + ("OUI" if refaite.hex() == OBSERVEES[0] else "NON"))
