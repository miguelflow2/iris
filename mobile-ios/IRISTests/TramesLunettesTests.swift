// TramesLunettesTests.swift — le portage Swift du protocole des lunettes doit rendre EXACTEMENT les octets
// du service Python (backend/iris/lunettes_trames.py et lunettes_camera.py).
//
// Les valeurs attendues ont été recalculées côté Python par mobile-ios/outils/verifier_ios.py (qui relit
// aussi ce fichier) : si l'un des deux côtés change, ce script échoue.

import CoreBluetooth
import UIKit
import XCTest
@testable import IRIS

final class TramesLunettesTests: XCTestCase {
    func testTramesObserveesRelues() throws {
        let attendus = [86, 85, 84, 83]
        for (hexa, niveau) in zip(TramesLunettes.tramesObservees, attendus) {
            let octets = try XCTUnwrap(TramesLunettes.octets(hexa: hexa))
            XCTAssertEqual(TramesLunettes.batterie(octets), niveau, hexa)
        }
    }

    func testFabriquerRedonneLaTrameObservee() {
        let trame = TramesLunettes.fabriquer(commande: 0x73, contenu: [0x05, 86, 0x00])
        XCTAssertEqual(TramesLunettes.hexa(trame), "bc7303005e61055600")
        XCTAssertTrue(TramesLunettes.autoVerifier())
    }

    func testCrcModbus() {
        XCTAssertEqual(TramesLunettes.crcModbus([]), 0xFFFF)
        XCTAssertEqual(TramesLunettes.crcModbus([0x01, 0x04, 0x00]), 0xC022)
    }

    func testTrameHypotheseCamera() {
        let trame = ProtocoleCamera.trameHypothese(charge: ProtocoleCamera.chargePhoto, type: ProtocoleCamera.typeCamera)
        XCTAssertEqual(TramesLunettes.hexa(trame), "fe02030022c0010400")
        // Tant que l'en-tête n'est pas confirmé sur le vrai matériel, l'app refuse de l'écrire.
        XCTAssertFalse(ProtocoleCamera.enteteConfirme)
    }

    func testSommeFausseRapporteeEtBatterieRefusee() throws {
        var octets = try XCTUnwrap(TramesLunettes.octets(hexa: "bc7303005e61055600"))
        octets[4] ^= 0xFF
        XCTAssertEqual(TramesLunettes.lire(octets)?.crcValide, false)
        XCTAssertNil(TramesLunettes.batterie(octets))
        XCTAssertNil(TramesLunettes.lire([0xBC, 0x73]))
    }

    // MARK: - Photo

    private func jpegDeTest() throws -> Data {
        let taille = CGSize(width: 160, height: 120)
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        let rendu = UIGraphicsImageRenderer(size: taille, format: format)
        let donnees = rendu.jpegData(withCompressionQuality: 0.95) { contexte in
            for i in 0..<40 {
                UIColor(hue: CGFloat(i) / 40, saturation: 0.8, brightness: 0.9, alpha: 1).setFill()
                contexte.fill(CGRect(x: CGFloat(i * 4), y: CGFloat((i * 7) % 100), width: 20, height: 20))
            }
        }
        XCTAssertGreaterThan(donnees.count, 512)
        return donnees
    }

    private func trame(type: UInt8, charge: [UInt8]) -> [UInt8] {
        ProtocoleCamera.trameHypothese(charge: charge, type: type)
    }

    func testCollecteurReconstitueLesTramesVerifiees() throws {
        let jpeg = [UInt8](try jpegDeTest())
        let collecteur = CollecteurPhoto()
        var debut = 0
        while debut < jpeg.count {
            let fin = min(debut + 180, jpeg.count)
            collecteur.ajouter(trame(type: ProtocoleCamera.typeFichierPaquet, charge: Array(jpeg[debut..<fin])))
            debut = fin
        }
        XCTAssertFalse(collecteur.trameFinVue)
        collecteur.ajouter(trame(type: ProtocoleCamera.typeFichierFin, charge: []))
        XCTAssertTrue(collecteur.termine)
        let (image, methode) = try XCTUnwrap(collecteur.assembler())
        XCTAssertEqual(methode, "trames à somme de contrôle juste")
        XCTAssertEqual([UInt8](image), jpeg)
    }

    func testCollecteurRepliSurLeFluxBrut() throws {
        let jpeg = [UInt8](try jpegDeTest())
        let collecteur = CollecteurPhoto()
        // Les deux derniers octets (FF D9, fin du JPEG) arrivent ensemble dans le dernier paquet : sinon un
        // découpage malchanceux les séparerait et `termine` dépendrait de la taille de l'image.
        let corps = jpeg.count - 2
        var debut = 0
        while debut < corps {
            let fin = min(debut + 200, corps)
            collecteur.ajouter(Array(jpeg[debut..<fin]))
            debut = fin
        }
        collecteur.ajouter(Array(jpeg[corps...]))
        XCTAssertTrue(collecteur.termine)
        let (_, methode) = try XCTUnwrap(collecteur.assembler())
        XCTAssertEqual(methode, "bornes JPEG dans le flux brut")
    }

    func testCollecteurNInventeRien() {
        let collecteur = CollecteurPhoto()
        collecteur.ajouter([0xFF, 0xD8, 0xFF, 0x00, 0x01, 0xFF, 0xD9])
        XCTAssertNil(collecteur.assembler())
    }

    // MARK: - Reconnaître des lunettes VELA

    func testSeulsLesServicesConnusVerifientDesLunettes() {
        XCTAssertTrue(LunettesBLE.servicesReconnus([CBUUID(string: "AE00")]))
        XCTAssertTrue(LunettesBLE.servicesReconnus([CBUUID(string: "180F"), CBUUID(string: "DE5BF728-D711-4E47-AF26-65E3012A5DC7")]))
        XCTAssertFalse(LunettesBLE.servicesReconnus([CBUUID(string: "180F"), CBUUID(string: "180D")]))
        XCTAssertFalse(LunettesBLE.servicesReconnus([]))
    }

    func testIndicesDeNomEtroits() {
        XCTAssertTrue(LunettesBLE.nomRessemble("M01 Pro_F444"))
        XCTAssertTrue(LunettesBLE.nomRessemble("VELA K900"))
        XCTAssertFalse(LunettesBLE.nomRessemble("SmartBand 7"))
        XCTAssertFalse(LunettesBLE.nomRessemble("Glass Speaker"))
        XCTAssertFalse(LunettesBLE.nomRessemble("iris-montre"))
        XCTAssertFalse(LunettesBLE.nomRessemble(nil))
    }
}
