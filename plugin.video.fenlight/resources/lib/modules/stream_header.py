# -*- coding: utf-8 -*-
# LETTURA DELL'INTESTAZIONE DEL FLUSSO -- lotto 203.
#
# NON E' LA SONDA DEI LOTTI 191-195, e la differenza non e' di grado. Quelle misuravano la BANDA:
# una grandezza che fra due connessioni allo stesso nodo variava di 3,3x, cioe' piu' del segnale che
# cercavano, e per questo sono state buttate. Questa legge un NUMERO SCRITTO NEL FILE, che non varia
# mai e che non dipende dalla rete: larghezza e altezza del video. Il costo e' un ttfb -- 343 ms
# misurati su questo cdn -- piu' i byte dell'intestazione.
#
# COSA LEGGE. Larghezza, altezza, codec e -- dal lotto 209 -- la DURATA. La durata sta nell'Info di
# un matroska e nel mvhd di un mp4, cioe' prima del Tracks e del moov che gia' attraversiamo: arriva
# dentro i byte che stavamo scaricando comunque, e non allunga ne' la richiesta ne' l'attesa. Con la
# dimensione, che il Content-Range porta a casa dalla stessa risposta, e' il secondo dei due numeri
# che servono per un bitrate ESATTO: byte veri diviso secondi veri, senza niente di dedotto.
#
# A COSA SERVE. Sapere l'altezza PRIMA di chiamare play(). L'08/09 due riproduzioni di un file
# 1920x1456 hanno ucciso Kodi: il decoder muore, e chiudere un decoder morto fa abortire Kodi dentro
# CDVDVideoCodecAndroidMediaCodec::Dispose (fmt::format_error, stesso indirizzo due volte su due).
# Una volta aperto il file NON esiste modo di chiuderlo senza il crash, quindi l'unica difesa e' non
# aprirlo.
#
# SI FALLISCE SEMPRE IN FAVORE DELLA RIPRODUZIONE. Contenitore che non conosciamo, intestazione oltre
# i byte letti, rete lenta, parser che si perde: si restituisce None e si riproduce. Questo modulo
# puo' solo scartare cio' che ha POSITIVAMENTE misurato come troppo grande; tutto il resto passa.
BYTE_INTESTAZIONE = 131072      # 128 KB: coprono Tracks di un matroska e il moov di un mp4 faststart
TIMEOUT = 6                     # per singola operazione di socket
# Tetto sul TOTALE, redirect compresi. Senza, quattro salti da 6 s farebbero aspettare l'utente 24
# secondi prima ancora di provare a riprodurre: un controllo che deve costare mezzo secondo non puo'
# avere una coda lunga cosi'. Scaduto il tempo non si sa, e non sapere vuol dire riprodurre.
TEMPO_MASSIMO = 8
PEZZO = 16384                   # si legge a pezzi e ci si ferma appena l'intestazione ha risposto

# CodecID matroska e tipi di sample entry mp4 -> i nomi con cui li chiama decoder_limits.
CODEC_MKV = (('V_MPEGH/ISO/HEVC', 'hevc'), ('V_MPEG4/ISO/AVC', 'h264'), ('V_AV1', 'av1'),
			 ('V_VP9', 'vp9'), ('V_VP8', 'vp8'), ('V_MPEG4/ISO/', 'mpeg4'), ('V_MPEG2', 'mpeg2'))
CODEC_MP4 = {b'hvc1': 'hevc', b'hev1': 'hevc', b'dvh1': 'hevc', b'dvhe': 'hevc',
			 b'avc1': 'h264', b'avc3': 'h264', b'dva1': 'h264', b'dvav': 'h264',
			 b'av01': 'av1', b'vp09': 'vp9', b'vp08': 'vp8', b'mp4v': 'mpeg4'}


def _scarica(url):
	"""(byte, dimensione_totale, host_finale). Segue i redirect a mano."""
	import http.client
	from time import perf_counter
	from modules.http_client import _split_url
	scaduto = perf_counter() + TEMPO_MASSIMO
	for _ in range(4):
		if perf_counter() >= scaduto: return None, None, None
		scheme, host, port, percorso = _split_url(url)
		cls = http.client.HTTPSConnection if scheme == 'https' else http.client.HTTPConnection
		conn = cls(host, port, timeout=min(TIMEOUT, max(1, scaduto - perf_counter())))
		try:
			conn.request('GET', percorso, headers={'Range': 'bytes=0-%d' % (BYTE_INTESTAZIONE - 1),
												   'Accept-Encoding': 'identity', 'User-Agent': 'Mozilla/5.0',
												   'Connection': 'close'})
			resp = conn.getresponse()
			if resp.status in (301, 302, 303, 307, 308):
				dove = resp.getheader('Location')
				if not dove: return None, None, host
				url = dove if not dove.startswith('/') else '%s://%s:%s%s' % (scheme, host, port, dove)
				continue
			if resp.status not in (200, 206): return None, None, host
			# A PEZZI, e ci si ferma appena la risposta c'e'. Il Tracks di un matroska sta quasi
			# sempre nei primi kilobyte: leggerne 128 sempre vuol dire pagare byte che non servono.
			# Il tetto resta, per i file che l'intestazione ce l'hanno lontana.
			dati = b''
			while len(dati) < BYTE_INTESTAZIONE:
				pezzo = resp.read(min(PEZZO, BYTE_INTESTAZIONE - len(dati)))
				if not pezzo: break
				dati += pezzo
				if _basta(dati): break
			return dati, _totale(resp), host
		finally:
			try: conn.close()
			except: pass
	return None, None, None


