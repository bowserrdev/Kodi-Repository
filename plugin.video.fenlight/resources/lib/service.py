# -*- coding: utf-8 -*-
# La nascita di questo servizio e' stata profilata nel lotto 204 e il profilatore e' stato tolto
# dopo aver risposto. Il referto, perche' non si riapra la stessa domanda fra sei mesi (stick,
# avvii 08/09 05:03 e 05:08, fra 'entering source directory' e 'Main Monitor Service Starting'):
#     prima:  import 864 ms + corpo 2 ms + ~110 ms di compilazione = 976 ms
#     dopo:   import 331 ms + corpo 1 ms + ~103 ms di compilazione = 436 ms
# Due conclusioni, entrambe con un numero sotto:
#  - la COMPILAZIONE dei 76 KB vale ~105 ms, stabile su due avvii. Kodi esegue questo file come
#    __main__, quindi Python non ne mette in cache il bytecode, e infatti resources/lib/ e' l'unica
#    cartella senza __pycache__. Spostare 1100 righe in un modulo col .pyc per recuperare 105 ms non
#    vale il rimaneggiamento: ipotesi valutata e SCARTATA, non dimenticata.
#  - il costo era negli import di sola libreria standard (Fen Light: 0 ms), e pendeva quasi tutto da
#    `json`, usato in UN punto solo. Reso pigro: 23 moduli -> 12, 864 ms -> 331.
# Quel che resta e' l'albero di `threading` (~310 ms) piu' xbmcgui: Thread serve subito, per far
# partire il rinvio del lotto 203, e non si toglie senza cambiare come il servizio genera lavoro.
# Il capitolo import di service.py e' chiuso.
import xbmc, xbmcgui
# `import json` NON sta piu' qui: vedi WidgetRefresher.condition_check, l'unico punto che lo usa.
from threading import Thread
# BlurService NON si importa piu' qui (lotto avvio, 08/09/2026). L'import era di livello modulo,
# quindi girava a ogni avvio del servizio anche con il blur spento dal 23/08 (vedi la riga
# commentata in startServices): modules/blur_service.py importa urllib.parse in testa, cioe'
# proprio la catena che il lotto 74 aveva tolto dal percorso di Fen Light portandosi in casa
# urlencode/parse_qsl/unquote. Rientrava dalla finestra, e rientrava dentro la tempesta d'avvio.
# Ora sta dentro _delayed_blur_start, che e' l'unico punto che lo usa: se il blur tornera' vivo
# pagera' il suo import allora, fuori dai 7,56 s in cui si costruiscono i widget della home.

pause_services_prop = 'fenlight.pause_services'
# Vedi kodi_utils.PLAYBACK_ACTIVE_PROP. Dal lotto 113 la bandiera non taglia piu' niente: resta
# come stato leggibile senza toccare la GUI, e la usa la diagnostica delle costruzioni.
playback_active_prop = 'fenlight.playback.active'
playback_start_prop = 'fenlight.perf.playstart'
current_skin_prop = 'fenlight.current_skin'
trakt_service_string = 'TraktMonitor Service Update %s - %s'
trakt_success_line_dict = {'success': 'Trakt Update Performed', 'no account': '(Unauthorized) Trakt Update Performed'}
# SECONDI, non minuti, ed e' voluto. 'fenlight.trakt.sync_interval' e' in secondi in tutto il
# sistema: l'etichetta dell'impostazione dice 'Resync Interval (secs)' e lo schema in
# settings_cache.py la limita a 15-3600. Un poll stretto (30 s il minimo scelto) serve a dare
# l'impressione di una sincronizzazione immediata fra dispositivi diversi, simulando un webhook
# dove Trakt offre solo polling. Sul Mi Stick l'utente alza l'intervallo; altrove resta basso.
# NON "correggerlo" moltiplicando per 60: il messaggio diceva 'minutes' e faceva sembrare un bug
# di unita' di misura cio' che e' una scelta.
update_string = 'Next Update in %s seconds...'
# Finestra entro cui una ricostruzione globale gia' avvenuta rende superflua quella che Trakt
# chiederebbe. Tarata sopra il ritardo osservato fra le due (7,1 s) e sotto nessun vincolo:
# alzarla sopprime piu' duplicati ma ritarda di piu' un cambiamento fatto DAVVERO altrove.
TRAKT_REFRESH_COALESCE = 30
# Ritardo prima di avviare BlurService (lotto 48, 23/08). In tre catture indipendenti (17:20,
# a1edbba, 19:51) la riga finale del log prima del riavvio da watchdog era sempre 'BlurService
# Starting (Pillow: OK)' o l'equivalente import di Pillow da fen_blur -- l'unico elemento presente
# in ogni crash da avvio catturato. Test a 4 cicli consecutivi con BlurService disattivato del
# tutto: 4 su 4 senza riavvio, contro una serie precedente di crash quasi sistematici. Toglierlo
# per sempre pero' perde la sfocatura (verificato: nessun file nuovo nella cache blur durante il
# test). Il compromesso e' rimandarne l'avvio oltre la finestra critica (0-25s misurati finora):
# l'interprete Kodi e' gia' vivo, aspettare qui non costa un processo in piu', solo un thread fermo.
BLUR_START_DELAY = 25
# Attesa del lavoro di avvio differito (lotto 2, 08/09/2026). Vedi _deferred_services.
#
# SETTLE e' quiete DOPO l'ultima consegna, non una stima della durata dell'avvio. Va tarata sopra il
# BUCO PIU' LARGO fra due consegne consecutive, o la quiete scatta in mezzo alla finestra e il rinvio
# non serve a niente. I buchi misurati, per avvio:
#     03:42 (6 interpreti)  36.36 / 37.26 / 37.44  ->  0,90 e 0,18
#     04:35 (4 interpreti)  57.89 / 59.26 / 59.57  ->  1,37 e 0,31
#     04:36 (4 interpreti)  22.42 / 24.16 / 24.40  ->  1,74 e 0,24
# Il peggiore e' 1,74 s. Il valore sotto e' 3,0: 1,7 volte il peggiore osservato, perche' sbagliare
# per eccesso non costa nulla (il lavoro rinviato non e' urgente) mentre sbagliare per difetto
# annulla il lotto. La prima stesura aveva 1,5 s e un banco di prova con orologio finto l'ha
# bocciata sul caso reale del 04:36: sarebbe ripartita dopo UN widget su tre.
# Se un widget straggler arrivasse comunque oltre i 3 s, il rinvio degrada al comportamento di prima
# per quel solo widget: si perde guadagno, non si rompe niente.
# POLL e' fitto perche' ogni giro e' la lettura di una proprieta' di finestra.
# CAP e' la rete di sicurezza: dopo tanto si parte comunque, widget o non widget.
BOOT_DEFER_SETTLE = 3.0
BOOT_DEFER_POLL = 0.25
BOOT_DEFER_CAP = 20

def refresh_official_status():
	"""Ricalcola in anticipo la risposta di trakt_official_status, fuori dal percorso critico.

	Vedi apis.trakt_api.trakt_official_status: e' una domanda di configurazione che costava 2347 ms
	quando veniva posta alla chiusura del player, perche' passa da getCondVisibility e li' il lock
	della GUI e' conteso. Chiesta da qui, mentre non succede niente, costa quello che deve costare e
	set_bookmark la trova gia' pronta.
	Sta in un thread perche' anche questa chiamata puo' bloccare, e il ciclo del TraktMonitor non
	deve dipenderne.
	"""
	def _work():
		try:
			from apis.trakt_api import compute_official_status
			for media_type in ('movie', 'episode'): compute_official_status(media_type, store=True)
		except: pass
	Thread(target=_work).start()

def decide_refresh(changed, actions, age, coalesce_seconds):
	"""Cosa fare del risultato di una sincronizzazione Trakt. Torna (cosa, ids, azioni).

	Pura: niente Kodi, niente rete, niente orologio -- l'eta' arriva da fuori. Esiste perche' questa
	decisione ha gia' prodotto tre guasti (lotti 130, 134 e 139) e non era provabile in nessun modo:
	stava dentro un ciclo di servizio che parla con Trakt.

	I due canali, che sono canali DIVERSI e non due modi di dire la stessa cosa:
	  changed: CHI e' cambiato. '-' = lo sappiamo, non e' cambiato nessuno. '' = non lo sappiamo.
	  actions: QUALE widget cambia composizione. '' = nessuna. Non ha un valore 'ignoto'.

	QUI NON C'E' PIU' LA GUARDIA self_mark_recent, ed e' il punto del lotto 139. Diceva: 'la modifica
	e' nostra ed e' gia' a schermo', e lo deduceva da un timbro temporale -- abbiamo scritto qualcosa
	negli ultimi 45 s. E' la domanda sbagliata: risponde 'ho scritto di recente?' quando quella giusta
	e' 'questo cambiamento e' gia' a schermo?'. Sulla stick il 03/09 alle 17:17:03 le due hanno dato
	risposte opposte: la stick aveva spinto un proprio segnalibro alle 17:16:32 (`in locale 1
	(1 pending_put)`), poi e' arrivato da Trakt un episodio segnato visto DAL MAC
	(`1 new plays added`, `titoli cambiati: 1 -> ['287238'] | azioni: continue_watching`) e la guardia
	l'ha buttato: `refresh saltato, la modifica e' nostra ed e' gia' a schermo`. Non era nostra, e non
	era a schermo -- l'episodio successivo non e' mai entrato in 'continua a guardare'. E non era
	nemmeno un ritardo: quel ramo non leggeva ne' azzerava i due canali, che il giro dopo venivano
	sovrascritti. Perso, non rimandato.

	Si puo' togliere perche' cio' che proteggeva non esiste piu'. Proteggeva dalla ricostruzione
	GLOBALE innescata da una nostra marcatura: trakt_indicators_movies, vedendo il proprio timbro,
	torna None, e None significa 'non so chi e' cambiato' -> globale. Ma dal lotto 134 OGNI ramo che
	puo' lasciare gli id ignoti dichiara comunque la propria azione (continue_watching), e un'azione
	da sola basta per una ricarica MIRATA (lotto 119). Il globale per una nostra marcatura non e' piu'
	raggiungibile: la guardia difendeva una porta murata, e nel farlo ne teneva chiusa una aperta.
	"""
	acts = actions or ''
	# 'lo sappiamo, non e' cambiato nessuno' e nessun widget cambia composizione: non c'e' niente da
	# mostrare. E' la versione ESATTA, basata sul contenuto, di cio' che il timbro approssimava.
	if changed == '-' and not acts: return ('niente', '', '')
	# Ricostruito da poco: non si giudica di nuovo qui, si RIMANDA con tutto cio' che si sa (lotto 130).
	if age < coalesce_seconds: return ('rinvio', '' if changed == '-' else (changed or ''), acts)
	# '-' vuol dire 'nessun id', non 'nessun lavoro': con le sole azioni si ricostruiscono comunque i
	# widget che cambiano composizione.
	ids = '' if changed == '-' else (changed or '')
	if ids or acts: return ('mirato', ids, acts)
	# Non sappiamo chi e' cambiato e nessuno ha dichiarato un'azione: l'unica rete e' il globale.
	return ('globale', '', '')

def refresh_ids_inproc(ids, actions, coalesce=True):
	"""kodi_refresh_ids chiamato QUI invece di ordinato con RunPlugin (lotto 125).

	RunPlugin fa nascere un interprete Python nuovo che deve reimportare tutto l'albero del plugin
	per eseguire una funzione fatta di letture di proprieta' e di infolabel piu' un executebuiltin.
	Misurato sulla stick: ~350 ms di soli import a invocazione, piu' l'avvio dell'interprete, che su
	un dispositivo debole compete con la CPU che serve alla ricostruzione vera. Il servizio ha gia'
	kodi_utils caricato -- lo importa per run_plugin e refresh_age -- quindi la funzione si puo'
	chiamare direttamente: fa lo stesso lavoro, sugli stessi canali (proprieta' di finestra e
	builtin), che sono globali al processo Kodi e non appartengono all'invocazione del plugin.

	Il thread non e' un dettaglio: refresh_containers_for_ids interroga i contenitori a schermo e
	non deve mai poter ritardare il ciclo del monitor, che e' proprio cio' che RunPlugin garantiva
	gratis rendendo la chiamata asincrona. Togliere l'interprete senza rimettere l'asincronia
	sarebbe stato un baratto, non un guadagno.
	"""
	from modules.kodi_utils import kodi_refresh_ids
	_ids = [i for i in (ids or '').split(',') if i]
	_actions = tuple(a for a in (actions or '').split(',') if a)
	Thread(target=kodi_refresh_ids, args=(_ids, _actions), kwargs={'coalesce': coalesce}).start()
# Giri dopo un cambio di finestra in cui si ripassa il censimento dei contenitori. I giri sono da
# 0,3 s: 0 / 1,5 / 3 / 6 / 10,5 / 16,5 secondi. Copre il tempo in cui i widget si stanno ancora
# costruendo -- sulla stick una costruzione supera spesso i 5 s -- senza sondare per sempre una
# finestra che di widget Fen Light non ne ha. registry_add e' idempotente, quindi ripassare non
# duplica nulla: aggiunge solo cio' che nel frattempo e' comparso.
CENSUS_TICKS = frozenset((0, 5, 10, 20, 35, 55))
# xbmcgui.getCurrentWindowDialogId(): 9999 (WINDOW_INVALID) quando non c'e' nessun dialogo modale (vedi
# kodi_utils.modal_dialog_present), 10106 il menu contestuale (WINDOW_DIALOG_CONTEXT_MENU).
NO_DIALOG, CONTEXT_MENU_DIALOG = 9999, 10106

