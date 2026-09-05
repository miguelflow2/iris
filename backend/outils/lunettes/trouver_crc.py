"""Trouver la somme de controle des trames des lunettes.

Quatre trames observees, toutes de la meme forme :

    bc 73 03 00 | 5e 61 | 05 56 00      octet de valeur 0x56 = 86
    bc 73 03 00 | 5e 91 | 05 55 00      0x55 = 85
    bc 73 03 00 | 5f 01 | 05 54 00      0x54 = 84
    bc 73 03 00 | 5d 31 | 05 53 00      0x53 = 83   (trente minutes plus tard)

Lecture proposee : `bc` marque le debut, `73` designe la commande, `03 00` est la longueur du
contenu sur deux octets, viennent ensuite DEUX octets qui ne suivent aucune progression — donc une
somme de controle — puis le contenu `05 BB 00`, ou BB descend de 86 a 83. Une batterie.

Si la somme de controle se confirme, on ne fait pas que LIRE les lunettes : on peut fabriquer des
trames valides, donc leur PARLER. C'est tout l'enjeu de ce programme.

On essaie les variantes courantes de CRC 16 bits, sur toutes les portions plausibles de la trame,
dans les deux ordres d'octets. Aucune communication : ce ne sont que des calculs.
"""

TRAMES = [
    bytes.fromhex("bc7303005e61055600"),
    bytes.fromhex("bc7303005e91055500"),
    bytes.fromhex("bc7303005f01055400"),
    bytes.fromhex("bc7303005d31055300"),
]


def crc16(donnees, poly, init, refin, refout, xorout):
    """CRC 16 bits generique, calcule bit a bit : lent, mais couvre toutes les variantes."""
    def miroir(valeur, bits):
        resultat = 0
        for _ in range(bits):
            resultat = (resultat << 1) | (valeur & 1)
            valeur >>= 1
        return resultat

    reg = init
    for octet in donnees:
        if refin:
            octet = miroir(octet, 8)
        reg ^= octet << 8
        for _ in range(8):
            reg = ((reg << 1) ^ poly) & 0xFFFF if reg & 0x8000 else (reg << 1) & 0xFFFF
    if refout:
        reg = miroir(reg, 16)
    return reg ^ xorout


# (nom, polynome, valeur initiale, entree inversee, sortie inversee, ou exclusif final)
VARIANTES = [
    ("CCITT-FALSE", 0x1021, 0xFFFF, False, False, 0x0000),
    ("XMODEM", 0x1021, 0x0000, False, False, 0x0000),
    ("KERMIT", 0x1021, 0x0000, True, True, 0x0000),
    ("MODBUS", 0x8005, 0xFFFF, True, True, 0x0000),
    ("ARC / IBM", 0x8005, 0x0000, True, True, 0x0000),
    ("MAXIM", 0x8005, 0x0000, True, True, 0xFFFF),
    ("USB", 0x8005, 0xFFFF, True, True, 0xFFFF),
    ("X-25", 0x1021, 0xFFFF, True, True, 0xFFFF),
    ("MCRF4XX", 0x1021, 0xFFFF, True, True, 0x0000),
    ("GENIBUS", 0x1021, 0xFFFF, False, False, 0xFFFF),
    ("DNP", 0x3D65, 0x0000, True, True, 0xFFFF),
    ("DECT-R", 0x0589, 0x0000, False, False, 0x0001),
    ("CDMA2000", 0xC867, 0xFFFF, False, False, 0x0000),
    ("TELEDISK", 0xA097, 0x0000, False, False, 0x0000),
]

# Quelles portions de la trame la somme pourrait-elle couvrir ?
PORTIONS = {
    "contenu seul (6:9)": lambda t: t[6:],
    "entete sans magie + contenu (1:4)+(6:9)": lambda t: t[1:4] + t[6:],
    "tout sauf magie et somme (1:4)+(6:9) inverse": lambda t: t[6:] + t[1:4],
    "depuis la magie, somme exclue (0:4)+(6:9)": lambda t: t[0:4] + t[6:],
    "longueur + contenu (2:4)+(6:9)": lambda t: t[2:4] + t[6:],
    "commande + contenu (1:2)+(6:9)": lambda t: t[1:2] + t[6:],
}

print("Recherche de la somme de controle sur {} trames\n".format(len(TRAMES)))
trouve = False
for nom_portion, decoupe in PORTIONS.items():
    for nom, poly, init, refin, refout, xorout in VARIANTES:
        for ordre in ("gros-boutiste", "petit-boutiste"):
            ok = True
            for trame in TRAMES:
                attendu = int.from_bytes(trame[4:6], "big" if ordre == "gros-boutiste" else "little")
                if crc16(decoupe(trame), poly, init, refin, refout, xorout) != attendu:
                    ok = False
                    break
            if ok:
                trouve = True
                print("TROUVE : {} / {} / {} sur << {} >>".format(nom, ordre, hex(poly), nom_portion))

if not trouve:
    print("Aucune variante standard ne correspond.\n")
    print("Ce que les octets 4 et 5 valent, trame par trame :")
    for trame in TRAMES:
        print("  contenu {} -> octets 4-5 = {}  (batterie {})".format(
            trame[6:].hex(), trame[4:6].hex(), trame[7]))
    print("\nSommes simples, pour comparaison :")
    for trame in TRAMES:
        contenu = trame[6:]
        somme = sum(contenu) & 0xFFFF
        ouex = 0
        for o in contenu:
            ouex ^= o
        print("  contenu {} : somme={:04x} ouexclusif={:02x} attendu={}".format(
            contenu.hex(), somme, ouex, trame[4:6].hex()))
    print("\nHypothese de rechange : les octets 4-5 ne sont pas une somme de controle mais une")
    print("mesure — une tension, par exemple. Valeurs, avec la batterie en regard :")
    for trame in TRAMES:
        for ordre, valeur in (("BE", int.from_bytes(trame[4:6], "big")), ("LE", int.from_bytes(trame[4:6], "little"))):
            print("  batterie {:3d} % -> {} {:6d}  ({:.3f} si millivolts/1000)".format(
                trame[7], ordre, valeur, valeur / 1000))
