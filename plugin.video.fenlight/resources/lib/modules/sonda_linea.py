# -*- coding: utf-8 -*-
# SONDA DELLA LINEA -- lotto 222. Fase 4.
#
# COSA MISURA, e in cosa differisce da tutto cio' che c'e' stato prima. Non misura il buffer di
# Kodi: misura la LINEA, con una richiesta nostra, su byte nostri, col nostro orologio. Nessuno dei
# due bordi che hanno tenuto occupati gli otto lotti da 214 a 221 -- sopra il tetto Kodi si strozza
# da solo, sotto il pavimento il buffer non puo' scendere -- perche' qui non c'e' nessun buffer.
#
# QUANDO PARTE (lotto 230, e le tre collocazioni precedenti erano tutte sbagliate). Subito dopo che
# TorBox ha detto quali sorgenti sono in cache, prima che il filtro della dimensione decida.
# L'utente aspetta cinque secondi in piu' e in cambio il filtro decide su un numero misurato adesso.
#
# Perche' proprio li', e non altrove:
#   - lotto 222, DENTRO lo scraping: gli scraper sono richieste piccole e la banda e' ferma, vero;
#     ma la CPU no. Tutti i sotto-interpreti di Kodi si dividono un core, e la sonda prendeva il 10-25%
#     di quel core dichiarando 8,0 e 26,0 Mbit/s su una linea da 45. Misurava se stessa.
#   - lotto 225, NEL SERVIZIO: puo' aspettare un momento con la CPU libera, ma non sa mai quando
#     l'utente fara' partire un film. Tre sonde su quattro sono state abbandonate a meta'.
#   - QUI la CPU e' libera (gli scraper hanno finito), la rete e' libera (la risoluzione non e'
#     ancora partita), e soprattutto la misura arriva **quando serve**, non quando capita.
#
# SU QUALE FILE. Sulla prima sorgente in cache nell'ordine dell'autoplay, cioe' quella che partirebbe.
# Il link risolto per sondarla viene riusato per riprodurla: cosi' una parte dell'attesa non e'
# aggiunta, e' anticipata. E il nodo che misuriamo e' lo stesso che consegnera' il film.
#
# ATTENZIONE -- IL PRECEDENTE NEGATIVO. modules/band_probe.py e' la sonda dei lotti 191-195,
# staccata perche' non prediceva: il 07/09 dichiarava 3,39 Mbit/s e mezzo secondo dopo Kodi, sullo
# STESSO nodo, ne consegnava 11,16. Sappiamo adesso che quel numero era un artefatto di CPU, non del
# cdn. Ma la sua obiezione di fondo -- "misuri una connessione diversa da quella che riproduce" --
# qui non si applica proprio: e' la stessa sorgente, lo stesso nodo, lo stesso lettore.
#
# SOLO MISURA E FILTRO. La sonda non scarta niente da sola: produce una capacita', e chi filtra la
# divide per MARGINE. Quel margine e' l'unico numero ancora da guadagnare sui dati.
import http.client
from random import uniform
from time import monotonic as orologio, perf_counter, process_time, thread_time, time as adesso

# LOTTO 224 -- 256 KB, non 8. Il controllo dal Mac ha letto lo STESSO link con lo STESSO codice a
# 212-224 Mbit/s a qualunque profondita', mentre sulla stick la stessa sonda leggeva 3-4: il collo
# di bottiglia non e' ne' il cdn ne' il link, e' la lettura dentro il processo di Kodi. A 8 KB per
# giro una linea da 46 Mbit/s costa 700 iterazioni al secondo di ciclo Python -- ognuna con una
# allocazione, una copia e un rilascio del GIL -- dentro un interprete dove nello stesso momento
# venti thread di scraper stanno analizzando JSON. A 256 KB i giri diventano 22 e si legge con
# readinto() dentro un buffer riusato, quindi senza allocare.
# Il passo grosso non toglie risoluzione dove serve: 256 KB a 46 Mbit/s sono 45 ms, contro un
# bucket di 500. Su una linea da 3 Mbit/s sono 700 ms, e li' la curva e' grossolana -- ma una linea
# da 3 Mbit/s la sonda la riconosce comunque.
PASSO = 262144
BUCKET = 0.5              # passo della curva
# LOTTO 230 -- I TRE NUMERI CHE COSTANO TEMPO ALL'UTENTE, e vengono dalle curve vere.
#
# QUANTO DURA LA FINESTRA. Facendo scorrere una finestra di lunghezza L dentro le quattro curve
# misurate e confrontandola col regime dell'intera curva, l'errore e':
#     1 s -> 37% peggiore, 7,0% medio | 2 s -> 23% / 5,3% | 3 s -> 16% / 4,8%
#     4 s -> 11% / 4,0%  |  5 s -> 8,6% / 3,5%  |  8 s -> 4,9% / 2,3%  |  10 s -> 4,7% / 1,8%
# Sopra i sei secondi la curva e' piatta e si paga attesa per niente. Cinque secondi, deciso
# dall'utente: 8,6% nel caso peggiore, 3,5% tipico. E gli errori sono quasi tutti VERSO IL BASSO,
# cioe' una finestra corta sottostima -- sbaglia dalla parte prudente.
#
# QUANTO DURA LA RAMPA. Il primo pezzo da PASSO byte e' gia' scartato prima che parta il cronometro,
# e quello si porta via quasi tutta la salita del tcp: nel primo secondo dopo di lui le quattro
# curve stanno a -0%, -0%, -13%, -12% dal regime. Un secondo basta; i due del lotto 222 erano
# attesa regalata.
SECONDI_SALITA = 1.0
SECONDI_MINIMI = 4.0      # meno di cosi' di regime non e' una misura: si dichiara None
SECONDI_TOTALI = 6.0      # rampa + finestra: e' il tempo che l'utente paga
BYTE_MASSIMI = 160 * 1024 * 1024   # tetto duro, per non restare attaccati a una linea velocissima
TIMEOUT = 8               # per singola operazione di socket
REDIRECT = 4

