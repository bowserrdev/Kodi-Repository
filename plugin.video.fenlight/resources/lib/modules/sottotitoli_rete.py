# -*- coding: utf-8 -*-
"""Lotto 416 (SOTTOTITOLI.md) -- cio' che i sottotitoli sincronizzati leggono dal file che si riproduce, via Range.

- struttura(): tracce e Cues di un matroska. La testa arriva gia' letta da stream_header (almeno 64 KB, dove stanno
  SeekHead, Info e Tracks); i Cues stanno di solito in fondo al file. Si chiedono LETTURA_CUES byte dalla loro posizione:
  bastano quasi sempre (mediana 145 KB, p90 1,1 MB), quindi una richiesta sola invece di intestazione + corpo, cioe' un
  andata e ritorno (~350 ms) risparmiato. Se l'elemento e' piu' grande, una seconda richiesta per il resto.
- hash_file(): l'hash OpenSubtitles del file. Prima pack_cache (TorBox lo da' gratis), poi il calcolo: primi 64 KB
  (gia' nella testa) + ultimi 64 KB (una richiesta).

- tracce_mp4() (lotto 421): le tracce di testo tx3g di un mp4, lette a pezzi. Il moov pesa 1,5-27 MB quasi tutti di
  tabelle del video e dell'audio; si scorrono le sue trak, di ognuna si guarda l'inizio e si legge intera solo se e'
  testo: 3-17 richieste e 128 KB-3,3 MB sui 10 mp4 del corpus, battute identiche al moov intero.

Nessuna funzione solleva: se qualcosa non va, i sottotitoli restano quelli di oggi. Ogni esito porta richieste, byte
e millisecondi, per la riga di log.
"""
import struct
from time import perf_counter
from modules import sottotitoli_tracce as T

LETTURA_CUES = 524288          # 512 KB: coprono i Cues di quasi tutti i file del corpus in una richiesta
MAX_CUES = 4194304             # oltre 4 MB non si legge: non se n'e' visto nessuno (max 2,7 MB), e costa film
BLOCCO_HASH = 65536


def _intervallo(url, inizio, n, conto):
	from modules import stream_header
	t0 = perf_counter()
	dati = stream_header.leggi_intervallo(url, inizio, n)
	conto['richieste'] += 1
	conto['ms'] += int((perf_counter() - t0) * 1000)
	if dati: conto['byte'] += len(dati)
	return dati


def _elemento(url, pos, dimensione, conto, primo=None):
	"""I byte di un elemento che comincia a `pos`: una lettura di `primo` byte, e il resto se non bastano."""
	primo = primo or LETTURA_CUES
	dati = _intervallo(url, pos, min(primo, max(0, (dimensione or pos + primo) - pos)), conto)
	if not dati: return None
	h, t = T.intestazione(dati[:16])
	if h is None or t is None: return None
	if h + t > MAX_CUES:
		conto['oltre'] = h + t          # per il motivo nel log: l'elemento c'e', e' solo piu' grande del tetto
		return None
	if h + t > len(dati):
		resto = _intervallo(url, pos + len(dati), h + t - len(dati), conto)
		if not resto: return None
		dati += resto
	return dati[:h + t]


# ---- mp4 (lotto 421) ------------------------------------------------------------------------------------------------
MP4_FINESTRA = 65536          # ogni lettura nel moov mentre si scavalcano video e audio: basta per l'inizio di una trak
MP4_FINESTRA_TESTO = 524288   # dalla prima trak di testo: stanno in fila e pesano 30-50 KB l'una (Superman ne ha ~50)
MP4_MAX_RICHIESTE = 40        # una richiesta per scavalcare ogni trak lunga (video, audio): le MULTi ne hanno 10-15
MP4_TEMPO_MASSIMO = 15.0      # s in tutto: e' il thread di preparazione, in sottofondo, ma non all'infinito
MP4_MAX_TRACCIA = 4194304     # una traccia di testo pesa decine di KB; oltre non e' testo da leggere
MP4_SCATOLE = (b'ftyp', b'moov', b'styp', b'free', b'skip', b'wide', b'mdat', b'pdin', b'uuid', b'moof', b'sidx', b'meta', b'mfra')


def e_mp4(testa):
	return bool(testa) and len(testa) > 12 and testa[4:8] in (b'ftyp', b'moov', b'styp')


