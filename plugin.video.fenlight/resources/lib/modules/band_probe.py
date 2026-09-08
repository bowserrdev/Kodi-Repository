# -*- coding: utf-8 -*-
# SONDA DELLA BANDA sul link risolto. Fase 4, v2 -- **STACCATA AL LOTTO 195, RISULTATO NEGATIVO**.
#
# ESITO, tenuto qui perche' un risultato negativo vale solo se resta scritto accanto al codice.
# Due versioni, due sessioni, otto riproduzioni: la sonda non predice l'esito. La v2 e' uno
# strumento molto migliore della v1 (ha corretto il caso che la v1 sbagliava di 17 volte) e la
# previsione NON e' migliorata -- firma di una grandezza sbagliata, non di una misura fatta male.
# La prova, dal log del 07/09 alle 23:24:
#     23:24:17.755  la sonda chiude: REGIME 3,39 Mbit/s su nexus-192.ceur.tb-cdn.st
#     23:24:18.224  Kodi apre lo STESSO nodo, mezzo secondo dopo
#     23:24:20.727  Kodi: maxRate 11,16 Mbit/s, cache al 99%
# La sonda misura una connessione DIVERSA da quella che riprodurra' il film, e la varianza fra due
# connessioni allo stesso nodo (3,3x misurata) e' piu' grande del segnale cercato (il margine e'
# sopra o sotto 1?). Non e' rumore nella misura: l'oggetto misurato non e' quello che conta.
#
# Perche' non si ripara allungando la finestra: forse si riparerebbe -- la curva di Evil Dead sale
# ancora leggermente in fondo, quindi TorBox potrebbe salire su 15-30 s invece che su 3. Ma una
# sonda da 20-30 s prima di ogni riproduzione e' PIU' LUNGA che far partire il film e guardare la
# cache vera per lo stesso tempo. Quando la sonda corretta costa piu' della cosa che simula, la
# simulazione non ha piu' ragione di esistere.
#
# PERCHE' UNA SONDA E NON UN NUMERO FISSO. `line_speed` filtra sulla DIMENSIONE del file ed e' lo
# stesso tetto per tutte le sorgenti: non sa nulla di come consegna QUEL link. E il log del 07/09 ha
# mostrato che la differenza fra una riproduzione fluida e una stentata NON e' la linea ma il nodo cdn
# che TorBox assegna a quel file: Evil Dead a 11,16 Mbit/s ha riempito la cache al 99%, Toy Story a
# 9,85 e' rimasto all'11%. Un tetto statico avrebbe buttato via il primo e lasciato passare il secondo,
# cioe' esattamente il contrario di quello che serve. La misura va fatta sulla sorgente, non sulla linea.
#
# COSA UNA SONDA NON PUO' FARE. Il Signore degli Anelli, al secondo zero, era la sorgente MIGLIORE
# della serata (cache di Kodi salita al 47%); il nodo e' morto dopo ~40 secondi. La banda e'
# osservabile subito, l'affidabilita' nel tempo no. La sonda serve a scartare chi consegna male
# adesso, non a prevedere chi morira' dopo.
#
# --------------------------------------------------------------------------------------------
# PERCHE' LA VERSIONE 1 SBAGLIAVA, e cosa e' cambiato.
#
# La v1 chiedeva `resp.read(65536)`, che BLOCCA finche' non ha 64 KB, e solo dopo guardava il budget
# di tempo. Con un ttfb di 1,3-3,0 s verso i nodi tb-cdn.st, dentro una finestra di 1,5 s si leggeva
# UN solo chunk: il numero prodotto era "tempo per i primi 64 KB", cioe' la salita del tcp.
# Errore misurato contro l'esito vero, sempre verso il basso:
#     Simpson    la sonda diceva 0,29 Mbit/s  ->  il link ha consegnato 4,84   (17x)
#     Evil Dead  la sonda diceva 1,02 Mbit/s  ->  il link ha consegnato 11,16  (11x)
#
# Le quattro riparazioni:
#   1. si legge a 8 KB, cosi' a comandare e' l'orologio e non il blocco, e si ottiene una CURVA;
#   2. si scarta la salita: la velocita' si calcola solo sul tratto dopo RAMP_SECONDS;
#   3. ci si ferma da soli quando la velocita' si stabilizza (due mezzi secondi consecutivi entro
#      STABLE_TOLERANCE), con tetto a MAX_SECONDS -- un link veloce e stabile chiude in ~2 s,
#      uno incerto si prende tutto il budget;
#   4. si registra la curva dei mezzi secondi, cosi' la forma della salita e' ispezionabile e la
#      taratura si valida invece di fidarsi.
#
# GUADAGNO ACCESSORIO. `Content-Range` da' la dimensione VERA del file. Nel log del 07/09
# `item['size']` dello scraper diceva 0,03 GB dove il cdn ne dichiarava 0,74 -- 25 volte -- e
# `item['size']` e' proprio il numero su cui filter_size_method=1 calcola il tetto. La sonda si porta
# dietro la correzione della bilancia.
#
# MODO. Solo misura e registra: non scarta niente e non scrive impostazioni. Il potere di scartare si
# concede dopo aver confrontato il verdetto della sonda con gli esiti veri.
#
# INTERRUTTORE. Nessuna impostazione nuova: vive con fenlight.perf.instrumentation (modules/perf.py).
import http.client
from time import perf_counter

