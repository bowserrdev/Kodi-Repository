# -*- coding: utf-8 -*-
"""Lotto 415 (SOTTOTITOLI.md) -- i tempi delle tracce di sottotitoli di un matroska, letti dall'indice (Cues).

mkvmerge (e anche Lavf) scrive nei Cues una voce per OGNI battuta di ogni traccia di sottotitoli: il testo con
CueTime e CueDuration, le immagini (PGS) solo con CueTime, a coppie mostra/cancella. Verificato al millisecondo contro i
blocchi veri. I Cues stanno di solito in fondo al file e pesano in mediana 145 KB: si leggono con una o due richieste
Range, senza scaricare il film. Non serve il testo: per allineare bastano i tempi (sottotitoli_sync.py).

Qui solo la lettura dai BYTE (la rete e' del lotto 416) e la scelta del riferimento. Nessuna funzione solleva: un
file che non capiamo vuol dire "nessun riferimento", mai un errore nel player.

Fatti che la scelta del riferimento rispetta (corpus del 28/09):
- il flag forced non vale in nessuno dei due versi: forzate senza flag ("[ITA] SUBS FORCED"), complete col flag
  (All Quiet on the Western Front UHD: inglese da 1049 battute marcato forced);
- una traccia immagine puo' essere a effetti (PGS cinesi "特效", battute di 42-292 ms): non descrive il parlato;
- la traccia con PIU' battute non e' la piu' affidabile (SDH, descrittive): meglio quella vicina alla mediana;
- il testo e' esatto (CueDuration), l'immagine e' ricostruita a coppie.
"""
import re, struct

SEGMENT, SEEKHEAD, INFO, TRACKS, CUES, CLUSTER = 0x18538067, 0x114D9B74, 0x1549A966, 0x1654AE6B, 0x1C53BB6B, 0x1F43B675
MAGIA = b'\x1a\x45\xdf\xa3'
SOTTOTITOLI = 17

FORZATO_NOME = re.compile(r'forced|forzat|forcé|signs|songs|comment', re.I)
SDH = re.compile(r'sdh|\bcc\b|\[cc\]|hearing|non udenti|\bhi\b', re.I)
CLASSE = {'S_HDMV/PGS': 1, 'S_VOBSUB': 2}          # 0 = testo
MIN_BATTUTE = 100
DURATA_MEDIANA_MIN = 700                            # ms: sotto, la traccia immagine e' a effetti o spezzata
PGS_MAX_BATTUTA = 10000                             # ms: una coppia piu' lunga non e' una battuta


# ---- EBML ----------------------------------------------------------------------------------------------------------
def _vint(d, i, maschera=True):
	b = d[i]; l = 1
	while l <= 8 and not (b & (0x80 >> (l - 1))): l += 1
	if l > 8 or i + l > len(d): raise ValueError('vint')
	v = b & (0xFF >> l) if maschera else b
	for k in range(1, l): v = (v << 8) | d[i + k]
	return v, l, maschera and v == (1 << (7 * l)) - 1


def _elementi(d, i, fine):
	"""(id, inizio dei dati, taglia) dei figli in d[i:fine]; taglia None se sconosciuta (Segment dei muxer in diretta)."""
	fine = min(fine, len(d))
	while i < fine:
		eid, l1, _ = _vint(d, i, maschera=False)
		taglia, l2, sconosciuta = _vint(d, i + l1)
		inizio = i + l1 + l2
		yield eid, inizio, (None if sconosciuta else taglia)
		if sconosciuta: return
		i = inizio + taglia


def _uint(b): return int.from_bytes(b, 'big') if b else 0


def _flt(b):
	if len(b) == 4: return struct.unpack('>f', b)[0]
	if len(b) == 8: return struct.unpack('>d', b)[0]
	return None


def intestazione(dati):
	"""(lunghezza dell'intestazione, taglia dei dati) di un elemento che comincia in dati[0]. Serve alla rete per sapere
	quanti byte chiedere dopo aver letto i primi 16 di un elemento indicato dalla SeekHead. (None, None) se illeggibile."""
	try:
		_, l1, _ = _vint(dati, 0, maschera=False)
		t, l2, sconosciuta = _vint(dati, l1)
		return l1 + l2, (None if sconosciuta else t)
	except Exception:
		return None, None


