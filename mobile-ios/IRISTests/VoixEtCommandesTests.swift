// VoixEtCommandesTests.swift — ce qui décide qu'une phrase part à l'ordinateur, et laquelle.

import XCTest
@testable import IRIS

final class MotActivationTests: XCTestCase {
    func testVarianteDicteeIsoleLaCommande() {
        let commande = MotActivation.commande(apres: ["dit", "moi", "Irisse", "ouvre", "mes", "courriels"],
                                              motActivation: "Dis-moi Iris")
        XCTAssertEqual(commande, "ouvre mes courriels")
    }

    func testMotSeulRendUneCommandeVide() {
        XCTAssertEqual(MotActivation.commande(apres: ["Dis-moi", "Iris"], motActivation: "Dis-moi Iris"), "")
    }

    func testSansMotDActivationRienNePart() {
        XCTAssertNil(MotActivation.commande(apres: ["Quelle", "heure", "est-il"], motActivation: "Dis-moi Iris"))
        XCTAssertNil(MotActivation.commande(apres: [], motActivation: "Dis-moi Iris"))
    }

    func testMotDActivationRegleSurLOrdinateur() {
        XCTAssertEqual(MotActivation.commande(apres: ["Salut", "Véla", "allume", "la", "lampe"], motActivation: "Salut Vela"),
                       "allume la lampe")
    }

    func testNormalisationCommeLeService() {
        XCTAssertEqual(MotActivation.normaliser("  Mode   INVITÉ, s'il te plaît ! "), "mode invite s il te plait")
    }
}

final class CommandesLocalesTests: XCTestCase {
    func testActiverLeModeInvite() {
        XCTAssertEqual(CommandesLocales.reconnaitre("Mode invité"), .activerModeInvite)
        XCTAssertEqual(CommandesLocales.reconnaitre("active le mode invité s'il te plaît"), .activerModeInvite)
        XCTAssertEqual(CommandesLocales.reconnaitre("Passe en mode invité."), .activerModeInvite)
    }

    func testSortirDuModeInvite() {
        XCTAssertEqual(CommandesLocales.reconnaitre("Fin du mode invité"), .quitterModeInvite)
        XCTAssertEqual(CommandesLocales.reconnaitre("quitter le mode invité"), .quitterModeInvite)
        XCTAssertEqual(CommandesLocales.reconnaitre("désactive le mode invité"), .quitterModeInvite)
    }

    func testLesAutresPhrasesVontAuChat() {
        XCTAssertNil(CommandesLocales.reconnaitre("c'est quoi le mode invité ?"))
        XCTAssertNil(CommandesLocales.reconnaitre("invite Marc à souper"))
        XCTAssertNil(CommandesLocales.reconnaitre("ouvre mes courriels"))
        XCTAssertNil(CommandesLocales.reconnaitre(""))
    }

    func testLaSortieVocaleEstRefusee() {
        XCTAssertEqual(CommandesLocales.phraseSortieRefusee(actif: false, jusqua: nil), "Le mode invité n'est pas actif.")
        let refus = CommandesLocales.phraseSortieRefusee(actif: true, jusqua: nil)
        XCTAssertTrue(refus.hasPrefix("Je ne peux pas savoir qui me parle"))
    }

    func testHeureDite() throws {
        var calendrier = Calendar(identifier: .gregorian)
        calendrier.timeZone = try XCTUnwrap(TimeZone(identifier: "UTC"))
        let date = Date(timeIntervalSince1970: 1_789_315_500) // 2026-09-13 16:05:00 UTC
        XCTAssertEqual(CommandesLocales.heure(date, calendrier: calendrier), "16 h 05")
    }
}

@MainActor
final class AttenteReponseTests: XCTestCase {
    private func evenement(_ json: String) throws -> EvenementPC {
        let donnees = Data(json.utf8)
        let champs = try JSONDecoder().decode([String: ValeurJSON].self, from: donnees)
        return EvenementPC(type: champs["type"]?.texte ?? "", ts: nil, champs: champs, brut: donnees)
    }