# LOTTO 230 -- L'ABBANDONO NON HA PIU' UNA CODA DA SALVARE.
#
# Fino al lotto 229 la sonda girava in sfondo e poteva essere sorpresa da un film che partiva: gli
# ultimi secondi erano concorrenza nostra e si scartavano (`CODA_ABBANDONO`), tenendo il resto.
# Adesso la sonda e' SINCRONA e sta dentro la ricerca sorgenti: mentre legge, nessuna riproduzione
# puo' partire, perche' e' lo stesso thread che la farebbe partire.
#
# Resta un solo motivo per mollare: l'utente che annulla la ricerca. E li' la misura non serve piu' a
# nessuno, quindi non si salva niente -- si smette di leggere e basta.
# DOVE si legge dentro il file. Non in testa, e non e' piu' una questione di velocita' del cdn (il
# lotto 227 ha dimostrato che la profondita' non conta): e' che la testa e' proprio la parte che il
# film sta per leggere. Sondarla la scalderebbe nel nodo di bordo, la riproduzione partirebbe piu'
# veloce del normale, e la TARATURA DEL MARGINE ne uscirebbe falsata verso il basso -- cioe' verso
# il meno sicuro. Si legge fra il 10% e il 25%: lontano dall'inizio, dentro la parte che il film
# attraversera' comunque.
FRAZIONE_MIN, FRAZIONE_MAX = 0.10, 0.25

# IL MARGINE. La sonda misura una CAPACITA'; `line_speed` e' cio' che un film puo' chiedere senza
# soffrire, ed e' piu' basso -- 24 MB di buffer sono meno di cinque secondi a 40 Mbit/s, e un cdn non
# consegna liscio.
#
# QUESTO NUMERO NON E' ANCORA GUADAGNATO SUI DATI, ed e' l'unica cosa che resta da fare. Viene da due
# indizi: la curva di salute misurata sulla stick (fluida fino a ~34 Mbit/s, in affanno da ~40, su
# una linea che la sonda misura a ~46) e il rapporto portata/sonda osservato, 1,04-1,08. Entrambi
# collocano il margine fra 1,15 e 1,4; 1,25 sta in mezzo ed e' prudente.
#
# Si tara cosi': ogni riproduzione lascia in archivio `bitrate` e `sonda_mbps`; si ordina il loro
# rapporto (playback_stats.rapporto_sonda) su venti-trenta righe indipendenti e si guarda dove le
# righe sane finiscono e cominciano quelle sofferenti. Quel confine e' 1/MARGINE.
MARGINE = 1.25

