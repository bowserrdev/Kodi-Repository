# -*- coding: utf-8 -*-
# Home-video availability lookup against blu-ray.com.
#
# Used by the widget "dubbed content" filter as the FALLBACK signal: it is queried only when a title
# is NOT found on any streaming platform (TMDb/JustWatch) in the user's country, to decide whether a
# physical/home-video edition exists there (a strong hint that a localised, i.e. dubbed, edition exists).
#
# LOTTO 94 -- UNA RICHIESTA SOLA, E LA FINE DI UN GUASTO CHE NON ESISTEVA.
#
# Il lotto 93 aveva concluso che `menu_ajax.php?action=showreleases` fosse morto ("200 con zero byte
# per qualunque titolo") e che il blocco delle edizioni si fosse spostato dentro la pagina prodotto da
# 524 KB. MISURATO IL 26/08: era falso. L'endpoint risponde benissimo -- 8.302 byte in 0,46 s per
# Oppenheimer, con i tre header oswaldcollection e il flag IT. Il corpo vuoto lo causavamo noi:
#
#     Cookie: country=it                      -> 0 byte        (un cookie SOLO)
#     Cookie: country=it; firstview=1         -> 8.302 byte
#     Cookie: country=it; pw_bottom_filter=.. -> 8.302 byte
#     Cookie: country=it; xyzzy=1             -> 8.302 byte    (il secondo cookie e' INVENTATO)
#
# Non conta il valore del secondo cookie, conta che ce ne sia uno: un'euristica anti-bot banale
# ("un browser vero non manda mai un cookie solo"). E noi ne mandavamo uno solo, perche' il barattolo
# del lotto 93 restava vuoto: questo percorso non visita mai la home page, e quicksearch.php -- unica
# richiesta che facevamo prima -- NON manda alcun Set-Cookie (verificato).
#
# STRADA SCELTA. La correzione del cookie basterebbe, ma cercando l'ho trovata una strada migliore:
# quicksearch.php con `section` DIVERSO da 'theatrical' non cerca fra i film, cerca nel CATALOGO
# PRODOTTI home-video gia' filtrato per paese, e accanto a ogni voce mette data d'uscita e codice
# paese. Una richiesta invece di due, ~0,42 s invece di ~0,87 s, 0-3 KB invece di 3-11 KB, e nessuna
# pagina pesante da aprire mai.
#
#     keyword='Oppenheimer 2023', cookie country=it  ->  3.286 B
#         cc=IT  Dec 21, 2023 | Oppenheimer (2023)
#         cc=IT  Dec 21, 2023 | Oppenheimer 4K (2023)
#     keyword='Hundreds of Beavers 2022'             ->  0 B       (nessuna edizione IT)
#         ...la stessa con country=us                ->  2.879 B   (cc=US)
#
# COSA SI PERDE, e perche' non importa. La ricerca prodotti vede solo i DISCHI, non le edizioni
# digitali. Su 18 titoli provati le due strade divergono su tre -- Aftersun, EO, Sound of Metal --
# tutti con la sola voce `iTunes[IT]`. Ma quei tre a blu-ray.com non ci arrivano MAI: il controllo a
# monte (metadata.py:_store_streaming_verdict e tmdb_api.streaming_available) accetta i secchi
# ('flatrate', 'free', 'ads', 'rent', 'buy'), e iTunes vive dentro rent/buy. Se stiamo interrogando
# blu-ray.com e' perche' TMDb/JustWatch ha gia' detto che in digitale non c'e'. Sui titoli che
# raggiungono davvero questo modulo le due strade danno lo stesso verdetto.
#
# TRAPPOLA DA NON RIPERCORRERE. quicksearch accetta un IMDb id e risponde, il che sembra la soluzione
# elegante al problema dei titoli localizzati. Non lo e': non esiste un indice IMDb, fa un match
# fuzzy sul NUMERO e restituisce risultati plausibili ma sbagliati. Misurato:
#     tt15398776 -> Oppenheimer             (giusto)
#     tt14209916 -> Cocaine Bear            (era Hundreds of Beavers)
#     tt13405778 -> Insidious: The Red Door (era Skinamarink)
#     tt28607951 -> Anora                   (era The Brutalist)
# Passerebbe qualunque prova superficiale. Non usare l'IMDb id come chiave di ricerca.
import re

