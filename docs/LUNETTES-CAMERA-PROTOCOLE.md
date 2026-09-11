# Lunettes VELA — protocole CAMÉRA / MÉDIA (extrait du SDK XSX)

Rédigé le 2026-09-09 à partir de l'extraction du **SDK XSX** (`C:\Users\migue\Downloads\vela-sdk\`) :
code source Java lisible de la démo, bytecode des `.aar` (`XSXGlass`, `XSXBluetooth`, `XSXSdk`,
`XSXHttp`) lu octet par octet avec un petit parseur de fichiers `.class`, et la documentation
officielle chinoise (`XSX_SDK … Android说明文档.docx`, extraite et traduite).

Ce document décrit **comment piloter la caméra des lunettes et récupérer l'image**. C'est la
fonctionnalité différenciante de VELA : *« la caméra, mais l'image ne part pas chez un tiers »*.
Le SDK d'origine, lui, envoie l'image et la voix à des clouds chinois (Baidu, xinsudian, Aliyun) —
voir §9. IRIS remplace tout ce chemin cloud par sa propre IA.

## Convention de certitude

- **[ÉTABLI]** = vu directement dans le code source de la démo, dans le bytecode extrait, ou dans
  la doc officielle. Cité avec le fichier.
- **[DÉDUIT]** = raisonnement cohérent à partir de plusieurs indices, mais pas d'affirmation
  directe dans une source.
- **[À CONFIRMER]** = pas trouvé de façon fiable dans le matériel disponible (bytecode obfusqué,
  logique noyée dans une méthode non décompilable proprement). À valider par un sniff BLE de
  l'application officielle, ou une décompilation `jadx` ultérieure, ou un test sur le vrai matériel.

> **Rien ici n'a été testé sur les vraies lunettes.** Tout vient de la lecture du SDK. Les octets
> marqués [À CONFIRMER] ne doivent pas être envoyés au hasard aux lunettes (voir l'avertissement
> de `LUNETTES-PUCE.md` §6 : le même espace de commandes contient le formatage et la suppression
> de fichiers).

---

## 0. Avertissement matériel important — deux paires de lunettes différentes

Il faut distinguer deux appareils, sinon tout ce document induit en erreur :

1. **Les lunettes que Miguel a physiquement aujourd'hui** (« M01 Pro » audio) : elles n'ont
   **pas de caméra**. Le relevé BLE (`docs/LUNETTES-PUCE.md`, `docs/LUNETTES-DIAGNOSTIC.md`)
   montre qu'elles exposent les canaux transparents Jieli `ae30`/`ae3a` et une couche applicative
   Oudmon/Colmi (service `de5bf728`, canal d'écriture `de5bf72a`, protocole à octet magique
   `0xBC`). C'est ce canal `de5bf72a` que `backend/iris/glasses.py` utilise déjà (constante
   `CANAL_COMMANDE`), et le protocole `0xBC` est décodé dans `backend/iris/lunettes_trames.py`.
   **Ces lunettes n'exposent pas `ae00` et ne prennent pas de photo.**

2. **Les lunettes-caméra cibles de VELA** (M01 Pro *avec caméra* : processeur Jieli type
   « JL7018F », capteur Sony IMX219 selon les notices citées dans `LUNETTES-PUCE.md` §3). C'est
   **pour elles** qu'est écrit le SDK XSX. Elles exposent le service **`ae00`** (RCSP/applicatif
   Jieli) — voir §4. C'est le protocole décrit dans ce document.

**Conséquence directe** : le module `backend/iris/lunettes_camera.py` livré ici cible l'interface
`ae00`/`ae01`/`ae02` des lunettes-caméra. Il réutilise la mécanique BLE d'IRIS (le thread Bleak
dédié, le `BleakClient`, l'abonnement aux notifications) mais **ne pourra pas être exercé sur la
paire audio actuelle** : elle n'a ni caméra ni service `ae00`. Il faut la paire caméra pour
tester. Le module est écrit pour être branché et validé le jour où cette paire est là.

