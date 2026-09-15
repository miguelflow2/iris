// PerceptionEtConfianceTests.swift — ce qui est dit à une personne malvoyante (couleur, billet), quand les
// alertes s'arrêtent, quelle zone sans mémoire est signalée, et si le texte reste lisible.

import XCTest
@testable import IRIS

final class AnalyseImageLocaleTests: XCTestCase {
    func testNomsDeCouleur() {
        // Valeurs recalculées par outils/verifier_ios.py avec le même algorithme.
        XCTAssertEqual(AnalyseImageLocale.nomCouleur(r: 1, v: 0, b: 0), "rouge")
        XCTAssertEqual(AnalyseImageLocale.nomCouleur(r: 0, v: 0, b: 1), "bleu")
        XCTAssertEqual(AnalyseImageLocale.nomCouleur(r: 0, v: 0.8, b: 0), "vert")
        XCTAssertEqual(AnalyseImageLocale.nomCouleur(r: 1, v: 1, b: 0), "jaune")
        XCTAssertEqual(AnalyseImageLocale.nomCouleur(r: 0.05, v: 0.05, b: 0.05), "noir")
        XCTAssertEqual(AnalyseImageLocale.nomCouleur(r: 1, v: 1, b: 1), "blanc")
        XCTAssertEqual(AnalyseImageLocale.nomCouleur(r: 0.5, v: 0.5, b: 0.5), "gris")
        XCTAssertEqual(AnalyseImageLocale.nomCouleur(r: 0.4, v: 0.2, b: 0.05), "brun")
        XCTAssertEqual(AnalyseImageLocale.nomCouleur(r: 1, v: 0.75, b: 0.8), "rose")
        XCTAssertEqual(AnalyseImageLocale.nomCouleur(r: 0, v: 0, b: 0.25), "bleu foncé")
    }

    private func ligne(_ texte: String) -> LigneLue {
        LigneLue(texte: texte, hauteur: 0.1, confiance: 1, centreX: 0.5, centreY: 0.5)
    }

    func testBilletExigeLeChiffreEtLeMot() {
        let vingt = AnalyseImageLocale.coupuresLues([ligne("20 VINGT")])
        XCTAssertEqual(vingt.map { $0.valeur }, [20])
        XCTAssertEqual(vingt.first?.preuves, ["20", "VINGT"])
        // Le chiffre seul ne suffit pas : un « 20 » peut être n'importe quoi (date, adresse).
        XCTAssertTrue(AnalyseImageLocale.coupuresLues([ligne("20")]).isEmpty)
        XCTAssertTrue(AnalyseImageLocale.coupuresLues([ligne("VINGT")]).isEmpty)
    }

    func testBilletsBilinguesEtPlusieursCoupures() {
        XCTAssertEqual(AnalyseImageLocale.coupuresLues([ligne("Banque du Canada"), ligne("twenty dollars 20")]).map { $0.valeur }, [20])
        XCTAssertEqual(AnalyseImageLocale.coupuresLues([ligne("5 cinq"), ligne("10 TEN")]).map { $0.valeur }, [5, 10])
        // « CINQUANTE » n'est pas « CINQ » : jetons entiers.
        XCTAssertEqual(AnalyseImageLocale.coupuresLues([ligne("50 CINQUANTE")]).map { $0.valeur }, [50])
    }
}

// Sur le MainActor par prudence : la classe testée est isolée au MainActor (ses constantes, elles, ne le sont pas).
@MainActor
final class AlertesSansLunettesTests: XCTestCase {
    func testArretApresDixMinutesSeulement() {
        let maintenant = Date()
        let delai = AlertesSonoresTelephone.delaiSansLunettes
        XCTAssertEqual(delai, 600)
        XCTAssertFalse(AlertesSonoresTelephone.doitArreterSansLunettes(absentesDepuis: nil, maintenant: maintenant, delai: delai))
        XCTAssertFalse(AlertesSonoresTelephone.doitArreterSansLunettes(absentesDepuis: maintenant.addingTimeInterval(-599),
                                                                       maintenant: maintenant, delai: delai))
        XCTAssertTrue(AlertesSonoresTelephone.doitArreterSansLunettes(absentesDepuis: maintenant.addingTimeInterval(-600),
                                                                      maintenant: maintenant, delai: delai))
    }