# LOTTO 225 -- QUANTA CPU RIUSCIAMO A OTTENERE ADESSO. E' la misura che mancava, e senza di lei
# ogni numero di questa sonda e' ambiguo.
#
# Su questo Android il Python di Kodi vive in UN processo e tutti i sotto-interpreti si dividono UN
# core: la quota di ciascuno e' circa 1/N (misurato il 08/09: 6 interpreti -> 16%, 4 -> 25%, da solo
# -> 86%). La sonda decifra TLS, quindi legge al massimo ~90-100 Mbit/s con un core intero: con un
# quarto di core il tetto scende a 25 e la sonda misura se stessa invece della linea.
#
# E il rapporto cpu/tempo della sonda NON basta a distinguere i due casi: se leggiamo 26 Mbit/s
# perche' la linea fa 26, la cpu consumata e' la stessa che se ne leggessimo 26 perche' abbiamo un
# quarto di core. I due casi hanno la stessa firma. L'unico modo di separarli e' misurare la quota
# disponibile con un ciclo che NON fa I/O -- questo -- e confrontarla.
QUOTA_CAMPIONE = 0.05     # secondi di cpu da bruciare per avere una lettura
QUOTA_ATTESA_MAX = 1.5    # se non li ottiene entro qui, la macchina e' occupata e tanto basta
# LOTTO 226 -- 0,75 e non 0,55, e il numero viene da una misura. La prima sonda buona (10/09,
# 42,77 Mbit/s) ha consumato 97 ms di cpu per MB: tetto 82,7 Mbit/s con un core intero, quindi
# 45,5 con la quota minima di allora. Ha letto 42,77 contro un tetto di 45,5: **2,7 Mbit/s di
# margine**, cioe' era gia' quasi contro il muro -- e infatti la riproduzione, subito dopo, ha
# misurato 45,4. Il numero era un pavimento travestito da misura.
# Con 0,75 il tetto effettivo sale a ~62 Mbit/s, che lascia spazio vero sopra una linea da 45.
# Il prezzo e' che la sonda parte piu' di rado; ma il servizio non ha nessuno che lo aspetta, e una
# sonda in meno costa molto meno di una sonda che mente.
# LOTTO 238 -- QUESTA COSTANTE ERA DICHIARATA E NON USATA DA NESSUNO, e nel frattempo il caso che
# doveva coprire e' successo davvero. Il 10/09 alle 22:02, sulla stick, con quota 27%:
#
#     REGIME 6.62 Mbit/s   (la stessa linea, due minuti dopo: 46,23)
#     curva  0.8 1.0 1.2 1.8 2.0 2.5 3.0 3.2 3.8 4.2 4.5 4.8    <- a scatti, 3x fra bucket vicini
#     cpu    consumo 9% | quota 27% | processo 185%
#
# La misura e' stata PUBBLICATA: il filtro ha lavorato con line_speed 5,3 e la lista delle sorgenti
# si e' svuotata. _limitata_da_cpu non l'ha fermata perche' cerca consumo/quota >= 0,95 e li' era
# 0,33: il suo presupposto e' che la fame di cpu si veda come consumo ALTO.
#
# PER UN THREAD CHE FA I/O NON E' COSI'. Il GIL conteso non toglie cicli, toglie OCCASIONI: fra due
# recv() il thread aspetta di riprendere il lucchetto, il socket non viene svuotato, la finestra TCP
# si chiude. Portata e consumo crollano INSIEME, e il loro rapporto resta innocente. La prova che
# non e' un tetto di decifratura: 27% di 74 Mbit/s fa 20, e la sonda ne ha letti 6,62, un terzo.
# Nessun prodotto tetto x quota spiega quel numero -- l'unica grandezza che separa quella sonda
# dalle altre cinque della serata e' la quota nuda.
#
# 0,60 e' EMPIRICO e non lo nascondo: le sei sonde della serata stanno a 27, 70, 74(*), 76, 78, 80,
# 81, 86, 87, 95 di quota e la soglia sta nel vuoto fra 27 e 70, verso l'alto. Sotto non ci sono
# misure buone da difendere; sopra non ce ne sono di cattive da scartare. Il vuoto in mezzo non l'ha
# mai visitato nessuno.
# L'ASIMMETRIA decide da che parte sbagliare: scartare costa un ripiego sull'impostazione dell'utente
# -- un numero conservativo e noto -- mentre tenere una misura falsa svuota la lista o fa stallare un
# film. Quindi si scarta con generosita'.
# Vale per ENTRAMBI i lettori, e questa e' una scelta prudente non una misura: anche il lettore di
# Kodi legge dentro un ciclo Python, quindi anche lui dipende da quanto spesso quel thread viene
# schedulato. Che CCurlFile lo assorba meglio e' plausibile e non l'ho verificato.
QUOTA_MINIMA = 0.60
# QUANDO UNA LETTURA E' LIMITATA DALLA CPU, e perche' la risposta dipende da CHI ha letto.
#
#   Lettore di KODI: decifra in C++ col GIL rilasciato, quindi il GIL non lo tocca. L'unico modo in
#     cui puo' essere limitato e' saturare un core: `consumo` (cpu del thread / tempo) vicino a 1.
#   Lettore PYTHON: puo' essere limitato in DUE modi -- il core saturo, e il GIL conteso dagli altri
#     interpreti. Il secondo non si vede dal consumo (0,10 puo' voler dire "linea lentissima" o
#     "un decimo di core"): si vede solo confrontando il consumo con la quota disponibile.
#
# Un solo numero non copre i due casi, e usarne uno solo li' dove non vale e' il modo in cui una
# misura sbagliata passa per buona.
CONSUMO_SOSPETTO = 0.85     # sopra: e' un minimo, si avvisa
CONSUMO_LIMITE = 0.95       # sopra: non e' una misura


def quota_cpu(campione=QUOTA_CAMPIONE):
	"""Frazione di un core che questo thread riesce a ottenere adesso, 0..1.

	Ciclo occupato puro, niente rete: e' esattamente la grandezza che la sonda non puo' dedurre da
	se stessa. Costa `campione` secondi di cpu -- 50 ms -- e li spende una volta per sonda.
	"""
	try:
		_t0, _c0 = orologio(), thread_time()
		_scade = _t0 + QUOTA_ATTESA_MAX
		while thread_time() - _c0 < campione:
			if orologio() > _scade: break
		_w = orologio() - _t0
		return ((thread_time() - _c0) / _w) if _w > 0 else 0.0
	except: return 1.0    # non misurabile: non si blocca la sonda per uno strumento rotto