# ---- la testa del file ----------------------------------------------------------------------------------------------
def testa(dati):
	"""Cosa si ricava dai primi byte del file (quelli che stream_header legge gia').
	-> {'seg_dati', 'seek': {id: posizione assoluta}, 'scala', 'durata' (s), 'writing', 'tracce': [...],
	    'cues': (inizio, fine) dei dati se sono gia' dentro questi byte, 'mancano': [id da leggere a parte]}
	o None se non e' un matroska o non si capisce."""
	try:
		if dati[:4] != MAGIA: return None
		_, ini, t = next(_elementi(dati, 0, len(dati)))
		eid, seg_dati, _ = next(_elementi(dati, ini + t, len(dati)))
		if eid != SEGMENT: return None
		pos = {}
		for eid, ini, t in _elementi(dati, seg_dati, len(dati)):
			if eid == CLUSTER: break
			pos.setdefault(eid, (ini, t))
			if t is None or ini + t > len(dati): break
		seek = {}
		if SEEKHEAD in pos and pos[SEEKHEAD][1] is not None:
			ini, t = pos[SEEKHEAD]
			for eid, a, b in _elementi(dati, ini, ini + t):
				if eid != 0x4DBB: continue
				sid = sp = None
				for e2, a2, b2 in _elementi(dati, a, a + b):
					if e2 == 0x53AB: sid = _uint(dati[a2:a2 + b2])
					elif e2 == 0x53AC: sp = _uint(dati[a2:a2 + b2])
				if sid is not None and sp is not None: seek[sid] = seg_dati + sp
		esito = {'seg_dati': seg_dati, 'seek': seek, 'scala': 1000000, 'durata': None, 'writing': None, 'tracce': [], 'cues': None, 'mancano': []}
		for eid, leggi in ((INFO, _leggi_info), (TRACKS, _leggi_tracce)):
			dentro = _dentro(dati, pos, seek, eid)
			if dentro: leggi(dati, dentro[0], dentro[1], esito)
			elif eid in seek: esito['mancano'].append(eid)
		dentro = _dentro(dati, pos, seek, CUES)
		if dentro: esito['cues'] = dentro
		elif CUES in seek: esito['mancano'].append(CUES)
		return esito
	except Exception:
		return None


def _dentro(dati, pos, seek, eid):
	"""(inizio, fine) dei dati di un elemento se sta per intero nei byte letti."""
	if eid in pos and pos[eid][1] is not None and pos[eid][0] + pos[eid][1] <= len(dati):
		return pos[eid][0], pos[eid][0] + pos[eid][1]
	p = seek.get(eid)
	if p is not None and p + 16 <= len(dati):
		h, t = intestazione(dati[p:p + 16])
		if h is not None and t is not None and p + h + t <= len(dati): return p + h, p + h + t
	return None


def _leggi_info(d, a, z, esito):
	grezza = None
	for eid, x, t in _elementi(d, a, z):
		v = d[x:x + t]
		if eid == 0x2AD7B1: esito['scala'] = _uint(v) or 1000000
		elif eid == 0x4489: grezza = _flt(v)
		elif eid == 0x5741: esito['writing'] = v.decode('utf-8', 'replace')
	if grezza: esito['durata'] = grezza * esito['scala'] / 1e9


def _leggi_tracce(d, a, z, esito):
	for eid, x, t in _elementi(d, a, z):
		if eid != 0xAE: continue
		tr = {'default': 1, 'forced': 0, 'lang': 'eng'}
		for e2, x2, t2 in _elementi(d, x, x + t):
			v = d[x2:x2 + t2]
			if e2 == 0xD7: tr['n'] = _uint(v)
			elif e2 == 0x83: tr['tipo'] = _uint(v)
			elif e2 == 0x86: tr['codec'] = v.rstrip(b'\0').decode('ascii', 'ignore')
			elif e2 == 0x22B59C: tr['lang'] = v.rstrip(b'\0').decode('ascii', 'ignore')
			elif e2 == 0x22B59D: tr['lang_bcp'] = v.rstrip(b'\0').decode('ascii', 'ignore')
			elif e2 == 0x536E: tr['nome'] = v.decode('utf-8', 'replace')
			elif e2 == 0x88: tr['default'] = _uint(v)
			elif e2 == 0x55AA: tr['forced'] = _uint(v)
			elif e2 == 0x55AB: tr['hi'] = _uint(v)
		if 'n' in tr: esito['tracce'].append(tr)


