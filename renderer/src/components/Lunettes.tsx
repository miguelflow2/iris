import React, { useId } from 'react'

/** Illustrations vectorielles des lunettes VELA, blanc nacré sur fond sombre (comme les maquettes).
 *  Résolution indépendante : pas de photo à fond blanc ou noir à masquer. */

function Nacre({ id }: { id: string }): JSX.Element {
  return (
    <defs>
      <linearGradient id={id} x1="0" y1="0" x2="1" y2="0.3">
        <stop offset="0" stopColor="#ffffff" />
        <stop offset="0.35" stopColor="#f2f7ff" />
        <stop offset="0.6" stopColor="#ffe9f8" />
        <stop offset="1" stopColor="#d9dde6" />
      </linearGradient>
    </defs>
  )
}

/** Vue de face (carte appareil). */
export function LunettesFace(props: React.SVGProps<SVGSVGElement>): JSX.Element {
  const id = useId()
  return (
    <svg viewBox="0 0 240 110" aria-hidden="true" {...props}>
      <Nacre id={id} />
      {/* branches vers l'arrière */}
      <path d="M18 34c-6 0-12 4-10 10l12 2Z" fill={`url(#${id})`} />
      <path d="M222 34c6 0 12 4 10 10l-12 2Z" fill={`url(#${id})`} />
      <path d="M18 38h-6l-8 46h5l9-39Z" fill={`url(#${id})`} opacity="0.9" />
      <path d="M222 38h6l8 46h-5l-9-39Z" fill={`url(#${id})`} opacity="0.9" />
      {/* monture : deux verres et le pont */}
      <path
        d="M20 30h84c10 0 16 6 16 14 0 2 0 4-1 6h2c-1-2-1-4-1-6 0-8 6-14 16-14h84c8 0 14 6 12 14l-6 34c-2 12-10 20-24 20h-42c-14 0-22-8-24-20l-4-22c-1-5-4-7-8-7s-7 2-8 7l-4 22c-2 12-10 20-24 20H38c-14 0-22-8-24-20L8 44c-2-8 4-14 12-14Z"
        fill={`url(#${id})`}
      />
      {/* verres (teintés, légèrement transparents) */}
      <path d="M22 42h78c6 0 9 4 8 10l-5 28c-1 8-7 13-16 13H42c-9 0-15-5-16-13l-5-28c-1-6 2-10 8-10Z" fill="#1b1b1d" opacity="0.92" />
      <path d="M140 42h78c6 0 9 4 8 10l-5 28c-1 8-7 13-16 13h-45c-9 0-15-5-16-13l-5-28c-1-6 2-10 8-10Z" fill="#1b1b1d" opacity="0.92" />
      {/* reflets */}
      <path d="M30 48h30" stroke="#ffffff" strokeOpacity="0.25" strokeWidth="3" strokeLinecap="round" />
      <path d="M148 48h30" stroke="#ffffff" strokeOpacity="0.25" strokeWidth="3" strokeLinecap="round" />
      {/* caméra et voyant sur les coins */}
      <circle cx="30" cy="38" r="2.6" fill="#1b1b1d" />
      <circle cx="210" cy="38" r="2.6" fill="#1b1b1d" />
    </svg>
  )
}

export type MarqueurLunettes = 'aucun' | 'bouton-avant' | 'bouton-arriere'

/** Vue de profil (tutoriels caméra / vidéo / audio) : la branche gauche avec ses deux boutons,
 *  le verre à droite. `marqueur` place la flèche bleue sur le bouton concerné. */
