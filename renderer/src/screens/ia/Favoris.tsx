import React, { useMemo } from 'react'
import { Avatar, Markdown, Vide } from '../../components/ui'
import { IcoEtoile, IcoRobot } from '../../components/icons'
import { formatDate } from '../../lib/api'
import { useStore } from '../../lib/store'

/* =========================================================================
   Onglet IA › Favoris : les messages étoilés (conservés sur cet ordinateur
   seulement, dans le store). Chaque favori s'affiche comme une bulle du fil,
   avec la date, « Ouvrir la conversation » et le retrait.
   ========================================================================= */

export function Favoris({ onOuvrir }: { onOuvrir: (conversationId: string) => void }): JSX.Element {
  const { favoris, basculerFavori, settings } = useStore()
  const tries = useMemo(() => [...favoris].sort((a, b) => (b.date || '').localeCompare(a.date || '')), [favoris])

  if (!tries.length) {
    return (
      <Vide
        icone={<IcoEtoile style={{ width: 120, height: 120, color: 'var(--orange)' }} />}
        texte="Aucun favori pour le moment"
        petit="Touchez l’étoile sous un message pour le retrouver ici."
      />
    )
  }

  return (
    <div className="fil">
      {tries.map((f) => {
        const moi = f.role === 'user'
        return (
          <div className={`message ${moi ? 'moi' : ''}`} key={f.id}>
            {moi ? (
              <Avatar nom={settings?.user_name} />
            ) : (
              <Avatar ia>
                <IcoRobot plein />
              </Avatar>
            )}
            <div className="colonne-msg">
              <div className={`bulle ${moi ? 'moi' : 'ia'}`}>{moi ? <div style={{ whiteSpace: 'pre-wrap' }}>{f.texte}</div> : <Markdown text={f.texte} />}</div>
              <div className="meta">
                <span>{formatDate(f.date)}</span>
                {f.conversation_id ? (
                  <button type="button" onClick={() => onOuvrir(f.conversation_id)} title="Retrouver ce message dans sa conversation">
                    Ouvrir la conversation
                  </button>
                ) : null}
                <button type="button" className="actif" title="Retirer des favoris" aria-label="Retirer des favoris" onClick={() => basculerFavori(f)}>
                  <IcoEtoile plein /> Retirer
                </button>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