class _Lettore:
	"""Byte del file a pezzi: la testa gia' letta, poi finestre di MP4_FINESTRA byte; una richiesta solo se il pezzo
	chiesto non e' nella finestra corrente."""
	def __init__(self, url, testa, dimensione, conto):
		self.url, self.dim, self.conto = url, dimensione, conto
		self.testa, self.a, self.buf = testa or b'', 0, b''
		self.finestra = MP4_FINESTRA
		self.scade = perf_counter() + MP4_TEMPO_MASSIMO

	def __call__(self, a, n):
		if a + n <= len(self.testa): return self.testa[a:a + n]
		if self.a <= a and a + n <= self.a + len(self.buf): return self.buf[a - self.a:a - self.a + n]
		if self.conto['richieste'] >= MP4_MAX_RICHIESTE or perf_counter() >= self.scade: return None
		m = max(n, self.finestra)
		if self.dim: m = min(m, self.dim - a)
		if m <= 0: return None
		d = _intervallo(self.url, a, m, self.conto)
		if not d or len(d) < min(n, m): return None
		self.a, self.buf = a, d
		return d[:n]


def _mp4_scatola(leggi, i, dimensione):
	"""(tipo, taglia, testata) della scatola che comincia a i, o None."""
	h = leggi(i, 16)
	if not h or len(h) < 8: return None
	t, tipo, hl = int.from_bytes(h[:4], 'big'), h[4:8], 8
	if t == 1:
		if len(h) < 16: return None
		t, hl = int.from_bytes(h[8:16], 'big'), 16
	elif t == 0:
		if not dimensione: return None
		t = dimensione - i
	if t < hl: return None
	return tipo, t, hl


def tracce_mp4(url, testa, dimensione, conto):
	"""Le trak di testo del moov, lette intere, con la loro linea. Il moov si trova scorrendo le scatole di primo livello
	(mdat si salta con una lettura della sola testata); nel moov di ogni trak si legge l'inizio (hdlr) e, se e' testo,
	la trak intera. -> ([{'handler','codec','lang','linea',...}], motivo)"""
	leggi = _Lettore(url, testa, dimensione, conto)
	i, moov = 0, None
	while dimensione is None or i < dimensione:
		x = _mp4_scatola(leggi, i, dimensione)
		if not x: return [], 'mp4: scatole illeggibili'
		tipo, t, hl = x
		if tipo == b'moov': moov = (i, t, hl); break
		if tipo not in MP4_SCATOLE: return [], 'mp4: scatola sconosciuta %r' % tipo
		i += t
	if not moov: return [], 'mp4: moov non trovato'
	pos, taglia, hl = moov
	fine, i, tracce = pos + taglia, pos + hl, []
	while i + 8 <= fine:
		x = _mp4_scatola(leggi, i, dimensione)
		if not x: return tracce, ('mp4: letture finite nel moov' if conto['richieste'] >= MP4_MAX_RICHIESTE or perf_counter() >= leggi.scade else 'mp4: moov illeggibile')
		tipo, t, th = x
		if tipo == b'trak':
			inizio = leggi(i, min(t, 4096))
			if inizio is None: return tracce, 'mp4: letture finite nel moov'
			g = T.gestore_mp4(inizio, th, len(inizio))
			if g in T.MP4_SUB_ALTRI: tracce.append({'handler': g.decode('latin-1')})     # c'e', ma non si conta
			elif g in T.MP4_TESTO and t <= MP4_MAX_TRACCIA:
				leggi.finestra = MP4_FINESTRA_TESTO
				d = leggi(i, t)
				if d is None: return tracce, 'mp4: letture finite nel moov'
				info = T.traccia_mp4(d, th, t)
				info['linea'] = T.linea_mp4(info)
				tracce.append(info)
		i += t
	return tracce, None


