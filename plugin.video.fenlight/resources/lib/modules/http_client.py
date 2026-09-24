# -*- coding: utf-8 -*-
# Sostituto di requests.Session costruito su http.client (lotto 84).
#
# PERCHE'. Misurato: `import requests` tira dentro 337 moduli, `import http.client` ne tira 66. Sul
# Mi Stick, dove il costo di un import e' il NUMERO DI FILE aperti per la latenza del flash, questo e'
# il singolo capitolo piu' grosso rimasto: nella sessione del 25/08 requests e' stato importato 26
# volte in 10 minuti, a 4,7-10,3 s l'una -- circa 150 secondi su 590. E con
# reuselanguageinvoker=false ogni invocazione ricomincia da zero.
# Quello che si paga per niente: charset_normalizer (776 ms) e chardet/langrussianmodel (250 ms)
# servono a INDOVINARE la codifica di una risposta, e le nostre API dichiarano sempre UTF-8.
#
# COSA NON SI PERDE, perche' e' riprodotto qui dentro. requests non e' piu' veloce di http.client sul
# filo -- gli sta sopra, attraverso urllib3 -- ma aggiunge quattro cose che se sparissero
# peggiorerebbero la rete sul serio:
#   1. KEEP-ALIVE. Senza riuso della connessione ogni richiesta rifa' l'handshake TLS: su questa
#      stick sono 100-300 ms buttati per chiamata, e una costruzione ne fa decine. E' il motivo per
#      cui qui c'e' un pool per host e non una connessione usa-e-getta.
#   2. GZIP. requests chiede e decomprime da solo. Le risposte TMDb sono JSON grandi e comprimono
#      benissimo: toglierlo vorrebbe dire moltiplicare i byte sul filo.
#   3. REDIRECT.
#   4. RIPROVA su connessione stantia: un socket tenuto aperto puo' essere stato chiuso dall'altra
#      parte, e la prima scrittura fallisce. Senza la riprova il keep-alive diventa un generatore
#      di errori casuali.
#
# La superficie riprodotta e' solo quella davvero usata nel progetto, verificata sul sorgente:
# get/post/delete, kwargs params/data/json/headers/cookies/timeout, e sulla risposta
# .status_code .text .content .json() .headers .ok .raise_for_status().
import http.client
import json as _json
import gzip
import socket
import re as _re
from _thread import allocate_lock as Lock  # builtin, vedi la nota in caches/base_cache.py

DEFAULT_TIMEOUT = 20
MAX_REDIRECTS = 5
# LOTTO 343 -- quante connessioni verso UN server possono essere in uso insieme, in tutto l'interprete. Con HTTP/1.1
# una connessione porta una richiesta alla volta: senza tetto, 20 thread aprono 20 connessioni, e finito il
# picco restavano li'. Col tetto i thread in piu' ASPETTANO che una connessione si liberi invece di aprirne
# un'altra: poche connessioni, usate a fondo. Misurato il 24/09 sul Mac, 20 thread di rete e cache vuota, somma dei
# tempi delle quattro righe della Home (dalla richiesta alla consegna) e picco dei descrittori del processo (256):
#     senza tetto (20)  25,1-29,8 s   picco 207-211 file, 85-89 socket
#     12                25,0 s        picco 189 file, 67 socket
#     8                 37,7 s        picco 171 file, 49 socket
# 12 e' la stessa velocita' di nessun tetto con 20 descrittori in meno al picco; 8 costa un terzo del tempo.
# Referti in strumenti/diagnostica/referti/riempimento-341-C*.
CONNESSIONI_PER_HOST = 12
# Una connessione ferma da piu' di questi secondi si chiude. Fra una pagina e l'altra di un lavoro passano
# frazioni di secondo, quindi durante il traffico il riuso resta intero; finito il traffico, i socket spariscono
# invece di occupare descrittori finche' il server non li chiude lui (sul Mac il processo ne ha 256: 24/09, 60
# socket fermi su 177 descrittori).
SCADENZA_FERME = 5.0
USER_AGENT = 'Mozilla/5.0 (Linux; Android 9) FenLight'

