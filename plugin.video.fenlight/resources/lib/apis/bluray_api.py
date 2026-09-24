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
# PRODOTTI gia' filtrato per paese -- ma solo quello BLU-RAY, vedi il lotto 340 qui sotto -- e accanto
# a ogni voce mette data d'uscita e codice paese. Una richiesta invece di due, ~0,42 s invece di ~0,87 s, 0-3 KB invece di 3-11 KB, e nessuna
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
#
# LOTTO 340 -- IL CATALOGO ERA SOLO BLU-RAY, E I DVD NON LI VEDEVAMO. Il lotto 94 aveva misurato che
# 'bluray', 'dvd', 'all' e '' danno la stessa risposta, e ne aveva dedotto che cercassero tutti fra i
# prodotti home-video. Uguali lo sono -- misurato di nuovo il 24/09, byte per byte, anche 'digital' --
# ma perche' il sito non riconosce nessuno di quei valori e ricade sul catalogo Blu-ray. I valori veri
# sono quelli della tendina del sito: 'bluraymovies', 'dvdmovies', '4k', '3d', 'itunesmovies',
# 'aivmovies', 'uvmovies', 'mamovies'. Il caso che l'ha fatto vedere, paese IT:
#
#     Ichi the Killer 2001   bluray: vuoto      dvdmovies: 2 voci, senza data   -> era NASCOSTO
#     Visitor Q 2001         bluray: vuoto      dvdmovies: Jan 16, 2007         -> era NASCOSTO
#     Oppenheimer 2023       bluray: 5 voci     dvdmovies: vuoto (il DVD IT esiste: il sito non lo ha)
#
# Il catalogo DVD del sito e' quindi un'AGGIUNTA, non un sostituto: sui titoli recenti e' lacunoso. Si
# chiede prima il Blu-ray (che contiene gia' i 4K: 'The Matrix 4K', 'Perfect Days 4K' ci sono) e il DVD
# solo se il Blu-ray non ha trovato un'edizione uscita. I titoli che il Blu-ray lo hanno pagano la
# richiesta di prima e basta; la seconda la pagano solo quelli che fino a oggi venivano scartati.
# I verdetti negativi scritti prima di questo lotto sono sbagliati per costruzione: li butta
# dub_cache.migra_verdetti, una volta.
#
# LOTTO 344 -- LA RICERCA MOBILE, PER IL FILTRO "USCITO" (FILTRO-USCITA.md, regola U3). La domanda e' un'altra:
# non "c'e' un'edizione in questo paese" ma "c'e' un'edizione in un paese qualsiasi". La ricerca desktop con
# country=all risponde, ma misurato il 24/09 ha un difetto che la rende inservibile per un "si'" senza paese:
# quando non trova il titolo NON risponde vuoto, riempie la lista con altri film dello stesso anno --
#     'The Mongoose 2026', DVD, IT   ->  In the Grey (2026), Star Wars: The Mandalorian and Grogu (2026), ...
# e le voci non portano l'anno a parte, quindi non c'e' modo di scartarle. La ricerca MOBILE
# (m.blu-ray.com/quicksearch/search.php) fa lo stesso ('The Fix (2026)', 'The Yeti (2026)'), ma risponde in
# JSON con l'anno in un campo suo: si tengono le voci con l'anno giusto e con TUTTE le parole del titolo
# (articoli e accenti a parte: 'Leon: The Professional' e' 'Léon: The Professional'). Su 137 film, 548
# domande: 266 abbinate, 7 scartate, tutte spazzatura. Pesa 0,03-3 KB e si ferma a 10 voci.
#
# LOTTO 348 -- LA RICERCA DESKTOP NON C'E' PIU'. La usava solo il filtro doppiaggio per paese (has_home_video_release),
# sostituito dai filtri "uscito" e "doppiato": restano la ricerca mobile (uscito_su_disco, U3) e le tracce audio delle
# schede (tracce_audio, D3). Le note dei lotti 93-340 qui sopra sono la storia di quella strada; valgono ancora le
# regole che ne sono uscite e che il codice sotto conserva: Accept-Language e due cookie (_HEADERS, _cookies), i
# cataloghi veri (_CATALOGUES), "uscito" = data passata (_on_sale), la sentinella prima di un "no".
import re
import unicodedata
from html import unescape as _unescape

