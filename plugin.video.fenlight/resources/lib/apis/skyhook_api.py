# -*- coding: utf-8 -*-
from caches.meta_cache import meta_cache
from modules.kodi_utils import make_session

SKYHOOK_URL = 'https://skyhook.sonarr.tv/v1/tvdb/shows/en/%s'
EXPIRY_7_DAYS = 168
invalid_tvdb = ('', 'None', None, 0, '0')
finished_statuses = ('Ended', 'Canceled')

# Session pigra (lotto 51 bis): era `session = make_session('https://skyhook.sonarr.tv')` a livello di modulo, e make_session()
# fa `import requests` al suo interno -- quindi ogni modulo che importava questo file
# caricava l'albero di requests SENZA nessuna istruzione `import requests` visibile.
# E' il motivo per cui la prima correzione non aveva prodotto alcun guadagno misurabile.
_session = [None]

def _get_session():
	if _session[0] is None: _session[0] = make_session('https://skyhook.sonarr.tv')
	return _session[0]

def _fetch_raw(tvdb_id):
	cache_key = 'skyhook_raw_%s' % tvdb_id
	data = meta_cache.get_function(cache_key)
	if data: return data
	try:
		response = _get_session().get(SKYHOOK_URL % tvdb_id, timeout=15)
		if response.status_code != 200: return None
		data = response.json()
		meta_cache.set_function(cache_key, data, expiration=EXPIRY_7_DAYS)
		return data
	except: return None

def stagioni_da_skyhook(data, tmdb_season_data, oggi):
	"""Le stagioni nella forma che usa il resto del codice. Pura: `data` e' il payload gia' letto.

	Due correzioni del lotto 147 rispetto alla versione precedente.

	1. `episode_count` conta SOLO GLI EPISODI GIA' USCITI. Prima contava tutto, e quel numero diventa
	   `total_aired_eps` in tvshow_meta -- il denominatore dei badge e di get_watched_status_tvshow.
	   Per un anime in corso il denominatore era gonfio e la serie non risultava mai completata. Il
	   percorso TMDb quel numero lo calcola con cura (usa `last_episode_to_air`); il percorso skyhook
	   lo sostituiva con "tutti gli episodi conosciuti", cioe' regrediva.
	2. La data della stagione e' quella del PRIMO EPISODIO PER NUMERO, non del primo elemento
	   dell'array. L'ordine di `episodes` non e' promesso da nessuno, e nel payload di Hunter x Hunter
	   la stagione 0 viene prima della 1.

	`poster_path` esce misto di proposito: da TMDb e' un percorso (`/x.jpg`), da skyhook una URL
	intera. Chi disegna lo sa gia' -- vedi `poster_path.startswith('http')` in indexers/seasons.py.
	"""
	try:
		tutti = data.get('episodes') or []
		poster_tmdb = {x['season_number']: x.get('poster_path') for x in tmdb_season_data if x.get('poster_path')} if tmdb_season_data else {}
		elenco = []
		for s in data.get('seasons') or []:
			numero = s['seasonNumber']
			episodi = [e for e in tutti if e.get('seasonNumber') == numero]
			usciti = [e for e in episodi if _uscito(e.get('airDate'), oggi)]
			poster = poster_tmdb.get(numero) or next((i['url'] for i in s.get('images', []) if i.get('coverType') == 'Poster'), None)
			primo = min(episodi, key=lambda e: e.get('episodeNumber') or 0) if episodi else None
			elenco.append({
				'season_number': numero,
				'episode_count': len(usciti),
				'poster_path': poster,
				'air_date': primo.get('airDate', '') if primo else '',
				'name': s.get('name', None),
				'overview': '',
				'id': numero
			})
		elenco.sort(key=lambda x: x['season_number'])
		return elenco or None
	except: return None

def get_skyhook_season_data(tvdb_id, tmdb_season_data=None, oggi=None):
	if tvdb_id in invalid_tvdb: return None
	data = _fetch_raw(tvdb_id)
	if not data: return None
	if oggi is None:
		from datetime import date as _date
		oggi = _date.today().isoformat()
	return stagioni_da_skyhook(data, tmdb_season_data, oggi)

