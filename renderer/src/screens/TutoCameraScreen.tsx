import React, { useEffect, useState } from 'react'
import { useStore } from '../lib/store'
import { BtnIcone, TopBar, TutoNav } from '../components/ui'
import { IcoEngrenage } from '../components/icons'
import { LunettesProfil, type MarqueurLunettes } from '../components/Lunettes'

/* =========================================================================
   Tutoriel « Caméra / Vidéo / Audio » (maquettes IMG_0700, 0705 à 0708) :
   cinq étapes dans un seul écran, la vue de profil des lunettes avec la flèche
   sur le bon bouton, et une pastille rouge d'enregistrement dont le chrono
   avance vraiment tant que l'étape est affichée.
   ========================================================================= */

interface Etape {
  titre: string
  sousTitre: string
  rouge?: boolean
  h2: string
  desc?: string
  marqueur: MarqueurLunettes
  /** valeur de départ du chrono (secondes) ; absent = pas de pastille */
  chip?: number
  /** engrenage à droite de la barre (réglages d'enregistrement, pas encore disponibles) */
  engrenage?: boolean
}

const ETAPES: Etape[] = [
  {
    titre: 'Caméra',
    sousTitre: 'Prendre une photo',
    h2: 'Un clic sur le bouton avant',
    desc: 'Quand une photo est prise, le voyant à l’extérieur des lunettes clignote.',
    marqueur: 'bouton-avant'
  },
  {
    titre: 'Vidéo',
    chip: 1,
    sousTitre: 'Démarrer l’enregistrement',
    h2: 'Deux clics pour démarrer',
    desc: 'Pendant l’enregistrement vidéo, le voyant reste allumé.',
    marqueur: 'bouton-avant'
  },
  {
    titre: 'Vidéo',
    engrenage: true,
    chip: 5,
    sousTitre: 'Arrêter l’enregistrement',
    rouge: true,
    h2: 'Un clic pour terminer',
    marqueur: 'bouton-avant'
  },
  {
    titre: 'Audio',
    engrenage: true,
    chip: 1,
    sousTitre: 'Démarrer l’enregistrement',
    h2: 'Deux clics sur le bouton arrière droit',
    desc: 'Pendant l’enregistrement audio, le voyant respire et clignote.',
    marqueur: 'bouton-arriere'
  },
  {
    titre: 'Audio',
    chip: 5,
    sousTitre: 'Arrêter l’enregistrement',
    rouge: true,
    h2: 'Un clic sur le bouton arrière droit pendant l’enregistrement',
    marqueur: 'bouton-arriere'
  }
]

function formatChrono(secondes: number): string {
  const s = Math.max(0, Math.floor(secondes))
  const mm = String(Math.floor(s / 60)).padStart(2, '0')
  const ss = String(s % 60).padStart(2, '0')
  return `${mm}:${ss}`
}

function indexDepart(params?: Record<string, any>): number {
  const n = Number(params?.etape)
  return Number.isFinite(n) ? Math.min(ETAPES.length - 1, Math.max(0, Math.floor(n))) : 0
}

export function TutoCameraScreen({ params }: { params?: Record<string, any> }): JSX.Element {
  const { toast } = useStore()
  const [index, setIndex] = useState(() => indexDepart(params))
  const etape = ETAPES[index]
  const [secondes, setSecondes] = useState(etape.chip ?? 0)

  // Le chrono repart à la valeur de départ de l'étape et avance d'une seconde tant qu'elle est affichée.
  useEffect(() => {
    const depart = ETAPES[index].chip
    if (depart === undefined) return
    setSecondes(depart)
    const t = window.setInterval(() => setSecondes((s) => s + 1), 1000)
    return () => window.clearInterval(t)
  }, [index])

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
      <TopBar
        titre={etape.titre}
        chevron={false}
        droite={
          etape.engrenage ? (
            <BtnIcone aria-label="Réglages d’enregistrement" title="À venir" onClick={() => toast('Pas encore disponible dans cette version.', 'info')}>
              <IcoEngrenage />
            </BtnIcone>
          ) : undefined
        }
      />
      <div className="tuto">
        <div className="compteur">{index + 1}/{ETAPES.length}</div>
        <div className="scene">
          {etape.chip !== undefined ? (
            <div className="chip-rec" aria-label={`Enregistrement ${formatChrono(secondes)}`}>
              <i />
              {formatChrono(secondes)}
            </div>
          ) : null}
          <LunettesProfil marqueur={etape.marqueur} />
        </div>
        <div className={'sous-titre' + (etape.rouge ? ' rouge' : '')}>{etape.sousTitre}</div>
        <h2>{etape.h2}</h2>
        {etape.desc ? <p className="desc">{etape.desc}</p> : null}
        <TutoNav index={index} total={ETAPES.length} onPrev={precedent} onNext={suivant} />
      </div>
    </div>
  )
}
