// PontTests.swift — adresses, refus, horodatages et décodage des réponses du service.
//
// Pourquoi ces tests : une adresse mal classée envoie le mot de passe en clair ; un refus mal classé
// efface la session au lieu d'afficher l'écran de verrouillage ; une erreur de décodage casse tous les écrans.

import XCTest
@testable import IRIS

final class AdressesTests: XCTestCase {
    func testHttpPermisSurLeReseauLocal() throws {
        XCTAssertEqual(try ClientPontPC.normaliserAdresse("http://192.168.1.5").absoluteString, "http://192.168.1.5")
        XCTAssertEqual(try ClientPontPC.normaliserAdresse("http://100.101.102.103:8765/").absoluteString,
                       "http://100.101.102.103:8765")
    }

    func testHttpRefuseHorsDuReseauLocal() {
        XCTAssertThrowsError(try ClientPontPC.normaliserAdresse("http://exemple.com"))
        XCTAssertThrowsError(try ClientPontPC.normaliserAdresse("ftp://192.168.1.5"))
        XCTAssertThrowsError(try ClientPontPC.normaliserAdresse("   "))
    }

    func testHttpsParDefaut() throws {
        XCTAssertEqual(try ClientPontPC.normaliserAdresse("bureau.tail1234.ts.net/").absoluteString,
                       "https://bureau.tail1234.ts.net")
    }

    func testPlagesLocales() {
        for hote in ["localhost", "monpc.local", "monpc", "10.0.0.2", "127.0.0.1", "172.16.0.1", "172.31.255.1",
                     "192.168.0.10", "169.254.1.1", "100.64.0.1", "100.127.255.254"] {
            XCTAssertTrue(ClientPontPC.estAdresseLocale(hote), hote)
        }
        for hote in ["172.32.0.1", "100.128.0.1", "8.8.8.8", "exemple.com", "192.169.0.1", "300.1.1.1"] {
            XCTAssertFalse(ClientPontPC.estAdresseLocale(hote), hote)
        }
    }
}

final class RefusDuPontTests: XCTestCase {
    private func classer(_ statut: Int, _ json: String, chemin: String = "/api/status") -> (ErreurPont, EffetRefus) {
        ClientPontPC.classerRefus(statut: statut, data: Data(json.utf8), chemin: chemin)
    }

