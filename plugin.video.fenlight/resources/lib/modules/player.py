# -*- coding: utf-8 -*-
import json
from threading import Thread
from apis.trakt_api import make_trakt_slug, trakt_scrobble_start, trakt_scrobble_stop, trakt_official_status
from caches.settings_cache import get_setting
from modules import kodi_utils as ku, settings as st, watched_status as ws
# logger = ku.logger

set_property, clear_property, get_visibility, hide_busy_dialog, xbmc_actor = ku.set_property, ku.clear_property, ku.get_visibility, ku.hide_busy_dialog, ku.xbmc_actor
xbmc_player, execute_builtin, sleep = ku.xbmc_player, ku.execute_builtin, ku.sleep
make_listitem, volume_checker, get_infolabel, xbmc_monitor = ku.make_listitem, ku.volume_checker, ku.get_infolabel, ku.xbmc_monitor
close_all_dialog, notification, poster_empty, fanart_empty = ku.close_all_dialog, ku.notification, ku.empty_poster, ku.get_addon_fanart()
auto_resume, auto_nextep_settings, store_resolved_to_cloud = st.auto_resume, st.auto_nextep_settings, st.store_resolved_to_cloud
set_bookmark, mark_movie, mark_episode = ws.set_bookmark, ws.mark_movie, ws.mark_episode
PLAYBACK_ACTIVE_PROP = ku.PLAYBACK_ACTIVE_PROP
mark_playback_start = ku.mark_playback_start
# Istante in cui lo stato locale (segnalibro o visto) e' stato scritto davvero. Non e' l'istante di
# chiusura del player: fra i due passa il tempo del sondaggio piu' quello della scrittura, e in mezzo
# Kodi ricostruisce. Solo una ricostruzione posteriore a QUESTO timbro ha potuto vedere il dato nuovo.
WRITE_DONE_PROP = 'fenlight.perf.write_done'
total_time_errors = ('0.0', '', 0.0, None)
set_resume, set_watched = 5, 90
video_fullscreen_check = 'Window.IsActive(fullscreenvideo)'

