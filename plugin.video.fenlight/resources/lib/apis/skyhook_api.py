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
		# 404 e' una risposta: skyhook non ha questa serie. {} e non None, perche' chi deve distinguere
		# "non c'e'" da "non ha risposto" (episodi_per_giuntura) possa farlo; per tutti gli altri {} e None
		# sono ugualmente falsi.
		if response.status_code == 404: return {}
		if response.status_code != 200: return None
		data = response.json()
		meta_cache.set_function(cache_key, data, expiration=EXPIRY_7_DAYS)
		return data
	except: return None

def stagioni_da_skyhook(data, tmdb_season_data, oggi, nascosti=None):
	"""Le stagioni nella forma che usa il resto del codice. Pura: `data` e' il payload gia' letto.

	`nascosti` sono gli episodi TVDB senza corrispondente su TMDb (gli `esclusi_tvdb` della giuntura).
	Dal lotto 357 non si mostrano e non si contano, e una stagione che resta senza episodi sparisce:
	e' cosi' che escono le stagioni delle serie costola (Pokemon S20 = Orizzonti), gli speciali usciti
	come film e le stagioni annunciate che TVDB elenca con un segnaposto senza data ne' titolo.

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
		nascosti = nascosti or ()
		tutti = [e for e in data.get('episodes') or [] if (e.get('seasonNumber'), e.get('episodeNumber')) not in nascosti]
		poster_tmdb = {x['season_number']: x.get('poster_path') for x in tmdb_season_data if x.get('poster_path')} if tmdb_season_data else {}
		elenco = []
		for s in data.get('seasons') or []:
			numero = s['seasonNumber']
			episodi = [e for e in tutti if e.get('seasonNumber') == numero]
			if not episodi: continue
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

def get_skyhook_season_data(tvdb_id, tmdb_season_data=None, oggi=None, nascosti=None):
	if tvdb_id in invalid_tvdb: return None
	data = _fetch_raw(tvdb_id)
	if not data: return None
	if oggi is None:
		from datetime import date as _date
		oggi = _date.today().isoformat()
	return stagioni_da_skyhook(data, tmdb_season_data, oggi, nascosti)

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

	Ogni episodio e' una tupla `(stagione, numero, id_tvdb, data[, assoluto])`: l'assoluto c'e' solo dal
	lato TVDB. Gli adattatori che le costruiscono stanno dai chiamanti: qui non si sa da dove arrivino,
	e la funzione resta pura e provabile.

	Perche' l'id e non la posizione: appaiare due elenchi contando le posizioni assume che contengano
	le stesse cose nello stesso ordine. Basta un episodio doppio, uno speciale contato da una parte
	sola o una stagione ridivisa, e l'allineamento salta da li' in avanti (lotto 145). L'id TVDB invece
	e' la STESSA cosa da entrambe le parti: skyhook lo espone come `tvdbId`, Trakt come `ids.tvdb`.

	Torna un dizionario con quattro voci:

	  'mappa'          {(s,e) TVDB: (s,e) Trakt}  le coppie appaiate che si numerano DIVERSAMENTE.
	                   Chi non c'e' e non e' fra gli esclusi si traduce con lo stesso numero.
	  'esclusi_tvdb'   {(s,e) TVDB}  senza corrispondente su TMDb: NON SI MOSTRANO (lotto 357; prima
	                   restavano visibili e solo non si traducevano). TMDb e' il fornitore dei metadati:
	                   un episodio che non ha non avrebbe immagini, titolo ne' date da mostrare.
	  'esclusi_trakt'  {(s,e) Trakt}  esistono su Trakt e non da noi: nessuna riga locale e' possibile.
	                   La loro CARDINALITA' e' lo scarto del lotto 142.
	  'frontiera'      True se fra gli esclusi TVDB c'e' un episodio uscito negli ultimi 30 giorni: e'
	                   il segno di un collegamento che i cataloghi non hanno ancora fatto, e chi chiama
	                   deve ricontrollare presto invece di aspettare la scadenza normale.

	Le regole, nell'ordine in cui si applicano. Numeri e casi in ANIME.md.

	1. AGGANCIO PER ID, IN TUTTE LE STAGIONI. L'id e' un'identita' e non dipende dalle coordinate, quindi
	   vale anche per la stagione 0 e fra stagioni diverse: Dragon Ball Kai TVDB S1E98 e' TMDb S0E1.
	   Fino al lotto 357 la stagione 0 restava fuori anche da qui, e quegli episodi si perdevano.
	2b. CONTRADDIZIONE DI TITOLO (lotto 384), solo stagioni > 0, applicata PRIMA della regola 1. L'id che TMDb dichiara puo'
	   essere sbagliato: Pokemon TMDb 1x65 "Holiday Hi-Jynx" (05/10/1998) porta l'id di TVDB 1x69, mentre titolo e data sono
	   quelli di TVDB 1x65; Full Metal Panic! Fumoffu S2 e' scalato di uno per l'OVA che TMDb tiene nella stagione. Se i due
	   titoli agganciati per id NON si somigliano e allo stesso numero l'altra parte ha un titolo QUASI IDENTICO, l'episodio
	   prende quel numero, riservato prima degli agganci per id: chi ci puntava per id resta libero e la regola 3 lo rimette
	   al suo numero. Il titolo da solo non decide mai (il 6% dei titoli giusti e' tradotto in modo diverso, collaudo del
	   26/09 su 11.318 episodi): serve la contraddizione da una parte e la conferma dall'altra.
	2. VETO PER CONTRADDIZIONE, solo stagioni > 0. Se dei due episodi agganciati uno e' uscito e l'altro
	   no, a piu' di un giorno di distanza, non sono lo stesso episodio: l'aggancio si rifiuta ed
	   entrambi tornano liberi. Battle Through the Heavens: Trakt (5,210), uscito il 12/09, porta l'id
	   che su TVDB e' (5,216), in uscita il 25/10. Non e' una soglia sulle date -- il 6% degli agganci
	   giusti ha date diverse di oltre un giorno -- ma una contraddizione: sulle coppie recenti delle
	   stagioni regolari del corpus lo scarto oltre il giorno c'e' SOLO negli agganci sbagliati di BTTH.
	   La stagione 0 resta fuori perche' le sue date sono le meno affidabili: Re:ZERO S0E67-70, aggancio
	   giusto, 399 giorni fra le due date (una replica).
	3. STESSO NUMERO LECITO SE LA COPPIA E' LIBERA DA ENTRAMBE LE PARTI, solo stagioni > 0. La stagione 0
	   non e' un sistema di coordinate condiviso (525 speciali TVDB contro 324 Trakt, 04/09). E' la
	   liberta' reciproca a garantire che due episodi non finiscano sulla stessa riga: un elemento
	   dell'intersezione non e' ne' chiave ne' valore della mappa (vedi il caso G di tests/test_145.py,
	   che prova la PROPRIETA' e non la formula).
	4. SECONDA CHIAVE, IL NUMERO ASSOLUTO, SOLO SE LA SERIE LA CONVALIDA. Vale se su TUTTE le coppie
	   agganciate per id (stagioni > 0 da entrambe le parti) l'assoluto TVDB coincide con la posizione
	   dell'episodio nella numerazione continua di TMDb; e per ogni coppia nuova le due date devono
	   coincidere entro un giorno. Detective Conan: S34E21.. (TVDB) e S1E1207.. (TMDb) non erano
	   collegati da nessuno dei due cataloghi, ma la serie conferma l'assoluto su 1206 agganci su 1206.
	   E' un'euristica sorvegliata, non un'identita': per questo si convalida da sola e dove la
	   convalida non passa non si applica (Battle Through the Heavens: 12 su 267).
	5. TUTTO IL RESTO E' "NESSUNA CORRISPONDENZA". Gli episodi Trakt non ancora usciti non contano come
	   scarto: non possono essere stati visti, quindi non possono mancare dal nostro conto.
	"""
	from datetime import date, timedelta
	def _per_coppia(righe):
		fuori = {}
		for riga in righe or ():
			try: stagione, numero, id_tvdb, data = riga[0], riga[1], riga[2], riga[3]
			except: continue
			try: stagione, numero = int(stagione), int(numero)
			except: continue
			if stagione < 0: continue
			try: assoluto = int(riga[4]) if len(riga) > 4 and riga[4] else None
			except: assoluto = None
			titolo = riga[6] if len(riga) > 6 else None      # lotto 384: il titolo inglese, per il veto di titolo
			fuori[(stagione, numero)] = (id_tvdb or None, data or None, assoluto, titolo or None)
		return fuori
	def _giorno(data):
		try: return date.fromisoformat(str(data)[:10])
		except: return None
	def _contraddizione(data_tvdb, data_trakt):
		# Uno uscito e l'altro no, a piu' di un giorno di distanza. Il giorno di tolleranza e' il fuso:
		# TVDB da' la data giapponese, Trakt l'istante UTC, e il giorno dell'uscita i due possono
		# cadere a cavallo di `oggi` pur essendo lo stesso episodio (649 coppie recenti su 663 hanno
		# 0-1 giorni di scarto).
		g1, g2 = _giorno(data_tvdb), _giorno(data_trakt)
		if g1 is None or g2 is None or abs((g1 - g2).days) <= 1: return False
		return _uscito(data_tvdb, oggi) != _uscito(data_trakt, oggi)
	def _parole_titolo(t):
		import re, unicodedata
		return re.sub(r'[^a-z0-9 ]', ' ', unicodedata.normalize('NFKD', t or '').encode('ascii', 'ignore').decode().lower().replace('&', ' and ')).split()
	def _somiglianza(a, b):
		# 0..1 fra due titoli di episodio, None se uno manca o e' generico ("Episode 12"): il massimo fra la somiglianza dei
		# caratteri e la quota di parole in comune sul titolo piu' corto (lotto 384)
		import re, difflib
		pa, pb = _parole_titolo(a), _parole_titolo(b)
		generico = re.compile(r'^(?:episode|episodio|ep|tba|tbd|untitled)?\s*\d*$')
		if not pa or not pb or generico.match(' '.join(pa)) or generico.match(' '.join(pb)): return None
		if pa == pb: return 1.0
		comuni = len(set(pa) & set(pb)) / float(min(len(set(pa)), len(set(pb))))
		somiglianza = max(difflib.SequenceMatcher(None, ' '.join(pa), ' '.join(pb)).ratio(), comuni)
		# i numeri dicono QUALE parte: "A Goddess Comes to Japan (Part 1)" non e' "(Part 2)"
		if set(x for x in pa if x.isdigit()) != set(x for x in pb if x.isdigit()): somiglianza = min(somiglianza, 0.5)
		return somiglianza
	def _titolo_contraddice(titolo_tvdb, titolo_agganciato, titolo_stesso_numero):
		# gli agganciati non si somigliano (< 0,6) e quello allo stesso numero e' quasi identico (>= 0,9)
		s1, s2 = _somiglianza(titolo_tvdb, titolo_agganciato), _somiglianza(titolo_tvdb, titolo_stesso_numero)
		return s1 is not None and s2 is not None and s1 < 0.6 and s2 >= 0.9
	tvdb, trakt = _per_coppia(episodi_tvdb), _per_coppia(episodi_trakt)
	per_id = {}
	for coppia in sorted(trakt):
		ident = trakt[coppia][0]
		# Il PRIMO vince, e l'ordine e' deterministico: un id ripetuto e' un dato sporco, e fra due
		# comportamenti sbagliati e' meglio quello uguale su tutti i dispositivi.
		if ident is not None and ident not in per_id: per_id[ident] = coppia
	mappa, presi_tvdb, presi_trakt, per_identita = {}, set(), set(), []
	# REGOLA 2b (lotto 384). Gli episodi il cui aggancio per id e' contraddetto dal titolo, mentre allo stesso numero l'altra
	# parte ha il titolo quasi identico, si riservano quel numero PRIMA degli agganci per id: l'aggancio sbagliato che ci
	# puntava resta libero e la regola 3 lo rimette al suo numero. Senza la riserva l'episodio restava senza posto, cioe'
	# nascosto (Full Metal Panic! Fumoffu 2x8: il suo posto era preso dall'aggancio sbagliato di 2x9).
	# Il titolo che conferma dev'essere UNICO nella stagione TVDB: Pokemon 12x45 e 12x46 si chiamano entrambi "Unlocking the
	# Red Chain of Events!" (un doppio episodio), e li' il titolo non dice quale dei due.
	riservati = set()
	for coppia in sorted(tvdb):
		altra = per_id.get(tvdb[coppia][0]) if tvdb[coppia][0] is not None else None
		if (altra is not None and altra != coppia and coppia[0] > 0 and altra[0] > 0 and coppia in trakt
				and _titolo_contraddice(tvdb[coppia][3], trakt[altra][3], trakt[coppia][3])
				and not any(c != coppia and c[0] == coppia[0] and (_somiglianza(tvdb[coppia][3], tvdb[c][3]) or 0) >= 0.9 for c in tvdb)):
			riservati.add(coppia)
	# presi prima del ciclo: un aggancio per id che viene PRIMA nell'ordine non deve poter occupare un posto riservato
	presi_tvdb.update(riservati)
	presi_trakt.update(riservati)
	for coppia in sorted(tvdb):
		if coppia in riservati: continue
		ident = tvdb[coppia][0]
		if ident is None: continue
		altra = per_id.get(ident)
		if altra is None or altra in presi_trakt: continue
		# REGOLA 2. Senza data non si puo' concludere niente: si tiene l'aggancio.
		if coppia[0] > 0 and altra[0] > 0 and _contraddizione(tvdb[coppia][1], trakt[altra][1]): continue
		presi_tvdb.add(coppia)
		presi_trakt.add(altra)
		per_identita.append((coppia, altra))
		if coppia != altra: mappa[coppia] = altra
	liberi_tvdb, liberi_trakt = set(tvdb) - presi_tvdb, set(trakt) - presi_trakt
	# REGOLA 3.
	identita = set(c for c in (liberi_tvdb & liberi_trakt) if c[0] > 0)
	liberi_tvdb, liberi_trakt = liberi_tvdb - identita, liberi_trakt - identita
	# REGOLA 4. La posizione e' quella nella numerazione continua di TMDb: le stagioni > 0 in ordine.
	posizione = {c: i for i, c in enumerate(sorted(c for c in trakt if c[0] > 0), 1)}
	prove = [(tvdb[a][2], posizione[b]) for a, b in per_identita if a[0] > 0 and b[0] > 0]
	if prove and all(assoluto == pos for assoluto, pos in prove):
		per_posizione = {pos: c for c, pos in posizione.items() if c in liberi_trakt}
		for coppia in sorted(c for c in liberi_tvdb if c[0] > 0):
			altra = per_posizione.get(tvdb[coppia][2])
			if altra is None or altra not in liberi_trakt: continue
			g1, g2 = _giorno(tvdb[coppia][1]), _giorno(trakt[altra][1])
			if g1 is None or g2 is None or abs((g1 - g2).days) > 1: continue
			liberi_tvdb.discard(coppia)
			liberi_trakt.discard(altra)
			if coppia != altra: mappa[coppia] = altra
	# REGOLA 5. La frontiera si cerca solo nelle stagioni che restano VISIBILI: una stagione nascosta per
	# intero e' strutturale (una serie costola), non un collegamento in ritardo. Pokemon S20 e'
	# *Orizzonti*, ancora in onda: contata qui, terrebbe la frontiera aperta per sempre e la meta di
	# Pokemon si riscaricherebbe ogni giorno per niente.
	g_oggi = _giorno(oggi)
	inizio_frontiera = (g_oggi - timedelta(days=30)).isoformat() if g_oggi else oggi
	visibili = set(c[0] for c in tvdb if c not in liberi_tvdb)
	frontiera = any(c[0] > 0 and c[0] in visibili and tvdb[c][1] and inizio_frontiera <= str(tvdb[c][1])[:10] <= oggi
					for c in liberi_tvdb)
	return {
		'mappa': mappa,
		'esclusi_tvdb': liberi_tvdb,
		'esclusi_trakt': set(c for c in liberi_trakt if _uscito(trakt[c][1], oggi)),
		'frontiera': frontiera,
	}

