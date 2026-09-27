# -*- coding: utf-8 -*-

import re
import unicodedata
from threading import Thread, Lock, Event
from time import time
from difflib import SequenceMatcher
from json import loads as jsloads
from cocoscrapers.modules import source_utils
from cocoscrapers.modules import log_utils
from cocoscrapers.modules import cleantitle
from cocoscrapers.modules import client

# Fen Light, lotto 406: il controllo del nome dei film per chi cerca per testo (Knaben, bitsearch). Era copiato nei due
# scraper: le correzioni del 26/09 e del lotto 387 erano finite solo in Knaben, e bitsearch (giu' allora) teneva "Mission
# Impossible Dead Reckoning Part One 2023" per The One (2022)
_YEAR_RE = re.compile(r'(?:19|20)\d{2}')
_VIDEO_RE = re.compile(
	r'(\.(?:mkv|mp4|avi|m2ts|ts|mov|wmv|mpg|mpeg|divx)\b|'
	r'\b(?:bluray|bdrip|brrip|web-dl|webdl|webrip|dvdrip|dvd9|dvd5|hdrip|hdtv|tvrip|remux|workprint|x264|x265|h264|h265|hevc|xvid)\b)',
	re.I)
_TITLE_MARKER_RE = re.compile(
	r'2160p|216op|4k|1080p|1o8op|108op|1o80p|720p|72op|480p|48op|'
	r'\.(?:mkv|mp4|avi|m2ts|ts|mov|wmv|mpg|mpeg|divx)\b|'
	r'\b(?:uhd|hdr|sdr|dv|dovi|bluray|blu-ray|bdrip|brrip|bdremux|web-dl|webdl|webrip|dvdrip|dvd9|dvd5|hdrip|hdtv|tvrip|remux|workprint|x264|x265|h264|h265|hevc|xvid)\b',
	re.I)
_TOKEN_RE = re.compile(r'[a-z0-9]+', re.I)
_NON_LATINO = re.compile(r'[^\W\d_\u0000-\u024F\u1E00-\u1EFF]')   # Fen Light, lotto 387: una lettera di un'altra scrittura

# Fen Light, lotto 411 (SORGENTI.md): la risposta di un servizio condivisa fra la ricerca dell'episodio e quelle dei pacchetti, al
# posto della coda di classe. La coda la riempiva solo sources(): con l'episodio gia' in external_cache (scadenze diverse da
# quelle dei pacchetti) i pacchetti aspettavano 11-12 s a vuoto, e una copia non letta passava alla ricerca dopo.
DURATA_CONDIVISA = 120     # secondi in cui una risposta vale per chi arriva dopo
ATTESA_CONDIVISA = 60      # al piu', per chi aspetta una richiesta in volo (le richieste hanno i loro timeout)
_condivise, _blocco_condivise = {}, Lock()
# Fen Light, lotto 411: il testo delle query di chi cerca per testo. Le lettere accentate si traslitterano (NFKD senza i segni, piu'
# quelle che NFKD non scompone) prima di togliere cio' che non e' [A-Za-z0-9 .-]: prima si cancellavano, "Kaçış" diventava "Ka"
_TRASLITTERA = str.maketrans({'ø': 'o', 'Ø': 'O', 'ł': 'l', 'Ł': 'L', 'ı': 'i', 'ß': 'ss', 'æ': 'ae', 'Æ': 'AE', 'œ': 'oe', 'Œ': 'OE',
							  'đ': 'd', 'Đ': 'D', 'ð': 'd', 'Ð': 'D', 'þ': 'th', 'Þ': 'Th'})
_FUORI_QUERY = re.compile(r'[^A-Za-z0-9\s\.-]+')