    func testConsentementRequisConclutAussitot() async throws {
        let attente = AttenteReponse(convId: "c1", connus: [])
        let evt = try evenement(#"{"type":"chat.consent_required","conversation_id":"c1","data_type":"transcript","label":"Texte de vos demandes","description":""}"#)
        attente.recevoir(evt, debut: Date()) { _ in }
        XCTAssertTrue(attente.termine)
        switch await attente.attendre() {
        case .erreur(let message):
            XCTAssertTrue(message.contains("« Texte de vos demandes »"))
            XCTAssertTrue(message.contains("Confidentialité"))
        default:
            XCTFail("chat.consent_required doit conclure par une erreur exacte")
        }
    }

    /// Liaison d'événements coupée : chat.consent_required est perdu. Le sondage lit `issue_non_gardee`
    /// (réponse exacte de GET /api/conversations/{id}, rejouée par outils/verifier_ios.py).
    func testConsentementLuParSondageQuandLEvenementEstPerdu() throws {
        let json = #"{"id":"c1","title":"salut","messages":[{"id":"u1","conversation_id":"c1","role":"user","text":"salut","created_at":"2026-09-14T10:00:00+00:00","meta":{"source":"text"}}],"issue_non_gardee":{"apres":"u1","message":"consentement requis : Texte de vos demandes","consentement":{"data_type":"transcript","label":"Texte de vos demandes"},"ts":1789401600.0}}"#
        let conv = try JSONIRIS.decodeur.decode(Conversation.self, from: Data(json.utf8))
        let phrase = try XCTUnwrap(AttenteReponse.phraseIssueNonGardee(conv.issueNonGardee, connus: []))
        XCTAssertTrue(phrase.contains("« Texte de vos demandes »"))
        XCTAssertTrue(phrase.contains("Confidentialité"))
        // Issue d'une demande PRÉCÉDENTE (son message était connu avant l'envoi) : ignorée.
        XCTAssertNil(AttenteReponse.phraseIssueNonGardee(conv.issueNonGardee, connus: ["u1"]))
        // Ordinateur plus ancien : pas de champ, pas de conclusion inventée.
        let ancien = try JSONIRIS.decodeur.decode(Conversation.self, from: Data(#"{"id":"c1","title":null,"messages":[]}"#.utf8))
        XCTAssertNil(AttenteReponse.phraseIssueNonGardee(ancien.issueNonGardee, connus: []))
        // Erreur publiée seulement (sans consentement) : sa phrase exacte.
        let erreur = IssueNonGardee(apres: "u2", message: "Mode 100 % local activé.", consentement: nil)
        XCTAssertEqual(AttenteReponse.phraseIssueNonGardee(erreur, connus: ["u1"]), "Mode 100 % local activé.")
    }

    func testAutreConversationIgnoree() throws {
        let attente = AttenteReponse(convId: "c1", connus: [])
        attente.recevoir(try evenement(#"{"type":"chat.error","conversation_id":"c2","message":"x"}"#), debut: Date()) { _ in }
        XCTAssertFalse(attente.termine)
    }

    func testReponseDejaConnueIgnoree() throws {
        let attente = AttenteReponse(convId: "c1", connus: ["m1"])
        let ancien = #"{"type":"chat.done","conversation_id":"c1","message":{"id":"m1","role":"assistant","text":"vieux"}}"#
        attente.recevoir(try evenement(ancien), debut: Date()) { _ in }
        XCTAssertFalse(attente.termine)
        let neuf = #"{"type":"chat.done","conversation_id":"c1","message":{"id":"m2","role":"assistant","text":"neuf"}}"#
        attente.recevoir(try evenement(neuf), debut: Date()) { _ in }
        XCTAssertTrue(attente.termine)
    }
}

/// Commande DITE dans les lunettes : POST /api/voix/commande (constats iOS 1 et 3 du 2026-09-14). Les réponses
/// JSON ci-dessous sont les formes exactes de main.py (voix_commande), rejouées par outils/verifier_ios.py.
final class CommandeVocaleTests: XCTestCase {
    private func reponse(_ json: String) throws -> ReponseCommandeVocale {
        try JSONIRIS.decodeur.decode(ReponseCommandeVocale.self, from: Data(json.utf8))
    }

    func testInterceptionLueTelleQuelle() throws {
        let r = try reponse(#"{"texte":"Étape 2 sur 3 : cuire 2 minutes.","intercepte":true,"duree_ms":42}"#)
        XCTAssertEqual(ConversationIRIS.phraseCommandeVocale(r), "Étape 2 sur 3 : cuire 2 minutes.")
        XCTAssertFalse(ConversationIRIS.estUnRefus(r))
        XCTAssertEqual(r.dureeMs, 42)
    }

    func testConsentementRequisSynchrone() throws {
        let r = try reponse(#"{"texte":"Je ne peux pas envoyer cette demande : le consentement n'est pas accordé. Ouvre Confidentialité dans IRIS.","intercepte":false,"duree_ms":5,"conversation_id":"c1","message_id":null,"consentement_requis":"transcript"}"#)
        XCTAssertEqual(r.consentementRequis, "transcript")
        XCTAssertTrue(ConversationIRIS.estUnRefus(r))
        XCTAssertTrue(ConversationIRIS.phraseCommandeVocale(r).hasPrefix("Je ne peux pas envoyer cette demande"))
        // Phrase absente : l'app en dit une, exacte, plutôt que le silence.
        let sansTexte = try reponse(#"{"texte":"","intercepte":false,"consentement_requis":"transcript"}"#)
        XCTAssertTrue(ConversationIRIS.phraseCommandeVocale(sansTexte).contains("Confidentialité"))
    }

    func testRefusDuMicroDeLaMaison() throws {
        let r = try reponse(#"{"texte":"Dehors, je n'ouvre pas le micro de l'ordinateur resté à la maison : utilise l'interprète de l'application du téléphone.","intercepte":true,"duree_ms":1,"refus":"micro_de_la_maison"}"#)
        XCTAssertTrue(ConversationIRIS.estUnRefus(r))
    }

    func testRepliSeulementSurUnOrdinateurSansLaRoute() {
        let absente = ClientPontPC.classerRefus(statut: 404, data: Data(#"{"detail":"Not Found"}"#.utf8), chemin: "/api/voix/commande").0
        XCTAssertTrue(ConversationIRIS.routeVocaleAbsente(absente))
        XCTAssertFalse(ConversationIRIS.conversationIntrouvable(absente))
        let conversation = ClientPontPC.classerRefus(statut: 404, data: Data(#"{"detail":"conversation introuvable"}"#.utf8), chemin: "/api/voix/commande").0
        XCTAssertFalse(ConversationIRIS.routeVocaleAbsente(conversation))
        XCTAssertTrue(ConversationIRIS.conversationIntrouvable(conversation))
        // 428 lunettes : pas de repli (le repli contournerait la règle de la voix).
        let lunettes = ClientPontPC.classerRefus(statut: 428, data: Data(#"{"detail":{"code":"lunettes_requises","fonction":"voix","message":"Connecte tes lunettes."}}"#.utf8), chemin: "/api/voix/commande").0
        XCTAssertFalse(ConversationIRIS.routeVocaleAbsente(lunettes))
    }
}

/// Une pause de la veille (alertes, sous-titres, mode confidentiel) ferme le micro de la voix TOUT DE SUITE,
/// écoute dirigée comprise : sinon deux AVAudioEngine tiennent l'entrée (constat iOS du 2026-09-14).
final class PauseDuMicroTests: XCTestCase {
    func testLaPauseFermeAussiUneEcouteDirigee() {
        XCTAssertTrue(MoteurVoix.fermerMicroAuSuspens(ecouteDirigee: true, etat: .commande))
        XCTAssertTrue(MoteurVoix.fermerMicroAuSuspens(ecouteDirigee: true, etat: .inactive))
        XCTAssertTrue(MoteurVoix.fermerMicroAuSuspens(ecouteDirigee: false, etat: .veille))
        XCTAssertTrue(MoteurVoix.fermerMicroAuSuspens(ecouteDirigee: false, etat: .commande))
        XCTAssertFalse(MoteurVoix.fermerMicroAuSuspens(ecouteDirigee: false, etat: .parle))
        XCTAssertFalse(MoteurVoix.fermerMicroAuSuspens(ecouteDirigee: false, etat: .inactive))
    }

    func testLeMicroDePerceptionRefuseTantQueLaVoixLeTient() {
        XCTAssertTrue(MoteurVoix.voixTientLeMicro(.veille))
        XCTAssertTrue(MoteurVoix.voixTientLeMicro(.commande))
        XCTAssertFalse(MoteurVoix.voixTientLeMicro(.inactive))
        XCTAssertFalse(MoteurVoix.voixTientLeMicro(.reflexion))
        XCTAssertFalse(MoteurVoix.voixTientLeMicro(.indisponible(raison: "pause")))
    }
}
