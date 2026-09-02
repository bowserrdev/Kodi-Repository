# -*- coding: utf-8 -*-
import xbmc, xbmcgui
import json
from threading import Thread
from modules.blur_service import BlurService

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

def refresh_ids_inproc(ids, actions):
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
	Thread(target=kodi_refresh_ids, args=(_ids, _actions)).start()
# Giri dopo un cambio di finestra in cui si ripassa il censimento dei contenitori. I giri sono da
# 0,3 s: 0 / 1,5 / 3 / 6 / 10,5 / 16,5 secondi. Copre il tempo in cui i widget si stanno ancora
# costruendo -- sulla stick una costruzione supera spesso i 5 s -- senza sondare per sempre una
# finestra che di widget Fen Light non ne ha. registry_add e' idempotente, quindi ripassare non
# duplica nulla: aggiunge solo cio' che nel frattempo e' comparso.
CENSUS_TICKS = frozenset((0, 5, 10, 20, 35, 55))

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
		from apis.trakt_api import trakt_sync_activities
		from caches.settings_cache import get_setting
		from apis.trakt_api import self_mark_recent
		from modules.kodi_utils import run_plugin, refresh_age
		from modules.settings import trakt_sync_interval
		monitor, player, window = xbmc.Monitor(), xbmc.Player(), xbmcgui.Window(10000)
		wait_for_abort, is_playing = monitor.waitForAbort, player.isPlayingVideo
		while not monitor.abortRequested():
			while is_playing() or window.getProperty(pause_services_prop) == 'true': wait_for_abort(10)
			# Prima del giro di sincronizzazione, cioe' sempre mentre non si sta riproducendo nulla.
			refresh_official_status()
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
					# volte: a fine film mandiamo lo scrobble a Trakt, il poll successivo lo rilegge come
					# 'qualcosa e' cambiato' e ricostruisce tutto una seconda volta per lo stesso titolo.
					# Nel log del Mac del 21/08: scan alle 23:37:44.874 (il nostro flush post-riproduzione) e
					# di nuovo alle 23:37:51.969, 62 ms dopo 'Trakt Update Performed'. Se l'interfaccia e'
					# stata ricostruita da poco, la ricostruzione di Trakt e' quasi certamente per il
					# cambiamento che l'ha appena innescata. La sincronizzazione e' gia' avvenuta comunque:
					# quello che si salta e' solo il ridisegno, e il dato compare alla prima ricostruzione
					# successiva -- che con la navigazione arriva in pochi secondi.
					# Se a svegliare la sincronizzazione e' stata la NOSTRA marcatura, l'interfaccia mostra
					# gia' il dato giusto: mark_movie/mark_episode scrivono in locale e ricaricano i
					# contenitori toccati PRIMA ancora di spingere su Trakt. Ordinare qui una
					# ricostruzione GLOBALE vuol dire rifare da capo ogni widget della schermata per un
					# cambiamento gia' visibile. Nel log della stick del 23/08 sono i due
					# 'DIAG refresh: GLOBALE' delle 13:22:12 e 13:22:59: nessuno dei due aveva niente
					# di nuovo da mostrare, e ognuno si e' portato dietro cinque ricostruzioni.
					# La finestra dell'accorpamento qui sotto non li prendeva perche' guarda solo
					# l'orologio, e fra la marcatura e il poll successivo passa piu' di quel tempo.
					if status == 'success' and self_mark_recent():
						logger('Fen Light', "TraktMonitor: refresh saltato, la modifica e' nostra ed e' gia' a schermo")
					elif status == 'success' and get_setting('fenlight.trakt.refresh_widgets', 'false') == 'true':
						# Quali titoli sono cambiati lo pubblica trakt_sync_activities dopo la
						# ricostruzione (lotto 59). Trakt non lo dice mai -- last_activities da solo
						# marche temporali per categoria -- ma il confronto fra l'insieme prima e
						# quello dopo lo sa. Tre stati: '' non lo sappiamo -> globale come prima;
						# '-' nulla e' cambiato davvero -> non si ricostruisce niente; altrimenti
						# ricarica MIRATA dei soli contenitori che contengono quegli id.
						# Si legge SEMPRE, anche quando la guardia qui sotto vieta di ricostruire ADESSO:
						# prima la lettura stava dentro il ramo 'else' e quando la guardia scattava questo
						# elenco non veniva nemmeno guardato. Vedi _defer_widget_refresh.
						changed = window.getProperty('fenlight.trakt.changed_ids')
						window.clearProperty('fenlight.trakt.changed_ids')
						# Le AZIONI viaggiano accanto agli id (lotto 119) e sono un canale a se': un
						# 'paused_at' su un film che ENTRA adesso in 'continua a guardare' non ha ancora
						# il suo id nell'elenco pubblicato dal widget, quindi la regola per id lo
						# scarterebbe proprio mentre va ricostruito. Lo stesso vale per la watchlist.
						# Non c'e' un valore '-' per le azioni: '' significa semplicemente 'nessuna'.
						actions = window.getProperty('fenlight.trakt.changed_actions')
						window.clearProperty('fenlight.trakt.changed_actions')
						age = refresh_age()
						if changed == '-' and not actions:
							logger('Fen Light', 'TraktMonitor: nessun titolo cambiato davvero, nessuna ricostruzione')
						elif age < TRAKT_REFRESH_COALESCE: self._defer_widget_refresh(window, changed, actions, age)
						elif changed or actions:
							# '-' vuol dire 'nessun id', non 'nessun lavoro': con le sole azioni si
							# ricostruiscono comunque i widget che cambiano composizione.
							ids = '' if changed == '-' else changed
							logger('Fen Light', 'TraktMonitor: refresh MIRATO su %d titoli e %d azioni%s'
									% (len(ids.split(',')) if ids else 0, len(actions.split(',')) if actions else 0,
										(' [%s]' % actions) if actions else ''))
							refresh_ids_inproc(ids, actions)
						else: run_plugin({'mode': 'kodi_refresh'})
			except Exception as e: logger('Fen Light', trakt_service_string % ('Failed', 'The following Error Occured: %s' % str(e)))
			wait_for_abort(wait_time)
		try: del monitor
		except: pass
		try: del player
		except: pass
		return logger('Fen Light', 'TraktMonitor Service Finished')

	def _defer_widget_refresh(self, window, changed, actions, age):
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
		from modules.kodi_utils import PENDING_REFRESH_PROP, PENDING_IDS_PROP, PENDING_ACTIONS_PROP, PENDING_SCOPE_PROP
		# Questo rinvio nasce da un cambiamento vero su Trakt: vale in qualunque finestra mostri widget,
		# quindi cancella l'eventuale marca lasciata dalla rete di sicurezza di kodi_refresh_ids.
		window.clearProperty(PENDING_SCOPE_PROP)
		# Un rinvio SENZA id vuol dire 'ricostruisci tutto' ed e' un superset di qualunque elenco: se ce
		# n'e' gia' uno in coda, aggiungerci degli id lo RESTRINGEREBBE. E' la stessa ragione per cui
		# _defer_refresh_if_playing cancella gli id invece di lasciarli: WidgetRefresher ricaricherebbe
		# i contenitori del titolo sbagliato invece di ricadere sul globale.
		# Un rinvio GLOBALE in coda e' un superset: non ha ne' id ne' azioni proprio perche' li copre
		# tutti. Si riconosce dall'assenza di ENTRAMBI i canali, non del solo elenco di id -- con la
		# sola verifica sugli id un rinvio nato da un'azione pura (watchlist, continua a guardare)
		# sarebbe stato scambiato per globale e avrebbe cancellato la propria azione.
		pending_global = (bool(window.getProperty(PENDING_REFRESH_PROP))
							and not window.getProperty(PENDING_IDS_PROP)
							and not window.getProperty(PENDING_ACTIONS_PROP))
		changed = '' if changed == '-' else changed
		if (not changed and not actions) or pending_global:
			window.clearProperty(PENDING_IDS_PROP)
			window.clearProperty(PENDING_ACTIONS_PROP)
			window.setProperty(PENDING_REFRESH_PROP, 'kodi_refresh')
			return logger('Fen Light', 'TraktMonitor: refresh GLOBALE rimandato, interfaccia ricostruita %.1fs fa' % age)
		# Gli id di un rinvio precedente non si perdono, si sommano: sono due cambiamenti distinti che
		# nessuno ha ancora mostrato, e chi arriva secondo non ha titolo per cancellare il primo.
		ids = set(i for i in window.getProperty(PENDING_IDS_PROP).split(',') if i)
		ids.update(i for i in changed.split(',') if i)
		# Le azioni si sommano per la stessa ragione, e su un canale separato: sono un criterio
		# diverso, non un altro tipo di id. Vedi paginator.refresh_containers_for_ids.
		acts = set(a for a in window.getProperty(PENDING_ACTIONS_PROP).split(',') if a)
		acts.update(a for a in actions.split(',') if a)
		window.setProperty(PENDING_IDS_PROP, ','.join(sorted(ids)))
		window.setProperty(PENDING_ACTIONS_PROP, ','.join(sorted(acts)))
		window.setProperty(PENDING_REFRESH_PROP, 'kodi_refresh_ids')
		logger('Fen Light', 'TraktMonitor: refresh MIRATO rimandato su %d titoli e %d azioni%s, interfaccia ricostruita %.1fs fa'
				% (len(ids), len(acts), (' [%s]' % ','.join(sorted(acts))) if acts else '', age))

