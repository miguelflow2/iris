// TramesLunettes.swift — le protocole des lunettes VELA, porté en Swift.
//
// Portage fidèle de backend/iris/lunettes_trames.py (trames 0xBC, prouvées sur quatre trames réellement
// observées) et de backend/iris/lunettes_camera.py (commande photo sur ae01/ae02, NON prouvée).
// Ce qui est sûr et ce qui ne l'est pas est dit ici, et répété dans les messages de l'app :
//
//   PROUVÉ (sur la paire audio M01 Pro, canal de5bf729/de5bf72a) :
//     bc | commande | longueur (2 octets, petit-boutiste) | CRC-16/MODBUS du contenu (2 octets, petit-
//     boutiste) | contenu. Commande 0x73, contenu « 05 BB 00 » : BB = batterie en %.
//
//   IDENTIFIÉ DANS LE SDK DU FABRICANT, JAMAIS ESSAYÉ SUR LE VRAI MATÉRIEL :
//     service ae00, écriture ae01, notifications ae02 ; charge utile photo « 01 04 00 » dans une trame de
//     type « Camera » (2) ; le fichier revient en trames 11 (début), 12 (paquet), 13 (fin).
//
//   NON CONFIRMÉ :
//     l'en-tête de 5 octets de la trame « Pro » (octet magique, place du type, de la longueur, du CRC).
//     L'hypothèse ci-dessous (0xFE | type | longueur | CRC-16/MODBUS | charge) n'est PAS prouvée. Sur ces
//     puces, les commandes voisines portent le micrologiciel et l'effacement : l'app REFUSE donc d'écrire
//     cette trame, sauf accès d'exploration du propriétaire (voir LunettesBLE.explorationPermise).

import CoreBluetooth
import Foundation
import ImageIO

enum TramesLunettes {
    static let magie: UInt8 = 0xBC
    static let commandeBatterie: UInt8 = 0x73

    /// CRC-16/MODBUS : polynôme 0x8005 réfléchi (0xA001), départ 0xFFFF. Même calcul que crc_modbus().
    static func crcModbus(_ donnees: [UInt8]) -> UInt16 {
        var registre: UInt16 = 0xFFFF
        for octet in donnees {
            registre ^= UInt16(octet)
            for _ in 0..<8 {
                if registre & 1 != 0 {
                    registre = (registre >> 1) ^ 0xA001
                } else {
                    registre >>= 1
                }
            }
        }
        return registre
    }

    /// Fabrique une trame 0xBC valide (même résultat que lunettes_trames.fabriquer).
    static func fabriquer(commande: UInt8, contenu: [UInt8]) -> [UInt8] {
        let longueur = UInt16(truncatingIfNeeded: contenu.count)
        let crc = crcModbus(contenu)
        return [magie, commande,
                UInt8(longueur & 0xFF), UInt8(longueur >> 8),
                UInt8(crc & 0xFF), UInt8(crc >> 8)] + contenu
    }

    struct TrameLue: Equatable {
        let commande: UInt8
        let contenu: [UInt8]
        let crcValide: Bool
        let reste: [UInt8]
    }

    /// Décompose une trame reçue ; nil si elle est mal formée (la somme fausse est rapportée, pas cachée).
    static func lire(_ trame: [UInt8]) -> TrameLue? {
        guard trame.count >= 6, trame[0] == magie else { return nil }
        let longueur = Int(trame[2]) | (Int(trame[3]) << 8)
        guard trame.count >= 6 + longueur else { return nil }
        let contenu = Array(trame[6..<(6 + longueur)])
        let attendu = UInt16(trame[4]) | (UInt16(trame[5]) << 8)
        return TrameLue(commande: trame[1], contenu: contenu,
                        crcValide: crcModbus(contenu) == attendu,
                        reste: Array(trame[(6 + longueur)...]))
    }

    /// Niveau de batterie annoncé par une trame, ou nil si elle dit autre chose. Ces lunettes n'exposent
    /// pas toujours la caractéristique de batterie standard : cette trame maison est parfois le seul moyen.
    static func batterie(_ trame: [UInt8]) -> Int? {
        guard let lue = lire(trame), lue.crcValide, lue.commande == commandeBatterie,
              lue.contenu.count == 3, lue.contenu[0] == 0x05 else { return nil }
        let niveau = Int(lue.contenu[1])
        return (0...100).contains(niveau) ? niveau : nil
    }

