// SessionAudio.swift — la session audio d'iOS réglée pour passer par les lunettes.
//
// .playAndRecord avec .allowBluetooth (profil mains libres : le micro ET le haut-parleur des
// lunettes) et .allowBluetoothA2DP (sortie seule, meilleure qualité quand le micro n'est pas
// demandé). Quand un appareil offre les deux, iOS donne la priorité au profil mains libres.
// .defaultToSpeaker : sans lunettes ni écouteurs, la voix sort du haut-parleur de l'iPhone et non
// de l'écouteur d'appel, qu'on n'entendrait pas.

import AVFoundation

enum SessionAudio {
    static func activer() throws {
        let session = AVAudioSession.sharedInstance()
        let options: AVAudioSession.CategoryOptions = [.allowBluetooth, .allowBluetoothA2DP, .defaultToSpeaker]
        if session.category != .playAndRecord || session.categoryOptions != options {
            try session.setCategory(.playAndRecord, mode: .default, options: options)
        }
        // Sans ceci, iOS coupe les vibrations pendant que le micro enregistre : le signal « je t'ai
        // entendue » ne se sentirait pas.
        try? session.setAllowHapticsAndSystemSoundsDuringRecording(true)
        try session.setActive(true, options: [])
    }

    static func desactiver() {
        try? AVAudioSession.sharedInstance().setActive(false, options: [.notifyOthersOnDeactivation])
    }

    /// Où la voix d'IRIS sort réellement, pour l'afficher (« VELA K900 (Bluetooth) »).
    static var sortieActuelle: String {
        let sorties = AVAudioSession.sharedInstance().currentRoute.outputs
        guard let sortie = sorties.first else { return "aucune sortie audio" }
        switch sortie.portType {
        case .bluetoothHFP, .bluetoothA2DP, .bluetoothLE:
            return "\(sortie.portName) (Bluetooth)"
        case .builtInSpeaker:
            return "haut-parleur de l'iPhone"
        case .builtInReceiver:
            return "écouteur de l'iPhone"
        case .headphones:
            return "écouteurs filaires"
        default:
            return sortie.portName
        }
    }

    /// Vrai si le micro utilisé est un micro Bluetooth (celui des lunettes, par exemple).
    static var microBluetooth: Bool {
        AVAudioSession.sharedInstance().currentRoute.inputs.contains { $0.portType == .bluetoothHFP }
    }
}
