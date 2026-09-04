/** Symbole VELA : anneau volontairement ouvert, trait unique. */
export function Ring({ className = 'ring', color = '#0F6E56' }: { className?: string; color?: string }): JSX.Element {
  return (
    <svg className={className} viewBox="0 0 100 100" fill="none" aria-hidden="true">
      <path
        d="M 72 24 A 36 36 0 1 0 84 62"
        stroke={color}
        strokeWidth="10"
        strokeLinecap="round"
      />
    </svg>
  )
}
