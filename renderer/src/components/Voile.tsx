/**
 * Le logo VELA : une voile.
 *
 * Vectorisé depuis le dessin d'origine (courbe de Bézier ajustée à 0,2 % près sur la
 * grand-voile). Deux variantes officielles, et une seule règle : le logo doit rester
 * lisible sur son fond.
 *
 *   - `sombre` : grand-voile encre sur fond clair. Variante principale.
 *   - `clair`  : grand-voile crème sur fond sombre. C'est celle qu'utilise l'application,
 *                dont le fond est sombre — la variante principale y disparaîtrait.
 *
 * Le foc reste terracotta dans les deux cas : c'est lui qui porte la couleur de la marque.
 */
import React from 'react'

export const VELA_COULEURS = {
  creme: '#F8F0E7',
  encre: '#1B140E',
  terracotta: '#B36B3B'
} as const

type Props = {
  /** Hauteur en pixels. La largeur suit le rapport du dessin (0,759). */
  taille?: number
  /** `clair` pour un fond sombre, `sombre` pour un fond clair. */
  variante?: 'clair' | 'sombre'
  /** Anime le tracé à l'apparition, comme une voile qui se hisse. */
  anime?: boolean
  className?: string
  titre?: string
}

export function Voile({ taille = 32, variante = 'clair', anime = false, className, titre }: Props): JSX.Element {
  const grandVoile = variante === 'clair' ? VELA_COULEURS.creme : VELA_COULEURS.encre
  const largeur = Math.round(taille * (120 / 158))

  return (
    <svg
      width={largeur}
      height={taille}
      viewBox="0 0 120 158"
      className={className}
      role={titre ? 'img' : undefined}
      aria-label={titre}
      aria-hidden={titre ? undefined : true}
      style={anime ? { ['--voile-duree' as string]: '900ms' } : undefined}
    >
      {/* Le foc : petite voile avant, en terracotta. */}
      <path
        d="M 36.5 46.3 L 36.6 158 L 0 158 Z"
        fill={VELA_COULEURS.terracotta}
        className={anime ? 'voile-foc' : undefined}
      />
      {/* La grand-voile : mât vertical à gauche, bord droit bombé, pied légèrement creusé. */}
      <path
        d="M 41.4 0 C 93.3 52.6 115 105.2 120 157.8 Q 80.4 149.2 41.4 158 Z"
        fill={grandVoile}
        className={anime ? 'voile-grand' : undefined}
      />
    </svg>
  )
}
