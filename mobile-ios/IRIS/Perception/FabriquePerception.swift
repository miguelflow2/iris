// FabriquePerception.swift — le point d'entrée du module de perception, trouvé À L'EXÉCUTION par l'app.
//
// L'app (EnvironnementIRIS) cherche NSClassFromString("IRISFabriquePerception") : si ce module est retiré
// de la cible, l'app compile et démarre quand même, et l'onglet Accessibilité dit qu'il manque. D'où le nom
// Objective-C imposé et l'absence de toute référence directe depuis le reste de l'app.
//
// Attention à l'ordre de construction : `creer` est appelé PENDANT la construction de l'environnement de
// l'app. Rien ici ne doit lire EnvironnementIRIS.partage (la garde de capture le lit plus tard, à l'usage).

import Foundation
import SwiftUI
import UIKit

@objc(IRISFabriquePerception)
final class FabriquePerceptionIRIS: NSObject, FabriquePerception {
    @MainActor
    static func creer(pont: any ServicePontPC, voix: any ServiceVoix) -> any ServicesPerception {
        PerceptionIRIS(pont: pont, voix: voix)
    }
}

@MainActor
final class PerceptionIRIS: ServicesPerception {
    let pont: any ServicePontPC
    let voix: any ServiceVoix
    let lunettesBLE: LunettesBLE
    let camera: CameraTelephone
    let micro: MicroPerception
    let garde: GardeCapture
    let visionAccessibilite: VisionAccessibilite
    let alertesSonores: AlertesSonoresTelephone
    let guidageAPied: GuidageAPied
    let sousTitres: SousTitresTelephone
    let partageVue: PartageVueTelephone

    init(pont: any ServicePontPC, voix: any ServiceVoix) {
        self.pont = pont
        self.voix = voix
        let lunettes = LunettesBLE()
        let camera = CameraTelephone()
        let micro = MicroPerception(voix: voix)
        let garde = GardeCapture(lunettes: lunettes)
        lunettesBLE = lunettes
        self.camera = camera
        self.micro = micro
        self.garde = garde
        visionAccessibilite = VisionAccessibilite(pont: pont, voix: voix, lunettes: lunettes, camera: camera, garde: garde)
        alertesSonores = AlertesSonoresTelephone(micro: micro, voix: voix, garde: garde, pont: pont)
        guidageAPied = GuidageAPied(voix: voix, garde: garde)
        sousTitres = SousTitresTelephone(micro: micro, voix: voix, garde: garde)
        partageVue = PartageVueTelephone(pont: pont, voix: voix, camera: camera, garde: garde)

        // Mode confidentiel activé sur l'ordinateur, ou IRIS verrouillée : ce qui capte s'arrête sur
        // l'iPhone aussi. L'environnement de l'app appelle aussi suspendreCaptures quand il RELIT les réglages
        // (un événement manqué app en arrière-plan ne laisse donc rien tourner).
        abonnement = pont.abonner { [weak self] evenement in
            guard let self else { return }
            let confidentiel = evenement.type == "settings.updated"
                && evenement.champs["settings"]?["privacy_mode"]?.booleen == true
            let verrouillee = evenement.type == "verrou.etat" && evenement.champs["verrouille"]?.booleen == true
            guard confidentiel || verrouillee else { return }
            self.suspendreCaptures(raison: verrouillee ? GardeCapture.messageVerrou : GardeCapture.messageConfidentiel)
        }
    }

    private var abonnement: AbonnementEvenements?

    // MARK: - Contrat ServicesPerception

    var lunettes: any ServiceLunettes { lunettesBLE }
    var vision: any ServiceVision { visionAccessibilite }
    var alertes: any ServiceAlertes { alertesSonores }
    var guidage: any ServiceGuidage { guidageAPied }

    func ecranAccessibilite() -> AnyView {
        AnyView(EcranAccessibilite(perception: self))
    }

    func ecranLunettes() -> AnyView {
        AnyView(EcranLunettes(lunettes: lunettesBLE))
    }

    func vueAlertePleinEcran(_ alerte: AlerteSonore, fermer: @escaping () -> Void) -> AnyView {
        AnyView(AlertePleinEcran(alerte: alerte, fermer: fermer))
    }

    /// Idempotent : appelé par l'événement ET par la relecture des réglages. Le guidage à pied n'est pas
    /// coupé net : une personne peut être au milieu d'une rue (il s'arrête depuis son écran).
    func suspendreCaptures(raison: String) {
        sousTitres.arreter()
        if alertesSonores.actives {
            alertesSonores.desactiver(raison: raison)
        }
        if partageVue.phase != .repos {
            Task { await self.partageVue.arreter() }
        }
        camera.arreter(pour: "apercu")
    }

    var microOccupePar: String? {
        micro.occupePar
    }

    func prendrePhotoTelephone() async throws -> ImageCapturee {
        if let refus = garde.refus(fonction: "photo_telephone") { throw refus }
        guard UIApplication.shared.applicationState != .background else { throw ErreurCamera.arrierePlan }
        return try await camera.prendrePhoto()
    }
}
