# -*- coding: utf-8 -*-
import time
import json
import random
from threading import Thread
from caches.external_cache import external_cache
from caches.settings_cache import get_setting
from modules import kodi_utils, source_utils
from modules.debrid import RD_check, PM_check, AD_check, OC_check, ED_check ,TB_check, query_local_cache
from modules.utils import clean_file_name
from modules.settings import preferred_language, pref_language_country
logger = kodi_utils.logger

normalize, get_file_info, pack_enable_check = source_utils.normalize, source_utils.get_file_info, source_utils.pack_enable_check
sleep, xbmc_monitor, get_property, set_property = kodi_utils.sleep, kodi_utils.xbmc_monitor, kodi_utils.get_property, kodi_utils.set_property
notification, hide_busy_dialog = kodi_utils.notification, kodi_utils.hide_busy_dialog
int_window_prop = 'fenlight.internal_results.%s'
pack_display = '%s (%s)'
pack_check = ('Season', 'Show')
debrid_runners = {'Real-Debrid': ('Real-Debrid', RD_check), 'Premiumize.me': ('Premiumize.me', PM_check), 'AllDebrid': ('AllDebrid', AD_check),
'Offcloud': ('Offcloud', OC_check), 'EasyDebrid': ('EasyDebrid', ED_check), 'TorBox': ('TorBox', TB_check)}
sd_check = ('SD', 'CAM', 'TELE', 'SYNC')
correct_pack_sizes = ('torrentio', 'knightcrawler', 'comet')
# LOTTO 366 -- i provider il cui abbinamento torrent -> id IMDb regge da solo, misurato (SORGENTI.md). Solo per i FILM
# e solo per ripescare un risultato che il nome aveva segnato. Prova del 25/09 sera, ripescati solo per id: Torrentio e
# MediaFusion tutti giusti nel campione; Comet ~1 su 6 sbagliato (Das Boot per L'Impero colpisce ancora, Aliens per
# Alien, Mandalorian and Grogu per Guerre stellari), ICV 1 su 10 (Galaxy Quest per Alien). DMM cerca per id ma ~45%
# dei suoi risultati ha un altro titolo. Knaben e bitsearch cercano per testo.
id_affidabile = ('torrentio', 'mediafusion')
# Lotto 368: l'ultimo provider che non si aspetta, e quante sorgenti in cache bastano per non aspettarlo
ULTIMO_LENTO, ULTIMO_BASTA = 'knaben', 10

def _senza_doppioni(results):
	"""Lotto 387 -- una copia per hash (e per url). Se lo stesso hash arriva da piu' provider vince la copia ACCETTATA dal nome
	(`identita_nome` non False), qualunque sia l'ordine d'arrivo: prima vinceva la prima arrivata, e la stessa ricerca
	decideva in due modi (la copia di DMM, con l'etichetta di un altro torrent, mandava a giudizio una fonte che quella di
	Knaben aveva accettato). L'ordine delle fonti resta quello d'arrivo."""
	scelta = {}
	for i in results:
		h = i.get('hash')
		if h and (h not in scelta or (scelta[h].get('identita_nome') is False and i.get('identita_nome') is not False)): scelta[h] = i
	fuori, url_visti = [], set()
	for i in results:
		try:
			h = i.get('hash')
			if h and scelta[h] is not i: continue
			url = i['url'].lower()
			if url in url_visti: continue
			url_visti.add(url)
		except: pass
		fuori.append(i)
	return fuori

def _provider_per_hash(results):
	"""Lotto 387 -- hash -> i provider che l'hanno dato, contati prima di togliere i doppioni."""
	fuori = {}
	for i in results:
		if i.get('hash'): fuori.setdefault(i['hash'], set()).add(i.get('provider'))
	return fuori

def _etichette_per_hash(results):
	"""Lotto 388 -- hash -> (le etichette, i nomi dei file indicati) di TUTTE le copie, prima di togliere i doppioni. Una fonte
	segnata dal nome si giudica su tutte: con la sola copia rimasta, quella arrivata prima, la stessa ricerca decideva in due
	modi (Dracula del 2025: "Dracula.3D" di DMM passava, "Dracula.3D.(2012)" di Knaben no).

	Lotto 393: le etichette di DMM solo se l'hash arriva SOLO da DMM. DMM a volte chiama un torrent col nome di un altro
	(lotto 373): nell'unione la sua etichetta ripescava "Monster.S01E01" per Re:Monster, che le copie di Comet chiamavano
	col nome vero. Gli altri provider danno il nome del torrent o di un suo file."""
	tutte, senza_dmm = {}, {}
	for i in results:
		if not i.get('hash'): continue
		for d in ((tutte, senza_dmm) if i.get('provider') != 'dmm' else (tutte,)):
			nomi, file = d.setdefault(i['hash'], ([], []))
			if i.get('name') and i['name'] not in nomi: nomi.append(i['name'])
			if i.get('nome_file') and i['nome_file'] not in file: file.append(i['nome_file'])
	return dict((h, senza_dmm.get(h) or v) for h, v in tutte.items())

def _in_testa_con_anno(domanda, nomi):
	"""LOTTO 386 -- la conferma larga del ripescaggio dei film: un titolo intero in testa alla radice o al file, con l'anno esatto
	nel nome, e nessuno dei due porta un anno di un altro film ("The Godfather 3 (1990)" in una cartella "(1972)" resta fuori).
	"El señor de los anillos El retorno del rey (Version Extendida) (2003)" passa; "Dune World (2021)" per Dune (2021) anche,
	e dal nome non si distingue. Con il titolo intero in testa e l'anno esatto `contraddice` non ha niente da dire."""
	nomi = [n for n in nomi if n]
	if any(domanda.anni_fuori(n) for n in nomi): return False
	return any(domanda.titolo_in_testa_con_anno(n) for n in nomi)

