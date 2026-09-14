import React, { useCallback, useEffect, useState } from 'react'
import { BtnIcone, Field, Holo, Liste, Rangee, SettingRow, Toggle, TopBar } from '../components/ui'
import { IcoDossier, IcoJournal } from '../components/icons'
import { api } from '../lib/api'
import { useStore } from '../lib/store'

/* =========================================================================
   « Contrôle de l'ordinateur » : confirmations et contrôle complet de l'écran,
   le moteur avancé (modèles de raisonnement et de vision, recherche web,
   effort, affichage du raisonnement, fenêtre d'historique), puis ce que le
   service sait de cet ordinateur (présence, dossier de données, journal,
   version). Aucun nom de fournisseur dans les libellés.
   ========================================================================= */

/** GET /api/recherche/cle : la clé n'est jamais renvoyée en clair (cle_masquee seulement). */
type EtatCleRecherche = {
  configuree: boolean
  source: 'environnement' | 'coffre' | null
  fournisseur: string | null
  cle_masquee: string | null
  coffre_defini: boolean
  note?: string
}

/* Clé de recherche web (apportez votre clé) : la comparaison de prix en dépend et répond 409 sans elle.
   Écran avancé : les services compatibles sont nommés, comme dans les autres réglages de clé. */
function CleRecherche(): JSX.Element {
  const { toast } = useStore()
  const [etat, setEtat] = useState<EtatCleRecherche | null>(null)
  const [cle, setCle] = useState('')
  const [fournisseur, setFournisseur] = useState('')
  const [occupe, setOccupe] = useState(false)

  const charger = useCallback(() => {
    api.get<EtatCleRecherche>('/api/recherche/cle').then(setEtat).catch(() => setEtat(null))
  }, [])
  useEffect(charger, [charger])

  const enregistrer = async (): Promise<void> => {
    if (!cle.trim()) return
    setOccupe(true)
    try {
      setEtat(await api.post<EtatCleRecherche>('/api/recherche/cle', { cle: cle.trim(), fournisseur: fournisseur || null }))
      setCle('')
      toast('Clé de recherche enregistrée dans le coffre de cet ordinateur.', 'success')
    } catch (err) {
      toast(String((err as Error).message), 'error')
    } finally {
      setOccupe(false)
    }
  }

  const effacer = async (): Promise<void> => {
    setOccupe(true)
    try {
      setEtat(await api.delete<EtatCleRecherche>('/api/recherche/cle'))
      toast('Clé de recherche effacée du coffre.', 'info')
    } catch (err) {
      toast(String((err as Error).message), 'error')
    } finally {
      setOccupe(false)
    }
  }

  const resume = !etat
    ? 'État inconnu (service injoignable).'
    : !etat.configuree
      ? 'Aucune clé : la comparaison de prix est indisponible.'
      : `Clé ${etat.cle_masquee || ''} (${etat.fournisseur || 'service détecté'}), ${etat.source === 'environnement' ? 'lue dans le fichier .env : elle passe avant celle du coffre' : 'gardée dans le coffre de cet ordinateur'}.`

  return (
    <div className="col" style={{ gap: 10 }}>
      <Field
        label="Clé de recherche web (comparaison de prix)"
        hint={`${resume} La requête (le nom du produit) part vers le service de recherche choisi ; les prix trouvés peuvent dater de quelques jours.`}
      >
        <input
          className="input mono"
          type="password"
          autoComplete="off"
          placeholder={etat?.coffre_defini ? 'remplacer la clé enregistrée' : 'coller la clé'}
          value={cle}
          onChange={(e) => setCle(e.target.value)}
        />
      </Field>
      <div className="row" style={{ gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <select className="select" aria-label="Service de recherche" style={{ width: 230 }} value={fournisseur} onChange={(e) => setFournisseur(e.target.value)}>
          <option value="">Détecter d’après la clé</option>
          <option value="tavily">Tavily</option>
          <option value="brave">Brave Search</option>
        </select>
        <Holo taille="mini" variante="bleu" disabled={occupe || !cle.trim()} onClick={() => void enregistrer()}>
          Enregistrer
        </Holo>
        {etat?.coffre_defini ? (
          <Holo taille="mini" variante="contour" disabled={occupe} onClick={() => void effacer()}>
            Effacer
          </Holo>
        ) : null}
      </div>
    </div>
  )
}

export function ReglagesPcScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { settings, updateSettings, status, appInfo, toast } = useStore()
  const [draft, setDraft] = useState<any>(settings)

  useEffect(() => setDraft(settings), [settings])

  if (!draft) {
    return (
      <div className="ecran">
        <TopBar titre="Contrôle de l’ordinateur" />
      </div>
    )
  }

  const set = (patch: Record<string, unknown>): Promise<void> => updateSettings(patch).catch((err: Error) => toast(String(err.message), 'error'))
  const commit = (key: string): void => {
    if (draft[key] !== settings?.[key]) set({ [key]: draft[key] })
  }

  const presence = status?.presence
  const dossierDonnees: string = status?.data_dir || appInfo?.userData || ''
  const journal: string = appInfo?.logPath || ''
  const version = `IRIS ${appInfo?.version || '?'} · service ${status?.version || '?'} · ${status?.platform || appInfo?.platform || ''}`

  const ouvrir = (chemin: string): void => {
    if (!chemin) return
    window.iris.openPath(chemin).catch((err: Error) => toast(String(err.message), 'error'))
  }

  return (
    <div className="ecran">
      <TopBar titre="Contrôle de l’ordinateur" />
      <div className="contenu">
        {/* ------------------------------------------------------------ actions */}
        <h3 className="section-sous">Actions sur l’ordinateur</h3>
        <div className="carte">
          <SettingRow title="Confirmation avant une commande" desc="IRIS n’agit que sur votre demande. Les commandes dangereuses (suppression, arrêt, droits…) demandent toujours confirmation en mode « dangereuses ».">
            <select className="select" aria-label="Confirmation avant une commande" style={{ width: 230 }} value={draft.confirm_commands || 'dangerous'} onChange={(e) => set({ confirm_commands: e.target.value })}>
              <option value="dangerous">Seulement les commandes dangereuses</option>
              <option value="always">Toujours</option>
              <option value="never">Jamais (fluidité maximale)</option>
            </select>
          </SettingRow>
          <SettingRow title="Contrôle complet de l’écran" desc="Souris, capture d’écran et lecture du texte à l’écran (OCR hors-ligne) : IRIS peut agir dans n’importe quelle application ou jeu. Dites par exemple « clique sur Jouer » ou « dans le jeu, appuie sur Entrée ».">
            <Toggle on={Boolean(draft.computer_use)} onChange={(v) => set({ computer_use: v })} titre="Contrôle complet de l’écran" />
          </SettingRow>
        </div>

        {/* ------------------------------------------------------------ moteur avancé */}
        <h3 className="section-sous">Moteur avancé</h3>
        <div className="carte col" style={{ gap: 14 }}>
          <Field label="Modèle de raisonnement" hint="Pour la création (jeux, sites, apps) et les tâches longues. Vide = modèle de l’assistante. Un modèle avancé améliore nettement la qualité des plans.">
            <input
              className="input mono"
              placeholder="identifiant de modèle"
              value={draft.reasoning_model || ''}
              onChange={(e) => setDraft({ ...draft, reasoning_model: e.target.value })}
              onBlur={() => commit('reasoning_model')}
            />
          </Field>
          <Field label="Modèle vision (écran)" hint="Doit accepter les images. Vide = modèle de l’assistante.">
            <input
              className="input mono"
              placeholder="identifiant de modèle"
              value={draft.vision_model || ''}
              onChange={(e) => setDraft({ ...draft, vision_model: e.target.value })}
              onBlur={() => commit('vision_model')}
            />
          </Field>
          <CleRecherche />
          <div>
            <SettingRow title="Recherche web" desc="Le cerveau d’IRIS peut consulter le web pour répondre à jour ; les requêtes de recherche transitent alors par le fournisseur d’intelligence artificielle tiers.">
              <Toggle on={Boolean(draft.claude_web_search)} onChange={(v) => set({ claude_web_search: v })} titre="Recherche web" />
            </SettingRow>
            <SettingRow title="Effort de réflexion" desc="Pour les conversations écrites.">
              <select className="select" aria-label="Effort de réflexion" style={{ width: 160 }} value={draft.claude_effort || 'medium'} onChange={(e) => set({ claude_effort: e.target.value })}>
                <option value="low">Rapide</option>
                <option value="medium">Équilibré</option>
                <option value="high">Approfondi</option>
              </select>
            </SettingRow>
            <SettingRow title="Afficher le raisonnement" desc="Résumé de la réflexion, déroulable sous chaque réponse écrite.">
              <Toggle on={Boolean(draft.claude_thinking_display)} onChange={(v) => set({ claude_thinking_display: v })} titre="Afficher le raisonnement" />
            </SettingRow>
            <SettingRow title="Messages d’historique envoyés" desc="Fenêtre d’historique par conversation (de 2 à 200 messages).">
              <input
                type="number"
                className="input"
                aria-label="Messages d’historique envoyés"
                style={{ width: 90 }}
                min={2}
                max={200}
                value={Number(draft.history_window) || 40}
                onChange={(e) => setDraft({ ...draft, history_window: Number(e.target.value) })}
                onBlur={() => {
                  const borne = Math.max(2, Math.min(200, Number(draft.history_window) || 40))
                  if (borne !== draft.history_window) setDraft({ ...draft, history_window: borne })
                  if (borne !== settings?.history_window) set({ history_window: borne })
                }}
              />
            </SettingRow>
          </div>
        </div>

        {/* ------------------------------------------------------------ cet ordinateur */}
        <h3 className="section-sous">Cet ordinateur</h3>
        <Liste>
          {presence ? (
            <>
              <Rangee compacte titre="Nom de l’ordinateur" valeur={presence.device_name || '—'} />
              <Rangee
                compacte
                titre="IRIS est installée"
                valeur={presence.installed_days >= 1 ? `depuis ${presence.installed_days} jour${presence.installed_days > 1 ? 's' : ''}` : 'aujourd’hui'}
              />
              <Rangee compacte titre="Démarrages" valeur={`${presence.sessions ?? 0}`} />
              {presence.last_interaction_ago ? <Rangee compacte titre="Dernier échange" valeur={presence.last_interaction_ago} /> : null}
            </>
          ) : null}
          <Rangee
            compacte
            titre="Dossier de données"
            sous={<span className="mono" title={dossierDonnees || undefined} style={{ wordBreak: 'break-all' }}>{dossierDonnees || 'Inconnu pour l’instant'}</span>}
            droite={
              <BtnIcone title="Ouvrir le dossier" aria-label="Ouvrir le dossier de données" disabled={!dossierDonnees} onClick={() => ouvrir(dossierDonnees)}>
                <IcoDossier />
              </BtnIcone>
            }
          />
          <Rangee
            compacte
            titre="Journal du service"
            sous={<span className="mono" title={journal || undefined} style={{ wordBreak: 'break-all' }}>{journal || 'Inconnu pour l’instant'}</span>}
            droite={
              <BtnIcone title="Ouvrir le journal" aria-label="Ouvrir le journal du service" disabled={!journal} onClick={() => ouvrir(journal)}>
                <IcoJournal />
              </BtnIcone>
            }
          />
          <Rangee compacte titre="Version" sous={version} />
        </Liste>
      </div>
    </div>
  )
}