def logger(heading, function):
	xbmc.log('###%s###: %s' % (heading, function), 1)

class SetAddonConstants:
	def run(self):
		logger('Fen Light', 'SetAddonConstants Service Starting')
		import xbmcgui, xbmcaddon, xbmcvfs
		addon_object = xbmcaddon.Addon('plugin.video.fenlight')
		self.window = xbmcgui.Window(10000)
		_info = addon_object.getAddonInfo
		addon_items = [('fenlight.addon_version', _info('version')),
					('fenlight.addon_path', _info('path')),
					('fenlight.addon_profile', xbmcvfs.translatePath(_info('profile'))),
					('fenlight.addon_icon', xbmcvfs.translatePath(_info('icon'))),
					('fenlight.addon_fanart', xbmcvfs.translatePath(_info('fanart')))]
		for item in addon_items: self.set_property(*item)
		# LOTTO 311 -- la sessione dei widget si apre QUI, nel primo servizio, e non nella manutenzione
		# dei database: quella puo' essere rimandata (vedi _boot_work_can_wait) e intanto i widget
		# costruiscono. Una lista registrata senza sessione non si potrebbe mai buttare, quindi senza
		# questo id le build non registrano affatto.
		try:
			from caches.widgets_cache import avvia_sessione
			avvia_sessione()
		except Exception as e: logger('Fen Light', 'sessione widget non aperta (%s)' % e)
		return logger('Fen Light', 'SetAddonConstants Service Finished')

	def set_property(self, prop, value):
		self.window.setProperty(prop, value)

class DatabaseMaintenance:
	def run(self):
		logger('Fen Light', 'DatabaseMaintenance Service Starting')
		from caches.base_cache import make_databases
		make_databases()
		return logger('Fen Light', 'DatabaseMaintenance Service Finished')

class SyncSettings:
	def run(self):
		logger('Fen Light', 'SyncSettings Service Starting')
		from caches.settings_cache import sync_settings
		sync_settings()
		logger('Fen Light', 'SyncSettings Service Finished')

class CustomFonts:
	def run(self):
		logger('Fen Light', 'CustomFonts Service Starting')
		from windows.base_window import FontUtils
		monitor, player, window = xbmc.Monitor(), xbmc.Player(), xbmcgui.Window(10000)
		wait_for_abort, is_playing = monitor.waitForAbort, player.isPlayingVideo
		window.clearProperty(current_skin_prop)
		font_utils = FontUtils()
		while not monitor.abortRequested():
			# In riproduzione non si tocca la skin: execute_custom_fonts riscrive Font.xml e puo'
			# innescare un ricaricamento. Prima girava comunque, solo piu' di rado.
			if window.getProperty(pause_services_prop) == 'true' or is_playing():
				wait_for_abort(20); continue
			font_utils.execute_custom_fonts()
			wait_for_abort(10)
		try: del monitor
		except: pass
		try: del player
		except: pass
		return logger('Fen Light', 'CustomFonts Service Finished')

class TraktMonitor:
	def run(self):
		logger('Fen Light', 'TraktMonitor Service Starting')
		from apis.trakt_api import trakt_sync_activities, trakt_ensure_token
		from caches.settings_cache import get_setting
		from modules.kodi_utils import run_plugin, refresh_age, playback_running, search_running
		from modules.settings import trakt_sync_interval
		monitor, player, window = xbmc.Monitor(), xbmc.Player(), xbmcgui.Window(10000)
		wait_for_abort, is_playing = monitor.waitForAbort, player.isPlayingVideo
		while not monitor.abortRequested():
			# LOTTO 210 -- LA GUARDIA GUARDAVA IL SEGNALE SBAGLIATO.
			# isPlayingVideo() diventa vero solo quando Kodi ha davvero un flusso video, cioe' a
			# Player.OnAVStart. Fra il momento in cui l'utente sceglie la sorgente e quell'istante
			# passano secondi -- il 09/09 sulla stick 15:42:58 (Select) -> 15:43:11.9 (OnAVStart),
			# quattordici -- e in quella finestra questa guardia diceva 'non si sta riproducendo'.
			# Alle 15:43:08, cinque secondi dopo che il player era gia' partito, il monitor si e'
			# svegliato, ha sincronizzato con Trakt e ha chiesto un ridisegno. A valle
			# _defer_refresh_if_busy usa Player.HasVideo, che li' era gia' vero: l'ha rimandato
			# buttando id e azioni, e alla chiusura dell'episodio e' uscito un UpdateLibrary globale.
			# Due definizioni diverse di 'sta riproducendo' nello stesso percorso.
			# playback_running() legge fenlight.playback.active, che il player alza PRIMA di play()
			# (player.py:159, 'l'unico istante che non e' una corsa') e abbassa alla chiusura: e'
			# l'unico segnale che copre anche l'apertura del file. Durante una riproduzione queste
			# dinamiche non devono esistere, ed e' questa la riga che lo garantisce.
			# LOTTO 238 -- e search_running() accanto, per la fase PRIMA di play(): scraping,
			# controllo cache, sonda della linea, filtri. Vedi kodi_utils.SEARCH_ACTIVE_PROP.
			while is_playing() or playback_running() or search_running() \
					or window.getProperty(pause_services_prop) == 'true':
				wait_for_abort(10)
			# Prima del giro di sincronizzazione, cioe' sempre mentre non si sta riproducendo nulla.
			refresh_official_status()
			# LOTTO 236 -- il token lo tiene fresco il servizio, che e' l'unico processo che esiste
			# prima dei widget e vive quanto Kodi. Se il rinnovo avviene qui, gli interpreti del
			# plugin trovano un token gia' buono e non si mettono in coda sul lucchetto.
			trakt_ensure_token()
			wait_time = 1800
			try:
				sync_interval, wait_time = trakt_sync_interval()
				next_update_string = update_string % sync_interval
				status = trakt_sync_activities()
				if status == 'failed': logger('Fen Light', trakt_service_string % ('Failed. Error from Trakt', next_update_string))
				else:
					if status in ('success', 'no account'): logger('Fen Light', trakt_service_string % ('Success. %s' % trakt_success_line_dict[status], next_update_string))
					else: logger('Fen Light', trakt_service_string % ('Success. No Changes Needed', next_update_string))# 'not needed'
					# Le due ondate di ricostruzione dopo una riproduzione erano lo STESSO evento contato due
					# volte: a fine film scriviamo su Trakt, il poll successivo lo rilegge come
					# 'qualcosa e' cambiato' e ricostruisce tutto una seconda volta per lo stesso titolo.
					# Nel log del Mac del 21/08: scan alle 23:37:44.874 (il nostro flush post-riproduzione) e
					# di nuovo alle 23:37:51.969, 62 ms dopo 'Trakt Update Performed'. Se l'interfaccia e'
					# stata ricostruita da poco, la ricostruzione di Trakt e' quasi certamente per il
					# cambiamento che l'ha appena innescata -- e allora si RIMANDA, non si butta.
					if status == 'success':
						# Quali titoli sono cambiati lo pubblica trakt_sync_activities dopo la
						# ricostruzione (lotto 59). Trakt non lo dice mai -- last_activities da solo
						# marche temporali per categoria -- ma il confronto fra l'insieme prima e
						# quello dopo lo sa. Tre stati: '' non lo sappiamo -> globale come prima;
						# '-' nulla e' cambiato davvero -> non si ricostruisce niente; altrimenti
						# ricarica MIRATA dei soli contenitori che contengono quegli id.
						# Si leggono SEMPRE ED ENTRAMBI, e si azzerano SEMPRE: lasciarli scritti li fa
						# rileggere al giro dopo, quando sono gia' stati sovrascritti (lotto 139).
						changed = window.getProperty('fenlight.trakt.changed_ids')
						window.clearProperty('fenlight.trakt.changed_ids')
						# Le AZIONI viaggiano accanto agli id (lotto 119) e sono un canale a se': un
						# 'paused_at' su un film che ENTRA adesso in 'continua a guardare' non ha ancora
						# il suo id nell'elenco pubblicato dal widget, quindi la regola per id lo
						# scarterebbe proprio mentre va ricostruito. Lo stesso vale per la watchlist.
						# Non c'e' un valore '-' per le azioni: '' significa semplicemente 'nessuna'.
						actions = window.getProperty('fenlight.trakt.changed_actions')
						window.clearProperty('fenlight.trakt.changed_actions')
						# La lettura e l'azzeramento stanno SOPRA questa condizione, non sotto (lotto 140):
						# con la ricostruzione dei widget disattivata i due canali non venivano ne' letti
						# ne' cancellati, e restavano scritti a tempo indeterminato. Nessun danno oggi --
						# nessuno li legge -- ma e' esattamente la forma del guasto del lotto 139, dove un
						# valore lasciato in una proprieta' e' stato poi sovrascritto e perso. Si azzera
						# cio' che si e' consumato, sempre, e la decisione di disegnare viene dopo.
						# NIENTE `continue` QUI: l'attesa del ciclo (wait_for_abort) sta FUORI dal try,
						# in fondo al giro, quindi saltarla farebbe girare il monitor a vuoto a piena
						# velocita' contro Trakt. Si annida, e basta.
						if get_setting('fenlight.trakt.refresh_widgets', 'false') == 'true':
							age = refresh_age()
							# La decisione sta in decide_refresh, che e' pura e provata. Qui si esegue e basta.
							cosa, ids, acts = decide_refresh(changed, actions, age, TRAKT_REFRESH_COALESCE)
							if cosa == 'niente':
								logger('Fen Light', 'TraktMonitor: nessun titolo cambiato davvero, nessuna ricostruzione')
							# LOTTO 179. `changed == '-'` vuol dire "lo sappiamo, non e' cambiato nessuno":
							# decide_refresh lo fonde con "non lo sappiamo" quando rimanda, e a valle i
							# due casi diventano indistinguibili. Qui la distinzione c'e' ancora, e
							# viaggia col rinvio: e' cio' che permette di non ridisegnare due volte lo
							# stesso widget senza tornare a una guardia a tempo.
							elif cosa == 'rinvio': self._defer_widget_refresh(window, ids, acts, age, changed == '-')
							elif cosa == 'mirato':
								logger('Fen Light', 'TraktMonitor: refresh MIRATO su %d titoli e %d azioni%s'
										% (len(ids.split(',')) if ids else 0, len(acts.split(',')) if acts else 0,
											(' [%s]' % acts) if acts else ''))
								refresh_ids_inproc(ids, acts)
							else: run_plugin({'mode': 'kodi_refresh'})
			except Exception as e: logger('Fen Light', trakt_service_string % ('Failed', 'The following Error Occured: %s' % str(e)))
			wait_for_abort(wait_time)
		try: del monitor
		except: pass
		try: del player
		except: pass
		return logger('Fen Light', 'TraktMonitor Service Finished')

	def _defer_widget_refresh(self, window, changed, actions, age, nochange=False):
		# La guardia dell'accorpamento vieta di ricostruire ADESSO, e ha ragione: all'avvio scatta
		# sempre, perche' stamp_startup_rebuild timbra la costruzione iniziale dei widget come
		# ricostruzione globale, e senza di lei la prima sincronizzazione ordinava UpdateLibrary sopra
		# la costruzione ancora in corso (due volte gli stessi widget in quindici secondi, ogni avvio).
		# Aveva pero' torto sul METODO: usciva buttando l'elenco dei titoli cambiati, e quei widget
		# restavano vecchi finche' l'utente non usciva e rientrava nella Home. Nei log del 28/08 due
		# sincronizzazioni su due hanno rilevato un cambiamento e due su due l'hanno perso.
		# E' il caso peggiore possibile, per due motivi che si sommano: il sync dell'avvio copre tutto
		# l'intervallo da quando Kodi era acceso l'ultima volta -- ore o giorni, contro i 30 s di un
		# poll -- ed e' quindi quello con piu' probabilita' di trovare qualcosa; e quando trova qualcosa
		# e' anche il piu' lento (7,0 s contro 4,45 misurati il 28/08, per il token da rinnovare, il
		# remap TMDb e il sync incrementale), quindi e' anche quello che perde la corsa con i widget.
		# Ora il cambiamento non si esegue: si RIMANDA, sul canale che WidgetRefresher gia' raccoglie
		# per gli altri due casi in cui si sa cosa mostrare ma non e' il momento di disegnarlo
		# (riproduzione in corso, e finestra Video del lotto 60). Lui aspetta di essere sulla Home e
		# fuori dalla tempesta: 20 s di attesa iniziale piu' 10 di ciclo, cioe' ~37 s dall'apertura
		# contro i ~12,5 in cui la home si assesta. Margine abbondante, per ora voluto: stringerlo e'
		# una regolazione da fare dopo aver visto il meccanismo in un log vero.
		# La somma la fa queue_pending_refresh (lotto 136): un rinvio globale in coda e' un superset e
		# non si restringe, uno senza id vuol dire 'tutto', e per il resto id e azioni si SOMMANO --
		# sono due cambiamenti distinti che nessuno ha ancora mostrato, e chi arriva secondo non ha
		# titolo per cancellare il primo. Quella logica era scritta qui e altre due volte in
		# kodi_utils, dove sovrascriveva; ora ha una sola implementazione.
		# scope='': questo rinvio nasce da un cambiamento vero su Trakt e vale in qualunque finestra
		# mostri widget, quindi cancella l'eventuale marca lasciata dalla rete di sicurezza.
		from modules.kodi_utils import queue_pending_refresh, PENDING_IDS_PROP, PENDING_ACTIONS_PROP
		_ids = [i for i in changed.split(',') if i]
		_acts = [a for a in actions.split(',') if a]
		if queue_pending_refresh('kodi_refresh_ids' if (_ids or _acts) else 'kodi_refresh',
									_ids, _acts, scope='', nochange=nochange):
			return logger('Fen Light', 'TraktMonitor: refresh GLOBALE rimandato, interfaccia ricostruita %.1fs fa' % age)
		ids = [i for i in window.getProperty(PENDING_IDS_PROP).split(',') if i]
		acts = [a for a in window.getProperty(PENDING_ACTIONS_PROP).split(',') if a]
		logger('Fen Light', 'TraktMonitor: refresh MIRATO rimandato su %d titoli e %d azioni%s, interfaccia ricostruita %.1fs fa'
				% (len(ids), len(acts), (' [%s]' % ','.join(acts)) if acts else '', age))