def struttura(url, testa, dimensione=None, lingue_utente=()):
	"""-> {'info', 'cues', 'rif', 'utente', 'giudicato', 'richieste', 'byte', 'ms', 'motivo'}. `rif`: riferimenti
	ordinati (vuoto se il file non ne ha), `utente`: traccia completa nella lingua dell'utente o None, `giudicato`: le
	battute delle tracce si sono potute contare (Cues di un mkv, tracce tx3g di un mp4), quindi `utente` e' un giudizio e
	non un "non so". `motivo` dice perche' non c'e' un riferimento, per il log. Lotto 421: anche gli mp4."""
	conto = {'richieste': 0, 'byte': 0, 'ms': 0}
	esito = dict(conto, info=None, cues=[], rif=[], utente=None, motivo=None, giudicato=False)
	try:
		if e_mp4(testa):
			tracce, motivo = tracce_mp4(url, testa, dimensione, conto)
			esito['info'] = {'mp4': True, 'tracce': tracce}
			esito['rif'], esito['utente'] = T.riferimenti(None, None, None, set(lingue_utente), tutte=T.ordina(T.candidate_mp4(tracce)))
			# le battute si sono contate: la presenza di una traccia completa nella lingua e' giudicata, come coi Cues
			esito['giudicato'] = not motivo and not T.mp4_non_contate(tracce)
			if not esito['rif'] and not esito['utente']:
				esito['motivo'] = motivo or ('mp4 senza tracce di testo complete' if tracce else 'mp4 senza tracce di testo')
			esito.update(conto)
			return esito
		info = T.testa(testa or b'')
		if not info:
			esito['motivo'] = 'non matroska'
			return esito
		esito['info'] = info
		if T.TRACKS in info['mancano']:
			dati = _elemento(url, info['seek'][T.TRACKS], dimensione, conto, primo=65536)
			if dati: info['tracce'] = T.tracce_da_elemento(dati)
		numeri = T.numeri_sottotitoli(info['tracce'])
		if not numeri:
			esito['motivo'] = 'nessuna traccia di sottotitoli'
		elif info['cues']:
			esito['cues'] = T.cues(testa, info['cues'][0], info['cues'][1], solo=numeri)
		elif T.CUES in info['seek']:
			dati = _elemento(url, info['seek'][T.CUES], dimensione, conto)
			if dati: esito['cues'] = T.cues(dati, solo=numeri)
			elif conto.get('oltre'): esito['motivo'] = 'Cues di %.1f MB, oltre il tetto di %.1f MB' % (conto['oltre'] / 1048576.0, MAX_CUES / 1048576.0)
			else: esito['motivo'] = 'Cues non letti'
		else:
			esito['motivo'] = 'nessun indice (Cues)'
		if numeri and esito['cues']:
			esito['giudicato'] = True
			esito['rif'], esito['utente'] = T.riferimenti(info['tracce'], esito['cues'], info['scala'], set(lingue_utente))
			if not esito['rif'] and not esito['utente']: esito['motivo'] = 'nessuna traccia completa con i tempi'
		elif numeri and not esito['motivo']:
			esito['motivo'] = 'nessun cue per i sottotitoli'
	except Exception as e:
		esito['motivo'] = 'errore %s' % type(e).__name__
	esito.update(conto)
	return esito


def calcola_hash(url, dimensione, testa):
	"""(hash OSDb, conto). Dimensione + somma a 64 bit dei primi e degli ultimi 64 KB. None se manca qualcosa."""
	conto = {'richieste': 0, 'byte': 0, 'ms': 0}
	try:
		if not dimensione or dimensione < BLOCCO_HASH or not testa or len(testa) < BLOCCO_HASH: return None, conto
		coda = _intervallo(url, dimensione - BLOCCO_HASH, BLOCCO_HASH, conto)
		if not coda or len(coda) != BLOCCO_HASH: return None, conto
		h = dimensione
		for blocco in (testa[:BLOCCO_HASH], coda):
			for (v,) in struct.iter_unpack('<Q', blocco): h = (h + v) & 0xFFFFFFFFFFFFFFFF
		return '%016x' % h, conto
	except Exception:
		return None, conto


def hash_file(info_hash, nome_file, url, dimensione, testa):
	"""(hash OSDb, da dove, conto). Prima pack_cache (gratis, dato da TorBox), poi il calcolo a Range. Senza
	`nome_file` il video si riconosce dalla dimensione esatta (pack_cache.nome_per_dimensione)."""
	try:
		from caches import pack_cache
		nome_file = nome_file or pack_cache.nome_per_dimensione(info_hash, dimensione)
		h = pack_cache.oshash(info_hash, nome_file)
		if h: return h, 'torbox', {'richieste': 0, 'byte': 0, 'ms': 0}
	except Exception: pass
	h, conto = calcola_hash(url, dimensione, testa)
	return h, ('calcolato' if h else None), conto
