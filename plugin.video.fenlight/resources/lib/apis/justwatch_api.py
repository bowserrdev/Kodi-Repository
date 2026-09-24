# -*- coding: utf-8 -*-
"""JustWatch: in quali lingue e' doppiato un titolo sulle piattaforme (lotto 345, regola D2 di FILTRO-USCITA.md).

E' l'unica fonte che conosce l'audio delle offerte in streaming: TMDb prende da JustWatch le piattaforme ma non le
lingue. Si interroga l'endpoint GraphQL del sito (apis.justwatch.com/graphql), NON l'API ufficiale, che e' a
pagamento: non e' documentato e puo' cambiare, quindi e' trattato come blu-ray.com -- sentinella, e "non so" quando
non risponde, mai "no". Decisione dell'utente del 24/09.

UNA RICHIESTA PER TITOLO, qualunque sia il numero di lingue: la ricerca, gli id per l'abbinamento e le offerte di
tutti i paesi insieme (un alias GraphQL per paese). 1-6 KB compressi, ~0,2 s, misurato il 24/09.

Cose misurate che la forma del modulo rispecchia:
  - non esiste una ricerca per id (introspezione disabilitata; titleByTmdbId, node(tmdbId) rifiutati): si cerca per
    titolo e si abbina sugli id. La ricerca per titolo sbaglia (Rings of Power -> Power Rangers), gli id no;
  - il tmdbId a volte e' nullo (Gabriel's Inferno: Part 1): allora vale l'imdbId;
  - cercare in USA, col titolo inglese e il tipo (objectTypes): su 110 titoli il giusto e' il primo 103 volte,
    nei primi 5 altre 2, assente 5 (serie di nicchia che JustWatch non ha). In Italia 95 e 15 assenti;
  - le offerte CINEMA (Cinelandia, Starplex) non sono un'uscita e non contano;
  - Netflix, Sky/Now, RaiPlay, Timvision, CHILI hanno audioLanguages vuoto: per loro questa fonte non sa niente
    (Netflix lo copre la regola D1, dalla risposta di TMDb);
  - i codici regionali si riducono alla lingua: es-419 -> es, pt-BR -> pt, fr-CA -> fr (le fonti non distinguono
    i doppiaggi regionali in modo affidabile, quindi non lo facciamo nemmeno noi);
  - carico: 720 ricerche a 12 e a 20 in parallelo, zero errori e zero rifiuti, mediana 0,2 s.

LA CORRISPONDENZA TMDb -> JUSTWATCH ESISTE (osservazione dell'utente, 24/09), ma non nell'API di TMDb: sta nella sua
pagina web "dove guardarlo" (il `link` di watch/providers). Ogni link verso JustWatch porta un parametro `cx`, JSON in
base64, con l'id interno del titolo ('jwEntityId': 'tm10' e' The Matrix), e `node(id:)` di JustWatch lo accetta. E'
la strada piu' affidabile -- recupera Cado dalle nubi e Il ciclone, che la ricerca in USA non trova, e il Pinocchio del
1972 che JustWatch ha legato a un duplicato di TMDb -- ma come strada PRINCIPALE non regge: ~40 KB di HTML contro
1-6 KB, e il sito ha un limite di frequenza. Quindi tre passi:
  1. TMDb, gratis: le piattaforme di TMDb vengono da JustWatch. Se TMDb non ha offerte nei paesi chiesti, JustWatch
     non ne ha: "nessuna lingua" senza nessuna richiesta, e si chiedono solo i paesi che hanno offerte;
  2. la ricerca per titolo, abbinata sugli id (216 titoli su 220 in un campione difficile);
  3. se la ricerca non trova il titolo, la pagina di TMDb. Il limite del sito, misurato il 24/09, e' una FINESTRA
     FISSA: 10 pagine ogni 10 secondi, qualunque sia la concorrenza (14 chieste insieme: 10 passano, 4 rifiutate con
     429; poi rifiutato tutto fino al decimo secondo, e si riparte). Si contano quindi le pagine della finestra: fino
     a 10 partono subito, l'undicesima aspetta la finestra dopo (al piu' 10 s). Servono a ~2 titoli su 100, quindi in
     pratica non si aspetta mai. Un 429 resta "non so", mai "no".
"""
import re
import threading
from time import time as _time, sleep as _sleep

_URL = 'https://apis.justwatch.com/graphql'
_TIMEOUT = 8.0
_RISULTATI = 5
_TIPI = {'movie': 'MOVIE', 'tvshow': 'SHOW'}
# La sentinella: The Matrix ha offerte con audio in tutti i 12 paesi provati il 24/09.
_SENTINELLA = ('movie', 603, 'tt0133093', 'The Matrix', ('US',))
_SENTINELLA_PROP = 'fenlight.justwatch.sentinella'