def _totale(resp):
	"""La dimensione vera del file, che la stessa richiesta porta a casa gratis."""
	try:
		cr = resp.getheader('Content-Range')
		if cr and '/' in cr:
			coda = cr.rsplit('/', 1)[1].strip()
			if coda.isdigit(): return int(coda)
		return int(resp.getheader('Content-Length') or 0) or None
	except: return None


def _basta(dati):
	"""True quando i byte letti bastano gia' a rispondere: si smette di scaricare.

	Si guardano i primi TRE valori -- codec, larghezza, altezza -- e non la durata. La durata sta
	sempre prima di essi nel file, quindi quando ci sono c'e' anche lei; ma metterla nella
	condizione significherebbe che un file senza durata leggibile fa scaricare tutti i 128 KB
	invece di fermarsi ai primi kilobyte. Il lotto 209 non deve costare byte: se la durata non
	c'e' nei byte che servivano comunque, non c'e' e basta.
	"""
	try:
		if dati[:4] == b'\x1a\x45\xdf\xa3': return all(_mkv(dati)[:3])
		if len(dati) > 12 and dati[4:8] in (b'ftyp', b'moov', b'styp'): return all(_mp4(dati)[:3])
	except: pass
	return False


# ---- matroska ---------------------------------------------------------------------------------
def _ebml_id(dati, i):
	b = dati[i]
	if b == 0: return None, i + 1
	lunghezza = 1
	while lunghezza <= 4 and not (b & (0x80 >> (lunghezza - 1))): lunghezza += 1
	if lunghezza > 4 or i + lunghezza > len(dati): return None, len(dati)
	valore = 0
	for k in range(lunghezza): valore = (valore << 8) | dati[i + k]
	return valore, i + lunghezza


def _ebml_size(dati, i):
	if i >= len(dati): return None, len(dati)
	b = dati[i]
	if b == 0: return None, len(dati)
	lunghezza = 1
	while lunghezza <= 8 and not (b & (0x80 >> (lunghezza - 1))): lunghezza += 1
	if lunghezza > 8 or i + lunghezza > len(dati): return None, len(dati)
	valore = b & (0xFF >> lunghezza)
	sconosciuta = valore == (0xFF >> lunghezza)
	for k in range(1, lunghezza):
		valore = (valore << 8) | dati[i + k]
		if dati[i + k] != 0xFF: sconosciuta = False
	# Dimensione sconosciuta: legale, e i muxer in streaming la usano per Segment. Si scende dentro
	# lo stesso, fino a fine buffer.
	return (None if sconosciuta else valore), i + lunghezza


MASTER = (0x18538067, 0x1654AE6B, 0xAE, 0xE0, 0x1549A966)   # Segment, Tracks, TrackEntry, Video, Info


def _ebml_float(blocco):
	"""Un float EBML e' a 4 o 8 byte, big endian. Qualunque altra lunghezza non e' un float e non si
	prova a interpretarla: un numero inventato qui diventerebbe una sorgente buona scartata."""
	try:
		from struct import unpack
		if len(blocco) == 4: return unpack('>f', blocco)[0]
		if len(blocco) == 8: return unpack('>d', blocco)[0]
	except: pass
	return None


