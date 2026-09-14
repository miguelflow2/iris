// CameraTelephone.swift — la caméra arrière de l'iPhone, EN SECOURS de la caméra des lunettes.
//
// Deux usages, une seule session de capture (iOS n'en permet qu'une active à la fois par caméra) :
// - une photo à la demande pour la vision d'accessibilité (sans aperçu obligatoire : une personne
//   non voyante pointe l'iPhone et touche le bouton ; l'exposition a une demi-seconde pour se régler) ;
// - des images successives pour la vision partagée (la dernière image reçue est gardée en mémoire vive,
//   convertie en JPEG seulement au moment d'être envoyée).
//
// Limites réelles : iOS coupe la caméra dès que l'app passe en arrière-plan, pendant un appel ou quand
// une autre app la prend (voir `interrompue`). Rien n'est enregistré sur l'iPhone : la photo reste en
// mémoire le temps d'être analysée ou envoyée.

import AVFoundation
import CoreImage
import Foundation
import ImageIO
import UIKit

enum ErreurCamera: Error, LocalizedError {
    case refusee
    case indisponible
    case configuration(String)
    case photo(String)
    case arrierePlan

    var errorDescription: String? {
        switch self {
        case .refusee:
            return "Caméra refusée pour IRIS : Réglages › IRIS › Appareil photo."
        case .indisponible:
            return "Aucune caméra arrière utilisable sur cet appareil."
        case .configuration(let message):
            return "La caméra n'a pas pu démarrer : \(message)"
        case .photo(let message):
            return "La photo a échoué : \(message)"
        case .arrierePlan:
            return "iOS ne permet pas d'utiliser la caméra quand l'app IRIS n'est pas à l'écran."
        }
    }
}

final class CameraTelephone: NSObject, AVCapturePhotoCaptureDelegate, AVCaptureVideoDataOutputSampleBufferDelegate {
    let session = AVCaptureSession()

    private let fileSession = DispatchQueue(label: "ca.velaglass.iris.camera.session")
    private let fileImages = DispatchQueue(label: "ca.velaglass.iris.camera.images")
    private let sortiePhoto = AVCapturePhotoOutput()
    private let sortieVideo = AVCaptureVideoDataOutput()
    private let contexteCI = CIContext(options: [.cacheIntermediates: false])
    private let verrou = NSLock()

    // Protégés par `verrou`.
    private var configuree = false
    private var utilisateurs: Set<String> = []
    private var dernierTampon: CVPixelBuffer?
    private var dateDernierTampon: Date?
    private var demarreeLe: Date?
    private var attentesPhoto: [Int64: CheckedContinuation<Data, Error>] = [:]
    private var interrompueFlag = false

    /// Appelé (fil quelconque) quand iOS coupe ou rend la caméra : vrai = coupée.
    var surInterruption: ((Bool) -> Void)?

    override init() {
        super.init()
        let centre = NotificationCenter.default
        centre.addObserver(self, selector: #selector(sessionInterrompue(_:)),
                           name: AVCaptureSession.wasInterruptedNotification, object: session)
        centre.addObserver(self, selector: #selector(sessionReprise(_:)),
                           name: AVCaptureSession.interruptionEndedNotification, object: session)
    }

    deinit {
        NotificationCenter.default.removeObserver(self)
    }

    var interrompue: Bool {
        verrou.lock(); defer { verrou.unlock() }
        return interrompueFlag
    }

    // MARK: - Autorisation