# Rete pigra (lotto 52): 'requests' e/o la Session erano a livello di modulo, quindi si
# caricavano all'import anche quando l'utente non toccava questo servizio. requests costa ~5,7 s
# a freddo sulla stick (misura del 24/08) e si paga per ogni interprete. Ora entra solo se serve.
def _requests():
	from modules.kodi_utils import import_requests
	return import_requests('bluray_api')

_MOBILE_URL = 'https://m.blu-ray.com/quicksearch/search.php'
# 'theatrical' cerca fra i FILM (e la risposta non dice nulla sulle edizioni). I cataloghi PRODOTTI del
# paese sono uno per supporto, e si chiedono in quest'ordine (lotto 340). Un valore che il sito non
# conosce -- 'bluray', 'dvd', 'all', '' -- non e' un catalogo "di tutto": ricade in silenzio su
# 'bluraymovies', ed e' cosi' che per 246 lotti abbiamo chiesto solo dei Blu-ray.
_CATALOGUES = ('bluraymovies', 'dvdmovies')
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
	# e' il motivo per cui esiste la sentinella (_sentinella): quel dubbio si scioglie li', una volta ogni mezz'ora,
	# non a ogni risposta.
	try:
		head = response.text[:2000].lower()
		if not head: return True
		return not any(m in head for m in _BLOCK_MARKERS)
	except Exception:
		return True   # nel dubbio si assume buona: non si apre un interruttore per un errore nostro

# Lazily-built shared session. Built through modules.http_client (lotto 84), which already keeps
# keep-alive connections per host (CONNESSIONI_PER_HOST, lotto 343). Cookies are passed PER-REQUEST (never mutating
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


# --- sentinella: il vuoto e' un "no" solo se l'indice sta rispondendo -----------------------------
# Il verdetto negativo di questa strada e' il CORPO VUOTO. E' economico e netto, ma ha un difetto:
# un guasto sistemico (indice cambiato, ip bandito) svuoterebbe ogni risposta, e il filtro
# nasconderebbe in blocco tutto cio' che non e' in streaming -- widget vuoti, senza una riga di log.
# Dopo il lotto 93 nessun guasto di questo sottosistema deve poter essere muto.
# Prima di fidarsi di un negativo si chiede quindi un titolo che nel catalogo c'e' di sicuro. Costa
# una richiesta ogni mezz'ora, e solo se un negativo capita davvero.
# 'The Matrix 1999' e' scelto per misura, non a naso: provato su 13 paesi (IT US UK FR DE ES JP NL SE
# PL BR AU CA) risponde in tutti. 'Oppenheimer 2023' no -- in Brasile e' vuoto.
# LOTTO 340 -- una sentinella PER CATALOGO: che risponda l'indice Blu-ray non dice niente di quello DVD.
# Stesso titolo, rimisurato il 24/09 su 'dvdmovies' negli stessi 13 paesi: risponde in tutti (IT con una
# voce sola, 'The Matrix Collection'). 'Gladiator 2000' e 'Jurassic Park 1993' no -- JP, PL, SE, BR vuoti.
_SENTINEL_KEYWORD = 'The Matrix 1999'
# LOTTO 344 -- la sentinella della ricerca mobile, per catalogo e paese: 'The Matrix 1999' risponde in entrambi i
# cataloghi con country=all e, misurato il 24/09 per il lotto 346, in ogni paese delle lingue del filtro doppiaggio
# (IT US UK CA AU ES MX FR DE PT BR JP PL; nel DVD italiano e giapponese solo con una raccolta, ma risponde).
_MOBILE_SENTINEL_PROP = 'fenlight.bluray.mobile.%s.%s'
def _log(message):
	try:
		from modules.kodi_utils import logger
		logger('FenLight BLURAY', message)
	except Exception: pass

