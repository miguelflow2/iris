// MicroPerception.swift — un seul robinet de micro pour les sous-titres et les alertes sonores.
//
// Pourquoi un robinet commun : deux moteurs audio qui posent chacun un robinet sur le micro se disputent
// l'entrée, et un changement de sortie (lunettes connectées ou retirées) casse le format d'un robinet
// posé à l'ancien. Ici, un seul moteur, et chaque abonné reçoit une copie des blocs de son, précédée du
// format à utiliser (rappelé à chaque changement).
//
// Limites réelles, dites dans les écrans :
// - pendant que ce micro tourne, l'écoute de « Dis-moi Iris » est mise en pause (puis reprise), pour ne
//   pas ouvrir deux reconnaissances en même temps ;
// - un appel, Siri ou une autre app qui prend le micro met l'écoute en pause ; elle repart seule quand
//   iOS rend le micro ;
// - en arrière-plan, iOS laisse tourner le micro seulement parce que l'app déclare l'audio en arrière-plan
//   (l'indicateur de micro reste visible) ; iOS peut malgré tout l'arrêter.
// Aucun son n'est enregistré : les blocs sont analysés puis oubliés.

import AVFoundation
import Foundation
import Observation

enum ErreurMicro: Error, LocalizedError {
    case refuse
    case occupe(String)
    case aucunMicro

    var errorDescription: String? {
        switch self {
        case .refuse:
            return "Micro refusé pour IRIS : Réglages › IRIS › Micro."
        case .occupe(let message):
            return message
        case .aucunMicro:
            return "Aucun micro disponible : permission refusée, ou micro pris par un appel ou une autre app."
        }
    }
}

/// Liste des abonnés au son, lue depuis le fil audio : protégée par un verrou, jamais par un acteur.
final class RegistreSon {
    typealias Bloc = (AVAudioPCMBuffer, AVAudioTime) -> Void

    private let verrou = NSLock()
    private var blocs: [String: Bloc] = [:]
    private var dernierBloc = Date.distantPast

    func poser(_ nom: String, _ bloc: @escaping Bloc) {
        verrou.lock()
        blocs[nom] = bloc
        dernierBloc = Date()   // l'attente du premier bloc commence maintenant
        verrou.unlock()
    }

    /// Retire un abonné ; vrai s'il n'en reste aucun.
    @discardableResult
    func retirer(_ nom: String) -> Bool {
        verrou.lock()
        defer { verrou.unlock() }
        blocs[nom] = nil
        return blocs.isEmpty
    }

    func distribuer(_ tampon: AVAudioPCMBuffer, _ quand: AVAudioTime) {
        verrou.lock()
        let copie = Array(blocs.values)
        dernierBloc = Date()
        verrou.unlock()
        for bloc in copie {
            bloc(tampon, quand)
        }
    }

    /// Secondes depuis le dernier bloc de son reçu (sert à dire « en attente du micro »).
    var secondesSansSon: TimeInterval {
        verrou.lock()
        defer { verrou.unlock() }
        return Date().timeIntervalSince(dernierBloc)
    }
}

@MainActor
@Observable
final class MicroPerception {
    private(set) var actif = false
    /// Phrase à afficher quand iOS a coupé le micro (nil sinon).
    private(set) var interruption: String?

    @ObservationIgnored let registre = RegistreSon()
    @ObservationIgnored private let moteur = AVAudioEngine()
    @ObservationIgnored private let voix: any ServiceVoix
    @ObservationIgnored private var rappelsFormat: [String: @MainActor (AVAudioFormat) -> Void] = [:]
    @ObservationIgnored private(set) var formatCourant: AVAudioFormat?
    @ObservationIgnored private var motActivationSuspendu = false
    @ObservationIgnored private var observateurs: [NSObjectProtocol] = []
    @ObservationIgnored private var relance: Task<Void, Never>?

    init(voix: any ServiceVoix) {
        self.voix = voix
    }

    var abonnes: Bool { !rappelsFormat.isEmpty }

    // MARK: - Abonnement

    /// `surFormat` est appelé (fil principal) avant le premier bloc et à chaque changement de format ;
    /// `bloc` est appelé sur le fil audio : il doit être court et ne jamais bloquer.
    func abonner(_ nom: String, surFormat: @escaping @MainActor (AVAudioFormat) -> Void,
                 bloc: @escaping RegistreSon.Bloc) throws {
        rappelsFormat[nom] = surFormat
        if actif, let formatCourant {
            surFormat(formatCourant)
            registre.poser(nom, bloc)
            return
        }
        registre.poser(nom, bloc)
        do {
            try demarrerMoteur()
        } catch {
            rappelsFormat[nom] = nil
            registre.retirer(nom)
            throw error
        }
    }