# ---------------------------------------------------------------------------------------------
# LOTTO 93 -- POLITICA DEGLI ERRORI E INTERRUTTORE PER HOST
#
# Fino a qui ogni modulo si scriveva il suo `except`, e quasi tutti finivano in `return None`:
# tmdb_api ha `except: return None` in nove punti, skyhook `if status != 200: return None`,
# bluray_api cattura RequestException e poi Exception. Un timeout e un 404 sono indistinguibili,
# nessuno riprova, nessuno rinuncia, e la salute della rete non si legge da nessuna parte.
#
# Il peso non e' teorico. Nel log ze del 25/08 il filtro doppiaggio ha speso 57,6 secondi di sola
# ATTESA di blu-ray.com per 66 elementi su 3423 (0,87 s a elemento), piu' 29,8 s di import della
# pila HTTP. Con l'host irraggiungibile ogni elemento pagherebbe DEFAULT_TIMEOUT per intero: su una
# lista da 20 sono 400 secondi in cui la stick sembra bloccata.
#
# L'interruttore e' la risposta a quel caso: dopo BREAKER_FAILS guasti consecutivi verso un host si
# smette di provare per un po', e le chiamate successive falliscono SUBITO invece di aspettare il
# timeout. Il primo elemento paga, gli altri no.
#
# LO STATO STA IN UNA PROPRIETA' DI FINESTRA, e non e' un dettaglio: con
# reuselanguageinvoker=false ogni invocazione del plugin e' un processo Python NUOVO, quindi un
# contatore in memoria di modulo si azzererebbe a ogni build e l'interruttore non scatterebbe mai.
# Window(10000) e' l'unica memoria condivisa fra i processi che non costa I/O.
BREAKER_FAILS = 3            # guasti CONSECUTIVI prima di aprire (un successo azzera il contatore)
# Il primo passo e' corto di proposito: se l'interruttore si aprisse per sbaglio, 30 secondi sono un
# inciampo, non un guasto. I passi successivi salgono perche' a quel punto l'host e' morto davvero e
# risondarlo ogni mezzo minuto e' solo lavoro buttato.
BREAKER_STEPS = (30, 300, 900, 1800)
BREAKER_PROP = 'fenlight.net.brk.%s'
RETRY_FAST_ERRORS = 1        # riprove per i guasti che falliscono SUBITO (vedi _is_fast_failure)

# GERARCHIA DELLE ECCEZIONI. Tutte derivano da OSError, e la ragione e' di compatibilita': i
# chiamanti di oggi catturano `except:` nudo, `except Exception`, oppure socket.error/OSError.
# Derivando da OSError ogni handler esistente continua a comportarsi ESATTAMENTE come prima -- il
# guasto arriva solo molto piu' in fretta. Questo modulo e' stato gia' una volta la causa di una
# regressione silenziosa (il CaseInsensitiveDict del lotto 84/88): qui si aggiunge, non si cambia.
class NetworkError(OSError):
	"""Base di tutti i guasti di rete classificati."""

class TemporaryError(NetworkError):
	"""Timeout, connessione rifiutata/chiusa, DNS, 5xx. Ha senso riprovare."""

class Throttled(NetworkError):
	"""429/403 o risposta riconosciuta come blocco dal chiamante. NON riprovare subito."""

class PermanentError(NetworkError):
	"""4xx diverso da 403/408/429. L'host sta bene, la richiesta no."""

class ReteVietata(NetworkError):
	"""Questa invocazione non puo' andare in rete (lotto 333): vedi kodi_utils.vieta_rete."""

_VIETATE_SEGNALATE = set()

def _rete_vietata(url):
	# Si guarda kodi_utils solo se e' GIA' caricato: chi non l'ha importato non puo' aver vietato niente,
	# e importarlo qui costerebbe a ogni processo che usa il client.
	import sys
	ku = sys.modules.get('modules.kodi_utils')
	motivo = getattr(ku, 'RETE_VIETATA', (None,))[0] if ku else None
	if not motivo: return
	host = _split_url(url)[1]
	if host not in _VIETATE_SEGNALATE:
		_VIETATE_SEGNALATE.add(host)
		try: ku.logger('FenLight RETE VIETATA', '%s: richiesta a %s rifiutata (%s)' % (motivo, host, url[:120]))
		except Exception: pass
	raise ReteVietata('rete vietata in %s: %s' % (motivo, host))

class CircuitOpen(NetworkError):
	"""L'interruttore per quell'host e' aperto: si rinuncia senza toccare la rete."""

class HTTPError(Exception):
	def __init__(self, message, response=None):
		Exception.__init__(self, message)
		self.response = response

class _Exceptions:
	# Scorciatoia di compatibilita': bluray_api scrive gia'
	# `except _requests().exceptions.RequestException:`, che finora sollevava AttributeError ed era
	# salvato per caso dall'`except Exception` successivo. Ora risolve davvero.
	RequestException = NetworkError
	ConnectionError = TemporaryError
	Timeout = TemporaryError
	HTTPError = HTTPError

exceptions = _Exceptions()

class _Adapters:
	# Altra scorciatoia di compatibilita', e nasce da un guasto vero: bluray_api chiamava
	# `_requests().adapters.HTTPAdapter(pool_maxsize=8)`, che qui non esisteva. Sollevava
	# AttributeError dentro un try che finiva in `return None`, quindi l'interrogazione a
	# blu-ray.com e' stata spenta in silenzio dal lotto 84 al 93 senza che nulla lo dicesse.
	# La lezione: una superficie di compatibilita' incompleta non da' errore, da' comportamento
	# sbagliato. Qui l'adapter non deve fare nulla -- il pool per host c'e' gia' (_Pool, lotto 343) --
	# ma deve ESISTERE, cosi' che un chiamante scritto per requests non cada nel vuoto.
	class HTTPAdapter:
		def __init__(self, *args, **kwargs): pass

adapters = _Adapters()