class BaseTorrentScraper:
	priority = 99
	pack_capable = False
	hasMovies = True
	hasEpisodes = True

	def __init__(self):
		self._reset()

	def _reset(self):
		self._results = []
		self._seen_hashes = set()
		self._blocco_visti = Lock()    # lotto 412: Knaben e bitsearch aggiungono risultati da piu' thread
		self._items = []
		self.item_totals = {'4K': 0, '1080p': 0, '720p': 0, 'SD': 0, 'SCR': 0, 'CAM': 0}
		self._start_time = time()
		self._log_attivo = None

	# ------------------------------------------------------------------ #
	# Data init helpers
	# ------------------------------------------------------------------ #

	def _get_search_titles(self):
		en_title = next((a.get('title') for a in (self.aliases or [])
						 if isinstance(a, dict) and a.get('country') == 'en'), None)
		orig_title = next((a.get('title') for a in (self.aliases or [])
						   if isinstance(a, dict) and a.get('country') == 'original'), None)
		pref_title = None
		if self._pref_language_country:
			pref_title = next((a.get('title') for a in (self.aliases or [])
							   if isinstance(a, dict) and a.get('country', '').lower() == self._pref_language_country), None)

		seen, titles = set(), []
		def _add(t):
			if t and t.strip() and t.strip().lower() not in seen:
				seen.add(t.strip().lower())
				titles.append(t.strip())

		_add(orig_title or self.title)
		_add(en_title)
		_add(pref_title)
		if not titles: _add(self.title)

		en_norm = en_title.strip().lower() if en_title else None
		self._paginate_title = next(
			(t for t in titles if t.strip().lower() == en_norm),
			titles[0] if titles else None
		)

		log_utils.log('COCOSCRAPERS', 'SEARCH_TITLES: pref_lc=%s titles=%s paginate="%s"' % (
			self._pref_language_country, titles, self._paginate_title))
		alias_debug = []
		for alias in (self.aliases or []):
			if isinstance(alias, dict):
				alias_debug.append('%s:%s' % (alias.get('country', ''), alias.get('title', '')))
			else:
				alias_debug.append(str(alias))
		log_utils.log('COCOSCRAPERS', 'ALIASES: %s' % alias_debug)
		return titles

	def _init_episode_data(self, data):
		self.giudizio_esterno = bool(data.get('giudizio_esterno'))
		self.title = data['tvshowtitle'].replace('&', 'and').replace('Special Victims Unit', 'SVU').replace('/', ' ').replace('$', 's')
		self.episode_title = data['title']
		self.hdlr = 'S%02dE%02d' % (int(data['season']), int(data['episode']))
		# Il numero assoluto (Fen Light, lotto 361): c'e' solo per le serie in numerazione TVDB. `hdlr`
		# resta la stringa delle query; per RICONOSCERE l'episodio nel nome si usa `hdlr_match`, che
		# accetta anche l'assoluto. Vedi source_utils.episodio_regex.
		self.absolute = data.get('absolute') or None
		self.hdlr_match = source_utils.episodio_regex(data['season'], data['episode'], self.absolute)
		self.year = data['year']
		self.aliases = data['aliases']
		self.season_x = data['season']
		self.season_xx = self.season_x.zfill(2)
		self.years = None
		self._pref_language_country = data.get('pref_language_country', '')
		self.search_titles = self._get_search_titles()

	def _init_movie_data(self, data):
		self.giudizio_esterno = bool(data.get('giudizio_esterno'))
		self.title = data['title'].replace('&', 'and').replace('/', ' ').replace('$', 's')
		self.episode_title = None
		self.hdlr = data['year']
		self.absolute = None
		self.hdlr_match = self.hdlr
		self.year = data['year']
		self.aliases = data['aliases']
		self.years = [str(int(self.year) - 1), str(self.year), str(int(self.year) + 1)]
		self._registi = [[t.lower() for t in _TOKEN_RE.findall(r)] for r in (data.get('director') or []) if isinstance(r, str)]
		self._titoli_testo = None      # lotto 412: i titoli per testo si preparano alla prima richiesta di questa ricerca
		self._pref_language_country = data.get('pref_language_country', '')
		self.search_titles = self._get_search_titles()

	def _init_pack_data(self, data, search_series=False, total_seasons=None, bypass_filter=False):
		# lotto 409: i parametri della ricerca dei pacchetti, che _valuta_pacchetto legge
		self._search_series, self._total_seasons, self._bypass_filter = search_series, total_seasons, bypass_filter
		self.giudizio_esterno = bool(data.get('giudizio_esterno'))
		self.title = data['tvshowtitle'].replace('&', 'and').replace('Special Victims Unit', 'SVU').replace('/', ' ').replace('$', 's')
		self.aliases = data['aliases']
		self.imdb = data['imdb']
		self.year = data['year']
		self.season_x = data['season']
		self.season_xx = self.season_x.zfill(2)
		self._pref_language_country = data.get('pref_language_country', '')
		self.search_titles = self._get_search_titles()

	def _init_filters(self):
		self.undesirables = source_utils.get_undesirables()
		self.check_foreign_audio = False

	# ------------------------------------------------------------------ #
	# Threading helper
	# ------------------------------------------------------------------ #

	def _run_threads(self, func, items):
		threads = [Thread(target=func, args=(i,)) for i in items]
		[t.start() for t in threads]
		[t.join() for t in threads]

	# ------------------------------------------------------------------ #
	# Result builders — also update item_totals
	# ------------------------------------------------------------------ #

	def _build_result(self, provider, hash, name, name_info, url, seeders, dsize, isize):
		quality, info = source_utils.get_release_quality(name_info, url)
		if isize: info.insert(0, isize)
		return {
			'provider': provider, 'source': 'torrent', 'seeders': seeders,
			'hash': hash, 'name': name, 'name_info': name_info,
			'quality': quality, 'language': 'en', 'url': url,
			'info': ' | '.join(info), 'direct': False, 'debridonly': True, 'size': dsize
		}

	def _build_pack_result(self, provider, hash, name, name_info, url, seeders, dsize, isize,
							package, episode_start=0, episode_end=0, last_season=None, search_series=False):
		quality, info = source_utils.get_release_quality(name_info, url)
		if isize: info.insert(0, isize)
		item = {
			'provider': provider, 'source': 'torrent', 'seeders': seeders,
			'hash': hash, 'name': name, 'name_info': name_info,
			'quality': quality, 'language': 'en', 'url': url,
			'info': ' | '.join(info), 'direct': False, 'debridonly': True,
			'size': dsize, 'package': package
		}
		if search_series and last_season is not None:
			item['last_season'] = last_season
		elif episode_start:
			item.update({'episode_start': episode_start, 'episode_end': episode_end})
		return item

	def _gia_visto(self, h):
		"""Fen Light, lotto 364 -- il doppione si riconosce appena letto l'hash, non dopo qualita' e info.

		_append_result lo scartava per ultimo: nel test del 25/09 DMM ha elaborato per intero 4.173 doppioni
		(titolo, info, lingua, indesiderati, qualita') prima di buttarli. Stessa chiave di _append_result."""
		return bool(h) and h in self._seen_hashes

	def _scarta_identita(self):
		"""Fen Light, lotto 366 -- il giudizio d'identita' sul NOME (titolo, anno, pacchetto) scarta o segna.

		Senza `giudizio_esterno` (Fen Light lo mette solo con TorBox attivo) scarta, come prima. Con, il risultato
		prosegue segnato `identita_nome: False`: Fen Light, dopo il controllo cache, lo tiene solo se e' in cache,
		il contenuto lo conferma e il titolo regge (SORGENTI.md). Nel test del 25/09 il nome buttava ~300 film e
		~136 episodi in cache che contenevano la cosa cercata: stagioni col nome del primo episodio, collezioni
		senza anno, titoli stranieri, pacchetti anime in assoluto. Lotto 412: il segno lo tiene chi chiama e lo passa ad
		_append_result (prima una variabile per thread)."""
		return not getattr(self, 'giudizio_esterno', False)

	def _append_result(self, result, segnato=False):
		if segnato: result['identita_nome'] = False
		h = result.get('hash')
		with self._blocco_visti:    # lotto 412: il controllo e l'aggiunta insieme
			if h and h in self._seen_hashes: return
			if h: self._seen_hashes.add(h)
			self.item_totals[result.get('quality', 'SD')] += 1
			self._results.append(result)

	# ------------------------------------------------------------------ #
	# Episode filter
	# ------------------------------------------------------------------ #

	# lotto 412: un'espressione sola (dei tre modelli di prima, "[.-]s\d{2}e\d{2}" era contenuto in "[.-]s\d{2}")
	_EPISODIO_IN_FILM = re.compile(r'[.-]s\d{2}|[.-]season[.-]?\d{1,2}')
	# lotto 410: l'ultimo gettone del nome e' spesso il gruppo ("...AAC2.0.S33D3R112", "...DDP5.1-S56"): non e' una stagione se
	# non ne ha la forma, o se e' "-S" con sole cifre in un nome che separa le parole con punti o spazi ("digimon-adventure-S01"
	# e' una stagione). Il separatore facoltativo dopo la stagione resta ("S04P02", "S01SP1")
	_CODA = re.compile(r'[.-](s\d[a-z0-9]*)$')
	_FORMA_STAGIONE = re.compile(r's\d{1,4}(?:(?:ep|e|x|v|part|p|sp|d)\d*)*(?:pilot|ova)?$')
	_ESTENSIONE = re.compile(r'\.(?:mkv|mp4|avi|m4v|ts|m2ts|wmv)$')

	def _is_episode_result(self, name):
		n = self._ESTENSIONE.sub('', name.lower()).rstrip(' )]')
		coda = self._CODA.search(n)
		if coda and (not self._FORMA_STAGIONE.match(coda.group(1))
					 or (n[coda.start()] == '-' and coda.group(1)[1:].isdigit() and re.search(r'[. ]', n[:coda.start()]))):
			n = n[:coda.start()]
		return bool(self._EPISODIO_IN_FILM.search(n))

	def _check_title_raw(self, raw_title):
		if not raw_title or raw_title.isascii(): return False
		if self.years and not any(y in raw_title for y in self.years): return False
		non_ascii = [a['title'] for a in (self.aliases or [])
		if isinstance(a, dict) and a.get('title') and not a['title'].isascii()]
		if not non_ascii: return False
		raw_lower = raw_title.lower()
		return any(alias.lower() in raw_lower for alias in non_ascii)

	# ------------------------------------------------------------------ #
	# Stats logging
	# ------------------------------------------------------------------ #

	def _log_stats(self, name, pack=False):
		label = '%s(pack)' % name if pack else name
		logged = False
		for q, count in self.item_totals.items():
			if count > 0:
				log_utils.log('#STATS - %s found %s %s' % (label, count, q))
				logged = True
		if not logged:
			log_utils.log('#STATS - %s found nothing' % label)
		log_utils.log('#STATS - %s took %.2fs' % (label, time() - self._start_time))

	_registi = ()
	_titoli_testo = None

	def _nome_scraper(self):
		return self.__class__.__module__.split('.')[-1].upper()

	def _autore_davanti(self, result_tokens, name_title):
		# 26/09: un titolo di una parola vale come ULTIMA parola solo nella forma "Autore - Titolo": dopo un trattino, o
		# dopo il nome del regista ("Akira.Kurosawa.Yojimbo"). Senza, "Con Air 1997" passava per The End of Evangelion
		# (alias "Air") e "Planet Dune" per Dune.
		token = result_tokens[-1]
		if re.search(r'[-\u2013]\W*%s\W*$' % re.escape(token), name_title.lower()): return True
		davanti = result_tokens[:-1]
		return any(davanti[-len(r):] == r for r in self._registi if r and len(davanti) >= len(r))

	def _davanti_ammesso(self, davanti, title_tokens, name_title, title_token_lists):
		# Fen Light, lotto 387: il titolo di piu' parole vale in testa, o dopo un altro titolo dell'opera ("Sen to Chihiro no
		# Kamikakushi Spirited Away"), il regista o un trattino ("Hayao Miyazaki - Spirited Away"). Prima valeva in qualunque
		# punto: "Call Me by Your Name 2017" passava per "Your Name." (2016)
		if not davanti or davanti in title_token_lists: return True
		if any(davanti[-len(r):] == r for r in self._registi if r and len(davanti) >= len(r)): return True
		return bool(re.search(r'[-\u2013]\W*' + r'\W+'.join(re.escape(t) for t in title_tokens) + r'(?![a-z0-9])', name_title.lower()))

	def _titoli_per_testo(self):
		"""Lotto 412: i titoli del controllo dei film per testo, preparati una volta per ricerca (l'oggetto vive una ricerca) invece
		che per ogni risultato: su 83.521 nomi veri il controllo costava 4,7 s, quasi tutti a rifare questa lista.
		-> (titoli puliti, liste di parole)."""
		if self._titoli_testo is not None: return self._titoli_testo
		title_list = []
		for item in source_utils.aliases_to_array(self.aliases):
			try:
				title_list.append(item.replace('&', 'and'))
			except:
				pass
		title_list.append(self.title.replace('&', 'and'))
		clean_titles = []
		title_token_lists = []
		for t in title_list:
			# Fen Light, lotto 387: un alias con lettere non latine non si confronta qui (le parole sono [a-z0-9]): "美少女战士Eternal
			# 后篇" diventava la sola parola "eternal", e per somiglianza passava "Eternals (2021)" per Sailor Moon Eternal. Lo
			# giudica Fen Light, che legge ogni scrittura
			if _NON_LATINO.search(t): continue
			clean_title = cleantitle.get(t)
			if not clean_title: continue
			clean_titles.append(clean_title)
			title_tokens = [x.lower() for x in _TOKEN_RE.findall(t.replace('&', 'and'))]
			if title_tokens: title_token_lists.append(title_tokens)
			t_lower = t.strip().lower()
			for article in ('the ', 'a ', 'an '):
				if t_lower.startswith(article):
					clean_titles.append(cleantitle.get(t[len(article):]))
					article_tokens = [x.lower() for x in _TOKEN_RE.findall(t[len(article):])]
					if article_tokens: title_token_lists.append(article_tokens)
		self._titoli_testo = (clean_titles, title_token_lists)
		return self._titoli_testo

	def _check_movie_result(self, name):
		try:
			result_years = _YEAR_RE.findall(name)
			if not result_years:
				return False, 'year missing'
			if not any(y in self.years for y in result_years):
				return False, 'year out of range'
			if not _VIDEO_RE.search(name):
				return False, 'video marker missing'

			clean_titles, title_token_lists = self._titoli_per_testo()
			name_title = _YEAR_RE.sub(' ', name.replace('&', 'and'))
			name_title = _TITLE_MARKER_RE.split(name_title, 1)[0]
			clean_result = cleantitle.get(name_title)
			result_tokens = [t.lower() for t in _TOKEN_RE.findall(name_title)]

			for title_tokens in title_token_lists:
				if len(title_tokens) == 1:
					token = title_tokens[0]
					# 26/09: un titolo di una parola vale come ULTIMA parola solo dopo un trattino ("Fritz Lang -
					# Metropolis"); senza, "Con Air 1997" passava per The End of Evangelion (alias "Air")
					if result_tokens == title_tokens or (result_tokens and result_tokens[-1] == token and self._autore_davanti(result_tokens, name_title)):
						return True, ''
					continue
				for idx in range(0, len(result_tokens) - len(title_tokens) + 1):
					if result_tokens[idx:idx + len(title_tokens)] == title_tokens and self._davanti_ammesso(result_tokens[:idx], title_tokens, name_title, title_token_lists):
						return True, ''
			if self.year in result_years and _VIDEO_RE.search(name):
				# Fen Light, lotto 387: la somiglianza e' per i refusi, fra titoli di lunghezza simile (almeno 4/5): un titolo che ne
				# contiene un altro ("Call Me by Your Name" / "Your Name") non e' un refuso
				fuzzy_titles = [t for t in clean_titles if t and len(t) >= 8 and clean_result
								and min(len(t), len(clean_result)) >= 0.8 * max(len(t), len(clean_result))]
				if not fuzzy_titles:
					return False, 'title mismatch'
				best_ratio = max(SequenceMatcher(None, t, clean_result).ratio() for t in fuzzy_titles)
				if best_ratio >= 0.62:
					log_utils.log('%s KEPT [exact year + video fuzzy title %.2f]: "%s"' % (self._nome_scraper(), best_ratio, name))
					return True, ''
				return False, 'title mismatch fuzzy=%.2f' % best_ratio
			return False, 'title mismatch'
		except:
			source_utils.scraper_error(self._nome_scraper())
			return False, 'title/year check error'

	# ------------------------------------------------------------------ #
	# Lotto 409 (SORGENTI.md): la sequenza dei controlli, una per tutti
	# ------------------------------------------------------------------ #
	# Ogni scraper aveva due cicli scritti a mano (risultati singoli e pacchetti), 14 copie che divergevano: bitsearch non
	# applicava il filtro della lingua, "episodio in una ricerca di film" c'era in tre scraper su sette, e una correzione
	# fatta in un ciclo non arrivava agli altri (lotto 406). Qui la sequenza; lo scraper chiede al servizio e traduce ogni
	# voce della risposta in un CANDIDATO: hash, name, url, seeders, dsize, isize e, se li ha, nome_file (il file indicato
	# dal provider) e raw (il titolo prima di clean_name, per gli alias non latini).

	cerca_per_testo = False     # Knaben, bitsearch: per i film il controllo di chi cerca per testo (_check_movie_result)
	salta_titolo = False        # Torrentio: l'impostazione torrentio.bypass_filter

	def _nome_provider(self):
		return self.__class__.__module__.split('.')[-1]

	@staticmethod
	def _taglia_da_byte(byte):
		"""Lotto 412. (GB, etichetta) da una taglia in byte: GB da 1 GiB in su, MB sotto, niente se non c'e'."""
		try:
			sb = int(byte or 0)
			if sb >= 1024 ** 3: return source_utils._size('%.2f GB' % (sb / 1024.0 ** 3))
			if sb > 0: return source_utils._size('%.2f MB' % (sb / 1024.0 ** 2))
		except: pass
		return 0, ''

	@staticmethod
	def _magnet(h, nome):
		return 'magnet:?xt=urn:btih:%s&dn=%s' % (h, nome)

	@staticmethod
	def _testo_query(titolo):
		"""Lotto 411. Il titolo come testo di una query: traslitterato, poi solo lettere latine, cifre, spazi, punti e trattini
		(apostrofi e "&" tolti come prima). Vuoto per un titolo con lettere di un'altra scrittura: i suoi pezzi latini non sono il
		titolo ("ドラゴンボールＺ 危険なふたり！" darebbe "Z", "美少女战士Eternal" darebbe "Eternal")."""
		if _NON_LATINO.search(titolo or ''): return ''
		t = unicodedata.normalize('NFKD', (titolo or '').translate(_TRASLITTERA))
		return _FUORI_QUERY.sub('', ''.join(c for c in t if not unicodedata.combining(c))).strip()

	def _condivisa(self, chiave, produci):
		"""Lotto 411. La risposta per `chiave` (dello stesso provider): chi arriva primo la produce, chi arriva mentre e' in volo
		la aspetta, chi arriva dopo la riusa per DURATA_CONDIVISA secondi. Una risposta vuota vale solo per chi la aspettava:
		chi arriva dopo riprova."""
		chiave = (self._nome_provider(),) + tuple(chiave)
		adesso = time()
		with _blocco_condivise:
			for k in [k for k, v in _condivise.items() if v[0].is_set() and adesso - v[2] > DURATA_CONDIVISA]: del _condivise[k]
			voce = _condivise.get(chiave)
			mia = voce is None
			if mia: voce = _condivise[chiave] = [Event(), [], adesso]
		if not mia:
			return voce[1] if voce[0].wait(ATTESA_CONDIVISA) else []
		try: voce[1] = produci() or []
		finally:
			voce[2] = time()
			with _blocco_condivise:
				if not voce[1] and _condivise.get(chiave) is voce: del _condivise[chiave]
			voce[0].set()
		return voce[1]

	def _nome_per_titolo(self, nome):
		"""Il nome come lo leggono i controlli del titolo (Torrentio toglie ".(Archie.Bunker")."""
		return nome

	def _log_voce(self, testo):
		if self._log_attivo is None: self._log_attivo = log_utils.attivo()
		if self._log_attivo: log_utils.log('%s %s' % (self._nome_scraper(), testo))

	def _valuta_tutti(self, voci, leggi, pacchetti=False):
		"""Ogni voce della risposta: `leggi` la traduce in candidato (None se non serve), poi la sequenza dei controlli.
		Un errore su una voce si registra e non ferma le altre."""
		valuta = self._valuta_pacchetto if pacchetti else self._valuta
		for voce in voci or []:
			try:
				c = leggi(voce)
				if c: valuta(c)
			except:
				source_utils.scraper_error(self._nome_scraper())

	def _nome_regge(self, c):
		"""L'identita' dal nome: il titolo (e per i film l'anno) nel nome del torrent, poi nel file indicato dal provider, poi
		negli alias non latini del titolo grezzo."""
		if self.salta_titolo: return True
		nome = self._nome_per_titolo(c['name'])
		per_testo = self.cerca_per_testo and not self.episode_title
		if per_testo: ok, motivo = self._check_movie_result(nome)
		else: ok, motivo = source_utils.check_title(self.title, self.aliases, nome, self.hdlr_match, self.year, self.years), 'title mismatch'
		if ok: return True
		if not per_testo and c.get('nome_file') and source_utils.check_title(self.title, self.aliases, c['nome_file'], self.hdlr_match, self.year, self.years):
			return True
		if c.get('raw') and self._check_title_raw(c['raw']):
			self._log_voce('KEPT [non-ASCII title]: "%s"' % c['raw'])
			return True
		self._log_voce('SKIP [%s]: "%s"' % (motivo, c['name']))
		return False

	def _valuta(self, c):
		"""Un risultato singolo (film o episodio), dal controllo piu' economico; chi decide chiude. Gli scarti d'identita'
		passano da _scarta_identita (con TorBox segnano), lingua e indesiderati scartano."""
		h, name = c.get('hash'), c.get('name')
		if self._gia_visto(h): return            # lotto 364: il doppione in testa
		if not name or not h: return
		seeders = c.get('seeders') or 0
		self._log_voce('RAW: "%s" | hash=%s | seeders=%s' % (name, h, seeders))
		if self.min_seeders > seeders:
			self._log_voce('SKIP [seeders=%s < min=%s]: "%s"' % (seeders, self.min_seeders, name))
			return
		segnato = False
		if not self._nome_regge(c):
			if self._scarta_identita(): return
			segnato = True
		if not self.episode_title and self._is_episode_result(name):
			self._log_voce('SKIP [episode in movie search]: "%s"' % name)
			if self._scarta_identita(): return
			segnato = True
		name_info = source_utils.info_from_name(name, self.title, self.year, self.hdlr, self.episode_title)
		if self._preferenze_scartano(name, name_info): return
		risultato = self._build_result(self._nome_provider(), h, name, name_info, c['url'], seeders, c.get('dsize') or 0, c.get('isize') or '')
		if c.get('nome_file'): risultato['nome_file'] = c['nome_file']   # lotto 366: per ripescare per titolo un nome dubbio
		self._log_voce('KEPT: "%s" | hash=%s' % (name, h))
		self._append_result(risultato, segnato)

	def _valuta_pacchetto(self, c):
		"""Un pacchetto di stagione (search_series falso) o di serie."""
		h, name = c.get('hash'), c.get('name')
		if self._gia_visto(h): return
		if not name or not h: return
		seeders = c.get('seeders') or 0
		self._log_voce('RAW (pack): "%s" | hash=%s | seeders=%s' % (name, h, seeders))
		if self.min_seeders > seeders:
			self._log_voce('SKIP [seeders=%s < min=%s]: "%s"' % (seeders, self.min_seeders, name))
			return
		episode_start, episode_end, last_season, segnato = 0, 0, None, False
		nome = self._nome_per_titolo(name)
		if not self._search_series:
			if not self._bypass_filter:
				valid, episode_start, episode_end = source_utils.filter_season_pack(self.title, self.aliases, self.year, self.season_x, nome)
				if not valid:
					self._log_voce('SKIP [filter_season_pack]: "%s"' % name)
					if self._scarta_identita(): return
					segnato = True
			package = 'season'
		else:
			if not self._bypass_filter:
				valid, last_season = source_utils.filter_show_pack(self.title, self.aliases, self.imdb, self.year, self.season_x, nome, self._total_seasons)
				if not valid:
					self._log_voce('SKIP [filter_show_pack]: "%s"' % name)
					if self._scarta_identita(): return
					segnato = True
			else: last_season = self._total_seasons
			package = 'show'
		name_info = source_utils.info_from_name(name, self.title, self.year, season=self.season_x, pack=package)
		if self._preferenze_scartano(name, name_info): return
		self._log_voce('KEPT (pack=%s): "%s" | hash=%s' % (package, name, h))
		self._append_result(self._build_pack_result(self._nome_provider(), h, name, name_info, c['url'], seeders, c.get('dsize') or 0,
													c.get('isize') or '', package, episode_start, episode_end, last_season, self._search_series), segnato)

	def _preferenze_scartano(self, name, name_info):
		"""Le preferenze dell'utente (lingua dell'audio, indesiderati) scartano sempre: non sono un giudizio d'identita'."""
		if source_utils.remove_lang(name_info, self.check_foreign_audio):
			self._log_voce('SKIP [language filter]: "%s"' % name)
			return True
		if self.undesirables and source_utils.remove_undesirables(name_info, self.undesirables):
			self._log_voce('SKIP [undesirable tag]: "%s"' % name)
			return True
		return False


