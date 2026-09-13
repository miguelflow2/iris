import React, { useId } from 'react'

/** Icônes SVG inline (trait 1.8, style système). `plein` = variante remplie (onglet actif). */
type P = React.SVGProps<SVGSVGElement> & { plein?: boolean }

function base(props: P, children: React.ReactNode, fill = false): JSX.Element {
  const { plein: _p, ...rest } = props
  return (
    <svg
      viewBox="0 0 24 24"
      width={24}
      height={24}
      fill={fill ? 'currentColor' : 'none'}
      stroke={fill ? 'none' : 'currentColor'}
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  )
}

/* ---------------------------------------------------------------- onglets */
export const IcoMaison = (p: P): JSX.Element =>
  p.plein
    ? base(p, <path d="M12 2.6 2.8 10.2V21a1 1 0 0 0 1 1h5.4v-6.2h5.6V22h5.4a1 1 0 0 0 1-1V10.2L12 2.6Z" />, true)
    : base(p, <><path d="M3.5 10.5 12 3.5l8.5 7" /><path d="M5.5 9v12h13V9" /><path d="M9.5 21v-5.5h5V21" /></>)

export const IcoRobot = (p: P): JSX.Element =>
  p.plein
    ? base(
        p,
        <>
          <path d="M12 2.2a1 1 0 0 1 1 1V4h2.6A3.4 3.4 0 0 1 19 7.4v2.2a3.4 3.4 0 0 1-3.4 3.4H8.4A3.4 3.4 0 0 1 5 9.6V7.4A3.4 3.4 0 0 1 8.4 4H11V3.2a1 1 0 0 1 1-1Zm-2.6 5.3a1.2 1.2 0 1 0 0 2.4 1.2 1.2 0 0 0 0-2.4Zm5.2 0a1.2 1.2 0 1 0 0 2.4 1.2 1.2 0 0 0 0-2.4Z" />
          <path d="M4 21.5a8 8 0 0 1 16 0H4Z" />
        </>,
        true
      )
    : base(
        p,
        <>
          <rect x="5.5" y="4.5" width="13" height="8" rx="3" />
          <path d="M12 2.5v2" />
          <circle cx="9.5" cy="8.5" r="1" fill="currentColor" stroke="none" />
          <circle cx="14.5" cy="8.5" r="1" fill="currentColor" stroke="none" />
          <path d="M4.5 21.5a7.5 7.5 0 0 1 15 0" />
        </>
      )

export const IcoAlbum = (p: P): JSX.Element =>
  p.plein
    ? base(p, <path d="M4 3.5h16A1.5 1.5 0 0 1 21.5 5v14a1.5 1.5 0 0 1-1.5 1.5H4A1.5 1.5 0 0 1 2.5 19V5A1.5 1.5 0 0 1 4 3.5Zm4.6 5.2-4.1 6.6h15l-4.6-6.1-3 3.4-3.3-3.9Zm7.4-2.2a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3Z" />, true)
    : base(p, <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="m4 17 5-6 4 4.5 3-3.5 4 5" /><circle cx="16" cy="9" r="1.4" fill="currentColor" stroke="none" /></>)

export const IcoProfil = (p: P): JSX.Element =>
  p.plein
    ? base(p, <><circle cx="12" cy="8" r="4.6" /><path d="M6 21.5c0-3.5 1.6-5 3.6-5.3l2.4 2.6 2.4-2.6c2 .3 3.6 1.8 3.6 5.3H6Z" /></>, true)
    : base(p, <><circle cx="12" cy="8" r="4" /><path d="M6.5 21c0-3.2 1.5-4.6 3.4-4.9L12 18.5l2.1-2.4c1.9.3 3.4 1.7 3.4 4.9" /></>)