def _sentinella(key, domanda, nome):
	# LOTTO 345 -- la regola e la memoria della sentinella stanno in modules/sentinella, comune con JustWatch.
	from modules.sentinella import viva
	return viva(key, domanda, '%s, "%s"' % (nome, _SENTINEL_KEYWORD), 'FenLight BLURAY')



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



# --- LOTTO 344: ricerca mobile, filtro "uscito" (regola U3 di FILTRO-USCITA.md) ------------------------------------

def _mobile_search(keyword, country, section):
	"""Le voci della ricerca mobile, come le da' il sito: [{'title', 'year', 'reldate', 'flag', 'url'}, ...].

	Nessuna edizione e' {"items":[]}, cioe' una lista vuota. Un corpo vuoto con 200 (2 volte su 360 nella misura del
	24/09, e alla riprova non si ripete) non e' un "no": json() solleva, e il chiamante conclude inconcludente.
	"""
	response = _get_session().get(_MOBILE_URL, params={'userid': '-1', 'section': section, 'country': country, 'keyword': keyword},
								  cookies=_cookies(country), timeout=_TIMEOUT, validate=_looks_genuine)
	response.raise_for_status()
	items = response.json().get('items')
	if not isinstance(items, list): raise ValueError('ricerca mobile: risposta senza "items"')
	return items

def _causa(cosa, errore):
	"""Una riga di diagnostica: che cosa non ha risposto e perche'. Si scrive solo quando il verdetto resta "non so",
	e la scrive l'unico punto che conosce la causa (come tmdb_api.get_tmdb dal lotto 334): con "ricerca o scheda
	senza risposta" e basta, il 25/09 non si poteva distinguere un corpo vuoto da un blocco o da una pagina cambiata."""
	if isinstance(errore, ValueError) and 'Expecting value' in str(errore): motivo = 'risposta vuota o non JSON'
	else: motivo = '%s: %s' % (type(errore).__name__, str(errore)[:120])
	return '%s: %s' % (cosa, motivo)

def _mobile_alive(section, country='all'):
	return _sentinella(_MOBILE_SENTINEL_PROP % (section, country), lambda: _mobile_search(_SENTINEL_KEYWORD, country, section),
					   'mobile %s/%s' % (country, section))

_ARTICOLI = frozenset(('the', 'a', 'an'))
_PAROLA_RE = re.compile(r'[^\W_]+')

def _parole(testo):
	"""Le parole di un titolo, senza accenti, articoli e maiuscole: 'Léon: The Professional' -> {'leon', 'professional'}."""
	testo = unicodedata.normalize('NFKD', _unescape(testo or ''))
	testo = ''.join(c for c in testo if not unicodedata.combining(c)).lower().replace('&', ' and ')
	return set(_PAROLA_RE.findall(testo)) - _ARTICOLI

def _stesso_anno(voce, year, serie):
	anno = str(voce.get('year') or '')
	# Una serie ha anche i cofanetti di piu' stagioni, con l'intervallo: 'Breaking Bad: The Complete Series' e' '2008-2013'.
	return anno == str(year) or (serie and anno.startswith('%s-' % year))

def _voci_del_titolo(items, title, year, serie=False):
	"""Le sole voci che sono QUEL titolo: anno uguale e tutte le sue parole presenti.

	Il nome della voce puo' averne di piu' ('Oppenheimer 4K (Limited Edition) (2023)', 'Demon Slayer - Kimetsu no
	Yaiba - The Movie: Infinity Castle'), non di meno.
	"""
	cercate = _parole(title)
	return [i for i in items if isinstance(i, dict) and _stesso_anno(i, year, serie) and cercate <= _parole(i.get('title'))]