---

## 1. Résumé exécutable (la chaîne complète)

Pour « IRIS, prends une photo », sur les lunettes-caméra :

```
1. IRIS  --(BLE, écriture sur ae01)-->  trame « Camera / prise de photo »   (§7.1)
2. Lunettes : déclenchent le capteur, écrivent le JPEG sur leur stockage interne.
3. Récupération de l'image, DEUX chemins possibles :
   a) BLE : les lunettes poussent le fichier en paquets sur ae02 (protocole « Pro »
      FileStartTransfer / FilePackTransfer / FileTransferFinished).            (§8.1)  [chemin privé, préféré]
   b) WiFi : les lunettes ouvrent un point d'accès WiFi ; le PC s'y connecte ;
      téléchargement HTTP de chaque fichier depuis l'IP locale des lunettes.   (§8.2)  [chemin de masse]
4. IRIS a le JPEG en local -> le donne à SA PROPRE IA (vision), jamais à un cloud tiers.  (§9)
```

Le SDK d'origine ajoute une étape 4′ : `takePictureAndRecognize` envoie l'image à Baidu/xinsudian
avec l'invite « décris cette image ». **C'est exactement ce que VELA supprime.**

---

## 2. Ce que le SDK XSX sait faire (API publique) — [ÉTABLI]

Relevé de tous les appels `XSXSdk.getInstance().*` dans la démo
(`android/XSXSdk_demo/.../ui/MainActivity.java`) et des méthodes du constructeur de trames
`com.xsx.rdpro.RDProSendUtils` (bytecode `XSXGlass_V1.0.2.aar`) :

| Méthode SDK | Rôle | Source |
|---|---|---|
| `takePicture()` | prendre une photo | MainActivity l.222 ; builder `RDProSendUtils.takeAPicture()` |
| `takePictureAndRecognize(prompt)` | photo + envoi à l'IA cloud pour description | MainActivity l.270 (invite « 描述一下这张图片的内容 » = « décris cette image ») |
| `startRecordVideo(sec)` / `stopRecordVideo()` | enregistrer une vidéo (durée en s) | MainActivity l.251/260 ; `RDProSendUtils.controlVideo(ControlEnum, int)` |
| `startRecordAudio(sec)` / `stopRecordAudio()` | enregistrer de l'audio | MainActivity l.232/241 ; `RDProSendUtils.controlAudio(ControlEnum, int)` |
| `getDeviceParams()` / `setDeviceParams()` | lire/écrire réglages (ratios photo/vidéo, durées, filigrane…) | MainActivity l.157 |
| `controlDevice(ControlDeviceEnum)` | éteindre, redémarrer, réinitialiser… | MainActivity l.198 |
| `syncTime()` | synchroniser l'heure | MainActivity l.213 |
| `shutDown()`, `restart()`, `restore()` | raccourcis de contrôle | MainActivity l.184/191/205 |
| `initAI(context)` | initialiser la couche IA (cloud) | MainActivity l.397 |

