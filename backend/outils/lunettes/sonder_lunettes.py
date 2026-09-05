"""Sonde les lunettes VELA : lire leur identite, ecouter ce qu'elles disent, puis leur parler.

Prudence deliberee. Trois etages, du plus sur au moins sur :
  1. LECTURE des caracteristiques standard : aucun risque, on ne fait que demander.
  2. ECOUTE des notifications : on note ce qu'elles emettent spontanement.
  3. ECRITURE sur le service UART Nordic uniquement. C'est un tuyau serie generique, prevu pour
     du texte : au pire le micrologiciel ignore ce qu'il ne comprend pas.

On ne touche PAS aux caracteristiques du fabricant (ae01, ae03, ae3b). Sur les puces JieLi, ce
sont elles qui portent le protocole proprietaire, mise a jour du micrologiciel comprise. Une
sequence mal devinee y couterait des lunettes.
"""
import asyncio
import sys
from datetime import datetime

from bleak import BleakClient

ADRESSE = "65:A2:9F:5C:F4:44"

STANDARD = {
    "00002a00-0000-1000-8000-00805f9b34fb": "Nom de l'appareil",
    "00002a25-0000-1000-8000-00805f9b34fb": "Numero de serie",
    "00002a27-0000-1000-8000-00805f9b34fb": "Revision materielle",
    "00002a26-0000-1000-8000-00805f9b34fb": "Revision micrologiciel",
    "00002a23-0000-1000-8000-00805f9b34fb": "Identifiant systeme",
}
LISIBLES_VENDEUR = {
    "0000ae10-0000-1000-8000-00805f9b34fb": "JieLi ae10",
    "00004a02-0000-1000-8000-00805f9b34fb": "Service 3802 / 4a02",
    "0000fee3-0000-1000-8000-00805f9b34fb": "Huami fee3",
}
UART_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"   # on ecrit ici
UART_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"   # elles repondent ici

recu = []


def horodate():
    return datetime.now().strftime("%H:%M:%S")


def noter(canal, donnees):
    brut = bytes(donnees)
    texte = brut.decode("utf-8", errors="replace")
    lisible = "".join(c if 32 <= ord(c) < 127 else "." for c in texte)
    recu.append((horodate(), canal, brut.hex(), lisible))
    print("   {} <- {:<12} {:<28} {}".format(horodate(), canal, brut.hex(), lisible), flush=True)


async def principal():
    print("Connexion a", ADRESSE, flush=True)
    async with BleakClient(ADRESSE, timeout=30.0) as client:
        print("Connecte.", flush=True)

        # ---------------------------------------------------------------- 1. lecture
        print("\n=== IDENTITE (lecture seule) ===", flush=True)
        for uuid, nom in {**STANDARD, **LISIBLES_VENDEUR}.items():
            try:
                brut = bytes(await client.read_gatt_char(uuid))
                texte = "".join(c if 32 <= c < 127 else "." for c in brut.decode("latin1")) if brut else ""
                print("  {:<24} {:<20} {}".format(nom, brut.hex(), texte), flush=True)
            except Exception as exc:
                print("  {:<24} (illisible : {})".format(nom, type(exc).__name__), flush=True)

        # ---------------------------------------------------------------- 2. ecoute
        print("\n=== ECOUTE (12 s, sans rien envoyer) ===", flush=True)
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
        print("  abonne a :", ", ".join(abonnes), flush=True)
        await asyncio.sleep(12)
        avant = len(recu)
        print("  {} paquet(s) recu(s) spontanement".format(avant), flush=True)

        # ---------------------------------------------------------------- 3. ecriture
        print("\n=== ON LEUR PARLE (UART Nordic uniquement) ===", flush=True)
        cr, lf = chr(13), chr(10)
        essais = [
            ("saut de ligne seul", (cr + lf).encode()),
            ("AT", ("AT" + cr + lf).encode()),
            ("AT+VERSION", ("AT+VERSION" + cr + lf).encode()),
            ("AT+BATT", ("AT+BATT" + cr + lf).encode()),
            ("texte simple", ("bonjour" + cr + lf).encode()),
            ("un seul zero", bytes([0x00])),
        ]
        for nom, charge in essais:
            marque = len(recu)
            try:
                await client.write_gatt_char(UART_RX, charge, response=False)
                print("  -> {:<20} {}".format(nom, charge.hex()), flush=True)
            except Exception as exc:
                print("  -> {:<20} REFUSE : {}".format(nom, exc), flush=True)
                continue
            await asyncio.sleep(2.5)
            if len(recu) == marque:
                print("     (aucune reponse)", flush=True)

        print("\n=== BILAN ===", flush=True)
        print("  {} paquet(s) au total, dont {} apres nos envois".format(len(recu), len(recu) - avant), flush=True)
        canaux = {}
        for _, canal, _, _ in recu:
            canaux[canal] = canaux.get(canal, 0) + 1
        for canal, n in sorted(canaux.items(), key=lambda x: -x[1]):
            print("  canal {} : {} paquet(s)".format(canal, n), flush=True)


try:
    asyncio.run(principal())
except Exception as exc:
    print("ECHEC :", type(exc).__name__, exc, flush=True)
    sys.exit(1)