def _date_e_nomi(voci):
	"""Le voci nella forma che legge _on_sale: [(data_o_None, nome)]. 'No release date' diventa None."""
	return [(_parse_date(i.get('reldate')), i.get('title') or '') for i in voci]

def uscito_su_disco(title, year, verify_released=False):
	"""U3: esiste un'edizione Blu-ray o DVD gia' uscita, in un paese qualsiasi? True / False / None (inconcludente).

	Blu-ray, poi DVD solo se serve. Basta un catalogo che dica si'; il "no" dev'essere di tutti, e il vuoto di un
	catalogo vale "no" solo se risponde la sua sentinella (stessa regola del lotto 340). Un catalogo che ha il titolo
	ma solo in edizioni non ancora uscite ha risposto: e' un "no", senza sentinella. `verify_released` ha il
	significato di sempre: per un titolo appena uscito di sala un'edizione senza data non conta.
	"""
	if not title or not year or not _parole(title): return None
	keyword = '%s %s' % (title, year)
	cause = []
	for section in _CATALOGUES:
		try: items = _mobile_search(keyword, 'all', section)
		except Exception as e:
			cause.append(_causa('ricerca %s/all' % section, e))
			continue
		entries = _date_e_nomi(_voci_del_titolo(items, title, year))
		if entries:
			if _on_sale(entries, verify_released, _today()): return True
		elif not _mobile_alive(section): cause.append('%s/all: sentinella muta' % section)
	if cause:
		_log('"%s" (%s): uscita su disco non accertata -- %s' % (title, year, '; '.join(cause)))
		return None
	return False

# --- LOTTO 346: le tracce audio dei dischi, filtro doppiaggio (regola D3 di FILTRO-USCITA.md) ------------------------
#
# La domanda non e' piu' "e' uscito un disco nel paese" (il filtro di oggi, che fa passare Visitor Q: DVD italiano con
# il solo giapponese) ma "esiste un disco con la traccia in quella lingua". La risposta e' nella scheda mobile
# dell'edizione (m.blu-ray.com/movies/.../ID/), ~4 KB compressi, che elenca le tracce una per riga:
#     <h3>Audio</h3><p ...>English: DTS-HD Master Audio 5.1 (48kHz, 24-bit)<br> Italian: DTS 5.1<br> </p>
# Una scheda vale per TUTTE le lingue insieme. "TBA" (audio non ancora catalogato, frequente sui DVD) non certifica
# niente; una scheda SENZA la sezione Audio e' una pagina che non riconosciamo, e rende il verdetto inconcludente.
# blu-ray.com scrive i nomi inglesi delle lingue e non distingue le varianti regionali ("Spanish" anche sul disco
# canadese, che e' il doppiaggio latinoamericano; "Spanish: Dolby Digital Mono (Spain)" su Twin Peaks): come le
# altre fonti, si riduce alla lingua, cioe' al testo prima dei due punti.
_NOMI_LINGUE = {'italian': 'it', 'english': 'en', 'spanish': 'es', 'french': 'fr', 'german': 'de',
				'portuguese': 'pt', 'japanese': 'ja', 'polish': 'pl'}
_AUDIO_RE = re.compile(r'<h3>\s*Audio\s*</h3>\s*<p[^>]*>(.*?)</p>', re.DOTALL | re.IGNORECASE)
_BR_RE = re.compile(r'<br\s*/?>', re.IGNORECASE)
_TAG_RE = re.compile(r'<[^>]+>')
# Schede lette insieme. Poche: di solito la prima certifica, e sono le fermate dopo a costare meno.
_SCHEDE_INSIEME = 4
# Thread per le ricerche di UN titolo (lotto 347). Il preparatore giudica fino a 20 titoli insieme, e senza tetto ogni
# giudizio ne lancerebbe fino a WORKER_COUNT (10): 200 thread. Il limite vero verso il sito resta CONNESSIONI_PER_HOST.
_RICERCHE_INSIEME = 4

