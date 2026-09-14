import React, { useCallback, useRef, useState } from 'react'
import { CarteReglage, Holo, Liste, Rangee, Toggle, TopBar } from '../components/ui'
import { IcoBatterie, IcoLunettes } from '../components/icons'
import { LunettesFace } from '../components/Lunettes'
import { api, formatDate, formatTime } from '../lib/api'
import { useStore } from '../lib/store'

/* =========================================================================
   Mes lunettes : l'appareil (nom, adresse, état, batterie), la présence telle que le service
   la voit (ordinateur ou téléphone appairé), la reconnexion automatique, le bouton des
   lunettes, les actions et la dissociation.
   Aucune donnée inventée : ni micrologiciel ni numéro de série tant que le service ne les fournit pas.

   Lunettes d'abord (décision de Miguel du 2026-09-13) : les anciens interrupteurs du verrou des
   lunettes ont été RETIRÉS de cet écran, et les réglages correspondants sont refusés par le service
   (403). Leur seul accès est propriétaire et caché (voir AProposScreen) ; aucun écran client ne doit
   le montrer ni le mentionner (vérifié par backend/tests/test_wake.py).
   ========================================================================= */

// Ce que le fabricant ne documente pas ne se promet pas : ni « à venir », ni bouton qui fait semblant.
const NON_DOCUMENTE = 'Non pris en charge : le fabricant des lunettes ne documente pas cette commande, IRIS ne peut donc pas la lancer.'
const SANS_CAPTEUR = 'Non pris en charge : les lunettes n’exposent à IRIS aucun capteur de port.'