class CaseInsensitiveDict(dict):
	# requests.Response.headers NON e' un dict normale: e' insensibile alle maiuscole, e il progetto ci
	# conta. Misurato il 25/08 (log zb): con un dict semplice a chiavi minuscole,
	# `resp_headers['X-Pagination-Page-Count']` in trakt_api solleva KeyError, la sincronizzazione crede
	# che ci sia UNA sola pagina e scarica 100 film invece di 598 -- poi set_bulk_movie_watched fa
	# DELETE+INSERT e i badge "visto" spariscono in massa. Lo stesso vale per 'X-Sort-By' e per
	# Content-Length/Accept-Ranges in downloader.py.
	# Le chiavi si conservano in minuscolo (come le restituisce http.client) e la ricerca normalizza.
	def __getitem__(self, key):
		return dict.__getitem__(self, key.lower() if isinstance(key, str) else key)

	def __setitem__(self, key, value):
		dict.__setitem__(self, key.lower() if isinstance(key, str) else key, value)

	def __contains__(self, key):
		return dict.__contains__(self, key.lower() if isinstance(key, str) else key)

	def get(self, key, default=None):
		return dict.get(self, key.lower() if isinstance(key, str) else key, default)

class Response:
	__slots__ = ('status_code', 'content', 'headers', 'url', 'encoding')

	def __init__(self, status_code, content, headers, url):
		self.status_code, self.content, self.headers, self.url = status_code, content, headers, url
		self.encoding = 'utf-8'

	@property
	def ok(self):
		return 200 <= self.status_code < 400

	@property
	def text(self):
		if not self.content: return ''
		# Nessun rilevamento di codifica: e' esattamente cio' che si e' voluto togliere. Si prende la
		# dichiarazione del server se c'e', altrimenti utf-8, e in caso di byte invalidi si sostituisce
		# invece di sollevare -- una pagina HTML sporca non deve far fallire una ricerca.
		charset = self.encoding
		try:
			ctype = self.headers.get('content-type') or ''
			if 'charset=' in ctype: charset = ctype.split('charset=')[1].split(';')[0].strip() or 'utf-8'
		except: pass
		try: return self.content.decode(charset, 'replace')
		except LookupError: return self.content.decode('utf-8', 'replace')

	def json(self):
		return _json.loads(self.text)

	def raise_for_status(self):
		if self.status_code >= 400:
			raise HTTPError('%s per %s' % (self.status_code, self.url), self)
		return self

# --- interruttore per host --------------------------------------------------------------------
_MEMORY_BREAKER = {}   # ricaduta quando non siamo dentro Kodi (test, uso del modulo da solo)

def _breaker_io():
	# Le proprieta' di finestra sono l'unica memoria condivisa fra le invocazioni. Import ritardato
	# e protetto: questo modulo deve restare importabile fuori da Kodi.
	try:
		from modules.kodi_utils import get_property, set_property, clear_property
		return get_property, set_property, clear_property
	except Exception:
		return (lambda k: _MEMORY_BREAKER.get(k, ''),
				lambda k, v: _MEMORY_BREAKER.__setitem__(k, v),
				lambda k: _MEMORY_BREAKER.pop(k, None))

def _net_log(message):
	try:
		from modules.kodi_utils import logger
		logger('FenLight NET', message)
	except Exception: pass

def _breaker_read(host):
	get_property, _, _ = _breaker_io()
	raw = get_property(BREAKER_PROP % host) or ''
	try:
		fails, until, level = raw.split('|')
		return int(fails), float(until), int(level)
	except Exception:
		return 0, 0.0, 0

def _breaker_write(host, fails, until, level):
	_, set_property, _ = _breaker_io()
	set_property(BREAKER_PROP % host, '%s|%s|%s' % (fails, until, level))

def breaker_check(host):
	# Chiamata PRIMA di aprire il socket. Solleva se l'interruttore e' aperto: e' tutto il guadagno,
	# perche' un timeout non consumato e' un timeout risparmiato.
	from time import time
	fails, until, level = _breaker_read(host)
	if until and time() < until:
		raise CircuitOpen('%s non raggiungibile, riprovo fra %d s' % (host, int(until - time())))
	return True

def breaker_success(host):
	# Un successo azzera tutto, LIVELLO COMPRESO. Volutamente: se l'host e' tornato, non deve
	# restare punito da guasti di mezz'ora fa. Il livello serve a punire l'insistenza, non la storia.
	fails, until, level = _breaker_read(host)
	if not (fails or until or level): return
	_, _, clear_property = _breaker_io()
	clear_property(BREAKER_PROP % host)
	if until: _net_log('%s risponde di nuovo, interruttore richiuso' % host)

def breaker_failure(host, reason):
	from time import time
	fails, until, level = _breaker_read(host)
	fails += 1
	if fails < BREAKER_FAILS:
		_breaker_write(host, fails, until, level)
		return
	# Si apre. Il livello sale a ogni apertura consecutiva, cosi' un host morto da un'ora non viene
	# risondato ogni minuto per sempre.
	step = BREAKER_STEPS[min(level, len(BREAKER_STEPS) - 1)]
	_breaker_write(host, 0, time() + step, level + 1)
	_net_log('%s: %s guasti consecutivi (ultimo: %s). Interruttore APERTO per %s s: le chiamate a '
			'questo host falliranno subito invece di aspettare il timeout.' % (host, fails, reason, step))