class BaseStremioScraper(BaseTorrentScraper):
	"""Fen Light, lotto 412: Torrentio, MediaFusion, Comet e ICV sono addon Stremio (/stream/<tipo>/<id>.json) e avevano quattro
	copie di sources/sources_packs. Lo scraper dice la base dell'URL (_base: None se non e' configurato), come legge una voce
	(_leggi) e, per Torrentio, il bypass dei pacchetti. La risposta dell'episodio vale anche per i suoi pacchetti (_condivisa,
	lotto 411); la riga "query" porta solo il percorso (lotto 411: dopo la base c'e' userdata)."""
	pack_capable = True
	min_seeders = 0
	movieSearch_link = '/stream/movie/%s.json'
	tvSearch_link = '/stream/series/%s:%s:%s.json'

	def _base(self):
		raise NotImplementedError

	def _bypass_pacchetti(self, bypass_filter):
		return bypass_filter

	@staticmethod
	def _scarica(url):
		try: return jsloads(client.request(url, timeout=10))['streams']
		except: return []

	def _risposta(self, percorso):
		url = self._base() + percorso
		return self._condivisa((url,), lambda: self._scarica(url))

	def sources(self, data, hostDict):
		self._reset()
		nome = self._nome_scraper()
		if not data: return self._results
		if not self._base():
			log_utils.log('%s: no userdata configured, skipping' % nome)
			return self._results
		files = []
		try:
			if 'tvshowtitle' in data:
				self._init_episode_data(data)
				percorso = self.tvSearch_link % (data['imdb'], self.season_x, data['episode'])
			else:
				self._init_movie_data(data)
				percorso = self.movieSearch_link % data['imdb']
			self._init_filters()
			log_utils.log('%s query: %s' % (nome, percorso))
			files = self._risposta(percorso)
		except:
			source_utils.scraper_error(nome)
		log_utils.log('%s: %s raw results for "%s"' % (nome, len(files), getattr(self, 'title', '')))
		self._valuta_tutti(files, self._leggi)
		self._log_stats(nome)
		return self._results

	def sources_packs(self, data, hostDict, search_series=False, total_seasons=None, bypass_filter=False):
		self._reset()
		nome = self._nome_scraper()
		if not data: return self._results
		if not self._base():
			log_utils.log('%s: no userdata configured, skipping' % nome)
			return self._results
		try:
			self._init_pack_data(data, search_series, total_seasons, self._bypass_pacchetti(bypass_filter))
			self._init_filters()
			# lotto 411: la stessa risposta della ricerca dell'episodio, o chiesta qui se l'episodio era gia' in cache
			files = self._risposta(self.tvSearch_link % (data['imdb'], self.season_x, data['episode']))
		except:
			source_utils.scraper_error(nome)
			self._log_stats(nome, pack=True)
			return self._results
		log_utils.log('%s packs: %s raw results for "%s"' % (nome, len(files), self.title))
		self._valuta_tutti(files, self._leggi, pacchetti=True)
		self._log_stats(nome, pack=True)
		return self._results