La doc officielle (§5 « 眼镜控制 ») confirme la même liste : 5.1 拍照 (photo), 5.2 AI识图
(reconnaissance d'image), 5.3/5.4 录像 (vidéo début/fin), 5.5/5.6 录音 (audio début/fin),
5.7 眼镜存储空间 (espace de stockage).

---

## 3. Puce et pile logicielle — [ÉTABLI]

- Le SDK XSX abstrait **deux familles de puces** : la classe `com.xsx.rdpro.main.BLEAgmHelper`
  contient les constantes `PLATFORM_JL` (Jieli), `PLATFORM_RU_8763` (Realtek RTL8763) et les
  classes de base `com/xsx/rdpro/platform/jieli/RDJieLiBase` et
  `com/xsx/rdpro/platform/realtek/RDRealTekBase`. Il y a un jeu d'UUID « par défaut »
  (`SERVICE_UUID_DEF`, `WRITE_CHAR_UUID_DEF`, `NOTIFY_CHAR_UUID_DEF`) et un jeu « JL »
  (`NOTIFY_CHAR_UUID_JL`), commutés par `setPlatformNotify(platform)`.
- Le transfert de fichier côté Jieli s'appuie sur la **bibliothèque officielle Jieli** :
  `com.jieli.jl_rcsp.impl.RcspOpImpl`, `com.jieli.jl_filebrowse.bean.FileStruct`,
  `com.jieli.jl_filebrowse.bean.SDCardBean` (vus dans `com/xsx/rdpro/platform/jieli/rdb.class`,
  la classe interne `FileDownloadManager`). C'est du **RCSP over BLE** : les médias sont sur la
  carte SD des lunettes et se parcourent/téléchargent par le protocole série Jieli.

Cela recoupe `LUNETTES-PUCE.md` : puce Jieli (identifiant société Bluetooth SIG `0x05D6`),
protocole applicatif RCSP, service `ae00`.

---

## 4. Canal BLE — UUID — [ÉTABLI]

Constantes lues dans `com/xsx/rdbluetooth/utils/BluetoothConstant.class` (`XSXBluetooth_V1.0.1.aar`) :

| Rôle | UUID |
|---|---|
| Service applicatif (« DEF ») | `0000ae00-0000-1000-8000-00805f9b34fb` |
| Écriture (commandes) | `0000ae01-0000-1000-8000-00805f9b34fb` |
| Notification (réponses / fichiers) | `0000ae02-0000-1000-8000-00805f9b34fb` |
| Descriptor CCCD | `00002902-…` |
| SPP (Bluetooth classique) | `00001101-…` |
| A2DP / HFP | `0000110b-…` / `0000111e-…` |

C'est **exactement** le service RCSP `ae00`/`ae01`/`ae02` de Jieli documenté dans
`LUNETTES-PUCE.md` §1.3. **On écrit les commandes sur `ae01`, on écoute les réponses et les
fichiers sur `ae02`.**

> Rappel §0 : la paire audio actuelle n'expose PAS `ae00`. Elle expose `ae30`/`ae3a`/`de5bf728`.
> Le module caméra doit donc chercher `ae01`/`ae02` et échouer proprement s'ils sont absents.

---

## 5. Séquence de connexion / handshake — [ÉTABLI pour le cadre, À CONFIRMER pour l'auth RCSP]

D'après `MainActivity.onConnectChange()` et la doc §4, les états de connexion (enum
`RDProStateEnum`, bytecode) sont, dans l'ordre :

```
Disconnect(0) -> Connecting(3) -> Connected(4) -> ServicesDiscovered(5) -> Authenticated(6)
                                                                     \-> Authenticated_fail(2)
```

1. **Scan / bind** BLE classique (le SDK parle de « 绑定 » = appairage). [ÉTABLI]
2. **Connexion GATT**, découverte des services. [ÉTABLI]
3. **Abonnement** aux notifications sur `ae02` (CCCD `2902`). [ÉTABLI — c'est ce que fait déjà
   `glasses.py:_ble_subscribe`, qui active `notify` sur toute caractéristique qui le permet]
4. **Négociation de MTU** : `RDProSendUtils.syncMTU(int)` envoie une trame de type MTU
   (`ProBeanEnum.MTU`). Le SDK travaille avec un MTU élevé pour le transfert de fichier
   (`BLEAgmHelper` : `MTU_SIZE`, `updateBleMtu`, `setAppointMtuSize`). [ÉTABLI]
5. **Authentification** : le RCSP Jieli comporte une poignée de main (`RcspAuth`, clé statique de
   16 octets) — voir `LUNETTES-PUCE.md` §1.4. Le SDK XSX passe à l'état `Authenticated` avant
   d'autoriser les commandes. **Le détail exact de l'auth pour ces lunettes est [À CONFIRMER]** ;
   il se peut qu'elle soit permissive (beaucoup de firmwares Jieli acceptent une auth par défaut).
6. Ensuite seulement : `syncTime()`, `getDeviceParams()`, puis les commandes caméra.