class FenLightPlayer(xbmc_player):
	def __init__ (self):
		xbmc_player.__init__(self)

	def onAVStarted(self):
		self._av_started = True
		# Proprieta' di finestra normale, non una condizione della GUI. La diagnostica dei widget deve
		# poter sapere se un video e' in corso senza chiamare getCondVisibility dal thread del plugin:
		# quella chiamata attraversa il lock grafico proprio mentre il thread GUI aspetta la cartella
		# che stiamo costruendo. Vedi paginator._diag_note e il commento in end_directory.
		try: mark_playback_start()
		except: pass

	# LOTTO 121 -- LA FINE DELLA RIPRODUZIONE SI SA PER EVENTO, NON SONDANDO.
	# Finora l'unico rilevatore era il ciclo di monitor(), che dorme un secondo per giro: la scrittura
	# del punto di ripresa partiva quindi fra 0 e 1000 ms dopo la fine reale. Nel frattempo Kodi, che
	# l'evento ce l'ha subito, torna alla finestra sottostante e ne rilegge le cartelle. Misurato sul
	# Mac il 01/09:
	#     42.112  OnPlayBackStopped          <- l'evento
	#     42.133  GetDirectory (stagioni)    <- Kodi rilegge, 21 ms dopo
	#     42.157  pannello episodi           <- e qui, 45 ms dopo
	#     42.234  il nostro ciclo si sveglia <- 122 ms dopo, e solo ORA si scrive
	# Il pannello veniva quindi disegnato PRIMA che il punto di ripresa esistesse, e restava senza
	# badge fino al rientro nella serie (21:52:57, sedici secondi dopo). Non era un ritardo: era un
	# ordine sbagliato, e la corsa la perdevamo per costruzione.
	# Agganciando l'evento si scrive entro pochi millisecondi dalla chiusura, cioe' PRIMA della
	# rilettura di Kodi: quella rilettura -- che avviene comunque e che non possiamo spegnere (vedi la
	# nota su cacheToDisc in indexers/episodes.py) -- mostra da sola il dato giusto.
	# media_marked fa da guardia: chi arriva secondo fra evento e ciclo non rifa' niente.
	def onPlayBackStopped(self):
		self._playback_finished()

	def onPlayBackEnded(self):
		self._playback_finished()

	def _playback_finished(self):
		# Si entra solo per una riproduzione NOSTRA e davvero avviata: per un video generico non c'e'
		# niente da segnare, e senza onAVStarted non c'e' nemmeno una posizione da scrivere.
		try:
			if getattr(self, 'is_generic', True): return
			if not getattr(self, '_av_started', False): return
			if getattr(self, 'media_marked', False): return
			self.media_watched_marker()
		except: pass

	def onPlayBackSeek(self, time, seekOffset):
		# Si aggiorna SOLO la posizione: nessuna chiamata a Trakt e nessuna marcatura qui.
		# Trakt riceve uno scrobble start all'avvio e uno stop alla chiusura, niente altro.
		try:
			if getattr(self, 'is_generic', True) or not getattr(self, '_av_started', False): return
			total = getattr(self, 'total_time', 0) or 0
			if not total: return
			self.curr_time = time / 1000.0
			self.current_point = round(float(self.curr_time / total * 100), 1)
		except: pass
 

	def run(self, url=None, obj=None):
		hide_busy_dialog()
		self.clear_playback_properties()
		if not url: return self.run_error()
		try: return self.play_video(url, obj)
		except: return self.run_error()

	def play_video(self, url, obj):
		self.set_constants(url, obj)
		volume_checker()
		# La bandiera si alza QUI, non in onAVStarted (lotto 111). onAVStarted arriva quando audio e
		# video sono davvero partiti: nel log del 29/08 sono le 16:00:07,5, mentre l'ondata di
		# ricostruzione dei widget che deve fermare parte alle 16:00:02,3 -- cinque secondi prima,
		# subito dopo Player.OnPlay. Alzarla prima di self.play() e' l'unico istante che non e' una
		# corsa: qui l'annuncio non e' ancora stato emesso. Dal lotto 113 la bandiera non taglia piu'
		# nessuna costruzione: resta come stato leggibile senza toccare la GUI, e timbra l'istante da
		# cui la riga PERF misura quanto lavoro di interfaccia cade sull'avvio del film.
		try: mark_playback_start()
		except: pass
		self.play(self.url, self.make_listing())
		if not self.is_generic:
			self.check_playback_start()
			if self.playback_successful: self.monitor()
			else:
				# Fallimento accertato: la bandiera va giu' SUBITO. self.stop() qui sotto non produce
				# nessun Player.OnStop se non c'era niente in riproduzione, quindi il presidio del
				# service non scatterebbe. Vedi clear_playback_properties.
				try: clear_property(PLAYBACK_ACTIVE_PROP)
				except: pass
				self.sources_object.playback_successful = self.playback_successful
				self.sources_object.cancel_all_playback = self.cancel_all_playback
				if self.cancel_all_playback: self.kill_dialog()
				self.stop()
			try: del self.kodi_monitor
			except: pass

	def check_playback_start(self):
		resolve_percent = 0
		while self.playback_successful is None:
			hide_busy_dialog()
			if not self.sources_object.progress_dialog: self.playback_successful = True
			elif self.sources_object.progress_dialog.skip_resolved(): self.playback_successful = False
			elif self.sources_object.progress_dialog.iscanceled() or self.kodi_monitor.abortRequested(): self.cancel_all_playback, self.playback_successful = True, False
			elif resolve_percent >= 100: self.playback_successful = False
			elif get_visibility('Window.IsTopMost(okdialog)'):
				execute_builtin('SendClick(okdialog, 11)')
				self.playback_successful = False
			elif self.isPlayingVideo():
				try:
					if self.getTotalTime() not in total_time_errors and get_visibility(video_fullscreen_check): self.playback_successful = True
				except: pass
			resolve_percent = round(resolve_percent + 26.0/100, 1)
			self.sources_object.progress_dialog.update_resolver(percent=resolve_percent)
			sleep(200)

	def playback_close_dialogs(self):
		self.sources_object.playback_successful = True
		self.kill_dialog()
		sleep(200)
		close_all_dialog()

	def monitor(self):
		try:
			ensure_dialog_dead, total_check_time = False, 0
			if self.media_type == 'episode':
				play_random_continual = self.sources_object.random_continual
				play_random = self.sources_object.random
				disable_autoplay_next_episode = self.sources_object.disable_autoplay_next_episode
				if disable_autoplay_next_episode: notification('Scrape with Custom Values - Autoplay Next Episode Cancelled', 4500)
				if any((play_random_continual, play_random, disable_autoplay_next_episode)): self.autoplay_nextep, self.autoscrape_nextep = False, False
				else: self.autoplay_nextep, self.autoscrape_nextep = self.sources_object.autoplay_nextep, self.sources_object.autoscrape_nextep
				# LA MAPPA STA NELLA META, O NON ESISTE (lotto 144). Qui c'era un ripiego che, quando la
				# meta non aveva 'tvdb_to_tmdb_ep', importava skyhook_api e chiamava get_tvdb_to_tmdb_map.
				# Non poteva funzionare, e non funzionava mai: le due chiavi 'tvdb_to_tmdb_ep' e
				# 'tmdb_season_data_original' si scrivono nello STESSO blocco di tvshow_meta (metadata.py,
				# righe 935 e 939), quindi se manca la prima manca anche la seconda -- e il ripiego riceveva
				# una lista vuota, da cui la mappa esce vuota per costruzione. Codice morto in ogni ramo.
				# Il prezzo non era zero: si pagava a OGNI riproduzione di episodio, anime o no, ed era
				# _fetch_raw sull'intero JSON skyhook della serie (105 KB per Hunter x Hunter) per ottenere
				# {} -- rete a cache fredda, e comunque una lettura di metacache piu' un json.loads sul
				# percorso caldo. Per una serie NON anime la chiave non c'e' mai, quindi il ripiego scattava
				# sempre.
				# TRE esiti, non due (lotto 145). None vuol dire che questo episodio su Trakt non
				# esiste: si riproduce normalmente, ma non si scrobbla -- mandare una coppia
				# inventata segnerebbe come visto un altro episodio.
				from modules.utils import traduci_episodio
				_coppia = traduci_episodio(self.meta.get('tvdb_to_tmdb_ep'), self.meta.get('ep_esclusi_tvdb'),
											self.season, self.episode)
				self._trakt_mappabile = _coppia is not None
				self._trakt_season, self._trakt_episode = _coppia if _coppia else (self.season, self.episode)
			else:
				play_random_continual, self.autoplay_nextep, self.autoscrape_nextep = False, False, False
				self._trakt_mappabile = True
				self._trakt_season, self._trakt_episode = self.season, self.episode
			while total_check_time <= 30 and not get_visibility(video_fullscreen_check):
				sleep(200)
				total_check_time += 0.10
			hide_busy_dialog()
			# ATTESA ESPLICITA (lotto 111), al posto di un sleep(1000) scritto a mano.
			# Quel secondo era la finestra di caricamento che restava sopra il player: misurata nel
			# log del 29/08, VideoFullScreen si apre alle 16:00:07,426 e sources_playback.xml muore
			# alle 16:00:08,746 -- 1,3 s in cui l'utente vede la schermata di Fen Light ricomparire
			# sopra il video gia' partito. Non era un caricamento: era un'attesa a vuoto.
			# La condizione vera e' onAVStarted, cioe' Kodi che dichiara audio e video avviati
			# (Player.OnAVStart, alle 16:00:07,561 nello stesso log): 1,2 s prima, e per un motivo
			# invece che per un numero. Il limite di 3 s non e' il criterio di uscita ma un
			# rompi-stallo: se l'annuncio non arrivasse, la finestra non deve restare appesa.
			_atteso = 0.0
			while not getattr(self, '_av_started', False) and _atteso < 3.0 and self.isPlayingVideo():
				sleep(50)
				_atteso += 0.05
			while self.isPlayingVideo():
				try:
					try: self.total_time, self.curr_time = self.getTotalTime(), self.getTime()
					except: sleep(250); continue
					if not ensure_dialog_dead:
						ensure_dialog_dead = True
						self.playback_close_dialogs()
						if st.trakt_user_active() and trakt_official_status(self.media_type) and self._trakt_mappabile:
							Thread(target=trakt_scrobble_start, args=(self.media_type, self.tmdb_id, self._trakt_season, self._trakt_episode)).start()
							self.scrobble_started = True
						from modules.auto_subtitles import auto_subtitle_check
						Thread(target=auto_subtitle_check, args=(self,)).start()

					sleep(1000)
					self.current_point = round(float(self.curr_time/self.total_time * 100), 1)
					# Durante la riproduzione non si tocca ne' Trakt ne' il database dei visti: niente
					# rinvio periodico dello scrobble (era ogni 120s) e niente marcatura al 90%. Tutto
					# avviene una volta sola all'uscita dal ciclo, con la percentuale reale di chiusura.
					if self.current_point >= set_watched:
						if play_random_continual: self.run_random_continual(); break
					if self.autoplay_nextep or self.autoscrape_nextep:
						if not self.nextep_info_gathered: self.info_next_ep()
						if round(self.total_time - self.curr_time) <= self.start_prep: self.run_next_ep(); break
				except: pass
			hide_busy_dialog()
			if not self.media_marked: self.media_watched_marker()
			self.clear_playback_properties()
			self.clear_playing_item()
			Thread(target=self.flush_pending_refresh).start()
		except:
			hide_busy_dialog()
			self.sources_object.playback_successful = False
			self.sources_object.cancel_all_playback = True
			return self.kill_dialog()

	def make_listing(self):
		listitem = make_listitem()
		listitem.setPath(self.url)
		listitem.setContentLookup(False)
		if self.is_generic:
			info_tag = listitem.getVideoInfoTag()
			info_tag.setMediaType('video')
			info_tag.setFilenameAndPath(self.url)
		else:
			self.tmdb_id, self.imdb_id, self.tvdb_id = self.meta_get('tmdb_id', ''), self.meta_get('imdb_id', ''), self.meta_get('tvdb_id', '')
			self.media_type, self.title, self.year = self.meta_get('media_type'), self.meta_get('title'), self.meta_get('year')
			self.season, self.episode = self.meta_get('season', ''), self.meta_get('episode', '')
			self.auto_resume = auto_resume(self.media_type)
			poster = self.meta_get('poster') or poster_empty
			fanart = self.meta_get('fanart') or fanart_empty
			clearlogo = self.meta_get('clearlogo') or ''
			duration, plot, genre, trailer, mpaa = self.meta_get('duration'), self.meta_get('plot'), self.meta_get('genre', ''), self.meta_get('trailer'), self.meta_get('mpaa')
			rating, votes = self.meta_get('rating'), self.meta_get('votes')
			premiered, studio, tagline = self.meta_get('premiered'), self.meta_get('studio', ''), self.meta_get('tagline')
			director, writer, cast, country = self.meta_get('director', ''), self.meta_get('writer', ''), self.meta_get('cast', []), self.meta_get('country', '')
			listitem.setLabel(self.title)
			if self.media_type == 'movie':
				listitem.setArt({'poster': poster, 'fanart': fanart, 'icon': poster, 'clearlogo': clearlogo})
				info_tag = listitem.getVideoInfoTag()
				info_tag.setMediaType('movie'), info_tag.setTitle(self.title), info_tag.setOriginalTitle(self.meta_get('original_title')), info_tag.setPlot(plot)
				info_tag.setYear(int(self.year)), info_tag.setRating(rating), info_tag.setVotes(votes), info_tag.setMpaa(mpaa)
				info_tag.setDuration(duration), info_tag.setCountries(country), info_tag.setTrailer(trailer), info_tag.setPremiered(premiered)
				info_tag.setTagLine(tagline), info_tag.setStudios(studio), info_tag.setIMDBNumber(self.imdb_id), info_tag.setGenres(genre)
				info_tag.setWriters(writer), info_tag.setDirectors(director), info_tag.setUniqueIDs({'imdb': self.imdb_id, 'tmdb': str(self.tmdb_id)})
				info_tag.setCast([xbmc_actor(name=item['name'], role=item['role'], thumbnail=item['thumbnail']) for item in cast])
			else:
				listitem.setArt({'poster': poster, 'fanart': fanart, 'icon': poster, 'clearlogo': clearlogo, 'tvshow.poster': poster, 'tvshow.clearlogo': clearlogo})
				info_tag = listitem.getVideoInfoTag()
				info_tag.setMediaType('episode'), info_tag.setTitle(self.meta_get('ep_name')), info_tag.setOriginalTitle(self.meta_get('original_title'))
				info_tag.setTvShowTitle(self.title), info_tag.setTvShowStatus(self.meta_get('status')), info_tag.setSeason(self.season), info_tag.setEpisode(self.episode)
				info_tag.setPlot(plot), info_tag.setYear(int(self.year)), info_tag.setRating(rating), info_tag.setVotes(votes)
				info_tag.setMpaa(mpaa), info_tag.setDuration(duration), info_tag.setTrailer(trailer), info_tag.setFirstAired(premiered)
				info_tag.setStudios(studio), info_tag.setIMDBNumber(self.imdb_id), info_tag.setGenres(genre), info_tag.setWriters(writer)
				info_tag.setDirectors(director), info_tag.setUniqueIDs({'imdb': self.imdb_id, 'tmdb': str(self.tmdb_id), 'tvdb': str(self.tvdb_id)})
				info_tag.setCast([xbmc_actor(name=item['name'], role=item['role'], thumbnail=item['thumbnail']) for item in cast])
				info_tag.setFilenameAndPath(self.url)
			self.set_resume_point(listitem)
			self.set_playback_properties()
		return listitem

	def media_watched_marker(self, force_watched=False):
		self.media_marked = True
		try: clear_property(PLAYBACK_ACTIVE_PROP)
		except: pass
		# PERF: timbro della chiusura, letto da paginator.log_build. Serve a UNA domanda sola: quanto
		# ci mette Kodi a rileggere da solo la cartella aperta uscendo dal player? E' l'attesa che il
		# sleep(2000) di run_media_progress deve coprire, e quel 2000 non e' mai stato misurato --
		# su Mac la rilettura arriva a 390-653 ms, ma il numero che conta e' quello del Mi Stick.
		try:
			from time import time as _now
			ku.set_property('fenlight.perf.closefile', str(_now()))
			# Timbro "questa modifica e' nostra" anche quando NON marchiamo niente. Finora lo metteva
			# solo watched_status._mark_on_trakt, cioe' solo se si superava la soglia di visto: chiudere
			# un film a meta' mandava comunque uno scrobble stop a Trakt, il monitor lo rileggeva come
			# cambiamento remoto e ordinava una ricostruzione GLOBALE di tutti i widget.
			# Nel log della stick del 23/08: CloseFile 14:18:40.877 -> 'Trakt Update Performed'
			# 14:18:45.895 -> 'DIAG refresh: GLOBALE (UpdateLibrary)' 14:18:48.472, e dietro otto
			# ricostruzioni di widget in cinquanta secondi. E' la risposta alla domanda "perche' si
			# aggiornano TUTTI i widget quando chiudo il player".
			# episode -> tvshow: la guardia ragiona per database, non per tipo di media.
			ku.set_property('fenlight.trakt.self_mark',
							'%s|%s' % (_now(), 'tvshow' if self.media_type == 'episode' else 'movie'))
		except: pass
		if self.scrobble_started:
			Thread(target=trakt_scrobble_stop, args=(self.media_type, self.tmdb_id, self.current_point, self._trakt_season, self._trakt_episode)).start()
		try:
			if self.current_point >= set_watched or force_watched:
				if self.media_type == 'movie': watched_function = mark_movie
				else: watched_function = mark_episode
				watched_params = {'action': 'mark_as_watched', 'tmdb_id': self.tmdb_id, 'title': self.title, 'year': self.year, 'season': self.season, 'episode': self.episode,
									'tvdb_id': self.tvdb_id, 'from_playback': 'true'}
				# mark_movie/mark_episode con from_playback NON fanno alcun refresh (mettono refresh=False),
				# quindi finora finire un film non aggiornava i widget: lo si chiede qui. La ricostruzione
				# e' comunque rimandata a fine riproduzione dal gate in kodi_utils, quindi passando
				# all'episodio successivo non si ricostruisce nulla mentre il video va.
				# IN UN THREAD, e il lotto 121 aveva provato a renderla sincrona sbagliando la stima.
				# "Una manciata di operazioni SQLite" era falso: misurato sulla stick il 02/09,
				# 827 ms e 175 ms (riga DIAG qui sotto). Non e' la INSERT -- sono le letture di
				# impostazioni e lo stato degli addon che set_bookmark/mark_episode fanno prima, su
				# eMMC e mentre il player si sta smontando. Tenere un thread occupato cosi' a lungo
				# proprio in quel momento non e' accettabile, e la finestra di 45 ms non si vince
				# comunque. Vedi _order_refresh_after_write per come si arriva lo stesso al badge.
				Thread(target=self.run_media_progress, args=(watched_function, watched_params, True)).start()
			else:
				clear_property('fenlight.random_episode_history')
				if self.current_point >= set_resume:
					progress_params = {'media_type': self.media_type, 'tmdb_id': self.tmdb_id, 'curr_time': self.curr_time, 'total_time': self.total_time,
									'title': self.title, 'season': self.season, 'episode': self.episode, 'from_playback': 'true'}
					Thread(target=self.run_media_progress, args=(set_bookmark, progress_params, True)).start()
		except: pass

	def flush_pending_refresh(self):
		# Esegue, a riproduzione finita, l'unico refresh eventualmente rimandato da kodi_utils mentre il
		# video era in corso. L'attesa lascia passare prima il refresh dello stato, che ora parte da
		# _order_refresh_after_write subito dopo la scrittura e azzera la stessa proprieta': cosi' si
		# ricostruisce una volta sola. Per una riproduzione NOSTRA questa funzione trova quindi quasi
		# sempre la proprieta' gia' azzerata e non fa niente; il caso che serve davvero e' il video
		# generico (trailer, file esterno), dove run_media_progress non gira e non c'e' nessun tmdb_id.
		try:
			if not ku.get_property(ku.PENDING_REFRESH_PROP): return
			ku.sleep(3000)
			kind = ku.get_property(ku.PENDING_REFRESH_PROP)
			if not kind: return
			ku.clear_property(ku.PENDING_REFRESH_PROP)
			# Ricarica MIRATA quando sappiamo cosa e' cambiato, ed e' il caso piu' frequente: e' finito UN
			# film. Solo i contenitori che lo contengono vanno ricostruiti; per gli altri non e' cambiato
			# niente. Se il sondaggio non identifica nessun contenitore, kodi_refresh_ids ricade da sola
			# sul globale, quindi questo ramo non puo' comportarsi peggio di quello di prima.
			if self.kodi_rebuilt_by_itself(): return
			tmdb_id = str(getattr(self, 'tmdb_id', '') or '')
			# Mirato per ENTRAMBI i tipi di richiesta: kodi_refresh_ids alza da sola
			# fenlight.refresh_widgets, quindi la distinzione che c'era qui non serve piu'. Con il ramo
			# 'refresh_widgets' ancora globale, nel log del 22/08 00:24:16 usciva uno scan globale a 46 ms
			# dal refresh mirato di run_media_progress: due ricostruzioni per lo stesso evento.
			# L'azione accompagna sempre l'id (lotto 114): finito un film, 'continua a guardare' cambia
			# composizione -- il titolo entra se e' rimasto a meta', esce se e' arrivato in fondo.
			if tmdb_id: return ku.kodi_refresh_ids([tmdb_id], (ku.CONTINUE_WATCHING_ACTION,))
			ku.run_plugin({'mode': 'refresh_widgets' if kind == 'refresh_widgets' else 'kodi_refresh'})
		except: pass

	# Quanto si aspetta, uscendo dal player, per vedere se Kodi ricostruisce da sola. Sulla stick la
	# sua rilettura arriva 15-17 s dopo la chiusura (log 22/08: CloseFile 23:15:04.818, prima
	# costruzione 23:15:20.219), quindi una finestra corta non la vedrebbe mai e continueremmo a
	# ordinare la seconda ondata. Attendere non costa una tempesta: e' un thread fermo dentro un
	# interprete gia' vivo, contro tre-cinque ricostruzioni da 2.5-4 s l'una.
	# Misurato sulla stick il 23/08: la rilettura spontanea di Kodi arriva a 4.8s, 9.7s e 13.2s dalla
	# chiusura. Venti secondi la coprivano sempre, ma quando NON arrivava si finiva a ordinare una
	# ricarica venti secondi dopo l'evento -- cioe' mentre l'utente sta gia' facendo altro, con la
	# lista che si ricostruisce sotto le sue dita. Quattordici copre i casi osservati e accorcia di
	# sei secondi il ritardo peggiore.
	REBUILD_WAIT_SECONDS = 14

	def kodi_rebuilt_by_itself(self):
		"""Vero se Kodi ha gia' riletto le cartelle per conto suo dopo la chiusura del player.

		Uscendo dal player la finestra sottostante torna in primo piano e Kodi rilegge i suoi
		DirectoryProvider senza che nessuno glielo chieda. Nel log della stick del 22/08 questo e la
		NOSTRA ricarica mirata producevano due ondate distinte: la stessa lista (mdblist 91378, 48
		elementi) costruita a +18160 ms dalla chiusura e di NUOVO a +27545 ms. Ventiquattro secondi di
		ricostruzioni per un badge.
		Se Kodi ci arriva prima, la nostra ricarica non aggiunge niente: la riga di visto e' gia'
		scritta in locale PRIMA di tutto questo, quindi la sua rilettura legge gia' il dato giusto.

		ATTENZIONE (lotto 121): quell'ultima frase era FALSA, ed e' costata il badge dell'episodio.
		Fino al lotto 121 lo stato si scriveva dal ciclo di monitor(), che se ne accorge con un
		sondaggio da un secondo: la rilettura di Kodi arrivava PRIMA della scrittura e mostrava il dato
		vecchio. Ora la scrittura parte dalla callback onPlayBackStopped e la precede davvero, quindi
		la premessa e' vera -- ma solo per una riproduzione NOSTRA, che e' il caso in cui questa
		funzione non viene piu' chiamata.
		Restano due limiti che rendono questa guardia inadatta al percorso mirato, ed e' il motivo per
		cui li' non si usa: risponde a "e' stato ricostruito QUALCOSA, da QUALCHE PARTE", mentre la
		domanda utile e' "e' stato ricostruito il contenitore che l'utente sta guardando, e dopo che il
		dato esisteva"; e legge LAST_BUILD_PROP, che copre i soli WIDGET -- la cartella aperta di una
		finestra non lo accende mai (vedi open_folder_built_since).
		Qui sopravvive perche' il suo ripiego e' un refresh globale, dove sbagliare per eccesso di
		prudenza costa molto piu' che sbagliare per difetto.
		"""
		try:
			from time import time as _now
			close_ts = ku.get_property('fenlight.perf.closefile') or 0
			if not close_ts: return False
			deadline = _now() + self.REBUILD_WAIT_SECONDS
			while _now() < deadline:
				if ku.directory_built_since(close_ts):
					ku.logger('Fen Light', 'DIAG refresh: NON ordinato, Kodi ha gia' + "'" + ' ricostruito da sola %.1fs dopo la chiusura'
								% (float(ku.get_property(ku.LAST_BUILD_PROP) or 0) - float(close_ts)))
					return True
				ku.sleep(500)
			# Un ULTIMO controllo dopo la scadenza. Il ciclo verifica solo prima di dormire, quindi una
			# ricostruzione arrivata negli ultimi 500 ms passava inosservata e ne ordinavamo un'altra
			# sopra. Misurato il 24/08: build_continue_watching chiude alle 16:06:25.819 e questo
			# messaggio esce alle 16:06:26.171 -- 352 ms di scarto, e un'ondata di ricostruzioni in piu'.
			if ku.directory_built_since(close_ts):
				ku.logger('Fen Light', 'DIAG refresh: NON ordinato, ricostruzione rilevata al controllo finale')
				return True
			ku.logger('Fen Light', 'DIAG refresh: nessuna ricostruzione spontanea entro %ss, la ordiniamo noi' % self.REBUILD_WAIT_SECONDS)
		except: pass
		return False

	def run_media_progress(self, function, params, do_refresh=False):
		"""Scrive lo stato in locale (SINCRONO) e poi ordina il ridisegno (asincrono).

		La divisione fra le due meta' e' il punto del lotto 121. La scrittura deve stare davanti alla
		rilettura spontanea di Kodi -- una manciata di millisecondi -- percio' non puo' passare da un
		thread. Il ridisegno invece puo' aspettare: nessuno lo guarda finche' non e' finito.
		"""
		try:
			from time import perf_counter as _pc
			_t0 = _pc()
			function(params)
			# Le memorizzazioni dello stato visto vanno invalidate QUI, non nel thread del refresh: la
			# rilettura di Kodi arriva entro poche decine di millisecondi e le leggerebbe ancora
			# vecchie, mostrando il dato di prima con il database gia' aggiornato.
			if do_refresh:
				for _b1, _b2 in ((True, True), (True, False), (False, True), (False, False)):
					ku.clear_property('1_%s_%s_%s_watched' % (self.media_type, _b1, _b2))
			_ms = (_pc() - _t0) * 1000
			# L'ISTANTE IN CUI IL DATO ESISTE. E' il riferimento giusto per decidere se una
			# ricostruzione ha visto lo stato nuovo: quella di Kodi che parte alla chiusura del player
			# di solito e' ANTERIORE e non prova niente. Vedi _open_folder_rebuilt_after_write.
			try:
				from time import time as _now
				ku.set_property(WRITE_DONE_PROP, str(_now()))
			except: pass
			try: ku.logger('Fen Light', 'DIAG scrittura stato locale: %.0f ms (su %s)' % (_ms, function.__name__))
			except: pass
			if do_refresh: self._order_refresh_after_write()
		except: pass

	def _open_folder_rebuilt_after_write(self):
		"""Solo per la finestra Video: Kodi sta gia' ricostruendo la cartella aperta con il dato nuovo?

		Serve a UN caso preciso, e fuori da quello non va applicata. Nella finestra Video (10025) la
		nostra ricarica mirata si riduce a un `Container.Refresh` sulla cartella aperta -- che e'
		esattamente la cartella che Kodi sta gia' rileggendo per conto suo al ritorno dal player. Il
		lotto 121 aveva tolto ogni guardia dando per scontato che "mirato" volesse dire "a buon
		mercato": misurato sulla stick il 02/09, vuol dire invece DUE build_season_list in parallelo,
		2365 ms e 2160 ms -- quasi tutto import -- e la schermata vuota per 2,2 s con il pannello
		episodi a +3,9 s dalla chiusura. Due ricostruzioni della stessa cartella, una di troppo.

		Il confronto e' con l'istante della SCRITTURA, non con quello di chiusura del player: e' la
		correzione dell'errore che aveva reso inutile la vecchia guardia. Una ricostruzione anteriore
		alla scrittura mostra lo stato vecchio e non conta.

		Fuori dalla finestra Video non si aspetta niente: li' la ricarica mirata non ricostruisce la
		cartella aperta, cambia i token dei contenitori interessati e scarta gli altri -- e quello e'
		il comportamento che i test del lotto 119 hanno confermato buono.

		LOTTO 125 -- la domanda ora nomina IL CONTENITORE, non solo l'istante. Prima bastava "una
		cartella aperta, una qualunque, ricostruita dopo la scrittura", e nella finestra di una serie
		le cartelle sono due: la lista STAGIONI (la cartella aperta) e il PANNELLO EPISODI (un
		DirectoryProvider, quindi timbrato fra i widget). Il segnalibro lo disegna solo il secondo.
		Nel log della stick del 02/09 alle 12:12 la guardia si e' accontentata delle stagioni
		(costruite a +0,6 s dalla scrittura) e il pannello e' arrivato a +1,3 s: il risultato e' stato
		giusto, ma per come stavano i tempi, non perche' fosse stato verificato. Bastava che il
		pannello si ricostruisse PRIMA della scrittura e le stagioni dopo -- l'ordine non e' garantito
		da niente -- per avere la guardia soddisfatta e il badge vecchio a schermo: esattamente il
		difetto intermittente che stiamo inseguendo da tre lotti.
		Adesso per un episodio si aspetta il pannello di QUELLA serie, e per un film la cartella
		aperta di cui si e' verificata l'identita'. Se la verifica non riesce entro il tempo massimo
		si ordina il refresh: il caso peggiore torna a essere una ricostruzione di troppo, mai un
		badge vecchio.
		"""
		try:
			# La finestra la si guarda quando ha SMESSO di cambiare: vedi _wait_window_settled, che
			# il chiamante ha gia' eseguito. Qui si assume che 12005 sia passata.
			if ku.getCurrentWindowId() != 10025: return False
			from time import time as _now
			write_ts = ku.get_property(WRITE_DONE_PROP) or 0
			if not write_ts: return False
			tmdb_id = str(getattr(self, 'tmdb_id', '') or '')
			is_episode = getattr(self, 'media_type', '') == 'episode'
			# Senza tmdb_id non si puo' nominare nessun contenitore e la guardia si astiene: meglio
			# una ricostruzione in piu' che una condizione che non sa cosa sta aspettando.
			if is_episode and not tmdb_id: return False
			deadline = _now() + self.OPEN_FOLDER_WAIT_SECONDS
			while _now() < deadline:
				# Si scorre il REGISTRO delle costruzioni, non i due timbri a casella singola: dentro
				# la finestra Video ci finiscono entrambe -- stagioni e pannello -- e la seconda
				# cancellava la prima. Vedi kodi_utils.BUILD_LOG_PROP.
				rows = ku.build_log_rows(write_ts)
				if is_episode:
					# Confronto ESATTO sui parametri, non per sottostringa: vedi build_mark_param.
					if any(ku.build_mark_param(w, 'mode') == 'build_episode_list'
							and ku.build_mark_param(w, 'tmdb_id') == tmdb_id for w in rows):
						ku.logger('Fen Light', "DIAG refresh: NON ordinato, il pannello episodi della serie %s si e' gia' ricostruito con il dato nuovo" % tmdb_id)
						return True
				else:
					# Per un film la cartella aperta E' quella che mostra il badge. L'identita' si
					# verifica contro Container.FolderPath: il registro porta la query della
					# costruzione, che deve essere la stessa cartella che Container.Refresh
					# ricaricherebbe. La lettura sta DENTRO il ciclo perche' alla chiusura del
					# player la finestra e' ancora in transizione e l'infolabel puo' essere vuota.
					folder = ku.folder_path() or ''
					hit = next((w for w in rows if len(w) > 1 and w in folder), None)
					if hit:
						ku.logger('Fen Light', "DIAG refresh: NON ordinato, Kodi ha gia' ricostruito la cartella aperta (%s) con il dato nuovo" % hit)
						return True
				ku.sleep(200)
			ku.logger('Fen Light', 'DIAG refresh: %s non ricostruito entro %ss dalla scrittura, il refresh lo ordiniamo noi'
						% ('pannello episodi della serie %s' % tmdb_id if is_episode else 'cartella aperta', self.OPEN_FOLDER_WAIT_SECONDS))
		except: pass
		return False

	# Quanto si concede a Kodi per ricostruire da solo la cartella aperta, contato DALLA SCRITTURA.
	# Sulla stick il 02/09 la sua ricostruzione e' arrivata a +2,1 s dalla scrittura (build finita
	# alle 04:14:44,71, scrittura alle 04:14:42,60). Sei secondi coprono quel caso con margine quasi
	# triplo. Se non arriva si ordina noi: l'attesa non costa nulla di visibile, perche' in quei
	# secondi a schermo c'e' comunque la ricostruzione di Kodi in corso.
	OPEN_FOLDER_WAIT_SECONDS = 6

	# Le finestre del player: finche' si e' qui, la finestra a cui si tornera' non si sa ancora.
	PLAYER_WINDOWS = (12005, 12006)
	# Quanto si concede alla transizione di uscita dal player. Sulla stick il 02/09 alle 18:10 e'
	# durata 1,1 s (scrittura finita alle 37,03, finestra 10025 alle 38,16): tre secondi la coprono
	# con margine, e l'attesa non costa nulla di visibile perche' in quei millisecondi lo schermo e'
	# gia' in transizione.
	WINDOW_SETTLE_SECONDS = 3

	def _wait_window_settled(self):
		"""Aspetta che la finestra del player abbia lasciato il posto a quella di destinazione.

		QUESTA E' LA CORREZIONE DI UN DIFETTO CHE HO INTRODOTTO IO (lotto 127). La guardia decideva
		leggendo getCurrentWindowId() nell'istante subito dopo la scrittura, e la cosa ha funzionato
		finche' la scrittura e' durata centinaia di millisecondi: il tempo bastava a Kodi per chiudere
		VideoFullScreen e aprire la finestra vera. Portata la scrittura a 42 ms (lotti 125 e 126), quel
		tempo non c'e' piu'. Log della stick del 02/09:

		    18:10:37,033  scrittura finita (42 ms)     <- la finestra e' ancora 12005
		    18:10:38,091  Window Init (MyVideoNav)
		    18:10:38,158  finestra 12005 -> 10025

		La guardia usciva subito su `!= 10025`, e il risultato si vede due righe piu' sotto nel log:

		    18:10:38,191  GetDirectory (build_season_list)   <- Kodi, per conto suo
		    18:10:38,306  GetDirectory (build_season_list)   <- il nostro Container.Refresh
		    18:10:40,092  seasons ... 2 elementi
		    18:10:40,100  seasons ... 2 elementi             <- la stessa cartella, due volte

		Cioe' esattamente la doppia ricostruzione che la guardia esiste per impedire, tornata perche'
		una correzione di prestazioni ha tolto il ritardo su cui la guardia si appoggiava senza dirlo.

		Il difetto non riguarda solo la finestra Video: anche il ramo dei widget di kodi_refresh_ids
		legge getCurrentWindowId() e interroga i contenitori a schermo. Lanciato mentre si e' ancora
		in 12005 non identifica niente e puo' ricadere sul refresh GLOBALE -- il caso peggiore fra
		tutti. Per questo l'attesa sta nel chiamante, prima di qualunque decisione, e non dentro la
		sola guardia.
		"""
		try:
			from time import time as _now
			deadline = _now() + self.WINDOW_SETTLE_SECONDS
			while _now() < deadline and ku.getCurrentWindowId() in self.PLAYER_WINDOWS:
				ku.sleep(100)
		except: pass

	def _order_refresh_after_write(self):
		"""Il ridisegno mirato dopo che lo stato locale e' gia' scritto.

		Qui c'era una guardia -- kodi_rebuilt_by_itself() -- che saltava questo refresh se Kodi aveva
		gia' ricostruito qualcosa per conto suo. E' stata tolta e poi RIMESSA in forma ristretta
		(_open_folder_rebuilt_after_write), perche' toglierla del tutto e' costato 2,2 s di schermata
		vuota sulla stick: nella finestra Video la ricarica "mirata" e' un Container.Refresh sulla
		cartella che Kodi sta gia' rileggendo, quindi le due si sommano invece di escludersi.
		Restano validi i due motivi per cui la versione ORIGINALE era sbagliata, e la nuova li corregge
		entrambi -- guarda solo la finestra Video, e confronta con l'istante della scrittura:

		1. CHIEDEVA LA COSA SBAGLIATA. La domanda era "e' stato ricostruito qualcosa, da qualche parte,
		   dopo la CHIUSURA del video?". Sul Mac del 01/09 la risposta e' arrivata dai widget della
		   Home ricostruiti alle 21:52:49 mentre l'utente guardava il pannello episodi dentro la serie:
		   contenitori diversi, e il pannello e' rimasto vecchio. E anche il contenitore giusto non
		   avrebbe voluto dire niente, perche' la ricostruzione che la guardia vedeva era ANTERIORE
		   alla scrittura -- confrontava con l'istante di chiusura, non con quello del dato.
		2. ERA TROPPO LARGA. Valeva ovunque, mentre il danno che evita esiste solo nella finestra
		   Video. Fuori di li' la ricarica mirata non ricostruisce nessuna cartella aperta: cambia i
		   token dei contenitori interessati e scarta gli altri -- il comportamento che i test del
		   lotto 119 hanno confermato buono, e che una guardia larga avrebbe soppresso a sproposito.

		kodi_rebuilt_by_itself resta in flush_pending_refresh, dove il ripiego puo' ancora essere un
		refresh globale e la ragione originale vale tuttora.
		"""
		try:
			# La richiesta rimandata si azzera subito: ne' flush_pending_refresh ne' la rete di
			# sicurezza di WidgetRefresher (che ordinerebbe un GLOBALE) devono partire sopra questo.
			ku.clear_property(ku.PENDING_REFRESH_PROP)
			# Prima di qualunque decisione: la finestra deve avere smesso di essere quella del player.
			self._wait_window_settled()
			if self._open_folder_rebuilt_after_write():
				# Kodi ha rifatto la CARTELLA APERTA, non il resto (lotto 122). Saltare l'intera
				# ricarica lasciava indietro 'continua a guardare' e ogni altro widget in altre
				# finestre: nella finestra Video kodi_refresh_ids fa due cose -- Container.Refresh
				# sulla lista aperta E l'armamento del rinvio per le altre finestre -- e la guardia
				# deve togliere solo la prima. Qui si arma il rinvio a mano: WidgetRefresher lo
				# consuma appena si torna su una schermata con widget.
				try:
					_id = str(getattr(self, 'tmdb_id', '') or '')
					if _id:
						ku.set_property(ku.PENDING_IDS_PROP, _id)
						ku.set_property(ku.PENDING_ACTIONS_PROP, ku.CONTINUE_WATCHING_ACTION)
						ku.set_property(ku.PENDING_REFRESH_PROP, 'kodi_refresh_ids')
				except: pass
				return
			# L'azione accompagna sempre l'id (lotto 114): finito un episodio, 'continua a guardare'
			# cambia composizione -- entra se e' rimasto a meta', esce se e' arrivato in fondo.
			tmdb_id = str(getattr(self, 'tmdb_id', '') or '')
			if tmdb_id: return ku.kodi_refresh_ids([tmdb_id], (ku.CONTINUE_WATCHING_ACTION,))
			ku.run_plugin({'mode': 'refresh_widgets'})
		except: pass

	def run_next_ep(self):
		from modules.episode_tools import EpisodeTools
		if not self.media_marked: self.media_watched_marker(force_watched=True)
		EpisodeTools(self.meta, self.nextep_settings).auto_nextep()

	def run_random_continual(self):
		from modules.episode_tools import EpisodeTools
		if not self.media_marked: self.media_watched_marker(force_watched=True)
		EpisodeTools(self.meta).play_random_continual(False)

	def set_resume_point(self, listitem):
		if self.playback_percent > 0.0: listitem.setProperty('StartPercent', str(self.playback_percent))

	def info_next_ep(self):
		self.nextep_info_gathered = True
		try:
			play_type = 'autoplay_nextep' if self.autoplay_nextep else 'autoscrape_nextep'
			nextep_settings = auto_nextep_settings(play_type)
			final_chapter = self.final_chapter() if nextep_settings['use_chapters'] else None
			percentage = 100 - final_chapter if final_chapter else nextep_settings['window_percentage']
			window_time = round((percentage/100) * self.total_time)
			use_window = nextep_settings['alert_method'] == 0
			default_action = nextep_settings['default_action']
			self.start_prep = nextep_settings['scraper_time'] + window_time
			self.nextep_settings = {'use_window': use_window, 'window_time': window_time, 'default_action': default_action, 'play_type': play_type}
		except: pass

	def final_chapter(self):
		try:
			final_chapter = float(get_infolabel('Player.Chapters').split(',')[-1])
			if final_chapter >= 90: return final_chapter
		except: pass
		return None

	def kill_dialog(self):
		try: self.sources_object._kill_progress_dialog()
		except: close_all_dialog()

	def set_constants(self, url, obj):
		self.url = url
		self.sources_object = obj
		self.is_generic = self.sources_object == 'video'
		if not self.is_generic:
			self.meta = self.sources_object.meta
			self.meta_get, self.kodi_monitor, self.playback_percent = self.meta.get, xbmc_monitor(), self.sources_object.playback_percent or 0.0
			self.playing_filename = self.sources_object.playing_filename
			self.media_marked, self.nextep_info_gathered = False, False
			self.current_point = 0.0
			self.scrobble_started = False
			self.playback_successful, self.cancel_all_playback = None, False
			# Prudente per difetto: se monitor() non arriva a calcolarla, non si scrobbla.
			# La bandiera dice se questo episodio ha una coppia valida su Trakt (lotto 145).
			# NON si puo' leggere self.media_type qui: set_constants gira per PRIMA in play_video,
			# mentre media_type nasce in make_listing, dopo. La prima stesura lo faceva, e siccome
			# play_video sta dentro il try di run(), l'AttributeError avrebbe fatto fallire OGNI
			# riproduzione con 'run_error'. Entrambi i rami di monitor() la assegnano prima dell'uso:
			# questo e' solo il valore di partenza, e il verso giusto e' il piu' prudente.
			self._trakt_mappabile = False
			self.playing_item = self.sources_object.playing_item
			self._av_started = False


	def set_playback_properties(self):
		try:
			trakt_ids = {'tmdb': self.tmdb_id, 'imdb': self.imdb_id, 'slug': make_trakt_slug(self.title)}
			if self.media_type == 'episode': trakt_ids['tvdb'] = self.tvdb_id
			set_property('script.trakt.ids', json.dumps(trakt_ids))
			if self.playing_filename: set_property('subs.player_filename', self.playing_filename)
		except: pass

	def clear_playback_properties(self):
		# La bandiera del lotto 111 si abbassa QUI oltre che su Player.OnStop, e il motivo e' un buco
		# vero: play_video la alza PRIMA di self.play(), quindi se la riproduzione non parte mai --
		# link morto, sorgenti esaurite, utente che annulla -- nessun player e' mai esistito e OnStop
		# non arriva. La bandiera resterebbe alzata per sempre e ogni riga PERF successiva direbbe
		# 'riproduzione in corso' con lo schermo sulla home: una diagnostica che mente.
		# Questo metodo e' chiamato all'inizio di run(), a fine riproduzione e in run_error: copre
		# l'ingresso, l'uscita pulita e l'errore.
		clear_property(PLAYBACK_ACTIVE_PROP)
		clear_property('fenlight.window_stack')
		clear_property('script.trakt.ids')
		clear_property('subs.player_filename')

	def clear_playing_item(self):
		if self.playing_item['cache_provider'] == 'Offcloud':
			if self.playing_item.get('direct_debrid_link', False): return
			if store_resolved_to_cloud('Offcloud', 'package' in self.playing_item): return
			from apis.offcloud_api import OffcloudAPI
			OffcloudAPI().clear_played_torrent(self.playing_item)

	def run_error(self):
		try: self.sources_object.playback_successful = False
		except: pass
		self.clear_playback_properties()
		notification('Playback Failed', 3500)
		return False
