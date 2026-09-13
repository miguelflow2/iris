/* =========================================================================
   IRIS — application web téléphone (VELA)
   Trois responsabilités, et rien de plus :
     1. Dire honnêtement si la voix d'Iris est prête (le widget ElevenLabs).
     2. Aider à poser l'app sur l'écran d'accueil (Android et iOS Safari).
     3. Enregistrer l'agent de service pour l'installation et la coquille hors ligne.
   Aucune clé, aucun secret : l'agent vocal est appelé par son seul identifiant public,
   posé dans le HTML. Tout le raisonnement et la voix vivent côté ElevenLabs et relais VELA.
   ========================================================================= */
(function () {
  "use strict";

  // -- petit garde-fou pour localStorage : Safari en navigation privée le fait lever.
  function memoire(cle) { try { return localStorage.getItem(cle); } catch (e) { return null; } }
  function retenir(cle, val) { try { localStorage.setItem(cle, val); } catch (e) { /* tant pis */ } }

  // -- où sommes-nous ? (iPadOS se déguise en Mac, d'où le test tactile)
  var UA = navigator.userAgent || "";
  var IOS = /iPad|iPhone|iPod/.test(UA) ||
            (UA.indexOf("Macintosh") !== -1 && "ontouchend" in document);
  var SAFARI_IOS = IOS && !/CriOS|FxiOS|EdgiOS|OPiOS|Chrome/.test(UA);
  var AUTONOME = window.navigator.standalone === true ||
    (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches);

  // ---------------------------------------------------------------- état de la voix
  // Le widget définit l'élément personnalisé <elevenlabs-convai> une fois son script chargé.
  // On s'en sert comme signal honnête : voix prête, ou voix indisponible — jamais de faux « prête ».
  var point = document.getElementById("point");
  var etatTexte = document.getElementById("etat-texte");
  var repli = document.getElementById("repli");
  var indice = document.getElementById("indice");

  function marquer(classe, texte) {
    if (point) point.className = "point " + (classe || "");
    if (etatTexte) etatTexte.textContent = texte;
  }

  function voixPrete() {
    marquer("ok", "Voix d'Iris prête");
  }

  function voixEchouee() {
    marquer("err", "Voix indisponible");
    if (repli) repli.hidden = false;
    if (indice) indice.hidden = true;
  }

  if (window.customElements && customElements.whenDefined) {
    var repondu = false;
    customElements.whenDefined("elevenlabs-convai").then(function () {
      repondu = true;
      voixPrete();
    });
    // Si le script ne se charge pas (hors ligne, ressource bloquée), on le dit au bout de 12 s.
    setTimeout(function () { if (!repondu) voixEchouee(); }, 12000);
  } else {
    // Navigateur trop ancien pour les éléments personnalisés : le widget ne marchera pas.
    voixEchouee();
  }

  // ---------------------------------------------------------------- installation
  var carteInstaller = document.getElementById("installer");
  var texteInstaller = document.getElementById("installer-texte");
  var boutonInstaller = document.getElementById("installer-ok");
  var inviteAndroid = null;   // l'événement beforeinstallprompt, s'il vient

  function montrerInstaller(texte, libelleBouton) {
    if (!carteInstaller || memoire("iris_installe_vu") === "oui" || AUTONOME) return;
    if (texteInstaller) texteInstaller.textContent = texte;
    if (boutonInstaller && libelleBouton) boutonInstaller.textContent = libelleBouton;
    carteInstaller.hidden = false;
  }

  // Android / Chrome : le navigateur propose l'installation ; on la déclenche à la demande.
  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    inviteAndroid = e;
    montrerInstaller(
      "Installez IRIS comme une application : un appui, et elle vit sur votre écran d'accueil.",
      "Installer IRIS"
    );
  });

  if (boutonInstaller) {
    boutonInstaller.addEventListener("click", function () {
      if (inviteAndroid) {
        inviteAndroid.prompt();
        inviteAndroid.userChoice.finally(function () { inviteAndroid = null; });
      }
      carteInstaller.hidden = true;
      retenir("iris_installe_vu", "oui");   // fermé une fois, fermé pour de bon
    });
  }

  // iOS : aucun événement d'installation n'existe. Le seul chemin est Safari ▸ Partager ▸
  // « Sur l'écran d'accueil ». On l'explique, et on nomme Safari car lui seul sait le faire.
  if (IOS && !AUTONOME) {
    montrerInstaller(
      SAFARI_IOS
        ? "Gardez Iris sous la main : touchez Partager, en bas de Safari, puis « Sur l'écran d'accueil »."
        : "Gardez Iris sous la main : ouvrez cette adresse dans Safari — seul lui sait le faire sur iPhone — puis Partager, puis « Sur l'écran d'accueil ».",
      "Compris"
    );
  }

  // ---------------------------------------------------------------- agent de service
  // Il sert la coquille hors ligne (l'app s'ouvre même sans réseau, avec un message clair) et,
  // sur Android, permet la proposition d'installation. Sans lui, l'app marche quand même.
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("./sw.js").catch(function () { /* facultatif */ });
    });
  }
})();