**Pour IRIS** : les étapes 1-3 sont déjà faites par `GlassesService.connect()`. Le module caméra
doit, en plus, s'assurer que `ae01`/`ae02` existent, tenter le `syncMTU`, et — au besoin —
l'auth RCSP (marquée TODO dans le code).

---

## 6. Le protocole applicatif « Pro » — format de trame

Le SDK n'envoie pas d'octets bruts : il construit des objets `ProBean` (paquet applicatif),
sérialisés puis fragmentés à la taille du MTU par `RDProSendUtils` (méthode privée
`rda(byte, byte, byte[])`, qui utilise `RDUtils.splitByteArr` et recopie les paquets avec un
en-tête via `System.arraycopy` à un décalage de **5 octets**). [ÉTABLI]

### Types de trame — enum `ProBeanEnum` — [ÉTABLI] (bytecode `bean/type/ProBeanEnum.class`)

Chaque trame porte un **type** (discriminant interne du SDK). Valeurs (ordinal) :

| Valeur | Type | Sens |
|---|---|---|
| 0 | `Sync` | synchro / heartbeat |
| 1 | `FileTransferResp` | réponse de transfert de fichier |
| 2 | **`Camera`** | **commande caméra (photo)** |
| 3 | `PushFileStart` | début d'envoi de fichier (app→lunettes) |
| 4 | `FirmwareComplete` | fin de firmware (OTA) |
| 5 | `ProBean` | générique |
| 6 | `MTU` | négociation de MTU |
| 7 | `DeviceInfos` | infos appareil |
| 8 | `DeviceParamsResp` | réponse « réglages » |
| 9 | `GetParamsResp` | réponse « lire réglages » |
| 10 | `ControlDeviceResp` | réponse à un contrôle appareil |
| 11 | `FileStartTransfer` | **début de transfert d'un fichier (lunettes→app)** |
| 12 | `FilePackTransfer` | **un paquet de données de fichier** |
| 13 | `FileTransferFinished` | **fin de transfert d'un fichier** |

> **[À CONFIRMER]** : ces valeurs sont l'ordinal de l'enum interne. Rien ne prouve encore que
> l'octet *sur le fil* soit exactement cet ordinal ; le SDK peut le mapper vers un opcode
> différent lors de la sérialisation. À valider par sniff BLE.

### En-tête de trame — [À CONFIRMER]

L'en-tête fait **5 octets** (décalage confirmé dans `rda`). Sa composition exacte (octet magique,
type, longueur, index/total de fragment, somme de contrôle) n'a **pas** pu être lue de façon fiable
dans le bytecode obfusqué.

- Indice faible : le constructeur de trames `RDProSendUtils` contient deux littéraux `0xFE`
  (aucun `0xBC`, aucun `0xDC`/`0xBA`). Le protocole RCSP Jieli commence par `FE DC BA … EF`
  (`LUNETTES-PUCE.md` §1.4). **Hypothèse [DÉDUIT]** : la trame « Pro » dérive du cadre RCSP
  (magie `0xFE…`), pas du cadre Oudmon `0xBC` de la paire audio.
- Le champ longueur est sur 16 bits (les beans `ProMTUBean`/`ProFilePackBean` manipulent des
  `max` et `index` — cf. `ProBean.setMaxAndIndex(int max, int index)`), ce qui va avec une
  fragmentation index/total.

**À trancher par**: (a) capture BLE des écritures `ae01` pendant que l'app officielle prend une
photo ; ou (b) décompilation `jadx` de `RDProSendUtils.rda(BB[B)V`, `ProBean` et `BLEAgmHelper`.

---

## 7. Commandes caméra / vidéo / audio — charges utiles

### 7.1 Prendre une photo — [ÉTABLI pour la charge utile, À CONFIRMER pour l'enveloppe]

`RDProSendUtils.takeAPicture()` (bytecode) construit une charge utile de 3 octets :

```
0x01 0x04 0x00
```

et l'envoie via une trame de type `Camera` (`ProBeanEnum.Camera` = 2).