# LA SONDA SI ABBANDONA APPENA UN FILM PARTE, e non e' una cortesia: la banda che prende e' quella
# che il film sta usando. Cio' che e' stato letto PRIMA dell'avvio resta valido: si tronca, non si
# butta via del tutto: chi ha annullato non vuole una misura. Chi la chiama passa `molla`.


# ---- i due lettori --------------------------------------------------------------------------
# LOTTO 227 -- LEGGERE CON KODI, NON CON PYTHON, e la ragione e' un numero.
#
# La prima sonda buona ha consumato 97 ms di cpu per MB: il modulo `ssl` di Python su questa stick
# decifra AES a **10,3 MB/s**, cioe' 82 Mbit/s con un core intero e basta. Non e' un problema di
# GIL da aggirare mettendoci piu' thread: e' proprio il costo della decifratura, e su quattro core
# non si distribuisce -- una connessione sola vive in un thread solo.
#
# Kodi lo stesso https lo legge a 46 Mbit/s mentre riproduce. Quindi il lettore giusto ce l'abbiamo
# gia' in casa: `xbmcvfs.File` e' la stessa CCurlFile che apre il film. Tre vantaggi, e il terzo e'
# quello che conta di piu':
#   1. decifra in C++, con il GIL RILASCIATO: un core libero diventa davvero utilizzabile;
#   2. usa la libreria TLS di Kodi, che sulla piattaforma puo' avere l'accelerazione hardware che
#      il Python di Kodi non ha;
#   3. e' **lo stesso percorso di codice che riprodurra' il film**. Una sonda che misura la strada
#      vera vale piu' di una che ne misura una parallela: e' l'obiezione con cui e' morta la sonda
#      dei lotti 191-195, e qui cade da sola.
#
# Il lettore Python resta come RIPIEGO e come banco di prova: e' quello che le prove sanno guidare
# con una rete finta, e se un giorno xbmcvfs non aprisse un link la sonda non deve sparire.
#
# Cosa si perde: con xbmcvfs non si vede il nodo finale dopo i redirect, quindi `cdn` e' l'host
# chiesto e non quello che ha risposto. E non si vede lo stato HTTP: un link scaduto si presenta
# come "non si apre", che per noi vuol dire la stessa cosa.

def _limitata_da_cpu(esito):
	"""Il motivo per cui questa lettura non e' una misura della linea, o None.

	INVARIANTE, nello spirito di portata_secchi: una lettura fatta senza cpu NON descrive la linea e
	non deve poter arrivare al wizard travestita da tale. Il 10/09 due sonde hanno dichiarato 26,0 e
	8,01 Mbit/s su una linea da 45: erano esattamente 0,25 e 0,10 del tetto di decifratura.
	"""
	try:
		# LOTTO 238 -- PRIMA DI TUTTO IL RESTO: con troppo poca cpu disponibile la lettura non
		# descrive la linea, e non serve sapere che cosa stesse occupando la macchina. E' l'unica
		# guardia che non ha bisogno di una diagnosi, ed e' per questo che sta in cima.
		_quota = esito.get('quota')
		if _quota is not None and _quota < QUOTA_MINIMA:
			return 'cpu contesa (quota %.0f%%, sotto il %.0f%% minimo)' % (_quota * 100, QUOTA_MINIMA * 100)
		_sec, _cpu = esito.get('secondi') or 0, esito.get('cpu')
		if not _sec or _cpu is None: return None
		_consumo = _cpu / _sec
		# Un thread non puo' superare un core: consumo vicino a 1 vuol dire che il core e' il
		# vincolo, e vale per QUALUNQUE lettore.
		if _consumo >= CONSUMO_LIMITE:
			return 'cpu satura (%.0f%% di un core)' % (_consumo * 100)
		# Solo per il lettore Python: il GIL. Col lettore di Kodi la quota misura una cosa che non
		# c'entra -- il tempo di Python -- e confrontarla col consumo darebbe rapporti sopra 1.
		if esito.get('lettore') == '_LettorePython':
			if _quota and _consumo / _quota >= CONSUMO_LIMITE:
				return 'GIL conteso (%.0f%% di quota, consumata tutta)' % (_quota * 100)
		return None
	except: return None


def _host(url):
	"""L'host chiesto. Col lettore di Kodi non si vede quello che risponde dopo i redirect."""
	try:
		from modules.http_client import _split_url
		return _split_url(url)[1]
	except: return None