def get_skyhook_episodes(tvdb_id, season, meta):
	if tvdb_id in invalid_tvdb: return None
	data = _fetch_raw(tvdb_id)
	if not data: return None
	try:
		season = int(season)
		finished = meta.get('status', '') in finished_statuses
		total_seasons = meta.get('total_seasons', 1)
		if season == 1: season_type = 'premiere_finale' if (total_seasons == 1 and finished) else 'premiere'
		else: season_type = 'finale' if (total_seasons == season and finished) else ''
		raw_eps = sorted([e for e in data.get('episodes', []) if e.get('seasonNumber') == season],
						 key=lambda x: x.get('episodeNumber', 0))
		if not raw_eps: return None
		result = []
		midseason_premiere = False
		for ep in raw_eps:
			ep_num = ep.get('episodeNumber', 0)
			finale_type = ep.get('finaleType', '')
			if ep_num == 1:
				episode_type = 'series_premiere' if 'premiere' in season_type else 'season_premiere'
			elif midseason_premiere:
				episode_type, midseason_premiere = 'mid_season_premiere', False
			elif finale_type == 'series':
				episode_type = 'series_finale'
			elif finale_type == 'season':
				episode_type = 'series_finale' if 'finale' in season_type else 'season_finale'
			elif finale_type == 'mid_season':
				episode_type, midseason_premiere = 'mid_season_finale', True
			else:
				episode_type = ''
			runtime = ep.get('runtime')
			result.append({
				'writer': [], 'director': [], 'mediatype': 'episode',
				'episode_type': episode_type,
				'episode_id': ep.get('tvdbId'),
				'title': ep.get('title', ''),
				'plot': ep.get('overview') or '',
				'duration': int(runtime) * 60 if runtime else 30 * 60,
				'premiered': ep.get('airDate', ''),
				'season': season,
				'episode': ep_num,
				'rating': 0,
				'votes': 0,
				'thumb': ep.get('image'),
				'guest_stars': []
			})
		return result or None
	except: return None

def _uscito(data, oggi):
	# Senza data non si puo' concludere "non e' ancora uscito": si tratta come uscito, che e' la
	# lettura prudente in entrambi gli usi (un episodio entra nella giuntura, e uno senza
	# corrispondenza viene CONTATO fra gli esclusi invece di sparire dal conto).
	if not data: return True
	try: return str(data)[:10] <= oggi
	except: return True