`RDProSendUtils.takePictureAndRecognize()` construit exactement la même chose **sauf l'octet du
milieu** :

```
0x01 0x07 0x00
```

**Lecture [DÉDUIT]** : octet 0 = sous-commande « prise de photo » (`0x01`) ; octet 1 = **mode** :
`0x04` = photo simple, `0x07` = photo destinée à la reconnaissance IA ; octet 2 = réservé (`0x00`).
Le préfixe/en-tête « Pro » (magie + type Camera + longueur) reste [À CONFIRMER] (§6).

### 7.2 Vidéo — [ÉTABLI]

`controlVideo(ControlEnum, int durée)` : `ControlEnum.Open`(1) = démarrer, `ControlEnum.Close`(0)
= arrêter ; l'entier est la durée en secondes (la démo met 10 s par défaut). Type de trame :
famille `Camera`/contrôle. Les octets exacts de l'enveloppe : [À CONFIRMER].

### 7.3 Audio — [ÉTABLI]

`controlAudio(ControlEnum, int durée)` : même logique. L'audio est stocké en **`.opus`**
(la démo le re-décode ensuite en `.pcm`, cf. `MediaActivity.onDecodeOpusComplete`).

### 7.4 Contrôle appareil — [ÉTABLI] (enum `ControlDeviceEnum`, bytecode)

Valeurs (`getId`) portées dans la charge utile d'une trame `controlDevice` :

| id | nom |
|---|---|
| 0 | `ShutDown` (éteindre) |
| 1 | `Restart` (redémarrer) |
| 2 | `Restore` (réinit. réglages) |
| 3 | `Restore_ShutDown` |
| 4 | `Shipping_Mode` (mode transport) |
| 5 | `Erasure_Data` (**effacer les données** — dangereux) |

> Ne jamais deviner ces octets à l'aveugle : `Erasure_Data` efface l'appareil.

---

## 8. Récupérer le média — les deux chemins de transfert

### 8.1 Chemin BLE (protocole « Pro », préféré pour VELA — privé) — [ÉTABLI dans ses grandes lignes]

Les lunettes poussent un fichier vers l'app **sur `ae02`** en trois temps (types de trame vus au
§6, et beans `com.xsx.rdpro.bean.agreement.*` + listeners `com.xsx.rdpro.listener.*`) :

```
FileStartTransfer(11)  -> ProTransferFileInfoBean / ProFileStartBean : nom + taille du fichier
FilePackTransfer(12)   -> ProFilePackBean : un paquet de données (index / max)   [répété]
FileTransferFinished(13) -> ProTransferFileFinishedBean : terminé
```

Côté app, la réception est gérée par `com.xsx.rdpro.main.RDReceiveFile` et remontée par
`OnFileReceiveListener` / `RDProReceiveFileListener` / `OnSingleFileTransferListener`. L'app doit
**acquitter** chaque étape : `RDProSendUtils` expose `fileStartTransferResp`, `fileTransferResp`,
`fileRetransferPack` (redemander un paquet perdu), `fileTransferFinish`. Il y a donc un contrôle
de flux avec ré-émission des paquets manquants.

