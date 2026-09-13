import React from 'react'
import { Avatar, Markdown } from '../../components/ui'
import { IcoEtoile, IcoRobot } from '../../components/icons'
import { formatTime } from '../../lib/api'
import { useStore } from '../../lib/store'
import { summarizeInput, type Message } from './commun'

/* =========================================================================
   Une entrée du fil de discussion (maquette IMG_0713) : avatar à gauche pour
   IRIS (bulle blanche), à droite pour l'utilisateur (bulle bleue). Porte tout
   ce que l'ancienne MessageBubble affichait : images, raisonnement, outils,
   lignes d'information, erreur, pastilles (voix, interrompu, raison de
   routage) et l'heure ; plus l'étoile « favori ».
   ========================================================================= */

export function Bulle({ m, conversationId }: { m: Message; conversationId: string | null }): JSX.Element {
  const { settings, estFavori, basculerFavori } = useStore()
  const isUser = m.role === 'user'
  const error = m.meta?.error
  const reason = m.meta?.reason
  const favori = estFavori(m.id)
  // Bulle de texte : l'utilisateur n'en a une que s'il a écrit quelque chose (une photo seule
  // n'appelle pas de bulle vide) ; IRIS en a toujours une, sauf en cas d'erreur sans texte.
  const aBulle = isUser ? Boolean(m.text) : Boolean(m.text || m.streaming || m.thinking || m.tools?.length || m.infos?.length || !error)

  return (
    <div className={`message ${isUser ? 'moi' : ''}`}>
      {isUser ? (
        <Avatar nom={settings?.user_name} />
      ) : (
        <Avatar ia>
          <IcoRobot plein />
        </Avatar>
      )}
      <div className="colonne-msg">
        {m.images?.length ? (
          <div className={`bulle ${isUser ? 'moi' : 'ia'}`} style={{ padding: 6 }}>
            <div className="images">
              {m.images.map((img, i) => (img.data ? <img key={i} src={`data:${img.media_type};base64,${img.data}`} alt="" /> : null))}
            </div>
          </div>
        ) : null}

        {aBulle ? (
          <div className={`bulle ${isUser ? 'moi' : 'ia'}`}>
            {m.thinking ? (
              <details className="thinking">
                <summary>Raisonnement</summary>
                {m.thinking}
              </details>
            ) : null}
            {m.tools?.map((t) => (
              <div className="tool" key={t.id}>
                <div className="h">
                  <span className={`dot ${t.status === 'running' ? 'rec' : t.status === 'done' ? 'on' : ''}`} style={t.status === 'error' ? { background: 'var(--red)' } : undefined} />
                  <span className="name">{t.name}</span>
                  <span className="muted small">{summarizeInput(t.input)}</span>
                </div>
                {t.result ? <pre>{t.result}</pre> : null}
              </div>
            ))}
            {m.infos?.map((line, i) => (
              <div className="info-line" key={i}>{line}</div>
            ))}
            {isUser ? (
              m.text ? <div style={{ whiteSpace: 'pre-wrap' }}>{m.text}</div> : null
            ) : m.text ? (
              <Markdown text={m.text} />
            ) : m.streaming ? (
              <span className="row" style={{ gap: 8, color: '#666', fontSize: 14 }}>
                <span className="dot rec" /> IRIS réfléchit…
              </span>
            ) : !error ? (
              <Markdown text="IRIS n’a rien répondu. Reformulez votre demande." />
            ) : null}
            {m.streaming && m.text && !isUser ? <span className="dot rec" style={{ marginLeft: 6, verticalAlign: 'middle' }} /> : null}
          </div>
        ) : null}

        {error ? <div className="bulle erreur">{error}</div> : null}

        <div className="meta">
          <span>{formatTime(m.created_at)}</span>
          {m.meta?.source === 'voice' ? <span className="etiquette">voix</span> : null}
          {m.meta?.cancelled ? <span className="etiquette" style={{ color: 'var(--orange)' }}>interrompu</span> : null}
          {reason && !isUser ? <span title="Pourquoi cette IA">· {reason}</span> : null}
          {!m.streaming ? (
            <button
              type="button"
              className={favori ? 'actif' : ''}
              title={favori ? 'Retirer des favoris' : 'Ajouter aux favoris'}
              aria-label={favori ? 'Retirer des favoris' : 'Ajouter aux favoris'}
              onClick={() => basculerFavori({ id: m.id, conversation_id: conversationId || '', texte: m.text || (m.images?.length ? '[image]' : ''), role: m.role, date: m.created_at })}
            >
              <IcoEtoile plein={favori} />
            </button>
          ) : null}
        </div>
      </div>
    </div>
  )
}
