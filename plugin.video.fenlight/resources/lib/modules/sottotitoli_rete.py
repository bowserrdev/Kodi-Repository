# -*- coding: utf-8 -*-
"""Lotto 416 (SOTTOTITOLI.md) -- cio' che i sottotitoli sincronizzati leggono dal file che si riproduce, via Range.

- struttura(): tracce e Cues di un matroska. La testa arriva gia' letta da stream_header (almeno 64 KB, dove stanno
  SeekHead, Info e Tracks); i Cues stanno di solito in fondo al file. Si chiedono LETTURA_CUES byte dalla loro posizione:
  bastano quasi sempre (mediana 145 KB, p90 1,1 MB), quindi una richiesta sola invece di intestazione + corpo, cioe' un
  andata e ritorno (~350 ms) risparmiato. Se l'elemento e' piu' grande, una seconda richiesta per il resto.
- hash_file(): l'hash OpenSubtitles del file. Prima pack_cache (TorBox lo da' gratis), poi il calcolo: primi 64 KB
  (gia' nella testa) + ultimi 64 KB (una richiesta).

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
	if h is None or t is None or h + t > MAX_CUES: return None
	if h + t > len(dati):
		resto = _intervallo(url, pos + len(dati), h + t - len(dati), conto)
		if not resto: return None
		dati += resto
	return dati[:h + t]


def struttura(url, testa, dimensione=None, lingue_utente=()):
	"""-> {'info', 'cues', 'rif', 'utente', 'richieste', 'byte', 'ms', 'motivo'}. `rif`: riferimenti ordinati (vuoto se
	il file non ne ha), `utente`: traccia completa nella lingua dell'utente o None. `motivo` dice perche' non c'e' un
	riferimento, per il log."""
	conto = {'richieste': 0, 'byte': 0, 'ms': 0}
	esito = dict(conto, info=None, cues=[], rif=[], utente=None, motivo=None)
	try:
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
			else: esito['motivo'] = 'Cues non letti'
		else:
			esito['motivo'] = 'nessun indice (Cues)'
		if numeri and esito['cues']:
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