    func testVerrouilleeNEffacePasLaSession() {
        let message = "IRIS est verrouillée à distance. Déverrouillez-la avec le mot de passe du propriétaire."
        let (erreur, effet) = classer(401, #"{"detail":"\#(message)"}"#)
        XCTAssertEqual(erreur, .verrouillee(message))
        XCTAssertEqual(effet, .verrouiller(message))
    }

    func testSessionRefuseeOublieeSaufALaConnexion() {
        let (erreur, effet) = classer(401, #"{"detail":"Session invalide ou expirée."}"#)
        XCTAssertEqual(erreur, .nonConnecte("Session invalide ou expirée."))
        XCTAssertEqual(effet, .oublierSession)
        XCTAssertEqual(classer(401, #"{"detail":"Mot de passe incorrect."}"#, chemin: "/api/compte/connexion").1, .aucun)
    }

    func testLunettesRequises() {
        let json = #"{"detail":{"code":"lunettes_requises","fonction":"vision","message":"Cette fonction marche avec les lunettes VELA.","acheter_url":"https://velaglass.ca/lunettes.html"}}"#
        let (erreur, effet) = classer(428, json)
        XCTAssertEqual(effet, .aucun)
        guard case .lunettesRequises(let refus) = erreur else { return XCTFail("428 doit devenir lunettesRequises") }
        XCTAssertEqual(refus.fonction, "vision")
        XCTAssertEqual(refus.acheterUrl, "https://velaglass.ca/lunettes.html")
    }

    func testConsentement() {
        let json = #"{"detail":{"code":"consentement","data_type":"image","label":"Images","message":"Accord requis."}}"#
        guard case .consentement(let refus) = classer(403, json).0 else { return XCTFail("403 consentement") }
        XCTAssertEqual(refus.dataType, "image")
    }

    func testAppareilNonAssocieProposeLAssociation() {
        let json = #"{"detail":"Ce téléphone n'est pas encore associé à tes lunettes sur cet IRIS. Pour l'associer, confirme avec le mot de passe du propriétaire."}"#
        XCTAssertTrue(AttestationLunettes.demandeAssociation(classer(403, json, chemin: "/api/lunettes/attestation").0))
        // Autres lunettes que la paire connue : on n'y propose PAS d'association (elle échouerait aussi).
        let autres = #"{"detail":"Ces lunettes ne sont pas celles associées à cet IRIS."}"#
        XCTAssertFalse(AttestationLunettes.demandeAssociation(classer(403, autres, chemin: "/api/lunettes/attestation").0))
        XCTAssertFalse(AttestationLunettes.demandeAssociation(ErreurPont.injoignable("x")))
    }

    /// La VRAIE réponse du service (lunettes_presence.attester) : detail en objet {code, message}.
    func testAppareilNonAssocieAvecDetailEnObjet() {
        let json = #"{"detail":{"code":"appareil_non_associe","message":"Ce téléphone n'est pas encore associé à tes lunettes sur cet IRIS. Pour l'associer, confirme avec le mot de passe du propriétaire."}}"#
        let (erreur, effet) = classer(403, json, chemin: "/api/lunettes/attestation")
        XCTAssertEqual(effet, .aucun)
        XCTAssertTrue(AttestationLunettes.demandeAssociation(erreur))
        XCTAssertTrue(erreur.errorDescription?.hasPrefix("Ce téléphone n'est pas encore associé") == true)
    }

    /// Téléphone perdu, en arrière-plan pendant l'effacement à distance : il n'a pas vu verrou.etat. À sa
    /// réouverture, le 401 (main.py, require_token) dit la cause ; l'app garde le verrou, oublie la session et
    /// retire les copies. Réponse exacte du service, rejouée par outils/verifier_ios.py.
    func testSessionRevoqueeParUnEffacementADistance() {
        let json = #"{"detail":{"code":"efface_a_distance","message":"IRIS a été effacée à distance et est verrouillée. Reconnectez-vous avec le mot de passe du propriétaire."}}"#
        for chemin in ["/api/status", "/api/confiance/verrou/etat", "/api/cours"] {
            let (erreur, effet) = classer(401, json, chemin: chemin)
            XCTAssertEqual(effet, .effacement, chemin)
            XCTAssertEqual(erreur, .verrouillee(ClientPontPC.raisonEffacement), chemin)
        }
        // Une session refusée pour une autre raison n'est PAS prise pour un effacement.
        XCTAssertEqual(classer(401, #"{"detail":"jeton de session invalide"}"#).1, .oublierSession)
    }

    /// Finition B du 2026-09-14 : après l'effacement, le propriétaire déverrouille son ordinateur puis clique
    /// « Déconnecter tous les appareils » AVANT que le téléphone perdu rouvre l'app. Le service gardait seulement le
    /// dernier motif de révocation : l'iPhone recevait « jeton de session invalide » et gardait ses cours. Le 401 porte
    /// maintenant encore le code, avec une phrase qui ne dit plus « verrouillée ». Réponse exacte du service, rejouée
    /// par outils/verifier_ios.py.
    func testEffacementVuApresDeconnexionDeTousLesAppareils() {
        let json = #"{"detail":{"code":"efface_a_distance","message":"IRIS a été effacée à distance. Reconnectez-vous avec le mot de passe du propriétaire."}}"#
        let (erreur, effet) = classer(401, json, chemin: "/api/status")
        XCTAssertEqual(effet, .effacement)
        XCTAssertEqual(erreur, .verrouillee(ClientPontPC.raisonEffacement))
    }

    /// Le retrait nomme CET iPhone : sans identifiant, le service effacerait l'attestation d'un autre appareil.
    func testLeRetraitDAttestationNommeCetAppareil() throws {
        let uuid = "A1B2C3D4-0000-4000-8000-00000000ABCD"   // forme de CBPeripheral.identifier.uuidString
        XCTAssertEqual(AttestationLunettes.parametresRetrait(identifiant: " \(uuid) "),
                       [URLQueryItem(name: "identifiant", value: uuid)])
        XCTAssertEqual(AttestationLunettes.parametresRetrait(identifiant: nil), [])
        XCTAssertEqual(AttestationLunettes.parametresRetrait(identifiant: "  "), [])
        var composants = try XCTUnwrap(URLComponents(string: "https://bureau.tail1234.ts.net"))
        composants.path = "/api/lunettes/attestation"
        composants.queryItems = AttestationLunettes.parametresRetrait(identifiant: uuid)
        XCTAssertEqual(composants.url?.absoluteString,
                       "https://bureau.tail1234.ts.net/api/lunettes/attestation?identifiant=\(uuid)")
    }

    func testAutresRefusGardentLeurPhrase() {
        let (erreur, _) = classer(409, #"{"detail":"Le mode confidentiel est actif."}"#)
        XCTAssertEqual(erreur.errorDescription, "Le mode confidentiel est actif.")
        XCTAssertEqual(erreur.statut, 409)
        let (validation, _) = classer(422, #"{"detail":[{"loc":["body","mode"],"msg":"field required"}]}"#)
        XCTAssertEqual(validation.errorDescription, "IRIS a refusé la demande : données incomplètes ou invalides.")
        XCTAssertEqual(classer(500, "pas du json").0.errorDescription, "L'ordinateur a répondu par une erreur (500).")
    }
}

final class DecodageTests: XCTestCase {
    private struct Boite: Codable { let h: Horodatage }

    private func horodatage(_ brut: String) throws -> Horodatage {
        try JSONIRIS.decodeur.decode(Boite.self, from: Data(#"{"h": \#(brut)}"#.utf8)).h
    }

    func testHorodatageIsoSansFuseauEstLHeureLocale() throws {
        let h = try horodatage(#""2026-09-13T14:05:12""#)
        let date = try XCTUnwrap(h.date)
        let c = Calendar.current.dateComponents([.year, .month, .day, .hour, .minute, .second], from: date)
        XCTAssertEqual([c.year, c.month, c.day, c.hour, c.minute, c.second], [2026, 9, 13, 14, 5, 12])
    }

    func testHorodatageIsoAvecFuseau() throws {
        XCTAssertEqual(try horodatage(#""2026-09-13T14:05:12+00:00""#).date?.timeIntervalSince1970, 1_789_308_312)
        XCTAssertNotNil(try horodatage(#""2026-09-13T14:05:12.123456""#).date)
    }

    func testHorodatageEnSecondes() throws {
        let h = try horodatage("1757800000.5")
        XCTAssertEqual(h.date?.timeIntervalSince1970, 1_757_800_000.5)
        XCTAssertEqual(h.secondes, 1_757_800_000.5)
        // Réencodé puis relu (copie gardée sur l'iPhone) : toujours des secondes.
        let relu = try JSONIRIS.decodeur.decode(Boite.self, from: JSONIRIS.encodeur.encode(Boite(h: h))).h
        XCTAssertEqual(relu.date?.timeIntervalSince1970, 1_757_800_000.5)
    }

    func testValeurJSONNeConfondPasBooleenEtNombre() throws {
        let objet = try JSONDecoder().decode([String: ValeurJSON].self,
                                             from: Data(#"{"a": true, "b": 1, "c": "x", "d": [null], "e": {"f": 2.5}}"#.utf8))
        XCTAssertEqual(objet["a"], .booleen(true))
        XCTAssertEqual(objet["b"], .nombre(1))
        XCTAssertEqual(objet["c"]?.texte, "x")
        XCTAssertEqual(objet["d"], .tableau([.nul]))
        XCTAssertEqual(objet["e"]?["f"]?.nombre, 2.5)
    }

    func testEntierReencodeRestantEntier() throws {
        // settings.updated et pas_a_pas.etat passent par ValeurJSON avant d'être relus dans des champs Int.
        let donnees = try JSONEncoder().encode(ValeurJSON.objet(["tts_rate": .nombre(370), "debit": .nombre(1.5)]))
        XCTAssertEqual(String(data: donnees, encoding: .utf8)?.contains("370.0"), false)
        struct Lu: Decodable { let ttsRate: Int; let debit: Double }
        let lu = try JSONIRIS.decodeur.decode(Lu.self, from: donnees)
        XCTAssertEqual(lu.ttsRate, 370)
        XCTAssertEqual(lu.debit, 1.5)
    }

    func testPrixVuEstUnNombre() throws {
        // prix.py rend prix_vu en nombre : un champ texte faisait échouer toute la comparaison.
        let json = #"{"produit":{"nom":"Cafetière","marque":null,"format":null,"code_barres":"0123456789012","prix_vu":39.99},"offres":[{"marchand":"Boutique","prix":35.5,"devise":"CAD","url":"https://exemple.ca","extrait":"…"}],"resume":"r","avertissement":"a","local":false,"source":"image","ecartees":0,"recherches":2,"duree_ms":1200}"#
        let r = try JSONIRIS.decodeur.decode(ComparaisonPrix.self, from: Data(json.utf8))
        XCTAssertEqual(r.produit?.prixVu, 39.99)
        XCTAssertEqual(r.produit?.codeBarres, "0123456789012")
        XCTAssertEqual(r.offres?.first?.prix, 35.5)
    }

    func testRecuNonEnregistreEnMemoireSuspendue() throws {
        let json = #"{"id":null,"date":"2026-09-13","commercant":"Épicerie","sous_total":10.0,"tps":0.5,"tvq":1.0,"tvh":null,"total":11.5,"devise":"CAD","categorie":"Alimentation","moyen_paiement":null,"lignes":[{"libelle":"Pain","montant":3.5}],"confiance":0.8,"image_nom":null,"local":true,"enregistre":false,"corrige":false,"note":"Mémoire suspendue.","controle":{"somme_ok":true,"taux_ok":null},"duree_ms":900}"#
        let r = try JSONIRIS.decodeur.decode(Recu.self, from: Data(json.utf8))
        XCTAssertNil(r.id)
        XCTAssertEqual(r.enregistre, false)
        XCTAssertEqual(r.lignes?.first?.montant, 3.5)
    }

    func testTotauxParCategorieGardentLeursNoms() throws {
        let json = #"{"recus":[],"totaux":{"nombre":2,"devise":"CAD","sous_total":20,"tps":1,"tvq":2,"tvh":0,"total":23,"par_categorie":{"Fournitures de bureau":23},"autres_devises":{"USD":4},"sans_total":0},"limite":"l","retention_jours":0}"#
        let liste = try JSONIRIS.decodeur.decode(ListeRecus.self, from: Data(json.utf8))
        XCTAssertEqual(liste.totaux?.parCategorie?["Fournitures de bureau"], 23)
        XCTAssertEqual(liste.totaux?.autresDevises?["USD"], 4)
    }

    func testSessionPasAPasDansLEvenement() throws {
        let json = #"{"type":"pas_a_pas.etat","session":{"id":"s1","sujet":"crêpes","type":"recette","etapes":[{"n":1,"texte":"Mélanger.","minuteur_s":null},{"n":2,"texte":"Cuire 2 minutes.","minuteur_s":120}],"index":1,"actif":true,"minuteurs":[{"etape":2,"duree_s":120,"restant_s":90}],"ecoute_active":false,"limite":"l"},"annonce":"Étape 2 sur 2 : Cuire 2 minutes."}"#
        let champs = try JSONDecoder().decode([String: ValeurJSON].self, from: Data(json.utf8))
        let brute = try XCTUnwrap(champs["session"])
        let session = try JSONIRIS.decodeur.decode(SessionPasAPas.self, from: JSONEncoder().encode(brute))
        XCTAssertEqual(session.etapes?.last?.minuteurS, 120)
        XCTAssertEqual(session.minuteurs?.first?.restantS, 90)
        XCTAssertEqual(champs["annonce"]?.texte, "Étape 2 sur 2 : Cuire 2 minutes.")
    }

    func testSeanceHistoriqueSansChampActif() throws {
        let json = #"{"seances":[{"id":"x","exercice":"squats","series":3,"series_cibles":null,"repos_s":90,"debut":"2026-09-13T14:05:12+00:00","fin":"2026-09-13T14:25:12+00:00","duree_s":1200,"pauses_s":0}],"memoire_suspendue":null,"retention_jours":30}"#
        let liste = try JSONIRIS.decodeur.decode(ListeSeances.self, from: Data(json.utf8))
        XCTAssertEqual(liste.seances.first?.series, 3)
    }
}