def tracce_da_elemento(dati):
	"""Tracks letto a parte (quando non sta nella testa): dati che cominciano con l'elemento. -> [tracce]"""
	try:
		h, t = intestazione(dati)
		esito = {'tracce': []}
		if h is not None: _leggi_tracce(dati, h, h + (t if t is not None else len(dati)), esito)
		return esito['tracce']
	except Exception:
		return []


# ---- i Cues ---------------------------------------------------------------------------------------------------------
def cues(dati, a=None, z=None, solo=None):
	"""[(tempo, traccia, durata o None)] in unita' di TimecodeScale. `dati` sono i byte che contengono i dati dei Cues
	fra a e z; senza a/z, `dati` comincia con l'elemento Cues. `solo`: insieme di numeri di traccia da tenere (le tracce
	di sottotitoli: il video ha un cue per fotogramma chiave e non serve). Lista vuota se illeggibile."""
	fuori = []
	try:
		if a is None:
			h, t = intestazione(dati)
			if h is None: return []
			a, z = h, h + (t if t is not None else len(dati))
		for eid, x, t in _elementi(dati, a, z):
			if eid != 0xBB or t is None: continue
			tempo, posizioni = None, []
			for e2, x2, t2 in _elementi(dati, x, x + t):
				if e2 == 0xB3: tempo = _uint(dati[x2:x2 + t2])
				elif e2 == 0xB7:
					traccia = durata = None
					for e3, x3, t3 in _elementi(dati, x2, x2 + t2):
						if e3 == 0xF7: traccia = _uint(dati[x3:x3 + t3])
						elif e3 == 0xB2: durata = _uint(dati[x3:x3 + t3])
					posizioni.append((traccia, durata))
			if tempo is None: continue
			for traccia, durata in posizioni:
				if solo is None or traccia in solo: fuori.append((tempo, traccia, durata))
	except Exception:
		pass   # Cues troncati: si tiene cio' che si e' letto
	return fuori


def numeri_sottotitoli(tracce): return {t['n'] for t in tracce if t.get('tipo') == SOTTOTITOLI}


def linea(traccia, lista_cues, scala=1000000):
	"""Linea temporale in ms di una traccia: [(inizio, fine)]. Dai cue con durata (testo, e anche VOBSUB: mkvmerge la
	scrive). Solo le PGS, che la durata non l'hanno, si ricostruiscono a coppie mostra/cancella; una coppia piu' lunga di
	PGS_MAX_BATTUTA non e' una battuta."""
	k = scala / 1e6
	n = traccia.get('n')
	if traccia.get('codec') == 'S_HDMV/PGS':
		t = sorted(c * k for c, tr, d in lista_cues if tr == n)
		return [(t[i], t[i + 1]) for i in range(0, len(t) - 1, 2) if 0 < t[i + 1] - t[i] <= PGS_MAX_BATTUTA]
	return sorted((c * k, (c + d) * k) for c, tr, d in lista_cues if tr == n and d)


# ---- la scelta del riferimento --------------------------------------------------------------------------------------
def lingua(t): return (t.get('lang_bcp') or t.get('lang') or '').split('-')[0].lower()