export function LunettesProfil({ marqueur = 'aucun', ...props }: React.SVGProps<SVGSVGElement> & { marqueur?: MarqueurLunettes }): JSX.Element {
  const id = useId()
  const flecheX = marqueur === 'bouton-avant' ? 118 : 74
  return (
    <svg viewBox="0 0 420 300" aria-hidden="true" {...props}>
      <Nacre id={id} />
      {/* branche droite (arrière-plan) */}
      <path d="M186 76c40-30 90-36 130-30 22 3 30 12 30 24v20c-20-8-60-12-100-8-30 3-52 12-60 20Z" fill={`url(#${id})`} opacity="0.85" />
      {/* branche gauche, longue, vue de côté */}
      <path d="M0 122c60-8 140-14 220-12v40c-80 4-160 12-220 20Z" fill={`url(#${id})`} />
      {/* charnière et monture avant */}
      <path
        d="M214 106c40-4 90-2 140 8 30 6 44 20 46 42l6 40c4 30-16 60-58 68-40 8-84-6-100-40-8-16-14-40-20-64-4-16-14-24-14-54Z"
        fill={`url(#${id})`}
      />
      {/* verre */}
      <path d="M270 150c40-4 74 0 96 10 16 8 22 22 20 40-4 30-30 48-64 48-30 0-50-14-58-38-6-18-10-38 6-60Z" fill="#1b1b1d" />
      {/* lentille de la caméra sur la face */}
      <ellipse cx="246" cy="128" rx="14" ry="18" fill="#1b1b1d" />
      <ellipse cx="243" cy="125" rx="5" ry="6" fill="#3a3a3c" />
      {/* les deux boutons sur le dessus de la branche */}
      <rect x="60" y="106" width="30" height="10" rx="4" fill="#3b8cff" transform="rotate(-3 75 111)" />
      <rect x="104" y="104" width="30" height="10" rx="4" fill="#3b8cff" transform="rotate(-3 119 109)" />
      {marqueur !== 'aucun' ? (
        <g stroke="#3b8cff" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" fill="none">
          <path d={`M${flecheX} 48v40`} />
          <path d={`M${flecheX - 14} 74l14 16 14-16`} />
        </g>
      ) : null}
    </svg>
  )
}

export type GestePave = 'double' | 'triple' | 'long'

/** Vue de dessus des deux branches (tutoriel du pavé tactile) : un point bleu sur la branche
 *  droite marque le geste ; le halo grandit avec l'intensité (double / triple / appui long). */
export function LunettesPave({ geste = 'double', ...props }: React.SVGProps<SVGSVGElement> & { geste?: GestePave }): JSX.Element {
  const id = useId()
  const rayon = geste === 'double' ? 0 : geste === 'triple' ? 16 : 22
  return (
    <svg viewBox="0 0 420 260" aria-hidden="true" {...props}>
      <Nacre id={id} />
      {/* branche droite (celle du pavé tactile), légèrement inclinée */}
      <path d="M0 132 8 112c70-20 200-40 330-46 30-2 60-2 82 4v54c-40 6-120 10-200 20-90 12-160 24-220 34Z" fill={`url(#${id})`} />
      <rect x="352" y="60" width="40" height="8" rx="4" fill={`url(#${id})`} />
      {/* branche gauche, plus bas, avec l'embout recourbé */}
      <path d="M150 232c30-30 70-46 130-52 50-6 100-4 140-10v30c-40 6-90 8-130 12-40 4-80 14-110 30-8 4-16 10-30 6Z" fill={`url(#${id})`} opacity="0.9" />
      {/* geste : point + halo */}
      {rayon > 0 ? <circle cx="240" cy="110" r={rayon} fill="#3b8cff" opacity="0.35" /> : null}
      {geste === 'long' ? <circle cx="240" cy="110" r="30" fill="#3b8cff" opacity="0.18" /> : null}
      <circle cx="240" cy="110" r="10" fill="#3b8cff" />
    </svg>
  )
}

/** Petit pictogramme « lunettes » en trait, pour le logo de l'accueil. */
export function LogoLunettes(props: React.SVGProps<SVGSVGElement>): JSX.Element {
  return (
    <svg viewBox="0 0 120 54" fill="none" stroke="currentColor" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      <path d="M6 22 14 8h92l8 14" />
      <path d="M6 24c0-6 4-9 10-9h22c8 0 12 4 12 12v6c0 8-6 12-14 12H20c-8 0-14-5-14-13v-8Z" />
      <path d="M70 24c0-6 4-9 10-9h22c8 0 12 4 12 12v6c0 8-6 12-14 12H84c-8 0-14-5-14-13v-8Z" />
      <path d="M50 29h20" />
    </svg>
  )
}