from modules.http_client import _split_url
from modules.perf import log as perf_log

READ_SIZE = 8192          # piccolo apposta: e' l'orologio a dover comandare, non il blocco su read
BUCKET_SECONDS = 0.5      # passo della curva
RAMP_SECONDS = 1.2        # tratto iniziale scartato: partenza lenta del tcp
# I quattro numeri qui sotto devono essere coerenti fra loro, altrimenti la sonda spende tempo e
# dichiara '?'. Il primo bucket che supera RAMP_SECONDS cade a ~1,5 s (i bucket sono a 0,5-1,0-1,5),
# quindi per avere MIN_STEADY_SECONDS di regime servono almeno 1,5 + 1,0 = 2,5 s: MIN_SECONDS sta a
# 3,0 per avere margine anche quando una lettura lenta sposta il bucket in avanti.
MIN_SECONDS = 3.0         # prima di qui non ci si ferma mai: non ci sarebbe un regime da dichiarare
MAX_SECONDS = 5.0         # tetto per finestra
MAX_BYTES = 12 * 1024 * 1024
# Il tetto di byte non deve poter chiudere la finestra PRIMA che esista un regime da dichiarare,
# altrimenti su una linea veloce la sonda spende traffico e non produce nessun numero. Quindi vale
# solo da MIN_SECONDS in poi, e sopra c'e' un tetto duro che vale sempre.
HARD_MAX_BYTES = 24 * 1024 * 1024
MIN_STEADY_SECONDS = 1.0  # tratto di regime piu' corto di cosi' e' rumore, si dichiara '?'
STABLE_TOLERANCE = 0.20   # due bucket consecutivi entro il 20% = velocita' stabile, si chiude
DEEP_FRACTION = 0.45
SOCKET_TIMEOUT = 8
MAX_REDIRECTS = 4


def _open(url, offset, redirects=MAX_REDIRECTS):
	# GET con Range, redirect seguiti a mano. Niente urllib.request: tirerebbe dentro email.* per un GET.
	while True:
		scheme, host, port, path = _split_url(url)
		if scheme == 'https': conn = http.client.HTTPSConnection(host, port, timeout=SOCKET_TIMEOUT)
		else: conn = http.client.HTTPConnection(host, port, timeout=SOCKET_TIMEOUT)
		headers = {'Range': 'bytes=%d-' % offset, 'Accept-Encoding': 'identity',
				   'User-Agent': 'Mozilla/5.0', 'Connection': 'close'}
		conn.request('GET', path, headers=headers)
		resp = conn.getresponse()
		if resp.status in (301, 302, 303, 307, 308) and redirects > 0:
			location = resp.getheader('Location')
			conn.close()
			if not location: return None, None
			if location.startswith('/'): location = '%s://%s:%s%s' % (scheme, host, port, location)
			url, redirects = location, redirects - 1
			continue
		return conn, resp


def _total_size_from(resp):
	content_range = resp.getheader('Content-Range')
	if content_range and '/' in content_range:
		tail = content_range.rsplit('/', 1)[1].strip()
		if tail.isdigit(): return int(tail)
	if resp.status == 200:
		length = resp.getheader('Content-Length')
		if length and length.isdigit(): return int(length)
	return None