class WidgetRefresher:
	def run(self):
		logger('Fen Light', 'WidgetRefresher Service Starting')
		from time import time
		from caches.settings_cache import get_setting
		from modules.kodi_utils import home, run_plugin, PENDING_REFRESH_PROP, PENDING_IDS_PROP, PENDING_ACTIONS_PROP, PENDING_SCOPE_PROP, refresh_flag_expired
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
		# (paginator.INFLIGHT_PROP, alzata in get_pages e abbassata in set_head) e il rinvio parte
		# APPENA l'ultima si spegne. Nessun numero da indovinare.
		# Il giro e' di un secondo perche' la reazione dev'essere pronta, ma il lavoro periodico resta
		# a dieci (contatore `tick`): quando non c'e' nessun rinvio in attesa il giro veloce costa una
		# sola lettura di proprieta' di finestra, che Kodi serve dalla memoria.
		tick = 0
		while not monitor.abortRequested():
			try:
				wait_for_abort(1)
				if self.window.getProperty(PENDING_REFRESH_PROP):
					if self.pending_since is None: self.pending_since = time()
					if not self.is_playing() and self._nothing_building() and self._widgets_on_screen():
						pending_ids = self.window.getProperty(PENDING_IDS_PROP)
						pending_actions = self.window.getProperty(PENDING_ACTIONS_PROP)
						self.window.clearProperty(PENDING_REFRESH_PROP)
						self.window.clearProperty(PENDING_IDS_PROP)
						self.window.clearProperty(PENDING_ACTIONS_PROP)
						self.window.clearProperty(PENDING_SCOPE_PROP)
						logger('Fen Light', 'WidgetRefresher: rinvio consumato dopo %.1fs di attesa, nessuna costruzione in volo'
								% (time() - self.pending_since))
						self.pending_since = None
						# Con gli id si ricaricano i soli contenitori che li contengono; senza, si ricade
						# sul globale come prima. Vedi lotto 60: gli id c'erano gia' e venivano buttati qui.
						# Le azioni bastano da sole (lotto 119): un rinvio che porta solo
						# 'continue_watching' o 'trakt_watchlist:movie' e' un rinvio MIRATO a tutti gli
						# effetti, e degradarlo a globale perche' l'elenco di id e' vuoto sarebbe
						# esattamente il difetto che il canale delle azioni esiste per togliere.
						if pending_ids or pending_actions:
							refresh_ids_inproc(pending_ids, pending_actions)
						else: run_plugin({'mode': 'refresh_widgets'})
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
		if self.next_refresh == None or self.is_playing() or self.window.getProperty(pause_services_prop) == 'true': return True
		if self.window.getProperty('fenlight.window_loaded') == 'true': return True 
		try:
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
		from caches.settings_cache import get_setting
		from modules.settings import page_limit
		from modules import paginator
		monitor, player = xbmc.Monitor(), xbmc.Player()
		wait_for_abort, is_playing = monitor.waitForAbort, player.isPlayingVideo
		window = xbmcgui.Window(10000)
		get_infolabel = xbmc.getInfoLabel
		pending = {}  # key -> time the loading flag was set, to self-heal a build that never finishes
		# Timeout di autoguarigione per una build che non finisce mai. NON abbassarlo senza misurare:
		# se scade MENTRE la build sta ancora lavorando, il flag LOADING viene tolto sotto i piedi e
		# get_pages() -- che lo legge per decidere se ricostruire N pagine o solo il lotto iniziale --
		# fa collassare il widget alla prima pagina. Sul Mi Stick una ricostruzione cumulativa supera
		# regolarmente gli 8 secondi originali (interprete Python nuovo a ogni build + tutti i widget
		# ricostruiti insieme dall'UpdateLibrary globale): era questa la ragione per cui in home la
		# paginazione non avanzava mai e in cerca si fermava dopo qualche pagina.
		stuck_timeout = 90
		# Secondo timeout, molto piu' corto, per una domanda DIVERSA: non "la build e' lenta?" ma "la
		# build e' mai partita?". Scritto il token, la skin rilegge il <content> e Kodi lancia il plugin
		# entro un attimo -- get_pages timbra LASTBUILD prima di qualunque lavoro, quindi il timbro
		# arriva anche se poi la costruzione dura mezzo minuto. Se dopo questo tempo non e' arrivato
		# NIENTE, il widget non sta leggendo il token: e' un disallineamento fra addon e skin, non
		# lentezza. Vedi LASTBUILD_PROP in paginator.py per il caso reale che lo ha reso necessario.
		no_build_timeout = 20
		token_written = {}   # key -> (istante del TRIGGER, scope, id contenitore, nome proprieta')
		token_reported = set()  # una diagnosi per chiave per sessione: e' un guasto di configurazione, non un evento
		last_current = {}  # key -> last observed focus index, so we load ahead on real downward movement only
		last_log = None  # dedup: only log when the observed state actually changes
		last_scope, census_tick = None, 0  # finestra censita e da quanti giri: vedi CENSUS_TICKS
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
				if is_playing() or window.getProperty(pause_services_prop) == 'true' \
						or get_setting('fenlight.paginate.interactive', 'true') != 'true':
					log_change('idle (off/playing/paused)')
					wait_for_abort(1); continue
				# Never paginate a widget inside an overlay dialog (e.g. the video-info card). Its related
				# lists (cast/recommendations/credits/sets) are bounded, not meant for infinite scroll, and the
				# only widget-refresh primitive available is the GLOBAL UpdateLibrary hack -- it would rebuild
				# every DirectoryProvider in the dialog at once and flicker the whole card. Home/hubs/search,
				# the intended browsing contexts, all live in non-modal windows, so this never gates them.
				if xbmc.getCondVisibility('System.HasActiveModalDialog'):
					log_change('idle (modal dialog open)')
					wait_for_abort(0.5); continue
				# Identify the focused Fen Light widget by container id (skin sets fenlight.active_widget on focus
				# for every widget) and resolve its key via the universal first-item bridge: the plugin published
				# first-item-path -> key, and we read that same path from the container here.
				cur_ctrl = get_infolabel('System.CurrentControlID')
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
				prop_id = window.getProperty('fenlight.active_widget')
				widget_id = None
				if prop_id and xbmc.getCondVisibility('Control.HasFocus(%s)' % prop_id):
					widget_id = prop_id
				elif cur_ctrl and xbmc.getCondVisibility('Control.HasFocus(%s)' % cur_ctrl) \
						and 'plugin.video.fenlight' in get_infolabel('Container(%s).ListItemAbsolute(0).FolderPath' % cur_ctrl):
					widget_id = cur_ctrl
				if widget_id is None:
					log_change('idle cur_ctrl=%s prop=%s' % (cur_ctrl, prop_id))
					wait_for_abort(0.3); continue
				key, first_url = paginator.container_head(widget_id, scope)
				if not key:
					# Contenitore VUOTO con un token residuo: e' la ricerca a casella vuota, dove il path di
					# base sparisce e resterebbe il solo '&pages=N', che Kodi non sa risolvere. Si azzera solo a
					# zero elementi: durante una ricostruzione gli elementi restano e la chiave torna subito,
					# quindi non si rischia di svuotare un widget vivo.
					if int(get_infolabel('Container(%s).NumItems' % widget_id) or 0) == 0:
						window.clearProperty(paginator.CTL_PAGES_PROP % (scope, widget_id))
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
					runway = page_limit(True) * paginator.lookahead_pages()
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
							pages = paginator.raw_pages(key, paginator.initial_batch())
							now = time()
							window.setProperty(paginator.LOADING_PROP % key, str(now))
							window.setProperty(paginator.PAGES_PROP % key, str(pages + 1))
							pending[key] = now
							paginator.log('watcher TRIGGER key=%s pages %s->%s current=%s/%s built=%s -> token ctl%s' %
										(paginator.short(key), pages, pages + 1, current, numitems, built, widget_id))
							# Ricarica MIRATA: il token compare dentro il <content> del widget come $INFO[],
							# quindi cambiarlo fa ricaricare SOLO questo contenitore. Prima si sparava
							# UpdateLibrary, che e' un evento globale: per paginare un widget si
							# ricostruivano tutti quelli della schermata, ognuno con il suo interprete
							# Python nuovo. Era la causa principale della lentezza in home, e la coda di
							# invocazioni che ne usciva e' quella che faceva scadere il flag LOADING.
							ctl_prop = paginator.CTL_PAGES_PROP % (scope, widget_id)
							window.setProperty(ctl_prop, str(pages + 1))
							token_written[key] = (now, ctl_prop, pages + 1)
							wait_for_abort(0.5); continue
			except Exception as e:
				paginator.log('watcher EXC %s' % e)
			wait_for_abort(0.2)
		try: del monitor
		except: pass
		try: del player
		except: pass
		return logger('Fen Light', 'WidgetPaginator Service Finished')