/* ---------------------------------------------------------------- actions */
export const IcoCamera = (p: P): JSX.Element => base(p, <><path d="M4 8.5h3l1.5-2.5h7L17 8.5h3v10H4v-10Z" /><circle cx="12" cy="13.3" r="3.2" /></>)
export const IcoVideo = (p: P): JSX.Element => base(p, <><rect x="3" y="7" width="13" height="10" rx="2" /><path d="m16 10.5 5-2.5v8l-5-2.5" /></>)
export const IcoMicro = (p: P): JSX.Element => base(p, <><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M6 11a6 6 0 0 0 12 0" /><path d="M12 17v4M9 21h6" /></>)
export const IcoImageIA = (p: P): JSX.Element => base(p, <><rect x="3" y="5" width="15" height="14" rx="2" /><path d="m4 17 4-5 3.5 3.5 2.5-2.5 3.5 4" /><path d="M19.5 3v4M17.5 5h4" /></>)
export const IcoMusique = (p: P): JSX.Element => base(p, <><path d="M9 18V6l10-2v12" /><circle cx="6.5" cy="18" r="2.5" /><circle cx="16.5" cy="16" r="2.5" /></>)
export const IcoEngrenage = (p: P): JSX.Element => base(p, <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" /></>)
export const IcoChevronD = (p: P): JSX.Element => base(p, <path d="m9 6 6 6-6 6" />)
export const IcoChevronG = (p: P): JSX.Element => base(p, <path d="m15 6-6 6 6 6" />)
export const IcoChevronBas = (p: P): JSX.Element => base(p, <path d="m6 9 6 6 6-6" />)
export const IcoRetour = (p: P): JSX.Element => base(p, <><path d="M19 12H5" /><path d="m11 6-6 6 6 6" /></>)
export const IcoFermer = (p: P): JSX.Element => base(p, <path d="M6 6l12 12M18 6 6 18" />)
export const IcoCoche = (p: P): JSX.Element => base(p, <path d="m5 12.5 4.5 4.5L19 7.5" />)
export const IcoPlus = (p: P): JSX.Element => base(p, <path d="M12 5v14M5 12h14" />)
export const IcoRecherche = (p: P): JSX.Element => base(p, <><circle cx="11" cy="11" r="6.5" /><path d="m16 16 4.5 4.5" /></>)
export const IcoTraduire = (p: P): JSX.Element => base(p, <><rect x="3" y="3" width="18" height="18" rx="3" /><path d="m8 16 3.2-8h1.6L16 16" /><path d="M9.3 13h5.4" /></>)
export const IcoNouveauChat = (p: P): JSX.Element => base(p, <><path d="M20 12.5V7a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v9.5l3.5-2.5H12" /><path d="M18 14v6M15 17h6" /></>)
export const IcoListeChat = (p: P): JSX.Element => base(p, <><path d="M4 5.5h16v10H9l-4 3.5v-3.5H4v-10Z" /><path d="M8 9h8M8 12h5" /></>)
export const IcoHorloge = (p: P): JSX.Element => base(p, <><circle cx="12" cy="13" r="8" /><path d="M12 8.5V13l3 2" /><path d="M9 2.5h6" /></>)
export const IcoHautParleur = (p: P): JSX.Element => base(p, <><path d="M4 9.5v5h3.5L12 18.5v-13L7.5 9.5H4Z" /><path d="M15.5 9a4.5 4.5 0 0 1 0 6" /><path d="M18 6.5a8 8 0 0 1 0 11" /></>)
export const IcoTelecharger = (p: P): JSX.Element => base(p, <><path d="M12 4v11" /><path d="m7.5 10.5 4.5 4.5 4.5-4.5" /><path d="M5 19h14" /></>)
export const IcoBaguette = (p: P): JSX.Element => base(p, <><path d="m4 20 10-10" /><path d="m14 10 2-2" /><path d="M17 3v3M15.5 4.5h3" /><path d="M20 9v2M19 10h2" /><path d="M9 4v2M8 5h2" /></>)
export const IcoOreille = (p: P): JSX.Element => base(p, <><path d="M6 10a6 6 0 0 1 12 0c0 3-2 4-2.5 6S14 21 11 21" /><path d="M9 10a3 3 0 0 1 6 0c0 1.6-1 2-1.5 3" /></>)
export const IcoTelephoneEcran = (p: P): JSX.Element => base(p, <><rect x="6" y="2.5" width="12" height="19" rx="2.5" /><path d="M10.5 18.5h3" /></>)
export const IcoReunion = (p: P): JSX.Element => base(p, <><path d="M3 5.5h12v8H8l-3.5 3v-3H3v-8Z" /><path d="M15 9.5h6v7h-1.5v2.5l-3-2.5H12" /></>)
export const IcoUtilisateur = (p: P): JSX.Element => base(p, <><circle cx="12" cy="8" r="3.5" /><path d="M6 20a6 6 0 0 1 12 0" /></>)
export const IcoCommentaire = (p: P): JSX.Element => base(p, <><path d="M4 5h11v4M4 5v14h13v-5" /><path d="m19.5 4.5-6 6-.5 2.5 2.5-.5 6-6-2-2Z" /><path d="M7 9h5M7 12.5h4" /></>)
export const IcoQuestion = (p: P): JSX.Element => base(p, <><circle cx="12" cy="12" r="9" /><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .8-1 1.7" /><circle cx="12" cy="17" r="0.8" fill="currentColor" stroke="none" /></>)
export const IcoInfo = (p: P): JSX.Element => base(p, <><circle cx="12" cy="12" r="9" /><path d="M12 11v6" /><circle cx="12" cy="7.8" r="0.9" fill="currentColor" stroke="none" /></>)
export const IcoOnde = (p: P): JSX.Element => base(p, <><path d="M8 9.5a4 4 0 0 1 0 5" /><path d="M11.5 7a8 8 0 0 1 0 10" /><path d="M15 4.5a12 12 0 0 1 0 15" /></>)
export const IcoEtoile = (p: P): JSX.Element =>
  base(p, <path d="m12 3 2.8 5.8 6.2.9-4.5 4.4 1.1 6.3L12 17.4l-5.6 3 1.1-6.3L3 9.7l6.2-.9L12 3Z" />, Boolean(p.plein))
export const IcoCapture = (p: P): JSX.Element => base(p, <><path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3" /><rect x="8" y="9" width="8" height="6" rx="1" /></>)
export const IcoImage = (p: P): JSX.Element => base(p, <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="m4 17 5-6 4 4.5 3-3.5 4 5" /><circle cx="16" cy="9" r="1.4" fill="currentColor" stroke="none" /></>)
export const IcoEnvoyer = (p: P): JSX.Element => base(p, <><path d="M12 19V5" /><path d="m6 11 6-6 6 6" /></>)
export const IcoStop = (p: P): JSX.Element => base(p, <rect x="6" y="6" width="12" height="12" rx="2" />, true)
export const IcoPoubelle = (p: P): JSX.Element => base(p, <><path d="M4 7h16" /><path d="M9 7V4h6v3" /><path d="M6 7l1 13h10l1-13" /></>)
export const IcoCrayon = (p: P): JSX.Element => base(p, <><path d="m4 20 4-1 10-10-3-3L5 16l-1 4Z" /><path d="m13 8 3 3" /></>)
export const IcoMemoire = (p: P): JSX.Element => base(p, <><path d="M6 3.5h12v17l-6-4-6 4v-17Z" /></>)
export const IcoRoutine = (p: P): JSX.Element => base(p, <><path d="M20 12a8 8 0 0 1-14.5 4.6" /><path d="M4 12a8 8 0 0 1 14.5-4.6" /><path d="M18.5 3.5v4h-4M5.5 20.5v-4h4" /></>)
export const IcoTache = (p: P): JSX.Element => base(p, <><rect x="4" y="4" width="16" height="16" rx="3" /><path d="m8 12 3 3 5-6" /></>)
export const IcoOeil = (p: P): JSX.Element => base(p, <><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z" /><circle cx="12" cy="12" r="3" /></>)
export const IcoBouclier = (p: P): JSX.Element => base(p, <><path d="M12 3 4.5 6v6c0 4.5 3.2 7.7 7.5 9 4.3-1.3 7.5-4.5 7.5-9V6L12 3Z" /><path d="m9 12 2 2 4-4" /></>)
export const IcoCarte = (p: P): JSX.Element => base(p, <><rect x="3" y="6" width="18" height="12" rx="2.5" /><path d="M3 10h18" /><path d="M7 14.5h4" /></>)
export const IcoCerveau = (p: P): JSX.Element => base(p, <><path d="M9.5 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 5.5 1V5a3 3 0 0 0-2.5-1Z" /><path d="M14.5 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-5.5 1V5a3 3 0 0 1 2.5-1Z" /></>)
export const IcoReglages = (p: P): JSX.Element => base(p, <><path d="M4 7h10M18 7h2M4 12h3M11 12h9M4 17h12M20 17h0" /><circle cx="16" cy="7" r="2" /><circle cx="9" cy="12" r="2" /><circle cx="18" cy="17" r="2" /></>)
export const IcoCourriel = (p: P): JSX.Element => base(p, <><rect x="3" y="5" width="18" height="14" rx="2.5" /><path d="m3.5 7 8.5 6 8.5-6" /></>)
export const IcoTelephone = (p: P): JSX.Element => base(p, <path d="M6.5 3.5h3l1.5 4-2 1.5a10 10 0 0 0 6 6l1.5-2 4 1.5v3a2 2 0 0 1-2 2A16 16 0 0 1 4.5 5.5a2 2 0 0 1 2-2Z" />)
export const IcoGlobe = (p: P): JSX.Element => base(p, <><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" /></>)
export const IcoLien = (p: P): JSX.Element => base(p, <><path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1" /><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" /></>)
export const IcoCopier = (p: P): JSX.Element => base(p, <><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M15 9V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h3" /></>)
export const IcoActualiser = (p: P): JSX.Element => base(p, <><path d="M20 12a8 8 0 1 1-2.3-5.7" /><path d="M20 4v5h-5" /></>)
export const IcoBluetooth = (p: P): JSX.Element => base(p, <path d="m6.5 7.5 11 9-5.5 4.5V3l5.5 4.5-11 9" />)
export const IcoLunettes = (p: P): JSX.Element =>
  base(p, <><path d="M2.5 11.5 5 7h14l2.5 4.5" /><rect x="2.5" y="11" width="8" height="6" rx="3" /><rect x="13.5" y="11" width="8" height="6" rx="3" /><path d="M10.5 13.5h3" /></>)
export const IcoPause = (p: P): JSX.Element => base(p, <><rect x="6" y="5" width="4" height="14" rx="1" /><rect x="14" y="5" width="4" height="14" rx="1" /></>, true)
export const IcoLecture = (p: P): JSX.Element => base(p, <path d="M7 4.5v15l12-7.5-12-7.5Z" />, true)
export const IcoMicroBarre = (p: P): JSX.Element => base(p, <><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M6 11a6 6 0 0 0 12 0" /><path d="M12 17v4M9 21h6" /><path d="m4 4 16 16" /></>)
export const IcoAvertissement = (p: P): JSX.Element => base(p, <><path d="M12 3.5 2.5 20h19L12 3.5Z" /><path d="M12 10v4.5" /><circle cx="12" cy="17.2" r="0.8" fill="currentColor" stroke="none" /></>)
export const IcoDossier = (p: P): JSX.Element => base(p, <path d="M3 6.5A1.5 1.5 0 0 1 4.5 5h5l2 2h8A1.5 1.5 0 0 1 21 8.5v10a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5v-12Z" />)
export const IcoJournal = (p: P): JSX.Element => base(p, <><path d="M6 3.5h9l4 4v13H6v-17Z" /><path d="M15 3.5v4h4" /><path d="M9 12h6M9 15.5h6" /></>)

/* ---------------------------------------------------------------- batterie */
export function IcoBatterie({ niveau, charge, ...rest }: P & { niveau?: number | null; charge?: boolean }): JSX.Element {
  const n = typeof niveau === 'number' ? Math.max(0, Math.min(100, niveau)) : null
  const largeur = n === null ? 0 : (14 * n) / 100
  const couleur = n === null ? 'currentColor' : n <= 20 ? '#ff3b30' : '#30d158'
  return (
    <svg viewBox="0 0 28 16" width={30} height={17} aria-hidden="true" {...rest}>
      <rect x="1" y="2" width="22" height="12" rx="3" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <rect x="24" y="5.5" width="3" height="5" rx="1" fill="currentColor" />
      {n !== null ? <rect x="3.5" y="4.5" width={largeur} height="7" rx="1.4" fill={couleur} /> : null}
      {charge ? <path d="m13.5 4-3 4.5h3l-1 3.5 3-4.5h-3l1-3.5Z" fill="#fff" /> : null}
    </svg>
  )
}

/* ---------------------------------------------------------------- icônes en dégradé holographique
   (robot de l'assistant, album vide, minuteur vide). Le dégradé porte un id unique par instance. */
function Degrade({ id }: { id: string }): JSX.Element {
  return (
    <defs>
      <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stopColor="#f7bfff" />
        <stop offset="0.5" stopColor="#c8c8ff" />
        <stop offset="1" stopColor="#97f2ff" />
      </linearGradient>
    </defs>
  )
}

export function IcoRobotDegrade(props: React.SVGProps<SVGSVGElement>): JSX.Element {
  const id = useId()
  return (
    <svg viewBox="0 0 100 120" width={100} height={120} aria-hidden="true" {...props}>
      <Degrade id={id} />
      <rect x="47" y="4" width="6" height="10" rx="3" fill={`url(#${id})`} />
      <rect x="12" y="12" width="76" height="52" rx="20" fill={`url(#${id})`} />
      <circle cx="36" cy="38" r="7.5" fill="#1b1b1d" />
      <circle cx="64" cy="38" r="7.5" fill="#1b1b1d" />
      <path d="M8 118a42 42 0 0 1 84 0Z" fill={`url(#${id})`} />
    </svg>
  )
}

export function IcoAlbumDegrade(props: React.SVGProps<SVGSVGElement>): JSX.Element {
  const id = useId()
  return (
    <svg viewBox="0 0 120 100" width={120} height={100} aria-hidden="true" {...props}>
      <Degrade id={id} />
      <rect x="20" y="4" width="96" height="70" rx="12" fill={`url(#${id})`} opacity="0.9" />
      <rect x="4" y="20" width="96" height="72" rx="12" fill={`url(#${id})`} stroke="#1b1b1d" strokeWidth="3" />
      <circle cx="30" cy="42" r="8" fill="#1b1b1d" />
      <path d="M12 84 40 56l18 18 14-14 22 24Z" fill="#1b1b1d" />
    </svg>
  )
}

export function IcoHorlogeDegrade(props: React.SVGProps<SVGSVGElement>): JSX.Element {
  const id = useId()
  return (
    <svg viewBox="0 0 120 130" width={120} height={130} aria-hidden="true" {...props}>
      <Degrade id={id} />
      <rect x="44" y="2" width="32" height="8" rx="4" fill={`url(#${id})`} />
      <circle cx="60" cy="72" r="54" fill={`url(#${id})`} />
      <path d="M60 40v34h24" stroke="#1b1b1d" strokeWidth="9" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </svg>
  )
}

/** Petite plateforme isométrique bleue avec un glyphe dessus (cartes de l'accueil). */
export function IcoPlateforme({ glyphe, ...props }: React.SVGProps<SVGSVGElement> & { glyphe: 'orbe' | 'nuage' | 'baguette' }): JSX.Element {
  const id = useId()
  return (
    <svg viewBox="0 0 130 110" width={130} height={110} aria-hidden="true" {...props}>
      <defs>
        <linearGradient id={`${id}a`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#5b7cff" />
          <stop offset="1" stopColor="#2a45b8" />
        </linearGradient>
        <linearGradient id={`${id}b`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#3b56d6" />
          <stop offset="1" stopColor="#1e2f80" />
        </linearGradient>
        <radialGradient id={`${id}c`} cx="0.4" cy="0.35" r="0.7">
          <stop offset="0" stopColor="#ffffff" />
          <stop offset="0.5" stopColor="#bfd4ff" />
          <stop offset="1" stopColor="#6f8cff" />
        </radialGradient>
      </defs>
      {/* socle */}
      <path d="M65 58 118 80 65 102 12 80Z" fill={`url(#${id}a)`} />
      <path d="M12 80v8l53 22v-8Z" fill={`url(#${id}b)`} />
      <path d="M118 80v8l-53 22v-8Z" fill="#1a2a70" />
      <path d="M65 66 98 80 65 94 32 80Z" fill="#1c2f8a" opacity="0.8" />
      {glyphe === 'orbe' ? (
        <>
          <circle cx="65" cy="46" r="22" fill={`url(#${id}c)`} />
          <ellipse cx="58" cy="42" rx="5" ry="6" fill="#2a3a90" opacity="0.8" />
          <ellipse cx="72" cy="42" rx="5" ry="6" fill="#2a3a90" opacity="0.8" />
          <circle cx="85" cy="20" r="2" fill="#fff" />
          <circle cx="42" cy="26" r="1.5" fill="#fff" />
        </>
      ) : null}
      {glyphe === 'nuage' ? (
        <>
          <path d="M40 60a14 14 0 0 1 14-16 18 18 0 0 1 33 6 12 12 0 0 1 3 24H48a12 12 0 0 1-8-14Z" fill={`url(#${id}c)`} />
          <circle cx="92" cy="22" r="2" fill="#fff" />
          <circle cx="36" cy="30" r="1.5" fill="#fff" />
        </>
      ) : null}
      {glyphe === 'baguette' ? (
        <>
          <path d="m48 72 30-30" stroke="#fff" strokeWidth="7" strokeLinecap="round" />
          <path d="m48 72 30-30" stroke="#8fb0ff" strokeWidth="3" strokeLinecap="round" />
          <path d="M84 24v12M78 30h12" stroke="#fff" strokeWidth="3.5" strokeLinecap="round" />
          <path d="M98 44v8M94 48h8" stroke="#fff" strokeWidth="3" strokeLinecap="round" />
          <path d="M60 22v6M57 25h6" stroke="#fff" strokeWidth="2.5" strokeLinecap="round" />
        </>
      ) : null}
    </svg>
  )
}

/** Vague décorative des cartes « Configuration des lunettes ». */
export function Vague(props: React.SVGProps<SVGSVGElement>): JSX.Element {
  return (
    <svg viewBox="0 0 200 90" preserveAspectRatio="none" aria-hidden="true" {...props}>
      <path d="M0 70c30-10 45-40 70-40s35 45 60 45 40-55 70-60" fill="none" stroke="#8fd8f6" strokeWidth="2" opacity="0.6" />
    </svg>
  )
}
