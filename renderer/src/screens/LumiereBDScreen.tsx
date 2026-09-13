import React from 'react'
import { useStore } from '../lib/store'
import { Holo, TopBar } from '../components/ui'
import { IcoPlateforme } from '../components/icons'

/* =========================================================================
   « Lumière BD » : la carte de l'accueil promet une transformation de photos
   en traits de bande dessinée. Aucun support côté service pour l'instant :
   l'écran le dit clairement au lieu de simuler.
   ========================================================================= */

export function LumiereBDScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { nav } = useStore()
  return (
    <div className="ecran">
      <TopBar titre="Lumière BD" />
      <div className="contenu">
        <div className="carte" style={{ textAlign: 'center' }}>
          <IcoPlateforme glyphe="baguette" style={{ width: 180, height: 150 }} />
          <h3>Lumière BD</h3>
          <span className="pill warn">À venir</span>
          <p className="desc" style={{ marginTop: 12 }}>Transforme vos photos en traits de bande dessinée : portraits, paysages et plus.</p>
          <p className="muted" style={{ marginTop: 10 }}>Cette fonction n’est pas encore disponible dans cette version d’IRIS.</p>
        </div>
        <Holo variante="sombre" onClick={nav.retour}>Retour</Holo>
      </div>
    </div>
  )
}
