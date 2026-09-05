# Sondes des lunettes VELA

Le carnet de laboratoire du décodage des lunettes `M01 Pro_F444`
(micrologiciel `AM01C_2.20.04_260122`, matériel `AM01C_V2.2`).

Ces programmes ne servent pas à IRIS : ils servent à comprendre les lunettes. Le résultat, lui,
est dans `iris/lunettes_trames.py` et gardé par `tests/test_lunettes_trames.py`.

## Dans l'ordre où ils ont servi

| Programme | Ce qu'il a appris |
|---|---|
| `sonder_lunettes.py` | Écrire sur l'UART Nordic est accepté, sans réponse. Les lectures par UUID en chaîne échouaient. |
| `sonder_lunettes2.py` | L'identité complète (nom, micrologiciel, matériel). Les paquets ne sont ni périodiques ni liés au volume de Windows : 100 s d'écoute, zéro paquet. |
| `ecouter_lunettes.py` | Un quatrième paquet, une demi-heure après les trois premiers, avec l'octet à 83 au lieu de 84. C'est ce qui a révélé la batterie. |
| `trouver_crc.py` | **La somme de contrôle** : CRC-16/MODBUS petit-boutiste sur le contenu seul. Quatorze variantes de CRC, six découpages, une seule combinaison colle sur les quatre trames. |
| `ecouter_serie.py` | Le port `COM4` s'ouvre mais rien n'y circule spontanément. |
| `parler_serie.py` | Fausse piste : `COM4` renvoie tout à l'identique, y compris des octets absurdes. C'est un écho local de Windows, pas un canal vers les lunettes. |
| `parler_ble.py` | Écriture acceptée sur `de5bf72a`, aucune réponse. La commande `0x73` ne descend que dans un sens. |

## Ce qui est établi

```
bc | commande | longueur (2, petit-boutiste) | CRC-16/MODBUS du contenu (2, petit-boutiste) | contenu
```

Preuve : la trame reconstruite à partir de « batterie 86 % » est identique, octet pour octet, à
celle reçue des lunettes.

Seule commande observée : `0x73`, contenu `05 BB 00`, où `BB` est le pourcentage de batterie.
Ces lunettes n'exposent aucune caractéristique de batterie standard — c'est le seul moyen de
connaître leur charge.

## Ce qui reste inconnu

Les commandes montantes. Aucune trame `0x73` envoyée n'a provoqué de réponse : soit cette commande
ne sert qu'aux notifications descendantes, soit il faut d'abord ouvrir une session dont on ignore
la forme.

## Ce qu'on ne fait pas

Aucun balayage des autres commandes, et rien sur les caractéristiques `ae01`, `ae03` et `ae3b`.
Sur ces puces, ce sont elles qui portent la mise à jour du micrologiciel : une séquence mal devinée
transforme les lunettes en presse-papier. Il n'y en a qu'une paire.