class WidgetRefresher:
	def run(self):
		logger('Fen Light', 'WidgetRefresher Service Starting')
		from time import time
		from caches.settings_cache import get_setting
		from modules.kodi_utils import home, run_plugin, PENDING_REFRESH_PROP, PENDING_IDS_PROP, PENDING_ACTIONS_PROP, PENDING_SCOPE_PROP, PENDING_NOCHANGE_PROP, refresh_flag_expired, modal_dialog_open, pending_refresh_is_redundant, playback_running, decide_pending_refresh, search_running
		self.playback_running, self.search_running = playback_running, search_running
		self.modal_dialog_open = modal_dialog_open
		self.refresh_flag_expired = refresh_flag_expired
		monitor, player = xbmc.Monitor(), xbmc.Player()
		wait_for_abort, self.is_playing = monitor.waitForAbort, player.isPlayingVideo
		self.window = xbmcgui.Window(10000)
		self.get_setting = get_setting
		self.home = home
		self.window.setProperty('fenlight.refresh_widgets', 'true')
		self.set_next_refresh(time())
		self.pending_since = None
		# NIENTE ATTESA FISSA ALL'AVVIO, e niente cadenza da dieci secondi per il rinvio (lotto 106).
		# I 20 secondi qui e i 10 del giro servivano a lasciar passare la tempesta d'avvio a occhio: il
		# rinvio nasceva verso il quindicesimo secondo e si consumava verso il trentasettesimo, cioe'
		# oltre venti secondi di attesa morta con l'interfaccia disallineata da Trakt.
		# Ora la tempesta si riconosce da sola: ogni costruzione dichiara "sto costruendo"
		# (paginator.INFLIGHT_PROP, alzata in passi_da_caricare e abbassata in set_head) e il rinvio parte
		# APPENA l'ultima si spegne. Nessun numero da indovinare.
		# Il giro e' di un secondo perche' la reazione dev'essere pronta, ma il lavoro periodico resta
		# a dieci (contatore `tick`): quando non c'e' nessun rinvio in attesa il giro veloce costa una
		# sola lettura di proprieta' di finestra, che Kodi serve dalla memoria.
		tick = 0
		while not monitor.abortRequested():
			try:
				wait_for_abort(1)
				_kind_rinvio = self.window.getProperty(PENDING_REFRESH_PROP)
				if _kind_rinvio:
					if self.pending_since is None: self.pending_since = time()
					# modal_dialog_open() sta QUI e non solo in kodi_refresh_ids (lotto 136). Senza, il
					# rinvio nato per il dialogo verrebbe consumato al giro dopo, ririmandato da
					# _defer_refresh_if_busy, riconsumato... un giro al secondo per tutta la durata del
					# dialogo, e con pending_since azzerato ogni volta. Qui si aspetta in silenzio.
					if not self.is_playing() and not self.modal_dialog_open() \
							and self._nothing_building() and self._widgets_on_screen():
						pending_ids = self.window.getProperty(PENDING_IDS_PROP)
						pending_actions = self.window.getProperty(PENDING_ACTIONS_PROP)
						# LOTTO 179. Unico caso in cui un rinvio si spegne invece di essere disegnato:
						# la sincronizzazione ha dichiarato zero titoli cambiati E cio' che il rinvio
						# chiederebbe e' gia' tutto a schermo. Non e' l'accorpamento a tempo del lotto
						# 130 -- quello bocciava anche i rinvii che portavano roba nuova -- ne' la
						# guardia del lotto 139, che deduceva "e' gia' a schermo" da un timbro. Vedi
						# kodi_utils.pending_refresh_is_redundant.
						_inutile = pending_refresh_is_redundant(
								[i for i in pending_ids.split(',') if i],
								[a for a in pending_actions.split(',') if a])
						self.window.clearProperty(PENDING_REFRESH_PROP)
						self.window.clearProperty(PENDING_IDS_PROP)
						self.window.clearProperty(PENDING_ACTIONS_PROP)
						self.window.clearProperty(PENDING_SCOPE_PROP)
						self.window.clearProperty(PENDING_NOCHANGE_PROP)
						logger('Fen Light', 'WidgetRefresher: rinvio consumato dopo %.1fs di attesa, nessuna costruzione in volo'
								% (time() - self.pending_since))
						self.pending_since = None
						# Con gli id si ricaricano i soli contenitori che li contengono; senza, si ricade
						# sul globale come prima. Vedi lotto 60: gli id c'erano gia' e venivano buttati qui.
						# Le azioni bastano da sole (lotto 119): un rinvio che porta solo
						# 'continue_watching' o 'trakt_watchlist:movie' e' un rinvio MIRATO a tutti gli
						# effetti, e degradarlo a globale perche' l'elenco di id e' vuoto sarebbe
						# esattamente il difetto che il canale delle azioni esiste per togliere.
						# coalesce=False, ed e' il punto del lotto 130. Un rinvio e' per definizione lavoro
						# NON ancora fatto: e' nato perche' in quel momento non si poteva disegnare. Qui
						# ha gia' aspettato le sue condizioni -- niente riproduzione, nessuna costruzione
						# in volo, widget a schermo -- e ripassarlo sotto l'accorpamento significa
						# giudicarlo una seconda volta con la stessa guardia che l'aveva fatto rimandare.
						# All'avvio quel secondo giudizio lo bocciava SEMPRE: stamp_startup_rebuild timbra
						# la costruzione iniziale come globale ('*'), che copre qualunque elenco di id, e
						# fra il timbro e il rinvio maturo passano un paio di secondi, cioe' meno dei 5
						# di REFRESH_COALESCE_SECONDS. Nel log del Mac del 02/09 alle 21:15:44.299:
						# 'refresh mirato accorpato: gli stessi id ricostruiti 2.04s fa'. Quei 2.04s
						# erano la costruzione d'avvio, avvenuta PRIMA della sincronizzazione e quindi
						# fatta sui dati vecchi: aveva davvero ricostruito quegli id, e li aveva
						# ricostruiti sbagliati. Dopo, ogni poll dice 'not needed' -- reset_activity ha
						# gia' fatto avanzare il segnalibro -- e l'interfaccia resta indietro finche'
						# non la si ricostruisce a mano. Otto titoli tolti dalla stick, zero
						# ricostruzioni nei sei minuti successivi.
						# La protezione che stamp_startup_rebuild doveva dare non si perde: quella
						# vietava di ordinare una ricostruzione SOPRA la costruzione d'avvio ancora in
						# corso, e a garantirla e' _nothing_building() qui sopra, non l'accorpamento.
						# LOTTO 210 -- la decisione sta in decide_pending_refresh, che e' pura e provata.
						# Qui si esegue e basta, come gia' per decide_refresh nel monitor Trakt.
						_cosa = decide_pending_refresh(_kind_rinvio, pending_ids, pending_actions, _inutile)
						if _cosa == 'niente':
							logger('Fen Light', 'WidgetRefresher: rinvio spento, nessun titolo cambiato e i widget richiesti [%s] sono gia\' quelli appena ricostruiti'
									% (pending_actions or pending_ids or '-'))
						elif _cosa == 'mirato':
							refresh_ids_inproc(pending_ids, pending_actions, coalesce=False)
						elif _cosa == 'strappata':
							# Tipo mirato ma canali vuoti: qualcuno stava azzerando mentre leggevamo.
							# Chi azzera lo fa perche' sta gia' ridisegnando lui -- e' il caso di
							# player._order_refresh_after_write -- quindi qui non manca niente da
							# mostrare, e ricostruire tutto sarebbe la reazione piu' costosa possibile
							# al piu' piccolo dei disallineamenti.
							logger('Fen Light', 'WidgetRefresher: rinvio letto a meta\' (tipo %s, nessun id ne\' azione): '
									'lo sta gia\' consumando qualcun altro, nessuna ricostruzione' % _kind_rinvio)
						else: run_plugin({'mode': 'refresh_widgets', 'coalesce': 'false'})
				elif self.pending_since is not None: self.pending_since = None
				tick += 1
				if tick < 10: continue
				tick = 0
				# I segnali di "ricostruzione in corso" non li spegne piu' chi li accende: prima li
				# teneva alzati uno sleep(2000) dentro l'invocazione del plugin, cioe' due secondi di
				# interprete Python vivo a non fare nulla (vedi hold_refresh_flag). Ora li spegne
				# questo servizio, che gira gia', e solo a scadenza avvenuta -- sulla stick fra
				# l'ordine di ricarica e la prima costruzione passano 11 secondi, spegnerli subito
				# li renderebbe inutili proprio dove servono.
				if self.refresh_flag_expired():
					self.window.clearProperty('fenlight.refresh_widgets')
					self.window.clearProperty('fenlight.pg.refresh')
				# Rete di sicurezza per il refresh rimandato durante la riproduzione: se il video non e'
				# passato da FenLightPlayer (video generico, trailer) nessuno lo rilancia alla chiusura,
				# e il widget resterebbe vecchio. Qui si recupera appena la riproduzione e' finita.
				playing = self.is_playing()
				# Il rinvio non si consuma piu' qui: sta nel giro veloce di un secondo, sopra. La
				# condizione su quale finestra lo ammette resta la stessa (_widgets_on_screen).
				# In riproduzione si esce QUI. Sotto c'e' get_setting, che quando la chiave non e' anche
				# una proprieta' di finestra ricade su una query SQLite: era una lettura da disco ogni
				# 10s per tutta la durata del film, sulla stessa eMMC su cui il player scrive la cache
				# dello stream. condition_check() scartava comunque il giro, ma solo DOPO averla pagata.
				# Stesso difetto gia' corretto per WidgetPaginator nel lotto 27 ter.
				if playing: continue
				offset = int(self.get_setting('fenlight.widget_refresh_timer', '60'))
				if offset != self.offset:
					self.set_next_refresh(time())
					continue
				if self.condition_check(): continue
				if self.next_refresh < time():
					run_plugin({'mode': 'refresh_widgets', 'show_notification': self.get_setting('fenlight.widget_refresh_notification', 'false')}, block=True)
					logger('Fen Light', 'WidgetRefresher Service - Widgets Refreshed')
					self.set_next_refresh(time())
			except: pass
		try: del monitor
		except: pass
		try: del player
		except: pass
		return logger('Fen Light', 'WidgetRefresher Service Finished')

	def _nothing_building(self):
		# La condizione che ha sostituito l'attesa a tempo. Non e' "sono passati N secondi", e'
		# "nessuno ha dichiarato di stare costruendo": vedi paginator.INFLIGHT_PROP.
		# In caso di errore torna True: un rinvio in ritardo e' un fastidio, un rinvio che non parte
		# piu' e' un guasto -- la lezione del lotto 100.
		from modules import paginator
		try: return not paginator.builds_in_flight()
		except: return True

	def _widgets_on_screen(self):
		# Dove il rinvio si puo' consumare senza fare danni.
		# La condizione e' passata per tre stadi. Prima era 'diverso da 10025', cioe' ovunque tranne il
		# player. Poi fu stretta alla sola Home, con questa motivazione: 'Container(N).ListItem...' non
		# risolve per una finestra che non e' a schermo, quindi una ricarica mirata lanciata da un hub
		# raggiungerebbe i widget dell'hub e nient'altro, lasciando la Home vecchia.
		# QUELLA MOTIVAZIONE E' CADUTA COL CENSIMENTO DEL LOTTO 69. refresh_containers_for_ids fa due
		# cose nello stesso istante: ricarica i contenitori a schermo, e cambia i token di quelli
		# censiti nelle ALTRE finestre, che Kodi rilegge quando tornano a schermo -- e' la voce
		# 'altre finestre N' del DIAG. Nessuna finestra resta indietro, da qualunque si parta.
		# Restare vincolati alla Home aveva quindi un solo effetto: un hub vecchio restava vecchio
		# proprio mentre lo si stava guardando, e si allineava solo passando dalla Home. Misurato il
		# 28/08 alle 19:38 (lotto 99): l'hub era giusto per fortuna di tempistica -- costruito dopo il
		# sync -- e entrandoci qualche secondo prima sarebbe rimasto sbagliato a tempo indeterminato.
		# Non basta pero' allargare a 'qualunque finestra tranne il player'. Se qui dentro non c'e'
		# nessun contenitore Fen Light, refresh_containers_for_ids torna 0 e kodi_refresh_ids RICADE
		# SUL GLOBALE ('nessun contenitore identificato'): un rinvio mirato su un titolo diventerebbe
		# un UpdateLibrary su tutto, per il solo fatto di trovarsi nelle impostazioni quando scade il
		# giro. Percio' non si indovina e non si tiene una lista di id da aggiornare a mano quando la
		# skin cambia: si chiede al censimento se in QUESTA finestra dei widget ci sono mai stati.
		from modules.kodi_utils import getCurrentWindowId, PENDING_SCOPE_PROP
		from modules import paginator
		try:
			wid = getCurrentWindowId()
			if wid == 10025: return False
			scope = paginator.ctl_scope()
			# Un riarmo della rete di sicurezza e' lavoro destinato ad ALTRE finestre: riconsumarlo qui
			# non farebbe nulla di utile e lo rimetterebbe in coda identico, un giro ogni 10 s senza fine.
			# Osservato il 28/08 alle 20:18-20:19, tre giri in venti secondi, restando nell'hub.
			# La rete di sicurezza non scatta mai dalla Home, quindi questa marca non puo' valere 'home'.
			if self.window.getProperty(PENDING_SCOPE_PROP) == scope: return False
			# La Home e' ammessa SEMPRE: e' la finestra dei widget per definizione ed era la condizione
			# storica. Il censimento serve a giudicare le ALTRE, che possono benissimo non avere widget.
			# Senza questa riga un rinvio resterebbe bloccato per sempre tutte le volte che i widget della
			# Home non hanno fatto in tempo a farsi censire -- che e' esattamente il caso del 28/08.
			if wid == 10000: return True
			return any(p.partition(':')[0] == scope for p in paginator.registry_pairs())
		except: return False

	def condition_check(self):
		if not self.home(): return True
		# playback_running() accanto a is_playing() per la stessa ragione del monitor Trakt (lotto
		# 210): questo ramo ordina refresh_widgets, cioe' un UpdateLibrary globale, e non deve poterlo
		# fare nella finestra in cui il file si sta aprendo e isPlayingVideo() risponde ancora di no.
		# LOTTO 238 -- e search_running() accanto, per la fase PRIMA di play(): scraping,
		# controllo cache, sonda della linea, filtri. Vedi kodi_utils.SEARCH_ACTIVE_PROP.
		if self.next_refresh == None or self.is_playing() or self.playback_running() \
				or self.search_running() or self.window.getProperty(pause_services_prop) == 'true': return True
		if self.window.getProperty('fenlight.window_loaded') == 'true': return True 
		try:
			# json e' PIGRO (lotto 204), e questo e' il suo unico uso in tutto il file. Misurato sulla
			# stick il 08/09 col profilatore in cima: la nascita del servizio costava 864 ms di import,
			# tutti di libreria standard (Fen Light: 0 ms), e la catena che pende SOLO da json --
			# json, decoder, encoder, _json, re con le sue tabelle, enum, copyreg -- ne vale ~373.
			# Il resto (collections, functools, operator, itertools, _weakrefset) lo tira `threading`
			# per conto suo, verificato importandolo da solo, quindi resta e non c'e' niente da fare.
			# Qui dentro l'import costa una ricerca in sys.modules per chiamata, su un metodo che
			# gira a widget gia' costruiti.
			import json
			window_stack = json.loads(self.window.getProperty('fenlight.window_stack'))
			if isinstance(window_stack, list): return True
		except: pass
		return False

	def set_next_refresh(self, _time):
		self.offset = int(self.get_setting('fenlight.widget_refresh_timer', '60'))
		if self.offset: self.next_refresh = _time + (self.offset*60)
		else: self.next_refresh = None