# Il limite del sito web di TMDb (passo 3): PAGINE_PER_FINESTRA ogni FINESTRA secondi. La finestra nostra e' di un
# secondo piu' larga della loro: i due orologi non partono insieme, e il margine evita i 429 al confine.
PAGINE_PER_FINESTRA = 10
FINESTRA = 11.0
_CLICK_RE = re.compile(r'https?://click\.justwatch\.com/a\?[^"\'\s<>]*')
_PREFISSI = {'movie': 'tm', 'tvshow': 'ts'}
_OFFERTE_TMDB = ('flatrate', 'free', 'ads', 'rent', 'buy')

_session = None
_lock = threading.Lock()
_ritmo = threading.Lock()
_finestra = [0.0, 0]   # inizio della finestra corrente, pagine gia' chieste in essa

def _posto_per_una_pagina():
	"""Aspetta, se serve, che nella finestra ci sia posto per una pagina, e lo prende."""
	with _ritmo:
		adesso = _time()
		if adesso - _finestra[0] >= FINESTRA: _finestra[:] = [adesso, 0]
		elif _finestra[1] >= PAGINE_PER_FINESTRA:
			_sleep(_finestra[0] + FINESTRA - adesso)
			_finestra[:] = [_time(), 0]
		_finestra[1] += 1

def _get_session():
	# Pigra (lotto 52: niente rete all'import) e sotto lucchetto: la chiamano i thread del preparatore insieme.
	global _session
	if _session is None:
		with _lock:
			if _session is None:
				from modules.kodi_utils import import_requests
				s = import_requests('justwatch_api').Session()
				s.headers.update({'Content-Type': 'application/json', 'Accept': 'application/json'})
				_session = s
	return _session

def _log(message):
	try:
		from modules.kodi_utils import logger
		logger('FenLight JUSTWATCH', message)
	except Exception: pass

def _offerte(paesi):
	return ' '.join('o_%s: offers(country:%s, platform:WEB){ monetizationType audioLanguages }' % (p, p) for p in paesi)

def _query(paesi):
	return ('query($s:String!,$t:[ObjectType!]){ popularTitles(country:US, first:%d, filter:{searchQuery:$s, objectTypes:$t})'
			'{ edges{ node{ objectType content(country:US, language:"en"){ externalIds{ tmdbId imdbId } } %s } } } }'
			% (_RISULTATI, _offerte(paesi)))

def _query_nodo(paesi):
	return 'query($id:ID!){ node(id:$id){ ... on MovieOrShow { objectType %s } } }' % _offerte(paesi)

def _risposta_valida(response):
	# Un 200 con "errors" e' uno schema cambiato o una domanda rifiutata: guasto della fonte, per l'interruttore
	# di http_client come per chi chiama. Nel dubbio si assume buona: non si apre un interruttore per un errore nostro.
	try: return not response.json().get('errors')
	except Exception: return True

def _base(codice):
	return (codice or '').lower().split('-')[0]

def _lingue(nodo, paesi):
	"""Le lingue audio (codici base) delle offerte di un titolo nei `paesi`, cinema esclusi."""
	return {_base(lingua) for p in paesi for offerta in (nodo.get('o_%s' % p) or ())
			if offerta.get('monetizationType') != 'CINEMA' for lingua in (offerta.get('audioLanguages') or ())} - {''}

def _chiedi(query, variabili):
	"""I dati di una domanda GraphQL. Solleva se non ha avuto risposta (rete, errore GraphQL, risposta malformata)."""
	response = _get_session().post(_URL, json={'query': query, 'variables': variabili}, timeout=_TIMEOUT, validate=_risposta_valida)
	response.raise_for_status()
	data = response.json()
	if data.get('errors'): raise ValueError('JustWatch: %s' % data['errors'][0].get('message'))
	return data['data']

def _cerca(media_type, tmdb_id, imdb_id, titolo, paesi):
	"""Passo 2: le lingue del titolo trovato con la ricerca e abbinato sugli id; None se la ricerca non lo trova."""
	voci = _chiedi(_query(paesi), {'s': titolo, 't': [_TIPI[media_type]]})['popularTitles']['edges']
	for voce in voci:
		nodo = voce['node']
		ids = (nodo.get('content') or {}).get('externalIds') or {}
		if nodo.get('objectType') != _TIPI[media_type]: continue
		if str(ids.get('tmdbId') or '') == str(tmdb_id) or (imdb_id and ids.get('imdbId') == imdb_id):
			return _lingue(nodo, paesi)
	return None