def _mkv(dati):
	trovati, pila = [], [(0, len(dati))]
	corrente = {}
	# Stanno nell'Info, che e' fratello del Tracks e viene prima: sono di tutto il Segment, non di
	# una traccia, e per questo non finiscono in `corrente`. 1.000.000 ns e' il valore predefinito
	# della specifica -- quasi tutti i muxer lo scrivono comunque, ma chi lo omette lo intende.
	scala, durata_grezza = 1000000, None
	while pila:
		i, fine = pila.pop()
		while i < fine and i < len(dati):
			eid, i = _ebml_id(dati, i)
			if eid is None: break
			taglia, i = _ebml_size(dati, i)
			if taglia is None: taglia = fine - i
			prossimo = min(i + taglia, fine, len(dati))
			if eid == 0xAE:                          # nuovo TrackEntry: si chiude il precedente
				if corrente: trovati.append(corrente)
				corrente = {}
			if eid in MASTER:
				pila.append((prossimo, fine))    # dove riprendere dopo il master
				fine = prossimo                  # e intanto si scende dentro
				continue
			# SOLO SE L'ELEMENTO E' INTERO. Se il buffer si e' chiuso a meta' di un valore,
			# int.from_bytes sui byte rimasti da' un numero PIU' PICCOLO del vero -- 0x05B0 (1456)
			# tagliato a un byte diventa 5 -- e leggerlo vorrebbe dire misurare una risoluzione che
			# non esiste. Oggi l'errore cadeva sempre verso il basso, quindi verso "si riproduce", ma
			# era fortuna, non progetto: con la lettura a pezzi qui sotto diventerebbe sistematico.
			intero = (i + taglia) <= len(dati)
			blocco = dati[i:prossimo] if intero else b''
			if eid == 0x86 and blocco:               # CodecID
				corrente['codec_id'] = blocco.rstrip(b'\x00').decode('ascii', 'ignore')
			elif eid == 0x83 and blocco:             # TrackType, 1 = video
				corrente['tipo'] = int.from_bytes(blocco, 'big')
			elif eid == 0xB0 and blocco:             # PixelWidth
				corrente['w'] = int.from_bytes(blocco, 'big')
			elif eid == 0xBA and blocco:             # PixelHeight
				corrente['h'] = int.from_bytes(blocco, 'big')
			elif eid == 0x2AD7B1 and blocco:         # TimecodeScale, nanosecondi per unita'
				scala = int.from_bytes(blocco, 'big') or scala
			elif eid == 0x4489 and blocco:           # Duration, in unita' di TimecodeScale
				durata_grezza = _ebml_float(blocco)
			i = prossimo
	if corrente: trovati.append(corrente)
	durata = (durata_grezza * scala / 1000000000.0) if durata_grezza and scala else None
	for t in trovati:
		if t.get('w') and t.get('h') and (t.get('tipo') in (None, 1)):
			codec = None
			for prefisso, nome in CODEC_MKV:
				if t.get('codec_id', '').startswith(prefisso): codec = nome; break
			return codec, t['w'], t['h'], durata
	return None, None, None, durata


# ---- mp4 / mov --------------------------------------------------------------------------------
def _mvhd(dati, inizio, fine):
	"""Secondi da un box mvhd, contando i campi invece di ricordarli.

	Dopo gli 8 byte di intestazione del box: version 1 + flags 3. Poi, con version 0, creation 4 +
	modification 4 + timescale 4 + duration 4; con version 1 gli stessi campi ma i due tempi e la
	durata a 64 bit. Si torna None se il box e' troncato: mezzo campo letto e' un numero sbagliato.
	"""
	try:
		versione = dati[inizio]
		if versione == 1:
			if inizio + 32 > fine: return None
			scala = int.from_bytes(dati[inizio + 20:inizio + 24], 'big')
			grezza = int.from_bytes(dati[inizio + 24:inizio + 32], 'big')
		else:
			if inizio + 20 > fine: return None
			scala = int.from_bytes(dati[inizio + 12:inizio + 16], 'big')
			grezza = int.from_bytes(dati[inizio + 16:inizio + 20], 'big')
		if scala and grezza: return grezza / float(scala)
	except: pass
	return None


