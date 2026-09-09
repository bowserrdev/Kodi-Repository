# -*- coding: utf-8 -*-
import json
from time import perf_counter
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
perf_logger = ku.logger
# Istante in cui lo stato locale (segnalibro o visto) e' stato scritto davvero. Non e' l'istante di
# chiusura del player: fra i due passa il tempo del sondaggio piu' quello della scrittura, e in mezzo
# Kodi ricostruisce. Solo una ricostruzione posteriore a QUESTO timbro ha potuto vedere il dato nuovo.
WRITE_DONE_PROP = 'fenlight.perf.write_done'
total_time_errors = ('0.0', '', 0.0, None)
set_resume, set_watched = 5, 90
# LOTTO 202 -- CAMBIO SORGENTE AUTOMATICO. Soglie in secondi: il ciclo di monitor() dorme 1000 ms
# per giro, quindi un giro vale un secondo. Due guasti diversi meritano due soglie diverse.
#
# MAI PARTITO. L'08/09 un episodio HEVC 10 bit 1920x1456 ha fatto morire il decoder della stick,
# che dichiara max="1920x1088": 44.055 righe 'dequeueInputBuffer failed' in 67 secondi, schermo
# nero, e alla fine Kodi si e' ucciso da solo su un bug di formattazione nel PROPRIO percorso
# d'errore (fmt::format_error, SIGABRT). Kodi non ha mai emesso Player.OnAVStart e la posizione e'
# rimasta a zero, ma isPlayingVideo() diceva di si': dal punto di vista di Fen Light la
# riproduzione era in corso, e nessuna delle nostre misure di banda poteva accorgersene -- il file
# era da 2,1 Mbit/s con la cache piena. Quindici secondi fermi a zero non sono mai una
# riproduzione lenta: sono una sorgente che questa macchina non sa riprodurre.
#
# BLOCCATO. Soglia molto piu' alta perche' qui l'ambiguita' c'e' davvero: un buco di banda blocca
# la posizione allo stesso modo, ma si riprende. Il congelamento di Dead Man del 07/09 e' durato
# 77 secondi e non si e' ripreso mai.
FERMO_MAI_PARTITO, FERMO_BLOCCATO = 15, 60
video_fullscreen_check = 'Window.IsActive(fullscreenvideo)'

