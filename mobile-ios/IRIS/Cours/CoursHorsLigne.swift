// CoursHorsLigne.swift — les cours que l'utilisateur a choisi de garder sur cet iPhone.
//
// Rien n'est copié sans un geste (« Garder sur cet iPhone »). La copie est protégée par iOS
// (NSFileProtectionComplete : chiffrée tant que l'iPhone est verrouillé), exclue des sauvegardes,
// et effacée au-delà de la durée de conservation réglée sur l'ordinateur (retention_days, 0 = sans
// limite). Elle sert au mode hors ligne : relire ses fiches quand l'ordinateur ne répond pas.

import Foundation
import Observation

@MainActor
@Observable
final class CoursHorsLigne {
    struct Garde: Identifiable, Hashable {
        let id: String
        let titre: String
        let matiere: String?
        let gardeLe: Date
    }

    private(set) var gardes: [Garde] = []
    private(set) var erreur: String?

    @ObservationIgnored private let dossier: URL

    init() {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? FileManager.default.temporaryDirectory
        dossier = base.appendingPathComponent("CoursHorsLigne", isDirectory: true)
        recharger()
    }

    func estGarde(_ id: String) -> Bool {
        gardes.contains { $0.id == id }
    }

    func garder(_ cours: CoursDetail) {
        do {
            try FileManager.default.createDirectory(at: dossier, withIntermediateDirectories: true)
            var valeurs = URLResourceValues()
            valeurs.isExcludedFromBackup = true
            var dossierModifiable = dossier
            try? dossierModifiable.setResourceValues(valeurs)
            let donnees = try JSONIRIS.encodeur.encode(cours)
            try donnees.write(to: fichier(cours.id), options: [.atomic, .completeFileProtection])
            erreur = nil
        } catch {
            erreur = "Copie non gardée : \(error.localizedDescription)"
        }
        recharger()
    }

    func lire(_ id: String) -> CoursDetail? {
        guard let donnees = try? Data(contentsOf: fichier(id)) else { return nil }
        return try? JSONIRIS.decodeur.decode(CoursDetail.self, from: donnees)
    }

    func retirer(_ id: String) {
        try? FileManager.default.removeItem(at: fichier(id))
        recharger()
    }

    /// Efface les copies plus vieilles que la durée de conservation (0 ou nil : aucune limite).
    func purger(retentionJours: Int?) {
        guard let jours = retentionJours, jours > 0 else { return }
        let limite = Date().addingTimeInterval(-Double(jours) * 86_400)
        for garde in gardes where garde.gardeLe < limite {
            try? FileManager.default.removeItem(at: fichier(garde.id))
        }
        recharger()
    }

    private func fichier(_ id: String) -> URL {
        // L'identifiant vient du service (hexadécimal) ; on refuse tout caractère de chemin par prudence.
        let sur = id.filter { $0.isLetter || $0.isNumber || $0 == "-" || $0 == "_" }
        return dossier.appendingPathComponent("\(sur).json")
    }

    private func recharger() {
        guard let fichiers = try? FileManager.default.contentsOfDirectory(
            at: dossier, includingPropertiesForKeys: [.contentModificationDateKey], options: [.skipsHiddenFiles]) else {
            gardes = []
            return
        }
        var liste: [Garde] = []
        for url in fichiers where url.pathExtension == "json" {
            guard let donnees = try? Data(contentsOf: url),
                  let cours = try? JSONIRIS.decodeur.decode(CoursDetail.self, from: donnees) else { continue }
            let date = (try? url.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? Date()
            liste.append(Garde(id: cours.id, titre: cours.titre, matiere: cours.matiere, gardeLe: date))
        }
        gardes = liste.sorted { $0.gardeLe > $1.gardeLe }
    }
}
