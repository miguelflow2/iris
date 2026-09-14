// EcranAlertes.swift — alertes sonores sur l'iPhone : activer, choisir les sons, sensibilité, dernières
// alertes, essai de la façon d'être prévenu.
//
// L'essai ne prétend pas tester la détection (on ne peut pas faire sonner une vraie alarme) : il montre
// seulement la vibration, la notification et la voix, et le dit.

import SwiftUI
import UIKit

struct EcranAlertes: View {
    @Environment(EnvironnementIRIS.self) private var env
    let perception: PerceptionIRIS
    @State private var erreur: Error?
    @State private var bascule = false
    @State private var alertePleinEcran: AlerteSonore?

    // Initialiseur explicite : les propriétés privées (@State, @Environment) rendraient l'initialiseur
    // implicite privé, donc inaccessible depuis les autres fichiers.
    init(perception: PerceptionIRIS) {
        self.perception = perception
    }

    private var alertes: AlertesSonoresTelephone { perception.alertesSonores }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if !env.lunettesPresentes && !alertes.actives {
                    LunettesRequisesVue(message: "Les alertes sonores marchent avec les lunettes VELA.")
                }

                Carte(titre: "Écoute") {
                    Label(alertes.actives ? "Alertes actives" : "Alertes arrêtées",
                          systemImage: alertes.actives ? "ear.fill" : "ear")
                        .font(.headline)
                        .foregroundStyle(alertes.actives ? Couleurs.vert : Couleurs.texte2)
                    Button {
                        Task { await basculer() }
                    } label: {
                        if bascule {
                            ProgressView().tint(Couleurs.fond)
                        } else {
                            Text(alertes.actives ? "Arrêter les alertes" : "Activer les alertes")
                        }
                    }
                    .buttonStyle(.holo(alertes.actives ? .rouge : .holo))
                    .disabled(bascule || (!alertes.actives && !env.lunettesPresentes))
                    .accessibilityHint(alertes.actives ? "Ferme le micro." : "Écoute les sons choisis ci-dessous.")

                    if alertes.actives && alertes.attenteMicro {
                        NoteVerite(texte: "En attente du micro : aucun son n'arrive.", genre: .avertissement)
                    }
                    if let interruption = perception.micro.interruption {
                        NoteVerite(texte: interruption, genre: .avertissement)
                    }
                    if let message = alertes.erreur {
                        NoteVerite(texte: message, genre: .erreur)
                    }
                    if let erreur {
                        BandeauErreur(erreur: erreur)
                    }
                    if alertes.notificationsPermises == false {
                        NoteVerite(texte: "Notifications refusées pour IRIS : app en arrière-plan, tu seras prévenu seulement par la voix. Réglages › IRIS › Notifications.", genre: .avertissement)
                    }

                    Button("Essayer l'avertissement") {
                        alertes.essayerAvertissement()
                    }
                    .buttonStyle(.holo(.sombre, compact: true))
                    .accessibilityHint("Vibration, notification et voix, pour savoir à quoi t'attendre. Ne teste pas la détection des sons.")
                }

                Carte(titre: "Sons surveillés") {
                    ForEach(AlertesSonoresTelephone.catalogue) { definition in
                        let indisponible = alertes.indisponibles.contains(definition.id)
                        Toggle(isOn: Binding(
                            get: { alertes.types.first(where: { $0.id == definition.id })?.actif ?? false },
                            set: { alertes.choisir(type: definition.id, actif: $0) })) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(definition.libelle).foregroundStyle(Couleurs.texte)
                                if indisponible {
                                    Text("Indisponible : le classifieur de sons de cet iPhone ne connaît pas ce son.")
                                        .font(.caption)
                                        .foregroundStyle(Couleurs.avertissement)
                                }
                            }
                        }
                        .tint(Couleurs.bleu)
                        .disabled(indisponible)
                    }
                    NoteVerite(texte: "« Ton prénom » est détecté seulement par ton ordinateur, pas par l'iPhone.")
                }

                Carte(titre: "Réglages") {
                    VStack(alignment: .leading, spacing: 6) {
                        HStack {
                            Text("Sensibilité").foregroundStyle(Couleurs.texte)
                            Spacer()
                            Text("\(Int(alertes.sensibilite))").monospacedDigit().foregroundStyle(Couleurs.texte2)
                        }
                        .accessibilityHidden(true)
                        Slider(value: Binding(get: { alertes.sensibilite }, set: { alertes.choisirSensibilite($0) }),
                               in: 0...100, step: 5)
                            .accessibilityLabel("Sensibilité")
                            .accessibilityValue("\(Int(alertes.sensibilite)) sur 100")
                        NoteVerite(texte: "Plus sensible : moins de sons manqués, mais plus de fausses alertes.")
                    }
                    Toggle("Annoncer à voix haute", isOn: Binding(get: { alertes.voixActive },
                                                                   set: { alertes.choisirVoix($0) }))
                        .tint(Couleurs.bleu)
                        .foregroundStyle(Couleurs.texte)
                }

                if !alertes.dernieres.isEmpty {
                    Carte(titre: "Dernières alertes de l'iPhone") {
                        ForEach(alertes.dernieres) { alerte in
                            ligneAlerte(alerte)
                        }
                        NoteVerite(texte: "Liste gardée en mémoire vive seulement : elle disparaît quand l'app se ferme.")
                    }
                }

                if !alertes.dernieresOrdinateur.isEmpty {
                    Carte(titre: "Détectées par ton ordinateur") {
                        ForEach(alertes.dernieresOrdinateur) { alerte in
                            ligneAlerte(alerte)
                        }
                    }
                }

                Carte(titre: "Limites") {
                    NoteVerite(texte: alertes.limite)
                }
            }
            .padding()
        }
        .fondIRIS()
        .navigationTitle("Alertes sonores")
        .navigationBarTitleDisplayMode(.inline)
        .fullScreenCover(item: $alertePleinEcran) { alerte in
            AlertePleinEcran(alerte: alerte) { alertePleinEcran = nil }
        }
        .onAppear {
            alertes.surAlerte = { alerte in
                alertePleinEcran = alerte
            }
        }
        .onDisappear {
            alertes.surAlerte = nil
        }
    }

    private func ligneAlerte(_ alerte: AlerteSonore) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(TexteAccessibilite.heure(alerte.ts))
                .font(.caption.monospacedDigit())
                .foregroundStyle(Couleurs.attenue)
            Text(alerte.libelle + (alerte.test == true ? " (essai)" : ""))
                .foregroundStyle(Couleurs.texte2)
            Spacer()
            if let confiance = alerte.confiance {
                Text(NombresFr.pourcent(confiance))
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(Couleurs.attenue)
            }
        }
        .accessibilityElement(children: .combine)
    }

    private func basculer() async {
        guard !bascule else { return }
        bascule = true
        defer { bascule = false }
        erreur = nil
        if alertes.actives {
            alertes.desactiver()
            Annonce.voiceOver("Alertes sonores arrêtées.")
            return
        }
        do {
            try await alertes.activer(types: [])
            Annonce.voiceOver("Alertes sonores actives.")
        } catch {
            erreur = error
            Annonce.voiceOver(error.localizedDescription)
        }
    }
}
