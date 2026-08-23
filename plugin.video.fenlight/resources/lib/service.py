# -*- coding: utf-8 -*-
import xbmc, xbmcgui
import json
from threading import Thread
from modules.blur_service import BlurService

pause_services_prop = 'fenlight.pause_services'
current_skin_prop = 'fenlight.current_skin'
trakt_service_string = 'TraktMonitor Service Update %s - %s'
trakt_success_line_dict = {'success': 'Trakt Update Performed', 'no account': '(Unauthorized) Trakt Update Performed'}
update_string = 'Next Update in %s minutes...'
# Finestra entro cui una ricostruzione globale gia' avvenuta rende superflua quella che Trakt
# chiederebbe. Tarata sopra il ritardo osservato fra le due (7,1 s) e sotto nessun vincolo:
# alzarla sopprime piu' duplicati ma ritarda di piu' un cambiamento fatto DAVVERO altrove.
TRAKT_REFRESH_COALESCE = 30

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
						age = refresh_age()
						if age >= TRAKT_REFRESH_COALESCE: run_plugin({'mode': 'kodi_refresh'})
						else: logger('Fen Light', 'TraktMonitor: refresh saltato, interfaccia ricostruita %.1fs fa' % age)
			except Exception as e: logger('Fen Light', trakt_service_string % ('Failed', 'The following Error Occured: %s' % str(e)))
			wait_for_abort(wait_time)
		try: del monitor
		except: pass
		try: del player
		except: pass
		return logger('Fen Light', 'TraktMonitor Service Finished')

class WidgetRefresher:
	def run(self):
		logger('Fen Light', 'WidgetRefresher Service Starting')
		from time import time
		from caches.settings_cache import get_setting
		from modules.kodi_utils import home, run_plugin, PENDING_REFRESH_PROP, refresh_flag_expired
		self.refresh_flag_expired = refresh_flag_expired
		monitor, player = xbmc.Monitor(), xbmc.Player()
		wait_for_abort, self.is_playing = monitor.waitForAbort, player.isPlayingVideo
		self.window = xbmcgui.Window(10000)
		self.get_setting = get_setting
		self.home = home
		self.window.setProperty('fenlight.refresh_widgets', 'true')
		self.set_next_refresh(time())
		wait_for_abort(20)
		while not monitor.abortRequested():
			try:
				wait_for_abort(10)
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
				if not playing and self.window.getProperty(PENDING_REFRESH_PROP):
					self.window.clearProperty(PENDING_REFRESH_PROP)
					run_plugin({'mode': 'refresh_widgets'})
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
		last_current = {}  # key -> last observed focus index, so we load ahead on real downward movement only
		last_log = None  # dedup: only log when the observed state actually changes
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
				first_url = get_infolabel('Container(%s).ListItemAbsolute(0).FolderPath' % widget_id)
				key = paginator.head_lookup(first_url)
				if not key:
					# Contenitore VUOTO con un token residuo: e' la ricerca a casella vuota, dove il path di
					# base sparisce e resterebbe il solo '&pages=N', che Kodi non sa risolvere. Si azzera solo a
					# zero elementi: durante una ricostruzione gli elementi restano e la chiave torna subito,
					# quindi non si rischia di svuotare un widget vivo.
					if int(get_infolabel('Container(%s).NumItems' % widget_id) or 0) == 0:
						window.clearProperty(paginator.CTL_PAGES_PROP % widget_id)
					log_change('idle id=%s no-head first=%s' % (widget_id, (first_url[:50] or '-')))
					wait_for_abort(0.3); continue
				# Il token vive sul CONTENITORE, la paginazione sulla CHIAVE del widget: quando il contenitore
				# cambia inquilino il token del precedente va azzerato, o il widget nuovo si aprirebbe
				# direttamente alle pagine accumulate da quello vecchio.
				if window.getProperty(paginator.CTL_KEY_PROP % widget_id) != key:
					window.setProperty(paginator.CTL_KEY_PROP % widget_id, key)
					window.clearProperty(paginator.CTL_PAGES_PROP % widget_id)
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
							window.setProperty(paginator.CTL_PAGES_PROP % widget_id, str(pages + 1))
							wait_for_abort(0.5); continue
			except Exception as e:
				paginator.log('watcher EXC %s' % e)
			wait_for_abort(0.2)
		try: del monitor
		except: pass
		try: del player
		except: pass
		return logger('Fen Light', 'WidgetPaginator Service Finished')

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
		SetAddonConstants().run()
		DatabaseMaintenance().run()
		SyncSettings().run()
		Thread(target=CustomFonts().run).start()
		Thread(target=BlurService().run).start()
		Thread(target=TraktMonitor().run).start()
		Thread(target=WidgetRefresher().run).start()
		Thread(target=WidgetPaginator().run).start()
		AutoStart().run()

	def onNotification(self, sender, method, data):
		if method in ('GUI.OnScreensaverActivated', 'System.OnSleep'):
			xbmcgui.Window(10000).setProperty(pause_services_prop, 'true')
			logger('OnNotificationActions', 'PAUSING Fen Light Services Due to Device Sleep')
		elif method in ('GUI.OnScreensaverDeactivated', 'System.OnWake'):
			xbmcgui.Window(10000).clearProperty(pause_services_prop)
			logger('OnNotificationActions', 'UNPAUSING Fen Light Services Due to Device Awake')

logger('Fen Light', 'Main Monitor Service Starting')
FenLightMonitor().waitForAbort()
logger('Fen Light', 'Main Monitor Service Finished')