**C'est le chemin que le module IRIS vise pour `prendre_photo()`** : purement BLE, pas de WiFi à
gérer, l'image ne quitte jamais l'appareil vers un réseau. Les octets exacts d'acquittement sont
[À CONFIRMER] (mêmes réserves qu'au §6).

Il existe aussi le chemin RCSP « brut » de Jieli (`FileDownloadManager` /
`com.jieli.jl_filebrowse`) : on liste les fichiers de la carte SD (`FileStruct`, `SDCardBean`)
puis on télécharge par `startDownloadFile`. C'est plus bas niveau et propre à la plateforme Jieli.

### 8.2 Chemin WiFi (« importer les médias » — transfert de masse) — [ÉTABLI]

C'est le chemin de l'écran « Media » de la démo (`ui/media/MediaActivity.java`) et de la doc §6
(« 导出媒体资源 » / « WiFi导媒体资源 »). Géré par `com.xsx.sdk.main.DeviceWiFiManager` et
`MediaDownloadManager` (`XSXSdk_V1.0.2.aar`), avec l'interface de rappel `OnMediaDownloadListener`
(documentée intégralement dans le `.docx`) :

Déroulé :

```
1. DeviceWiFiManager.startDownloadMedia()
2. Les lunettes DÉMARRENT un point d'accès WiFi   -> callback hotspotStartSuccess(type)
   (type 0 = téléchargement média, 1 = OTA)
3. Le PC/téléphone découvre puis se connecte au WiFi des lunettes (WiFi Direct / P2P)
     -> discoverHotspotTimeout / discoverPeersTimeout / onConnectTimeout en cas d'échec
     -> onConnected(String ip, int type)          (« ip » = IP locale, log « MediaDownloadManager ip: »)
4. onDownloadStart(total)
5. Pour chaque fichier :
     - téléchargement HTTP depuis une URL locale (log « MediaDownloadManager sdpUrl: »)
       via com.xsx.rdhttp.download.IP2pDownloadManager (le « P2pDownloadManager » cherché)
       + IDownloadInfo / IDownloadCallback
     - onDownloadingMedia(index), onDownloadProgress(progress, total)
     - onDownloadSuccess(filePath)
6. onDownloadComplete()
```

- **Mécanisme** : les lunettes exposent un **serveur HTTP local** sur leur point d'accès WiFi ;
  chaque média a une **`sdpUrl`** (URL de fichier). Le PC télécharge par HTTP GET depuis l'IP des
  lunettes. [ÉTABLI : chaînes `ip:`, `sdpUrl:`, `IP2pDownloadManager`, `IDownloadInfo`, `http`,
  `.jpg` dans `MediaDownloadManager.class`]
- **Formats de fichier** [ÉTABLI, `MediaActivity.addData`] : photo `.jpg` / `.png`, vidéo `.mp4`,
  audio `.opus` / `.pcm`.
- **[À CONFIRMER]** : le SSID / mot de passe exact du point d'accès, le port HTTP, et le gabarit
  précis de `sdpUrl` (ex. `http://192.168.x.x:PORT/CHEMIN`). La liste des fichiers
  (`getResourceInfoFilesTotal`) est vraisemblablement obtenue d'abord par BLE, puis chaque
  `sdpUrl` est construite à partir de l'IP obtenue à la connexion WiFi. Le coordinateur
  `RetrofitP2pUtils` pointe aussi vers un serveur Aliyun `47.106.235.155:48080` — à surveiller :
  une partie de la mise en relation P2P peut transiter par ce serveur (§9).

Contraintes vues dans `MediaActivity` : pas de téléchargement si batterie basse (`isLowBattery`),
ni en charge (`isCharging`), ni pendant un enregistrement audio/vidéo en cours.

---

## 9. Le problème « vie privée » que VELA résout — [ÉTABLI]

Endpoints cloud codés en dur dans `XSXHttp_V1.0.1.aar` (classes `com/xsx/rdhttp/utils/Retrofit*`) :

| Hôte | Usage | Classe |
|---|---|---|
| `http://vop.baidu.com` | **reconnaissance vocale (ASR) Baidu** | `RetrofitAsrUtils` |
| `https://duer-kids.baidu.com` | **dialogue / LLM Baidu** | `RetrofitChatGPTUtils` |
| `http://bk.xinsudian.com` | SDK / IA « xinsudian » | `RetrofitSDKUtils` |
| `http://47.106.235.155:48080` | backend applicatif + P2P (Aliyun Shenzhen) | `RetrofitUtils`, `RetrofitP2pUtils` |
| `https://swapi.yueqizhixiang.com/` | API télécommande | `RetrofitRemoteControlUtils` |
| `https://api.ximalaya.com` | contenu audio (radio) | `RetrofitNewsRadioUtils` |
| `https://www.zhenyiwulian.com` | backend applicatif | `RetrofitAppUtils` |

`takePictureAndRecognize(prompt)` envoie **l'image capturée** à ce chemin cloud (beans
`ArtChatPictureRequestBody`, `ArtRecogImage*`, `ChatArtRecognizeBean` dans `XSXGlass`) avec une
invite du type « décris cette image ». La voix (ASR) part chez Baidu, le dialogue chez Baidu, la
reconnaissance d'image chez Baidu/xinsudian.

