import React, { useMemo } from 'react'

/** Fond « cosmos » de l'accueil (état non connecté) : champ d'étoiles, arc lumineux qui
 *  descend en croissant, et lignes ondulées sombres en bas. Étoiles déterministes (même
 *  ciel à chaque ouverture), sans image externe (la CSP l'interdit). */
export function CosmosFond({ className }: { className?: string }): JSX.Element {
  const etoiles = useMemo(() => {
    // générateur pseudo-aléatoire simple et reproductible
    let s = 20260912
    const rnd = (): number => {
      s = (s * 1664525 + 1013904223) % 4294967296
      return s / 4294967296
    }
    const liste: { x: number; y: number; r: number; o: number }[] = []
    for (let i = 0; i < 260; i++) {
      const x = rnd() * 600
      const y = rnd() * 720
      // plus dense le long de l'arc (diagonale haut-gauche → bas-droite), comme la maquette
      const d = Math.abs(y - (0.65 * x + 120))
      const densite = d < 70 ? 1 : d < 160 ? 0.55 : 0.25
      if (rnd() > densite) continue
      liste.push({ x, y, r: rnd() < 0.85 ? 0.7 + rnd() * 0.8 : 1.4 + rnd() * 1.2, o: 0.35 + rnd() * 0.65 })
    }
    return liste
  }, [])

  return (
    <svg className={className} viewBox="0 0 600 720" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <defs>
        <radialGradient id="cosmos-lueur" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#ffffff" stopOpacity="0.55" />
          <stop offset="0.5" stopColor="#c8d4ff" stopOpacity="0.18" />
          <stop offset="1" stopColor="#000" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="cosmos-fond" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#141416" />
          <stop offset="0.55" stopColor="#0f0f11" />
          <stop offset="1" stopColor="#1b1b1d" />
        </linearGradient>
        <filter id="cosmos-flou" x="-40%" y="-40%" width="180%" height="180%">
          <feGaussianBlur stdDeviation="14" />
        </filter>
        <filter id="cosmos-flou-fin" x="-40%" y="-40%" width="180%" height="180%">
          <feGaussianBlur stdDeviation="3" />
        </filter>
      </defs>
      <rect width="600" height="720" fill="url(#cosmos-fond)" />
      {/* halo diffus derrière l'arc */}
      <ellipse cx="150" cy="330" rx="330" ry="260" fill="url(#cosmos-lueur)" opacity="0.55" filter="url(#cosmos-flou)" />
      {/* l'arc lumineux : un croissant qui va du haut-gauche vers le bas-centre */}
      <path d="M-40 60C-10 220 60 380 210 450c90 42 200 36 320 0" fill="none" stroke="#ffffff" strokeWidth="2.5" opacity="0.7" filter="url(#cosmos-flou-fin)" />
      <path d="M-40 60C-10 220 60 380 210 450c90 42 200 36 320 0" fill="none" stroke="#ffffff" strokeWidth="14" opacity="0.10" filter="url(#cosmos-flou)" />
      {/* étoiles */}
      <g fill="#ffffff">
        {etoiles.map((e, i) => (
          <circle key={i} cx={e.x} cy={e.y} r={e.r} opacity={e.o} />
        ))}
      </g>
      {/* quelques étoiles plus vives */}
      <circle cx="108" cy="352" r="3.2" fill="#fff" />
      <circle cx="108" cy="352" r="9" fill="#fff" opacity="0.18" />
      <circle cx="252" cy="465" r="2.4" fill="#fff" />
      <circle cx="540" cy="540" r="2" fill="#fff" />
      <circle cx="470" cy="450" r="1.8" fill="#fff" />
      {/* les lignes ondulées du bas, sombres et fines */}
      <g fill="none" stroke="#ffffff" strokeWidth="1">
        {Array.from({ length: 16 }, (_, i) => (
          <path
            key={i}
            d={`M-20 ${560 + i * 11}C120 ${520 + i * 12} 220 ${640 + i * 6} 330 ${600 + i * 9}S520 ${560 + i * 12} 640 ${600 + i * 8}`}
            opacity={0.05 + (i % 4) * 0.02}
          />
        ))}
      </g>
    </svg>
  )
}