class WidgetPaginator:
	# Drives interactive "infinite scroll" pagination for home widgets. While a Fen Light widget is
	# focused it polls its scroll position; when the focus enters the last loaded page it bumps the
	# widget's page count (a Window(10000) property keyed per widget) and triggers a silent
	# Container.Refresh, so the plugin appends the next page in place and the focus is preserved.
	def run(self):
		logger('Fen Light', 'WidgetPaginator Service Starting')
		from time import time
		from modules import paginator, cw_head
		from modules.kodi_utils import search_running
		monitor, player = xbmc.Monitor(), xbmc.Player()
		wait_for_abort, is_playing = monitor.waitForAbort, player.isPlayingVideo
		window = xbmcgui.Window(10000)
		get_infolabel = xbmc.getInfoLabel
		pending = {}  # key -> time the loading flag was set, to self-heal a build that never finishes
		# Timeout di autoguarigione per una build che non finisce mai. NON abbassarlo senza misurare:
		# se scade MENTRE la build sta ancora lavorando, il flag LOADING viene tolto sotto i piedi e
		# passi_da_caricare() -- che lo legge per decidere se ricostruire N pagine o solo il lotto iniziale --
		# fa collassare il widget alla prima pagina. Sul Mi Stick una ricostruzione cumulativa supera
		# regolarmente gli 8 secondi originali (interprete Python nuovo a ogni build + tutti i widget
		# ricostruiti insieme dall'UpdateLibrary globale): era questa la ragione per cui in home la
		# paginazione non avanzava mai e in cerca si fermava dopo qualche pagina.
		stuck_timeout = 90
		# Secondo timeout, molto piu' corto, per una domanda DIVERSA: non "la build e' lenta?" ma "la
		# build e' mai partita?". Scritto il token, la skin rilegge il <content> e Kodi lancia il plugin
		# entro un attimo -- passi_da_caricare timbra LASTBUILD prima di qualunque lavoro, quindi il timbro
		# arriva anche se poi la costruzione dura mezzo minuto. Se dopo questo tempo non e' arrivato
		# NIENTE, il widget non sta leggendo il token: e' un disallineamento fra addon e skin, non
		# lentezza. Vedi LASTBUILD_PROP in paginator.py per il caso reale che lo ha reso necessario.
		no_build_timeout = 20
		token_written = {}   # key -> (istante del TRIGGER, scope, id contenitore, nome proprieta')
		# key -> (istante in cui la chiave e' comparsa in coda, movimento gia' ordinato?). Vedi lotto 166.
		rehead_moved = {}
		# LOTTO 216, le due memorie di lavoro del riposizionamento di 'continua a guardare'. Stanno in
		# RAM e non in una proprieta' apposta: perderle (servizio riavviato a meta') non puo' produrre
		# un esito sbagliato, solo un giro in piu'. Il debito, che invece non si puo' perdere, sta
		# nella proprieta' di cw_head.
		cw_focus = {}   # key -> la riga aveva il fuoco al giro scorso?
		cw_moved = {}   # key -> (istante dell'ultimo Control.Move, quanti ne sono stati ordinati)
		token_reported = set()  # una diagnosi per chiave per sessione: e' un guasto di configurazione, non un evento
		last_current = {}  # key -> last observed focus index, so we load ahead on real downward movement only
		last_log = None  # dedup: only log when the observed state actually changes
		last_scope, census_tick = None, 0  # finestra censita e da quanti giri: vedi CENSUS_TICKS
		# La voce watchlist del menu contestuale: vedi modules/watchlist_label.py.
		from modules.watchlist_label import Tracker as WatchlistLabel
		watchlist_label = WatchlistLabel(log=paginator.log)
		def log_change(state):
			nonlocal last_log
			if state != last_log:
				paginator.log('watcher %s' % state); last_log = state
		while not monitor.abortRequested():
			try:
				# is_playing() PRIMA di get_setting: quest'ultima, quando la chiave non e' anche una
				# proprieta' di finestra, finisce in una query SQLite. Nell'ordine precedente era una
				# lettura da disco al secondo per tutta la durata del film, sulla stessa eMMC lenta su
				# cui il player sta scrivendo la cache dello stream.
				# LOTTO 238 -- search_running(): paginare un widget mentre l'utente aspetta le sorgenti
				# toglie cpu allo scraping e alla sonda. Vedi kodi_utils.SEARCH_ACTIVE_PROP.
				if is_playing() or search_running() or window.getProperty(pause_services_prop) == 'true':
					log_change('idle (off/playing/paused/ricerca)')
					wait_for_abort(1); continue
				# Never paginate a widget inside an overlay dialog (e.g. the video-info card). Its related
				# lists (cast/recommendations/credits/sets) are bounded, not meant for infinite scroll, and the
				# only widget-refresh primitive available is the GLOBAL UpdateLibrary hack -- it would rebuild
				# every DirectoryProvider in the dialog at once and flicker the whole card. Home/hubs/search,
				# the intended browsing contexts, all live in non-modal windows, so this never gates them.
				# LOTTO 286 -- modal_dialog_present e non modal_dialog_open: questo giro e' periodico, e
				# getCondVisibility farebbe dormire il ciclo della GUI a ogni passaggio. Vedi kodi_utils.
				# La stessa lettura (getCurrentWindowDialogId, solo il lock grafico) serve anche alla voce
				# watchlist qui sotto, quindi si fa una volta.
				dialogo = xbmcgui.getCurrentWindowDialogId()
				# La voce watchlist del menu contestuale (modules/watchlist_label.py) segue l'elemento a fuoco
				# OVUNQUE, dialoghi compresi: per questo sta prima del cancello dei modali, che vale per la
				# paginazione e non per lei. System.CurrentControlID e Container(N) si risolvono entrambi
				# contro la finestra o il dialogo in primo piano (PR.md, voce 12), quindi home, hub, ricerca,
				# righe della scheda informazioni e cartelle di Fen Light sono lo stesso caso. Col menu
				# contestuale aperto no: la proprieta' deve restare quella dell'elemento su cui si e' aperto.
				# Il controllo a fuoco si leggeva comunque qui sotto per la paginazione: e' la stessa lettura,
				# anticipata. Un errore qui non deve fermare il paginatore.
				cur_ctrl = ''
				if dialogo != CONTEXT_MENU_DIALOG:
					cur_ctrl = get_infolabel('System.CurrentControlID')
					try: watchlist_label.update(cur_ctrl, get_infolabel, window)
					except Exception as e: logger('Fen Light', 'watchlist_label: errore %s' % e)
				if dialogo != NO_DIALOG:
					log_change('idle (modal dialog open)')
					wait_for_abort(0.5); continue
				# Identify the focused Fen Light widget by container id (skin sets fenlight.active_widget on focus
				# for every widget) and resolve its key via the universal first-item bridge: the plugin published
				# first-item-path -> key, and we read that same path from the container here. cur_ctrl e' gia'
				# stato letto sopra, per la voce watchlist: senza dialoghi il ramo che lo legge e' sempre preso.
				# Gli id dei contenitori si ripetono fra finestre (il generatore riparte da 501 per
				# ognuna), quindi ogni token va indicizzato anche per finestra: vedi paginator.ctl_scope.
				scope = paginator.ctl_scope()
				# Censimento dei contenitori di QUESTA finestra, una volta sola per passaggio. Costa una
				# ventina di infolabel al cambio di finestra e serve alla ricarica mirata per raggiungere
				# i widget delle finestre NON a schermo, dove le infolabel non arrivano: senza, un film
				# azzerato dalla Home lasciava l'hub vecchio (e viceversa). Vedi paginator.registry_add.
				# Un solo censimento al cambio di finestra NON basta, e il log delle 19:08 lo mostra:
				# entrando in Home alle 19:08:10.967 i provider partono 2 ms dopo, quindi quando il
				# censimento passava i contenitori erano ancora VUOTI, non registrava niente e la sua
				# unica occasione era bruciata. Alle 19:08:27, agendo dall'hub, la Home risultava non
				# censita ('altre finestre 0') e si ricadeva sul rinvio.
				# Si ripassa quindi a scatti finche' i widget non hanno finito di costruirsi: i tick
				# sono da 0,3 s, quindi 0 / 1,5 / 3 / 6 / 10,5 / 16,5 secondi. Sei passate da ~20
				# infolabel ciascuna per cambio di finestra, non una al secondo per sempre.
				if scope != last_scope:
					last_scope, census_tick = scope, 0
				else:
					census_tick += 1
				if census_tick in CENSUS_TICKS:
					for cid in paginator.WIDGET_CONTAINER_IDS:
						ckey, curl = paginator.container_head(cid, scope)
						if not ckey: continue
						# LOTTO 92: qui stava il controllo di cambio inquilino, che azzerava il token quando
						# la chiave dedotta dal contenuto non corrispondeva a quella registrata. Adesso lo fa
						# la BUILD (paginator.reconcile_position), che il contenuto lo conosce invece di
						# dedurlo. Era questo il punto da cui partiva il danno dei lotti 90-91: bastava
						# un'identificazione sbagliata perche' il watcher cancellasse il token del widget
						# giusto. Il censimento ora si limita a censire.
						paginator.registry_add(scope, cid)
				# LOTTO 216 -- 'continua a guardare' torna sul primo elemento quando arriva un titolo
				# nuovo, e solo allora. La regola sta per esteso in modules/cw_head.py; qui c'e' la
				# parte che solo il servizio puo' fare, cioe' guardare il contenitore DOPO che Kodi lo
				# ha aggiornato e sapere dove sta il fuoco.
				#
				# IL CANCELLO DEL FUOCO, e la sua unica sottigliezza. Non si tocca una riga su cui
				# l'utente sta scegliendo: se ha il fuoco, il debito aspetta. Ma la domanda giusta non
				# e' 'ha il fuoco adesso', e' 'ce l'aveva GIA' al giro scorso' -- altrimenti chi rientra
				# in Home da un hub e trova il fuoco atterrato proprio su questa riga non vedrebbe mai
				# il titolo nuovo, che e' il caso da cui e' partito tutto. Con 'al giro scorso':
				#   - stai dentro la riga da prima          -> il fuoco c'era anche al giro scorso, si aspetta
				#   - ci arrivi ora da un'altra riga        -> al giro scorso non c'era, si riporta in testa
				#     (ed e' quello che l'utente vuole: al rientro il fuoco sul primo elemento)
				#   - la finestra non era nemmeno a schermo -> per definizione non aveva il fuoco, si agisce
				# Alla PRIMA occhiata a un debito appena nato non c'e' un giro scorso, e allora vale
				# l'adesso: un titolo che arriva mentre stai nella riga non ti sposta niente.
				#
				# Il comando e' Control.Move e non SetFocus: SetFocus PORTEREBBE il fuoco sul widget, e
				# strappare l'utente da dov'e' sarebbe un danno peggiore del difetto. Control.Move manda
				# GUI_MSG_MOVE_OFFSET, che CGUIControlGroup consegna al controllo per ID senza toccare il
				# fuoco (Kodi 21.1: `return SendControlMessage(message)`), e che CGUIBaseContainer esegue
				# come N chiamate a MoveUp dentro UN SOLO messaggio: una scorsa sola, non N animazioni.
				# L'offset e' esattamente `1 - current`, e con il cursore oltre il primo elemento
				# l'ultimo passo ci arriva esatto senza eccedere.
				if window.getProperty(cw_head.PENDING_PROP):
					for ckey in cw_head.pending():
						cscope, _, ccid = ckey.rpartition('.')
						qui = cscope == scope and ccid.isdigit()
						fuoco = qui and ccid == cur_ctrl  # lotto 286: vedi il cancello del fuoco piu' sotto
						prima = cw_focus.get(ckey)
						cw_focus[ckey] = fuoco
						if not qui: continue          # altra finestra: il debito resta e si salda al ritorno
						if cw_head.hold(prima, fuoco): continue
						ccur = int(get_infolabel('Container(%s).CurrentItem' % ccid) or 0)
						mosso_da, tentativi = cw_moved.get(ckey, (None, 0))
						azione = cw_head.step(cw_head.head_of(ckey),
												get_infolabel('Container(%s).ListItemAbsolute(0).FolderPath' % ccid),
												ccur, xbmc.getCondVisibility('Container(%s).Scrolling' % ccid),
												mosso_da, tentativi, time())
						if azione == 'attendi': continue
						if azione == 'muovi':
							xbmc.executebuiltin('Control.Move(%s,%s)' % (ccid, 1 - ccur))
							cw_moved[ckey] = (time(), tentativi + 1)
							paginator.log('cw testa nuova key=%s: riga riportata in cima (era %s)'
											% (paginator.short(ckey), ccur))
							continue
						if azione == 'mollo':
							paginator.log('cw testa nuova key=%s: mollo dopo %s tentativi, il Control.Move '
											'non morde (fermo a %s)' % (paginator.short(ckey), tentativi, ccur))
						else:
							paginator.log('cw testa nuova key=%s: in testa e ferma, debito chiuso' % paginator.short(ckey))
						cw_head.done(ckey); cw_moved.pop(ckey, None); cw_focus.pop(ckey, None)
				# LOTTO 138 -- la riga si riporta in cima ANCHE se il widget non e' a fuoco.
				# Sta QUI, sopra il cancello del fuoco, e la posizione e' il punto del lotto. Nel 137 la
				# consumazione stava dentro il ramo del widget a fuoco, quindi con il fuoco sull'icona della
				# Home la riga restava scorsa sull'elemento vecchio finche' non ci si passava sopra -- e
				# allora si riposizionava di scatto. L'utente lo ha detto meglio di cosi': una modifica
				# fatta su Trakt compare a prescindere da dove sia il fuoco, e questo deve fare lo stesso.
				# Dal lotto 216 questa coda ha un committente solo, reconcile_position: 'continua a
				# guardare' ha una regola sua e un consumatore suo, qui sopra.
				# Il comando e' Control.Move e non SetFocus: SetFocus PORTEREBBE il fuoco sul widget, che
				# strappando l'utente dall'icona della Home sarebbe un danno peggiore del difetto.
				# Control.Move manda GUI_MSG_MOVE_OFFSET, che CGUIControlGroup consegna al controllo per ID
				# senza toccare il fuoco (Kodi 21.1: `return SendControlMessage(message)`), e che
				# CGUIBaseContainer esegue come N chiamate a MoveUp DENTRO UN SOLO messaggio -- quindi una
				# scorsa sola, non N animazioni.
				# L'offset e' esattamente `current-1`: MoveUp avvolge alla fine della lista SOLO se e' gia'
				# sul primo elemento, e con questo conto l'ultimo passo ci arriva esatto senza eccedere.
				# Un contenitore non ancora popolato (NumItems 0) resta in coda: la finestra puo' non essere
				# a schermo, e allora si riposiziona quando ci torna.
				# LOTTO 166 -- la chiave esce dalla coda quando il contenitore E' ARRIVATO, non quando gli
				# si ordina di partire. Prima rehead_done() stava PRIMA di Control.Move: dal lotto 165 la
				# skin tiene il row nascosto finche' la chiave e' in coda, quindi svuotarla li' scopriva il
				# row nell'istante esatto in cui cominciava uno scorrimento di 400 ms (List_Core,
				# <scrolltime>400</scrolltime>) -- cioe' il difetto che il 165 doveva togliere, intatto.
				# Adesso: si ordina il movimento una volta sola (rehead_moved), e si consuma la chiave solo
				# quando il cursore e' davvero in testa E lo scorrimento e' finito (Container(N).Scrolling).
				# Il tetto di REHEAD_TIMEOUT esiste perche' con il 165 una chiave incastrata non e' piu'
				# solo una riga fuori posto: terrebbe il row invisibile. Scaduto il tempo si molla, e il
				# peggio che resta e' il comportamento di prima.
				if window.getProperty(paginator.REHEAD_PROP):
					for rkey in paginator.rehead_pending():
						rscope, _, rcid = rkey.rpartition('.')
						if rscope != scope or not rcid.isdigit(): continue
						rnum = int(get_infolabel('Container(%s).NumItems' % rcid) or 0)
						rcur = int(get_infolabel('Container(%s).CurrentItem' % rcid) or 0)
						quando, mosso = rehead_moved.setdefault(rkey, (time(), False))
						azione = paginator.rehead_step(rnum, rcur, xbmc.getCondVisibility('Container(%s).Scrolling' % rcid),
														mosso, time() - quando)
						if azione == 'aspetta': continue
						if azione == 'muovi':
							xbmc.executebuiltin('Control.Move(%s,%s)' % (rcid, 1 - rcur))
							rehead_moved[rkey] = (quando, True)
							paginator.log('watcher testa nuova key=%s: riga riportata in cima (era %s/%s)'
											% (paginator.short(rkey), rcur, rnum))
							continue
						if azione == 'mollo':
							paginator.log('watcher testa nuova key=%s: mollo dopo %s s (fermo a %s/%s)'
											% (paginator.short(rkey), paginator.REHEAD_TIMEOUT, rcur, rnum))
						paginator.rehead_done(rkey); rehead_moved.pop(rkey, None)
				# LOTTO 286 -- il fuoco si confronta con System.CurrentControlID, letto in testa al giro,
				# invece di chiederlo con Control.HasFocus: quella passava da getCondVisibility, cioe' dalla
				# porta del FrameMove, una o due volte ogni 0,3 s. Equivalenza, Kodi 21.1: senza modali
				# (escluse sopra) entrambe guardano la finestra attiva (ModuleXbmc.cpp:365-367 contro
				# GetActiveWindowOrDialog, GUIWindowManager.cpp:1620-1629); Control.HasFocus confronta
				# GetFocusedControlID(), CurrentControlID l'id di GetFocusedControl() (GUIControlsGUIInfo.cpp
				# 323-332 e 663-670). Divergono solo se l'ultimo id registrato dalla finestra non ha piu' il
				# fuoco, e li' CurrentControlID e' quella giusta (GUIControlGroup.cpp GetFocusedControlID).
				# Il secondo ramo chiedeva Control.HasFocus(cur_ctrl): vero per definizione.
				prop_id = window.getProperty('fenlight.active_widget')
				widget_id = None
				if prop_id and prop_id == cur_ctrl:
					widget_id = prop_id
				elif cur_ctrl and 'plugin.video.fenlight' in get_infolabel('Container(%s).ListItemAbsolute(0).FolderPath' % cur_ctrl):
					widget_id = cur_ctrl
				if widget_id is None:
					log_change('idle cur_ctrl=%s prop=%s' % (cur_ctrl, prop_id))
					wait_for_abort(0.3); continue
				# LOTTO 217 -- L'INTESTAZIONE DEL MENU CONTESTUALE NELLE FINESTRE A WIDGET.
				#
				# 'TMDbHelper.ListItem.base_label' e 'base_poster' (nome vecchio, meccanismo tutto della
				# skin) sono cio' che il menu contestuale mostra su home, hub e ricerca: li' l'elemento
				# visibile sta in un contenitore che non ha il fuoco, e 'ListItem' nudo non lo vede.
				# Le scriveva solo l'onfocus del pulsante nascosto della riga widget, che e' un trigger
				# SUL FRONTE: scatta quando il fuoco si muove. Ma sotto un fuoco fermo l'elemento puo'
				# cambiare lo stesso -- il contenitore si ricostruisce -- e allora nessuno riscrive
				# niente. E l'onfocus e' anche guardato da !String.IsEmpty(ListItem.Label), messo il
				# 03/09 per non pubblicare il vuoto di meta' ricostruzione: giustissimo, ma vuol dire
				# che DURANTE una ricostruzione ogni spostamento del fuoco non scrive affatto.
				#
				# Le due cose insieme fanno il difetto misurato sulla stick il 10/09 alle 03:29:
				#   03:26:24.148  menu contestuale sull'elemento 6 di 1101.502 -> tmdb_id=1304313 (La Mummia)
				#   03:26:43      riproduzione, 03:29:15 stop, 03:29:16.192 Window Init (Custom_1101_Hub)
				#   03:29:16.533  contenitore 502 ricostruito (set_bookmark)   -> arriva 03:29:18.165
				#   03:29:20.378  contenitore 502 ricostruito (Trakt)          -> arriva 03:29:21.593
				#   03:29:20.581 / 21.030 / 21.245  tre Destra: 6 -> 7 -> 8 -> 9   TUTTI dentro la ricostruzione
				#   03:29:22.397  menu contestuale sull'elemento 9 -> tmdb_id=1233413 (Sinners)
				# Il menu di Kodi era giusto (playback_choice&meta=1233413); sbagliata era solo
				# l'intestazione della skin, ferma su La Mummia, cioe' sull'ultima scrittura riuscita
				# PRIMA della riproduzione. Dopo che la ricostruzione atterra il fuoco non si muove piu',
				# quindi non c'e' nessun altro fronte e nessuno rimedia.
				#
				# Il rimedio storico era il ciclo di blur_service, spento dal lotto 48. Non lo si
				# riaccende: quel ciclo compare in ogni crash da avvio catturato. Il lavoro va invece
				# dove il fuoco e' gia' seguito A LIVELLO, giro per giro -- qui. Questo watcher sa gia'
				# quale contenitore ha il fuoco, gira a 0,3 s, e si ferma da solo quando si apre un
				# dialogo modale ('idle (modal dialog open)'): quando il menu contestuale si apre, il
				# valore pubblicato all'ultimo giro utile e' esattamente quello dell'elemento giusto.
				#
				# Il confronto e' col VALORE ATTUALE della proprieta', non con una variabile locale: cosi'
				# si RIPRISTINA anche quando l'onfocus della skin l'ha azzerata (ri-fuoco a menu chiuso,
				# con l'elemento vuoto per un istante). Una variabile locale crederebbe di aver gia'
				# pubblicato e non riscriverebbe.
				# Poster e label si scrivono INSIEME, seguendo l'identita' dell'elemento: se il nuovo
				# elemento non ha poster la proprieta' va CANCELLATA, altrimenti resta quello di prima ed
				# e' di nuovo lo stesso difetto, solo sull'immagine invece che sul nome.
				# Costo: una getInfoLabel per giro, piu' una o due solo quando l'elemento cambia davvero.
				base_label = get_infolabel('Container(%s).ListItem.Label' % widget_id)
				if base_label and base_label != window.getProperty('TMDbHelper.ListItem.base_label'):
					base_poster = get_infolabel('Container(%s).ListItem.Art(poster)' % widget_id) \
									or get_infolabel('Container(%s).ListItem.Art(tvshow.poster)' % widget_id)
					window.setProperty('TMDbHelper.ListItem.base_label', base_label)
					if base_poster: window.setProperty('TMDbHelper.ListItem.base_poster', base_poster)
					else: window.clearProperty('TMDbHelper.ListItem.base_poster')
				key, first_url = paginator.container_head(widget_id, scope)
				if not key:
					# Riga a fuoco senza testa: sta caricando, o non e' di Fen Light. Non c'e' niente da
					# paginare e NIENTE DA DEDURRE: il token non si tocca.
					# LOTTO 337 -- qui il watcher azzerava il token dopo due letture vuote di fila, per
					# la ricerca a casella vuota (path di base sparito, resterebbe il solo '&pages=N').
					# Ma quelle righe a casella vuota sono NASCOSTE, e il watcher arriva qui solo sulla
					# riga che ha il fuoco: il caso per cui era nato non poteva mai toccarlo. Toccava
					# invece righe vere lette vuote -- un dialogo in cima (lotto 312, Horror da 16 passi a
					# 2) o una riga dell'hub al primo caricamento (19/09, 1101.504 azzerata ogni 0,6 s
					# per 4 secondi). Il token vuoto senza path lo impedisce adesso la skin, dove il path
					# si svuota: <ontextchange> per la ricerca testuale, Search_Discover_Path per Discover.
					log_change('idle id=%s no-head first=%s' % (widget_id, (first_url[:50] if first_url else '-')))
					wait_for_abort(0.3); continue
				# LOTTO 92: qui stava la seconda copia del controllo di cambio inquilino, tolta per la
				# stessa ragione dell'altra -- la riconciliazione appartiene alla build, che SA quale lista
				# sta costruendo, non al watcher, che poteva solo dedurlo dal contenuto a schermo.
				numitems = int(get_infolabel('Container(%s).NumItems' % widget_id) or 0)
				current = int(get_infolabel('Container(%s).CurrentItem' % widget_id) or 0)
				if numitems and current:
					loading = bool(window.getProperty(paginator.LOADING_PROP % key))
					hasmore = window.getProperty(paginator.HASMORE_PROP % key) == 'true'
					built = int(window.getProperty(paginator.BUILT_PROP % key) or 0)
					# Il margine e' in PASSI, come tutto il resto (lotto 317): la definizione del passo
					# sta in paginator.passo() e non si ricopia qui.
					runway = paginator.passo() * paginator.lookahead_pages()
					log_change('id=%s key=%s current=%s/%s remaining=%s runway=%s built=%s hasmore=%s loading=%s' %
								(widget_id, paginator.short(key), current, numitems, numitems - current, runway, built, hasmore, loading))
					if loading:
						# Una ricostruzione e' in corso. Sblocca il flag solo se la build e' morta davvero.
						# Il momento di partenza sta nella proprieta' stessa e non solo in `pending`, cosi'
						# il conteggio resta valido anche se il servizio riparte a meta' build.
						started = paginator.loading_started(key) or pending.get(key, 0)
						# Prima del timeout lungo, una domanda diversa: e' partita almeno una build da
						# quando ho scritto il token? Se no, non e' lentezza -- e' che il <content> di quel
						# widget non legge questa proprieta'. Si stampa il nome esatto scritto, cosi' la
						# verifica e' un grep dentro il file della skin e non un'indagine.
						written = token_written.get(key)
						if written and key not in token_reported and time() - written[0] > no_build_timeout \
								and paginator.last_build(key) < written[0]:
							token_reported.add(key)
							logger('Fen Light', 'WidgetPaginator: ricarica IGNORATA. Ho scritto Window(Home).Property(%s)=%s '
									'e in %ss non e\' partita nessuna build. Il <content> di quel widget non legge questa '
									'proprieta\': il file generato della skin e\' vecchio rispetto ai suoi .xmltemplate. '
									'Rigenerarlo -- alzare "buildv" in shortcuts/skinvariables-generator.json, oppure '
									'toccare i widget dalla schermata di modifica.' % (written[1], written[2], no_build_timeout))
						if started and time() - started > stuck_timeout:
							window.clearProperty(paginator.LOADING_PROP % key); pending.pop(key, None)
							logger('Fen Light', 'WidgetPaginator: build ferma da oltre %ss (key=%s), flag sbloccato. '
									'Se compare spesso le build sono troppo lente e il widget torna alla prima pagina.'
									% (stuck_timeout, paginator.short(key)))
					else:
						pending.pop(key, None)
						# (d) Only load ahead on genuine DOWNWARD movement, never on arrival. The first time a
						# widget is seen we just record its focus index (moved=False) so merely landing on it --
						# or on item 1 of a short list that already sits within the runway -- can't trigger a load.
						# A load fires only once the user actually scrolls toward the end (current increases);
						# staying put or scrolling up never does. This is what keeps a freshly-opened search from
						# auto-paginating, and stops a just-loaded page (numitems grows, current unchanged) from
						# immediately re-firing.
						moved = current > last_current.get(key, current)
						last_current[key] = current
						# Load ahead only when (a) more pages exist, (b) the focus is within one page of the
						# end of the VISIBLE items, and (c) the container has caught up to everything already
						# built (numitems >= built). Gate (c) is the anti-runaway: while a just-loaded page
						# hasn't surfaced yet -- Kodi coalesces the soft widget refreshes, so NumItems lags the
						# real build -- we wait instead of piling up loads. An empty filtered page leaves
						# built == numitems, so heavily-filtered searches still keep advancing.
						if hasmore and numitems - current <= runway and numitems >= built and moved:
							passi = paginator.raw_pages(key, paginator.passi_iniziali())
							now = time()
							window.setProperty(paginator.LOADING_PROP % key, str(now))
							window.setProperty(paginator.PAGES_PROP % key, str(passi + 1))
							pending[key] = now
							paginator.log('watcher TRIGGER key=%s passi %s->%s current=%s/%s built=%s -> token ctl%s' %
										(paginator.short(key), passi, passi + 1, current, numitems, built, widget_id))
							# Ricarica MIRATA: il token compare dentro il <content> del widget come $INFO[],
							# quindi cambiarlo fa ricaricare SOLO questo contenitore. Prima si sparava
							# UpdateLibrary, che e' un evento globale: per paginare un widget si
							# ricostruivano tutti quelli della schermata, ognuno con il suo interprete
							# Python nuovo. Era la causa principale della lentezza in home, e la coda di
							# invocazioni che ne usciva e' quella che faceva scadere il flag LOADING.
							# LOTTO 325 -- il token lo scrive scrivi_token e nessun altro, sotto lock. Qui
							# c'era una setProperty secca, che cancellava un ordine di ricarica appena
							# messo da un altro processo -- e dal 324 quell'ordine porta anche il motivo,
							# quindi perderlo riportava la watchlist a non aggiornarsi.
							ctl_prop = paginator.CTL_PAGES_PROP % (scope, widget_id)
							paginator.scrivi_token(scope, widget_id, passi=passi + 1)
							token_written[key] = (now, ctl_prop, passi + 1)
							wait_for_abort(0.5); continue
			except Exception as e:
				paginator.log('watcher EXC %s' % e)
			wait_for_abort(0.2)
		try: del monitor
		except: pass
		try: del player
		except: pass
		return logger('Fen Light', 'WidgetPaginator Service Finished')