def _mp4(dati):
	# La durata sta nel mvhd, che nel moov precede i trak: quando la ricorsione trova lo stsd e
	# torna, qui e' gia' passata. Vive fuori dalla ricorsione perche' quella esce al primo esito
	# utile e non puo' portarsi dietro un secondo valore.
	fuori = {}
	def dentro(inizio, fine, profondita=0):
		i = inizio
		while i + 8 <= fine and profondita < 8:
			taglia = int.from_bytes(dati[i:i + 4], 'big')
			tipo = dati[i + 4:i + 8]
			testa = 8
			if taglia == 1:
				if i + 16 > fine: return None
				taglia = int.from_bytes(dati[i + 8:i + 16], 'big'); testa = 16
			elif taglia == 0: taglia = fine - i
			if taglia < testa: return None
			prossimo = min(i + taglia, fine)
			if tipo in (b'moov', b'trak', b'mdia', b'minf', b'stbl'):
				esito = dentro(i + testa, prossimo, profondita + 1)
				if esito: return esito
			elif tipo == b'mvhd':
				fuori['durata'] = _mvhd(dati, i + testa, prossimo)
			elif tipo == b'stsd':
				# stsd: 4 byte version/flags + 4 byte entry_count, poi le voci. Dentro una
				# VisualSampleEntry: size 4 + type 4 + reserved 6 + data_reference_index 2 +
				# pre_defined 2 + reserved 2 + pre_defined[3] 12 = 32, e li' stanno larghezza e
				# altezza, due uint16. Contati, non ricordati a memoria.
				j = i + testa + 8
				while j + 36 <= prossimo:
					vtaglia = int.from_bytes(dati[j:j + 4], 'big')
					vtipo = dati[j + 4:j + 8]
					if vtaglia < 8: break
					if vtipo in CODEC_MP4:
						w = int.from_bytes(dati[j + 32:j + 34], 'big')
						h = int.from_bytes(dati[j + 34:j + 36], 'big')
						if w and h: return CODEC_MP4[vtipo], w, h
					j += vtaglia
			elif tipo == b'mdat' and profondita == 0:
				# I dati prima dell'indice: il moov sta in coda e nei byte letti non c'e'. Si smette,
				# e non sapere significa riprodurre.
				return None
			i = prossimo
		return None
	try: codec, larghezza, altezza = dentro(0, len(dati)) or (None, None, None)
	except: return None, None, None, None
	return codec, larghezza, altezza, fuori.get('durata')


# Fuori da questi estremi il numero non e' una risoluzione ma un errore di lettura, e un errore di
# lettura non deve poter scartare una sorgente buona: si butta e si torna a "non lo so".
MIN_LATO, MAX_LATO = 16, 16384
# Stessa idea per la durata: sotto il secondo o sopra le ventiquattro ore non e' un video, e' un
# campo letto male -- un mvhd con duration 0xFFFFFFFF, un float preso a meta'. Fuori da qui si torna
# a "non lo so", che vuol dire riprodurre.
MIN_DURATA, MAX_DURATA = 1.0, 86400.0


def leggi(url):
	"""{'codec','larghezza','altezza','durata','dimensione','host'} -- ogni campo puo' mancare.

	Se avvia() ha gia' messo in moto la richiesta per questo stesso url, qui si aspetta solo il
	tempo che manca. Se non l'ha fatto, o se e' fallita, si legge adesso: l'anticipo e' un risparmio,
	mai una dipendenza.
	"""
	try:
		th, scatola = _in_volo.pop(url, (None, None))
		if th is not None:
			th.join(TEMPO_MASSIMO + 2)
			if scatola.get('esito'): return scatola['esito']
	except: pass
	return _leggi_ora(url)


def _leggi_ora(url):
	esito = {'codec': None, 'larghezza': None, 'altezza': None, 'durata': None,
			 'dimensione': None, 'host': None}
	try:
		dati, totale, host = _scarica(url)
		esito['dimensione'], esito['host'] = totale, host
		if not dati: return esito
		if dati[:4] == b'\x1a\x45\xdf\xa3': codec, larghezza, altezza, durata = _mkv(dati)
		elif len(dati) > 12 and dati[4:8] in (b'ftyp', b'moov', b'styp'): codec, larghezza, altezza, durata = _mp4(dati)
		else: return esito
		if larghezza and altezza and all(MIN_LATO <= _v <= MAX_LATO for _v in (larghezza, altezza)):
			esito['larghezza'], esito['altezza'] = larghezza, altezza
		if durata and MIN_DURATA <= durata <= MAX_DURATA: esito['durata'] = float(durata)
		esito['codec'] = codec
		return esito
	except: return esito


# ---- anticipo ---------------------------------------------------------------------------------
# Il costo della sonda e' quasi tutto ANDATA E RITORNO, non byte: con `Range: bytes=0-0` il solo
# ttfb su questo cdn misura 343 ms, e i 128 KB ne aggiungono una sessantina. Ridurre i byte non
# serve quindi quasi a niente; l'unico modo di guadagnare tempo davvero e' non aspettare fermi.
# Fra la risoluzione del link e play() Fen Light fa gia' un sleep(200) piu' due aggiornamenti della
# finestra: avviando li' la richiesta, quel tempo si paga una volta sola invece che due.
_in_volo = {}


def avvia(url):
	"""Fa partire la lettura in sfondo. Chiamabile a vuoto: se qualcosa non va, leggi() rifara' da se'."""
	try:
		from threading import Thread
		if not url or url in _in_volo: return
		_in_volo.clear()                     # una alla volta: la sorgente in corso e' sempre una
		scatola = {}
		def _corri():
			try: scatola['esito'] = _leggi_ora(url)
			except: scatola['esito'] = None
		th = Thread(target=_corri)
		th.daemon = True
		_in_volo[url] = (th, scatola)
		th.start()
	except: _in_volo.clear()