**Position VELA/IRIS** : on garde uniquement les étapes 1-3 (capture + rapatriement local de
l'image) et on remplace l'étape 4 (reconnaissance) par l'IA propre d'IRIS. Aucune image, aucune
voix ne part vers Baidu/xinsudian/Aliyun. C'est l'argument produit, et il est techniquement
fondé : le SDK sépare proprement la capture/transfert (BLE + WiFi local) de l'analyse (cloud).

---

## 10. Ce qui reste à confirmer, et comment

Par ordre d'importance pour finir le module caméra :

1. **En-tête exact de la trame « Pro »** (magie, type sur le fil, longueur, CRC) et **opcode réel
   de la commande photo**. → `jadx` sur `RDProSendUtils`, `ProBean`, `BLEAgmHelper` ; ou sniff BLE
   (nRF Connect / Wireshark+HCI) des écritures `ae01` pendant que l'app officielle prend une photo.
2. **Séquence d'acquittement du transfert de fichier BLE** (`fileStartTransferResp`,
   `fileTransferResp`, `fileTransferFinish`) : octets exacts. → même méthode.
3. **Authentification RCSP** : nécessaire ou permissive sur ces lunettes ? → tester une commande
   de lecture inoffensive après connexion, observer si `Authenticated` est atteint.
4. **Chemin WiFi** : SSID/mot de passe du point d'accès, port HTTP, gabarit de `sdpUrl`.
   → sniff réseau une fois connecté au WiFi des lunettes, ou `jadx` sur `DeviceWiFiManager` /
   `MediaDownloadManager` / `com.xsx.rdhttp.download`.
5. **Tester sur la vraie paire caméra.** Rien de ceci n'est prouvé sur le matériel.