# LOTTO 333 -- qui stava DubResolver, che svuotava la coda dei verdetti rimandati dalle costruzioni e
# ricostruiva le righe a gruppi. Le costruzioni non rimandano piu' niente: i verdetti li decide il
# preparatore (modules/preparatore.py) PRIMA che un titolo entri in lista.

class PerfSampler:
	# Lotto 83. Il pezzo che mancava: finora ogni misura veniva da DENTRO un'invocazione del plugin,
	# quindi il tempo fra un'invocazione e l'altra -- cioe' la NAVIGAZIONE -- era cieco. Il servizio
	# invece e' sempre vivo, e puo' campionare.
	#
	# Tre serie, tutte in una riga sola per evento:
	#  1. MEMORIA LIBERA nel tempo. La domanda a cui deve rispondere e' se il degrado osservato dopo
	#     ~6 minuti di uso (import identici da 5,4 s a 17,4 s, con un onLowMemory di Android in mezzo)
	#     e' pressione di memoria o solo invocazioni sovrapposte. Il valore assoluto dice poco --
	#     Android tiene la libera bassa di proposito -- la DERIVATA dice tutto.
	#  2. CAMBI DI FINESTRA con il tempo passato nella precedente: la mappa della navigazione, che
	#     incrociata con le righe PERF INVOCAZIONE dice quanto di un gesto e' plugin e quanto e' skin.
	#  3. Il PICCO di memoria persa fra un campione e il precedente, per vedere QUALE gesto la mangia.
	#
	# Costo per giro: una getInfoLabel e una getCurrentWindowId. Deliberatamente a 2 secondi e non a
	# 0,3 come faceva BlurService: quel ciclo e' l'unico elemento presente in ogni crash da avvio
	# catturato (vedi BLUR_START_DELAY), e non si ripete quell'errore per una misura.
	INTERVAL = 2
	# Si stampa una riga di memoria solo se e' cambiata di almeno questo, o se sono passati
	# HEARTBEAT secondi. Senza soglia il log diventa esso stesso il carico -- e' l'errore gia' fatto
	# con DIAG in paginator.
	DELTA_MB = 8
	HEARTBEAT = 30
	# Soglia oltre la quale il ritardo del ciclo e' un segnale e non rumore di scheduling.
	LAG_ALERT = 1.5
	# LOTTO 246 -- IL CENSIMENTO DELLA CPU PER THREAD.
	#
	# Ogni CENSIMENTO_OGNI secondi si confrontano due letture di /proc/self/task e si stampa CHI ha
	# consumato. Non a ogni giro da 2 s: il censimento costa una lettura per thread (sessanta e piu'
	# su Kodi) e a 2 s sarebbe esso stesso un carico -- l'errore gia' fatto con DIAG in paginator.
	#
	# Si stampa su SOGLIA o a BATTITO, come la memoria qui sopra: a macchina quieta una riga al
	# minuto basta a dire che era quieta, quando lavora si vuole vedere tutto. E si stampa SEMPRE
	# quando il ciclo e' in ritardo, che e' il momento per cui questo strumento esiste: fino a oggi
	# la riga PERF CARICO diceva che la macchina non ce la faceva e non poteva dire per colpa di chi.
	CENSIMENTO_OGNI = 15
	CENSIMENTO_SOGLIA = 0.40      # frazione di UN core sotto la quale non vale una riga
	CENSIMENTO_BATTITO = 60
	# LOTTO 248 -- IL CAMPIONAMENTO A OGNI GIRO E' STATO TOLTO, ed era un mio errore.
	#
	# Il 247 lo aveva introdotto sulla base di "1 ms di mediana", che era il numero sbagliato: il
	# cronometro del 246 partiva DOPO la lettura e misurava la formattazione. Il costo vero,
	# misurato l'11/09 su 64 finestre, e' 53 ms di mediana e fino a 1875 ms per censimento.
	#
	# E il conto e' arrivato puntuale. Il ciclo di questo campionatore non era MAI andato in
	# ritardo: zero eventi PERF CARICO in log244, log245 e log246 (22+22+27 minuti, campionatore
	# attivo e funzionante in tutti e tre). Col censimento ogni 15 s: tredici. Col censimento piu'
	# i pronti a ogni giro: altri tredici, e la corrispondenza e' al millisecondo --
	#
	#     18:56:58  strumento 1792 + 1875 ms  ->  18:57:02 ritardo 3,7 s
	#     18:57:04  strumento 1712 + 1702 ms  ->  18:57:06 ritardo 3,5 s
	#
	# Lo strumento stava misurando se stesso e accusando la macchina. I pronti restano -- servono, e
	# hanno gia' risposto: 2-3, massimo 6, su quattro core, cioe' ne' satura ne' contesa -- ma si
	# prendono UNA volta per censimento, dove costano quanto il censimento stesso e non di piu'.

	def run(self):
		from modules.perf import enabled, free_memory_mb
		if not enabled():
			return logger('Fen Light', 'PerfSampler non avviato (strumentazione spenta)')
		logger('Fen Light', 'PerfSampler Service Starting')
		from time import time
		monitor = xbmc.Monitor()
		wait_for_abort = monitor.waitForAbort
		window = xbmcgui.Window(10000)
		get_current_window = xbmcgui.getCurrentWindowId
		get_current_dialog = xbmcgui.getCurrentWindowDialogId
		last_mem, last_beat = free_memory_mb(), time()
		last_win, last_dialog, win_since = None, None, time()
		worst_drop = [0, '']
		# SONDA DI SATURAZIONE (lotto 87). Su questo Android non rootato /proc/loadavg e le zone
		# termiche sono negate all'app, quindi carico e temperatura non si possono leggere. Ma un
		# effetto della saturazione si misura senza permessi: quanto RITARDA questo ciclo. waitForAbort
		# chiede 2,0 s; se ne restituisce 6 vuol dire che il thread non e' stato rischedulato in tempo,
		# cioe' che la macchina non ce la fa. E' un termometro del carico, non della temperatura -- ma
		# e' l'unico che possiamo leggere, e il crash del 25/08 e' avvenuto nel momento di carico
		# massimo della sessione.
		worst_lag, tick_at = 0.0, time()
		# LOTTO 246. Se /proc non e' leggibile `censimento_cpu` torna None e tutto il resto si
		# spegne da se': uno strumento rotto non deve poter fermare il campionatore.
		from modules.perf import censimento_cpu, divario_cpu
		from modules.perf import fps
		# thread_time e' la cpu di QUESTO thread: confrontata con la parete dice se il censimento
		# sta lavorando o aspettando. Se manca (build di Python senza) si ripiega su una costante,
		# e la riga stampera' 0 ms di cpu invece di far cadere il campionatore.
		try:
			from time import thread_time as _cpu_ora
		except Exception:
			_cpu_ora = lambda: 0.0
		censo, censo_at, censo_beat = censimento_cpu(), time(), time()
		# LOTTO 248 -- il costo dello strumento si SOTTRAE dal ritardo del ciclo. Senza, il
		# campionatore accusa la macchina del tempo che si e' preso da solo, ed e' esattamente cio'
		# che e' successo l'11/09.
		costo_strumento = 0.0
		if censo is None:
			logger('FenLight PERF CPU', 'censimento per thread NON disponibile (/proc/self/task non leggibile)')
		else:
			logger('FenLight PERF CPU', 'censimento per thread attivo | %d thread | ogni %s s'
					% (censo[2], self.CENSIMENTO_OGNI))
		logger('FenLight PERF MEM', 'inizio campionamento | memoria libera %s MB' % last_mem)
		while not wait_for_abort(self.INTERVAL):
			try:
				now = time()
				# Il ritardo si misura SEMPRE, anche a servizi in pausa: e' il campione piu' prezioso
				# proprio quando la macchina e' occupata a fare altro.
				# Al NETTO di quanto lo strumento ha speso nel giro precedente: quel tempo e'
				# nostro, non della macchina, e attribuirglielo e' come misurare la febbre col
				# termometro in bocca al medico.
				lag = (now - tick_at) - self.INTERVAL - costo_strumento
				tick_at, costo_strumento = now, 0.0
				in_ritardo = lag > self.LAG_ALERT
				if in_ritardo:
					if lag > worst_lag: worst_lag = lag
					logger('FenLight PERF CARICO', 'ciclo in ritardo di %.1f s (chiesti %s s) | finestra %s | memoria libera %s MB | ritardo peggiore finora %.1f s%s'
							% (lag, self.INTERVAL, get_current_window(), free_memory_mb(), worst_lag,
							   ' | al netto dello strumento'))
				# LOTTO 246 -- il censimento. Sta PRIMA della guardia sui servizi in pausa: durante
				# una riproduzione i servizi si fermano ma la cpu no, ed e' proprio allora che
				# serve sapere chi la sta usando.
				if censo is not None and (in_ritardo or now - censo_at >= self.CENSIMENTO_OGNI):
					# LOTTO 247 -- IL CRONOMETRO PARTE PRIMA DELLA LETTURA. Nel 246 stava dopo, e
					# quindi "costo del censimento" misurava la formattazione invece delle
					# cinquanta aperture di file che sono il costo vero: l'11/09 ha riportato 1 ms
					# di mediana, che era il numero sbagliato. Su quel numero avevo poi deciso di
					# campionare i pronti a ogni giro, quindi andava corretto prima di fidarsene.
					# LOTTO 248 -- CPU E PARETE INSIEME. 53 ms di mediana per leggere cinquanta
					# file possono essere lavoro vero (Python, un ARM a 32 bit a 1,4 GHz, SELinux
					# a ogni apertura) oppure attesa. Le due misure insieme lo dicono, e i due
					# casi hanno rimedi opposti: rendere lo strumento piu' magro, o diradarlo.
					_t0, _c0 = time(), _cpu_ora()
					_nuovo = censimento_cpu()
					_parete = now - censo_at
					if _nuovo is not None:
						_pronti = ('pronti %d su %d thread' % (_nuovo[3], _nuovo[2])) \
								  if len(_nuovo) > 3 else ''
						_f = fps()
						_capo, _chi = divario_cpu(censo, _nuovo, _parete, pronti=_pronti, fps=_f)
						_quanto = (_nuovo[0] - censo[0]) / _parete if _parete > 0 else 0
						if _capo and (in_ritardo or _quanto >= self.CENSIMENTO_SOGLIA
									  or now - censo_beat >= self.CENSIMENTO_BATTITO):
							_sp, _sc = (time() - _t0) * 1000, (_cpu_ora() - _c0) * 1000
							# LOTTO 253 -- ANCHE IL DIALOGO SOPRA, e serviva da tre lotti.
							# `getCurrentWindowId` torna la finestra SOTTO: con la finestra sorgenti
							# aperta il censimento scriveva `finestra 10000`, cioe' la Home, e i
							# censimenti fatti durante una ricerca erano indistinguibili da una Home
							# a riposo. Non cambia finestra e nessuno preme tasti, quindi passavano
							# anche il filtro dei "censimenti puliti": il 12/09 mi hanno fatto
							# leggere una Home a riposo scesa dall'85% al 60% che non esisteva.
							# La funzione c'era gia' in questo stesso ciclo, per le righe PERF NAV.
							# 9999 e' WINDOW_INVALID: `getCurrentWindowDialogId` lo torna quando NON c'e'
							# nessun dialogo. Con il solo `if _dlg` e' vero, e il lotto 253 ha passato
							# una sessione intera a scrivere `coperta dal dialogo 9999` su finestre
							# scoperte -- cioe' l'esatto contrario di cio' che la riga serve a dire.
							_dlg = get_current_dialog()
							if _dlg in (9999, 0): _dlg = None
							logger('FenLight PERF CPU', '%s%s | finestra %s%s%s | censimento %.0f ms parete / %.0f ms cpu'
									% (_capo, ' | fps %.0f' % _f if _f is not None else '',
									   get_current_window(),
									   (' coperta dal dialogo %s' % _dlg) if _dlg else '',
									   ' | CICLO IN RITARDO' if in_ritardo else '', _sp, _sc))
							logger('FenLight PERF CPU', '  %s' % _chi)
							censo_beat = now
						censo, censo_at = _nuovo, now
						costo_strumento = time() - _t0
				if window.getProperty(pause_services_prop) == 'true': continue
				mem = free_memory_mb()
				win, dialog = get_current_window(), get_current_dialog()
				# 2. cambio di finestra o di dialogo
				if win != last_win or dialog != last_dialog:
					if last_win is not None:
						logger('FenLight PERF NAV', 'finestra %s (dialogo %s) -> %s (dialogo %s) | %.1f s nella precedente | memoria libera %s MB'
								% (last_win, last_dialog, win, dialog, now - win_since, mem))
					last_win, last_dialog, win_since = win, dialog, now
				# 3. il calo peggiore e dove e' avvenuto
				if last_mem >= 0 and mem >= 0:
					drop = last_mem - mem
					if drop > worst_drop[0]:
						worst_drop = [drop, 'finestra %s' % win]
				# 1. memoria: solo su variazione sensibile o a battito
				if mem >= 0 and (abs(mem - last_mem) >= self.DELTA_MB or now - last_beat >= self.HEARTBEAT):
					logger('FenLight PERF MEM', 'memoria libera %s MB (%+d dal campione precedente) | finestra %s | calo peggiore finora %s MB (%s)'
							% (mem, mem - last_mem, win, worst_drop[0], worst_drop[1]))
					last_mem, last_beat = mem, now
			except: pass

