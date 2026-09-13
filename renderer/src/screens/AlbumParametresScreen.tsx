import React from 'react'
import { CarteReglage, TopBar } from '../components/ui'
import { useStore } from '../lib/store'

/* =========================================================================
   « Paramètres d'album » (maquette IMG_0697) : trois interrupteurs mémorisés
   sur cet ordinateur seulement (préférences locales du store, pas de réglage
   serveur). Le partage et la vidéo n'existent pas encore côté service : on le
   dit sous les cartes plutôt que de laisser croire à un effet immédiat.
   ========================================================================= */

export function AlbumParametresScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { prefs, setPref } = useStore()
  return (
    <div className="ecran">
      <TopBar titre="Paramètres d’album" />
      <div className="contenu">
        <CarteReglage
          titre="Filigrane"
          desc="Ajoutez un filigrane lorsque vous partagez des images"
          on={prefs.album_filigrane}
          onChange={(v) => setPref('album_filigrane', v)}
        />
        <CarteReglage
          titre="Stabilisation vidéo"
          desc="Stabilisation vidéo en cours. Gardez l’application au premier plan. Le passage en arrière-plan mettra le traitement en pause."
          on={prefs.album_stabilisation}
          onChange={(v) => setPref('album_stabilisation', v)}
        />
        <CarteReglage
          titre="Enregistrement automatique"
          desc="Lorsque les images sont synchronisées avec l’application, elles sont automatiquement enregistrées dans l’album de l’ordinateur."
          on={prefs.album_enregistrement_auto}
          onChange={(v) => setPref('album_enregistrement_auto', v)}
        />
        <div className="small muted" style={{ padding: '0 6px', lineHeight: 1.45 }}>
          Ces réglages sont mémorisés sur cet ordinateur ; le partage et la vidéo arrivent dans une prochaine version.
        </div>
      </div>
    </div>
  )
}