# Rete pigra (lotto 52): 'requests' e/o la Session erano a livello di modulo, quindi si
# caricavano all'import anche quando l'utente non toccava questo servizio. requests costa ~5,7 s
# a freddo sulla stick (misura del 24/08) e si paga per ogni interprete. Ora entra solo se serve.
def _requests():
	from modules.kodi_utils import import_requests
	return import_requests('bluray_api')

_SEARCH_URL = 'https://www.blu-ray.com/search/quicksearch.php'
# 'theatrical' cerca fra i FILM (e la risposta non dice nulla sulle edizioni). Qualunque altro valore
# -- 'bluray', 'dvd', 'all', o la stringa vuota: sono equivalenti, verificato -- cerca fra i PRODOTTI
# home-video del paese. E' quello che ci serve.
_CATALOGUE_SECTION = 'bluray'
# Una voce del menu a tendina: <li id="matchN"><span ...>Dec 21, 2023</span>&nbsp;Oppenheimer (2023)</li>
# La data sta nello span (che il CSS manda a destra ma nel sorgente viene prima); il nome e' il resto.
_ENTRY_RE = re.compile(r'id="match\d+"[^>]*>(.*?)</li>', re.DOTALL)
_ENTRY_DATE_RE = re.compile(r'<span[^>]*>(.*?)</span>', re.DOTALL)
# Array parallelo alle voci, un codice paese per voce.
_COUNTRYCODES_RE = re.compile(r'var countrycodes = new Array\((.*?)\);', re.DOTALL)
_QUOTED_RE = re.compile(r"'([^']*)'")
_MONTHS = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
           'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}
_DATE_RE = re.compile(r'([A-Za-z]{3})\w*\s+(\d{1,2}),?\s+(\d{4})')
_TIMEOUT = 8.0

_HEADERS = {
	'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
	'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
	# ACCEPT-LANGUAGE E' OBBLIGATORIO, misurato il 25/08 provando le intestazioni una per una sulla
	# home di blu-ray.com:
	#     solo User-Agent .......................... 200, 7 byte: 'error42'
	#     + Accept: */* ............................ 200, 7 byte: 'error42'
	#     + Accept: text/html ...................... 200, 7 byte: 'error42'
	#     + Accept-Language: it-IT ................. 200, 543059 byte, con Set-Cookie
	# Il sito rifiuta chi non manda Accept-Language -- e lo fa con un 200, quindi nessun codice di
	# stato lo rivela. Nemmeno 'requests' lo mandava: questo NON e' una regressione del lotto 84, e'
	# un giro di vite del sito.
	'Accept-Language': 'it-IT,it;q=0.9,en;q=0.8',
	'X-Requested-With': 'XMLHttpRequest',
	'Referer': 'https://www.blu-ray.com/'
}

# Risposte che sembrano buone (200) ma non contengono nulla di utilizzabile. Il livello di rete
# classifica il TRASPORTO e i codici di stato; che un 200 sia in realta' un rifiuto e' sapere di
# dominio e resta qui. Il verdetto pero' alimenta lo STESSO interruttore condiviso (parametro
# validate= di http_client), che e' il punto del lotto 93.
#
# 'error42' e' MISURATO, non ipotizzato: e' il corpo di 7 byte che blu-ray.com restituisce con
# HTTP 200 a chi non manda Accept-Language (vedi _HEADERS). Gli altri marcatori sono quelli dei
# filtri anti-bot piu' diffusi e NON li abbiamo mai visti sulla stick: se uno di loro apre
# l'interruttore per sbaglio si vede nel log come 'Interruttore APERTO' e si corregge.
_BLOCK_MARKERS = ('error42', 'just a moment', 'attention required', 'access denied',
                  'cf-browser-verification', 'unusual traffic', 'rate limit')