class BaseTestoScraper(BaseTorrentScraper):
	"""Fen Light, lotto 412: Knaben e bitsearch cercano per testo, con le stesse query (i titoli di ricerca, lotto 411 per il testo)
	e un thread per query; ognuno dice come chiede una query (_fetch_hits) e come legge una voce (_leggi). I film con l'anno solo
	per bitsearch (lotto 408, misurato li'): `anno_nei_film`."""
	pack_capable = True
	cerca_per_testo = True
	min_seeders = 0
	anno_nei_film = False

	def _fetch_hits(self, query):
		raise NotImplementedError

	def _una_query(self, query, pacchetti=False):
		self._valuta_tutti(self._fetch_hits(query), self._leggi, pacchetti=pacchetti)

	def sources(self, data, hostDict):
		self._reset()
		nome = self._nome_scraper()
		if not data: return self._results
		try:
			is_tv = 'tvshowtitle' in data
			if is_tv: self._init_episode_data(data)
			else: self._init_movie_data(data)
			self._init_filters()
			queries = []
			for st in self.search_titles:
				testo = self._testo_query(st)
				if not testo: continue
				queries.append('%s %s' % (testo, self.hdlr) if is_tv or self.anno_nei_film else testo)
				# Le release anime numerano in assoluto ("One Piece - 1178"): cercando solo S23E23 non si trovano. Vedi
				# source_utils.episodio_regex.
				if is_tv and self.absolute: queries.append('%s %s' % (testo, self.absolute))
			queries = list(dict.fromkeys(queries))
			log_utils.log('%s queries: %s' % (nome, queries))
		except:
			source_utils.scraper_error(nome)
			return self._results
		self._run_threads(self._una_query, queries)
		self._log_stats(nome)
		return self._results

	def sources_packs(self, data, hostDict, search_series=False, total_seasons=None, bypass_filter=False):
		self._reset()
		nome = self._nome_scraper()
		if not data: return self._results
		try:
			self._init_pack_data(data, search_series, total_seasons, bypass_filter)
			self._init_filters()
			queries = []
			for st in self.search_titles:
				testo = self._testo_query(st)
				if not testo: continue
				if search_series: queries += ['%s Season' % testo, '%s Complete' % testo]
				else: queries += ['%s S%s' % (testo, self.season_xx), '%s Season %s' % (testo, self.season_x)]
			queries = list(dict.fromkeys(queries))
			log_utils.log('%s pack queries: %s' % (nome, queries))
		except:
			source_utils.scraper_error(nome)
			return self._results
		self._run_threads(lambda q: self._una_query(q, pacchetti=True), queries)
		self._log_stats(nome, pack=True)
		return self._results
