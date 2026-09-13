import React, { useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { IcoChevronD, IcoChevronG, IcoCoche, IcoFermer, IcoRetour } from './icons'
import { useStore } from '../lib/store'

/* =========================================================================
   Composants partagés de la nouvelle interface (voir styles.css pour les classes).
   Tous les écrans doivent passer par ces briques : c'est ce qui donne à
   l'application l'unité visuelle des maquettes.
   ========================================================================= */

/** Interrupteur iOS. */
export function Toggle({ on, onChange, disabled, titre }: { on: boolean; onChange: (v: boolean) => void; disabled?: boolean; titre?: string }): JSX.Element {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={titre} title={titre} className={`toggle ${on ? 'on' : ''}`} disabled={disabled} onClick={() => onChange(!on)} />
  )
}

/** Grand bouton holographique (ou ses variantes de couleur). */
export function Holo({
  children,
  variante,
  taille,
  className,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variante?: 'holo' | 'blanc' | 'sombre' | 'bleu' | 'rouge' | 'contour'; taille?: 'grand' | 'petit' | 'mini' }): JSX.Element {
  const cls = ['holo', variante && variante !== 'holo' ? variante : '', taille === 'petit' ? 'petit' : taille === 'mini' ? 'mini' : '', className || ''].join(' ').trim()
  return (
    <button type="button" className={cls} {...rest}>
      {children}
    </button>
  )
}

/** Barre du haut d'un écran secondaire : flèche de retour, titre centré, action à droite.
 *  Sans `onRetour`, la flèche revient dans la pile de navigation. `retour={false}` la masque. */
export function TopBar({
  titre,
  retour = true,
  onRetour,
  droite,
  gauche,
  chevron
}: {
  titre: React.ReactNode
  retour?: boolean
  onRetour?: () => void
  droite?: React.ReactNode
  gauche?: React.ReactNode
  /** style de flèche : « < » fin (par défaut) ou « ← » */
  chevron?: boolean
}): JSX.Element {
  const { nav } = useStore()
  return (
    <div className="topbar">
      <div className="gauche">
        {gauche ? gauche : retour ? (
          <button type="button" className="btn-icone" aria-label="Retour" onClick={onRetour || nav.retour}>
            {chevron === false ? <IcoRetour /> : <IcoChevronG />}
          </button>
        ) : null}
      </div>
      <div className="titre">{titre}</div>
      <div className={`droite ${React.Children.count(droite) > 1 ? 'large' : ''}`}>{droite}</div>
    </div>
  )
}