def _lingue_della_scheda(body):
	"""Le lingue (codici) delle tracce audio di una scheda. Solleva se la scheda non ha la sezione Audio."""
	match = _AUDIO_RE.search(body or '')
	if not match: raise ValueError('scheda senza sezione Audio')
	lingue = set()
	for riga in _BR_RE.split(match.group(1)):
		nome = _unescape(_TAG_RE.sub('', riga)).split(':')[0].strip().lower()
		codice = _NOMI_LINGUE.get(nome)
		if codice: lingue.add(codice)
	return lingue

def _scheda(url):
	response = _get_session().get(url, cookies=_cookies('all'), timeout=_TIMEOUT, validate=_looks_genuine)
	response.raise_for_status()
	return _lingue_della_scheda(response.text)

def _in_vendita(voce, verify_released, today):
	"""L'edizione e' gia' uscita? La stessa regola di _on_sale, per UNA voce."""
	return _on_sale(_date_e_nomi([voce]), verify_released, today)

def tracce_audio(title, year, media_type, paesi_per_lingua, verify_released=False):
	"""D3: quali lingue hanno una traccia audio su un disco (Blu-ray o DVD) gia' uscito nei paesi di quella lingua.

	`paesi_per_lingua` e' {'it': ('IT',), 'es': ('ES', 'MX'), ...}. Restituisce l'insieme delle lingue certificate
	appena una scheda ne certifica almeno una (le altre lingue restano non chieste, non negate: al filtro basta una
	lingua); set() se tutte le edizioni sono state lette e nessuna ha quelle tracce; None se non si e' potuto sapere
	(una ricerca o una scheda senza risposta, una sentinella muta) e niente e' stato certificato.
	"""
	if not title or not year or not _parole(title) or not paesi_per_lingua: return None
	from modules.utils import make_thread_list_enumerate_capped
	lingue = set(paesi_per_lingua)
	paesi = []
	for lingua in sorted(paesi_per_lingua):
		for paese in paesi_per_lingua[lingua]:
			if paese.upper() not in paesi: paesi.append(paese.upper())
	keyword = '%s %s' % (title, year)
	serie = media_type != 'movie'
	ricerche = [(section, paese) for section in _CATALOGUES for paese in paesi]
	risposte = [None] * len(ricerche)
	def cerca(i, lavoro):
		section, paese = lavoro
		try: risposte[i] = _mobile_search(keyword, paese, section)
		except Exception as e: risposte[i] = e
	make_thread_list_enumerate_capped(cerca, ricerche, _RICERCHE_INSIEME)
	cause, oggi, schede = [], _today(), []
	for (section, paese), items in zip(ricerche, risposte):
		if not isinstance(items, list):
			cause.append(_causa('ricerca %s/%s' % (section, paese), items))
			continue
		voci = _voci_del_titolo(items, title, year, serie)
		if not voci:
			if not _mobile_alive(section, paese): cause.append('%s/%s: sentinella muta' % (section, paese))
			continue
		for voce in voci:
			url = voce.get('url')
			if url and url not in schede and _in_vendita(voce, verify_released, oggi): schede.append(url)
	# Le schede nell'ordine delle ricerche: Blu-ray prima dei DVD (hanno l'audio catalogato piu' spesso), a gruppi.
	for inizio in range(0, len(schede), _SCHEDE_INSIEME):
		gruppo = schede[inizio:inizio + _SCHEDE_INSIEME]
		lette = [None] * len(gruppo)
		def leggi(i, url):
			try: lette[i] = _scheda(url)
			except Exception as e: lette[i] = e
		make_thread_list_enumerate_capped(leggi, gruppo, _SCHEDE_INSIEME)
		trovate = set()
		for url, esito in zip(gruppo, lette):
			if isinstance(esito, set): trovate |= esito & lingue
			else: cause.append(_causa('scheda %s' % url, esito))
		if trovate: return trovate
	if cause:
		_log('"%s" (%s): tracce audio non accertate -- %s' % (title, year, '; '.join(cause)))
		return None
	return set()