def _looks_genuine(response):
	# True = risposta utilizzabile. False = rifiuto: conta come guasto per l'interruttore.
	#
	# LOTTO 94 -- IL CORPO VUOTO NON E' PIU' UN GUASTO. Nel lotto 93 lo era, perche' allora il vuoto
	# arrivava dall'ajax rotto dal cookie singolo. Nella ricerca a catalogo il corpo vuoto e' la
	# RISPOSTA LEGITTIMA a "nessuna edizione in questo paese" -- e' il verdetto negativo, il caso che
	# il filtro esiste per trovare. Contarlo come guasto aprirebbe l'interruttore dopo tre titoli
	# stranieri di fila e spegnerebbe il ripiego proprio quando serve.
	# Che il vuoto possa nascondere un guasto SISTEMICO (indice cambiato, ip bandito) resta vero, ed
	# e' il motivo per cui esiste _index_alive: quel dubbio si scioglie li', una volta ogni mezz'ora,
	# non a ogni risposta.
	try:
		head = response.text[:2000].lower()
		if not head: return True
		return not any(m in head for m in _BLOCK_MARKERS)
	except Exception:
		return True   # nel dubbio si assume buona: non si apre un interruttore per un errore nostro

# Lazily-built shared session. Built through modules.http_client (lotto 84), which already keeps
# POOL_PER_HOST=8 keep-alive connections per host. Cookies are passed PER-REQUEST (never mutating
# session state) so the shared session is safe to use from the parallel per-item filter threads.
_session = None

def _get_session():
	global _session
	if _session is None:
		s = _requests().Session()
		# LOTTO 93 -- QUI C'ERA UN GUASTO MUTO, ed e' durato dal lotto 84 al 25/08:
		#     s.mount('https://', _requests().adapters.HTTPAdapter(pool_maxsize=8))
		# Dal lotto 84 _requests() non torna piu' la libreria 'requests' ma modules.http_client, che
		# NON ha un attributo 'adapters'. Quella riga sollevava AttributeError, e siccome
		# has_home_video_release racchiude tutto in un try che finisce in `return None`, l'errore
		# spariva: OGNI interrogazione a blu-ray.com tornava None, cioe' "non lo so", cioe' fail open.
		# Il ripiego home-video del filtro doppiaggio era spento, e nessuno se ne accorgeva perche' il
		# risultato di un fallimento e' identico a quello di un titolo mostrato di proposito.
		s.headers.update(_HEADERS)
		_session = s
	return _session

def _cookies(country):
	# DUE cookie, sempre. Il secondo non serve a trasportare informazione -- serve a esistere: con un
	# cookie solo blu-ray.com risponde 200 con zero byte (vedi la nota in cima al modulo). Sulla
	# ricerca a catalogo il sintomo non si manifesta, ma non voglio che questa classe di guasto possa
	# tornare se un domani cambiamo endpoint: 'firstview' e' anche uno dei due cookie che la home page
	# assegna davvero, quindi la richiesta somiglia a quella di un browser invece di aggirare un
	# controllo per caso.
	return {'country': country.lower(), 'firstview': '1'}

def _today():
	from time import localtime
	now = localtime()
	return (now.tm_year, now.tm_mon, now.tm_mday)

def _parse_date(text):
	# 'Dec 21, 2023' -> (2023, 12, 21). None se la voce non ha data (il sito ci mette un '-').
	# strptime('%b') dipende dalla locale del processo, che su Kodi non controlliamo: mese a mano.
	match = _DATE_RE.search(text or '')
	if not match: return None
	month = _MONTHS.get(match.group(1).lower())
	if not month: return None
	try:
		return (int(match.group(3)), month, int(match.group(2)))
	except Exception:
		return None

def _parse_entries(body, country):
	# Ritorna [(data_o_None, nome), ...] per le sole voci del paese richiesto.
	raw_entries = _ENTRY_RE.findall(body)
	if not raw_entries: return []
	codes_match = _COUNTRYCODES_RE.search(body)
	codes = _QUOTED_RE.findall(codes_match.group(1)) if codes_match else []
	entries = []
	for index, chunk in enumerate(raw_entries):
		# Se l'array dei codici manca o e' piu' corto, si accetta la voce: la ricerca era GIA'
		# filtrata per paese dal payload e dal cookie, il codice e' una conferma, non la fonte.
		if index < len(codes) and codes[index] and codes[index].upper() != country:
			continue
		date_match = _ENTRY_DATE_RE.search(chunk)
		date_text = date_match.group(1) if date_match else ''
		name = re.sub(r'<[^>]+>', '', chunk.replace(date_match.group(0), '') if date_match else chunk)
		entries.append((_parse_date(date_text), name.replace('&nbsp;', ' ').strip()))
	return entries