def _apri_lettore(url, offset, lettore_classe, fuori):
	"""Chi legge, e la scelta e' cambiata al lotto 232 su una misura.

	Il lotto 227 aveva scelto il lettore di Kodi perche' decifra in C++ e costa meno cpu: 78 ms per
	MB contro 96, cioe' un tetto di 107 Mbit/s contro 82. Vero, ma il ttfb spezzato in tre (lotto
	231) ha mostrato il conto vero:

	    apertura 1098 ms  +  POSIZIONAMENTO 2263 ms  +  primo pezzo 102 ms

	`xbmcvfs.File` non sa aprire gia' a un offset: si apre, e poi si fa `seek()`, che su un file http
	e' una seconda richiesta con un secondo handshake. Il posizionamento da solo si mangia il 55-72%
	dell'attesa, e l'attesa e' tempo che l'utente paga SENZA misurare.

	Il lettore Python la Range la mette nella PRIMA richiesta: un giro solo, ttfb misurato 604-1077
	ms. Costa il 23% di cpu in piu', ma su una linea da 47 Mbit/s il consumo passa dal 45% al 55% di
	un core -- dentro la quota misurata (76-95%) e con `_limitata_da_cpu` a fare da guardia.

	Serve pero' conoscere l'offset PRIMA di aprire, quindi la dimensione va saputa in anticipo: la
	da' `item['size']` dello scraper. Quando non c'e' si ripiega sul lettore di Kodi, che la
	dimensione la sa dopo l'apertura e paga il seek. Stesso ripiego se la Range non viene onorata --
	`item['size']` e' stato trovato sbagliato di 25 volte (lotto 192), e un offset oltre la fine del
	file torna 416.
	"""
	if lettore_classe is not None: return lettore_classe(url, offset)
	if offset is not None:
		try: return _LettorePython(url, offset)
		except Exception as e: fuori['ripiego'] = 'Python: %s: %s' % (type(e).__name__, e)
	return _LettoreKodi(url, offset)


class _LettoreKodi:
	"""Il lettore di Kodi. `leggi(n)` torna quanti byte sono arrivati."""
	def __init__(self, url, offset=None):
		import xbmcvfs
		self.f = xbmcvfs.File(url)
		try: self.dimensione = self.f.size() or None
		except: self.dimensione = None

	def posiziona(self, offset):
		if offset: self.f.seek(offset, 0)

	def leggi(self, quanti):
		_b = self.f.readBytes(quanti)
		return len(_b) if _b else 0

	def chiudi(self):
		try: self.f.close()
		except: pass


class _LettorePython:
	"""http.client a mano. Ripiego, e l'unico che le prove sanno guidare."""
	def __init__(self, url, offset=None):
		self.offset = offset or 0
		self.conn, self.resp, self.host = _apri(url, self.offset)
		if self.resp is None: raise IOError('nessuna risposta')
		self.stato = self.resp.status
		# Con un offset chiesto, 200 vuol dire che la Range NON e' stata onorata e staremmo leggendo
		# la testa del file -- proprio cio' che non vogliamo scaldare. 416 vuol dire che l'offset era
		# oltre la fine, cioe' che `item['size']` mentiva. Entrambi si rifiutano: se ne occupa il
		# ripiego, che apre con Kodi e cerca.
		if self.offset and self.stato != 206: raise IOError('range non onorata (stato %s)' % self.stato)
		if self.stato not in (200, 206): raise IOError('stato %s' % self.stato)
		self.dimensione = self._totale()
		self.vista = memoryview(bytearray(PASSO))

	def _totale(self):
		"""La dimensione VERA dal Content-Range, che la stessa richiesta porta a casa gratis."""
		try:
			_cr = self.resp.getheader('Content-Range')
			if _cr and '/' in _cr:
				_coda = _cr.rsplit('/', 1)[1].strip()
				if _coda.isdigit(): return int(_coda)
			return int(self.resp.getheader('Content-Length') or 0) or None
		except: return None

	def posiziona(self, offset):
		pass       # l'offset e' gia' nella Range della richiesta: qui non si puo' riposizionare

	def leggi(self, quanti):
		return self.resp.readinto(self.vista[:quanti])

	def chiudi(self):
		try:
			if self.conn: self.conn.close()   # senza drenare: si abbandona
		except: pass


def _apri(url, offset):
	"""(conn, resp) con Range dall'offset. Redirect seguiti a mano: urllib tirerebbe dentro email.*."""
	from modules.http_client import _split_url
	giri = REDIRECT
	while True:
		scheme, host, port, percorso = _split_url(url)
		cls = http.client.HTTPSConnection if scheme == 'https' else http.client.HTTPConnection
		conn = cls(host, port, timeout=TIMEOUT)
		conn.request('GET', percorso, headers={'Range': 'bytes=%d-' % offset,
											   'Accept-Encoding': 'identity',
											   'User-Agent': 'Mozilla/5.0', 'Connection': 'close'})
		resp = conn.getresponse()
		if resp.status in (301, 302, 303, 307, 308) and giri > 0:
			dove = resp.getheader('Location')
			conn.close()
			if not dove: return None, None, host
			if dove.startswith('/'): dove = '%s://%s:%s%s' % (scheme, host, port, dove)
			url, giri = dove, giri - 1
			continue
		return conn, resp, host


def offset_per(dimensione):
	"""Dove aprire la lettura: fra FRAZIONE_MIN e FRAZIONE_MAX del file. Vedi le costanti."""
	try:
		if not dimensione: return 0
		return int(dimensione * uniform(FRAZIONE_MIN, FRAZIONE_MAX))
	except: return 0


