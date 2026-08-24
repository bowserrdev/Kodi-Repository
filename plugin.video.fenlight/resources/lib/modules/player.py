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
		try: set_property('fenlight.playback.active', 'true')
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
		self.play(self.url, self.make_listing())
		if not self.is_generic:
			self.check_playback_start()
			if self.playback_successful: self.monitor()
			else:
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
				_ep_map = self.meta.get('tvdb_to_tmdb_ep')
				if _ep_map is None:
					from apis.skyhook_api import get_tvdb_to_tmdb_map
					_ep_map = get_tvdb_to_tmdb_map(self.meta.get('tvdb_id'), self.meta.get('tmdb_season_data_original', []))
				self._trakt_season, self._trakt_episode = _ep_map.get((self.season, self.episode), (self.season, self.episode))
			else:
				play_random_continual, self.autoplay_nextep, self.autoscrape_nextep = False, False, False
				self._trakt_season, self._trakt_episode = self.season, self.episode
			while total_check_time <= 30 and not get_visibility(video_fullscreen_check):
				sleep(200)
				total_check_time += 0.10
			hide_busy_dialog()
			sleep(1000)
			while self.isPlayingVideo():
				try:
					try: self.total_time, self.curr_time = self.getTotalTime(), self.getTime()
					except: sleep(250); continue
					if not ensure_dialog_dead:
						ensure_dialog_dead = True
						self.playback_close_dialogs()
						if st.trakt_user_active() and trakt_official_status(self.media_type):
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
		try: clear_property('fenlight.playback.active')
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
		# video era in corso. L'attesa serve a lasciar passare prima il refresh del segnalibro, che parte
		# da run_media_progress dopo 2s e azzera la stessa proprieta': cosi' si ricostruisce una volta sola.
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
			if tmdb_id: return ku.kodi_refresh_ids([tmdb_id])
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
		try:
			function(params)
			if do_refresh:
				for _b1, _b2 in ((True, True), (True, False), (False, True), (False, False)):
					ku.clear_property('1_%s_%s_%s_watched' % (self.media_type, _b1, _b2))
				# Da qui il refresh post-riproduzione ha UN padrone solo: questo. La richiesta rimandata
				# si azzera subito, cosi' ne' flush_pending_refresh ne' la rete di sicurezza di
				# WidgetRefresher (che ordinerebbe un GLOBALE) possono partire mentre stiamo decidendo.
				ku.clear_property(ku.PENDING_REFRESH_PROP)
				if self.kodi_rebuilt_by_itself(): return
				# QUESTO e' il refresh che in pratica ricostruisce la home a fine film -- non
				# flush_pending_refresh, che al proprio risveglio trova gia' azzerata la proprieta' e non fa
				# nulla. Qui sappiamo esattamente cosa e' cambiato: il titolo appena visto. Se il sondaggio
				# dei contenitori non identifica nulla, kodi_refresh_ids ricade da sola sul globale.
				# Ci si arriva solo se Kodi NON ha ricostruito da sola: vedi kodi_rebuilt_by_itself.
				tmdb_id = str(getattr(self, 'tmdb_id', '') or '')
				if tmdb_id: return ku.kodi_refresh_ids([tmdb_id])
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
