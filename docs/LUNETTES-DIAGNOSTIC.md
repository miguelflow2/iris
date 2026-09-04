# Lunettes M01 Pro — ce que le matériel expose réellement

Relevé du 2026-09-04, sur l'exemplaire présent, avec `scripts/diagnostic-lunettes.py`
(strictement en lecture seule : rien n'a été écrit dans les lunettes).

## Identité

| | |
|---|---|
| Nom Bluetooth | `M01 Pro_F444` |
| Adresse | `65:A2:9F:5C:F4:44` |
| Identifiant Bluetooth | VID `05D6`, PID `000A` |
| Adaptateur du PC | Broadcom 20702 Bluetooth 4.0 |

Un second appareil, `GT TWS` (`41:42:22:33:B3:34`), est appairé sur la même machine : ce sont
des écouteurs, pas les lunettes. Ne pas les confondre, ils n'exposent que de l'audio.

## Canaux exposés par les lunettes

**Bluetooth classique**

| Service | Signification |
|---|---|
| `00001101` | **Port série (SPP)** — canal de commande, exposé sur **COM4** |
| `0000110B` | Réception audio (A2DP) |
| `0000110C` / `0000110E` | Contrôle de lecture (AVRCP) |
| `0000111E` | Mains libres (HFP) — le micro |

**Bluetooth basse consommation**

| Service | Signification |
|---|---|
| `00001800` / `00001801` | Standard (nom, attributs) |
| `0000180A` | Information sur l'appareil — donne fabricant, modèle et version du logiciel interne |
| `00003802` | Propriétaire |
| `0000AE30` / `0000AE3A` | Plage utilisée par les puces audio JieLi (AC69xx / AC70xx), très répandues |
| `0000FEE1` | Identifiant Anhui Huami, souvent réutilisé par les fabricants chinois |
| `6E40FFF0-B5A3-F393-E0A9-E50E24DCCA9E` | Canal série sur BLE (base Nordic UART) — second canal de commande |
| `DE5BF728-D711-4E47-AF26-65E3012A5DC7` | Entièrement propriétaire |

## Ce qui est établi

1. **Il existe un canal de commande, et il est accessible.** `COM4` s'ouvre depuis Windows.
   C'est par là que passe le protocole du fabricant.
2. **Il existe un second canal de commande en BLE** (`6E40FFF0…`), plus deux services
   entièrement propriétaires.
3. **Rien n'apparaît en USB** avec le câble de charge fourni. Deux causes possibles, non
   encore départagées : câble sans fils de données, ou absence d'interface USB de données.
4. **Aucun service de mise à jour documenté** (Nordic, Silicon Labs) n'a été observé. La plage
   `AE30`/`AE3A` suggère un mécanisme propriétaire de type JieLi.

## Identité confirmée (lunettes allumées, 2026-09-04 07:13)

| | |
|---|---|
| Révision matérielle | `AM01C_V2.2` |
| Logiciel interne | `AM01C_2.20.04_260122` |
| Identifiant système | `44f45c00009fa265` |

## Le protocole, décodé

Les lunettes émettent en continu sur `de5bf729-d711-4e47-af26-65e3012a5dc7`.
394 trames capturées en 90 secondes. Format :

```
bc <type> <longueur sur 2 octets, petit-boutiste> <données> <2 octets de contrôle>
```

| Type | Fréquence | Nature |
|---|---|---|
| `0x59` | 386 trames, ~25 ms, par paires | Flux continu de télémétrie, 40 octets de charge utile |
| `0x73` | 8 trames, isolées | **Événements discrets — les gestes de l'utilisateur** |

Les événements observés alternent entre deux codes, `c0 80` et `c6 d0`, plus deux trames plus
longues au début (`50 c7 01 01` et `63 c7 01 02`). Reste à savoir quel geste produit quel code :
c'est l'objet de `scripts/decoder-gestes-lunettes.py`, qui étiquette les trames geste par geste.

## Ce qui reste à établir

- Quel geste produit quel code : lancer la capture guidée.
- Nature du flux `0x59` : télémétrie de capteur de mouvement, ou audio.
- Protocole du port série COM4, qui porte peut-être d'autres commandes.
- Interface USB : refaire l'essai avec un câble de données confirmé.

## Ce que cela veut dire

Piloter les lunettes (boutons, LED, audio, capteurs) est **envisageable** par le port série ou
le canal BLE : c'est de la rétro-ingénierie de protocole, sans risque pour l'appareil.

Remplacer le logiciel interne est une **autre affaire** : aucun mécanisme documenté n'est exposé,
donc cela passe par le fabricant de la puce et son kit de développement. C'est une négociation
commerciale, pas un bricolage. Et sans copie du logiciel d'origine, un essai raté rend
l'exemplaire inutilisable.