def misura(url, offset=None, molla=None, lettore_classe=None, dimensione=None):
	"""Legge fino a SECONDI_TOTALI e restituisce il regime. Non solleva mai.

	`molla` e' una funzione senza argomenti: quando torna True la lettura si abbandona (oltre il
	pavimento utile). Serve al servizio, che vive in un altro interprete e non condivide _FERMA.
	"""
	# Tutti i campi si dichiarano QUI, anche quelli che verranno riempiti in fondo: su un percorso
	# di errore la funzione esce prima, e chi legge il risultato non deve dover indovinare quali
	# chiavi esistono. None vuol dire 'non misurato', mai 'misurato zero'.
	fuori = {'ok': False, 'stato': None, 'ttfb': None, 'byte': 0, 'secondi': 0.0,
			 'lorda': None, 'regime': None, 'regime_secondi': 0.0, 'offset': offset,
			 'cdn': None, 'curva': [], 'chiuso': None, 'errore': None,
			 'cpu': None, 'cpu_processo': None, 'quota': None, 'quando': None,
			 'lettore': None, 'ripiego': None,
			 't_apertura': None, 't_posizione': None, 't_primo': None,
			 'dimensione_attesa': dimensione, 'dimensione_vera': None}
	lettore = None
	try:
		t0 = perf_counter()
		fuori['cdn'] = _host(url)
		# L'offset PRIMA di aprire, se la dimensione la sappiamo gia': e' cio' che permette di
		# mettere la Range nella prima richiesta invece di aprire e poi cercare.
		if offset is None and dimensione: offset = offset_per(dimensione)
		lettore = _apri_lettore(url, offset, lettore_classe, fuori)
		fuori['lettore'] = lettore.__class__.__name__
		# LOTTO 231 -- il ttfb spezzato in tre. Passando al lettore di Kodi e' salito da 0,6-1,1 s a
		# 1,5-3,4: sono secondi che l'utente paga SENZA misurare, e prima di rimediare bisogna sapere
		# quale dei tre pezzi li consuma. L'apertura e il posizionamento sono due giri di rete
		# distinti -- xbmcvfs non sa aprire gia' all'offset -- e il primo pezzo e' il terzo.
		fuori['t_apertura'] = (perf_counter() - t0) * 1000
		# L'offset lo decide la dimensione che il lettore dichiara: cosi' non serve conoscerla prima
		# e non si dipende da cosa c'e' in archivio.
		_t = perf_counter()
		if offset is None:
			offset = offset_per(getattr(lettore, 'dimensione', None))
			try: lettore.posiziona(offset)
			except: pass
		fuori['t_posizione'] = (perf_counter() - _t) * 1000
		fuori['offset'] = offset
		fuori['dimensione_vera'] = getattr(lettore, 'dimensione', None)
		_t = perf_counter()
		# Il ttfb resta un numero SEPARATO: e' latenza, non banda, e mescolarlo ai byte e' il modo
		# in cui la v1 sbagliava di 11-17 volte. Col lettore di Kodi comprende anche il primo pezzo,
		# perche' e' li' che la richiesta parte davvero -- e quel pezzo non si conta.
		if lettore.leggi(PASSO) <= 0:
			fuori['errore'] = 'nessun byte all apertura'
			return fuori
		fuori['t_primo'] = (perf_counter() - _t) * 1000
		fuori['ttfb'] = (perf_counter() - t0) * 1000
		fuori['stato'] = getattr(lettore, 'stato', 206)
		letti, t1, prossimo = 0, perf_counter(), BUCKET
		trascorso, curva = 0.0, []
		# LAVORO O ATTESA. thread_time e' il tempo di CPU di QUESTO thread, process_time quello di
		# tutto il processo: insieme dicono quale delle tre spiegazioni regge, invece di sceglierla
		# a naso. Molta cpu propria = si sta decifrando e copiando, e il rimedio e' leggere a pezzi
		# piu' grossi. Poca cpu propria ma processo pieno = il GIL e' occupato dagli scraper e noi
		# aspettiamo il turno. Poca di entrambe = si aspetta la rete davvero.
		_cpu0, _proc0 = thread_time(), process_time()
		while True:
			quanti = lettore.leggi(PASSO)
			if not quanti:
				fuori['chiuso'] = 'fine del flusso'
				break
			letti += quanti
			trascorso = perf_counter() - t1
			if trascorso >= prossimo:
				curva.append((trascorso, letti))
				prossimo += BUCKET
			if trascorso >= SECONDI_TOTALI:
				fuori['chiuso'] = 'budget di tempo'
				break
			if letti >= BYTE_MASSIMI:
				fuori['chiuso'] = 'tetto di byte'
				break
			if molla is not None and molla():
				fuori['chiuso'] = 'abbandonata: ricerca annullata'
				break
		fuori['byte'], fuori['secondi'], fuori['curva'] = letti, trascorso, curva
		fuori['cpu'] = thread_time() - _cpu0
		fuori['cpu_processo'] = process_time() - _proc0
		# LOTTO 228 -- l'istante della misura e' la fine della LETTURA, non la fine della funzione.
		# quota_cpu() qui sotto puo' bruciare fino a QUOTA_ATTESA_MAX, e timbrando dopo di lei la
		# sonda risultava piu' vecchia di quanto fosse: sulla riga 2 del 10/09 `sonda_eta` e' uscita
		# **-1**, cioe' una misura presa dopo la riproduzione che doveva descrivere.
		fuori['quando'] = adesso()
		# La quota si rilegge DOPO, non prima: quella prima dice se valeva la pena partire, questa
		# dice se cio' che abbiamo letto e' una misura della linea o una misura di noi stessi.
		fuori['quota'] = quota_cpu()
		if letti <= 0 or trascorso <= 0:
			fuori['errore'] = 'nessun byte letto'
			return fuori
		fuori['ok'] = True
		fuori['lorda'] = (letti * 8.0) / trascorso / 1000000.0
		# REGIME: solo il tratto dopo la salita. Se non si e' andati abbastanza oltre la salita non
		# c'e' nessun regime da dichiarare e si lascia None -- 'non misurato' non e' 'misurato zero',
		# ed e' la distinzione che nei lotti 191-198 e' costata due sonde.
		base = None
		for _t, _b in curva:
			if _t >= SECONDI_SALITA:
				base = (_t, _b)
				break
		# Chi ha annullato non vuole una misura: si esce senza regime, e il motivo resta leggibile.
		_fine = None if (fuori['chiuso'] or '').startswith('abbandonata') else (trascorso, letti)
		if base and _fine and _fine[0] - base[0] >= SECONDI_MINIMI:
			dt, db = _fine[0] - base[0], _fine[1] - base[1]
			if dt > 0 and db > 0:
				fuori['regime'] = (db * 8.0) / dt / 1000000.0
				fuori['regime_secondi'] = dt
		# INVARIANTE, nello spirito di portata_secchi: una lettura fatta senza cpu NON e' una misura
		# della linea, e non deve poter arrivare al wizard travestita da tale. Il 10/09 due sonde
		# hanno dichiarato 26,0 e 8,0 Mbit/s su una linea da 43: la prima aveva il 25% di un core, la
		# seconda il 10%, e i due numeri sono esattamente 0,25 e 0,10 del tetto di decifratura.
		_perche = _limitata_da_cpu(fuori)
		if _perche:
			fuori['regime'], fuori['regime_secondi'] = None, 0.0
			fuori['errore'] = _perche
	except Exception as e:
		fuori['errore'] = '%s: %s' % (type(e).__name__, e)
	finally:
		# Sempre, e senza drenare: si abbandona il resto del file invece di scaricarlo. Un lettore
		# lasciato aperto tiene un socket e, con quello di Kodi, una CCurlFile.
		try:
			if lettore is not None: lettore.chiudi()
		except: pass
	return fuori