def numero_assoluto(tvdb_id, stagione, episodio):
	"""Il numero assoluto TVDB dell'episodio, o None. Lotto 361: serve agli scraper per riconoscere le
	release anime, che numerano in assoluto ("One Piece - 1178" e' TVDB S23E23). Legge lo stesso payload
	skyhook della giuntura, in cache: nessuna richiesta nuova quando la serie e' gia' stata aperta."""
	if tvdb_id in invalid_tvdb: return None
	data = _fetch_raw(tvdb_id)
	if not data: return None
	try:
		stagione, episodio = int(stagione), int(episodio)
		for e in data.get('episodes') or []:
			if e.get('seasonNumber') == stagione and e.get('episodeNumber') == episodio: return e.get('absoluteEpisodeNumber') or None
	except: pass
	return None

def episodi_per_giuntura(tvdb_id):
	"""Gli episodi della serie su TVDB nella forma `(stagione, numero, id_tvdb, data, assoluto)`.

	L'assoluto e' la seconda chiave della regola 4 di costruisci_mappa_episodi (lotto 357).

	Sostituisce get_tvdb_to_tmdb_map, che appaiava per posizione e costruiva il lato TMDb come
	`range(1, episode_count+1)` -- cioe' lo inventava. Vedi il lotto 145.
	Qui non si mappa niente: si consegna solo l'elenco. L'appaiamento lo fa
	costruisci_mappa_episodi, che e' pura e provata.

	Due esiti vuoti, e non si confondono (correzione del 25/09): [] = TVDB non ha episodi per questa serie, o la
	serie non ha un id TVDB -- un dato, la serie resta su TMDb; None = skyhook non ha risposto -- non si sa, e
	tvshow_meta non deve concludere niente (vedi `rimappaggio_mancante`).
	"""
	if tvdb_id in invalid_tvdb: return []
	data = _fetch_raw(tvdb_id)
	if data is None: return None
	try:
		righe = data.get('episodes') or []
		# lotto 384: il titolo al settimo posto (il sesto e' l'id IMDb dal lato Trakt), per il veto di titolo della giuntura
		return [(e.get('seasonNumber'), e.get('episodeNumber'), e.get('tvdbId'), e.get('airDate'), e.get('absoluteEpisodeNumber'), None, e.get('title'))
				for e in righe]
	except: return None