def _titolo_nel_vero(domanda, radice, f):
	"""Lotto 410. Il titolo nel nome VERO del torrent (il file scelto, la cartella radice) o, per i film, in testa con anno."""
	file = f[1] if f is not None else ''
	return ((bool(file) and domanda.titolo_nel_nome(file)) or (bool(radice) and domanda.titolo_nel_nome(radice))
			or (domanda.tipo == 'movie' and _in_testa_con_anno(domanda, (radice, file))))

def _anni_fuori_nel_vero(domanda, radice, file):
	"""LOTTI 403 e 410 -- il nome VERO del torrent (la cartella radice, il file scelto) porta anni fuori dai nostri (non quelli
	che sono parole del titolo, "Blade Runner 2049"). Per una fonte che regge solo per l'etichetta del provider, che non e' il
	nome del torrent, vuol dire un'altra opera."""
	return any(domanda.anni_fuori(n, senza_titolo=True) for n in (radice, file) if n)

def _radice_e_file(f):
	return ((f[0] or '').replace('\\', '/').split('/')[0], f[1] or '') if f is not None else ('', '')

def giudica_accettata(domanda, verdetto):
	"""LOTTO 410 -- (tenuta, motivo) per una fonte in cache che lo scraper ha ACCETTATO dal nome: un film accettato per la sua
	etichetta, ma col nome VERO senza il titolo e con soli anni fuori dai nostri, e' un'altra opera (la regola del 403 per i
	ripescati). "[Dodgy] Time Traveller - The Girl Who Leapt Through Time (2011)", il film dal vero del 2010, per l'etichetta DMM
	"The_Girl_Who_Leapt_Through_Time_(2006)_..._THORA". Lo stesso titolo con un altro anno resta ("Eternal.Sunshine.of.the.Spotless
	.Mind.2024.Kino.Lorber", "UP.3D.sbs.2011"): gli uploader sbagliano l'anno (idea scartata due volte). Prima gli anni
	(economico), i titoli solo se ci sono anni fuori. Lotto 413: funzione pura, la usa anche il banco (tests/banco/identita.py)."""
	esito, f, motivo = verdetto or (None, None, '')
	if domanda.tipo != 'movie' or esito is not True or f is None: return True, 'accettata dallo scraper'
	radice, file = _radice_e_file(f)
	if not _anni_fuori_nel_vero(domanda, radice, file) or _titolo_nel_vero(domanda, radice, f): return True, 'accettata dallo scraper'
	from modules.classificatore import altro_anno_dopo_titolo
	if any(altro_anno_dopo_titolo(domanda, n) for n in (radice, file) if n): return True, 'accettata dallo scraper (stesso titolo, altro anno)'
	return False, 'accettata, nome vero senza titolo e anni fuori'

def giudica_fonte(domanda, i, verdetto, affidabile, etichette=None, motivi=False):
	"""LOTTO 366 e seguenti -- (tenuta, motivo) per una fonte in cache SEGNATA dal nome (`identita_nome` False), dopo il controllo
	cache e il contenuto (SORGENTI.md). Lotto 413: funzione pura, usata da _giudica_dubbi e dal banco (tests/banco/identita.py
	la ricostruiva a mano, e ogni regola nuova andava scritta due volte). Con `motivi` le vie del titolo si calcolano tutte, per il
	rapporto; senza, la prima basta (a cascata, chi decide chiude). `affidabile`: un provider con id_affidabile ha dato l'hash;
	`etichette`: (le etichette, i file indicati) di tutte le copie dell'hash (lotto 388).

	Resta solo se il contenuto la conferma (verdetto True) E il titolo regge: per i film l'id affidabile, o il titolo nell'etichetta
	di una copia qualunque, nella cartella radice (il nome vero, lotto 385), nel file scelto o nel file indicato dal provider, o in
	testa con l'anno (lotto 386). Per gli episodi l'id non basta (Torrentio dava per Stranger Things S4E8 un pacchetto di "Sealab
	2021"), e l'episodio deve stare nel file in una forma forte: il "- 05" da solo non ribalta un no del nome."""
	from modules.classificatore import ANNO, altro_anno_dopo_titolo, anni_del_nome, etichette as letture
	esito, f, motivo = verdetto or (None, None, '')
	if esito is None: return False, 'senza elenco'
	if esito is False: return False, 'contenuto: %s' % motivo
	affidabile = affidabile and domanda.tipo == 'movie'
	radice, file = _radice_e_file(f)
	nomi, nomi_file = etichette or ([i.get('name') or ''], [i['nome_file']] if i.get('nome_file') else [])
	nomi = [x for n in nomi for x in letture(n)]   # lotto 393: le barre di un'etichetta separano titoli, non cartelle
	prove = (('id', lambda: affidabile),
			 ('titolo etichetta', lambda: any(domanda.titolo_nel_nome(n) for n in nomi)),
			 ('titolo file', lambda: bool(file) and domanda.titolo_nel_nome(file)),
			 ('titolo radice', lambda: bool(radice) and domanda.titolo_nel_nome(radice)),
			 ('in testa con anno', lambda: domanda.tipo == 'movie' and _in_testa_con_anno(domanda, (radice, file))),
			 ('titolo nome_file', lambda: any(domanda.titolo_nel_nome(n) for n in nomi_file)))
	vie = [nome for nome, prova in prove if prova()] if motivi else next(([nome] for nome, prova in prove if prova()), [])
	if not vie: return False, 'titolo assente'
	via = '+'.join(vie)
	# il titolo nel nome VERO (file scelto, radice, in testa con anno): conta per il 403 e per la parola del 405
	vero = domanda.tipo == 'movie' and _titolo_nel_vero(domanda, radice, f)
	if domanda.tipo == 'movie' and not affidabile and not vero and _anni_fuori_nel_vero(domanda, radice, file):
		# lotto 403: ripescata dalla sola etichetta del provider, che non e' il nome del torrent ("El ultimo aliento (The Last
		# Breath) (2023)", etichetta DMM "El.ultimo.aliento", per Fino all'ultimo respiro, 1960)
		return False, 'solo etichetta, anni fuori nel nome vero'
	if domanda.tipo == 'episode':
		from modules.source_utils import seas_ep_filter
		if not (f is not None and seas_ep_filter(domanda.stagione, domanda.episodio, file, absolute=domanda.assoluto, forte=True)):
			return False, 'episodio non in forma forte (%s)' % via
	if affidabile:
		# lotto 381 -- il ripescaggio per id guarda il nome VERO: il file scelto, se no la cartella radice; l'etichetta solo senza
		# elenco. Un anno fuori +-1 esclude, tranne un intervallo che lo comprende ("Saga Completa (2001-2011)")
		anni = (anni_del_nome(file) or anni_del_nome(radice)) if f is not None else ANNO.findall(i.get('name') or '')
		if anni and domanda.anni:
			a = int(domanda.anno)
			if not any(x in domanda.anni for x in anni) and not (len(anni) >= 2 and int(min(anni)) <= a <= int(max(anni))):
				return False, 'anno fuori (%s)' % via
		# lotto 405 (decisione dell'utente): la parola del titolo serve quando l'id e' l'unica prova; lotto 410: col titolo provato
		# nel nome vero no ("Up", "P": sotto le 3 lettere non si ripescavano mai per id)
		if not vero and not any(domanda.parola_del_titolo(t) for t in nomi + [radice, file]):
			return False, 'id senza parola del titolo'
	if domanda.tipo == 'movie' and any(altro_anno_dopo_titolo(domanda, n) for n in (radice, file) if n):
		# lotto 378: il titolo seguito subito da un altro anno e' un'altra opera con lo stesso titolo (The Magnificent Seven 1960
		# per I sette samurai). Non l'etichetta: per le raccolte e' il primo file visto dal provider
		return False, 'altro anno dopo il titolo (%s)' % via
	return True, via

