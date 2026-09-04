"""Diagnostic des lunettes : peut-on modifier leur logiciel interne ?

STRICTEMENT EN LECTURE SEULE. Ce script ne écrit rien dans les lunettes, ne flashe rien,
ne modifie aucun réglage. Il se contente de regarder ce qu'elles exposent, ce qui suffit
à répondre à la question sans prendre le moindre risque de les abîmer.

Il regarde quatre choses :
  1. USB   — les lunettes apparaissent-elles quand on les branche, et sous quelle identité ?
             Le couple VID/PID identifie le fabricant de la puce, c'est le renseignement le plus utile.
  2. BLE   — tous les services et caractéristiques Bluetooth, avec ce qu'on peut y lire.
  3. Identité — le service d'information standard donne le fabricant, le modèle, la version du
             logiciel interne et celle du matériel. C'est souvent là qu'on découvre la vraie puce.
  4. Mise à jour — présence d'un service de mise à jour du logiciel interne (OTA/DFU) connu.
             C'est ce service qui déterminera si une modification est envisageable.

Usage : backend/.venv/Scripts/python scripts/diagnostic-lunettes.py
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
from datetime import datetime

# --------------------------------------------------------------------------- services connus
# Services de mise à jour du logiciel interne. Leur présence est le signal le plus important :
# sans l'un d'eux (ou un équivalent propriétaire), aucune modification n'est possible sans
# ouvrir le boîtier et souder sur les broches de programmation.
SERVICES_MAJ = {
    "0000fe59-0000-1000-8000-00805f9b34fb": "Nordic Secure DFU (nRF52) — protocole documenté, outils libres",
    "00001530-1212-efde-1523-785feabcd123": "Nordic Legacy DFU (nRF51) — protocole documenté",
    "1d14d6ee-fd63-4fa1-bfa4-8f47b42119f0": "Silicon Labs OTA — documenté",
    "00010203-0405-0607-0809-0a0b0c0d1912": "Telink OTA — semi-documenté",
    "0000d0ff-3c17-d293-8e48-14fe2e4da212": "Realtek / Bee OTA — propriétaire",
    "00006287-3c17-d293-8e48-14fe2e4da212": "Airoha OTA — propriétaire",
    "0000ae00-0000-1000-8000-00805f9b34fb": "JieLi (AC69xx) OTA — propriétaire, très courant sur l'audio Bluetooth bon marché",
    "0000fee9-0000-1000-8000-00805f9b34fb": "BES / Bestechnic OTA — propriétaire",
    "0000fee7-0000-1000-8000-00805f9b34fb": "Actions Semiconductor OTA — propriétaire",
    "0000ffe0-0000-1000-8000-00805f9b34fb": "HM-10 / transparent série — souvent un canal de commande",
    "6e400001-b5a3-f393-e0a9-e50e24dcca9e": "Nordic UART — canal série sur BLE, souvent le canal de commande du fabricant",
}

# Caractéristiques standard qui révèlent l'identité réelle du matériel.
INFO_APPAREIL = {
    "00002a29-0000-1000-8000-00805f9b34fb": "Fabricant",
    "00002a24-0000-1000-8000-00805f9b34fb": "Modèle",
    "00002a25-0000-1000-8000-00805f9b34fb": "Numéro de série",
    "00002a27-0000-1000-8000-00805f9b34fb": "Révision matérielle",
    "00002a26-0000-1000-8000-00805f9b34fb": "Version du logiciel interne",
    "00002a28-0000-1000-8000-00805f9b34fb": "Version logicielle",
    "00002a23-0000-1000-8000-00805f9b34fb": "Identifiant système",
    "00002a50-0000-1000-8000-00805f9b34fb": "Identifiant PnP (VID/PID Bluetooth)",
    "00002a00-0000-1000-8000-00805f9b34fb": "Nom de l'appareil",
    "00002a19-0000-1000-8000-00805f9b34fb": "Niveau de batterie",
}

SERVICES_STANDARD = {
    "00001800": "Accès générique (nom, apparence)",
    "00001801": "Attributs génériques",
    "0000180a": "Information sur l'appareil",
    "0000180f": "Batterie",
    "00001812": "Périphérique d'entrée (HID) — boutons des lunettes",
    "0000110a": "Source audio (A2DP)",
    "0000111e": "Mains libres (HFP)",
    "00001101": "Port série (SPP) — canal de commande",
}

MOTS_LUNETTES = ("glass", "lunette", "vela", "iris", "smart", "k900", "audio", "bt", "tws", "eyewear")


def adresse_configuree() -> str:
    """Adresse des lunettes retenue dans les réglages d'IRIS, si elle existe."""
    import os
    from pathlib import Path as _P

    fichier = _P(os.path.expandvars(r"%APPDATA%\IRIS\iris-data\settings.json"))
    try:
        data = json.loads(fichier.read_text(encoding="utf-8"))
        return (data.get("glasses") or {}).get("address", "")
    except Exception:
        return ""


