import React, { useEffect, useState } from 'react'
import { TopBar, TutoNav } from '../components/ui'
import { LunettesPave, type GestePave } from '../components/Lunettes'

/* =========================================================================
   Tutoriel « Gestes du pavé tactile » (maquettes IMG_0701 à 0703) : trois
   étapes dans un seul écran, la vue de dessus des branches avec le point
   bleu qui marque le geste.
   ========================================================================= */

interface Etape {
  sousTitre: string
  h2: string
  geste: GestePave
}

const ETAPES: Etape[] = [
  { sousTitre: 'Lecture / Pause', h2: 'Deux tapes sur le pavé', geste: 'double' },
  { sousTitre: 'Piste précédente', h2: 'Trois tapes sur le pavé', geste: 'triple' },
  { sousTitre: 'Piste suivante', h2: 'Appui long sur le pavé droit', geste: 'long' }
]

function indexDepart(params?: Record<string, any>): number {
  const n = Number(params?.etape)
  return Number.isFinite(n) ? Math.min(ETAPES.length - 1, Math.max(0, Math.floor(n))) : 0
}

export function TutoTouchpadScreen({ params }: { params?: Record<string, any> }): JSX.Element {
  const [index, setIndex] = useState(() => indexDepart(params))
  const etape = ETAPES[index]

  const precedent = (): void => setIndex((i) => Math.max(0, i - 1))
  const suivant = (): void => setIndex((i) => Math.min(ETAPES.length - 1, i + 1))

  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'ArrowLeft') precedent()
      if (e.key === 'ArrowRight') suivant()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className="ecran">
      <TopBar titre="Gestes du pavé tactile" chevron={false} />
      <div className="tuto">
        <div className="compteur">{index + 1}/{ETAPES.length}</div>
        <div className="scene">
          <LunettesPave geste={etape.geste} />
        </div>
        <div className="sous-titre">{etape.sousTitre}</div>
        <h2>{etape.h2}</h2>
        <TutoNav index={index} total={ETAPES.length} onPrev={precedent} onNext={suivant} />
      </div>
    </div>
  )
}