def misura_sorgente(url, molla=None, dimensione=None):
	"""Misura la linea sul link appena risolto e pubblica il risultato. Restituisce l'esito.

	E' l'unico ingresso: la chiama sources.process_results sulla prima sorgente in cache dell'ordine
	di autoplay, subito prima di applicare il filtro della dimensione.
	"""
	if not url:
		_riga_log('non eseguita: nessun link da sondare')
		return None
	esito = misura(url, None, molla, dimensione=dimensione)
	esito.setdefault('quando', adesso())
	pubblica(esito)
	_registra_log(esito, None)
	return esito


def line_speed_da(capacita):
	"""La soglia da applicare al filtro, a partire dalla capacita' misurata. None se non c'e'.

	Una riga sola, ed e' il punto d'arrivo di tutta la fase 4: `line_speed = capacita / MARGINE`.
	"""
	try:
		return (capacita / MARGINE) if capacita else None
	except: return None


def _mb(byte):
	return (byte or 0) / 1048576.0


def _riga_log(testo):
	try:
		from modules.perf import log as perf_log
		perf_log('FenLight PERF SONDA', testo)
	except: pass


def _registra_log(esito, nota):
	try:
		from modules.perf import log as perf_log
		if esito is None:
			perf_log('FenLight PERF SONDA', 'non eseguita: %s' % nota)
			return
		if not esito['ok']:
			perf_log('FenLight PERF SONDA', 'FALLITA su %s (%s)'
					 % (esito['cdn'] or '?', esito['errore'] or '?'))
			return
		if esito.get('ripiego'):
			perf_log('FenLight PERF SONDA', 'lettore di Kodi non disponibile, si ripiega su Python '
					 '(%s): il tetto di cpu scende a ~82 Mbit/s' % esito['ripiego'])
		if esito.get('dimensione_vera') and esito.get('dimensione_attesa'):
			_sc = abs(esito['dimensione_vera'] - esito['dimensione_attesa']) / float(esito['dimensione_vera'])
			if _sc > 0.05:
				perf_log('FenLight PERF SONDA', '  ATTENZIONE dimensione: lo scraper diceva %.2f GB, '
						 'il cdn ne dichiara %.2f GB'
						 % (esito['dimensione_attesa'] / 1073741824.0,
							esito['dimensione_vera'] / 1073741824.0))
		perf_log('FenLight PERF SONDA', '  attesa apertura %.0f ms + posizione %.0f ms + primo pezzo %.0f ms'
				 % (esito.get('t_apertura') or 0, esito.get('t_posizione') or 0, esito.get('t_primo') or 0))
		perf_log('FenLight PERF SONDA', '%s | %s | offset %.2f GB | ttfb %4.0f ms | %.1f MB in %.1f s | '
				 'lorda %.2f | REGIME %s Mbit/s su %.1f s (%s)'
				 % (esito['cdn'] or '?', (esito.get('lettore') or '?').replace('_Lettore', ''),
					esito['offset'] / 1073741824.0, esito['ttfb'] or 0,
					_mb(esito['byte']), esito['secondi'], esito['lorda'],
					'%.2f' % esito['regime'] if esito['regime'] else '?',
					esito['regime_secondi'],
					esito['chiuso'] or '?'))
		# La curva serve a VERIFICARE la taratura di SECONDI_SALITA invece di crederci: se i primi
		# passi sono molto piu' bassi degli altri la rampa e' quella, e se non lo sono va accorciata.
		if esito['curva']:
			perf_log('FenLight PERF SONDA', '  curva  %s'
					 % ' '.join('%.1f' % _mb(_b) for _, _b in esito['curva']))
		if esito.get('cpu') is not None and esito['secondi'] > 0:
			_consumo = esito['cpu'] / esito['secondi']
			_quota = esito.get('quota')
			_tetto = (esito['byte'] * 8.0 / esito['cpu'] / 1000000.0) if esito['cpu'] else 0
			perf_log('FenLight PERF SONDA', '  cpu    consumo %.0f%% | quota %s | processo %.0f%% | '
					 'tetto %.0f Mbit/s con un core intero (%.0f ms per MB)'
					 % (_consumo * 100, ('%.0f%%' % (_quota * 100)) if _quota is not None else '?',
						esito['cpu_processo'] / esito['secondi'] * 100, _tetto,
						esito['cpu'] / (esito['byte'] / 1048576.0) * 1000 if esito['byte'] else 0))
			# Il numero che dice se abbiamo misurato la linea o il muro.
			if _consumo > CONSUMO_SOSPETTO:
				perf_log('FenLight PERF SONDA', '  ATTENZIONE consumo al %.0f%% di un core: il regime '
						 'e un MINIMO, la linea puo essere piu veloce' % (_consumo * 100))
			elif esito.get('lettore') == '_LettorePython' and _quota and _consumo / _quota > CONSUMO_SOSPETTO:
				perf_log('FenLight PERF SONDA', '  ATTENZIONE consumata il %.0f%% della quota di GIL: '
						 'il regime e un MINIMO' % (_consumo / _quota * 100))
	except: pass