def breaker_state(host):
	"""Per la diagnostica e per chi deve decidere se vale la pena chiedere: (aperto, secondi_residui)."""
	from time import time
	_, until, _ = _breaker_read(host)
	if until and time() < until: return True, int(until - time())
	return False, 0

def _classify_status(status):
	if status < 400: return None
	if status in (408, 429): return Throttled if status == 429 else TemporaryError
	if status == 403: return Throttled
	if status >= 500: return TemporaryError
	return PermanentError

def _is_fast_failure(error):
	# Si riprova solo cio' che ha fallito SUBITO: connessione rifiutata, azzerata, DNS. Un TIMEOUT ha
	# gia' consumato l'intero budget, e riprovarlo raddoppia il caso peggiore -- che su questa stick e'
	# esattamente il sintomo da evitare. Misurato nel log ze: 0,87 s a elemento con la rete sana, ma
	# DEFAULT_TIMEOUT=20 s quando non risponde.
	if isinstance(error, socket.timeout): return False
	if isinstance(error, OSError) and 'timed out' in str(error).lower(): return False
	return isinstance(error, (socket.gaierror, ConnectionError, http.client.HTTPException, OSError))

def _encode_params(params):
	# Riusa l'urlencode che ci siamo gia' scritti (lotto 74): urllib.parse era stato tolto dall'albero
	# proprio per non pagarne i file, e non va rifatto entrare da qui. Import ritardato: kodi_utils
	# importa questo modulo, quindi a livello di modulo sarebbe un ciclo.
	from modules.kodi_utils import urlencode
	return urlencode(params)

class _Tetto:
	"""Semaforo contatore sui soli builtin di _thread (threading costa import: vedi caches/base_cache).

	I posti si passano DIRETTAMENTE al primo in attesa, in ordine d'arrivo: chi rilascia non rimette il posto
	in comune dove un nuovo arrivato potrebbe soffiarlo a chi aspetta da piu' tempo.
	"""
	def __init__(self, posti):
		self._liberi, self._lock, self._attese = posti, Lock(), []

	def prendi(self, attesa):
		with self._lock:
			if self._liberi > 0:
				self._liberi -= 1
				return True
			segnale = Lock(); segnale.acquire(); self._attese.append(segnale)
		if segnale.acquire(True, attesa): return True
		with self._lock:
			if segnale in self._attese:
				self._attese.remove(segnale)
				return False
		# Il posto e' arrivato insieme alla scadenza: rendi() l'ha gia' consegnato, quindi e' nostro.
		segnale.acquire()
		return True

	def rendi(self):
		with self._lock:
			if self._attese:
				self._attese.pop(0).release()
				return
			self._liberi += 1

	def in_uso(self, posti):
		with self._lock: return posti - self._liberi

_tetti, _tetti_lock = {}, Lock()

def _tetto(scheme, host, port):
	# Uno per server e per INTERPRETE, non per sessione: due sessioni verso lo stesso host (tmdb_api la crea
	# pigramente, e piu' thread possono crearla insieme) non devono raddoppiare le connessioni.
	chiave = (scheme, host, port)
	with _tetti_lock:
		t = _tetti.get(chiave)
		if t is None: t = _tetti[chiave] = _Tetto(CONNESSIONI_PER_HOST)
	return t

class NessunaConnessioneLibera(NetworkError):
	"""Tutte le connessioni verso l'host sono rimaste occupate per l'intero timeout. Non e' un guasto
	dell'host: e' coda nostra, e non conta per l'interruttore."""