/** Bouton rond d'icône (barre du haut, actions). */
export function BtnIcone({ children, plein, className, ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement> & { plein?: boolean }): JSX.Element {
  return (
    <button type="button" className={`btn-icone ${plein ? 'plein' : ''} ${className || ''}`} {...rest}>
      {children}
    </button>
  )
}

/** Rangée de liste avec icône, titre, sous-titre et chevron (Mon profil, Mes lunettes). */
export function Rangee({
  icone,
  titre,
  sous,
  valeur,
  onClick,
  droite,
  chevron = true,
  compacte,
  danger
}: {
  icone?: React.ReactNode
  titre: React.ReactNode
  sous?: React.ReactNode
  valeur?: React.ReactNode
  onClick?: () => void
  /** contenu à droite à la place du chevron (interrupteur, pastille…) */
  droite?: React.ReactNode
  chevron?: boolean
  compacte?: boolean
  danger?: boolean
}): JSX.Element {
  const cls = `rangee ${compacte ? 'compacte' : ''} ${danger ? 'danger' : ''}`
  const inner = (
    <>
      {icone ? <span className="icone">{icone}</span> : null}
      <span className="corps">
        <span style={{ display: 'block' }}>{titre}</span>
        {sous ? <span className="sous" style={{ display: 'block' }}>{sous}</span> : null}
      </span>
      {valeur ? <span className="valeur">{valeur}</span> : null}
      {droite ? droite : chevron && onClick ? <span className="chevron"><IcoChevronD /></span> : null}
    </>
  )
  return onClick ? (
    <button type="button" className={cls} onClick={onClick}>{inner}</button>
  ) : (
    <div className={cls}>{inner}</div>
  )
}

/** Groupe de rangées sur fond anthracite. */
export function Liste({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }): JSX.Element {
  return <div className="liste" style={style}>{children}</div>
}

/** Carte-réglage : titre + description + interrupteur (Paramètres d'album, Mes lunettes). */
export function CarteReglage({ titre, desc, on, onChange, disabled }: { titre: string; desc?: string; on: boolean; onChange: (v: boolean) => void; disabled?: boolean }): JSX.Element {
  return (
    <div className="carte reglage">
      <div className="corps">
        <h3>{titre}</h3>
        {desc ? <div className="desc">{desc}</div> : null}
      </div>
      <Toggle on={on} onChange={onChange} disabled={disabled} titre={titre} />
    </div>
  )
}

/** Contrôle segmenté (Discussion / Favoris / Minuteur). */
export function Segmente<T extends string>({ options, valeur, onChange }: { options: { id: T; label: string }[]; valeur: T; onChange: (v: T) => void }): JSX.Element {
  return (
    <div className="segmente" role="tablist">
      {options.map((o) => (
        <button key={o.id} type="button" role="tab" aria-selected={o.id === valeur} className={o.id === valeur ? 'actif' : ''} onClick={() => onChange(o.id)}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

/** Puces de filtre (Tout / Photos / Vidéos / Enregistrements). */
export function Puces<T extends string>({ options, valeur, onChange }: { options: { id: T; label: string }[]; valeur: T; onChange: (v: T) => void }): JSX.Element {
  return (
    <div className="puces">
      {options.map((o) => (
        <button key={o.id} type="button" className={`puce ${o.id === valeur ? 'actif' : ''}`} onClick={() => onChange(o.id)}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

/** État vide centré : icône en dégradé + phrase. */
export function Vide({ icone, texte, petit, action }: { icone?: React.ReactNode; texte: React.ReactNode; petit?: React.ReactNode; action?: React.ReactNode }): JSX.Element {
  return (
    <div className="vide">
      {icone}
      <div>{texte}</div>
      {petit ? <div className="petit">{petit}</div> : null}
      {action}
    </div>
  )
}

/** Feuille qui monte du bas (Choisir un rôle, options). Se ferme au clic sur le fond ou Échap. */
export function Feuille({ titre, children, onClose }: { titre?: React.ReactNode; children: React.ReactNode; onClose: () => void }): JSX.Element {
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="voile-fond" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="feuille" role="dialog" aria-modal="true">
        {titre ? <h3>{titre}</h3> : null}
        {children}
      </div>
    </div>
  )
}

/** Option d'une feuille (titre + sous-titre + coche si active). */
export function Option({ titre, sous, actif, onClick }: { titre: React.ReactNode; sous?: React.ReactNode; actif?: boolean; onClick: () => void }): JSX.Element {
  return (
    <button type="button" className={`option ${actif ? 'actif' : ''}`} onClick={onClick}>
      <span className="corps">
        <span className="titre" style={{ display: 'block' }}>{titre}</span>
        {sous ? <span className="sous" style={{ display: 'block' }}>{sous}</span> : null}
      </span>
      {actif ? <span className="coche"><IcoCoche /></span> : null}
    </button>
  )
}

/** Modale centrée (confirmations, détails). */
export function Modal({ title, children, onClose, actions }: { title: string; children: React.ReactNode; onClose?: () => void; actions?: React.ReactNode }): JSX.Element {
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose?.()}>
      <div className="modal" role="dialog" aria-modal="true">
        <div className="row between" style={{ marginBottom: 8 }}>
          <h3 style={{ margin: 0 }}>{title}</h3>
          {onClose ? (
            <button type="button" className="btn-icone" aria-label="Fermer" onClick={onClose}><IcoFermer /></button>
          ) : null}
        </div>
        {children}
        {actions ? <div className="actions">{actions}</div> : null}
      </div>
    </div>
  )
}

/** Texte Markdown ; les liens s'ouvrent dans le navigateur du système. */
export function Markdown({ text }: { text: string }): JSX.Element {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => (
            <a
              href={href}
              onClick={(e) => {
                e.preventDefault()
                if (href) window.iris.openExternal(href)
              }}
            >
              {children}
            </a>
          )
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  )
}

/** Champ de formulaire étiqueté. */
export function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }): JSX.Element {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint ? <span className="hint">{hint}</span> : null}
    </label>
  )
}

/** Ligne « titre + description | contrôle » (héritée ; utile dans les réglages). */
export function SettingRow({ title, desc, children }: { title: React.ReactNode; desc?: React.ReactNode; children: React.ReactNode }): JSX.Element {
  return (
    <div className="row between" style={{ padding: '12px 0', borderBottom: '1px solid var(--line)', gap: 16 }}>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontWeight: 600, fontSize: 16 }}>{title}</div>
        {desc ? <div className="small muted" style={{ marginTop: 2, lineHeight: 1.4 }}>{desc}</div> : null}
      </div>
      <div className="row" style={{ flex: 'none' }}>{children}</div>
    </div>
  )
}

/** Navigation d'un tutoriel : bouton précédent, points, bouton suivant. */
export function TutoNav({ index, total, onPrev, onNext }: { index: number; total: number; onPrev: () => void; onNext: () => void }): JSX.Element {
  return (
    <div className="nav">
      <button type="button" className="btn-rond" aria-label="Précédent" disabled={index <= 0} onClick={onPrev}><IcoChevronG /></button>
      <div className="points" aria-hidden="true">
        {Array.from({ length: total }, (_, i) => <span key={i} className={i === index ? 'actif' : ''} />)}
      </div>
      <button type="button" className="btn-rond" aria-label="Suivant" disabled={index >= total - 1} onClick={onNext}><IcoChevronD /></button>
    </div>
  )
}

/** Avatar : initiale sur fond gris, ou dégradé holographique pour IRIS. */
export function Avatar({ nom, ia, taille, children }: { nom?: string; ia?: boolean; taille?: 'moyen' | 'grand'; children?: React.ReactNode }): JSX.Element {
  const initiale = (nom || '').trim().charAt(0).toUpperCase() || '·'
  return <div className={`avatar ${ia ? 'ia' : ''} ${taille || ''}`}>{children ? children : ia ? 'I' : initiale}</div>
}