# --- sentinella: il vuoto e' un "no" solo se l'indice sta rispondendo -----------------------------
# Il verdetto negativo di questa strada e' il CORPO VUOTO. E' economico e netto, ma ha un difetto:
# un guasto sistemico (indice cambiato, ip bandito) svuoterebbe ogni risposta, e il filtro
# nasconderebbe in blocco tutto cio' che non e' in streaming -- widget vuoti, senza una riga di log.
# Dopo il lotto 93 nessun guasto di questo sottosistema deve poter essere muto.
# Prima di fidarsi di un negativo si chiede quindi un titolo che nel catalogo c'e' di sicuro. Costa
# una richiesta ogni mezz'ora, e solo se un negativo capita davvero.
# 'The Matrix 1999' e' scelto per misura, non a naso: provato su 13 paesi (IT US UK FR DE ES JP NL SE
# PL BR AU CA) risponde in tutti. 'Oppenheimer 2023' no -- in Brasile e' vuoto.
_SENTINEL_KEYWORD = 'The Matrix 1999'
_SENTINEL_PROP = 'fenlight.bluray.index.%s'
_SENTINEL_TTL = 1800
_MEMORY_SENTINEL = {}

def _sentinel_io():
	# Le proprieta' di finestra sono l'unica memoria condivisa fra le invocazioni: con
	# reuselanguageinvoker=false ogni build e' un processo nuovo, quindi una variabile di modulo non
	# sopravviverebbe. Import ritardato e protetto: il modulo deve restare importabile fuori da Kodi.
	try:
		from modules.kodi_utils import get_property, set_property
		return get_property, set_property
	except Exception:
		return (lambda k: _MEMORY_SENTINEL.get(k, ''),
				lambda k, v: _MEMORY_SENTINEL.__setitem__(k, v))

def _log(message):
	try:
		from modules.kodi_utils import logger
		logger('FenLight BLURAY', message)
	except Exception: pass

def _index_alive(country):
	# True  -> l'indice risponde: un corpo vuoto significa davvero "nessuna edizione".
	# False -> l'indice non risponde nemmeno per un titolo che c'e' di sicuro: il vuoto non e' un no.
	from time import time
	get_property, set_property = _sentinel_io()
	key = _SENTINEL_PROP % country
	try:
		state, expiry = (get_property(key) or '').split('|')
		if time() < float(expiry): return state == 'ok'
	except Exception:
		pass
	try:
		alive = bool(_search(_SENTINEL_KEYWORD, country))
	except Exception:
		return False   # non si e' potuto stabilire: non si trasforma un dubbio in un "no"
	set_property(key, '%s|%s' % ('ok' if alive else 'ko', time() + _SENTINEL_TTL))
	if not alive:
		_log('SENTINELLA FALLITA per %s: "%s" non risulta nel catalogo. L\'indice non sta rispondendo, '
			'quindi le risposte vuote NON valgono come "nessuna edizione" e i verdetti restano '
			'inconcludenti (elementi mostrati) finche\' non torna.' % (country, _SENTINEL_KEYWORD))
	return alive

def _search(keyword, country):
	# Una richiesta. Ritorna la lista delle edizioni del paese ([] se non ce ne sono).
	# Solleva se la rete fallisce: la classificazione, la riprova e l'interruttore per host stanno in
	# modules/http_client (lotto 93) e valgono per ogni chiamata di rete della stick.
	payload = {'section': _CATALOGUE_SECTION, 'userid': '-1', 'country': country, 'keyword': keyword}
	response = _get_session().post(_SEARCH_URL, data=payload, cookies=_cookies(country),
									timeout=_TIMEOUT, validate=_looks_genuine)
	response.raise_for_status()
	body = response.text
	if not body or not body.strip(): return []
	return _parse_entries(body, country)