class DubResolver:
	# LOTTO 95, punto 3 del piano concordato: *"coda dei verdetti doppiaggio, risolta dal servizio"*.
	#
	# La costruzione di un widget non fa piu' rete per il filtro doppiaggio: nasconde l'elemento e lo
	# accoda (modules/dub_queue). Qui la coda si svuota, a stick ferma, e i verdetti finiscono in
	# dub_cache. Se qualcuno risulta disponibile si ordina UNA ricarica mirata dei soli contenitori
	# interessati -- alla ricostruzione quegli elementi hanno il verdetto in cache e compaiono senza
	# toccare la rete.
	#
	# Le tre condizioni per lavorare, e la ragione di ognuna:
	#  1. NON si riproduce. Richiesta esplicita dell'utente: *"durante la riproduzione non si fa nulla,
	#     si usa tutto per la riproduzione"*. E' il punto 4 applicato a questo servizio.
	#  2. La coda e' FERMA da QUIET_SECONDS. Finche' i widget si costruiscono continuano ad accodare;
	#     mettersi a fare rete in mezzo all'ondata e' la raffica che le note sui crash dicono di evitare.
	#  3. Per la RICARICA soltanto, non per le interrogazioni: l'utente non sta toccando il telecomando
	#     da IDLE_BEFORE_REFRESH secondi. Gli elementi rientrano al loro posto in lista (l'ordine e'
	#     preservato, invariante del paginatore), quindi cio' che sta sotto il cursore si sposta:
	#     farlo mentre il dito si muove sarebbe esattamente il focus instabile che l'utente ha chiesto
	#     di evitare. Le interrogazioni invece si fanno comunque -- non si vedono.
	POLL = 2.0
	QUIET_SECONDS = 4.0
	IDLE_BEFORE_REFRESH = 3
	# Titoli per giro. Piccolo di proposito: fra un lotto e l'altro si ricontrolla la riproduzione e
	# l'abort, cosi' un film che parte ferma il lavoro entro pochi secondi invece che a coda finita.
	BATCH = 8
	# Oltre questo, la ricarica si fa comunque anche se l'utente non e' mai fermo: meglio uno spostamento
	# di lista che elementi nascosti per sempre in una sessione di navigazione continua.
	MAX_REFRESH_HOLD = 120
	# LOTTO 97. Quante volte si riprova una ricarica che non ha raggiunto NESSUN contenitore, e quanto
	# si aspetta fra un tentativo e l'altro. Vedi il commento al punto in cui si usano.
	REFRESH_ATTEMPTS = 10
	REFRESH_RETRY = 6.0

	def run(self):
		logger('Fen Light', 'DubResolver Service Starting')
		from time import time
		from modules.settings import dub_filter_enabled, dub_filter_country, tmdb_api_key
		from modules import dub_queue, paginator
		monitor, player = xbmc.Monitor(), xbmc.Player()
		wait_for_abort, is_playing = monitor.waitForAbort, player.isPlayingVideo
		window = xbmcgui.Window(10000)
		# Id risolti come DISPONIBILI e non ancora portati a schermo, con l'istante del primo.
		to_show, held_since = [], 0
		tentativi, prossimo_tentativo = 0, 0
		breaker_reported = False
		while not wait_for_abort(self.POLL):
			try:
				if is_playing() or window.getProperty(pause_services_prop) == 'true': continue
				now = time()
				# --- la ricarica in sospeso viene prima: e' cio' che l'utente aspetta di vedere -------
				# Si aspetta che la coda sia VUOTA, non che il lotto sia finito. Un lotto e' 8 titoli:
				# ricaricare a ogni lotto significherebbe, su cache fredda, una decina di ricostruzioni
				# degli stessi contenitori a pochi secondi l'una dall'altra -- la raffica che tutto il
				# resto del lavoro esiste per evitare. Peggio: ogni ricostruzione rimetterebbe in coda i
				# titoli ancora ignoti, alimentando il proprio ciclo. Una sola ricarica a svuotamento.
				# LOTTO 97 -- il guardiano del dialogo, e perche' mancava proprio qui.
				# Con un dialogo modale a schermo l'infolabel Container(N) si risolve contro il DIALOGO,
				# non contro la finestra sotto: refresh_containers_for_ids non trova nessun contenitore
				# Fen Light, torna 0 e non ricarica niente. Il watcher della paginazione questo controllo
				# ce l'ha da sempre (vedi 'idle (modal dialog open)' in WidgetPaginator); qui non era
				# stato riportato, e il difetto e' peggiore di quanto sembri perche' il cancello
				# dell'inattivita' SELEZIONA il caso rotto: stare fermi a leggere la scheda di un film e'
				# proprio cio' che fa crescere getGlobalIdleTime. Misurato sul Mac (log zmac, 26/08): due
				# ricariche alle 02:50:33 e 02:50:59, entrambe dentro il dialogo 13000, entrambe
				# 'contenitori ricaricati 0', e 5 titoli gia' risolti buttati via.
				# Si ferma la sola RICARICA: interrogare la rete dentro un dialogo non da' fastidio a
				# nessuno, non si vede.
				modale = xbmc.getCondVisibility('System.HasActiveModalDialog')
				if to_show and not modale and now >= prossimo_tentativo \
						and (dub_queue.pending_count() == 0 or now - held_since > self.MAX_REFRESH_HOLD) \
						and (xbmc.getGlobalIdleTime() >= self.IDLE_BEFORE_REFRESH
								or now - held_since > self.MAX_REFRESH_HOLD):
					hit = paginator.refresh_containers_for_ids(to_show)
					raggiunti = hit + paginator.LAST_OTHER_HITS[0]
					logger('Fen Light', 'DubResolver: %s titoli tornati disponibili, contenitori ricaricati %s '
							'(altre finestre %s)' % (len(to_show), hit, paginator.LAST_OTHER_HITS[0]))
					# Gli id si buttano SOLO se qualcosa e' stato davvero raggiunto. Prima si svuotava
					# to_show prima ancora di sapere l'esito, quindi una ricarica a vuoto perdeva per
					# sempre verdetti gia' pagati -- ed era muta. Restano i casi legittimi in cui non
					# c'e' niente da ricaricare (finestra Video, nessun widget nostro a schermo): per
					# quelli si riprova qualche volta e poi si lascia perdere, dicendolo.
					if raggiunti:
						to_show, held_since, tentativi, prossimo_tentativo = [], 0, 0, 0
					else:
						tentativi += 1
						prossimo_tentativo = now + self.REFRESH_RETRY
						if tentativi >= self.REFRESH_ATTEMPTS:
							logger('Fen Light', 'DubResolver: %s titoli risolti ma nessun contenitore raggiungibile '
									'dopo %s tentativi. Restano nascosti fino alla prossima ricostruzione del loro '
									'widget, che li mostrera\' leggendo il verdetto dalla cache.'
									% (len(to_show), tentativi))
							to_show, held_since, tentativi, prossimo_tentativo = [], 0, 0, 0
					continue
				if not dub_queue.pending_count(): continue
				if now - dub_queue.last_enqueue() < self.QUIET_SECONDS: continue
				# Il filtro puo' essere stato spento mentre la coda era piena: in quel caso non c'e'
				# niente da risolvere e la coda va buttata, non lavorata.
				if not dub_filter_enabled():
					dub_queue.clear(); continue
				country = dub_filter_country()
				if not country:
					dub_queue.clear(); continue
				api_key = tmdb_api_key()
				batch = dub_queue.drain(self.BATCH)
				if not batch: continue
				from modules.metadata import dub_resolve
				t0, resolved, inconclusive = time(), 0, 0
				for pos, entry in enumerate(batch):
					if monitor.abortRequested() or is_playing():
						# Si restituisce il NON lavorato, compreso quello in corso: e' la sola cosa che
						# rende sicuro il drain distruttivo.
						dub_queue.requeue(batch[pos:]); break
					media_type, tmdb_id, title, year, verify = entry
					try:
						verdict = dub_resolve(country, media_type, tmdb_id, title, year, verify, api_key)
					except Exception as e:
						logger('Fen Light', 'DubResolver: errore su tmdb=%s (%s)' % (tmdb_id, e)); verdict = None
					if verdict is None:
						inconclusive += 1
						continue
					resolved += 1
					# Solo i DISPONIBILI muovono qualcosa a schermo: un negativo conferma cio' che si
					# vede gia' (l'elemento e' nascosto) e non vale una ricostruzione.
					if verdict:
						if not to_show: held_since = time()
						to_show.append(tmdb_id)
				logger('Fen Light', 'DubResolver: lotto di %s in %.1f s | risolti %s (da mostrare %s) | '
						'inconcludenti %s | in coda %s'
						% (len(batch), time() - t0, resolved, len(to_show), inconclusive, dub_queue.pending_count()))
				# La rete muta: se l'interruttore di blu-ray.com e' aperto, il filtro sta nascondendo
				# elementi per una ragione che non e' un verdetto. Va detto, UNA volta per apertura --
				# era la richiesta dell'utente: *"magari una notifica che avvisa l'utente che la rete
				# non ha risposto per il filtro doppiaggio"*.
				breaker_reported = self._report_breaker(inconclusive, breaker_reported)
			except Exception as e:
				logger('Fen Light', 'DubResolver EXC %s' % e)
		try: del monitor
		except: pass
		try: del player
		except: pass
		return logger('Fen Light', 'DubResolver Service Finished')

	def _report_breaker(self, inconclusive, already):
		try:
			from modules.http_client import breaker_state
			is_open, remaining = breaker_state('www.blu-ray.com')
			if not is_open:
				return False   # richiuso: la prossima apertura torna a essere una notizia
			if already or not inconclusive: return already
			from modules.kodi_utils import notification
			notification('Filtro doppiaggio: blu-ray.com non risponde, riprovo fra %s min. '
						'Alcuni titoli restano nascosti.' % max(1, remaining // 60), 6000)
			return True
		except Exception:
			return already

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
		logger('FenLight PERF MEM', 'inizio campionamento | memoria libera %s MB' % last_mem)
		while not wait_for_abort(self.INTERVAL):
			try:
				now = time()
				# Il ritardo si misura SEMPRE, anche a servizi in pausa: e' il campione piu' prezioso
				# proprio quando la macchina e' occupata a fare altro.
				lag = (now - tick_at) - self.INTERVAL
				tick_at = now
				if lag > self.LAG_ALERT:
					if lag > worst_lag: worst_lag = lag
					logger('FenLight PERF CARICO', 'ciclo in ritardo di %.1f s (chiesti %s s) | finestra %s | memoria libera %s MB | ritardo peggiore finora %.1f s'
							% (lag, self.INTERVAL, get_current_window(), free_memory_mb(), worst_lag))
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

	def startServices(self):
		# Prima di far partire TraktMonitor: la costruzione iniziale dei widget che Kodi sta facendo
		# adesso vale come ricostruzione globale, e va registrata o la prima sincronizzazione Trakt ne
		# ordinera' una seconda a vuoto. Vedi kodi_utils.stamp_startup_rebuild.
		from modules.kodi_utils import stamp_startup_rebuild
		stamp_startup_rebuild()
		SetAddonConstants().run()
		DatabaseMaintenance().run()
		SyncSettings().run()
		Thread(target=CustomFonts().run).start()
		# BLUR SPENTO (23/08, richiesta dell'utente). Non differito: proprio non parte. Lo sfondo
		# sfocato ricade sull'artwork nitido, che e' una perdita puramente estetica; in cambio
		# spariscono l'import di Pillow, il ciclo di polling a 0.3s e ogni generazione di immagine.
		# Per riaccenderlo basta ripristinare la riga sotto: e' l'unico punto che lo avvia.
		# Thread(target=self._delayed_blur_start).start()
		Thread(target=TraktMonitor().run).start()
		Thread(target=WidgetRefresher().run).start()
		Thread(target=WidgetPaginator().run).start()
		Thread(target=DubResolver().run).start()
		Thread(target=PerfSampler().run).start()
		AutoStart().run()

	def _delayed_blur_start(self):
		# Aspetta che la tempesta di avvio sia passata prima di importare Pillow e partire col
		# polling: vedi BLUR_START_DELAY per la misura che l'ha motivato. waitForAbort (non sleep)
		# cosi' un abort di Kodi durante l'attesa non lascia il thread appeso.
		if xbmc.Monitor().waitForAbort(BLUR_START_DELAY): return
		BlurService().run()

	def onNotification(self, sender, method, data):
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
			# ricostruzione non era marcata in nessun modo, quindi _get_pages_legacy la trattava come
			# l'apertura di un widget nuovo e tornava 'default' (2 pagine): il contenitore si
			# accorciava, gli elementi si spostavano e il fuoco tornava al primo. Misurato nel log
			# del 29/08: prima di riprodurre 'watcher id=504 current=2/27', dopo la chiusura
			# 'current=1/27', con la firma del contenuto IDENTICA (3c418f7c) -- cioe' non era
			# cambiato niente, si perdeva la posizione e basta.
			#
			# Lo dice gia' il commento di _get_pages_legacy: il conteggio accumulato serve quando
			# "il contenitore deve mantenere la lunghezza corrente cosi' gli elementi restano fermi e
			# il fuoco e' preservato". Il ritorno dalla riproduzione e' esattamente quel caso, e non
			# era nell'elenco. E' anche il problema lasciato aperto a voce in kodi_refresh: "il fuoco
			# resta un problema aperto, da risolvere conservando la posizione".
			#
			# hold_refresh_flag scrive una SCADENZA e torna subito -- nessuna attesa dentro
			# l'invocazione, e a spegnere la bandiera pensa WidgetRefresher, che gira gia'. La
			# finestra di 20 s copre abbondantemente il ritardo osservato fra OnStop (17:18:57,078) e
			# la prima get_pages (17:18:59,031).
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
FenLightMonitor().waitForAbort()
logger('Fen Light', 'Main Monitor Service Finished')