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

# LOTTO 212 -- LA CAPACITA' SI VEDE SOLO QUANDO IL BUFFER HA SPAZIO.
#
# Consegna e capacita' non sono la stessa cosa. Per quasi tutta una riproduzione il player chiede
# solo cio' che consuma: buffer pieno, richieste rallentate, consegna = bitrate del file. In quel
# momento la consegna non dice NIENTE su quanto la linea saprebbe dare. La capacita' e' osservabile
# soltanto mentre il buffer NON e' pieno, perche' li' Kodi tira quanto la linea concede.
#
# Sotto il tetto vale una formula sola, e copre tre casi invece di uno:
#     capacita' = bitrate + (variazione del buffer in byte / tempo)
#   buffer che SALE   -> la linea da' piu' del film: capacita' = bitrate + surplus
#   buffer FERMO      -> da' esattamente quanto il film consuma: capacita' = bitrate, esatto
#   buffer che CALA   -> non ce la fa: capacita' MINORE del bitrate, e sappiamo di quanto
# Gli ultimi due il lotto 197 non li misurava affatto (`if _dt > 0 and _dl > 0`): su 33 riproduzioni
# riuscite, 9 non hanno prodotto nessuna misura, e otto di quelle nove avevano la cache inchiodata
# vicino a zero. Erano le riproduzioni al limite, cioe' le uniche che dicono dove sta il limite.
#
# 90 e non 100: vicino al tetto la percentuale si appiattisce -- il buffer e' quasi sazio e l'ultimo
# tratto non e' piu' una misura della linea. Dieci punti di distanza dal tetto costano poco e tolgono
# l'ambiguita'.
TETTO_CACHE = 90
# Un crollo di questa ampiezza in un campione solo non e' consegna che manca: e' il buffer BUTTATO
# (un salto, un cambio di flusso). Vale 6 MB in un secondo su un buffer da 24: nessuna linea lo fa.
# Spezza il tratto invece di entrare nel conto come pendenza negativa enorme.
CROLLO_BRUSCO = 25
# Sotto questi campioni un tratto non dice niente: la percentuale e' un intero, e su pochi punti la
# quantizzazione pesa piu' del segnale.
MIN_CAMPIONI_TRATTO = 5
# E almeno questi secondi. Il minimo in CAMPIONI da solo non basta piu' da quando si campiona fitto:
# a 250 ms cinque campioni sono un secondo e un quarto, cioe' un lampo, e la quantizzazione della
# percentuale peserebbe piu' del segnale. Le due condizioni misurano cose diverse -- quanti punti
# abbiamo letto e per quanto tempo -- e servono tutte e due.
MIN_SECONDI_TRATTO = 3.0
# Capienza minima: un tratto che parte troppo in alto ha il tetto addosso e la sua pendenza e'
# tagliata dal tetto, non dalla linea. Quaranta punti sono cio' che serve per poter scrivere,
# nei tre secondi minimi, anche la linea piu' veloce che abbiamo mai misurato (~13%/s).
CAPIENZA_MINIMA = 40
# Il PAVIMENTO della banda utile, e NON e' lo zero esatto. Su 28 Years Later (10/09) il buffer ha
# passato quarantadue secondi a terra rimbalzando fra 0 e 1, e il conteggio a zero esatto leggeva 7:
# quegli 1% spezzavano la sequenza. Ma l'1% di 24 MB sono 245 KB, cioe' quattro centesimi di secondo
# di un film da 45 Mbit/s -- vuoto quanto lo zero. Sotto questa soglia il buffer non puo' piu'
# scendere e smette di registrare il deficit, esattamente come sopra il tetto smette di registrare
# il surplus: la formula non vale ne' di qua ne' di la'.
PAVIMENTO_CACHE = 2
# LOTTO 221 -- una finestra deve avere una DIREZIONE. `capacita = bitrate + variazione/tempo` e'
# vera su qualunque finestra, ma su una a V -- il buffer scende e poi risale allo stesso punto -- la
# media descrive due regimi opposti e non ne descrive nessuno. The Two Towers (10/09): il buffer e'
# sceso da 87 a 48 ed e' risalito a 81, netto +1 punto in dieci secondi, e la riga ha registrato
# "22,0 Mbit/s" su un collegamento che nella stessa riproduzione ne misurava 42,9 dopo il salto.
# Il criterio e' quanto la finestra FINISCE vicino a uno dei suoi estremi: sui tratti veri separa
# senza sovrapposizioni -- riempimenti e svuotamenti monotoni 1,00, tuffi a V 0,14-0,25.
FRAZIONE_DIREZIONE = 0.5
# ...sotto questa escursione la finestra e' semplicemente piatta, e il rapporto non significa niente:
# una cache ferma a 12% con un punto di rumore avrebbe netto 0 su escursione 2. Il piatto dentro la
# banda resta la misura esatta che il lotto 212 ha voluto (capacita' = bitrate).
ESCURSIONE_MINIMA = 10

