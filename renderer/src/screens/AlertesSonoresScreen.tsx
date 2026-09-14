import React, { useEffect, useState } from 'react'
import { CarteReglage, Holo, Toggle, TopBar } from '../components/ui'
import { CarteLunettesRequises } from '../components/LunettesRequises'
import { api, estLunettesRequises, messageErreur, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'
import './AccessibiliteScreen.css'

/* =========================================================================
   « Alertes sonores » : alarme, sirène, klaxon, sonnette, coups à la porte,
   prénom — détectés sur l'ordinateur, affichés en plein écran (App.tsx),
   annoncés dans les lunettes si l'annonce vocale est active.

   Tout vient du service (backend/iris/alertes_sonores.py) : l'avertissement et
   les limites sont affichés tels quels. « Tester » passe un signal synthétique
   dans le VRAI détecteur ; le prénom ne se teste pas ainsi, et l'écran le dit.
   ========================================================================= */

interface TypeAlerte {
  id: string
  libelle: string
  actif: boolean
}

interface Alerte {
  type?: string
  genre?: string
  libelle: string
  confiance: number
  ts: number
  test: boolean
}

interface EtatAlertes {
  actives: boolean
  en_marche: boolean
  types: TypeAlerte[]
  sensibilite: number
  voix: boolean
  dernieres: Alerte[]
  raison: string | null
  en_attente_micro: boolean
  prenom?: { prenom: string | null; disponible: boolean; raison: string | null }
  local?: boolean
  avertissement?: string
  limites?: string[]
}

function heure(ts: number): string {
  const d = new Date(ts * 1000)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('fr-CA', { dateStyle: 'short', timeStyle: 'medium' })
}

export function AlertesSonoresScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { settings, updateSettings, toast, presence, exigerLunettes } = useStore()
  const [etat, setEtat] = useState<EtatAlertes | null>(null)
  const [erreur, setErreur] = useState('')
  const [occupe, setOccupe] = useState(false)
  const [enTest, setEnTest] = useState<string | null>(null)
  const [resultatsTest, setResultatsTest] = useState<Record<string, string>>({})
  const [sensibilite, setSensibilite] = useState<number>(Number(settings?.alertes_sensibilite ?? 50))

  const absentes = presence !== null && !presence.presentes

  const charger = async (): Promise<void> => {
    try {
      setEtat(await api.get('/api/alertes'))
      setErreur('')
    } catch (err) {
      setErreur(messageErreur(err))
    }
  }

  useEffect(() => {
    charger()
    return api.on((e: IrisEvent) => {
      if (e.type === 'alertes.etat') {
        setEtat((s) => (s ? { ...s, actives: Boolean(e.actives), en_marche: Boolean(e.en_marche), raison: e.raison ?? null, en_attente_micro: Boolean(e.en_attente_micro) } : s))
      } else if (e.type === 'alerte.sonore') {
        const a: Alerte = { genre: e.genre, libelle: e.libelle, confiance: Number(e.confiance) || 0, ts: Number(e.ts) || Date.now() / 1000, test: Boolean(e.test) }
        setEtat((s) => (s ? { ...s, dernieres: [a, ...s.dernieres].slice(0, 20) } : s))
      } else if (e.type === 'settings.updated') {
        // types, sensibilité et annonce vivent dans les réglages : on relit l'état qui les recompose
        charger()
      }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    setSensibilite(Number(settings?.alertes_sensibilite ?? 50))
  }, [settings?.alertes_sensibilite])

  const basculerGeneral = async (v: boolean): Promise<void> => {
    if (v && !exigerLunettes('Alertes sonores')) return
    setOccupe(true)
    setErreur('')
    try {
      setEtat(await api.post(v ? '/api/alertes/activer' : '/api/alertes/desactiver'))
    } catch (err) {
      // 409 : mode confidentiel ou micro indisponible, avec la raison exacte.
      if (!estLunettesRequises(err)) setErreur(messageErreur(err))
    } finally {
      setOccupe(false)
    }
  }

  const basculerType = (id: string, v: boolean): void => {
    const actuels: string[] = Array.isArray(settings?.alertes_types) ? settings.alertes_types : (etat?.types || []).filter((t) => t.actif).map((t) => t.id)
    const suivants = v ? Array.from(new Set([...actuels, id])) : actuels.filter((t) => t !== id)
    updateSettings({ alertes_types: suivants }).catch((err: unknown) => toast(messageErreur(err), 'error'))
  }

  const engagerSensibilite = (): void => {
    if (sensibilite !== Number(settings?.alertes_sensibilite)) {
      updateSettings({ alertes_sensibilite: sensibilite }).catch((err: unknown) => toast(messageErreur(err), 'error'))
    }
  }

  const tester = async (t: TypeAlerte): Promise<void> => {
    if (!exigerLunettes('Tester une alerte')) return
    setEnTest(t.id)
    try {
      const r = await api.post('/api/alertes/tester', { type: t.id })
      const texte = r?.detecte
        ? `Détecté (confiance ${Math.round((Number(r.confiance) || 0) * 100)} %).`
        : 'Non détecté avec la sensibilité actuelle.'
      setResultatsTest((m) => ({ ...m, [t.id]: `${texte}${r?.note ? ` ${r.note}` : ''}` }))
    } catch (err) {
      if (!estLunettesRequises(err)) setResultatsTest((m) => ({ ...m, [t.id]: messageErreur(err) }))
    } finally {
      setEnTest(null)
    }
  }

  const actives = Boolean(etat?.actives)

  return (
    <div className="ecran">
      <TopBar titre="Alertes sonores" />
      <div className="contenu">
        {absentes ? <CarteLunettesRequises /> : null}

        {etat?.avertissement ? <div className="bloc-note attention" role="note">{etat.avertissement}</div> : null}

        <CarteReglage
          titre="Alertes sonores"
          desc="IRIS écoute les sons importants sur cet ordinateur et les affiche en plein écran. Rien n’est enregistré, rien ne quitte l’appareil."
          on={actives}
          disabled={occupe}
          onChange={basculerGeneral}
        />
        {erreur ? <div className="bloc-note erreur" role="alert">{erreur}</div> : null}
        {actives && etat?.raison ? <div className="bloc-note attention">{etat.raison}</div> : null}
        {actives && etat?.en_attente_micro ? <div className="bloc-note attention">En attente du micro : aucun son n’arrive pour le moment, donc aucune alerte n’est possible.</div> : null}
        {actives && etat && !etat.en_marche && !etat.raison ? <div className="bloc-note attention">Activées, mais l’écoute des alertes ne tourne pas en ce moment.</div> : null}
        {actives && etat?.en_marche && !etat.en_attente_micro ? <div className="bloc-note ok">L’écoute des alertes tourne.</div> : null}

        <h2 className="section-sous">Sons à signaler</h2>
        <div className="carte col" style={{ gap: 4 }}>
          {(etat?.types || []).map((t) => (
            <div key={t.id} className="alerte-ligne">
              <div className="corps">
                <div className="titre">{t.libelle}</div>
                {t.id === 'prenom' ? (
                  <div className="sous">
                    {etat?.prenom?.prenom ? `Prénom écouté : ${etat.prenom.prenom}. ` : ''}
                    {etat?.prenom?.raison || 'Ne se teste pas avec un son d’essai : faites dire votre prénom près du micro, alertes activées.'}
                  </div>
                ) : resultatsTest[t.id] ? (
                  <div className="sous" aria-live="polite">{resultatsTest[t.id]}</div>
                ) : null}
              </div>
              {t.id !== 'prenom' ? (
                <Holo taille="mini" variante="sombre" disabled={enTest !== null} onClick={() => tester(t)} aria-label={`Tester : ${t.libelle}`}>
                  {enTest === t.id ? 'Test…' : 'Tester'}
                </Holo>
              ) : null}
              <Toggle on={t.actif} onChange={(v) => basculerType(t.id, v)} titre={t.libelle} />
            </div>
          ))}
          {!etat && !erreur ? <div className="small muted">Chargement…</div> : null}
        </div>

        <div className="carte col" style={{ gap: 14 }}>
          <div className="curseur">
            <div className="entete">
              <label htmlFor="sensibilite-alertes">Sensibilité</label>
              <output htmlFor="sensibilite-alertes">{sensibilite}</output>
            </div>
            <input
              id="sensibilite-alertes"
              type="range"
              min={0}
              max={100}
              step={5}
              value={sensibilite}
              onChange={(e) => setSensibilite(Number(e.target.value))}
              onMouseUp={engagerSensibilite}
              onKeyUp={engagerSensibilite}
              onTouchEnd={engagerSensibilite}
              onBlur={engagerSensibilite}
            />
            <div className="aide">Plus haut : moins de sons manqués, plus de fausses alertes. Plus bas : l’inverse.</div>
          </div>
          <div className="row between" style={{ gap: 12 }}>
            <div>
              <div style={{ fontWeight: 700, fontSize: 17 }}>Annonce vocale</div>
              <div className="small muted">IRIS dit l’alerte à voix haute (dans les lunettes quand elles sont la sortie audio).</div>
            </div>
            <Toggle
              on={settings?.alertes_voix !== false}
              onChange={(v) => updateSettings({ alertes_voix: v }).catch((err: unknown) => toast(messageErreur(err), 'error'))}
              titre="Annonce vocale"
            />
          </div>
        </div>

        <h2 className="section-sous">Dernières alertes</h2>
        <div className="carte col" style={{ gap: 4 }}>
          {etat?.dernieres?.length ? (
            etat.dernieres.map((a, i) => (
              <div key={`${a.ts}-${i}`} className="alerte-ligne">
                <div className="corps">
                  <div className="titre">{a.libelle}{a.test ? ' (essai)' : ''}</div>
                  <div className="sous">{heure(a.ts)} · confiance {Math.round(a.confiance * 100)} %</div>
                </div>
              </div>
            ))
          ) : (
            <div className="small muted">Aucune alerte depuis le démarrage d’IRIS. Les alertes ne sont pas conservées d’un démarrage à l’autre.</div>
          )}
        </div>

        <div className="carte">
          <h3>Limites</h3>
          <ul className="liste-limites">
            <li>Délai de détection observé sur des sons d’essai : d’environ 0,5 s pour un klaxon à environ 3 s pour une alarme ou une sirène lente. Jamais instantané.</li>
            {(etat?.limites || []).map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  )
}