def _measure(url, offset):
	out = {'offset': offset, 'ok': False, 'status': None, 'ttfb_ms': None, 'bytes': 0,
		   'seconds': 0.0, 'gross_mbps': None, 'steady_mbps': None, 'steady_seconds': 0.0,
		   'curve': [], 'stopped': None, 'total_size': None, 'error': None}
	conn = None
	try:
		t0 = perf_counter()
		conn, resp = _open(url, offset)
		if resp is None:
			out['error'] = 'nessuna risposta'
			return out
		out['ttfb_ms'] = (perf_counter() - t0) * 1000
		out['status'] = resp.status
		if resp.status not in (200, 206):
			out['error'] = 'stato %s' % resp.status
			return out
		out['total_size'] = _total_size_from(resp)

		# L'orologio del trasferimento parte DOPO le intestazioni: la latenza del cdn resta un numero
		# separato e leggibile da solo.
		read, t1, next_bucket = 0, perf_counter(), BUCKET_SECONDS
		buckets = []            # (secondi trascorsi, byte cumulativi) a passo di mezzo secondo
		elapsed = 0.0
		while True:
			chunk = resp.read(READ_SIZE)
			if not chunk:
				out['stopped'] = 'fine del flusso'
				break
			read += len(chunk)
			elapsed = perf_counter() - t1
			if elapsed >= next_bucket:
				buckets.append((elapsed, read))
				next_bucket += BUCKET_SECONDS
				# Fermata anticipata: due bucket consecutivi con la stessa velocita' vogliono dire
				# che la salita e' finita e continuare non aggiunge informazione, solo attesa.
				if elapsed >= MIN_SECONDS and len(buckets) >= 3:
					(ta, ba), (tb, bb), (tc, bc) = buckets[-3], buckets[-2], buckets[-1]
					r1 = (bb - ba) / (tb - ta) if tb > ta else 0
					r2 = (bc - bb) / (tc - tb) if tc > tb else 0
					if r1 > 0 and r2 > 0 and abs(r1 - r2) / max(r1, r2) <= STABLE_TOLERANCE:
						out['stopped'] = 'velocita\' stabile'
						break
			if elapsed >= MAX_SECONDS:
				out['stopped'] = 'tetto di tempo'
				break
			if read >= MAX_BYTES and elapsed >= MIN_SECONDS:
				out['stopped'] = 'tetto di byte'
				break
			if read >= HARD_MAX_BYTES:
				out['stopped'] = 'tetto di byte duro'
				break
		out['bytes'], out['seconds'] = read, elapsed
		out['curve'] = buckets
		if read > 0 and elapsed > 0:
			out['gross_mbps'] = (read * 8.0) / elapsed / 1000000.0
			out['ok'] = True
			# REGIME: solo il tratto dopo la salita. Se non si e' andati oltre la salita non c'e' un
			# regime da dichiarare e si lascia None, invece di spacciare la salita per velocita'.
			base = None
			for t, b in buckets:
				if t >= RAMP_SECONDS:
					base = (t, b)
					break
			if base and elapsed - base[0] >= MIN_STEADY_SECONDS:
				dt, db = elapsed - base[0], read - base[1]
				if dt > 0 and db > 0:
					out['steady_mbps'] = (db * 8.0) / dt / 1000000.0
					out['steady_seconds'] = dt
		else: out['error'] = 'nessun byte letto'
	except Exception as e:
		out['error'] = '%s: %s' % (type(e).__name__, e)
	finally:
		try:
			if conn: conn.close()   # senza drenare: abbandona invece di scaricare il resto del file
		except: pass
	return out


def _gb(byte_count):
	if byte_count is None: return '?'
	if byte_count == 0: return '0'
	return '%.2f GB' % (byte_count / 1073741824.0)


def _fmt(window, etichetta):
	if not window['ok']:
		return '  %-7s offset %-11s FALLITA (%s)' % (etichetta, _gb(window['offset']), window['error'] or '?')
	steady = '%6.2f' % window['steady_mbps'] if window['steady_mbps'] else '     ?'
	return '  %-7s offset %-11s ttfb %4.0f ms | %5.2f MB in %.2f s | lorda %6.2f | REGIME %s Mbit/s (%.1f s utili, stop: %s)' % (
		etichetta, _gb(window['offset']), window['ttfb_ms'], window['bytes'] / 1048576.0,
		window['seconds'], window['gross_mbps'], steady, window['steady_seconds'], window['stopped'] or '?')


def _fmt_curve(window, etichetta):
	# La forma della salita, in MB cumulativi ogni mezzo secondo. Serve a validare la taratura:
	# se i primi due passi sono molto piu' bassi degli altri, RAMP_SECONDS e' giusto.
	if not window['curve']: return None
	return '  %-7s curva  %s' % (etichetta, ' '.join('%.2f' % (b / 1048576.0) for _, b in window['curve']))