# CAMPIONAMENTO FITTO -- LOTTO 213.
# Il buffer si riempie PRIMA che l'immagine compaia: il 10/09 fra Player.OnPlay (01:54:28.7) e
# Player.OnAVStart (01:54:33.1) sono passati 4,36 secondi, e al primo campione la cache era gia' al
# 72% -- 17,3 MB su 24 arrivati mentre non stavamo guardando. Su quattro riproduzioni i tratti sono
# usciti di 5, 6, 7 campioni e uno non e' uscito affatto: su un collegamento piu' veloce dei file,
# guardare una volta al secondo a partire da OnAVStart significa arrivare a riempimento quasi finito.
#
# La cura e' guardare PRIMA e piu' spesso, ma solo dove serve: finche' il buffer ha spazio e finche'
# il tratto e' ancora corto. A regime -- cache al tetto, o tratto gia' lungo -- si torna a un giro al
# secondo e il costo sparisce.
PASSO_FITTO = 250               # ms fra due letture nella fase fitta
CAMPIONI_FITTI = 40             # oltre questi il tratto ha gia' risoluzione a sufficienza
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
		# Il tratto in corso si spezza qui: un salto butta la cache di Kodi, e un tratto a cavallo
		# della discontinuita' misurerebbe un dislivello, non una velocita'.
		#
		# NON basta il cambio di fase dentro _campiona_cache. Quello scatta solo al PRIMO salto --
		# quando `_salti` passa da 0 a 1 e il suffisso va da _prima a _dopo -- mentre dal secondo in
		# poi la fase resta _dopo e il tratto passerebbe sopra il salto senza accorgersene. Il vecchio
		# meccanismo azzerava la finestra a ogni salto e aveva ragione; qui serve lo stesso.
		#
		# Si alza una bandiera invece di chiudere il tratto da qui: questa e' una richiamata di Kodi e
		# gira su un altro thread, mentre _campiona_cache sta scrivendo la stessa lista. Un booleano
		# lo si posa e basta; a chiudere ci pensa il ciclo, dove la lista ha un padrone solo.
		try: self._tratto_rotto = True
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
		self._tratto_campiona(_liv)
		# Il tratto consecutivo piu' lungo A SECCO. E' l'unico esito che si SENTE: la media della
		# cache misura il margine (lotto 197), ma il film si ferma solo quando il buffer resta vuoto.
		# La soglia e' PAVIMENTO_CACHE e non lo zero esatto -- vedi il commento alla costante: a zero
		# esatto questo numero usciva sei volte piu' piccolo del vero.
		if _liv <= PAVIMENTO_CACHE:
			_run = getattr(self, '_cache_run_secco', 0) + 1
			self._cache_run_secco = _run
			if _run > getattr(self, '_cache_secco_max', 0): self._cache_secco_max = _run
			# LOTTO 220 -- anche per fase, e serve al log: `_cache_secco_max` e' di TUTTA la
			# riproduzione, e usarlo per spiegare l'esito di una fase dice il falso. Marty Supreme
			# (11/09): la fase PRIMA aveva media 98% e minimo 55, zero secondi a secco, e il log le
			# attribuiva ventidue secondi di buffer vuoto che erano tutti nella fase DOPO.
			_sf = '_dopo' if _dopo else '_prima'
			if _run > getattr(self, '_cache_secco_max' + _sf, 0):
				setattr(self, '_cache_secco_max' + _sf, _run)
		else: self._cache_run_secco = 0
		_tratto = getattr(self, '_cache_tratto', None)
		if _tratto is None: _tratto = self._cache_tratto = []
		_tratto.append(_liv)
		# Una riga ogni dieci secondi: la forma a dente di sega si legge dalla sequenza, non da una media.
		if len(_tratto) >= 10:
			perf_logger('FenLight PERF CACHE', 'livello %s | salti finora %s'
						% ('-'.join(str(_v) for _v in _tratto), getattr(self, '_salti', 0)))
			self._cache_tratto = []

	def _campiona_capacita(self):
		"""UNA lettura in piu\' della cache, per la sola misura di capacita\' (lotto 213).

		Separata da _campiona_cache di proposito. Quella resta a UN giro al secondo perche\' possiede
		le statistiche -- `campioni`, `secondi_a_secco`, le medie e i massimi -- e quei nomi dicono
		secondi: farla girare quattro volte al secondo cambierebbe il significato di quattro colonne
		senza che nessuno se ne accorga. Qui invece si alimenta solo il tratto, che di suo non ha
		nessuna unita\' di tempo implicita: piu\' campioni sono solo piu\' risoluzione.
		"""
		try:
			_grezzo = get_infolabel('Player.CacheLevel')
			if not _grezzo: return
			self._tratto_campiona(int(float(_grezzo)))
		except: pass

	def _fitto_utile(self):
		"""Se conviene guardare piu\' spesso: c\'e\' spazio nel buffer E il tratto e\' ancora corto."""
		if getattr(self, '_tetto_raggiunto', False): return False
		return len(getattr(self, '_tratto_utile', None) or []) < CAMPIONI_FITTI

	def _attesa_campionata(self):
		"""Il secondo di attesa del ciclo, speso guardando la cache invece che dormendo e basta.

		L\'ultimo quarto non si campiona: subito dopo tocca a _campiona_cache, che legge comunque.
		"""
		_quanti = max(1, 1000 // PASSO_FITTO)
		for _i in range(_quanti):
			sleep(PASSO_FITTO)
			if _i == _quanti - 1: return
			if self._fitto_utile(): self._campiona_capacita()

	def _tratto_campiona(self, _liv):
		"""Aggiunge un campione al tratto in corso, spezzandolo dove va spezzato.

		PORTATA -- LOTTO 212. Niente finestra fissa da 20 campioni: era lei a produrre il numero
		costante. 5%/s x 20 s = 100%, cioe\' il buffer intero: ogni volta che la cache si riempiva
		dentro la finestra, la "portata sostenuta" misurava la LUNGHEZZA DELLA FINESTRA e non la
		linea. Nei log raccolti quel valore usciva 5,1%/s otto volte su ventisette, e 5,0 altre due.
		Su Angel Dust il conto vero era 9,1%/s e la finestra dava 5,1: capacita\' registrata
		15,1 Mbit/s contro 22,7 reali, -33%.

		Adesso si misurano TRATTI: ogni sequenza di campioni consecutivi rimasti sotto il tetto, con
		i due estremi presi da campioni VERI e il tempo da perf_counter. Non si indovina dove il
		riempimento comincia o finisce -- si usano i campioni che ci sono, e l\'unico errore che resta
		e\' l\'arrotondamento della percentuale: su un tratto da 90 punti vale l\'1%.

		UNA CONSERVATIVITA\' CHE RESTA, E VOLUTA. All\'avvio la cache sta a zero per qualche campione
		prima di muoversi -- il collegamento che si apre -- e quei secondi entrano nel conto.
		Toglierli vorrebbe dire decidere quali campioni sono "veri", ed e\' la strada delle euristiche
		che questo lotto sta smontando; e non si potrebbe distinguere il caso in cui la cache resta a
		zero perche\' la linea non ce la fa, che e\' la misura piu\' preziosa che abbiamo.
		"""
		self._tetto_raggiunto = _liv > TETTO_CACHE
		_suff = '_dopo' if getattr(self, '_salti', 0) > 0 else '_prima'
		_tratto_u = getattr(self, '_tratto_utile', None)
		if _tratto_u is None: _tratto_u = self._tratto_utile = []
		# Va INIZIALIZZATA al primo campione, non lasciata al valore predefinito. Se resta assente
		# fino al primo salto, quando quello arriva `_fase` si legge gia' come '_dopo' e il tratto
		# iniziale -- che e' tutto roba di PRIMA -- viene chiuso nella fase sbagliata: la misura
		# principale sparisce e quella secondaria eredita numeri che non sono suoi.
		_fase = getattr(self, '_tratto_fase', None)
		if _fase is None: _fase = self._tratto_fase = _suff
		# Quattro modi di spezzare un tratto, e nessuno dei quattro e' "la linea e' lenta": il primo
		# salto (cambia la fase), i salti successivi (la bandiera posata da onPlayBackSeek), il tetto
		# raggiunto (la capacita' smette di essere osservabile) e un crollo che nessuna linea puo'
		# produrre. Confonderne anche uno solo con la lentezza vorrebbe dire registrare come misura
		# della banda un buffer buttato via.
		# LOTTO 217 -- la banda utile ha DUE bordi, non uno. Sopra il tetto Kodi si strozza da solo
		# e la cache non dice piu' niente; a ZERO il buffer non puo' scendere oltre, quindi smette
		# di registrare il deficit: dB/dt va a zero e la formula legge "capacita' = bitrate" mentre
		# la verita' e' "capacita' MINORE del bitrate, di quanto non si sa". E' la stessa censura,
		# specchiata, e fino al lotto 216 si guardava un bordo solo. The Mandalorian (10/09): 206
		# dei 265 campioni del tratto vincente erano schiacciati sul pavimento.
		_fuori = _liv > TETTO_CACHE or _liv <= PAVIMENTO_CACHE
		if (_fase != _suff or getattr(self, '_tratto_rotto', False) or _fuori
				or (_tratto_u and (_tratto_u[-1][1] - _liv) > CROLLO_BRUSCO)):
			self._tratto_rotto = False
			self._chiudi_tratto(_fase, _liv > TETTO_CACHE)
			_tratto_u = self._tratto_utile = []
			self._tratto_fase = _suff
		if not _fuori: _tratto_u.append((perf_counter(), _liv))

	def _chiudi_tratto(self, suff, tetto=False):
		"""Chiude il tratto in corso e lo conserva se e\' il piu\' LUNGO fra quelli CAPIENTI.

		Due regole, e fanno due lavori diversi.

		La capienza SQUALIFICA. La pendenza di un tratto e' limitata dallo spazio che ha sopra di
		se': un tratto che parte da 82 ha otto punti prima del tetto, quindi non PUO' scrivere piu'
		di otto punti, per quanto veloce sia la linea. Se la linea fosse velocissima quel tratto
		finirebbe subito e cadrebbe sotto il minimo di tre secondi; se sopravvive e' perche' e'
		lento. Un tratto senza capienza dice sempre "linea al minimo", qualunque sia la linea, e
		quindi non e' una misura. Il lotto 213 lo faceva concorrere con gli altri e sul film delle
		02:42 il riempimento iniziale (73 punti, 39,8 Mbit/s) e un tuffo di meta' film (1 punto,
		20,1 Mbit/s) sono finiti a pari merito su 28 campioni: tre secondi di tuffo in piu' e la
		portata registrata si sarebbe dimezzata senza che la linea fosse cambiata di nulla.

		Fra i tratti capienti SCEGLIE la lunghezza, ed e' la regola del lotto 212, che resta: il
		piu' lungo, non il piu' ripido. Un tratto breve e ripido e' il picco che i lotti 191, 193 e
		197 hanno gia' preso per buono tre volte -- descrive un istante, non cio' che regge un film.

		Se nessun tratto e' capiente non si registra niente. Un buco e' onesto: vuol dire che quella
		riproduzione non ha mai offerto una finestra in cui la linea potesse dire quanto vale.

		Si conservano anche CAMPIONI e PUNTI, e non e' contorno: sono cio' che permette di
		distinguere una misura solida -- quaranta campioni su novanta punti -- da una tirata su
		cinque campioni e sei punti. Senza, davanti al 5,1%/s costante non avevo modo di accorgermi
		che non era una misura. Il wizard le usera' per pesare o scartare.
		"""
		_t = getattr(self, '_tratto_utile', None) or []
		if len(_t) < MIN_CAMPIONI_TRATTO: return
		_dt = _t[-1][0] - _t[0][0]
		if _dt < MIN_SECONDI_TRATTO: return
		# LOTTO 216 -- la capienza vale solo per i tratti che il TETTO ha troncato. Nel lotto 214
		# la si applicava sempre, e su The Mandalorian (10/09) ha buttato il tratto piu' lungo mai
		# osservato -- 265 campioni su 264 secondi -- soltanto perche' partiva da 79. Il tetto non
		# c'entrava niente: quel tratto SCENDEVA, allontanandosi dal tetto, e aveva davanti a se'
		# tutti i settantanove punti di discesa. Censura chi ti sbarra la strada, non chi ti sta
		# alle spalle.
		# LOTTO 219 -- la capienza si misura dal punto piu' BASSO che il tratto ha raggiunto, non da
		# dove parte. Il tetto censura un tratto solo se quel tratto non si e' mai allontanato dal
		# tetto: se e' sceso a 14 e poi e' risalito, di spazio ne ha avuto in abbondanza e la sua
		# pendenza non e' tagliata da niente. Wuthering Heights (11/09), 1805 campioni su mezz'ora:
		# quattro escursioni vere -- fino al 14%, al 37%, al 47% -- tutte buttate perche' PARTIVANO
		# da 80-87. Quella riproduzione non ha prodotto una sola misura.
		_liv_t = [_c[1] for _c in _t]
		if tetto and TETTO_CACHE - min(_liv_t) < CAPIENZA_MINIMA: return
		_escursione = max(_liv_t) - min(_liv_t)
		if _escursione > ESCURSIONE_MINIMA and \
				abs(_liv_t[-1] - _liv_t[0]) < _escursione * FRAZIONE_DIREZIONE: return
		# Fra i capienti vince il piu' lungo. A parita' non si sostituisce: il primo ha gia' un tempo.
		if len(_t) <= getattr(self, '_tratto_campioni' + suff, 0): return
		setattr(self, '_tratto_pendenza' + suff, (_t[-1][1] - _t[0][1]) / _dt)
		setattr(self, '_tratto_campioni' + suff, len(_t))
		setattr(self, '_tratto_punti' + suff, _t[-1][1] - _t[0][1])
		# LOTTO 217 -- quanti campioni di QUESTO tratto erano schiacciati sul pavimento. Lo stavo
		# gia' calcolando qui dentro e lo buttavo. E' il dato che distingue una misura da un limite
		# superiore: a zero il buffer non puo' scendere oltre, quindi smette di registrare il
		# deficit e la pendenza misura il pavimento invece della linea. `secondi_a_secco` non serve
		# allo scopo -- e' di tutta la riproduzione, mentre la contaminazione riguarda il tratto
		# vincente, e i due si separano solo per caso (Devil Wears Prada: 9 s a zero e la misura
		# migliore dell'archivio, perche' quegli zeri erano il punto da cui la risalita partiva).
		setattr(self, '_tratto_secchi' + suff, sum(1 for _c in _t if _c[1] <= PAVIMENTO_CACHE))
		# LOTTO 219 -- i SECONDI, e non si ricavano dai campioni: il passo non e' costante (250 ms
		# finche' il fitto e' acceso, poi 1 s), quindi 46 campioni possono valere 15,8 s e 77 ne
		# possono valere 48,3. E' la durata che dice quanto una misura e' sostenuta, ed e' la
		# distinzione che serve: le finestre corte leggono sistematicamente piu' alto.
		setattr(self, '_tratto_secondi' + suff, round(_dt, 1))
		# quanto la finestra e' andata in una direzione sola: 1,0 monotona, ~0 andata e ritorno.
		# Si conserva come si conserva `portata_secchi`, per poter verificare la regola dall'archivio
		# invece di doverla ricontrollare sui log.
		setattr(self, '_tratto_direzione' + suff,
				round(abs(_liv_t[-1] - _liv_t[0]) / float(_escursione), 2) if _escursione else 1.0)

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
			# LOTTO 231 -- LO STESSO NUMERO DEL FILTRO, non l'impostazione.
			#
			# Questo cancello e il filtro di sources.filter_results decidono la stessa cosa su due
			# stime diverse dello stesso bitrate: il filtro sulla dimensione dichiarata, questo sui
			# byte e i secondi letti dentro il file. Se leggessero due SOGLIE diverse -- il filtro
			# quella misurata dalla sonda, questo l'impostazione scritta a mano -- il piu' preciso
			# dei due giudicherebbe contro un numero vecchio. Il 10/09 il filtro decideva su 26,7
			# Mbit/s misurati e questo su 50 impostati.
			_linea, _fonte = self._linea_utile()
			if _linea <= 0: return True, 'linea non impostata'
			_mbit = (_byte * 8.0) / _sec / 1000000.0
			self._bitrate_vero = _mbit
			_come = '%.1f Mbit/s veri (%.2f GB in %s)' % (_mbit, _byte / 1000000000.0, self._mmss(_sec))
			if _mbit <= _linea: return True, '%s, entro i %.1f %s' % (_come, _linea, _fonte)
			return False, '%s, oltre i %.1f %s' % (_come, _linea, _fonte)
		except: return True, 'cancello banda fallito'

	@staticmethod
	def _linea_utile():
		"""(Mbit/s, da dove viene). La misura della sonda se c'e', l'impostazione altrimenti.

		La provenienza si restituisce e si scrive nel log: senza, una riga di scarto non dice se il
		numero contro cui la sorgente e' stata giudicata era misurato o scritto a mano, e non si
		puo' piu' verificare a posteriori se il cancello ha tolto roba buona.
		"""
		try:
			from modules import sonda_linea
			_m = sonda_linea.letta()
			_v = sonda_linea.line_speed_da((_m or {}).get('regime'))
			if _v: return _v, 'dalla sonda (%.1f Mbit/s misurati / %.2f)' % (_m['regime'], sonda_linea.MARGINE)
		except: pass
		try: return float(get_setting('results.line_speed', '25') or 25), 'impostati'
		except: return 0.0, 'impostati'

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
									dimensione_dichiarata=_item.get('size'),
									**self._campi_sonda())
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

	def _campi_sonda(self):
		"""Le colonne del lotto 222: la misura della linea presa PRIMA di questa riproduzione.

		`link` si scrive SEMPRE, anche quando la sonda non c'e' stata: non serve piu' a scegliere il
		bersaglio (dal lotto 230 e' la sorgente che sta per partire) ma a poter risalire a QUALE file
		una misura descriveva. Le altre colonne restano NULL, che vuol dire 'non misurato' e non
		'misurato zero'.
		"""
		_fuori = {'link': getattr(self, 'url', None) or None}
		try:
			from modules import sonda_linea
			_e = sonda_linea.letta()
			if not _e: return _fuori
			_t0 = getattr(self, '_sonda_t0', None)
			_fuori.update({
				'sonda_mbps': _e.get('regime'), 'sonda_lorda': _e.get('lorda'),
				'sonda_secondi': _e.get('regime_secondi'), 'sonda_byte': _e.get('byte'),
				'sonda_offset': _e.get('offset'),
				'sonda_quota': _e.get('quota'),
				'sonda_cpu': int(_e['cpu'] * 1000) if _e.get('cpu') else None,
				'sonda_ttfb': int(_e['ttfb']) if _e.get('ttfb') else None,
				'sonda_cdn': _e.get('cdn') or None,
				'sonda_eta': int(_t0 - _e['quando']) if (_t0 and _e.get('quando')) else None})
		except: pass
		return _fuori

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
			# Il tratto ancora aperto va chiuso PRIMA di leggere le pendenze: su una riproduzione che
			# non ha mai riempito il buffer -- proprio quelle che il lotto 197 non misurava -- il
			# tratto e' uno solo e arriva fino all'ultimo campione. Senza questa riga sarebbe l'unico
			# caso in cui continueremmo a non misurare niente.
			self._chiudi_tratto(getattr(self, '_tratto_fase', '_prima'))
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
			for _et, _sf in (('prima del salto', '_prima'), ('DOPO il salto ', '_dopo')):
				# LOTTO 219 -- una fase senza campioni non e' una fase senza misura: e' una fase che
				# non c'e' stata. Prima si stampava "capacita DOPO il salto | la linea non regge
				# questo bitrate" anche con `salti 0`, cioe' una diagnosi su una finestra mai
				# esistita, per giunta allarmante.
				if not getattr(self, '_cache_n' + _sf, 0):
					if _sf == '_dopo':
						perf_logger('FenLight PERF CACHE', 'capacita %s | nessun salto in questa '
									'riproduzione' % _et)
					continue
				_pend = getattr(self, '_tratto_pendenza' + _sf, None)
				if _pend is None:
					# LOTTO 216 -- il motivo, non una formula fissa. Il messaggio vecchio diceva
					# sempre "nessun tratto di almeno 5 campioni sotto il 90%", e su The Mandalorian
					# (10/09) era falso: di campioni sotto il 90 ce n'erano 283. Un log che dichiara
					# una causa sbagliata e' peggio di un log muto, perche' chiude l'indagine.
					_a_secco = getattr(self, '_cache_secco_max' + _sf, 0)
					perf_logger('FenLight PERF CACHE', 'capacita %s | non misurabile: %s'
								% (_et, ('il buffer e\' rimasto sotto il %s%% fino a %s s di fila: '
										 'li\' non puo\' scendere oltre, quindi non misura piu\' '
										 'niente -- la linea non regge questo bitrate'
										 % (PAVIMENTO_CACHE, _a_secco))
									if _a_secco >= 10 else
									('nessun tratto abbastanza lungo o abbastanza capiente sotto il '
									 '%s%% di buffer (minimo %s campioni, %s s)'
									 % (TETTO_CACHE, MIN_CAMPIONI_TRATTO, MIN_SECONDI_TRATTO))))
					continue
				_camp = getattr(self, '_tratto_campioni' + _sf, 0)
				_punti = getattr(self, '_tratto_punti' + _sf, 0)
				# Il verso si scrive a parole: e' la differenza fra "la linea aveva margine" e "la
				# linea non ce la faceva", e su un numero vicino a zero il segno da solo si perde.
				_verso = 'in salita' if _punti > 0 else ('in calo' if _punti < 0 else 'ferma')
				if _mb:
					perf_logger('FenLight PERF CACHE',
								'capacita %s | tratto piu\' lungo: %s campioni, %+d punti (%s) in %.1f s '
								'-> %+.2f%%/s = %+.1f Mbit/s oltre il bitrate | buffer in avanti %.0f MB'
								% (_et, _camp, _punti, _verso, (_punti / _pend) if _pend else 0.0,
								   _pend, _pend / 100.0 * _mb * 8, _mb))
				else:
					perf_logger('FenLight PERF CACHE', 'capacita %s | %+.2f%%/s su %s campioni '
								'(filecache.memorysize non leggibile, non convertibile in Mbit/s)'
								% (_et, _pend, _camp))
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
				# `is None` e NON `if not _p`: dal lotto 212 la pendenza puo' valere zero (buffer
				# fermo sotto il tetto: la linea da' esattamente il bitrate, ed e' una misura
				# perfetta) o essere negativa (non ce la fa). Il vecchio controllo le buttava
				# entrambe, ed erano proprio le riproduzioni al limite.
				_p = getattr(self, '_tratto_pendenza' + _sf, None)
				if _p is None or not buffer_mb or not _bit: return None
				return _p / 100.0 * buffer_mb * 8 + _bit
			def _con_peso(_v, _sf):
				if _v is None: return 'n.d.'
				return '%.1f (%s campioni in %s s)' % (_v, getattr(self, '_tratto_campioni' + _sf, 0),
													  getattr(self, '_tratto_secondi' + _sf, 0))
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
				# Lotto 215: una coppia per misura. Senza quella `_dopo`, una portata presa solo dopo
				# il salto arrivava al wizard senza peso e sembrava inaffidabile proprio quando era
				# la piu' solida delle due -- dopo un salto il buffer riparte da zero e ha tutti i
				# novanta punti davanti, quindi il tratto e' lungo e capiente.
				portata_campioni_prima=getattr(self, '_tratto_campioni_prima', None) or None,
				portata_punti_prima=getattr(self, '_tratto_punti_prima', None),
				portata_campioni_dopo=getattr(self, '_tratto_campioni_dopo', None) or None,
				portata_punti_dopo=getattr(self, '_tratto_punti_dopo', None),
				portata_secchi_prima=getattr(self, '_tratto_secchi_prima', None),
				portata_secchi_dopo=getattr(self, '_tratto_secchi_dopo', None),
				portata_secondi_prima=getattr(self, '_tratto_secondi_prima', None),
				portata_secondi_dopo=getattr(self, '_tratto_secondi_dopo', None),
				portata_direzione_prima=getattr(self, '_tratto_direzione_prima', None),
				portata_direzione_dopo=getattr(self, '_tratto_direzione_dopo', None),
				cache_media_prima=_media(getattr(self, '_cache_somma_prima', 0), _np),
				cache_max_prima=getattr(self, '_cache_max_prima', None) if _np else None,
				cache_media_dopo=_media(getattr(self, '_cache_somma_dopo', 0), _nd),
				cache_max_dopo=getattr(self, '_cache_max_dopo', None) if _nd else None,
				secondi_a_secco=getattr(self, '_cache_secco_max', 0),
				campioni=getattr(self, '_cache_n', 0),
				larghezza=getattr(self, '_vid_larghezza', None), altezza=getattr(self, '_vid_altezza', None),
				codec=getattr(self, '_vid_codec', None), esito=getattr(self, '_esito_guasto', None),
				nome=_it.get('name') or getattr(self, 'playing_filename', None) or None,
				dimensione_dichiarata=_dich, provider=_it.get('provider') or _it.get('scrape_provider') or None,
				pacchetto=_it.get('package') or None, **self._campi_sonda())
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
						   # Lotto 215: accanto al valore, su quanto e' stato costruito. Leggendo il
						   # log si deve poter distinguere 37,9 su 51 campioni da 37,9 su cinque,
						   # senza dover aprire il database.
						   _con_peso(_porta('_prima'), '_prima'), _con_peso(_porta('_dopo'), '_dopo'),
						   getattr(self, '_cache_secco_max', 0),
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
			# LOTTO 213 -- QUI SI CAMPIONA GIA'. Questa attesa esisteva per non entrare nel ciclo prima
			# che il flusso fosse davvero partito, e passava sessanta giri a guardare una bandiera.
			# Sono anche i secondi in cui il buffer si riempie: il 10/09 fra OnPlay e OnAVStart ne
			# sono passati 4,36, e quando il ciclo prendeva il suo primo campione la cache era gia' al
			# 72%. Il thread gira comunque; leggere la cache ogni PASSO_FITTO e' l'unico modo di
			# vedere il riempimento invece della sua coda, e non costa un giro in piu'.
			_atteso, _giri = 0.0, 0
			_ogni = max(1, int(PASSO_FITTO / 50))
			while not getattr(self, '_av_started', False) and _atteso < 3.0 and self.isPlayingVideo():
				sleep(50)
				_atteso += 0.05
				_giri += 1
				if _giri % _ogni == 0 and self._fitto_utile(): self._campiona_capacita()
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

					self._attesa_campionata()
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
		# LOTTO 225 -- si timbra solo l'istante di avvio. Niente da mollare e niente da aspettare:
		# la sonda vive nel servizio e ha gia' finito. Questo istante serve a `sonda_eta`, che
		# calcolata alla scrittura in archivio conterrebbe la durata del film invece dell'attesa.
		try:
			from time import time as _adesso
			self._sonda_t0 = _adesso()
		except: pass
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