def _on_sale(entries, verify_released, today):
	# True se almeno un'edizione del paese e' GIA' USCITA. Un'edizione annunciata non implica che una
	# copia doppiata sia comprabile oggi, che e' la domanda vera del filtro.
	#
	# Il pre-order NON si riconosce dalla sola assenza di data: verificato il 26/08 (data di sistema
	# Aug 26, 2026), un annuncio compare con la sua data FUTURA come qualsiasi altra voce --
	#     Oct 07, 2026 | Toy Story 5 (2026)          annunciato
	#     Sep 16, 2026 | Backrooms 4K (2026)         annunciato
	#     -            | Disclosure Day (2026)       annunciato, data ignota
	#     Dec 21, 2023 | Oppenheimer (2023)          uscito
	# La regola e' quindi: uscito = data presente E data <= oggi.
	#
	# Questo e' esattamente cio' che il vecchio _any_released calcolava aprendo fino a quattro pagine
	# prodotto per cercarci 'Available for pre-order' -- 402 KB e 1,65 s l'una, misurate. Ora e'
	# gratis, perche' la data arriva nella stessa risposta da 1-3 KB che scarichiamo comunque.
	undated = False
	for date, _name in entries:
		if date is None:
			undated = True
			continue
		if date <= today: return True
	# Nessuna edizione con data passata. Restano solo voci senza data: ambigue, perche' possono essere
	# un annuncio senza data OPPURE un buco nei dati del sito per un'edizione vecchia. Si scioglie
	# come il chiamante ha chiesto: per un titolo appena uscito di sala (verify_released) l'annuncio e'
	# l'ipotesi di gran lunga piu' probabile e non conta; per un titolo vecchio conta.
	return bool(undated) and not verify_released

def has_home_video_release(title, year, country='IT', verify_released=False):
	# Returns:
	#   True  -> a home-video release exists for `title` in `country` and is actually out
	#   False -> conclusively no release (not in the country's catalogue, or only announced editions)
	#   None  -> network/parse error, or the query can't be asked: INCONCLUSIVE. The caller must fail
	#            open (show the item) and NOT cache.
	# verify_released: when True the caller is asking about a recently-released title, where an
	# announced-but-not-out edition is plausible; it only decides how an UNDATED edition is read (see
	# _on_sale). Future-dated editions never count, for anyone: that check is free now.
	if not title: return None
	country = country.upper()
	keyword = '%s %s' % (title, year) if year else '%s' % title
	# La ricerca a catalogo ignora le query di UNA PAROLA SOLA: 'Oppenheimer' -> 0 byte,
	# 'Oppenheimer 2023' -> 3.286 byte. Misurato, e vale anche per 'Anora', 'Flow', 'Up'. Con l'anno
	# in mano siamo sempre a due parole, ma se manca -- o se il titolo e' una parola e l'anno e' None
	# -- la domanda non e' ponibile per questa strada: il vuoto che ne uscirebbe sarebbe un falso
	# negativo, cioe' un elemento nascosto per sbaglio. Meglio dichiararsi inconcludenti.
	if len(keyword.split()) < 2:
		_log('"%s": senza anno la ricerca a catalogo non e\' interrogabile (serve piu\' di una parola) '
			'-> INCONCLUSIVO' % title)
		return None
	try:
		entries = _search(keyword, country)
	except Exception:
		# LOTTO 93: la POLITICA sugli errori non sta qui. Classificazione, riprova e interruttore per
		# host vivono in modules/http_client e valgono per ogni chiamata di rete della stick; qui
		# resta la sola decisione DI DOMINIO, che e' sempre la stessa: se non si e' potuto stabilire
		# nulla si torna None, e il chiamante mostra l'elemento (fail open).
		# In particolare NON si distingue piu' fra tipi di guasto: quando l'interruttore e' aperto
		# arriva un CircuitOpen (sottoclasse di OSError) e si esce subito, senza aspettare _TIMEOUT.
		return None
	if not entries:
		# Il negativo di questa strada e' il corpo vuoto. Vale come "no" solo se l'indice risponde.
		return False if _index_alive(country) else None
	return _on_sale(entries, verify_released, _today())