def titre(texte: str) -> None:
    print(f"\n{'=' * 78}\n  {texte}\n{'=' * 78}")


def ps(commande: str) -> str:
    """Exécute une commande PowerShell et renvoie sa sortie."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", commande],
            capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace",
        )
        return (r.stdout or "").strip()
    except Exception as exc:
        return f"(erreur : {exc})"


# --------------------------------------------------------------------------- 1. USB
def examiner_usb() -> None:
    titre("1. USB — les lunettes sont-elles vues quand on les branche ?")
    sortie = ps(
        "Get-CimInstance Win32_PnPEntity | "
        "Where-Object { $_.PNPDeviceID -like 'USB*' } | "
        "Select-Object Name, PNPDeviceID, Service, Status | ConvertTo-Json -Depth 2"
    )
    try:
        appareils = json.loads(sortie) if sortie.startswith(("[", "{")) else []
    except json.JSONDecodeError:
        appareils = []
    if isinstance(appareils, dict):
        appareils = [appareils]

    interessants = []
    for a in appareils:
        nom = (a.get("Name") or "").lower()
        pnp = a.get("PNPDeviceID") or ""
        service = (a.get("Service") or "").lower()
        # On garde ce qui ressemble à un appareil audio, série, HID composite ou en mode
        # programmation, et tout ce qui porte un nom évoquant des lunettes.
        if (any(m in nom for m in MOTS_LUNETTES)
                or service in ("usbser", "winusb", "libusb0", "winusb.sys")
                or "dfu" in nom or "bootloader" in nom
                or "serial" in nom or "com" in nom and "port" in nom):
            interessants.append(a)

    print(f"{len(appareils)} appareils USB au total.")
    if not interessants:
        print("\n  Aucun appareil USB ne ressemble aux lunettes.")
        print("  Deux explications possibles, et il faut les distinguer :")
        print("    a) le câble ne transporte que le courant (très fréquent pour un câble de charge) ;")
        print("    b) les lunettes se chargent sans exposer d'interface de données.")
        print("  Pour trancher : rebranchez-les avec un câble de données connu (celui d'un téléphone")
        print("  Android, par exemple) et relancez. Si rien n'apparaît toujours, c'est (b).")
    else:
        print("\n  Appareils potentiellement liés aux lunettes :")
        for a in interessants:
            print(f"    · {a.get('Name')}")
            print(f"      {a.get('PNPDeviceID')}")
            print(f"      pilote : {a.get('Service') or '(aucun)'} · état : {a.get('Status')}")
            m = re.search(r"VID_([0-9A-F]{4})&PID_([0-9A-F]{4})", a.get("PNPDeviceID") or "", re.I)
            if m:
                print(f"      >>> VID {m.group(1)} / PID {m.group(2)} — identifiant du fabricant de la puce")

    # Ports série : un port COM qui apparaît au branchement est une porte d'entrée directe.
    coms = ps("Get-CimInstance Win32_SerialPort | Select-Object DeviceID, Description, PNPDeviceID | ConvertTo-Json")
    if coms and coms not in ("", "null"):
        print("\n  Ports série présents (un port qui n'apparaît QUE branché est un canal de commande) :")
        print("   ", coms.replace("\n", "\n    ")[:900])
    else:
        print("\n  Aucun port série. (Comparez avec les lunettes débranchées.)")


# --------------------------------------------------------------------------- 2. Bluetooth classique
def examiner_bluetooth_windows() -> None:
    titre("2. Bluetooth classique — profils exposés à Windows")
    sortie = ps(
        "Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue | "
        "Select-Object FriendlyName, InstanceId, Status | ConvertTo-Json -Depth 2"
    )
    try:
        appareils = json.loads(sortie) if sortie.startswith(("[", "{")) else []
    except json.JSONDecodeError:
        appareils = []
    if isinstance(appareils, dict):
        appareils = [appareils]

    lunettes = [a for a in appareils if any(m in (a.get("FriendlyName") or "").lower() for m in MOTS_LUNETTES)]
    if not lunettes:
        print("  Aucun appareil Bluetooth appairé ne porte un nom évoquant des lunettes.")
        print("  Appairez-les dans Windows (Paramètres › Bluetooth) avant de relancer.")
        return
    print(f"  {len(lunettes)} entrée(s) liée(s) aux lunettes :")
    for a in lunettes:
        print(f"    · {a.get('FriendlyName')} — {a.get('Status')}")
        iid = a.get("InstanceId") or ""
        if "SPP" in iid.upper() or "SERIAL" in iid.upper():
            print("      >>> profil SÉRIE détecté : canal de commande possible")


# --------------------------------------------------------------------------- 3. BLE
async def examiner_ble() -> None:
    titre("3. Bluetooth basse consommation — services, identité et mise à jour")
    try:
        from bleak import BleakClient, BleakScanner
    except ImportError:
        print("  bleak absent. Lancez ce script avec backend/.venv/Scripts/python.")
        return

    print("  Recherche en cours (12 s)…")
    trouves = await BleakScanner.discover(timeout=12.0, return_adv=True)
    if not trouves:
        print("  Aucun appareil BLE détecté. Allumez les lunettes et rapprochez-les.")
        return

    candidats = []
    for adresse, (appareil, adv) in trouves.items():
        nom = (appareil.name or adv.local_name or "").strip()
        score = 2 if any(m in nom.lower() for m in MOTS_LUNETTES) else 0
        candidats.append((score, adresse, nom or "(sans nom)", adv))
    candidats.sort(key=lambda c: -c[0])

    print(f"\n  {len(candidats)} appareil(s) détecté(s) :")
    for score, adresse, nom, adv in candidats[:12]:
        marque = " <<< probablement les lunettes" if score else ""
        print(f"    {adresse}  {nom:28} {adv.rssi:4} dBm{marque}")
        if adv.manufacturer_data:
            for cid, data in adv.manufacturer_data.items():
                print(f"        fabricant 0x{cid:04x} : {bytes(data).hex()}")

    # On vise en priorité les lunettes retenues dans les réglages d'IRIS.
    configuree = adresse_configuree()
    if configuree:
        connues = [c for c in candidats if c[1].upper() == configuree.upper()]
        if connues:
            candidats = connues + [c for c in candidats if c not in connues]
        else:
            print(f"  Les lunettes configurées ({configuree}) ne diffusent pas en ce moment.")
            print("  Allumez-les et sortez-les de leur étui, puis relancez.")
    cibles = [c for c in candidats if c[0] > 0] or candidats[:1]
    for _score, adresse, nom, _adv in cibles[:2]:
        await inspecter(BleakClient, adresse, nom)


async def inspecter(BleakClient, adresse: str, nom: str) -> None:
    print(f"\n  --- Connexion à {nom} ({adresse}) ---")
    try:
        async with BleakClient(adresse, timeout=25.0) as client:
            if not client.is_connected:
                print("    Connexion refusée.")
                return
            print("    Connecté.\n")

            identite, maj, autres = {}, [], []
            for service in client.services:
                court = str(service.uuid)[:8].lower()
                libelle = SERVICES_STANDARD.get(court, "")
                si_maj = SERVICES_MAJ.get(str(service.uuid).lower())
                if si_maj:
                    maj.append((str(service.uuid), si_maj))
                elif not libelle:
                    autres.append(str(service.uuid))

                print(f"    Service {service.uuid}  {libelle or si_maj or '(propriétaire)'}")
                for c in service.characteristics:
                    props = ",".join(c.properties)
                    print(f"       {c.uuid}  [{props}]  {c.description or ''}")
                    if "read" in c.properties and str(c.uuid).lower() in INFO_APPAREIL:
                        try:
                            brut = await client.read_gatt_char(c)
                            texte = brut.decode("utf-8", "replace").strip("\x00").strip()
                            identite[INFO_APPAREIL[str(c.uuid).lower()]] = texte or brut.hex()
                        except Exception as exc:
                            identite[INFO_APPAREIL[str(c.uuid).lower()]] = f"(illisible : {type(exc).__name__})"

            if identite:
                print("\n    IDENTITÉ RÉELLE DU MATÉRIEL :")
                for cle, valeur in identite.items():
                    print(f"       {cle:32} : {valeur}")

            print("\n    VERDICT SUR LA MODIFICATION DU LOGICIEL INTERNE :")
            if maj:
                for uuid, description in maj:
                    print(f"       Service de mise à jour PRÉSENT : {uuid}")
                    print(f"         {description}")
                print("       => Une modification est techniquement envisageable par ce canal.")
                print("          Il faut d'abord obtenir le logiciel interne d'origine auprès du")
                print("          fournisseur : sans copie de secours, un essai raté rend les lunettes inutilisables.")
            else:
                print("       Aucun service de mise à jour connu n'est exposé en Bluetooth.")
                print("       Cela ne prouve pas l'impossibilité, mais cela veut dire que la")
                print("       modification passe obligatoirement par le fournisseur (kit de")
                print("       développement, logiciel interne sur mesure), pas par un bricolage local.")
            if autres:
                print(f"\n    {len(autres)} service(s) propriétaire(s) non identifié(s) :")
                for u in autres[:10]:
                    print(f"       {u}")
                print("       Ce sont probablement les canaux de commande du fabricant.")
    except Exception as exc:
        print(f"    Connexion impossible : {type(exc).__name__}: {exc}")
        print("    Les lunettes sont peut-être déjà connectées ailleurs (fermez IRIS et")
        print("    déconnectez-les des paramètres Bluetooth de Windows), ou trop loin.")


# --------------------------------------------------------------------------- conclusion
def conclusion() -> None:
    titre("4. Ce qu'il faut en retenir")
    print("""  Trois cas de figure possibles, du plus ouvert au plus fermé :

  A. Un service de mise à jour documenté (Nordic, Silicon Labs) est présent.
     Modification envisageable avec des outils libres. Il faut quand même la copie du
     logiciel interne d'origine, sinon un essai raté est définitif.

  B. Un service de mise à jour propriétaire est présent (JieLi, Realtek, Airoha, BES…).
     La modification passe par les outils du fabricant de la puce. C'est une négociation
     avec le fournisseur, pas un bricolage.

  C. Aucun service de mise à jour, ni interface USB de données.
     Le logiciel interne n'est pas modifiable à distance. Il faudrait ouvrir le boîtier et
     souder sur les broches de programmation : destructif, et sans intérêt pour un produit
     que vous voulez vendre.

  Dans TOUS les cas, la vraie question reste commerciale : pour vendre des lunettes
  modifiées, il faut un accord de fabrication avec le fournisseur. Ce diagnostic sert à
  savoir quoi lui demander, et à vérifier ses réponses.""")


async def main() -> int:
    print(f"Diagnostic des lunettes — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("LECTURE SEULE : rien n'est écrit dans les lunettes, aucun risque de les abîmer.")
    examiner_usb()
    examiner_bluetooth_windows()
    await examiner_ble()
    conclusion()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