def costruisci_mappa_episodi(episodi_tvdb, episodi_trakt, oggi):
	"""Appaia gli episodi TVDB e Trakt per IDENTITA' -- l'id TVDB -- invece che per posizione.

	Ogni episodio e' una tupla `(stagione, numero, id_tvdb, data)`. Gli adattatori che le costruiscono
	stanno dai chiamanti: qui non si sa da dove arrivino, e la funzione resta pura e provabile.

	Perche' l'id e non la posizione: appaiare due elenchi contando le posizioni assume che contengano
	le stesse cose nello stesso ordine. Basta un episodio doppio, uno speciale contato da una parte
	sola o una stagione ridivisa, e l'allineamento salta da li' in avanti -- e' esattamente il difetto
	che questo lotto chiude. L'id TVDB invece e' la STESSA cosa da entrambe le parti: skyhook lo
	espone come `tvdbId`, Trakt come `ids.tvdb`.

	Torna un dizionario con tre voci, perche' gli esiti sono TRE e non due:

	  'mappa'          {(s,e) TVDB: (s,e) Trakt}  le coppie appaiate che si numerano DIVERSAMENTE.
	                   Chi non c'e' e non e' fra gli esclusi si traduce con l'identita'.
	  'esclusi_tvdb'   {(s,e) TVDB}  esistono da noi e non su Trakt: NON si traducono e NON si
	                   mandano. L'episodio resta visibile e riproducibile -- si esclude la
	                   traduzione, non l'episodio.
	  'esclusi_trakt'  {(s,e) Trakt}  esistono su Trakt e non da noi: nessuna riga locale e'
	                   possibile. La loro CARDINALITA' e' lo scarto del lotto 142, che cosi' smette
	                   di essere un numero misurato dopo un rebuild e diventa un numero calcolato
	                   prima di scaricare qualunque cosa.

	Le tre regole, misurate su 29 anime e 5941 episodi (vedi OTTIMIZZAZIONI.md):

	1. LA STAGIONE 0 E' FUORI. TVDB e Trakt non concordano sugli speciali in nessuna delle due
	   direzioni (525 contro 324, agganciati 275): la stagione 0 non e' un sistema di coordinate
	   condiviso. Escluderla toglie la stragrande maggioranza dei casi limite.
	2. GLI EPISODI NON ANCORA USCITI NON CONTANO COME SCARTO. Entrambi i cataloghi li elencano
	   (l'ipotesi contraria e' stata verificata e smentita), quindi non si escludono dalla giuntura --
	   se si agganciano, tanto meglio. Ma un episodio non uscito non puo' essere stato visto, quindi
	   non puo' mancare dal nostro conto: contarlo fra gli esclusi gonfierebbe lo scarto.
	3. L'IDENTITA' E' LECITA SOLO SE LA COPPIA E' LIBERA DA ENTRAMBE LE PARTI -- cioe' esiste
	   dall'altra parte e nessuna delle due e' gia' appaiata con qualcun altro. Non basta "esiste":
	   e' la liberta' reciproca a garantire che due episodi non finiscano sulla stessa riga. Sul corpus anime questo ramo non si prende mai -- tutti i residui puntano a
	   coppie che su Trakt non esistono -- ma nella popolazione generale si prende, ed e' la
	   formulazione che resta corretta in entrambi i casi. Attenzione: "la mappa e' identica" NON
	   basta come criterio, ci sono serie con mappa identita' al 100% i cui residui puntano nel vuoto.
	"""
	def _per_coppia(righe):
		fuori = {}
		for riga in righe or ():
			try: stagione, numero, id_tvdb, data = riga[0], riga[1], riga[2], riga[3]
			except: continue
			try: stagione, numero = int(stagione), int(numero)
			except: continue
			if stagione <= 0: continue  # regola 1
			fuori[(stagione, numero)] = (id_tvdb or None, data or None)
		return fuori
	tvdb, trakt = _per_coppia(episodi_tvdb), _per_coppia(episodi_trakt)
	per_id = {}
	for coppia in sorted(trakt):
		ident = trakt[coppia][0]
		# Il PRIMO vince, e l'ordine e' deterministico: un id ripetuto e' un dato sporco, e fra due
		# comportamenti sbagliati e' meglio quello uguale su tutti i dispositivi.
		if ident is not None and ident not in per_id: per_id[ident] = coppia
	mappa, presi_tvdb, presi_trakt = {}, set(), set()
	for coppia in sorted(tvdb):
		ident = tvdb[coppia][0]
		if ident is None: continue
		altra = per_id.get(ident)
		if altra is None or altra in presi_trakt: continue
		presi_tvdb.add(coppia)
		presi_trakt.add(altra)
		if coppia != altra: mappa[coppia] = altra
	liberi_tvdb, liberi_trakt = set(tvdb) - presi_tvdb, set(trakt) - presi_trakt
	# REGOLA 3, e la sua parte non ovvia. La prima stesura sottraeva anche le coordinate gia'
	# impegnate da una traduzione vera (`- (set(mappa) | set(mappa.values()))`), per paura della
	# collisione che con INSERT OR REPLACE scarta un episodio in silenzio. La verifica in rosso ha
	# mostrato che quella sottrazione non toglie MAI niente, ed e' giusto cosi': un elemento
	# dell'intersezione e' libero da entrambe le parti, quindi non e' ne' una chiave della mappa (che
	# sta fra le appaiate TVDB) ne' un suo valore (che sta fra le appaiate Trakt).
	# E' l'intersezione stessa a impedire la collisione. Se un giorno la si allentasse a "esiste
	# dall'altra parte" senza il "ed e' libera", due episodi Trakt finirebbero sulla stessa riga
	# locale: vedi il caso G di tests/test_145.py, che prova la PROPRIETA' e non la formula.
	identita = liberi_tvdb & liberi_trakt
	return {
		'mappa': mappa,
		'esclusi_tvdb': liberi_tvdb - identita,
		'esclusi_trakt': set(c for c in (liberi_trakt - identita) if _uscito(trakt[c][1], oggi)),  # regola 2
	}

def episodi_per_giuntura(tvdb_id):
	"""Gli episodi della serie su TVDB nella forma `(stagione, numero, id_tvdb, data)`.

	Sostituisce get_tvdb_to_tmdb_map, che appaiava per posizione e costruiva il lato TMDb come
	`range(1, episode_count+1)` -- cioe' lo inventava. Vedi il lotto 145.
	Qui non si mappa niente: si consegna solo l'elenco. L'appaiamento lo fa
	costruisci_mappa_episodi, che e' pura e provata.
	"""
	if tvdb_id in invalid_tvdb: return None
	data = _fetch_raw(tvdb_id)
	if not data: return None
	try:
		righe = data.get('episodes') or []
		return [(e.get('seasonNumber'), e.get('episodeNumber'), e.get('tvdbId'), e.get('airDate')) for e in righe] or None
	except: return None
