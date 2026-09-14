// Trousseau.swift — la session du PC rangée dans le Trousseau d'iOS (Keychain).
//
// Pourquoi le Trousseau et pas UserDefaults : la session ouverte avec le mot de passe donne les
// droits du propriétaire sur l'ordinateur pendant 30 jours. UserDefaults est un fichier en clair
// dans la sauvegarde de l'app ; le Trousseau est chiffré par le système et, avec
// kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly, ne quitte jamais cet iPhone (ni sauvegarde
// iCloud, ni transfert vers un nouvel appareil).

import Foundation
import Security

enum Trousseau {
    private static let service = "ca.velaglass.iris.session"

    /// Enregistre (ou remplace) une valeur. Rend false si le système refuse.
    @discardableResult
    static func ecrire(_ valeur: String, compte: String) -> Bool {
        guard let donnees = valeur.data(using: .utf8) else { return false }
        let requete: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: compte,
        ]
        // Accessible après le premier déverrouillage : les zones sans mémoire réveillent l'app en
        // arrière-plan, écran verrouillé, et doivent pouvoir joindre l'ordinateur.
        let attributs: [String: Any] = [
            kSecValueData as String: donnees,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]
        let statut = SecItemUpdate(requete as CFDictionary, attributs as CFDictionary)
        if statut == errSecSuccess { return true }
        if statut == errSecItemNotFound {
            var ajout = requete
            ajout.merge(attributs) { _, nouveau in nouveau }
            return SecItemAdd(ajout as CFDictionary, nil) == errSecSuccess
        }
        return false
    }

    static func lire(compte: String) -> String? {
        let requete: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: compte,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var resultat: CFTypeRef?
        let statut = SecItemCopyMatching(requete as CFDictionary, &resultat)
        guard statut == errSecSuccess, let donnees = resultat as? Data else { return nil }
        return String(data: donnees, encoding: .utf8)
    }

    @discardableResult
    static func effacer(compte: String) -> Bool {
        let requete: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: compte,
        ]
        let statut = SecItemDelete(requete as CFDictionary)
        return statut == errSecSuccess || statut == errSecItemNotFound
    }
}