    static func autoriser() async -> Bool {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            return true
        case .notDetermined:
            return await AVCaptureDevice.requestAccess(for: .video)
        default:
            return false
        }
    }

    // MARK: - Démarrage et arrêt (par raison : « photo », « partage », « apercu »)

    func demarrer(pour raison: String) async throws {
        guard await Self.autoriser() else { throw ErreurCamera.refusee }
        try await withCheckedThrowingContinuation { (suite: CheckedContinuation<Void, Error>) in
            fileSession.async { [self] in
                do {
                    try configurerSiBesoin()
                    verrou.lock()
                    utilisateurs.insert(raison)
                    verrou.unlock()
                    if !session.isRunning {
                        session.startRunning()
                        verrou.lock()
                        demarreeLe = Date()
                        verrou.unlock()
                    }
                    suite.resume()
                } catch {
                    suite.resume(throwing: error)
                }
            }
        }
    }

    func arreter(pour raison: String) {
        fileSession.async { [self] in
            verrou.lock()
            utilisateurs.remove(raison)
            let vide = utilisateurs.isEmpty
            if vide {
                dernierTampon = nil
                dateDernierTampon = nil
                demarreeLe = nil
            }
            verrou.unlock()
            if vide && session.isRunning {
                session.stopRunning()
            }
        }
    }

    private func configurerSiBesoin() throws {
        verrou.lock()
        let deja = configuree
        verrou.unlock()
        if deja { return }
        guard let appareil = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back) else {
            throw ErreurCamera.indisponible
        }
        let entree: AVCaptureDeviceInput
        do {
            entree = try AVCaptureDeviceInput(device: appareil)
        } catch {
            throw ErreurCamera.configuration(error.localizedDescription)
        }
        session.beginConfiguration()
        session.sessionPreset = .photo
        guard session.canAddInput(entree), session.canAddOutput(sortiePhoto), session.canAddOutput(sortieVideo) else {
            session.commitConfiguration()
            throw ErreurCamera.configuration("session de capture refusée par iOS")
        }
        session.addInput(entree)
        session.addOutput(sortiePhoto)
        sortieVideo.alwaysDiscardsLateVideoFrames = true
        sortieVideo.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
        sortieVideo.setSampleBufferDelegate(self, queue: fileImages)
        session.addOutput(sortieVideo)
        // L'app est en portrait : images et photos tournées de 90° pour arriver à l'endroit.
        for connexion in [sortiePhoto.connection(with: .video), sortieVideo.connection(with: .video)] {
            if let connexion, connexion.isVideoRotationAngleSupported(90) {
                connexion.videoRotationAngle = 90
            }
        }
        session.commitConfiguration()
        if (try? appareil.lockForConfiguration()) != nil {
            if appareil.isFocusModeSupported(.continuousAutoFocus) { appareil.focusMode = .continuousAutoFocus }
            if appareil.isExposureModeSupported(.continuousAutoExposure) { appareil.exposureMode = .continuousAutoExposure }
            appareil.unlockForConfiguration()
        }
        verrou.lock()
        configuree = true
        verrou.unlock()
    }

    // MARK: - Photo

    /// Photo à la demande, réduite à 1600 px, en JPEG. La caméra est ouverte puis refermée si personne
    /// d'autre ne s'en sert.
    func prendrePhoto() async throws -> ImageCapturee {
        try await demarrer(pour: "photo")
        defer { arreter(pour: "photo") }
        // Laisser l'exposition et la mise au point se régler après l'ouverture (sinon photo sombre ou floue).
        let depuis = secondesDepuisDemarrage()
        if depuis < 0.8 {
            try await Task.sleep(for: .milliseconds(Int((0.8 - depuis) * 1000)))
        }
        let brut = try await withCheckedThrowingContinuation { (suite: CheckedContinuation<Data, Error>) in
            fileSession.async { [self] in
                let reglages: AVCapturePhotoSettings
                if sortiePhoto.availablePhotoCodecTypes.contains(.jpeg) {
                    reglages = AVCapturePhotoSettings(format: [AVVideoCodecKey: AVVideoCodecType.jpeg])
                } else {
                    reglages = AVCapturePhotoSettings()
                }
                reglages.photoQualityPrioritization = .balanced
                verrou.lock()
                attentesPhoto[reglages.uniqueID] = suite
                verrou.unlock()
                sortiePhoto.capturePhoto(with: reglages, delegate: self)
            }
        }
        guard let reduite = ImagesJPEG.normaliser(brut, coteMax: 1600, qualite: 0.8) else {
            throw ErreurCamera.photo("image illisible")
        }
        return ImageCapturee(donnees: reduite.1, typeMedia: "image/jpeg", provenance: .telephone)
    }

    /// Secondes écoulées depuis l'ouverture de la caméra (verrou pris hors de tout contexte asynchrone).
    private func secondesDepuisDemarrage() -> TimeInterval {
        verrou.lock()
        defer { verrou.unlock() }
        return demarreeLe.map { Date().timeIntervalSince($0) } ?? 0
    }

    func photoOutput(_ output: AVCapturePhotoOutput, didFinishProcessingPhoto photo: AVCapturePhoto, error: Error?) {
        verrou.lock()
        let suite = attentesPhoto.removeValue(forKey: photo.resolvedSettings.uniqueID)
        verrou.unlock()
        if let error {
            suite?.resume(throwing: ErreurCamera.photo(error.localizedDescription))
        } else if let donnees = photo.fileDataRepresentation() {
            suite?.resume(returning: donnees)
        } else {
            suite?.resume(throwing: ErreurCamera.photo("aucune donnée d'image"))
        }
    }

    // MARK: - Images successives (vision partagée)

    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        guard let tampon = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        verrou.lock()
        dernierTampon = tampon
        dateDernierTampon = Date()
        verrou.unlock()
    }

    /// Âge de la dernière image reçue de la caméra, en secondes (nil : aucune).
    var ageDerniereImage: TimeInterval? {
        verrou.lock(); defer { verrou.unlock() }
        return dateDernierTampon.map { Date().timeIntervalSince($0) }
    }

    /// La dernière image, réduite à `coteMax` pixels et compressée en JPEG. À appeler hors du fil principal.
    func imageJPEG(coteMax: CGFloat, qualite: CGFloat) -> Data? {
        verrou.lock()
        let tampon = dernierTampon
        verrou.unlock()
        guard let tampon else { return nil }
        var image = CIImage(cvPixelBuffer: tampon)
        let largeur = image.extent.width, hauteur = image.extent.height
        guard largeur > 0, hauteur > 0 else { return nil }
        let echelle = min(1, coteMax / max(largeur, hauteur))
        if echelle < 1 {
            image = image.transformed(by: CGAffineTransform(scaleX: echelle, y: echelle))
        }
        guard let espace = CGColorSpace(name: CGColorSpace.sRGB) else { return nil }
        let options: [CIImageRepresentationOption: Any] = [
            CIImageRepresentationOption(rawValue: kCGImageDestinationLossyCompressionQuality as String): qualite,
        ]
        return contexteCI.jpegRepresentation(of: image, colorSpace: espace, options: options)
    }

    // MARK: - Interruptions

    @objc private func sessionInterrompue(_ note: Notification) {
        verrou.lock()
        interrompueFlag = true
        verrou.unlock()
        surInterruption?(true)
    }

    @objc private func sessionReprise(_ note: Notification) {
        verrou.lock()
        interrompueFlag = false
        verrou.unlock()
        surInterruption?(false)
    }
}