class source:
	def __init__(self, meta, source_dict, active_debrid, debrid_service, debrid_token, internal_scrapers, prescrape_sources, progress_dialog, disabled_ext_ignored=False):
		self.monitor = xbmc_monitor()
		self.scrape_provider = 'external'
		self.progress_dialog = progress_dialog
		self.meta = meta
		self.background = self.meta.get('background', False)
		self.active_debrid = active_debrid
		self.debrid_service, self.debrid_token = debrid_service, debrid_token
		self.source_dict, self.host_dict = source_dict, []
		self.sources, self.all_internal_sources, self.processed_internal_scrapers = [], [], []
		self.processed_internal_scrapers_append = self.processed_internal_scrapers.append
		self.internal_scrapers, self.prescrape_sources = internal_scrapers, prescrape_sources
		self.internal_activated, self.internal_prescraped = len(self.internal_scrapers) > 0, len(self.prescrape_sources) > 0
		self.processed_prescrape, self.threads_completed = False, False
		self.sleep_time = 100
		# LOTTO 256 -- ZERO VUOL DIRE NESSUN TETTO. Fino a qui il tetto scadeva e si andava avanti
		# LASCIANDO INDIETRO i thread ancora vivi: non si possono uccidere (in Python non esiste), e
		# quelli continuavano a macinare dentro lo stesso interprete. Misurato il 12/09: DMM impiega
		# 50-72 s contro un tetto di 60, quindi due ricerche su tre lo abbandonavano a pochi secondi
		# dalla fine -- e la sua cpu arrivava addosso alla chiamata al debrid e alla sonda, che gira
		# subito dopo. La sonda delle 06:44 e' stata buttata cosi': quota 34%, consumo proprio 8%,
		# cioe' ferma in coda sul GIL dietro a due scraper abbandonati.
		# Con zero non si abbandona nessuno: si esce quando hanno finito DAVVERO, e le tre fasi
		# (scraping+parsing -> debrid -> sonda) tornano separate. La valvola resta l'annulla
		# dell'utente, che il ciclo controlla a ogni giro.
		self.timeout = int(get_setting('fenlight.results.timeout', '20'))
		self.senza_tetto = self.timeout <= 0
		if disabled_ext_ignored and not self.senza_tetto: self.timeout = 60
		self.sources_total = self.sources_4k = self.sources_1080p = self.sources_720p = self.sources_sd = 0
		self.final_total = self.final_4k = self.final_1080p = self.final_720p = self.final_sd = 0
		self.count_tuple = (('sources_4k', '4K', self._quality_length), ('sources_1080p', '1080p', self._quality_length), ('sources_720p', '720p', self._quality_length),
							('sources_sd', '', self._quality_length_sd), ('sources_total', '', self.quality_length_final))
		self.count_tuple_final = (('final_4k', '4K', self._quality_length), ('final_1080p', '1080p', self._quality_length), ('final_720p', '720p', self._quality_length),
									('final_sd', '', self._quality_length_sd), ('final_total', '', self.quality_length_final))

	def results(self, info):
		if not self.source_dict: return
		try:
			self._info = info
			self.media_type, self.tmdb_id, self.orig_title = info['media_type'], str(info['tmdb_id']), info['title']
			self.season, self.episode, self.total_seasons = info['season'], info['episode'], info['total_seasons']
			self.absolute = info.get('absolute')
			self.title, self.year = normalize(info['title']), info['year']
			ep_name, aliases = normalize(info['ep_name']), info['aliases']
			self.single_expiry, self.season_expiry, self.show_expiry = info['expiry_times']
			if self.media_type == 'movie':
				self.season_divider, self.show_divider = 0, 0
				self.data = {'imdb': info['imdb_id'], 'title': self.title, 'aliases': aliases, 'year': self.year,
				'debrid_service': self.debrid_service, 'debrid_token': self.debrid_token, 'preferred_language': preferred_language(), 'pref_language_country': pref_language_country(),
				'giudizio_esterno': 'TorBox' in self.active_debrid, 'director': info.get('director') or []}
			else:
				try: self.season_divider = [int(x['episode_count']) for x in self.meta['season_data'] if int(x['season_number']) == int(self.meta['season'])][0]
				except: self.season_divider = 1
				self.show_divider = int(self.meta['total_aired_eps'])
				self.data = {'imdb': info['imdb_id'], 'tvdb': info['tvdb_id'], 'tvshowtitle': self.title, 'aliases': aliases,'year': self.year,
							'title': ep_name, 'season': str(self.season), 'episode': str(self.episode), 'absolute': info.get('absolute'), 'debrid_service': self.debrid_service, 'debrid_token': self.debrid_token, 'preferred_language': preferred_language(), 'pref_language_country': pref_language_country(),
							'giudizio_esterno': 'TorBox' in self.active_debrid}
		except: return []
		return self.get_sources()

	def get_sources(self):
		def _scraperDialog():
			hide_busy_dialog()
			sleep(200)
			start_time = time.time()
			while not self.progress_dialog.iscanceled() and not self.monitor.abortRequested():
				try:
					_vivi = [x for x in self.threads if x.is_alive()]
					alive_threads = [x.getName() for x in _vivi]
					if self.internal_activated or self.internal_prescraped: alive_threads.extend(self.process_internal_results())
					line1 =  ', '.join(alive_threads).upper()
					# LOTTO 256 -- senza tetto la barra non puo' misurare il TEMPO (non c'e' un
					# traguardo), quindi misura il LAVORO: quanti provider hanno gia' finito. E'
					# anche piu' onesta -- col tetto la barra corre mentre DMM e' fermo al 90%.
					if self.senza_tetto:
						_totali = len(self.threads) or 1
						percent = ((_totali - len(_vivi)) / float(_totali)) * 100 if self.threads_completed else 0
					else:
						percent = (max((time.time() - start_time), 0)/float(self.timeout))*100
					self.progress_dialog.update_scraper(self.sources_sd, self.sources_720p, self.sources_1080p, self.sources_4k, self.sources_total, line1, percent)
					if self.threads_completed:
						len_alive_threads = len(alive_threads)
						# Finiti tutti: si esce sempre, col tetto e senza. E' la condizione buona.
						if len_alive_threads == 0: break
						# LOTTO 368 -- Knaben ultimo rimasto e gia' abbastanza sorgenti in cache: non si aspetta.
						if self._lascia_ultimo(_vivi): break
						if not self.senza_tetto and percent >= 100: break
					elif not self.senza_tetto and percent >= 100: break
					sleep(self.sleep_time)
				# 26/09: un'eccezione qui saltava anche lo sleep e il ciclo girava a vuoto (visto con test_256)
				except: sleep(self.sleep_time)
			return
		def _background():
			sleep(1500)
			# LOTTO 256 -- lo sfondo NON eredita "nessun tetto", di proposito. Qui non c'e' dialogo
			# e quindi non c'e' annulla: un'attesa senza fine non avrebbe valvola. E soprattutto non
			# serve -- lo sfondo prepara l'episodio successivo mentre si guarda, non c'e' nessuna
			# sonda dopo di lui da proteggere. Col tetto a zero si usa il valore di sempre.
			end_time = time.time() + (60 if self.senza_tetto else self.timeout)
			while time.time() < end_time:
				alive_threads = [x for x in self.threads if x.is_alive()]
				len_alive_threads = len(alive_threads)
				sleep(1000)
				if len_alive_threads <= 5: return
				if len(self.sources) >= 100 * len_alive_threads: return
		# LOTTO 364 -- con TorBox il controllo cache parte a ogni provider che finisce (scrapers/verifica_cache.py),
		# non in coda a tutti. Gli altri debrid restano come prima.
		self._verifica = None
		if 'TorBox' in self.active_debrid:
			try:
				from scrapers.verifica_cache import VerificaTorBox
				self._verifica = VerificaTorBox()
			except: self._verifica = None
		self.threads = []
		self.threads_append = self.threads.append
		self._tempi, self._lasciati_indietro = {}, []
		if self.media_type == 'movie':
			self.source_dict = [i for i in self.source_dict if i[1].hasMovies]
			Thread(target=self.process_movie_threads).start()
		else:
			self.source_dict = [i for i in self.source_dict if i[1].hasEpisodes]
			self.season_packs, self.show_packs = pack_enable_check(self.meta, self.season, self.episode)
			if self.season_packs:
				self.source_dict = [(i[0], i[1], '') for i in self.source_dict]
				pack_capable = [i for i in self.source_dict if i[1].pack_capable]
				if pack_capable:
					self.source_dict.extend([(i[0], i[1], 'Season') for i in pack_capable])
					if self.show_packs: self.source_dict.extend([(i[0], i[1], 'Show') for i in pack_capable])
					random.shuffle(self.source_dict)
			Thread(target=self.process_episode_threads).start()
		if self.background: _background()
		else: _scraperDialog()
		# LOTTO 256 -- L'INVARIANTE, CONTROLLATA INVECE CHE SPERATA. Da qui si va al debrid e poi
		# alla sonda: se qui sopravvive qualcuno, la sua cpu finisce addosso a entrambi. Col tetto a
		# zero questa riga deve dire sempre zero; con un tetto dice QUANTO si sta abbandonando, che
		# e' il numero che serve per decidere se il tetto e' tarato bene.
		try:
			_vivi = [x.getName() for x in self.threads if x.is_alive()]
			_tempi = ', '.join('%s %d' % x for x in sorted(self._tempi.items(), key=lambda x: -x[1]))
			logger('FenLight SCRAPER', 'tempi (ms): %s%s' % (_tempi or '-', (' | Knaben non aspettato (%s)' % ', '.join(self._lasciati_indietro))
																  if self._lasciati_indietro else ''))
			if _vivi:
				logger('FenLight SCRAPER', 'si prosegue con %d scraper ANCORA VIVI (%s): la loro cpu '
					   'arrivera\' addosso al debrid e alla sonda' % (len(_vivi), ', '.join(_vivi)))
			else:
				logger('FenLight SCRAPER', 'tutti gli scraper hanno finito: nessuno lasciato indietro')
		except: pass
		current_results = list(self.sources)
		if current_results: return self.process_results(current_results)
		return []

	def _cronometra(self, nome, funzione, *args):
		# Lotto 368: quanto impiega ogni provider (riga FenLight SCRAPER)
		avvio = time.time()
		try: funzione(*args)
		finally:
			try: self._tempi[nome] = int((time.time() - avvio) * 1000)
			except: pass

	def _lascia_ultimo(self, vivi):
		"""LOTTO 368 -- se gli unici ancora in corsa sono di Knaben e ci sono gia' almeno ULTIMO_BASTA sorgenti in cache (non
		segnate dal nome), la lista parte senza aspettarlo: nella prova del 26/09 Knaben e' il piu' lento (0,3-90 s per
		la stessa richiesta) e ha dato 76 sorgenti uniche su 12.161. Continua in sottofondo e scrive la cache dei
		risultati, che vale dalla ricerca dopo. Senza TorBox si contano le sorgenti."""
		try:
			if not vivi or not all(x.getName().startswith(ULTIMO_LENTO) for x in vivi): return False
			buone = set(i['hash'] for i in list(self.sources) if i.get('hash') and i.get('identita_nome') is not False)
			verifica = getattr(self, '_verifica', None)
			if verifica is not None:
				with verifica._lock: in_cache = len(buone & verifica._in_cache)
			else: in_cache = len(buone)
			if in_cache < ULTIMO_BASTA: return False
			self._lasciati_indietro = [x.getName() for x in vivi]
			return True
		except: return False

	def process_movie_threads(self):
		for i in self.source_dict:
			provider, module = i[0], i[1]
			threaded_object = Thread(target=self._cronometra, args=(provider, self.get_movie_source, provider, module), name=provider)
			threaded_object.start()
			self.threads_append(threaded_object)
		self.threads_completed = True

	def process_episode_threads(self):
		for i in self.source_dict:
			provider, module = i[0], i[1]
			try: pack_arg = i[2]
			except: pack_arg = ''
			if pack_arg: provider_display = pack_display % (i[0], i[2])
			else: provider_display = provider
			threaded_object = Thread(target=self._cronometra, args=(provider_display, self.get_episode_source, provider, module, pack_arg), name=provider_display)
			threaded_object.start()
			self.threads_append(threaded_object)
		self.threads_completed = True

	def get_movie_source(self, provider, module):
		sources, grezzi = external_cache.leggi(provider, self.media_type, self.tmdb_id, self.title, self.year, '', '')
		if sources == None:
			sources = module().sources(self.data, self.host_dict)
			# Lotto 369: si salva il risultato dello scraper, process_sources rigira alla lettura.
			external_cache.set(provider, self.media_type, self.tmdb_id, self.title, self.year, '', '', sources, self.single_expiry if sources else 1)
			sources = self.process_sources(provider, sources)
		elif grezzi: sources = self.process_sources(provider, sources)
		if sources:
			if not self.background: self.process_quality_count([i for i in sources if i.get('identita_nome') is not False])
			self.sources.extend(sources)
			self._consegna(sources)

	def _setaccio_episodi(self, sources):
		"""LOTTO 366, 26/09 -- per gli EPISODI un risultato segnato dal nome il cui nome (e il nome del file indicato dal
		provider) non ha NESSUNA parola del titolo o degli alias esce subito: niente controllo cache, niente elenco.
		Nella prova del 25/09 sera: 70 cosi', ripescato 1 ("BB.2x04.Down.mkv"). "Top Gear" cercando One Piece non si apre.
		Per i film no: raccolte dal nome generico ("Epic.Films.3", "Great.Films.1") contenevano il film giusto."""
		try:
			if not any(i.get('identita_nome') is False for i in sources): return sources
			parole_titolo = getattr(self, '_parole_titolo', None)
			if parole_titolo is None:
				from modules.classificatore import domanda_da_info, parole, incollato, VUOTE
				d = domanda_da_info(self._info)
				# lotto 413: le parole vuote del classificatore (la lista propria di qui era uguale per le parole di 3 lettere o piu')
				parole_titolo = set(w for t in d.titoli for w in parole(t) if len(w) >= 3 and w not in VUOTE)
				# lotto 387: anche la forma incollata ("ThreeBody.S01E08.2023" per Three-Body)
				parole_titolo |= set(x for x in (incollato(parole(t)) for t in d.titoli) if x)
				self._parole_titolo = parole_titolo
			if not parole_titolo: return sources
			from modules.classificatore import parole
			def ha_titolo(i): return bool(set(parole(i.get('name') or '') + parole(i.get('nome_file') or '')) & parole_titolo)
			return [i for i in sources if i.get('identita_nome') is not False or ha_titolo(i)]
		except: return sources

	def _consegna(self, sources):
		# Lotto 364: gli hash di questo provider vanno subito al controllo cache.
		verifica = getattr(self, '_verifica', None)
		if not verifica: return
		try: verifica.consegna([i['hash'] for i in sources if i.get('hash')])
		except: pass

	def get_episode_source(self, provider, module, pack):
		if pack in pack_check:
			if pack == 'Show': s_check = ''
			else: s_check = self.season
			e_check = ''
		else: s_check, e_check = self.season, self.episode
		sources, grezzi = external_cache.leggi(provider, self.media_type, self.tmdb_id, self.title, self.year, s_check, e_check)
		if sources == None:
			if pack == 'Show':
				expiry_hours = self.show_expiry
				sources = module().sources_packs(self.data, self.host_dict, search_series=True, total_seasons=self.total_seasons)
			elif pack == 'Season':
				expiry_hours = self.season_expiry
				sources = module().sources_packs(self.data, self.host_dict)
			else:
				expiry_hours = self.single_expiry
				sources = module().sources(self.data, self.host_dict)
			if not sources: expiry_hours = 1
			# Lotto 369: si salva il risultato dello scraper, process_sources rigira alla lettura.
			external_cache.set(provider, self.media_type, self.tmdb_id, self.title, self.year, s_check, e_check, sources, expiry_hours)
			sources = self.process_sources(provider, sources)
		elif grezzi: sources = self.process_sources(provider, sources)
		if sources: sources = self._setaccio_episodi(sources)
		if sources:
			if pack == 'Season': sources = [i for i in sources if not 'episode_start' in i or i['episode_start'] <= self.episode <= i['episode_end']]
			# un pacchetto segnato dal nome (lotto 366) ha last_season 0: lo giudica il contenuto, non questo filtro
			elif pack == 'Show': sources = [i for i in sources if i.get('identita_nome') is False or i['last_season'] >= self.season]
			if not self.background: self.process_quality_count([i for i in sources if i.get('identita_nome') is not False])
			self.sources.extend(sources)
			self._consegna(sources)

	def process_results(self, results):
		def _process_cache_check(provider, function):
			cached = function(hash_list, cached_hashes)
			if not self.background: self.process_quality_count_final([i for i in results if i['hash'] in cached])
			final_results.extend([dict(i, **{'cache_provider': provider if i['hash'] in cached else 'Uncached %s' % provider, 'debrid':provider}) for i in results])
			# Lotto 363: una riga per provider, non una per risultato (migliaia per ricerca, ognuna una chiamata a Kodi).
			_in_cache = sum(1 for i in results if i['hash'] in cached)
			logger('FenLight', 'DEBRID %s: %d in cache, %d no, su %d risultati' % (provider, _in_cache, len(results) - _in_cache, len(results)))
		
		def _debrid_check_dialog():
			self.progress_dialog.reset_is_cancelled()
			start_time, timeout = time.time(), 20
			while not self.progress_dialog.iscanceled() and not self.monitor.abortRequested():
				try:
					remaining_debrids = [x.getName() for x in debrid_check_threads if x.is_alive() is True]
					current_progress = max((time.time() - start_time), 0)
					line1 = ', '.join(remaining_debrids).upper()
					percent = int((current_progress/float(timeout))*100)
					self.progress_dialog.update_scraper(self.final_sd, self.final_720p, self.final_1080p, self.final_4k, self.final_total, line1, percent)
					sleep(self.sleep_time)
					if len(remaining_debrids) == 0: break
					if percent >= 100: break
				except: sleep(self.sleep_time)
		try:
			if not self.background and self.all_internal_sources: self.process_quality_count_final(self.all_internal_sources)
			final_results = []
			self._provider_hash = _provider_per_hash(results)
			self._etichette_hash = _etichette_per_hash(results)
			results = _senza_doppioni(results)
			hash_list = list(set([i['hash'] for i in results]))
			cached_hashes = query_local_cache(hash_list)
			runners = dict(debrid_runners)
			verifica = getattr(self, '_verifica', None)
			if verifica:
				copertura = self._copertura(results)
				runners['TorBox'] = ('TorBox', lambda _hash_list, _cached: verifica.attendi(_hash_list, copertura))
			debrid_check_threads = [Thread(target=_process_cache_check, args=runners[item], name=item) for item in self.active_debrid]
			[i.start() for i in debrid_check_threads]
			if self.background: [i.join() for i in debrid_check_threads]
			else: _debrid_check_dialog()
			verdetti = self._applica_contenuto(final_results)
			self._giudica_dubbi(final_results, verdetti)
			return final_results
		except: return []

	def _copertura(self, results):
		"""LOTTO 370 -- la funzione con cui il verificatore decide se aspettare un blocco lento (SORGENTI.md).

		Una sorgente in attesa e' COPERTA se in cache ce n'e' gia' una nella stessa fascia di taglia (sotto 2 GB, 2-10,
		10-30, oltre 30), di qualita' uguale o migliore (CAM < SCR < SD < 720p < 1080p < 4K: SCR e CAM sono peggio della
		SD, osservazione dell'utente del 26/09) e nella lingua preferita almeno quanto lei (lotto 414: doppiata, solo
		sottotitolata o no, la stessa risposta di sort_preferred_language): "uguale o peggiore di una che c'e' gia'", la regola
		dell'utente. Se tutte quelle in attesa sono coperte, aspettarle non aggiunge niente. I segnati dal nome (lotto
		366) non tengono ferma la lista ne' coprono: il giudizio su di loro viene dopo.

		Lotto 414: le fasce si calcolano quando il verificatore chiede (passato il margine, mentre aspetta la rete) e solo per
		gli hash che chiede, una volta ciascuno: la lingua costa piu' della parola di prima (misura: 185 nomi a ricerca in
		mediana, fino a 5.561) e qui sarebbe stata prima del controllo cache. Un errore qui lo prende il verificatore
		(aspetta, come senza copertura), non results().
		"""
		gradi = {'CAM': 0, 'SCR': 1, 'SD': 2, '720p': 3, '1080p': 4, '4K': 5}
		voci = {}
		for i in results:
			h = (i.get('hash') or '').lower()
			if h and i.get('identita_nome') is not False: voci.setdefault(h, []).append(i)
		info, fasce, lingua = getattr(self, '_info', None), {}, []
		def fascia(i):
			if not lingua:
				from modules.lingua_fonte import prepara
				lingua.append(prepara(info, preferred_language()))
			try: gb = float(i.get('size') or 0)
			except: gb = 0.0
			t = 0 if gb < 2 else 1 if gb < 10 else 2 if gb < 30 else 3
			return gradi.get(i.get('quality'), 2), t, lingua[0].livello(i.get('name') or '', i.get('nome_file')) if lingua[0] else 0
		def fasce_di(h):
			f = fasce.get(h)
			if f is None: f = fasce[h] = set(fascia(i) for i in voci.get(h, ()))
			return f
		def coperta(f, gia):
			return any(t == f[1] and q >= f[0] and liv >= f[2] for q, t, liv in gia)
		def copertura(in_attesa, in_cache):
			gia = set()
			for h in in_cache: gia |= fasce_di(h)
			return all(coperta(f, gia) for h in in_attesa for f in fasce_di(h))
		return copertura

	def _applica_contenuto(self, results):
		"""LOTTO 365 -- il contenuto decide (SORGENTI.md). Al posto di _impara_pacchetti, _senza_episodio e
		_dimensioni_vere, che valevano solo per i pacchetti di serie.

		Per ogni sorgente con un hash: il verdetto salvato per questa domanda, altrimenti il classificatore
		sull'elenco dei file (arrivato ora dal verificatore o gia' in pack_cache). False: esce (non contiene cio' che
		si cerca, o non si riproduce per intero). True: resta con la taglia del file che la riproduzione sblocchera'.
		Senza elenco: resta com'e', decide il nome. Gli elenchi si aspettano al piu' TETTO_ELENCHI secondi dopo il
		controllo cache: chi arriva dopo vale dalla ricerca successiva.
		"""
		try:
			con_hash = [i for i in results if i.get('hash')]
			if not con_hash: return {}
			from caches import pack_cache
			from modules.classificatore import domanda_da_info, classifica_tutti
			avvio = time.time()
			verifica = getattr(self, '_verifica', None)
			arrivati, in_ritardo = verifica.attendi_elenchi() if verifica else ({}, 0)
			attesa = int((time.time() - avvio) * 1000)
			domanda = domanda_da_info(self._info, (self.meta or {}).get('duration'))
			chiave = domanda.chiave(self.tmdb_id)
			hashes = set(i['hash'] for i in con_hash)
			verdetti = dict((h, (esito, (nome, (nome or '').replace('\\', '/').split('/')[-1], byte) if esito else None, 'salvato'))
							for h, (esito, nome, byte) in pack_cache.leggi_verdetti(hashes, chiave).items())
			mancano = hashes - set(verdetti)
			elenchi = dict((h, arrivati[h]) for h in mancano if h in arrivati)
			elenchi.update(pack_cache.leggi(mancano - set(elenchi)))
			nuovi = classifica_tutti(elenchi, domanda)
			pack_cache.scrivi_verdetti(chiave, nuovi)
			verdetti.update(nuovi)
			via, taglie, motivi = set(), 0, {}
			for i in con_hash:
				esito, f, motivo = verdetti.get(i['hash'], (None, None, ''))
				if esito is False:
					via.add(id(i))
					motivi[motivo] = motivi.get(motivo, 0) + 1
				elif esito and f and f[2]:
					i['size'] = round(f[2] / 1073741824.0, 2)
					i['size_label'] = '%.2f GB' % i['size']
					taglie += 1
			if via: results[:] = [i for i in results if id(i) not in via]
			self._nome_vero([i for i in con_hash if verdetti.get(i['hash'], (None,))[0]], elenchi)
			logger('FenLight CONTENUTO', '%d sorgenti con hash: %d verdetti salvati, %d classificati ora, %d senza elenco | '
				   'tolte %d (%s) | taglie vere %d | attesa elenchi %d ms, %d in ritardo'
				   % (len(con_hash), len(verdetti) - len(nuovi), len(nuovi), len(hashes) - len(verdetti), len(via),
					  ', '.join('%s %d' % (k, v) for k, v in sorted(motivi.items(), key=lambda x: -x[1])) or '-', taglie,
					  attesa, in_ritardo))
			return verdetti
		except: return {}

	def _nome_vero(self, tenuti, elenchi):
		"""LOTTO 373 -- la lista mostra il nome vero del torrent (la cartella radice dell'elenco, o il file se e' uno solo),
		non l'etichetta del provider: Comet e MediaFusion chiamano un pacchetto completo col nome del primo file visto
		("Dragon.Ball.Z.S04E17...ZER0.mkv" per "Dragon Ball Z 30th Anniversary Complete"), DMM a volte con quello di un
		altro torrent. Qualita' e lingua restano lette dall'etichetta."""
		try:
			if not tenuti: return
			from caches import pack_cache
			from modules.classificatore import nome_vero
			mancano = set(i['hash'] for i in tenuti) - set(elenchi)
			tutti = dict(elenchi)
			if mancano: tutti.update(pack_cache.leggi(mancano))
			for i in tenuti:
				vero = nome_vero(tutti.get(i['hash']))
				if vero: i['display_name'] = clean_file_name(normalize(vero.replace('html', ' ').replace('+', ' ').replace('-', ' ')))
		except: pass

	def _giudica_dubbi(self, results, verdetti):
		"""LOTTO 366 -- l'identita' si giudica dopo la cache, dove ci sono i dati (SORGENTI.md).

		Con TorBox gli scraper non scartano piu' per il NOME (titolo, anno, pacchetto): segnano `identita_nome: False`. Qui, dopo
		il controllo cache e il contenuto: le sorgenti non in cache escono tutte (regola dell'utente, 25/09); una segnata resta se
		giudica_fonte la tiene, un film accettato se giudica_accettata la tiene (lotto 413: le regole stanno li'). Senza elenco il
		verdetto non c'e': decide il nome, cioe' fuori. Senza TorBox (nessun verificatore) le segnate escono tutte: possono
		arrivare da external_cache di una ricerca fatta con TorBox.
		"""
		try:
			if not getattr(self, '_verifica', None):
				if any(i.get('identita_nome') is False for i in results):
					results[:] = [i for i in results if i.get('identita_nome') is not False]
				return
			from modules.classificatore import domanda_da_info
			domanda = domanda_da_info(self._info, (self.meta or {}).get('duration'))
			# lotto 387: su TUTTE le copie dell'hash (process_results), non solo su quella rimasta dopo i doppioni
			per_hash = getattr(self, '_provider_hash', None) or _provider_per_hash(results)
			affidabili = set(h for h, provider in per_hash.items() if provider & set(id_affidabile))
			per_hash_etichette = getattr(self, '_etichette_hash', None) or _etichette_per_hash(results)
			tenuti, non_in_cache, ripescati, via, accettate_via = [], 0, 0, 0, 0
			for i in results:
				if 'Uncached' in (i.get('cache_provider') or ''):
					non_in_cache += 1
					continue
				verdetto = (verdetti or {}).get(i.get('hash'))
				if i.get('identita_nome') is False:
					# lotto 413: la decisione in giudica_fonte (pura, la stessa del banco)
					if not giudica_fonte(domanda, i, verdetto, i.get('hash') in affidabili, per_hash_etichette.get(i.get('hash')))[0]:
						via += 1
						continue
					ripescati += 1
				elif domanda.tipo == 'movie' and not giudica_accettata(domanda, verdetto)[0]:
					accettate_via += 1
					continue
				tenuti.append(i)
			results[:] = tenuti
			logger('FenLight IDENTITA', 'fuori %d non in cache | segnati dal nome: %d ripescati dal contenuto, %d fuori | accettate, altra opera: %d'
				   % (non_in_cache, ripescati, via, accettate_via))
		except: pass

	def process_sources(self, provider, sources):
		try:
			for i in sources:
				try:
					i_get = i.get
					size, size_label, divider = 0, None, None
					if 'hash' in i:
						_hash = i_get('hash').lower()
						i['hash'] = str(_hash)
					display_name = clean_file_name(normalize(i['name'].replace('html', ' ').replace('+', ' ').replace('-', ' ')))
					if 'name_info' in i: quality, extraInfo = get_file_info(name_info=i_get('name_info'))
					else: quality, extraInfo = get_file_info(url=i_get('url'))
					try:
						size = i_get('size')
						if 'package' in i and provider not in correct_pack_sizes:
							if i_get('package') == 'season': divider = self.season_divider
							else: divider = self.show_divider
							# LOTTO 207 -- la taglia del TORRENT si conserva: la divisione qui sotto e'
							# una stima e va potuta sostituire con il dato vero quando arriva. Serve
							# anche come ripiego: pacco/numero VERO di file batte pacco/conteggio TMDb.
							i['dimensione_pacchetto'] = float(size)
							size = float(size) / divider
						size_label = '%.2f GB' % size
					except: pass
					i.update({'provider': provider, 'display_name': display_name, 'external': True, 'scrape_provider': self.scrape_provider, 'extraInfo': extraInfo,
							'quality': quality, 'size_label': size_label, 'size': round(size, 2)})
				except: pass
		except: pass
		return sources

	def process_quality_count(self, sources):
		for item in self.count_tuple: setattr(self, item[0], getattr(self, item[0]) + item[2](sources, item[1]))
	
	def process_quality_count_final(self, sources):
		for item in self.count_tuple_final: setattr(self, item[0], getattr(self, item[0]) + item[2](sources, item[1]))

	def process_internal_results(self):
		if self.internal_prescraped and not self.processed_prescrape:
			self.all_internal_sources += self.prescrape_sources
			self.process_quality_count(self.prescrape_sources)
			self.processed_prescrape = True
		for i in self.internal_scrapers:
			win_property = get_property(int_window_prop % i)
			if win_property in ('checked', '', None): continue
			try: internal_sources = json.loads(win_property)
			except: continue
			set_property(int_window_prop % i, 'checked')
			self.all_internal_sources += internal_sources
			self.processed_internal_scrapers_append(i)
			self.process_quality_count(internal_sources)
		return [i for i in self.internal_scrapers if not i in self.processed_internal_scrapers]

	def _quality_length(self, items, quality):
		return len([i for i in items if i['quality'] == quality])

	def _quality_length_sd(self, items, dummy):
		return len([i for i in items if i['quality'] in sd_check])

	def quality_length_final(self, items, dummy):
		return len(items)