    /// En arrière-plan, le pont est fermé : les alertes sondent elles-mêmes l'ordinateur (constat du 2026-09-14).
    func testSondageEnArrierePlanSeulementEtParMinute() {
        let maintenant = Date()
        XCTAssertEqual(AlertesSonoresTelephone.intervalleSondageArrierePlan, 60)
        XCTAssertFalse(AlertesSonoresTelephone.doitSonderArrierePlan(enArrierePlan: false, pontConfigure: true,
                                                                     dernier: nil, maintenant: maintenant))
        XCTAssertFalse(AlertesSonoresTelephone.doitSonderArrierePlan(enArrierePlan: true, pontConfigure: false,
                                                                     dernier: nil, maintenant: maintenant))
        XCTAssertTrue(AlertesSonoresTelephone.doitSonderArrierePlan(enArrierePlan: true, pontConfigure: true,
                                                                    dernier: nil, maintenant: maintenant))
        XCTAssertFalse(AlertesSonoresTelephone.doitSonderArrierePlan(enArrierePlan: true, pontConfigure: true,
                                                                     dernier: maintenant.addingTimeInterval(-59),
                                                                     maintenant: maintenant))
        XCTAssertTrue(AlertesSonoresTelephone.doitSonderArrierePlan(enArrierePlan: true, pontConfigure: true,
                                                                    dernier: maintenant.addingTimeInterval(-60),
                                                                    maintenant: maintenant))
    }

    func testModeConfidentielOuVerrouArretentLesAlertesEnArrierePlan() {
        typealias A = AlertesSonoresTelephone
        XCTAssertEqual(A.decisionSondage(privacyMode: true, erreur: nil), .confidentiel)
        XCTAssertEqual(A.decisionSondage(privacyMode: false, erreur: nil), .continuer)
        XCTAssertEqual(A.decisionSondage(privacyMode: nil, erreur: nil), .continuer)
        // 401 « verrouillée » tel que le pont le classe, et session révoquée par un effacement à distance.
        let verrou = ClientPontPC.classerRefus(statut: 401, data: Data(#"{"detail":"IRIS est verrouillée à distance. Déverrouillez-la avec le mot de passe du propriétaire."}"#.utf8), chemin: "/api/settings").0
        XCTAssertEqual(A.decisionSondage(privacyMode: nil, erreur: verrou), .verrou)
        let effacement = ClientPontPC.classerRefus(statut: 401, data: Data(#"{"detail":{"code":"efface_a_distance","message":"IRIS a été effacée à distance et est verrouillée."}}"#.utf8), chemin: "/api/settings").0
        XCTAssertEqual(A.decisionSondage(privacyMode: nil, erreur: effacement), .verrou)
        // Ordinateur injoignable : on ne sait pas, les alertes continuent (c'est dit dans `limite`).
        XCTAssertEqual(A.decisionSondage(privacyMode: nil, erreur: ErreurPont.injoignable("x")), .continuer)
    }
}

final class ZonesTests: XCTestCase {
    private func zone(_ id: String, rayon: Double) -> ZoneSansMemoire {
        ZoneSansMemoire(id: id, nom: id, lat: 45.5, lon: -73.6, rayonM: rayon)
    }

    func testLaPlusPetiteZoneOccupeeEstSignalee() {
        let zones = [zone("maison", rayon: 300), zone("bureau", rayon: 80), zone("gym", rayon: 50)]
        XCTAssertEqual(SurveillanceZones.zoneCourante(zones: zones, dedans: ["maison", "bureau"]), "bureau")
        XCTAssertNil(SurveillanceZones.zoneCourante(zones: zones, dedans: []))
        // Une zone supprimée sur l'ordinateur ne compte plus.
        XCTAssertNil(SurveillanceZones.zoneCourante(zones: zones, dedans: ["ancienne"]))
    }

    func testReveilAvantLeChargementDeLaListe() {
        XCTAssertEqual(SurveillanceZones.zoneCourante(zones: [], dedans: ["b", "a"]), "a")
    }
}

final class ContrasteTests: XCTestCase {
    func testTexteAttenueLisibleSurLesCartesEtLeFond() {
        // WCAG 2.1 AA, petit texte : 4,5:1.
        XCTAssertGreaterThanOrEqual(PaletteRGB.contraste(PaletteRGB.attenue, PaletteRGB.carte), 4.5)
        XCTAssertGreaterThanOrEqual(PaletteRGB.contraste(PaletteRGB.attenue, PaletteRGB.fond), 4.5)
        XCTAssertGreaterThanOrEqual(PaletteRGB.contraste(PaletteRGB.attenue, PaletteRGB.fond2), 4.5)
        XCTAssertGreaterThanOrEqual(PaletteRGB.contraste(PaletteRGB.texte2, PaletteRGB.carte2), 4.5)
    }

    func testFormuleDeContraste() {
        XCTAssertEqual(PaletteRGB.contraste(0xFFFFFF, 0x000000), 21, accuracy: 0.01)
        XCTAssertEqual(PaletteRGB.contraste(0x777777, 0x777777), 1, accuracy: 0.0001)
    }
}