# ---- la bacheca ---------------------------------------------------------------------------------
# LOTTO 225 -- chi MISURA e chi USA la misura non sono piu' lo stesso interprete. La sonda vive nel
# servizio, dove puo' aspettare un momento con un core libero; il player, che scrive la riga in
# archivio, e' un'invocazione che nasce e muore. L'unica memoria condivisa fra interpreti che non
# costa un database e' la proprieta' di Window(10000), che e' anche cio' che perf.py usa per
# l'interruttore della strumentazione.
#
# Una proprieta' sola con i campi separati da barra, non nove: leggere e' una traversata verso la
# GUI e non ha senso pagarla nove volte per un dato che si scrive tutto insieme.
BACHECA = 'fenlight.sonda.misura'
_CAMPI_BACHECA = ('regime', 'lorda', 'regime_secondi', 'ttfb', 'byte', 'offset', 'quota', 'cpu',
				  'quando', 'cdn')


def pubblica(esito):
	"""Mette l'ultima misura buona in bacheca. Una misura senza regime NON si pubblica: sostituirebbe
	una buona con una che non dice niente."""
	try:
		if not esito or not esito.get('regime'): return False
		import xbmcgui
		xbmcgui.Window(10000).setProperty(BACHECA, '|'.join(
			('' if esito.get(_c) is None else str(esito.get(_c))) for _c in _CAMPI_BACHECA))
		return True
	except: return False


def letta():
	"""La misura in bacheca, o None. La chiama il player quando scrive la riga."""
	try:
		import xbmcgui
		_grezzo = xbmcgui.Window(10000).getProperty(BACHECA)
		if not _grezzo: return None
		_pezzi = _grezzo.split('|')
		if len(_pezzi) != len(_CAMPI_BACHECA): return None
		_fuori = dict(zip(_CAMPI_BACHECA, _pezzi))
		for _c in ('regime', 'lorda', 'regime_secondi', 'ttfb', 'quota', 'cpu', 'quando'):
			_fuori[_c] = float(_fuori[_c]) if _fuori[_c] else None
		for _c in ('byte', 'offset'):
			_fuori[_c] = int(_fuori[_c]) if _fuori[_c] else None
		return _fuori if _fuori.get('regime') else None
	except: return None