    /// Les quatre trames réellement observées sur la paire audio (lunettes_trames.py, __main__).
    static let tramesObservees = [
        "bc7303005e61055600",
        "bc7303005e91055500",
        "bc7303005f01055400",
        "bc7303005d31055300",
    ]

    /// Relit les trames observées et refabrique la première : vrai si le portage colle au Python.
    /// Appelé une fois au lancement en compilation de débogage (assert), jamais en production.
    static func autoVerifier() -> Bool {
        for hexa in tramesObservees {
            guard let octets = octets(hexa: hexa), batterie(octets) != nil else { return false }
        }
        let refaite = fabriquer(commande: commandeBatterie, contenu: [0x05, 86, 0x00])
        return hexa(refaite) == tramesObservees[0]
    }

    static func octets(hexa: String) -> [UInt8]? {
        let propre = hexa.filter { !$0.isWhitespace }
        guard propre.count % 2 == 0 else { return nil }
        var sortie: [UInt8] = []
        sortie.reserveCapacity(propre.count / 2)
        var index = propre.startIndex
        while index < propre.endIndex {
            let suivant = propre.index(index, offsetBy: 2)
            guard let octet = UInt8(propre[index..<suivant], radix: 16) else { return nil }
            sortie.append(octet)
            index = suivant
        }
        return sortie
    }

    static func hexa(_ octets: [UInt8]) -> String {
        octets.map { String(format: "%02x", $0) }.joined()
    }
}

// MARK: - Identifiants Bluetooth

enum UUIDLunettes {
    /// Service applicatif des lunettes-caméra (Jieli RCSP) — [ÉTABLI] dans le SDK du fabricant.
    static let serviceCamera = CBUUID(string: "AE00")
    static let ecritureCamera = CBUUID(string: "AE01")
    static let notificationCamera = CBUUID(string: "AE02")
    /// Canal applicatif de la paire audio (protocole 0xBC) — [OBSERVÉ] sur le vrai matériel.
    static let serviceCommande = CBUUID(string: "DE5BF728-D711-4E47-AF26-65E3012A5DC7")
    static let notificationCommande = CBUUID(string: "DE5BF729-D711-4E47-AF26-65E3012A5DC7")
    static let ecritureCommande = CBUUID(string: "DE5BF72A-D711-4E47-AF26-65E3012A5DC7")
    /// Canal transparent des puces audio Jieli — [OBSERVÉ].
    static let serviceTransparent = CBUUID(string: "AE30")
    /// Batterie standard Bluetooth (souvent absente sur ces lunettes).
    static let serviceBatterie = CBUUID(string: "180F")
    static let niveauBatterie = CBUUID(string: "2A19")

    /// Services qui trahissent des lunettes de cette famille, pour retrouver une paire déjà reliée à l'iPhone.
    static let servicesConnus = [serviceCamera, serviceCommande, serviceTransparent]

    /// Indices de nom : génériques et propres à VELA, les mêmes que glasses.py (plus le nom de plateforme).
    static let indicesNom = ["vela", "m01", "iris", "glass", "lunette", "k900", "smart"]
}

// MARK: - Caméra (hypothèse non confirmée)

enum ProtocoleCamera {
    /// Faux tant qu'un relevé Bluetooth de l'application officielle ou un essai sur la vraie paire
    /// caméra n'a pas confirmé l'en-tête. À passer à vrai SEULEMENT après cette preuve.
    static let enteteConfirme = false

    static let chargePhoto: [UInt8] = [0x01, 0x04, 0x00]
    static let typeCamera: UInt8 = 2
    static let typeFichierDebut: UInt8 = 11
    static let typeFichierPaquet: UInt8 = 12
    static let typeFichierFin: UInt8 = 13
    static let magieHypothese: UInt8 = 0xFE

    /// HYPOTHÈSE (identique à fabriquer_trame_camera côté ordinateur) : 0xFE | type | longueur | CRC | charge.
    static func trameHypothese(charge: [UInt8], type: UInt8) -> [UInt8] {
        let longueur = UInt16(truncatingIfNeeded: charge.count)
        let crc = TramesLunettes.crcModbus(charge)
        return [magieHypothese, type,
                UInt8(longueur & 0xFF), UInt8(longueur >> 8),
                UInt8(crc & 0xFF), UInt8(crc >> 8)] + charge
    }
}