def nota_sorgente(item, esito, motivo, dettaglio='', posizione=None):
	"""UNA riga per ogni sorgente presa in considerazione, accettata o scartata (lotto 205).

	Prima ogni via d'uscita raccontava una storia diversa, e due su quattro non ne raccontavano
	nessuna: una sorgente che non si risolveva usciva con un `continue` muto, e una che si apriva
	senza mai partire lasciava solo il crash. Nel log dell'08/09 l'utente ne aveva viste passare tre
	e il log ne mostrava una. Con una riga sola e sempre lo stesso formato, `grep SORGENTE` racconta
	l'intero giro -- ed e' anche il motivo per cui la notifica a schermo non serve piu': quello che
	diceva sta qui, per tutti i casi invece che per uno.

	Il provider e' quello VERO -- l'indicizzatore -- non 'external', che e' solo la famiglia: senza,
	una taglia sbagliata non si puo' attribuire a nessuno.
	"""
	try:
		_it = item or {}
		perf_logger('FenLight SORGENTE', '%s %s [%s]%s | %s | %s'
					% (posizione or '--', esito, motivo, ' ' + dettaglio if dettaglio else '',
					   _it.get('provider') or _it.get('scrape_provider') or 'n.d.',
					   _it.get('name') or _it.get('display_name') or 'senza nome'))
	except: pass


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
			# Una sorgente che non si e' riprodotta non lascia traccia (lotto 202). self.stop() dentro
			# _cambia_sorgente fa scattare questa richiamata, e senza la guardia scriverebbe un punto di
			# ripresa a zero su un film che l'utente non ha visto -- peggio del guasto stesso, perche'
			# resterebbe nel 'continua a guardare'. La guardia sta QUI e non solo in monitor() perche'
			# questa e' una richiamata di Kodi: arriva anche per strade che monitor() non controlla.
			if getattr(self, '_esito_guasto', None): return
			self.media_watched_marker()
		except: pass

	def onPlayBackSeek(self, time, seekOffset):
		# Si aggiorna SOLO la posizione: nessuna chiamata a Trakt e nessuna marcatura qui.
		# Trakt riceve uno scrobble start all'avvio e uno stop alla chiusura, niente altro.
		# SONDA (lotto 182): il numero di salti serve a separare il livello di cache PRIMA del primo
		# salto da quello DOPO l'ultimo. E' la sola cosa che questa richiamata aggiunge.
		# La finestra scorrevole della portata si azzera qui: un salto resetta la cache di Kodi, e una
		# finestra a cavallo della discontinuita' misurerebbe un dislivello, non una velocita'.
		try: self._cache_serie = []
		except: pass
		try: self._salti = getattr(self, '_salti', 0) + 1
		except: pass
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
		# QUI, e prima di play(): dopo e' troppo tardi per sempre. Se il decoder muore sul file,
		# chiuderlo fa abortire Kodi dentro Dispose (lotto 203), quindi non c'e' nessun rimedio a
		# valle -- l'unica difesa e' non aprirlo. Restituendo qui senza aver mai chiamato play(),
		# play_file trova playback_successful False e passa da solo alla sorgente successiva: la
		# rotazione non va scritta, esiste gia'.
		if not self.is_generic and not self._esamina_sorgente(): return
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
				# PRIMA di stop(), non dopo, e non e' pignoleria: se il file e' di quelli che
				# uccidono il decoder, stop() fa abortire il processo e nulla di cio' che sta sotto
				# viene mai eseguito. E' il motivo per cui l'08/09 non e' rimasta traccia di niente.
				_m, _d = getattr(self, '_motivo_avvio', ('avvio', ''))
				nota_sorgente(getattr(self, 'playing_item', None), 'SCARTATA', _m, _d, self._posizione())
				self._boccia_sorgente('mai_partito')
				self.stop()
			try: del self.kodi_monitor
			except: pass

	def check_playback_start(self):
		resolve_percent = 0
		# Ogni uscita da questo ciclo lascia detto perche' (lotto 205): quattro strade diverse
		# finivano tutte nello stesso `playback_successful = False`, e da fuori erano indistinguibili.
		self._motivo_avvio = ('avvio', '')
		while self.playback_successful is None:
			hide_busy_dialog()
			if not self.sources_object.progress_dialog: self.playback_successful = True
			elif self.sources_object.progress_dialog.skip_resolved():
				self._motivo_avvio = ('saltata', 'saltata dall\'utente')
				self.playback_successful = False
			elif self.sources_object.progress_dialog.iscanceled() or self.kodi_monitor.abortRequested():
				self._motivo_avvio = ('annullata', 'annullata dall\'utente o da Kodi')
				self.cancel_all_playback, self.playback_successful = True, False
			elif resolve_percent >= 100:
				# Scaduto il tempo. Se Kodi dice ancora di stare riproducendo, non e' un link morto
				# ne' un annullamento dell'utente: e' un file che si e' APERTO e non e' mai partito.
				# E' l'unico dei quattro esiti che merita la lista nera, quindi si distingue.
				try: self._scaduto_in_avvio = bool(self.isPlayingVideo())
				except: self._scaduto_in_avvio = False
				self._motivo_avvio = (('aperta ma mai partita' if self._scaduto_in_avvio else 'nessuna riproduzione'),
									  'scaduto il tempo di avvio (72 s)')
				self.playback_successful = False
			elif get_visibility('Window.IsTopMost(okdialog)'):
				execute_builtin('SendClick(okdialog, 11)')
				self._motivo_avvio = ('errore di Kodi', 'Kodi ha aperto una finestra di errore sul file')
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

	# --- SONDA CACHE (lotto 182) ----------------------------------------------------------------
	# Serve a inchiodare con i numeri di Kodi cio' che il log del 07/09 lascia solo dedurre: che dopo
	# un salto il buffer non torna mai pieno. Il criterio di uscita dallo stallo e' cached/currate > 8
	# (VideoPlayer.cpp:1879), cioe' circa 8 secondi di contenuto; il buffer in avanti ne contiene ~20.
	# Se la deduzione e' giusta, Player.CacheLevel tocca 100 prima del primo salto e poi resta basso
	# per tutto il resto del film. E' una sonda: si toglie appena il numero e' in mano.
	def _campiona_cache(self):
		try:
			_grezzo = get_infolabel('Player.CacheLevel')
			if not _grezzo: return
			_liv = int(float(_grezzo))
		except: return
		_dopo = getattr(self, '_salti', 0) > 0
		self._cache_n = getattr(self, '_cache_n', 0) + 1
		if _dopo:
			self._cache_max_dopo = max(getattr(self, '_cache_max_dopo', 0), _liv)
			self._cache_somma_dopo = getattr(self, '_cache_somma_dopo', 0) + _liv
			self._cache_n_dopo = getattr(self, '_cache_n_dopo', 0) + 1
		else:
			self._cache_max_prima = max(getattr(self, '_cache_max_prima', 0), _liv)
			self._cache_somma_prima = getattr(self, '_cache_somma_prima', 0) + _liv
			self._cache_n_prima = getattr(self, '_cache_n_prima', 0) + 1
		# PORTATA (lotto 197, corretto al 198). Quando la cache sale, il collegamento consegna piu' di
		# quanto il film consuma, e la pendenza dice di quanto. Tempo vero e non "un secondo": il ciclo
		# fa sleep(1000) ma anche altro, e slitta.
		#
		# DUE FINESTRE, e la seconda e' quella che conta. Con la sola finestra da 5 campioni il lotto
		# 197 leggeva il PICCO, e il picco non e' cio' che regge un film: la riproduzione 7 dell'08/09
		# (13,72 Mbit/s) dava picco 21,4 Mbit/s -- verdetto "larghissimo" -- mentre la cache non
		# passava mai il 21% e la media era 1%. Su 20 campioni la stessa riproduzione da' 15,8 Mbit/s,
		# cioe' un margine di 1,15x, che e' il numero vero. Stesso errore delle sonde dei lotti 191 e
		# 193, in un posto nuovo: misurare un massimo dove serve una portata sostenuta.
		_serie = getattr(self, '_cache_serie', None)
		if _serie is None: _serie = self._cache_serie = []
		_serie.append((perf_counter(), _liv))
		if len(_serie) > 20: _serie.pop(0)
		# Prima e dopo il primo salto si tengono separate: il dato dell'08/09 dice che dopo un salto
		# la cache non si riprende, ma senza la portata separata non si sa SE cala la consegna del cdn
		# (offset freddo) o se semplicemente manca il margine per ricostruire il buffer. E' la
		# domanda dell'obiettivo 1, e finora non era misurata.
		_suff = '_dopo' if _dopo else '_prima'
		for _w, _attr in ((5, '_cache_pend_picco' + _suff), (20, '_cache_pend_sost' + _suff)):
			if len(_serie) < _w: continue
			_a, _b = _serie[-_w], _serie[-1]
			_dt, _dl = _b[0] - _a[0], _b[1] - _a[1]
			if _dt > 0 and _dl > 0:
				_pend = _dl / _dt
				if _pend > getattr(self, _attr, 0): setattr(self, _attr, _pend)
		# Il tratto consecutivo piu' lungo a zero. E' l'unico esito che si SENTE: la media della cache
		# misura il margine (lotto 197), ma il film si ferma solo quando il buffer resta vuoto.
		if _liv <= 0:
			_run = getattr(self, '_cache_run_zero', 0) + 1
			self._cache_run_zero = _run
			if _run > getattr(self, '_cache_zero_max', 0): self._cache_zero_max = _run
		else: self._cache_run_zero = 0
		_tratto = getattr(self, '_cache_tratto', None)
		if _tratto is None: _tratto = self._cache_tratto = []
		_tratto.append(_liv)
		# Una riga ogni dieci secondi: la forma a dente di sega si legge dalla sequenza, non da una media.
		if len(_tratto) >= 10:
			perf_logger('FenLight PERF CACHE', 'livello %s | salti finora %s'
						% ('-'.join(str(_v) for _v in _tratto), getattr(self, '_salti', 0)))
			self._cache_tratto = []

	def _esamina_sorgente(self):
		"""True se si puo' provare a riprodurre. False solo se lo sappiamo POSITIVAMENTE (lotto 203).

		Tre controlli, in ordine di costo. Il primo e' gratis e legge la lista nera. Il secondo e'
		una richiesta sola al cdn -- `Range: bytes=0-131071` -- che porta a casa cinque cose:
		codec, larghezza, altezza, durata e, dal Content-Range, la dimensione vera del file che
		finora costava un secondo giro dentro monitor(). Il terzo non costa niente in piu': con
		byte veri e secondi veri gia' in mano, il bitrate e' una divisione.

		OGNI DUBBIO VALE COME SI'. Contenitore che non conosciamo, intestazione oltre i byte letti,
		rete lenta, dispositivo che non pubblica i suoi limiti (una Fire Stick, un Mac): in tutti
		questi casi non sappiamo, e non sapere vuol dire riprodurre. Il meccanismo puo' solo
		togliere cio' che ha misurato, e se non misura niente e' come se non ci fosse.
		"""
		try:
			from caches import playback_stats
			from modules import decoder_limits
			_item = getattr(self, 'playing_item', None) or {}
			_ch = playback_stats.chiave(_item)
			_motivo = playback_stats.bocciata(_ch)
			if _motivo:
				return self._rifiuta_sorgente('lista nera', 'gia\' fallita in passato (%s)' % _motivo, 'lista_nera')
			_t = perf_counter()
			from modules import stream_header
			_h = stream_header.leggi(self.url)
			_ms = int((perf_counter() - _t) * 1000)
			# La dimensione e il nodo si tengono comunque: valgono per la raccolta anche quando il
			# verdetto e' "vai".
			if _h.get('dimensione'): self._dimensione_vera = _h['dimensione']
			if _h.get('host'): self._cdn_host = _h['host']
			if _h.get('durata'): self._durata_vera = _h['durata']
			self._sonda = (_h.get('codec'), _h.get('larghezza'), _h.get('altezza'))
			_ok, _perche = decoder_limits.riproducibile(_h.get('codec'), _h.get('larghezza'), _h.get('altezza'))
			_forma = '%s %sx%s letti in %s ms' % (_h.get('codec') or 'codec ignoto',
												  _h.get('larghezza'), _h.get('altezza'), _ms)
			if not _ok:
				return self._rifiuta_sorgente('risoluzione', '%s, %s' % (_forma, _perche), 'scartata_dimensione')
			_ok, _banda = self._banda_sufficiente(_h)
			if not _ok:
				return self._rifiuta_sorgente('banda', '%s, %s' % (_forma, _banda), 'scartata_banda')
			nota_sorgente(self.playing_item, 'ACCETTATA', 'riproducibile',
						  '%s, %s, %s' % (_forma, _perche, _banda), self._posizione())
			return True
		except:
			# Qualunque cosa vada storta qui dentro non deve poter impedire una riproduzione.
			return True

	def _banda_sufficiente(self, _h):
		"""(esito, spiegazione). Il cancello ESATTO sul bitrate -- lotto 209.

		IL PROBLEMA CHE CHIUDE. Il filtro di `results.line_speed` in sources.py deve trasformare un
		limite di velocita' in un limite di dimensione, e il ponte fra i due e' il tempo:

		    byte ammessi = Mbit/s x secondi / 8

		Al momento dell'elenco quei secondi non esistono. La dimensione si', esatta, dal lotto 207 --
		TorBox la dichiara file per file -- ma la durata la sa solo il file, e aprire quarantasette
		file per leggerne l'intestazione vorrebbe dire quarantasette risoluzioni sul debrid prima di
		mostrare la lista. Quindi li' la durata resta quella di TMDb, che sui film e sugli episodi
		normali e' vicina al vero e sulle serie a segmenti no. Un filtro inesatto.

		Qui invece i due numeri ci sono ENTRAMBI, veri, e nella stessa risposta: la dimensione dal
		Content-Range, i secondi dall'Info del matroska o dal mvhd dell'mp4. Il bitrate diventa una
		divisione, e la sorgente che sta per aprirsi non puo' piu' sfuggire al limite per un errore
		di stima. Il filtro dell'elenco resta un setaccio; il giudice e' questo.

		SOLO SE IL FILTRO E' ACCESO. Con filter_size_method 0 l'utente ha scelto di non filtrare
		sulla banda, con 2 filtra su una dimensione fissa che non c'entra col tempo: in nessuno dei
		due casi si puo' introdurre qui uno scarto che dall'elenco non sarebbe mai arrivato.

		Mbit/s DECIMALI, come li vendono. 8 bit per byte e 10**6 per Mbit: una linea da 25 Mbit/s
		consegna 25.000.000 bit al secondo, non 26.214.400. Qui non c'entrano i GiB del lotto 207 --
		quelli servivano a confrontare due DIMENSIONI, questo confronta due VELOCITA'.

		OGNI DUBBIO VALE COME SI'. Durata illeggibile, contenitore non parsato, impostazione assente:
		si torna True. Come tutto il resto di questo percorso, puo' solo togliere cio' che ha
		positivamente misurato.
		"""
		try:
			if int(get_setting('fenlight.results.filter_size_method', '0')) != 1:
				return True, 'cancello banda non attivo'
			_byte, _sec = _h.get('dimensione'), _h.get('durata')
			if not _byte or not _sec: return True, 'bitrate non misurabile'
			_linea = float(get_setting('results.line_speed', '25') or 25)
			if _linea <= 0: return True, 'linea non impostata'
			_mbit = (_byte * 8.0) / _sec / 1000000.0
			self._bitrate_vero = _mbit
			_come = '%.1f Mbit/s veri (%.2f GB in %s)' % (_mbit, _byte / 1000000000.0, self._mmss(_sec))
			if _mbit <= _linea: return True, '%s, entro i %g impostati' % (_come, _linea)
			return False, '%s, oltre i %g impostati' % (_come, _linea)
		except: return True, 'cancello banda fallito'

	@staticmethod
	def _mmss(secondi):
		try: return '%d:%02d' % (int(secondi) // 60, int(secondi) % 60)
		except: return '?'

	def _posizione(self):
		try: return getattr(self.sources_object, '_posizione_sorgente', None)
		except: return None

	def _rifiuta_sorgente(self, motivo, dettaglio, esito):
		"""Registra lo scarto e restituisce False, cosi' play_file passa alla sorgente dopo."""
		try:
			from caches import playback_stats
			from time import time as _adesso
			_item = getattr(self, 'playing_item', None) or {}
			_c, _w, _h = getattr(self, '_sonda', (None, None, None))
			# Una riga anche per cio' che NON si e' riprodotto: senza, uno scarto sarebbe
			# indistinguibile da una sorgente mai comparsa, e non si potrebbe piu' verificare se il
			# meccanismo sta togliendo roba buona.
			playback_stats.registra(quando=int(_adesso()), dimensione=getattr(self, '_dimensione_vera', None),
									cdn=getattr(self, '_cdn_host', None), larghezza=_w, altezza=_h, codec=_c,
									# Lotto 209: su una riga di scarto questi due sono MISURATI, non stimati.
									# Senza, non si potrebbe verificare a posteriori se il cancello ha tolto
									# roba buona -- che e' l'unica domanda che conta su un filtro.
									durata=getattr(self, '_durata_vera', None),
									bitrate=getattr(self, '_bitrate_vero', None),
									esito=esito, nome=_item.get('name') or None,
									provider=_item.get('provider') or _item.get('scrape_provider') or None,
									pacchetto=_item.get('package') or None,
									dimensione_dichiarata=_item.get('size'))
		except: pass
		# Niente notifica a schermo: la riga di log copre tutti i casi di scarto, non solo questo, e
		# l'utente non deve essere avvisato di un lavoro che il meccanismo fa da solo.
		nota_sorgente(getattr(self, 'playing_item', None), 'SCARTATA', motivo, dettaglio, self._posizione())
		try:
			self.sources_object.playback_successful = False
			self.sources_object.cancel_all_playback = False
		except: pass
		self.clear_playback_properties()
		return False

	def _boccia_sorgente(self, motivo):
		"""Mette la sorgente in lista nera. Solo per il caso 'si e' aperta e non e' mai partita'."""
		try:
			if not getattr(self, '_scaduto_in_avvio', False): return
			from caches import playback_stats
			_item = getattr(self, 'playing_item', None) or {}
			_ch = playback_stats.chiave(_item)
			if playback_stats.boccia(_ch, _item.get('name'),
									 _item.get('provider') or _item.get('scrape_provider'), motivo):
				perf_logger('FenLight PERF CACHE', 'sorgente bocciata (%s) | %s | non verra\' piu\' proposta '
							'finche\' non si svuota la lista' % (motivo, _ch))
		except: pass

	def _misura_dimensione(self):
		"""Dimensione VERA del file dal cdn, in un thread di sfondo a riproduzione gia' avviata.

		Kodi scrive il bitrate del flusso (`setting maxRate`) solo nel log C++: Python non lo vede e
		nessuna API lo espone. L'unico modo di conoscerlo e' dimensione x 8 / durata -- e la
		dimensione dello scraper e' inaffidabile (lotto 192: 0,03 GB dichiarati contro 0,74 reali).
		`Content-Range` la da' esatta al costo di UN byte e di un ttfb.

		In sfondo e dopo l'avvio di proposito: il film sta gia' andando, quindi il costo visibile e'
		zero. E' la differenza con la sonda dei lotti 191-195, che la stessa attesa la metteva PRIMA.
		"""
		try:
			import http.client
			from modules.http_client import _split_url
			_url = getattr(self, 'url', None)
			if not _url: return
			# I redirect si seguono a mano: un cdn che rimandasse altrove darebbe, senza questo,
			# silenziosamente nessuna misura per sempre. Tre salti bastano e chiudono il ciclo.
			for _ in range(4):
				scheme, host, port, path = _split_url(_url)
				_cls = http.client.HTTPSConnection if scheme == 'https' else http.client.HTTPConnection
				conn = _cls(host, port, timeout=10)
				try:
					conn.request('GET', path, headers={'Range': 'bytes=0-0', 'Accept-Encoding': 'identity',
													   'User-Agent': 'Mozilla/5.0', 'Connection': 'close'})
					resp = conn.getresponse()
					if resp.status in (301, 302, 303, 307, 308):
						_loc = resp.getheader('Location')
						if not _loc: return
						_url = _loc if not _loc.startswith('/') else '%s://%s:%s%s' % (scheme, host, port, _loc)
						continue
					# Il nodo si registra QUELLO FINALE, non quello di partenza: e' il nodo che ha
					# davvero servito il file, ed e' il dato che serve al wizard.
					self._cdn_host = host
					_cr = resp.getheader('Content-Range')
					if _cr and '/' in _cr:
						_tot = _cr.rsplit('/', 1)[1].strip()
						if _tot.isdigit(): self._dimensione_vera = int(_tot)
					return
				finally:
					try: conn.close()
					except: pass
		except: pass

	def _buffer_avanti_mb(self):
		# filecache.memorysize e' in MB, e Kodi ne tiene un quarto per il buffer all'indietro:
		# FileCache.cpp -> back = cacheSize / 4; front = cacheSize - back. Quindi in avanti va il 75%,
		# ed e' su quel 75% che Player.CacheLevel calcola la percentuale (level = (writePos - readPos)
		# / m_maxForward). Letto da Kodi e non messo a mano perche' memorysize e' una delle voci che
		# un wizard dovra' cambiare: se resta scritta qui, la misura si sfalsa senza accorgersene.
		try:
			_r = ku.get_jsonrpc({'jsonrpc': '2.0', 'id': 1, 'method': 'Settings.GetSettingValue',
								 'params': {'setting': 'filecache.memorysize'}})
			_v = (_r or {}).get('value') or 0
			return _v * 0.75 if _v else 0
		except: return 0

	def _riassunto_cache(self):
		try:
			if not getattr(self, '_cache_n', 0): return
			_tratto = getattr(self, '_cache_tratto', None)
			if _tratto:
				perf_logger('FenLight PERF CACHE', 'livello %s | salti finora %s'
							% ('-'.join(str(_v) for _v in _tratto), getattr(self, '_salti', 0)))
			def _media(_s, _n): return round(float(_s) / _n) if _n else 0
			_np, _nd = getattr(self, '_cache_n_prima', 0), getattr(self, '_cache_n_dopo', 0)
			perf_logger('FenLight PERF CACHE',
						'riassunto | salti %s | prima del primo salto: %s campioni, max %s%%, media %s%% '
						'| dopo: %s campioni, max %s%%, media %s%%'
						% (getattr(self, '_salti', 0),
							_np, getattr(self, '_cache_max_prima', 0), _media(getattr(self, '_cache_somma_prima', 0), _np),
							_nd, getattr(self, '_cache_max_dopo', 0), _media(getattr(self, '_cache_somma_dopo', 0), _nd)))
			# La media della cache e' una misura di MARGINE, non di qualita': se il collegamento
			# consegna esattamente quanto il film consuma, la cache resta bassa e la riproduzione e'
			# perfetta lo stesso. Evil Dead, 07/09: media 26%, 17 s a zero, e nessun problema visto.
			# Il numero che serve per tarare results.line_speed e' questo qui sotto.
			_mb = self._buffer_avanti_mb()
			_c = (lambda _p: _p / 100.0 * _mb * 8) if _mb else None
			for _et, _sf in (('prima del salto', '_prima'), ('DOPO il salto ', '_dopo')):
				_pk, _so = getattr(self, '_cache_pend_picco' + _sf, 0), getattr(self, '_cache_pend_sost' + _sf, 0)
				if not (_pk or _so): continue
				if _c:
					perf_logger('FenLight PERF CACHE',
								'portata %s | SOSTENUTA (20 s) %.1f%%/s = %.1f Mbit/s di surplus | picco (5 s) %.1f%%/s = %.1f Mbit/s '
								'| buffer in avanti %.0f MB | portata = surplus + bitrate (riga "setting maxRate"); per tarare usare la SOSTENUTA'
								% (_et, _so, _c(_so), _pk, _c(_pk), _mb))
				else:
					perf_logger('FenLight PERF CACHE', 'portata %s | sostenuta %.1f%%/s | picco %.1f%%/s (filecache.memorysize non leggibile)' % (_et, _so, _pk))
			self._registra_misura(_mb)
		except: pass

	def _registra_misura(self, buffer_mb):
		"""Una riga nel database delle misure. Ingresso del wizard della banda (lotto 201).

		Sta qui e non in un punto piu' alto perche' qui ci sono gia' tutti i numeri, e perche' il
		riassunto gira una volta sola per riproduzione. Non solleva mai: una misura persa non deve
		poter disturbare la chiusura di un film.
		"""
		try:
			from caches import playback_stats
			from time import time as _now
			_dim = getattr(self, '_dimensione_vera', None)
			_dur = getattr(self, 'total_time', 0) or 0
			try: _dur = int(_dur)
			except: _dur = 0
			# NULL, non zero: il wizard deve poter distinguere "non misurato" da "misurato zero".
			_bit = (_dim * 8.0 / _dur / 1000000.0) if (_dim and _dur) else None
			def _porta(_sf):
				_p = getattr(self, '_cache_pend_sost' + _sf, 0)
				if not (_p and buffer_mb and _bit): return None
				return _p / 100.0 * buffer_mb * 8 + _bit
			_np, _nd = getattr(self, '_cache_n_prima', 0), getattr(self, '_cache_n_dopo', 0)
			_media = lambda _s, _n: int(round(float(_s) / _n)) if _n else None
			# Identita' della sorgente, dal risultato che play_file ha scelto. `size` e' in GiB, e
			# NON e' la stessa misura per tutti: per un pacchetto external e' la taglia del pacco
			# divisa per il numero di episodi, cioe' una stima. Per questo si registra accanto a
			# `provider` e `pacchetto`, che sono cio' che permette di leggerla.
			_it = getattr(self, 'playing_item', None) or {}
			try: _dich = float(_it.get('size')) if _it.get('size') is not None else None
			except: _dich = None
			playback_stats.registra(
				quando=int(_now()), cdn=getattr(self, '_cdn_host', None), dimensione=_dim,
				durata=_dur or None, bitrate=_bit, salti=getattr(self, '_salti', 0),
				portata_prima=_porta('_prima'), portata_dopo=_porta('_dopo'),
				cache_media_prima=_media(getattr(self, '_cache_somma_prima', 0), _np),
				cache_max_prima=getattr(self, '_cache_max_prima', None) if _np else None,
				cache_media_dopo=_media(getattr(self, '_cache_somma_dopo', 0), _nd),
				cache_max_dopo=getattr(self, '_cache_max_dopo', None) if _nd else None,
				secondi_a_zero=getattr(self, '_cache_zero_max', 0),
				campioni=getattr(self, '_cache_n', 0),
				larghezza=getattr(self, '_vid_larghezza', None), altezza=getattr(self, '_vid_altezza', None),
				codec=getattr(self, '_vid_codec', None), esito=getattr(self, '_esito_guasto', None),
				nome=_it.get('name') or getattr(self, 'playing_filename', None) or None,
				dimensione_dichiarata=_dich, provider=_it.get('provider') or _it.get('scrape_provider') or None,
				pacchetto=_it.get('package') or None)
			# Lo scarto fra taglia dichiarata e taglia vera va nel log perche' e' il numero che dira'
			# se il tetto di results.line_speed sta decidendo su un dato attendibile o su una stima.
			_sc = None
			if _dich and _dim:
				try: _sc = (_dich * 1073741824 / _dim - 1) * 100
				except: _sc = None
			perf_logger('FenLight PERF CACHE',
						'sorgente | %s | provider %s%s | dichiarata %s GiB contro %s GiB reali%s'
						% (_it.get('name') or getattr(self, 'playing_filename', None) or 'n.d.',
						   _it.get('provider') or _it.get('scrape_provider') or 'n.d.',
						   ' (pacchetto %s)' % _it.get('package') if _it.get('package') else '',
						   '%.2f' % _dich if _dich else 'n.d.',
						   '%.2f' % (_dim / 1073741824.0) if _dim else 'n.d.',
						   ' | scarto %+.1f%%' % _sc if _sc is not None else ''))
			perf_logger('FenLight PERF CACHE',
						'misura registrata | %sx%s %s | bitrate %s | portata prima %s dopo %s | zero piu\' lungo %s s '
						'| esito %s | righe in archivio %s'
						% (getattr(self, '_vid_larghezza', None), getattr(self, '_vid_altezza', None),
						   getattr(self, '_vid_codec', None) or 'n.d.',
						   '%.2f' % _bit if _bit else 'n.d.',
						   '%.1f' % _porta('_prima') if _porta('_prima') else 'n.d.',
						   '%.1f' % _porta('_dopo') if _porta('_dopo') else 'n.d.',
						   getattr(self, '_cache_zero_max', 0),
						   getattr(self, '_esito_guasto', None) or 'normale', playback_stats.quante()))
		except: pass

	def _misura_flusso(self):
		"""Forma del flusso video -- larghezza, altezza, codec -- una volta sola, in sfondo.

		E' la misura che mancava l'08/09. Tutte le colonne raccolte fin qui descrivono la VELOCITA'
		del collegamento, e nessuna avrebbe distinto quel guasto da una riproduzione riuscita: 2,1
		Mbit/s, cache piena, e niente da riprodurre. Il dato che lo spiega e' 1920x1456 contro il
		max="1920x1088" dichiarato dal decoder in /vendor/etc/media_codecs.xml.

		Va letta DURANTE la riproduzione: a player fermo Player.GetProperties non risponde piu'.
		Funziona anche quando il decoder e' morto, perche' il demuxer i flussi li conosce lo stesso.
		"""
		try:
			_att = ku.get_jsonrpc({'jsonrpc': '2.0', 'id': 1, 'method': 'Player.GetActivePlayers'}) or []
			_pid = next((_p.get('playerid') for _p in _att if _p.get('type') == 'video'), None)
			if _pid is None: return
			_r = ku.get_jsonrpc({'jsonrpc': '2.0', 'id': 1, 'method': 'Player.GetProperties',
								 'params': {'playerid': _pid, 'properties': ['currentvideostream']}}) or {}
			_v = _r.get('currentvideostream') or {}
			self._vid_larghezza = _v.get('width') or None
			self._vid_altezza = _v.get('height') or None
			self._vid_codec = _v.get('codec') or None
			perf_logger('FenLight PERF CACHE', 'flusso video | %sx%s | codec %s'
						% (self._vid_larghezza, self._vid_altezza, self._vid_codec))
		except: pass

	def _controlla_avanzamento(self):
		"""Riconosce una sorgente che NON si sta riproducendo, mentre Kodi dice che si'.

		Il criterio e' la posizione, non la cache e non il codec. Un decoder morto, un demuxer
		congelato e un collegamento che non consegna piu' niente hanno tre cause diverse e un solo
		sintomo osservabile da qui: getTime() non avanza. Guardare il sintomo li copre tutti e tre e
		non richiede di indovinare quale sia -- ed e' importante, perche' l'08/09 la causa vera non
		era osservabile da Python in nessun modo.

		Due condizioni da escludere prima di dire 'guasto', e sono le uniche due in cui la posizione
		sta ferma legittimamente: la pausa e un salto (che la fa anche tornare indietro).
		"""
		if getattr(self, '_esito_guasto', None): return
		try: _pos = float(self.curr_time or 0)
		except: return
		try:
			if get_visibility('Player.Paused'):
				self._fermo_da, self._pos_prec = 0, _pos
				return
		except: pass
		_prec = getattr(self, '_pos_prec', None)
		self._pos_prec = _pos
		# In valore assoluto: un salto all'indietro e' movimento quanto uno in avanti. Mezzo secondo
		# di tolleranza perche' il ciclo dorme 1000 ms ma slitta, e getTime() e' un float.
		if _prec is None or abs(_pos - _prec) > 0.5:
			self._fermo_da = 0
			# "Mai partito" e' una storia, non una posizione: contano i secondi visti scorrere, non il
			# numero sul cronometro. Con un punto di ripresa la posizione parte gia' da 1200 s, e un
			# criterio basato sul valore assoluto -- la prima stesura diceva `if _pos <= 1.0` --
			# avrebbe classificato lo stesso guasto come 'bloccato', facendo aspettare 60 secondi
			# invece di 15 proprio nei film che si stanno riprendendo a meta'.
			if _prec is not None: self._pos_avanzata = True
			return
		_fermo = self._fermo_da = getattr(self, '_fermo_da', 0) + 1
		if not getattr(self, '_pos_avanzata', False):
			if _fermo < FERMO_MAI_PARTITO: return
			_esito = 'mai_partito'
		else:
			if _fermo < FERMO_BLOCCATO: return
			_esito = 'bloccato'
		self._esito_guasto = _esito
		# Il livello di cache non decide niente, ma va scritto: e' cio' che dira', rileggendo le righe
		# raccolte, se abbiamo cambiato sorgente su un decoder morto (cache alta) o su un collegamento
		# semplicemente lento (cache bassa). Se il secondo caso comparisse, la soglia va alzata.
		perf_logger('FenLight PERF CACHE',
					'SORGENTE GUASTA (%s) | posizione ferma a %.1f s da %s s | Player.OnAVStart %s '
					'| cache max %s%% media ultimi campioni %s | passo alla sorgente successiva'
					% (_esito, _pos, _fermo, 'mai arrivato' if not getattr(self, '_av_started', False) else 'arrivato',
					   getattr(self, '_cache_max_prima', 0), getattr(self, '_cache_tratto', None)))

	def _cambia_sorgente(self):
		"""Chiude la sorgente guasta e fa riprendere play_file dalla successiva.

		La riga di misura e' gia' stata scritta da _riassunto_cache prima di arrivare qui, con la
		colonna `esito` valorizzata: una riproduzione che non e' avvenuta resta agli atti, ma il
		wizard deve escluderla dal percentile della banda -- non e' una misura di banda.
		"""
		try:
			self.stop()
			sleep(500)
		except: pass
		# Lo scrobble era gia' partito alla prima iterazione del ciclo: si chiude, altrimenti su Trakt
		# resta appesa una visione a zero mentre la sorgente successiva ne apre un'altra.
		try:
			if getattr(self, 'scrobble_started', False):
				Thread(target=trakt_scrobble_stop, args=(self.media_type, self.tmdb_id, 0.0,
														 self._trakt_season, self._trakt_episode)).start()
				self.scrobble_started = False
		except: pass
		self.clear_playback_properties()
		nota_sorgente(getattr(self, 'playing_item', None), 'SCARTATA', getattr(self, '_esito_guasto', 'bloccata'),
					  'la riproduzione era partita e si e\' fermata', self._posizione())
		# clear_playing_item e flush_pending_refresh NON si chiamano qui, e non e' una dimenticanza.
		# flush_pending_refresh lancia la ricostruzione dei widget rimandata durante il video: farla
		# ora vorrebbe dire ricostruire l'interfaccia proprio mentre play_file risolve la sorgente
		# successiva, cioe' esattamente cio' che il presidio del lotto 111 esiste per impedire. La
		# riproduzione che riesce la eseguira' lei; se falliscono tutte, ci pensa playback_failed_action.
		try:
			self.sources_object.playback_successful = False
			self.sources_object.cancel_all_playback = False
			# SENZA QUESTA RIGA IL MECCANISMO NON FUNZIONA AFFATTO. playback_close_dialogs, alla prima
			# iterazione del ciclo, ha chiuso la finestra del risolutore e _kill_progress_dialog la
			# mette a None; play_file, al giro successivo, apre con `if not self.progress_dialog:
			# break` e uscirebbe dal ciclo senza provare nessun'altra sorgente. Ricrearla e' lo stesso
			# rimedio che random_continual_handler usa gia' dopo una riproduzione.
			self.sources_object._make_resolve_dialog()
		except: pass
		return False

	def monitor(self):
		try:
			# Ripiego, non percorso normale: dal lotto 203 la dimensione arriva gia' dalla stessa
			# richiesta che legge l'intestazione, prima di play(). Si riparte da qui solo se quella
			# richiesta e' fallita, per non perdere anche la misura.
			if not getattr(self, '_dimensione_vera', None):
				try: Thread(target=self._misura_dimensione).start()
				except: pass
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
						# Una volta sola, in sfondo: a player fermo non si legge piu' (lotto 202).
						try: Thread(target=self._misura_flusso).start()
						except: pass

					sleep(1000)
					self._campiona_cache()
					self._controlla_avanzamento()
					if getattr(self, '_esito_guasto', None): break
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
			self._riassunto_cache()
			# L'ordine conta: prima si scrive la misura (che ora porta anche il motivo del guasto),
			# poi si cambia sorgente. Cambiando prima, self.stop() smonterebbe il player e il
			# riassunto troverebbe getTotalTime() gia' morto.
			if getattr(self, '_esito_guasto', None): return self._cambia_sorgente()
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
			#
			# LOTTO 210 -- SI AZZERANO TUTTE E TRE. Finora spariva solo la chiave, e i due canali
			# restavano scritti: un rinvio a meta', in cui 'c'e' qualcosa da fare' era gia' falso ma
			# 'cosa fare' era ancora vero. WidgetRefresher gira ogni secondo e legge le due cose in
			# momenti diversi -- prima PENDING_REFRESH_PROP per decidere se consumare, poi id e azioni
			# per decidere COSA -- quindi bastava cadere fra le due letture per trovare la chiave
			# ancora accesa e i canali gia' svuotati da kodi_refresh_ids qui sotto. Un rinvio senza
			# id ne' azioni significa 'ricostruisci tutto' (service.py:426), ed e' cosi' che un
			# refresh MIRATO su un episodio diventava un UpdateLibrary globale.
			#
			# Misurato sulla stick il 09/09 alle 15:42:32.293: nello STESSO millisecondo la riga
			# 'MIRATO 1 contenitori | id=1 azioni=1' del thread 32303 e 'rinvio consumato dopo 74.3s'
			# del thread 31994, e 11 ms dopo 'refresh_widgets&coalesce=false' -> GLOBALE. La finestra
			# di corsa era di circa 300 ms, cioe' il tempo di _wait_window_settled.
			#
			# Azzerarle insieme la chiude: chi legge trova o tutto o niente, e 'niente' non consuma.
			ku.clear_property(ku.PENDING_REFRESH_PROP)
			ku.clear_property(ku.PENDING_IDS_PROP)
			ku.clear_property(ku.PENDING_ACTIONS_PROP)
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