class _Pool:
	# Le connessioni FERME di una sessione, per (schema, host, porta). Sostituisce l'HTTPAdapter(pool_maxsize=8)
	# che make_session montava su requests.
	# LOTTO 343 -- quelle IN USO le conta il tetto dell'host. Ogni prendi() va chiusa con release() (la
	# connessione torna ferma) o scarta() (la connessione e' stata chiusa): tutte e due rendono il posto.
	# Un posto non reso e' perso per sempre, e al CONNESSIONI_PER_HOST-esimo tutti aspettano: _attempt lo
	# garantisce con un finally. Il timeout non fa piu' parte della chiave: si imposta sulla connessione al
	# momento del riuso, cosi' un host ha UN gruppo di connessioni ferme e non uno per ogni timeout usato.
	def __init__(self):
		self._free, self._lock = {}, Lock()
		with _pool_lock: _pool_vivi.append(_ref(self))

	def _scadute(self, bucket, adesso):
		# Le ferme sono in ordine di rilascio: le piu' vecchie in testa.
		n = 0
		while n < len(bucket) and adesso - bucket[n][1] >= SCADENZA_FERME: n += 1
		scadute = [c for c, _t in bucket[:n]]
		del bucket[:n]
		return scadute

	def prendi(self, scheme, host, port, timeout, nuova=False):
		"""(connessione, riciclata). Aspetta un posto libero fino a `timeout`, poi NessunaConnessioneLibera.
		`nuova` salta le ferme: la si chiede dopo che una riciclata e' morta."""
		if not _tetto(scheme, host, port).prendi(timeout):
			raise NessunaConnessioneLibera('%s: %d connessioni occupate per %s s' % (host, CONNESSIONI_PER_HOST, timeout))
		key, conn, scadute = (scheme, host, port), None, []
		with self._lock:
			bucket = self._free.get(key)
			if bucket:
				scadute = self._scadute(bucket, _adesso())
				if bucket and not nuova: conn = bucket.pop()[0]   # la piu' recente: la piu' probabilmente viva
		_chiudi(scadute)
		if conn is not None:
			conn.timeout = timeout
			if conn.sock is not None: conn.sock.settimeout(timeout)
			return conn, True
		if scheme == 'https':
			return http.client.HTTPSConnection(host, port, timeout=timeout), False
		return http.client.HTTPConnection(host, port, timeout=timeout), False

	def release(self, scheme, host, port, timeout, conn):
		"""La connessione ha finito e resta aperta: torna ferma, e il posto si rende."""
		with self._lock:
			self._free.setdefault((scheme, host, port), []).append((conn, _adesso()))
		_tetto(scheme, host, port).rendi()

	def scarta(self, scheme, host, port):
		"""La connessione presa e' stata chiusa (errore, o il server ha detto Connection: close): si rende il posto."""
		_tetto(scheme, host, port).rendi()

	def svuota(self, scheme, host, port, timeout=None):
		"""Chiude le connessioni ferme di questo host: una di loro e' appena risultata morta (lotto 334)."""
		with self._lock:
			bucket = self._free.pop((scheme, host, port), [])
		_chiudi(c for c, _t in bucket)

	def chiudi_ferme(self, adesso):
		with self._lock:
			scadute = [c for b in self._free.values() for c in self._scadute(b, adesso)]
			for k in [k for k, b in self._free.items() if not b]: del self._free[k]
		_chiudi(scadute)

	def ferme(self):
		with self._lock: return sum(len(b) for b in self._free.values())

	def close_all(self):
		with self._lock:
			buckets, self._free = list(self._free.values()), {}
		_chiudi(c for b in buckets for c, _t in b)

def _chiudi(connessioni):
	for conn in connessioni:
		try: conn.close()
		except: pass

# I pool vivi di questo interprete, per la pulizia periodica. Riferimenti DEBOLI: un pool di una sessione che
# nessuno usa piu' deve poter sparire, e con lui i suoi socket.
from _weakref import ref as _ref
from time import monotonic as _adesso
_pool_vivi, _pool_lock = [], Lock()

def connessioni_ferme():
	"""Quante connessioni ferme tiene questo interprete. Zero = non c'e' niente da pulire, e chi aspetta puo'
	aspettare senza svegliarsi."""
	with _pool_lock: pool = [r() for r in _pool_vivi]
	return sum(p.ferme() for p in pool if p is not None)

def chiudi_connessioni_ferme():
	"""Chiude le connessioni ferme da piu' di SCADENZA_FERME. La chiama il preparatore quando resta senza lavoro."""
	adesso = _adesso()
	with _pool_lock:
		_pool_vivi[:] = [r for r in _pool_vivi if r() is not None]
		pool = [r() for r in _pool_vivi]
	for p in pool:
		if p is not None: p.chiudi_ferme(adesso)

