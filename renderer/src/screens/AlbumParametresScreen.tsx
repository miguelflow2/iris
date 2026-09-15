import React, { useEffect, useState } from 'react'
import { CarteReglage, Field, TopBar } from '../components/ui'
import { api, messageErreur } from '../lib/api'
import { useStore } from '../lib/store'

/* =========================================================================
   « Paramètres d'album » (maquette IMG_0697) : les réglages de l'album tels
   que le service les applique (backend/iris/album.py), enregistrés dans les
   réglages d'IRIS (PATCH /api/settings) :
   - album_filigrane : « IRIS · VELA » sur les images EXPORTÉES ;
   - album_enregistrement_auto : copie de chaque nouvelle image dans le dossier
     d'exportation (images seulement, jamais l'audio) ;
   - album_dossier_export : le dossier de ces copies (vide = Images\IRIS).
   La stabilisation vidéo de la maquette reste affichée mais désactivée : IRIS
   ne récupère aucune vidéo des lunettes, il n'y a rien à stabiliser.
   Ce sont des réglages : accessibles sans lunettes.
   ========================================================================= */

export function AlbumParametresScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { settings, updateSettings, toast } = useStore()
  const [dossier, setDossier] = useState<string>(settings?.album_dossier_export || '')
  // Le dossier réellement utilisé, tel que le service le résout (le dossier Images quand le champ est vide).
  const [dossierReel, setDossierReel] = useState<string | null>(null)
  // Ce que le service dit des copies exportées (limite, dossier synchronisé) : affiché tel quel, jamais reformulé.
  const [limiteExport, setLimiteExport] = useState<string | null>(null)
  const [noteSynchronise, setNoteSynchronise] = useState<string | null>(null)

  const lireDossierReel = (): void => {
    api
      .get('/api/album?type=photo')
      .then((r) => {
        setDossierReel(typeof r?.dossier_export === 'string' ? r.dossier_export : null)
        setLimiteExport(typeof r?.limite === 'string' && r.limite ? r.limite : null)
        setNoteSynchronise(r?.synchronise && typeof r?.note_synchronise === 'string' ? r.note_synchronise : null)
      })
      .catch(() => setDossierReel(null))
  }

  useEffect(() => {
    setDossier(settings?.album_dossier_export || '')
  }, [settings?.album_dossier_export])

  useEffect(lireDossierReel, [settings?.album_dossier_export])

  const changer = (patch: Record<string, unknown>): void => {
    updateSettings(patch).catch((err: unknown) => toast(messageErreur(err), 'error'))
  }

  const validerDossier = (): void => {
    const valeur = dossier.trim()
    if (valeur === (settings?.album_dossier_export || '')) return
    updateSettings({ album_dossier_export: valeur })
      .then(() => toast(valeur ? 'Dossier d’exportation enregistré.' : 'Dossier d’exportation : dossier Images par défaut.', 'success'))
      .catch((err: unknown) => toast(messageErreur(err), 'error'))
  }

  const ouvrirDossier = async (): Promise<void> => {
    if (!dossierReel) return
    const erreur = await window.iris.openPath(dossierReel)
    // Le dossier n'est créé qu'au premier export : ce n'est pas une panne, on le dit.
    if (erreur) toast(`Ce dossier n’existe pas encore : il sera créé à la première exportation. (${erreur})`, 'info')
  }

  return (
    <div className="ecran">
      <TopBar titre="Paramètres d’album" />
      <div className="contenu">
        <CarteReglage
          titre="Filigrane"
          desc="Ajoute « IRIS · VELA », discrètement, sur les images que vous exportez. L’image filigranée est réenregistrée sans ses métadonnées (dont une éventuelle position). Les originaux de l’album ne sont pas modifiés."
          on={Boolean(settings?.album_filigrane)}
          disabled={!settings}
          onChange={(v) => changer({ album_filigrane: v })}
        />
        <CarteReglage
          titre="Stabilisation vidéo"
          desc="Non applicable : les vidéos restent dans les lunettes. Le fabricant ne documente pas leur transfert, IRIS ne les récupère donc pas et n’a rien à stabiliser."
          on={false}
          disabled
          onChange={() => undefined}
        />
        <CarteReglage
          titre="Enregistrement automatique"
          desc="Chaque nouvelle photo et chaque image Lumière BD est copiée dans le dossier d’exportation ci-dessous, sans écraser un fichier existant. Les enregistrements audio ne sont pas copiés : ils s’exportent à la main depuis l’album. Aucune copie en mode invité, en zone sans mémoire ni en mode confidentiel."
          on={Boolean(settings?.album_enregistrement_auto)}
          disabled={!settings}
          onChange={(v) => changer({ album_enregistrement_auto: v })}
        />

        <div className="carte col" style={{ gap: 12 }}>
          <h3 style={{ margin: 0 }}>Dossier d’exportation</h3>
          <Field
            label="Chemin complet"
            hint="Vide = votre dossier Images, sous-dossier IRIS. Exemple : C:\Users\vous\Pictures\IRIS. Validé quand vous quittez le champ."
          >
            <input
              className="input mono"
              value={dossier}
              placeholder="Dossier Images\IRIS (par défaut)"
              onChange={(e) => setDossier(e.target.value)}
              onBlur={validerDossier}
              onKeyDown={(e) => {
                if (e.key === 'Enter') validerDossier()
              }}
            />
          </Field>
          {dossierReel ? (
            <div className="small muted" style={{ lineHeight: 1.45 }}>
              Dossier utilisé : <span className="mono" style={{ wordBreak: 'break-all' }}>{dossierReel}</span>
            </div>
          ) : settings?.album_dossier_export ? (
            <div className="bloc-note attention">Ce chemin n’est pas utilisable : indiquez un chemin complet, qui commence par une lettre de lecteur.</div>
          ) : null}
          {noteSynchronise ? <div className="bloc-note attention" role="status">{noteSynchronise}</div> : null}
          {limiteExport ? <div className="small muted" style={{ lineHeight: 1.45 }}>{limiteExport}</div> : null}
          <div className="row wrap" style={{ gap: 8 }}>
            <button type="button" className="btn sm" disabled={!dossierReel} onClick={ouvrirDossier}>Ouvrir le dossier</button>
          </div>
        </div>

        <div className="small muted" style={{ padding: '0 6px', lineHeight: 1.45 }}>
          L’album reste sur cet ordinateur : IRIS n’envoie rien en ligne. Les fichiers copiés hors d’IRIS ne sont pas effacés par la rétention ni
          par l’effacement à distance, et un dossier synchronisé les emporte hors de l’ordinateur.
        </div>
      </div>
    </div>
  )
}