# LOTTO 230 -- LA SONDA NON VIVE PIU' QUI. Il servizio poteva aspettare un momento con la CPU
# libera, ma non sapeva mai quando l'utente avrebbe fatto partire un film: tre sonde su quattro sono
# finite abbandonate a meta'. Adesso sta in sources.process_results, subito dopo che TorBox ha detto
# quali sorgenti sono in cache, e misura la sorgente che sta per partire. Vedi modules/sonda_linea.py.

class AutoStart:
	def run(self):
		logger('Fen Light', 'AutoStart Service Starting')
		from modules.settings import auto_start_fenlight
		if auto_start_fenlight():
			from modules.kodi_utils import run_addon
			run_addon()
		return logger('Fen Light', 'AutoStart Service Finished')

class FenLightMonitor(xbmc.Monitor):
	def __init__ (self):
		xbmc.Monitor.__init__(self)
		self.startServices()

	def _avvia_diagnostica(self):
		"""LOTTO 261. Rileva il livello di log, lo rispecchia in una proprieta' e lo DICHIARA.

		E' tutto quello che la suite fa dentro Kodi: il censimento per thread vive fuori, in
		strumenti/diagnostica/sonda.sh, per non ripetere l'errore del lotto 248 (lo strumento che
		accusava la macchina del proprio peso). Qui si paga una getCondVisibility e, una volta sola,
		la lettura di advancedsettings.xml.

		La riga di log serve a chi leggera' il referto fra un mese: senza, non c'e' modo di sapere
		se una misura e' stata presa con l'overlay di debug acceso -- e l'overlay ridisegna tutto lo
		schermo a ogni fotogramma, quindi cambia proprio il numero che si stava misurando.
		"""
		try:
			from modules.diagnostica import rileva, pubblica, battezza, DEBUG, DEBUG_OVERLAY
			livello, overlay, fonte = rileva()
			pubblica(livello, overlay)
			battezza('FL:servizio')
			if livello >= DEBUG:
				logger('FenLight DIAG', 'diagnostica ATTIVA | livello %d da %s' % (livello, fonte))
				if overlay:
					logger('FenLight DIAG', "ATTENZIONE: l'overlay di debug e' acceso (livello %d). "
						   'Riscrive MEM e FPS quasi a ogni fotogramma, quindi sporca una regione, e '
						   'con algorithmdirtyregions=3 una regione sporca fa ridisegnare TUTTO lo '
						   'schermo. I numeri di questa sessione NON sono quelli a riposo: per '
						   'misurare usa <loglevel>1</loglevel> in advancedsettings.xml.' % livello)
			else:
				logger('FenLight DIAG', 'diagnostica spenta (log a livello normale): la sonda esterna '
					   'misurera\' tutto ma non potra\' dare un nome ai thread di Kodi')
		except Exception: pass

	def _filo(self, nome, funzione):
		"""Un thread che si presenta con un nome in /proc. Vedi modules/diagnostica.battezza:
		su Android Kodi non nomina i propri thread e su Linux il nome si EREDITA dal creatore,
		quindi senza questa riga tutti i nostri servizi compaiono nella traccia esterna col nome del
		thread Java dell'applicazione -- indistinguibili fra loro e da quelli di Kodi."""
		def _corpo():
			try:
				from modules.diagnostica import battezza
				battezza(nome)
			except Exception: pass
			funzione()
		return Thread(target=_corpo)

	def startServices(self):
		# Prima di far partire TraktMonitor: la costruzione iniziale dei widget che Kodi sta facendo
		# adesso vale come ricostruzione globale, e va registrata o la prima sincronizzazione Trakt ne
		# ordinera' una seconda a vuoto. Vedi kodi_utils.stamp_startup_rebuild.
		# Per primo: cosi' la proprieta' col livello esiste prima che qualunque invocazione del
		# plugin provi a leggerla.
		self._avvia_diagnostica()
		from modules.kodi_utils import stamp_startup_rebuild
		stamp_startup_rebuild()
		# SetAddonConstants resta SEMPRE qui e sempre in sincrono: sono 5 ms misurati, e la skin legge
		# fenlight.addon_path / _profile / _icon / _fanart appena disegna. Rimandarlo si vedrebbe.
		SetAddonConstants().run()
		# LOTTO 332 -- IL PREPARATORE PARTE SUBITO, non con il resto dell'avvio differito: le righe della Home
		# lo stanno aspettando (la costruzione non va piu' in rete da se'), e rimandarlo fino a "Home piena"
		# le fermerebbe tutte fino al limite di sicurezza. Prima, il token dei contenitori: il preparatore
		# ordina ricariche da questo processo (lotto 325).
		self._preparatore = None
		try:
			from modules import paginator as _pg, preparatore
			_pg.abilita_token_locale()
			self._preparatore = preparatore.avvia()
		except Exception as e: logger('Fen Light', 'preparatore NON avviato (%s)' % e)
		# IL RESTO ASPETTA CHE LA HOME SIA PIENA (lotto 2, 08/09/2026).
		#
		# Perche'. Su Android il Python di Kodi vive dentro un solo processo e i sotto-interpreti si
		# dividono UN core: la quota di CPU di ogni invocazione e' circa 1/N, con N il numero di
		# interpreti vivi. Misurato sulla stick il 08/09: con 6 interpreti la fase di import di un
		# widget girava al 16% di CPU, con 4 al 25%, da sola all'86%. Questo servizio e' uno di quegli
		# N, e nella finestra in cui si costruiscono i tre widget della home spendeva (log 04:36):
		#     DatabaseMaintenance 572 ms + SyncSettings 347 ms + AutoStart 175 ms
		#     + l'import del client http tirato dal primo giro di TraktMonitor, 1172 ms
		# cioe' oltre due secondi di lavoro che nessuno stava aspettando, sottratti a chi invece si
		# stava aspettando. Spostandolo dopo, quel lavoro costa meno anche a se stesso: e' la stessa
		# firma del controllo dei template del lotto 151, 5500 ms dentro la tempesta e 592 fuori.
		#
		# L'ordine interno NON cambia: _start_remaining_services e' la vecchia coda di questo metodo,
		# riga per riga. L'unica differenza e' QUANDO parte.
		if self._boot_work_can_wait(): self._filo('FL:avvio', self._deferred_services).start()
		else: self._start_remaining_services()

	def _start_remaining_services(self):
		DatabaseMaintenance().run()
		SyncSettings().run()
		self._filo('FL:fonts', CustomFonts().run).start()
		# BLUR SPENTO (23/08, richiesta dell'utente). Non differito: proprio non parte. Lo sfondo
		# sfocato ricade sull'artwork nitido, che e' una perdita puramente estetica; in cambio
		# spariscono l'import di Pillow, il ciclo di polling a 0.3s e ogni generazione di immagine.
		# Per riaccenderlo basta ripristinare la riga sotto: e' l'unico punto che lo avvia.
		# Thread(target=self._delayed_blur_start).start()
		# LOTTO 325 -- il token dei contenitori ha questo processo come unico scrittore: lo dichiara
		# startServices, prima del preparatore, che ordina ricariche.
		self._filo('FL:trakt', TraktMonitor().run).start()
		self._filo('FL:widgetref', WidgetRefresher().run).start()
		self._filo('FL:paginator', WidgetPaginator().run).start()
		self._filo('FL:perf', PerfSampler().run).start()
		# Aggiornamento della skin senza ReloadSkin. Vive in modules/skin_updater.py e non qui perche'
		# quel modulo ha il suo .pyc, mentre questo file Kodi lo esegue come __main__ e lo ricompila a
		# ogni avvio (vedi il referto in testa): sono ~250 righe che non hanno motivo di ricompilarsi.
		# L'import e' pigro per la stessa ragione, e il servizio aspetta comunque 90 s prima di
		# toccare la rete. Vedi il modulo per il log del 09/09 che l'ha reso necessario.
		self._filo('FL:skinupd', self._start_skin_updater).start()
		AutoStart().run()
		self._mark_boot_ready()

	def _start_skin_updater(self):
		try:
			from modules.skin_updater import SkinUpdater
			SkinUpdater().run()
		except Exception as e: logger('Fen Light', 'SkinUpdater non avviato (%s)' % e)

	def _boot_work_can_wait(self):
		"""Si puo' rimandare il lavoro di avvio, o questo e' un avvio in cui deve precedere i widget?

		DEVE precedere in due casi, e sono gli unici due in cui make_databases e sync_settings fanno
		qualcosa di piu' che confermare l'esistente:

		  1. primo avvio o profilo azzerato -- non esistono ne' i database ne' le impostazioni;
		  2. primo avvio dopo un aggiornamento dell'addon -- puo' esserci una tabella nuova da creare
		     o un'impostazione nuova da inserire.

		Il secondo caso non e' teorico ed e' il motivo per cui qui non c'e' un semplice
		"i database esistono?". get_setting e' `get_property(id) or settings_cache.get(id) or fallback`:
		un'impostazione che sync_settings non ha ancora inserito non torna il suo default dichiarato,
		torna il fallback di chi chiama. Sarebbe un widget costruito con un valore diverso da quello
		configurato, per un solo avvio, senza un errore in log -- esattamente il tipo di guasto
		silenzioso che questo progetto continua a scovare mesi dopo.

		Il dato che risponde alla domanda e' la VERSIONE, non un orologio: tabelle e impostazioni nuove
		arrivano solo con una versione nuova. Il segnalibro sta in un file del profilo e non nella
		cache delle impostazioni di proposito: sync_settings cancella le righe che non stanno in
		default_settings, quindi una riga nostra li' dentro verrebbe potata a ogni giro.

		Qualunque cosa vada storta -- file illeggibile, profilo non scrivibile, eccezione -- si
		risponde NO e si lavora in sincrono come prima del lotto: la via lenta e' sempre quella giusta.
		"""
		try:
			from modules.kodi_utils import addon_version
			marker = self._read_boot_marker()
			return bool(marker) and marker == addon_version()
		except: return False

	def _boot_marker_path(self):
		from modules.kodi_utils import addon_profile
		import os
		return os.path.join(addon_profile(), 'boot_ready')

	def _read_boot_marker(self):
		from modules.kodi_utils import path_exists, open_file
		p = self._boot_marker_path()
		if not path_exists(p): return ''
		f = open_file(p)
		try: return (f.read() or '').strip()
		finally: f.close()

	def _mark_boot_ready(self):
		"""Registra che con QUESTA versione un avvio completo e' andato a termine.

		Scritto in coda a _start_remaining_services, cioe' solo dopo che make_databases e
		sync_settings sono finiti davvero: se l'avvio si interrompe prima, il segnalibro resta
		vecchio e il prossimo avvio rifa' il lavoro in sincrono. E' il verso giusto in cui sbagliare.
		"""
		try:
			from modules.kodi_utils import addon_version, addon_profile, path_exists, make_directory, open_file
			version = addon_version()
			if not version or self._read_boot_marker() == version: return
			profile = addon_profile()
			if not path_exists(profile): make_directory(profile)
			f = open_file(self._boot_marker_path(), 'w')
			try: f.write(version)
			finally: f.close()
		except: pass

	def _deferred_services(self):
		"""Aspetta che la home smetta di costruire, poi avvia il resto.

		L'attesa NON e' un timer tarato a occhio sulla durata dell'avvio: il registro delle
		costruzioni (kodi_utils.BUILD_LOG_PROP, una riga per ogni cartella consegnata) dice
		quante ne sono state consegnate da quando il servizio e' nato. Si aspetta che quel
		numero smetta di crescere -- il timer misura solo la QUIETE fra una consegna e l'altra,
		non indovina quando finisce l'avvio, e non serve sapere quanti widget abbia la home.

		Due uscite di sicurezza, perche' un'attesa senza fine qui vorrebbe dire niente Trakt e
		niente paginazione per tutta la sessione:
		  - BOOT_DEFER_CAP: si parte comunque, anche se di widget non ne arriva nessuno (una home
		    senza widget Fen Light e' una configurazione legittima);
		  - waitForAbort: se Kodi chiude durante l'attesa il thread non resta appeso.
		"""
		from time import time as _now
		from modules.kodi_utils import build_log_rows
		monitor = xbmc.Monitor()
		t0 = _now()
		seen, last_change = 0, t0
		while not monitor.abortRequested():
			# Il registro si legge DA ZERO, non da t0, e non e' una svista. Le proprieta' di finestra
			# muoiono con Kodi, quindi all'avvio il registro e' vuoto e ogni riga che contiene e' di
			# questo avvio. Contare da t0 aprirebbe una corsa che questo metodo perderebbe: se i
			# widget venissero consegnati prima che questo thread nasca -- il servizio parte 1,3 s
			# dopo i provider e su una macchina piu' svelta l'ordine si inverte -- non ne vedrebbe
			# nessuno, e aspetterebbe BOOT_DEFER_CAP interi con Trakt e paginazione fermi.
			try: count = len(build_log_rows(0))
			except: count = seen
			if count != seen: seen, last_change = count, _now()
			now = _now()
			if seen and now - last_change >= BOOT_DEFER_SETTLE: break
			if now - t0 >= BOOT_DEFER_CAP: break
			if monitor.waitForAbort(BOOT_DEFER_POLL): return
		logger('Fen Light', 'Avvio differito: %s costruzioni viste, parto dopo %.1f s' % (seen, _now() - t0))
		self._start_remaining_services()

	def _delayed_blur_start(self):
		# Aspetta che la tempesta di avvio sia passata prima di importare Pillow e partire col
		# polling: vedi BLUR_START_DELAY per la misura che l'ha motivato. waitForAbort (non sleep)
		# cosi' un abort di Kodi durante l'attesa non lascia il thread appeso.
		if xbmc.Monitor().waitForAbort(BLUR_START_DELAY): return
		from modules.blur_service import BlurService
		BlurService().run()

	def onNotification(self, sender, method, data):
		# LOTTO 314 -- lo strato dati delle liste ha UN SOLO scrittore, ed e' questo. Le build
		# spediscono cio' che hanno consegnato (widgets_cache.invia) e qui si scrive, in ordine di
		# arrivo, su una connessione sola aperta per tutta la sessione. Il checkpoint del giornale lo
		# fa questo thread subito dopo, che e' il "momento di quiete" giusto: la cartella e' gia'
		# chiusa e nessun contenitore sta aspettando.
		if method.startswith('Other.') and sender == 'plugin.video.fenlight':
			# L'import sta qui dentro: onNotification riceve OGNI notifica di Kodi (player compreso),
			# e i messaggi 'Other.' sono solo i nostri.
			from modules import paginator
			messaggio = method[len('Other.'):]
			# LOTTO 332 -- le consegne (pgdb, lotto 314), le richieste di passo e le schede da rinnovare vanno
			# tutte al preparatore: e' l'unico thread che scrive widgets.db. Qui si smista soltanto.
			if self._preparatore is not None and self._preparatore.ricevi(messaggio, data): return
			# LOTTO 325 -- il token di ricarica di un contenitore ha UN SOLO scrittore ed e' questo processo.
			if messaggio == paginator.MESSAGGIO_TOKEN:
				try: paginator.applica_ricariche(data)
				except Exception as e: logger('Fen Light', 'pg: ricarica non applicata (%s)' % e)
				return
		# Marcatori di memoria attorno alla riproduzione (lotto 83). Sono il gruppo di controllo della
		# domanda posta dall'utente: il player E' capace di liberare risorse, quindi se la memoria
		# risale a OnPlay e riscende a OnStop, allora la memoria si puo' liberare e il problema e' che
		# navigando non la libera nessuno. Se invece non risale mai, non e' recuperabile per quella via.
		# Bandiera della riproduzione (lotto 111). La alza gia' modules/player.py prima di consegnare
		# l'URL a Kodi, che e' l'istante piu' presto possibile; questo e' il presidio per i due casi
		# che quello non copre: una riproduzione che NON parte da Fen Light, e -- soprattutto --
		# l'abbassamento. Se l'oggetto player morisse male senza pulire, i widget resterebbero
		# tagliati per sempre: qui il monitor e' sempre vivo e OnStop arriva comunque.
		if method in ('Player.OnPlay', 'Player.OnAVStart'):
			try:
				import time as _t
				xbmcgui.Window(10000).setProperty(playback_active_prop, 'true')
				xbmcgui.Window(10000).setProperty(playback_start_prop, str(_t.time()))
			except: pass
		elif method == 'Player.OnStop':
			try: xbmcgui.Window(10000).clearProperty(playback_active_prop)
			except: pass
			# IL RITORNO DAL PLAYER E' UN REFRESH IN POSTO (lotto 112).
			#
			# Uscendo dal player Kodi reinvalida da solo tutti i CDirectoryProvider. Quella
			# ricostruzione non era marcata in nessun modo, quindi _passi_legacy la trattava come
			# l'apertura di un widget nuovo e tornava 'default' (2 pagine): il contenitore si
			# accorciava, gli elementi si spostavano e il fuoco tornava al primo. Misurato nel log
			# del 29/08: prima di riprodurre 'watcher id=504 current=2/27', dopo la chiusura
			# 'current=1/27', con la firma del contenuto IDENTICA (3c418f7c) -- cioe' non era
			# cambiato niente, si perdeva la posizione e basta.
			#
			# Lo dice gia' il commento di _passi_legacy: il conteggio accumulato serve quando
			# "il contenitore deve mantenere la lunghezza corrente cosi' gli elementi restano fermi e
			# il fuoco e' preservato". Il ritorno dalla riproduzione e' esattamente quel caso, e non
			# era nell'elenco. E' anche il problema lasciato aperto a voce in kodi_refresh: "il fuoco
			# resta un problema aperto, da risolvere conservando la posizione".
			#
			# hold_refresh_flag scrive una SCADENZA e torna subito -- nessuna attesa dentro
			# l'invocazione, e a spegnere la bandiera pensa WidgetRefresher, che gira gia'. La
			# finestra di 20 s copre abbondantemente il ritardo osservato fra OnStop (17:18:57,078) e
			# la prima passi_da_caricare (17:18:59,031).
			#
			# LOTTO 177. Qui NON si timbra piu' una ricostruzione globale. Il passo 1.2 lo faceva
			# perche' Kodi, uscendo dal player, invalidava davvero tutti i contenitori; da quando
			# non scrive piu' nel proprio database video quella ricostruzione non avviene, e il
			# timbro scartava il refresh mirato del segnalibro -- l'unico che porta l'id del film.
			# Il motivo per esteso sta in kodi_utils, dove stava la funzione.
			try:
				from modules.kodi_utils import hold_refresh_flag
				hold_refresh_flag('fenlight.pg.refresh')
			except: pass
		if method in ('Player.OnPlay', 'Player.OnAVStart', 'Player.OnStop'):
			try:
				from modules.perf import log as perf_log, free_memory_mb
				perf_log('FenLight PERF MEM', '%s | memoria libera %s MB' % (method, free_memory_mb()))
			except: pass
		if method in ('GUI.OnScreensaverActivated', 'System.OnSleep'):
			xbmcgui.Window(10000).setProperty(pause_services_prop, 'true')
			logger('OnNotificationActions', 'PAUSING Fen Light Services Due to Device Sleep')
		elif method in ('GUI.OnScreensaverDeactivated', 'System.OnWake'):
			xbmcgui.Window(10000).clearProperty(pause_services_prop)
			logger('OnNotificationActions', 'UNPAUSING Fen Light Services Due to Device Awake')

logger('Fen Light', 'Main Monitor Service Starting')
_principale = FenLightMonitor()
# canwritedatabases: i due soli momenti in cui il file dei profili si puo' riconciliare. Vedi
# modules/profile_flag.py -- senza il marcatore scritto dal pulsante entrambe le chiamate tornano
# subito senza toccare niente.
try:
	from modules.profile_flag import on_service_start
	on_service_start()
except Exception as e: logger('Fen Light', 'profile_flag: controllo all\'avvio non riuscito (%s)' % e)
_principale.waitForAbort()
if _principale._preparatore is not None: _principale._preparatore.ferma()
# QUI, e non prima: Kodi riscrive profiles.xml dalla memoria al terzo passo di CApplication::Stop()
# ("Saving settings"), e i servizi Python vengono fermati molto piu' avanti. Scrivere adesso significa
# scrivere per ultimi. Misura sulla Mi Stick (17/09 04:48): salvataggio 31.818, servizi 32.61.
try:
	from modules.profile_flag import on_service_stop
	on_service_stop()
except Exception as e: logger('Fen Light', 'profile_flag: controllo all\'uscita non riuscito (%s)' % e)
logger('Fen Light', 'Main Monitor Service Finished')