def _mediana(xs):
	xs = sorted(xs); return xs[len(xs) // 2] if xs else 0


def tracce_complete(tracce, lista_cues, scala=1000000):
	"""[{'lingua','nome','sdh','classe','linea'}] delle tracce complete, nell'ordine in cui provarle come riferimento:
	testo prima dell'immagine, poi la piu' vicina alla mediana delle battute. Complete = almeno meta' della mediana; un
	flag forced conta solo con meno del 30% della mediana."""
	cand = []
	for t in tracce:
		if t.get('tipo') != SOTTOTITOLI: continue
		codec = t.get('codec') or ''
		if not (codec.startswith('S_TEXT') or codec in CLASSE): continue
		if FORZATO_NOME.search(t.get('nome') or ''): continue
		L = linea(t, lista_cues, scala)
		if len(L) < MIN_BATTUTE: continue
		classe = CLASSE.get(codec, 0)
		if classe and _mediana([b - a for a, b in L]) < DURATA_MEDIANA_MIN: continue
		cand.append({'lingua': lingua(t), 'nome': t.get('nome') or '', 'sdh': bool(SDH.search(t.get('nome') or '')) or bool(t.get('hi')),
					 'classe': classe, 'forced': bool(t.get('forced')), 'linea': L})
	return ordina(cand)


def ordina(cand):
	"""Le candidate complete nell'ordine in cui provarle. Vale per ogni contenitore (anche le tx3g di un mp4, lotto 421):
	complete = almeno meta' della mediana delle battute, un flag forced conta solo sotto il 30% della mediana; poi testo
	prima dell'immagine e la piu' vicina alla mediana."""
	if not cand: return []
	med = _mediana([len(c['linea']) for c in cand])
	cand = [c for c in cand if len(c['linea']) >= 0.5 * med and not (c['forced'] and len(c['linea']) < 0.3 * med)]
	cand.sort(key=lambda c: (c['classe'], abs(len(c['linea']) - med)))
	return cand


def riferimenti(tracce, lista_cues, scala, lingue_utente, tutte=None):
	"""(riferimenti ordinati, traccia completa nella lingua dell'utente o None). `lingue_utente`: i codici della lingua
	scelta (es. {'it', 'ita'}). Se il file ha gia' una traccia completa in quella lingua, i sottotitoli automatici non
	servono: la sceglie Kodi. `tutte`: candidate gia' ordinate (altri contenitori), al posto di tracce e cues."""
	if tutte is None: tutte = tracce_complete(tracce, lista_cues, scala)
	utente = sorted([c for c in tutte if c['lingua'] in lingue_utente], key=lambda c: (c['classe'], c['sdh']))
	return [c for c in tutte if c['lingua'] not in lingue_utente], (utente[0] if utente else None)


def secondo(rif):
	"""Il secondo riferimento da provare se il primo non basta: il primo di classe o lingua diversa."""
	if len(rif) < 2: return None
	p = rif[0]
	for c in rif[1:]:
		if c['classe'] != p['classe'] or c['lingua'] != p['lingua']: return c
	return rif[1]


# ---- mp4 (lotto 421) ------------------------------------------------------------------------------------------------
# Le tracce di testo tx3g di un mp4 hanno i tempi nella tabella dei campioni (stts: durate; stsz: taglie, e un campione
# di 2 byte e' una cancellazione, non una battuta). Stanno nel moov, che su un film lungo pesa 4-27 MB quasi tutti di
# tabelle del video e dell'audio: sottotitoli_rete legge solo le tracce di testo. Qui solo i byte.
# Il marcatore della traccia non basta: le WEB-DL con tracce da Apple dicono 'sbtl', quelle rifatte (Dune, Joker, Il
# cavaliere oscuro, See nel corpus) dicono 'text' con lo stesso tx3g dentro. Si prendono tutte e due; il capitolo di
# Apple ('text' con codec 'text', 15 campioni) resta fuori per codec e per numero di battute.
MP4_TESTO = (b'sbtl', b'text', b'subt')
# Sottotitoli che non contiamo: VobSub ('subp'), sottotitoli per non udenti ('clcp'), e nei marcatori di testo i codec
# che non sono tx3g (WebVTT, TTML, CEA-608/708). Il capitolo di Apple ('text'/'text') non e' un sottotitolo.
MP4_SUB_ALTRI = (b'subp', b'clcp')
MP4_CODEC_ALTRI = ('wvtt', 'stpp', 'c608', 'c708')


def mp4_non_contate(tracce):
	"""True se fra le trak c'e' un sottotitolo che non sappiamo contare: la presenza di una traccia completa nella lingua
	dell'utente allora non e' un giudizio (code review 30/09: un italiano completo in WebVTT si sarebbe ignorato)."""
	for t in tracce:
		h = (t.get('handler') or '').encode('latin-1')
		if h in MP4_SUB_ALTRI or (h in MP4_TESTO and t.get('codec') in MP4_CODEC_ALTRI): return True
	return False


def scatole(d, i, fine):
	"""(tipo, inizio del contenuto, fine) delle scatole in d[i:fine]. Taglia 0 = fino alla fine, 1 = a 64 bit."""
	fine = min(fine, len(d))
	while i + 8 <= fine:
		t = int.from_bytes(d[i:i + 4], 'big'); tipo = d[i + 4:i + 8]; h = 8
		if t == 1:
			if i + 16 > fine: return
			t = int.from_bytes(d[i + 8:i + 16], 'big'); h = 16
		elif t == 0: t = fine - i
		if t < h: return
		yield tipo, i + h, i + t
		i += t


def gestore_mp4(d, a, z):
	"""Il marcatore (hdlr) di una trak, da trak/mdia/hdlr, anche se la trak e' letta solo in parte. None se non c'e'."""
	try:
		for t, x, y in scatole(d, a, z):
			if t == b'mdia':
				for t2, x2, y2 in scatole(d, x, y):
					if t2 == b'hdlr' and x2 + 12 <= len(d): return d[x2 + 8:x2 + 12]
	except Exception: pass
	return None


def traccia_mp4(d, a, z):
	"""Una trak intera -> {'handler', 'scala', 'lang', 'codec', 'stts', 'stsz'} (come il banco). {} se illeggibile."""
	info = {}
	def giu(a, z):
		for t, x, y in scatole(d, a, z):
			if t in (b'mdia', b'minf', b'stbl'): giu(x, y)
			elif t == b'hdlr': info['handler'] = d[x + 8:x + 12].decode('latin-1')
			elif t == b'mdhd':
				v = d[x]
				info['scala'] = int.from_bytes(d[x + (20 if v == 1 else 12):x + (24 if v == 1 else 16)], 'big')
				lang = int.from_bytes(d[x + (32 if v == 1 else 20):x + (34 if v == 1 else 22)], 'big')
				info['lang'] = ''.join(chr(((lang >> s) & 31) + 0x60) for s in (10, 5, 0))
			elif t == b'stsd': info['codec'] = d[x + 12:x + 16].decode('latin-1')
			elif t == b'stts':
				n = int.from_bytes(d[x + 4:x + 8], 'big')
				info['stts'] = [(int.from_bytes(d[x + 8 + 8 * k:x + 12 + 8 * k], 'big'), int.from_bytes(d[x + 12 + 8 * k:x + 16 + 8 * k], 'big')) for k in range(n)]
			elif t == b'stsz':
				unica = int.from_bytes(d[x + 4:x + 8], 'big'); n = int.from_bytes(d[x + 8:x + 12], 'big')
				info['stsz'] = [unica] * n if unica else [int.from_bytes(d[x + 12 + 4 * k:x + 16 + 4 * k], 'big') for k in range(n)]
	try: giu(a, z)
	except Exception: return {}
	return info


def linea_mp4(info):
	"""tx3g: un campione vuoto (2 byte) cancella la battuta. -> [(inizio, fine)] ms, [] se mancano le tabelle."""
	if not info.get('scala') or 'stts' not in info or 'stsz' not in info: return []
	tempi, t = [], 0
	for n, d in info['stts']:
		for _ in range(n): tempi.append((t, d)); t += d
	k = 1000.0 / info['scala']
	return [(a * k, (a + d) * k) for (a, d), s in zip(tempi, info['stsz']) if s > 2]


def candidate_mp4(tracce):
	"""Le tracce di testo tx3g complete abbastanza da contare, nella forma di tracce_complete() (prima di ordina()).
	tracce: [{'handler', 'codec', 'lang', 'linea'}]."""
	fuori = []
	for t in tracce:
		if (t.get('handler') or '').encode('latin-1') in MP4_TESTO and t.get('codec') == 'tx3g' and len(t.get('linea') or []) >= MIN_BATTUTE:
			fuori.append({'lingua': (t.get('lang') or '')[:3], 'nome': t.get('codec') or '', 'sdh': False, 'classe': 0,
						  'forced': False, 'linea': [tuple(x) for x in t['linea']]})
	return fuori