# --- normalizzazione del request-target (lotto 260) ---------------------------------------------
# Il buco lasciato aperto dal lotto 84. requests non mandava l'URL sul filo come gli arrivava: lo
# passava per `requote_uri()`, che percent-codifica tutto cio' che in un request-target non ci puo'
# stare. Togliendo requests abbiamo tolto anche quello e nessuno l'ha rimpiazzato -- ma i chiamanti
# hanno continuato a costruire l'URL concatenando testo dell'utente (tmdb_api ha otto punti cosi').
#
# Cosa accadeva, misurato sul Mac il 13/09 con la ricerca testuale dell'hub:
#   'one piece' -> http.client.InvalidURL, "URL can't contain control characters (found at least
#                  ' ')". putrequest rifiuta qualunque carattere in [\x00-\x20\x7f]: la richiesta non
#                  partiva affatto, ed e' il motivo per cui nel log il fallimento arriva 40 ms dopo
#                  la TMDB CALL -- troppo presto per essere rete. InvalidURL deriva da HTTPException,
#                  quindi cadeva nell'except di _attempt: due riprove del tutto inutili (il guasto e'
#                  deterministico, non puo' che rifallire), un guasto contato dall'interruttore, e un
#                  TemporaryError che il bare-except di tmdb_api.get_tmdb riduceva a None. Da li'
#                  `get_tmdb(url).json()` -> AttributeError, la riga 'BUILD FALLITA' nel log, e
#                  zero risultati per qualunque ricerca di piu' di una parola.
#   'citta''    -> UnicodeEncodeError da _encode_request, che fa request.encode('ascii'). E' un
#                  ValueError, quindi l'except di _attempt NON lo prende: scavalcava classificazione
#                  e interruttore e usciva grezzo. Piu' insidioso del primo, e su un catalogo
#                  italiano non e' un caso limite.
# Per questo si corregge QUI e non nei chiamanti: il difetto e' del trasporto, i chiamanti che
# concatenano sono otto oggi e non si sa quanti domani, e soprattutto i redirect -- dove la Location
# la scrive il server -- non passerebbero da nessuna toppa messa in tmdb_api.
#
# COSA SI CONSIDERA SICURO. Lo stesso insieme di requests.utils.requote_uri: i non riservati di
# RFC 3986 (lettere, cifre, _.-~) piu' i riservati che nel target hanno un significato e non vanno
# toccati (!#$&'()*+,/:;=?@[]). Fuori restano lo spazio, i caratteri di controllo, " < > \ ^ ` { | }
# e tutto il non-ASCII, che diventano %XX dei loro byte UTF-8.
#
# IDEMPOTENTE, ed e' il requisito che conta davvero: qui passano URL che possono essere GIA' in parte
# codificati, perche' chi usa `params=` arriva dopo quote_plus. Un '%XX' valido si lascia com'e',
# quindi '%20' non diventa mai '%2520'.
# Sul '%' isolato ci discostiamo da requests, in meglio: requests lo lascia letterale e spedisce un
# escape malformato ('50% off' -> '50%%20off'), noi lo codifichiamo ('50%25%20off'). L'idempotenza
# regge perche' al secondo giro '%25' e' un escape valido e viene conservato.
#
# `re` non aggiunge un file all'albero degli import: http.client lo carica per conto suo.
_TARGET_SAFE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-~!#$&'()*+,/:;=?@[]"
_TARGET_SAFE_SET = frozenset(_TARGET_SAFE)
_HEXDIGITS = frozenset('0123456789abcdefABCDEF')
_PCT = ['%%%02X' % _i for _i in range(256)]
# Un solo passaggio in C per dire "non c'e' niente da fare", che e' il caso di ogni chiamata che non
# nasce da una ricerca: matcha qualsiasi carattere fuori dall'insieme sicuro, oppure un '%' NON
# seguito da due esadecimali (cioe' un escape da produrre, non uno da conservare).
_TARGET_DIRTY = _re.compile('[^%s%%]|%%(?![0-9A-Fa-f]{2})' % _re.escape(_TARGET_SAFE)).search

def _requote_target(path):
	if not _TARGET_DIRTY(path): return path
	out, i, n = [], 0, len(path)
	while i < n:
		ch = path[i]
		if ch == '%':
			if path[i+1:i+2] in _HEXDIGITS and path[i+2:i+3] in _HEXDIGITS:
				out.append(path[i:i+3]); i += 3; continue
			out.append('%25'); i += 1; continue
		if ch in _TARGET_SAFE_SET: out.append(ch)
		else: out.extend([_PCT[b] for b in ch.encode('utf-8')])
		i += 1
	return ''.join(out)

def _split_url(url):
	# Niente urllib.parse: vedi _encode_params. Lo scomponimento serve solo per http(s).
	scheme, _, rest = url.partition('://')
	scheme = scheme.lower()
	if not rest: scheme, rest = 'https', url
	netloc, sep, tail = rest.partition('/')
	path = (sep + tail) if sep else '/'
	if '@' in netloc: netloc = netloc.rsplit('@', 1)[1]
	host, _, port = netloc.partition(':')
	port = int(port) if port else (443 if scheme == 'https' else 80)
	return scheme, host, port, _requote_target(path or '/')

class _CookieJar:
	"""Barattolo dei cookie di sessione. LOTTO 93.

	requests.Session conserva i cookie fra una richiesta e l'altra; la nostra Session del lotto 84 NO,
	e questa e' stata la seconda meta' di un guasto durato nove lotti.

	Misurato il 25/08 contro blu-ray.com:
	  - richiesta alla pagina prodotto senza cookie  -> 200 con corpo 'error42' (7 byte)
	  - home page                                    -> Set-Cookie: pw_bottom_filter=none; firstview=1
	  - stessa pagina prodotto CON quei cookie       -> 200 con 524 KB e 'oswaldcollection' dentro
	Il sito rifiuta chi si presenta come visitatore senza stato, e lo fa con un 200 -- quindi nessun
	codice di stato lo rivelava. Con 'requests' non si notava perche' il barattolo c'era.

	Portata volutamente modesta: nome/valore, ambito per dominio, nessuna scadenza (durano quanto il
	processo, che con reuselanguageinvoker=false e' una singola invocazione) e nessun vincolo di path.
	Serve a tenere uno stato di sessione, non a essere un browser.
	"""
	__slots__ = ('_by_domain',)

	def __init__(self):
		self._by_domain = {}

	def store(self, host, set_cookie_values):
		for raw in set_cookie_values or ():
			if not raw: continue
			parts = raw.split(';')
			name, _, value = parts[0].strip().partition('=')
			if not name: continue
			domain = host
			for attr in parts[1:]:
				k, _, v = attr.strip().partition('=')
				if k.lower() == 'domain' and v:
					domain = v.strip().lstrip('.').lower()
			self._by_domain.setdefault(domain, {})[name] = value

	def header_for(self, host):
		# Si mandano i cookie del dominio esatto e di ogni suo dominio padre gia' visto.
		host = (host or '').lower()
		out = {}
		for domain, jar in self._by_domain.items():
			if host == domain or host.endswith('.' + domain):
				out.update(jar)
		if not out: return None
		return '; '.join('%s=%s' % (k, v) for k, v in out.items())