/// Rassemble les paquets ae02 pendant une photo et tente de reconstituer le JPEG.
///
/// Deux chemins, dans cet ordre :
/// 1. les paquets qui suivent l'en-tête supposé ET dont le CRC-16/MODBUS tombe juste : leurs charges sont
///    mises bout à bout (la somme juste est un indice fort que l'hypothèse d'en-tête est la bonne) ;
/// 2. sinon, le flux brut concaténé, entre le premier FF D8 FF et le dernier FF D9 (heuristique : les
///    en-têtes propriétaires de chaque paquet peuvent polluer l'image).
/// Dans les deux cas, l'image n'est rendue que si iOS arrive à la DÉCODER : jamais d'image inventée.
final class CollecteurPhoto {
    private(set) var paquets: [[UInt8]] = []
    private(set) var chargesVerifiees: [[UInt8]] = []
    private(set) var trameFinVue = false
    private(set) var octetsRecus = 0

    func ajouter(_ paquet: [UInt8]) {
        paquets.append(paquet)
        octetsRecus += paquet.count
        guard paquet.count >= 6, paquet[0] == ProtocoleCamera.magieHypothese else { return }
        let longueur = Int(paquet[2]) | (Int(paquet[3]) << 8)
        guard paquet.count >= 6 + longueur else { return }
        let charge = Array(paquet[6..<(6 + longueur)])
        let attendu = UInt16(paquet[4]) | (UInt16(paquet[5]) << 8)
        guard TramesLunettes.crcModbus(charge) == attendu else { return }
        if paquet[1] == ProtocoleCamera.typeFichierFin {
            trameFinVue = true
        } else if paquet[1] == ProtocoleCamera.typeFichierPaquet {
            chargesVerifiees.append(charge)
        }
    }

    /// Vrai quand il est inutile d'attendre davantage : trame de fin vue, ou fin de JPEG après son début.
    var termine: Bool {
        if trameFinVue { return true }
        guard let dernier = paquets.last, Self.contient(dernier, [0xFF, 0xD9]) else { return false }
        return paquets.contains { Self.contient($0, [0xFF, 0xD8]) }
    }

    /// (jpeg, méthode employée) ou nil si aucune image décodable n'est revenue.
    func assembler() -> (Data, String)? {
        if !chargesVerifiees.isEmpty, let image = Self.extraireJPEG(chargesVerifiees.flatMap { $0 }) {
            return (image, "trames à somme de contrôle juste")
        }
        if let image = Self.extraireJPEG(paquets.flatMap { $0 }) {
            return (image, "bornes JPEG dans le flux brut")
        }
        return nil
    }

    static func extraireJPEG(_ flux: [UInt8]) -> Data? {
        guard let debut = premiereOccurrence(flux, [0xFF, 0xD8, 0xFF]),
              let fin = derniereOccurrence(flux, [0xFF, 0xD9]), fin > debut else { return nil }
        let candidat = Data(flux[debut...(fin + 1)])
        guard candidat.count > 512, imageDecodable(candidat) else { return nil }
        return candidat
    }

    static func imageDecodable(_ donnees: Data) -> Bool {
        guard let source = CGImageSourceCreateWithData(donnees as CFData, nil),
              let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else { return false }
        return image.width > 0 && image.height > 0
    }

    private static func contient(_ flux: [UInt8], _ motif: [UInt8]) -> Bool {
        premiereOccurrence(flux, motif) != nil
    }

    private static func premiereOccurrence(_ flux: [UInt8], _ motif: [UInt8]) -> Int? {
        guard flux.count >= motif.count, !motif.isEmpty else { return nil }
        var i = 0
        while i <= flux.count - motif.count {
            if flux[i] == motif[0] && Array(flux[i..<(i + motif.count)]) == motif { return i }
            i += 1
        }
        return nil
    }

    private static func derniereOccurrence(_ flux: [UInt8], _ motif: [UInt8]) -> Int? {
        guard flux.count >= motif.count, !motif.isEmpty else { return nil }
        var i = flux.count - motif.count
        while i >= 0 {
            if flux[i] == motif[0] && Array(flux[i..<(i + motif.count)]) == motif { return i }
            i -= 1
        }
        return nil
    }
}