function messageErreur(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

export function LunettesScreen({ params }: { params?: Record<string, any> }): JSX.Element {
  void params
  const { nav, lunettes, rafraichirLunettes, toast, presence } = useStore()
  const [occupe, setOccupe] = useState<'batterie' | 'reconnexion' | 'deconnexion' | 'dissociation' | null>(null)
  const monte = useRef(true)
  React.useEffect(() => {
    monte.current = true
    return () => {
      monte.current = false
    }
  }, [])

  const connected = Boolean(lunettes?.connected)
  const device = lunettes?.device
  const remembered = lunettes?.remembered
  const battery: number | null = typeof lunettes?.battery === 'number' ? lunettes.battery : null
  const nom: string = device?.name || remembered?.name || device?.address || remembered?.address || 'Lunettes VELA'
  const adresse: string = device?.address || remembered?.address || ''
  const services: unknown[] = Array.isArray(lunettes?.services) ? lunettes.services : []
  const paquets: number = Number(lunettes?.packet_count) || 0

  const fini = (): void => {
    if (monte.current) setOccupe(null)
  }

  /* ---------------------------------------------------------------- actions */
  const mesurerBatterie = useCallback(async () => {
    if (!connected) {
      toast('Connectez les lunettes pour mesurer la batterie.', 'info')
      return
    }
    setOccupe('batterie')
    try {
      const r = await api.post('/api/glasses/battery')
      await rafraichirLunettes()
      if (typeof r?.battery === 'number') toast(`Batterie : ${r.battery} %`, 'success')
      else toast('Niveau de batterie non communiqué par les lunettes.', 'info')
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      fini()
    }
  }, [connected, rafraichirLunettes, toast])

  const reconnecter = useCallback(async () => {
    if (!remembered?.address) {
      toast('Aucunes lunettes mémorisées : passez par « Connecter les lunettes ».', 'info')
      return
    }
    setOccupe('reconnexion')
    try {
      await api.post('/api/glasses/connect', { address: remembered.address, name: remembered.name })
      await rafraichirLunettes()
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      fini()
    }
  }, [remembered?.address, remembered?.name, rafraichirLunettes, toast])

  const deconnecter = useCallback(async () => {
    setOccupe('deconnexion')
    try {
      await api.post('/api/glasses/disconnect')
      await rafraichirLunettes()
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      fini()
    }
  }, [rafraichirLunettes, toast])

  const dissocier = useCallback(async () => {
    if (!window.confirm('Oublier ces lunettes sur cet ordinateur ?')) return
    setOccupe('dissociation')
    try {
      try {
        await api.post('/api/glasses/disconnect')
      } catch {
        /* déjà déconnectées : on poursuit */
      }
      await api.post('/api/glasses/forget')
      await rafraichirLunettes()
      toast('Lunettes oubliées sur cet ordinateur.', 'info')
      nav.viderPile()
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      fini()
    }
  }, [nav, rafraichirLunettes, toast])

  /* ---------------------------------------------------------------- réglages */
  const changerAutoConnect = (v: boolean): void => {
    api
      .patch('/api/glasses/prefs', { auto_connect: v })
      .then(() => rafraichirLunettes())
      .catch((err: unknown) => toast(messageErreur(err), 'error'))
  }

  return (
    <div className="ecran">
      <TopBar titre="Mes lunettes" />
      <div className="contenu">
        {/* carte de l'appareil (non cliquable ici) */}
        <div className="carte-appareil">
          <div>
            <div className="nom">{nom}</div>
            <div className="infos">
              {adresse ? <div className="mono" style={{ fontSize: 15 }}>{adresse}</div> : null}
              {connected && lunettes?.connected_at ? <div>Connecté depuis {formatTime(lunettes.connected_at)}</div> : null}
              {!connected && lunettes?.connected_at ? <div>Dernière connexion : {formatDate(lunettes.connected_at)}</div> : null}
              {connected ? (
                <div>
                  {services.length} service{services.length > 1 ? 's' : ''} · {paquets} paquet{paquets > 1 ? 's' : ''}
                </div>
              ) : null}
            </div>
            <div className="etat">
              <span className={'point' + (connected ? '' : ' hors')}>{connected ? 'Connecté' : 'Déconnecté'}</span>
              {battery !== null ? (
                <span className="batterie">
                  <IcoBatterie niveau={battery} /> {battery} %
                </span>
              ) : null}
            </div>
            {!connected && presence?.presentes && presence.source === 'telephone' ? (
              <div style={{ marginTop: 10 }}>
                <span className="pill ok" style={{ whiteSpace: 'normal', lineHeight: 1.35 }}>
                  Signalées par votre téléphone{presence.attestation_age_s !== null ? ` il y a ${Math.round(presence.attestation_age_s)} s` : ''}
                </span>
              </div>
            ) : null}
            {lunettes?.error ? (
              <div style={{ marginTop: 10 }}>
                <span className="pill err">{String(lunettes.error)}</span>
              </div>
            ) : null}
          </div>
          <LunettesFace className="photo" />
        </div>

        <CarteReglage
          titre="Reconnexion automatique"
          desc="Se reconnecte aux lunettes mémorisées dès qu’elles sont allumées."
          on={Boolean(remembered?.auto_connect)}
          disabled={!remembered?.address}
          onChange={changerAutoConnect}
        />
        {/* Maquette : « Détection d'utilisation ». Aucun capteur de port n'est exposé par les lunettes :
            même carte, interrupteur désactivé, et la raison écrite sur la carte au lieu d'un « À venir ».
            Markup identique à CarteReglage (qui n'accepte qu'un titre texte). */}
        <div className="carte reglage">
          <div className="corps">
            <h3>
              Détection d’utilisation <span className="pill" style={{ verticalAlign: 'middle', marginLeft: 6 }}>Non disponible</span>
            </h3>
            <div className="desc">Suspendre IRIS quand vous retirez vos lunettes. {SANS_CAPTEUR}</div>
          </div>
          <span style={{ display: 'inline-flex', flex: 'none' }}>
            <Toggle on={false} disabled onChange={() => undefined} titre="Détection d’utilisation : non disponible" />
          </span>
        </div>

        <Liste>
          <Rangee
            icone={<IcoLunettes />}
            titre="Bouton des lunettes"
            sous="Apprendre un bouton pour demander une description, si les lunettes l’envoient"
            onClick={() => nav.ouvrir('bouton-lunettes')}
          />
          <Rangee titre="Paramètres d’enregistrement audio" onClick={() => nav.ouvrir('lunettes-audio')} />
          <Rangee
            titre="Mesurer la batterie"
            valeur={occupe === 'batterie' ? 'Mesure…' : battery !== null ? `${battery} %` : undefined}
            onClick={occupe ? undefined : mesurerBatterie}
          />
          {connected ? (
            <Rangee titre="Reconnecter" valeur="Déjà connectées" chevron={false} />
          ) : (
            <Rangee titre="Reconnecter" valeur={occupe === 'reconnexion' ? 'Connexion…' : undefined} onClick={occupe ? undefined : reconnecter} />
          )}
          {connected ? (
            <Rangee titre="Déconnecter" valeur={occupe === 'deconnexion' ? 'Déconnexion…' : undefined} onClick={occupe ? undefined : deconnecter} />
          ) : null}
          <Rangee titre="Détails techniques" onClick={() => nav.ouvrir('lunettes-technique')} />
        </Liste>

        <Liste>
          <Rangee titre="Mise à jour du micrologiciel" valeur="Non pris en charge" onClick={() => toast(NON_DOCUMENTE, 'info')} />
          <Rangee titre="Redémarrer les lunettes" valeur="Non pris en charge" onClick={() => toast(NON_DOCUMENTE, 'info')} />
          <Rangee titre="Restaurer les paramètres d’usine" valeur="Non pris en charge" onClick={() => toast(NON_DOCUMENTE, 'info')} />
          <Rangee titre="À propos" onClick={() => nav.ouvrir('a-propos')} />
        </Liste>

        <div style={{ marginTop: 'auto', paddingTop: 24 }}>
          <Holo disabled={occupe === 'dissociation'} onClick={dissocier}>
            {occupe === 'dissociation' ? 'Dissociation…' : 'Dissocier'}
          </Holo>
        </div>
      </div>
    </div>
  )
}