def _id_da_tmdb(media_type, link):
	"""Passo 3: l'id JustWatch del titolo, letto dai link della pagina web di TMDb. Solleva se non si legge."""
	import base64, json
	from html import unescape
	from urllib.parse import urlparse, parse_qs
	_posto_per_una_pagina()
	response = _get_session().get(link, headers={'Accept': 'text/html'}, timeout=_TIMEOUT)
	response.raise_for_status()
	for url in _CLICK_RE.findall(response.text):
		try:
			cx = parse_qs(urlparse(unescape(url)).query)['cx'][0]
			for contesto in json.loads(base64.urlsafe_b64decode(cx + '=' * (-len(cx) % 4))).get('data') or ():
				jw = (contesto.get('data') or {}).get('jwEntityId') or ''
				if jw.startswith(_PREFISSI[media_type]): return jw
		except Exception: continue
	raise ValueError('pagina TMDb senza id JustWatch: %s' % link)

def _dal_link(media_type, link, paesi):
	"""Passo 3 intero: id dalla pagina di TMDb, poi il titolo per id. Solleva se non si e' potuto sapere."""
	nodo = _chiedi(_query_nodo(paesi), {'id': _id_da_tmdb(media_type, link)})['node']
	if not nodo or nodo.get('objectType') != _TIPI[media_type]: raise ValueError('JustWatch: nodo assente o di altro tipo')
	return _lingue(nodo, paesi)

def _paesi_con_offerte(paesi, offerte_tmdb):
	"""Passo 1: (i paesi da chiedere, il link della pagina di TMDb per il passo 3). Con le offerte di TMDb in mano, solo
	i paesi che ne hanno -- nessuno vuol dire che JustWatch non ne ha -- e il link del primo; senza, tutti e nessun link."""
	paesi = tuple(p.upper() for p in paesi)
	if offerte_tmdb is None: return paesi, None
	con_offerte = tuple(p for p in paesi if any((offerte_tmdb.get(p) or {}).get(o) for o in _OFFERTE_TMDB))
	return con_offerte, ((offerte_tmdb.get(con_offerte[0]) or {}).get('link') if con_offerte else None)

def _lingue_del_titolo(media_type, tmdb_id, imdb_id, titolo, paesi, link=None):
	"""Le lingue audio delle offerte del titolo nei `paesi`, passi 2 e 3. set() se JustWatch non ne ha.

	`link` e' la pagina di TMDb del passo 3 (None: il passo si salta). Solleva se la domanda non ha avuto risposta.
	"""
	trovate = _cerca(media_type, tmdb_id, imdb_id, titolo, paesi) if titolo else None
	if trovate is not None: return trovate
	if link: return _dal_link(media_type, link, paesi)
	return set()

def _viva():
	from modules.sentinella import viva
	return viva(_SENTINELLA_PROP, lambda: _lingue_del_titolo(*_SENTINELLA), 'JustWatch, "The Matrix"', 'FenLight JUSTWATCH')

def lingue_audio(media_type, tmdb_id, imdb_id, titolo, lingue, paesi, offerte_tmdb=None):
	"""Quali delle `lingue` ('it', 'es', ...) JustWatch certifica come audio di un'offerta del titolo nei `paesi`.

	Un insieme, anche vuoto: vuoto vuol dire che JustWatch ha risposto e non certifica nessuna di quelle lingue (non
	ha il titolo, o le sue offerte non le hanno) -- ma vale solo se risponde la sentinella, oppure se TMDb dice gia'
	che nei paesi chiesti non ci sono offerte. None se non si e' potuto sapere: il chiamante non conclude e riprova.
	`offerte_tmdb`: i `results` di watch/providers di TMDb, se chi chiama li ha (vedi _lingue_del_titolo).
	"""
	if media_type not in _TIPI or not paesi: return None
	if not titolo and offerte_tmdb is None: return None
	lingue = {_base(l) for l in lingue}
	paesi, link = _paesi_con_offerte(paesi, offerte_tmdb)
	if not paesi: return set()   # passo 1: TMDb, che prende le piattaforme da JustWatch, non ha offerte nei paesi chiesti
	try: trovate = _lingue_del_titolo(media_type, tmdb_id, imdb_id, titolo, paesi, link) & lingue
	except Exception as e:
		_log('tmdb=%s "%s": nessuna risposta (%r)' % (tmdb_id, titolo, e))
		return None
	if trovate: return trovate
	return trovate if _viva() else None