    func desabonner(_ nom: String) {
        rappelsFormat[nom] = nil
        let vide = registre.retirer(nom)
        if vide && actif {
            arreterMoteur()
        }
    }

    // MARK: - Moteur

    private func demarrerMoteur() throws {
        suspendreMotActivation()
        do {
            try SessionAudio.activer()
        } catch {
            reprendreMotActivation()
            throw ErreurMicro.occupe("Le micro est occupé par un appel ou une autre app.")
        }
        do {
            try installerEtLancer()
        } catch {
            reprendreMotActivation()
            throw error
        }
        actif = true
        interruption = nil
        brancherObservateurs()
    }

    private func installerEtLancer() throws {
        let entree = moteur.inputNode
        let format = entree.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else { throw ErreurMicro.aucunMicro }
        entree.removeTap(onBus: 0)
        entree.installTap(onBus: 0, bufferSize: 4096, format: format, block: Self.robinet(registre))
        formatCourant = format
        for rappel in Array(rappelsFormat.values) {
            rappel(format)
        }
        moteur.prepare()
        do {
            try moteur.start()
        } catch {
            entree.removeTap(onBus: 0)
            throw ErreurMicro.occupe("Le micro n'a pas pu démarrer (\(error.localizedDescription)).")
        }
    }

    /// Fabriqué hors du MainActor : le bloc tourne sur le fil audio.
    nonisolated private static func robinet(_ registre: RegistreSon) -> AVAudioNodeTapBlock {
        return { tampon, quand in
            registre.distribuer(tampon, quand)
        }
    }

    private func arreterMoteur() {
        relance?.cancel()
        relance = nil
        moteur.inputNode.removeTap(onBus: 0)
        if moteur.isRunning {
            moteur.stop()
        }
        actif = false
        interruption = nil
        formatCourant = nil
        retirerObservateurs()
        reprendreMotActivation()
    }

    /// Relance après un changement de route (lunettes connectées ou retirées) ou une interruption finie.
    private func relancer(apres delai: Duration) {
        relance?.cancel()
        relance = Task { [weak self] in
            try? await Task.sleep(for: delai)
            guard let self, !Task.isCancelled, self.abonnes else { return }
            do {
                if self.moteur.isRunning { self.moteur.stop() }
                try SessionAudio.activer()
                try self.installerEtLancer()
                self.actif = true
                self.interruption = nil
            } catch {
                self.interruption = "Micro indisponible pour l'instant (\(error.localizedDescription)). Nouvel essai dans 5 secondes."
                self.relancer(apres: .seconds(5))
            }
        }
    }

    // MARK: - « Dis-moi Iris » en pause

    private func suspendreMotActivation() {
        let voulu: Bool
        if let moteurVoix = voix as? MoteurVoix {
            voulu = moteurVoix.motActivationVoulu
        } else {
            voulu = voix.etat == .veille || voix.etat == .commande
        }
        if voulu {
            voix.arreterMotActivation()
            motActivationSuspendu = true
        }
    }

    private func reprendreMotActivation() {
        guard motActivationSuspendu else { return }
        motActivationSuspendu = false
        voix.demarrerMotActivation()
    }

    // MARK: - Notifications d'iOS

    private func brancherObservateurs() {
        guard observateurs.isEmpty else { return }
        let centre = NotificationCenter.default
        observateurs.append(centre.addObserver(forName: .AVAudioEngineConfigurationChange, object: moteur, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.relancer(apres: .milliseconds(400)) }
        })
        observateurs.append(centre.addObserver(forName: AVAudioSession.interruptionNotification, object: nil, queue: .main) { [weak self] note in
            let brut = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt
            let debut = brut == AVAudioSession.InterruptionType.began.rawValue
            MainActor.assumeIsolated {
                guard let self else { return }
                if debut {
                    self.interruption = "Micro interrompu par iOS (appel, Siri ou autre app) : écoute en pause."
                } else {
                    self.relancer(apres: .milliseconds(500))
                }
            }
        })
        observateurs.append(centre.addObserver(forName: AVAudioSession.mediaServicesWereResetNotification, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.relancer(apres: .seconds(1)) }
        })
    }

    private func retirerObservateurs() {
        for observateur in observateurs {
            NotificationCenter.default.removeObserver(observateur)
        }
        observateurs.removeAll()
    }
}