Outils recommandés (aucun n'écrit dans les lunettes) : `jadx-gui` sur les `.aar`, `nRF Connect`
pour lire le profil GATT réel et sniffer, capture HCI Bluetooth de Windows/Android.

---

## 11. Intégration dans IRIS (à appliquer par l'agent qui touche main.py / tools.py)

Le module livré (`backend/iris/lunettes_camera.py`) est autonome et **ne modifie aucun fichier
existant**. Pour le brancher, trois petits ajouts (non appliqués ici pour éviter les conflits
avec les autres agents qui touchent la couche voix/chat/lunettes) :

1. **Instancier la caméra** à côté du service lunettes. Dans `main.py`, là où est créé
   `self.glasses = GlassesService(...)` (l.145) :

   ```python
   from .lunettes_camera import CameraLunettes
   self.camera_lunettes = CameraLunettes(self.glasses)  # réutilise la connexion BLE existante
   ```

   Passer la référence au ToolContext (comme `glasses` l'est déjà) : ajouter un champ
   `camera_lunettes: Any = None` à `ToolContext` (tools.py) et le renseigner à la construction
   du contexte.

2. **Exposer un outil à l'agent** — dans `tools.py`, ajouter au `TOOL_SPECS` :

   ```python
   ToolSpec(
       "lunettes_prendre_photo",
       "Prend une photo avec la caméra des lunettes VELA et récupère l'image en local "
       "(elle ne part chez aucun tiers). À utiliser pour « prends une photo », « regarde ça ».",
       _obj({"reconnaissance": {"type": "boolean",
             "description": "true si la photo doit ensuite être décrite/analysée par IRIS"}}),
   ),
   ```

   et le brancher dans `_run_inner`, dans le bloc `if name.startswith("lunettes_"):` déjà présent
   (à côté de `lunettes_etat` / `lunettes_envoyer`) :

   ```python
   if name == "lunettes_prendre_photo":
       cam = getattr(ctx, "camera_lunettes", None)
       if cam is None:
           return _err("La caméra des lunettes n'est pas disponible.")
       try:
           res = await cam.prendre_photo(bool(args.get("reconnaissance", False)))
       except Exception as exc:
           return _err(str(exc))
       return json.dumps(res.__dict__, ensure_ascii=False)
   ```

   Comme les autres tâches déclenchées à la voix, penser à lever la pastille de capture :
   `ctx.capture.set(camera=True)` autour de la prise de vue (le champ `camera` existe déjà dans
   `CaptureIndicator`), puis `ctx.capture.set(camera=False)` — l'indicateur de capture non
   désactivable est déjà prévu pour ça.

3. **Chaîner vers l'IA locale** : quand `reconnaissance=True`, une fois le JPEG obtenu
   (`res.chemin`), le passer à la vision locale d'IRIS plutôt qu'au cloud — c'est là que se joue
   la promesse VELA. À câbler quand la brique vision locale est prête.

Ainsi, dire « IRIS, prends une photo » déclenchera l'outil `lunettes_prendre_photo`, qui appelle
`CameraLunettes.prendre_photo()`, qui réutilise la connexion BLE de `GlassesService`.

> Tant que l'en-tête de trame n'est pas confirmé (§6), l'outil renverra un message honnête
> expliquant qu'il n'écrit pas d'octets non prouvés (sauf réglage « lunettes_exploration »). Ce
> n'est pas un bug : c'est le garde-fou anti-« brique » demandé par LUNETTES-PUCE.md.

---

## 12. Sources (fichiers réellement ouverts)

- Démo Java : `android/XSXSdk_demo/app/src/main/java/com/xsx/xsxproductiontool/` —
  `ui/MainActivity.java`, `service/EventManagerService.java`, `service/CameraService.java`
  (stub, commenté), `ui/media/MediaActivity.java`, `dialog/WiFiDialog.java`.
- Bytecode `XSXGlass_V1.0.2.aar` : `com/xsx/rdpro/RDProSendUtils`,
  `com/xsx/rdpro/main/BLEAgmHelper`, `com/xsx/rdpro/main/RDReceiveFile`,
  `com/xsx/rdpro/bean/type/{ProBeanEnum,ControlDeviceEnum,ControlEnum,RDProStateEnum,SDPEnum}`,
  `com/xsx/rdpro/bean/agreement/ProFilePackBean`, `ProTransferFileInfoBean`,
  `ProTransferFileFinishedBean`, `com/xsx/rdpro/platform/jieli/rdb` (FileDownloadManager),
  `com/xsx/rdpro/bean/other/DeviceControlBean`.
- Bytecode `XSXBluetooth_V1.0.1.aar` : `com/xsx/rdbluetooth/utils/BluetoothConstant`.
- Bytecode `XSXSdk_V1.0.2.aar` : `com/xsx/sdk/main/DeviceWiFiManager`, `MediaDownloadManager`,
  `com/xsx/sdk/listener/OnMediaDownloadListener`.
- Bytecode `XSXHttp_V1.0.1.aar` : `com/xsx/rdhttp/utils/Retrofit*`, `com/xsx/rdhttp/download/*`.
- Doc officielle : `android/XSX_SDK_V1.0.1 Android说明文档.docx` (§4 connexion, §5 contrôle,
  §6 export média WiFi, §7 IA).
- Croisé avec `docs/LUNETTES-PUCE.md` et `docs/LUNETTES-DIAGNOSTIC.md` (relevé matériel IRIS).

Méthode d'extraction du bytecode : parseur `.class` maison (constant pool + désassemblage partiel
des méthodes) — pas de `jadx` disponible sur la machine. Les charges utiles du §7.1 (`01 04 00` /
`01 07 00`) viennent de la lecture directe des instructions `bipush`/`bastore` de
`RDProSendUtils.takeAPicture()` / `takePictureAndRecognize()`.