class Session:
	def __init__(self):
		self.pool = _Pool()
		self.headers = {}
		self.cookies = _CookieJar()

	# --- API pubblica, la stessa di requests per i soli usi presenti nel progetto ---------------
	def get(self, url, **kwargs): return self.request('GET', url, **kwargs)
	def post(self, url, **kwargs): return self.request('POST', url, **kwargs)
	def put(self, url, **kwargs): return self.request('PUT', url, **kwargs)
	def delete(self, url, **kwargs): return self.request('DELETE', url, **kwargs)
	def head(self, url, **kwargs): return self.request('HEAD', url, **kwargs)
	def close(self): self.pool.close_all()
	def mount(self, *args, **kwargs): pass   # compatibilita': make_session la chiamava su requests

	def request(self, method, url, params=None, data=None, json=None, headers=None,
				cookies=None, timeout=None, allow_redirects=True, validate=None, **_ignored):
		timeout = DEFAULT_TIMEOUT if timeout is None else timeout
		body, sent = None, dict(self.headers)
		sent.setdefault('User-Agent', USER_AGENT)
		sent['Accept-Encoding'] = 'gzip'
		if json is not None:
			body = _json.dumps(json).encode('utf-8')
			sent.setdefault('Content-Type', 'application/json')
		elif data is not None:
			if isinstance(data, (bytes, bytearray)): body = bytes(data)
			elif isinstance(data, str): body = data.encode('utf-8')
			else:
				body = _encode_params(data).encode('utf-8')
				sent.setdefault('Content-Type', 'application/x-www-form-urlencoded')
		if headers: sent.update(headers)
		# I cookie di sessione si accodano PRIMA di quelli espliciti: se il chiamante ne passa uno con
		# lo stesso nome (blu-ray.com riceve country= a ogni richiesta) deve vincere il suo.
		jar_header = self.cookies.header_for(_split_url(url)[1])
		if jar_header: sent['Cookie'] = jar_header
		if cookies:
			explicit = '; '.join('%s=%s' % (k, v) for k, v in cookies.items())
			sent['Cookie'] = ('%s; %s' % (jar_header, explicit)) if jar_header else explicit
		if params:
			query = _encode_params(params)
			if query: url = '%s%s%s' % (url, '&' if '?' in url else '?', query)
		return self._send(method, url, body, sent, timeout, allow_redirects, MAX_REDIRECTS, validate)

	# --- interno --------------------------------------------------------------------------------
	def _send(self, method, url, body, headers, timeout, allow_redirects, budget, validate=None):
		_rete_vietata(url)
		scheme, host, port, path = _split_url(url)
		# L'interruttore si consulta PRIMA di aprire il socket: e' qui che sta tutto il guadagno.
		breaker_check(host)
		response = self._attempt(method, scheme, host, port, path, body, headers, timeout)
		# CLASSIFICAZIONE. Un 404 non e' un guasto dell'host: la richiesta e' sbagliata, l'host sta
		# benissimo, e non deve contare per l'interruttore. Un 500 o un 429 si'.
		#
		# MA NON SI SOLLEVA MAI PER UN CODICE DI STATO, e questa e' una decisione, non una svista.
		# La prima stesura sollevava su 429/5xx, e avrebbe rotto tre chiamanti che oggi funzionano:
		#   - trakt_api guarda il 429 per leggere Retry-After, dormire e riprovare (riga 114);
		#     sollevando, il suo `except` lo trasformava in None e la gestione del rate limit spariva;
		#   - real_debrid controlla `status_code in (401, 403, 404)` (riga 117): il 403 non sarebbe
		#     mai arrivato;
		#   - imdb_api fa `if r.status_code != 200`.
		# La risposta torna al chiamante ESATTAMENTE come prima. L'interruttore invece prende nota:
		# per smettere di martellare un host morto non serve sollevare, serve contare.
		# Cosa conta per l'interruttore, e cosa no:
		#   - 5xx e 429: contano. L'host e' in difficolta' o ci sta dicendo di rallentare.
		#   - 403: NON conta. Sembra un bando ma quasi sempre non lo e': real_debrid lo usa come
		#     risposta normale (`status_code in (401, 403, 404)`), ed e' anche il "non autorizzato"
		#     di mezzo mondo. Farlo contare aprirebbe l'interruttore su un uso legittimo.
		#   - 4xx restanti: non contano, l'host sta bene.
		# Serve che siano CONSECUTIVI: un successo azzera il contatore, quindi durante una build in
		# cui quasi tutte le chiamate riescono il contatore non arriva mai a fondo. Tre di fila
		# significano davvero qualcosa.
		kind = _classify_status(response.status_code)
		if kind is TemporaryError or response.status_code == 429:
			breaker_failure(host, 'HTTP %s' % response.status_code)
		# Il chiamante puo' dichiarare che una risposta formalmente valida per lui e' un blocco:
		# blu-ray.com non manda un 429, manda 200 con una pagina di sbarramento. Riconoscerlo richiede
		# di guardare il CORPO, ed e' conoscenza del singolo sito -- non puo' stare qui dentro. Ma il
		# verdetto alimenta lo stesso interruttore condiviso, che e' il punto.
		if validate is not None and kind is None:
			try: good = validate(response)
			except Exception: good = True
			if not good:
				breaker_failure(host, 'risposta rifiutata dal chiamante')
				raise Throttled('%s: risposta %s non valida (blocco?)' % (host, response.status_code))
		if kind is None: breaker_success(host)
		if allow_redirects and response.status_code in (301, 302, 303, 307, 308) and budget > 0:
			location = response.headers.get('location')
			if location:
				if location.startswith('//'): location = '%s:%s' % (scheme, location)
				elif location.startswith('/'): location = '%s://%s:%s%s' % (scheme, host, port, location)
				# 303, e per convenzione anche 301/302 dopo un POST, proseguono in GET senza corpo.
				if response.status_code == 303 or (response.status_code in (301, 302) and method == 'POST'):
					method, body = 'GET', None
					headers = {k: v for k, v in headers.items() if k.lower() != 'content-type'}
				return self._send(method, location, body, headers, timeout, allow_redirects, budget - 1, validate)
		return response

	def _attempt(self, method, scheme, host, port, path, body, headers, timeout):
		# DUE riprove distinte, e la distinzione conta perche' costano in modo diverso:
		#
		# 1) CONNESSIONE RICICLATA MORTA. Un socket tenuto aperto puo' essere stato chiuso dall'altro capo
		#    mentre era fermo, e la prima scrittura fallisce. Non e' un guasto di rete e non conta per
		#    l'interruttore. (Lotto 84.)
		#    LOTTO 334 -- e non e' morta da sola. Le connessioni ferme di un host hanno la stessa eta', e il
		#    server le chiude tutte insieme: qui si riprovava con la SUCCESSIVA del pool, morta anche lei, e
		#    la riprova dei guasti veloci con una terza. Sulla stick, 16/09 19:52:14, la ricerca "go" e'
		#    fallita cosi' in 140 ms dopo un minuto di silenzio, senza aprire un solo socket. Ora si buttano
		#    le sorelle ferme e si riprova con una connessione NUOVA.
		#
		# 2) GUASTO CHE FALLISCE SUBITO (connessione rifiutata/azzerata, DNS) su una connessione nuova. Vale
		#    la pena riprovare una volta perche' costa poco. Un TIMEOUT invece NON si riprova: ha gia'
		#    consumato DEFAULT_TIMEOUT e riprovarlo raddoppierebbe il caso peggiore, che su questa stick e'
		#    esattamente il sintomo da evitare. (Lotto 93, vedi _is_fast_failure.)
		fast_retries, nuova = 0, False
		while True:
			conn, reused = self.pool.prendi(scheme, host, port, timeout, nuova)
			reso = False   # LOTTO 343: il posto del tetto si rende UNA volta, in qualunque modo si esca
			try:
				conn.request(method, path, body=body, headers=headers)
				raw = conn.getresponse()
				payload = raw.read()
				raw_headers = raw.getheaders()
				status, hdrs = raw.status, CaseInsensitiveDict((k.lower(), v) for k, v in raw_headers)
				# I Set-Cookie si raccolgono dalla LISTA, non dal dict: sono spesso piu' d'uno e il
				# dict ne terrebbe solo l'ultimo. (blu-ray.com ne manda due.)
				self.cookies.store(host, [v for k, v in raw_headers if k.lower() == 'set-cookie'])
				if hdrs.get('content-encoding', '').lower() == 'gzip' and payload:
					try: payload = gzip.decompress(payload)
					except: pass
				if hdrs.get('connection', '').lower() == 'close':
					try: conn.close()
					except: pass
					self.pool.scarta(scheme, host, port)
				else:
					self.pool.release(scheme, host, port, timeout, conn)
				reso = True
				return Response(status, payload, hdrs, '%s://%s%s' % (scheme, host, path))
			except (http.client.HTTPException, socket.error, OSError) as error:
				try: conn.close()
				except: pass
				self.pool.scarta(scheme, host, port); reso = True
				if reused:
					self.pool.svuota(scheme, host, port, timeout)
					nuova = True
					continue
				if _is_fast_failure(error) and fast_retries < RETRY_FAST_ERRORS:
					fast_retries += 1; nuova = True; continue
				# Guasto vero: alimenta l'interruttore e si presenta classificato. TemporaryError
				# deriva da OSError, quindi ogni `except` gia' scritto nei chiamanti lo cattura
				# esattamente come prima -- cambia solo che ora sappiamo COSA e' successo.
				breaker_failure(host, type(error).__name__ or 'errore di trasporto')
				raise TemporaryError('%s: %s' % (host, error)) from error
			finally:
				if not reso:
					# Uscita imprevista (un'eccezione che non e' di trasporto): la connessione e' in uno stato
					# che non si conosce, quindi si chiude, e il posto si rende comunque.
					try: conn.close()
					except: pass
					self.pool.scarta(scheme, host, port)