def probe(url, item, meta, count=0, line_speed=None):
	"""Misura la banda utile sul link appena risolto. Non decide nulla: registra.

	Chiamata da sources.play_file fra resolve_sources e player.run. Non solleva mai: se fallisce,
	la riproduzione parte come se la sonda non ci fosse.
	"""
	try:
		t_start = perf_counter()
		provider = item.get('scrape_provider') or '?'
		if provider == 'external': provider = (item.get('debrid') or '?').replace('.me', '')
		try: _, host, _, _ = _split_url(url)
		except: host = '?'

		meta = meta or {}
		duration, duration_note = meta.get('duration') or 0, ''
		if not duration:
			duration = 5400 if meta.get('media_type') == 'movie' else 2400
			duration_note = ' (RIPIEGO, durata non nota)'

		inizio = _measure(url, 0)
		total = inizio.get('total_size')

		# Bitrate richiesto. Si calcola sulla dimensione DICHIARATA DAL CDN quando c'e', perche' e'
		# quella vera: item['size'] dello scraper e' stato trovato sbagliato di 25 volte (lotto 192).
		size_scraper_gb = float(item.get('size') or 0)
		size_real_gb = (total / 1073741824.0) if total else size_scraper_gb
		required_mbps = (size_real_gb * 1073741824.0 * 8.0) / float(duration) / 1000000.0 if (size_real_gb and duration) else None

		# La finestra profonda misura il caso del SALTO, che ha senso solo per una sorgente che gia'
		# regge la riproduzione lineare: se l'inizio non arriva al bitrate richiesto la sorgente e'
		# gia' giudicata, e i ~6 s della seconda finestra sarebbero spesi per niente.
		deep_offset, dentro, deep_skipped = (int(total * DEEP_FRACTION) if total else 0), None, None
		if not deep_offset: deep_skipped = 'dimensione totale sconosciuta'
		elif inizio['ok'] and inizio['steady_mbps'] and required_mbps and inizio['steady_mbps'] < required_mbps:
			deep_skipped = 'inizio gia\' sotto il richiesto, niente da aggiungere'
		if not deep_skipped: dentro = _measure(url, deep_offset)

		perf_log('FenLight PERF BANDA', 'SORGENTE %02d | %s | %s | %s s%s -> richiesti %s' % (
			count, provider.upper(), item.get('quality') or '?', duration, duration_note,
			'%.2f Mbit/s' % required_mbps if required_mbps else '?'))
		# La discrepanza si scrive SEMPRE quando c'e': e' il difetto della bilancia su cui
		# filter_size_method=1 calcola il tetto, e va visto accumularsi campione dopo campione.
		if total and size_scraper_gb and abs(size_real_gb - size_scraper_gb) / size_real_gb > 0.05:
			perf_log('FenLight PERF BANDA', '  ATTENZIONE dimensione: scraper %.2f GB contro cdn %.2f GB (%.1fx)' % (
				size_scraper_gb, size_real_gb, size_real_gb / size_scraper_gb if size_scraper_gb else 0))

		if inizio.get('status') is None: range_text = 'richiesta non riuscita'
		elif inizio.get('status') == 206: range_text = '206 onorato'
		else: range_text = 'NON onorato (stato %s)' % inizio.get('status')
		perf_log('FenLight PERF BANDA', '  cdn %s | range %s | dimensione dal cdn %s' % (host, range_text, _gb(total)))

		perf_log('FenLight PERF BANDA', _fmt(inizio, 'inizio'))
		curva = _fmt_curve(inizio, 'inizio')
		if curva: perf_log('FenLight PERF BANDA', curva)
		if dentro is not None:
			perf_log('FenLight PERF BANDA', _fmt(dentro, 'dentro'))
			curva = _fmt_curve(dentro, 'dentro')
			if curva: perf_log('FenLight PERF BANDA', curva)
		else:
			perf_log('FenLight PERF BANDA', '  dentro  NON misurata (%s)' % deep_skipped)

		# Il margine si dichiara sul REGIME, non sulla lorda: la lorda contiene la salita ed e'
		# proprio il numero che nella v1 sbagliava di 11-17 volte.
		def _margine(window):
			if not window or not window['ok'] or not required_mbps: return '?'
			value = window['steady_mbps']
			if not value: return 'n.d.'
			return '%.2fx' % (value / required_mbps)
		perf_log('FenLight PERF BANDA', '  MARGINE inizio %s | dentro %s | line_speed impostata %s Mbit/s | sonda %.0f ms' % (
			_margine(inizio), _margine(dentro), line_speed if line_speed is not None else '?',
			(perf_counter() - t_start) * 1000))

		return {'inizio': inizio, 'dentro': dentro, 'required_mbps': required_mbps,
				'total_size': total, 'host': host}
	except Exception as e:
		try: perf_log('FenLight PERF BANDA', 'sonda fallita: %s: %s' % (type(e).__name__, e))
		except: pass
		return None
