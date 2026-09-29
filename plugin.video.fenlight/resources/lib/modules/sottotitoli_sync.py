# -*- coding: utf-8 -*-
"""Lotto 415 (SOTTOTITOLI.md) -- allineamento di un sottotitolo sulla linea temporale del file che si riproduce.

Python puro, nessuna dipendenza da Kodi: lo usa anche il banco (tests/sottotitoli), che su questo codice ha misurato
ogni soglia. Intervalli in millisecondi [(inizio, fine)], ordinati per inizio.

Il riferimento e' il PARLATO del file: i tempi delle sue tracce di sottotitoli incorporate (sottotitoli_tracce.py), in
qualunque lingua. Non serve il testo. Tre passi, in cascata:
  1. globale(): un offset unico e un rapporto di velocita' (25/23,976 e compagni). Istogramma delle differenze fra
     inizi, poi rifinitura sulla sovrapposizione.
  2. candidati(): un offset per blocco di 16 battute, A CATENA: ogni blocco prova l'offset del precedente e cerca
     solo se non combacia. Se ogni blocco combacia con l'offset unico, si finisce qui (il caso tipico).
  3. a_tratti(): programmazione dinamica sugli offset dei blocchi. Offset che SALE = il film ha materiale che il
     sottotitolo non ha (un'edizione piu' lunga): niente da togliere. Offset che SCENDE di D = il sottotitolo ha D ms
     che il film non ha: quelle battute si tolgono.
Il giudizio lo da' accettabile(): un allineamento vale se ha agganciato il parlato, altrimenti si rifiuta invece di
applicare male.

Numeri del banco (corpus del 28/09, 187 file in lingua originale): 164 accettati al primo sottotitolo, 6 al secondo o
terzo, 0 falliti; errore contro la verita' da 0,73 senza sincronizzazione a 0,15. Sulla Firestick ~22 volte il Mac:
caso tipico ~1,5-2 s di un core.
"""
import re, bisect

RAPPORTI = (1.0, 25 / 23.976, 23.976 / 25, 24 / 23.976, 23.976 / 24, 25 / 24, 24 / 25)
TEMPO = re.compile(r'(\d+):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d+):(\d{2}):(\d{2})[,.](\d{1,3})')
SOGLIA_TRATTI = 0.005    # i gradini da DVD (+-400 ms) cambiano poco la copertura e molto l'errore: soglia bassa
SOGLIA_BUCHI = 0.10      # oltre questa quota di parlato scoperto si prova il candidato successivo


# ---- srt -----------------------------------------------------------------------------------------------------------
def _ms(h, m, s, f): return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(f.ljust(3, '0'))


def decodifica(dati):
	"""I byte di un srt come testo. OpenSubtitles converte in utf-8, ma un srt vecchio puo' essere cp1252."""
	for c in ('utf-8-sig', 'cp1252', 'latin-1'):
		try: return dati.decode(c)
		except UnicodeDecodeError: pass
	return ''


def leggi_srt(testo):
	"""[(inizio, fine, testo)] ordinate per inizio."""
	fuori = []
	for b in re.split(r'\r?\n\s*\r?\n', (testo or '').strip()):
		m = TEMPO.search(b)
		if m:
			g = m.groups()
			fuori.append((_ms(*g[:4]), _ms(*g[4:]), b[m.end():].strip()))
	fuori.sort()
	return fuori


def _hms(ms):
	ms = max(0, int(round(ms)))
	return '%02d:%02d:%02d,%03d' % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def scrivi_srt(righe, al):
	"""Il sottotitolo allineato. righe: [(inizio, fine, testo)] originali; al: [(inizio, fine, indice)] da allinea()."""
	pezzi = []
	for n, (A, B, i) in enumerate(sorted(al), 1):
		pezzi.append('%d\n%s --> %s\n%s\n' % (n, _hms(A), _hms(B), righe[i][2]))
	return '\n'.join(pezzi)


# ---- riferimento ----------------------------------------------------------------------------------------------------
class Riferimento:
	"""Il parlato di riferimento come unione di intervalli, con somme prefisse: sovrapposizione in O(log n)."""
	def __init__(self, intervalli):
		fusi = []
		for a, b in sorted(intervalli):
			if b <= a: continue
			if fusi and a <= fusi[-1][1]: fusi[-1][1] = max(fusi[-1][1], b)
			else: fusi.append([a, b])
		self.inizi = [a for a, b in fusi]
		self.fini = [b for a, b in fusi]
		self.starts = sorted(a for a, b in intervalli)
		self.cum = [0]
		for a, b in fusi: self.cum.append(self.cum[-1] + b - a)

	def _fino(self, x):
		i = bisect.bisect_right(self.inizi, x) - 1
		return 0 if i < 0 else self.cum[i] + min(x, self.fini[i]) - self.inizi[i]

	def sovrapposizione(self, a, b):
		return self._fino(b) - self._fino(a) if b > a else 0


def trasforma(iv, rapporto, offset): return [(a * rapporto + offset, b * rapporto + offset) for a, b in iv]
def punteggio(ref, iv, rapporto=1.0, offset=0): return sum(ref.sovrapposizione(a * rapporto + offset, b * rapporto + offset) for a, b in iv)


# ---- 1. offset unico --------------------------------------------------------------------------------------------------
def istogramma(ref, iv, rapporto, finestra=120000, passo=100, campione=1):
	"""Voti delle differenze fra inizi, a secchielli di `passo` ms, entro +-finestra. `campione`: una battuta ogni N."""
	voti, s = {}, ref.starts
	mezzo = passo // 2
	get = voti.get
	for a, b in iv[::campione]:
		x = int(a * rapporto)
		for j in range(bisect.bisect_left(s, x - finestra), bisect.bisect_right(s, x + finestra)):
			k = (int(s[j]) - x + mezzo) // passo
			voti[k] = get(k, 0) + 1
	return voti, passo


def picchi(voti, passo, quanti=8, distanza=1000):
	"""Offset piu' votati (lisciati su +-1 secchiello), distanti fra loro. -> [(offset, voti)]"""
	liscio = {k: voti.get(k - 1, 0) + voti[k] + voti.get(k + 1, 0) for k in voti}
	scelti = []
	for k in sorted(liscio, key=liscio.get, reverse=True):
		if all(abs(k - q) * passo >= distanza for q in scelti): scelti.append(k)
		if len(scelti) >= quanti: break
	return [(k * passo, liscio[k]) for k in scelti]


def rifinisci(ref, iv, rapporto, offset):
	"""+-600 a passi di 100, poi +-80 a passi di 20: 22 valutazioni."""
	best = offset
	for raggio, passo in ((600, 100), (80, 20)):
		c = best
		best = max(range(c - raggio, c + raggio + 1, passo), key=lambda o: punteggio(ref, iv, rapporto, o))
	return best, punteggio(ref, iv, rapporto, best)


def globale(ref, iv, finalisti=2):
	"""(rapporto, offset, copertura) con un offset unico.
	Istogramma dei 7 rapporti su una battuta ogni 3; i due picchi piu' forti rifiniti (+-600 poi +-80) su una battuta
	ogni 2; poi +-40 sul totale. Una rifinitura piu' corta (+-300 su una ogni 3) peggiorava le edizioni."""
	parlato = sum(b - a for a, b in iv) or 1
	campione = 3 if len(iv) > 300 else 1
	cand = []
	for r in RAPPORTI:
		voti, passo = istogramma(ref, iv, r, campione=campione)
		cand += [(forza, r, off) for off, forza in picchi(voti, passo, quanti=2)]
	cand.sort(reverse=True)
	meta = iv[::2] if len(iv) > 300 else iv
	migliori = []
	for forza, r, off in cand[:finalisti]:
		o, p = rifinisci(ref, meta, r, off)
		migliori.append((p, r, o))
	if not migliori: return 1.0, 0, 0.0
	p, r, o = max(migliori)
	best = max(range(o - 40, o + 41, 20), key=lambda x: punteggio(ref, iv, r, x))
	return r, best, punteggio(ref, iv, r, best) / (parlato * r)


# ---- 2. candidati a catena ------------------------------------------------------------------------------------------
def _coperto(ref, bl, rapporto, o):
	d = sum(b - a for a, b in bl) * rapporto or 1
	return punteggio(ref, bl, rapporto, o) / d


def _rifinisci_breve(ref, bl, rapporto, o):
	"""+-300 a passi di 100, poi +-40 a passi di 20: 12 valutazioni su un blocco."""
	for raggio, passo in ((300, 100), (40, 20)):
		c = o
		o = max(range(c - raggio, c + raggio + 1, passo), key=lambda x: punteggio(ref, bl, rapporto, x))
	return o


def _cerca(ref, bl, rapporto, centro, raggio, passo=100):
	"""Picco dell'istogramma delle differenze del blocco, entro +-raggio da centro."""
	s, v = ref.starts, {}
	mezzo = passo // 2
	for a, b in bl:
		x = int(a * rapporto) + centro
		for j in range(bisect.bisect_left(s, x - raggio), bisect.bisect_right(s, x + raggio)):
			k = (int(s[j]) - x + mezzo) // passo
			v[k] = v.get(k, 0) + 1
	if not v: return None, 0
	k = max(v, key=lambda k: v.get(k - 1, 0) + v[k] + v.get(k + 1, 0))
	return centro + k * passo, v.get(k - 1, 0) + v[k] + v.get(k + 1, 0)


def candidati_a_blocchi(ref, iv, rapporto, raggio, blocco=16, offset_globale=0, buono=0.55):
	"""[(offset, voti)]: un offset per blocco di 16 battute, A CATENA. Si prova l'offset del blocco prima; se il blocco
	non combacia, si cerca vicino (+-15 s); se ancora no, largo (+-raggio). La ricerca larga resta solo dove l'edizione
	cambia: su un film senza tagli ogni blocco costa una dozzina di valutazioni invece di un istogramma su minuti."""
	trovati, prec = [], offset_globale
	for b0 in range(0, len(iv), blocco):
		bl = iv[b0:b0 + blocco]
		if len(bl) < 4: break
		if _coperto(ref, bl, rapporto, prec) >= buono:
			o = _rifinisci_breve(ref, bl, rapporto, prec)
		else:
			o = None
			for centro, r in ((prec, 15000), (offset_globale, raggio)):
				c, voti = _cerca(ref, bl, rapporto, centro, r)
				if c is None or voti < len(bl) // 3: continue
				c = _rifinisci_breve(ref, bl, rapporto, c)
				if _coperto(ref, bl, rapporto, c) >= buono * 0.8: o = c; break
			if o is None: continue
		trovati.append(o); prec = o
	return [(o, sum(1 for p in trovati if abs(p - o) <= 200)) for o in trovati]


def candidati(ref, iv, rapporto, durata_file, offset_globale):
	"""I candidati a catena col raggio adattato alla differenza di durata fra file e sottotitolo: le edizioni spostano
	di decine di minuti, e l'ultima battuta sottostima (i titoli di coda non ne hanno): raggio = 2 x delta + 3 min."""
	ultima = iv[-1][1] * rapporto
	delta = abs((durata_file or ultima) - ultima)
	return candidati_a_blocchi(ref, iv, rapporto, max(120000, 2 * delta + 180000), offset_globale=offset_globale or 0)


# ---- 3. a tratti ----------------------------------------------------------------------------------------------------
def a_tratti(ref, iv, rapporto, durata_file=None, penalita=2000, tol=500, costo_tolta=0.5, offset_globale=None, max_cand=16, grezzi=None):
	"""-> ([(inizio, fine, indice originale)], copertura, tagli, battute tolte)

	Candidati: gli offset dei blocchi piu' l'offset globale, i max_cand piu' frequenti. DP: offset che sale = il film ha
	materiale senza sottotitolo; offset che scende di D = via le battute nei D ms prima del taglio, e ogni battuta tolta
	costa costo_tolta x la sua durata (senza costo la DP toglie per saltare verso offset spuri). Dopo la DP ogni tratto
	si rifinisce su TUTTE le sue battute: il candidato di un blocco e' impreciso di centinaia di ms. O(n x K^2).
	"""
	n = len(iv)
	if not n: return [], 0.0, 0, 0
	if grezzi is None: grezzi = candidati(ref, iv, rapporto, durata_file, offset_globale)
	grezzi = list(grezzi)
	if offset_globale is not None: grezzi.append((offset_globale, 10 ** 6))
	# i piu' votati; fusi entro 200 ms
	grezzi.sort(key=lambda x: -x[1])
	cand = []
	for o, v in grezzi:
		if all(abs(o - c) > 200 for c in cand): cand.append(o)
		if len(cand) >= max_cand: break
	cand.sort()
	if not cand: cand = [0]
	K = len(cand)
	inizi = [a * rapporto for a, b in iv]
	durate = [0]
	for a, b in iv: durate.append(durate[-1] + (b - a) * rapporto)
	g = [[ref.sovrapposizione(a * rapporto + o, b * rapporto + o) for o in cand] for a, b in iv]
	NEG = float('-inf')
	V = [[NEG] * K for _ in range(n)]
	P = [[None] * K for _ in range(n)]
	V[0] = list(g[0])
	for i in range(1, n):
		Vp = V[i - 1]
		for k2 in range(K):
			best, arg = Vp[k2], (i - 1, k2)
			# sale (cand[k1] < cand[k2]): nessuna battuta tolta
			for k1 in range(k2):
				v = Vp[k1] - penalita
				if v > best: best, arg = v, (i - 1, k1)
			# scende di D: si torna all'ultima battuta prima dei D ms che il film non ha
			for k1 in range(k2 + 1, K):
				D = cand[k1] - cand[k2]
				j = bisect.bisect_right(inizi, inizi[i] - D + tol) - 1
				if j < 0 or j >= i: continue
				v = V[j][k1] - penalita - costo_tolta * (durate[i] - durate[j + 1])
				if v > best: best, arg = v, (j, k1)
			V[i][k2] = best + g[i][k2] if best > NEG else NEG
			P[i][k2] = arg
	i, k = n - 1, max(range(K), key=lambda k: V[n - 1][k])
	tenute = []
	while True:
		tenute.append((i, k))
		if P[i][k] is None: break
		i, k = P[i][k]
	tenute.reverse()
	tratti = []
	for i, k in tenute:
		if tratti and tratti[-1][0] == k: tratti[-1][1].append(i)
		else: tratti.append((k, [i]))
	offs = {}
	for k, idx in tratti:
		o = cand[k]
		if len(idx) >= 8: o = rifinisci(ref, [iv[x] for x in idx], rapporto, o)[0]
		for x in idx: offs[x] = o
	al = [(iv[i][0] * rapporto + offs[i], iv[i][1] * rapporto + offs[i], i) for i, k in tenute]
	parlato = durate[-1] or 1
	return al, sum(ref.sovrapposizione(A, B) for A, B, i in al) / parlato, len(tratti) - 1, n - len(al)


# ---- la cascata e il giudizio -----------------------------------------------------------------------------------------
def allinea(ref, iv, durata_file=None, **kw):
	"""-> {'al': [(inizio, fine, indice)], 'metodo': 'unico'|'tratti', 'rapporto', 'offset', 'cop', 'cop_unico',
	'tagli', 'tolte', 'precisione', 'aggancio'}. `ref` e' un Riferimento, `iv` le battute [(inizio, fine)], la durata
	del file in ms (dall'intestazione). I tratti si tengono solo se aggiungono almeno SOGLIA_TRATTI di copertura."""
	r, o, f = globale(ref, iv)
	unico = {'al': [(a * r + o, b * r + o, i) for i, (a, b) in enumerate(iv)], 'metodo': 'unico', 'rapporto': r, 'offset': o,
			 'cop': f, 'cop_unico': f, 'tagli': 0, 'tolte': 0}
	grezzi = candidati(ref, iv, r, durata_file, o)
	blocchi = (len(iv) + 15) // 16
	if len(grezzi) >= 0.7 * blocchi and all(abs(g - o) <= 200 for g, v in grezzi):
		# ogni blocco combacia con l'offset globale: niente tratti, niente DP (il caso tipico)
		esito = unico
	else:
		al, f2, tagli, tolte = a_tratti(ref, iv, r, durata_file, offset_globale=o, grezzi=grezzi, **kw)
		if tagli and f2 >= f + SOGLIA_TRATTI:
			esito = {'al': al, 'metodo': 'tratti', 'rapporto': r, 'offset': o, 'cop': f2, 'cop_unico': f, 'tagli': tagli, 'tolte': tolte}
		elif not tagli and tolte == 0 and f2 > f:
			# un tratto solo, rifinito su tutto: e' l'offset unico migliorato
			esito = dict(unico, al=al, offset=al[0][0] - iv[al[0][2]][0] * r if al else o, cop=f2)
		else:
			esito = unico
	esito['precisione'], esito['aggancio'] = precisione(ref, esito['al'])
	return esito


def con_riserva(primo, secondo, iv, durata_file=None, **kw):
	"""allinea() sul primo riferimento; se non e' accettabile, sul secondo (sottotitoli_tracce.secondo), e si tiene il
	secondo se accettabile o migliore in copertura senza perdere precisione. Sul corpus il secondo serve 16 volte su
	504. primo/secondo: linee [(inizio, fine)], secondo puo' essere None. -> esito con 'rif' (0 o 1) e 'ref' (il
	Riferimento usato, per buchi())."""
	R0 = Riferimento(primo)
	e = allinea(R0, iv, durata_file, **kw)
	e['rif'], e['ref'] = 0, R0
	if accettabile(e) or not secondo: return e
	R1 = Riferimento(secondo)
	e1 = allinea(R1, iv, durata_file, **kw)
	e1['rif'], e1['ref'] = 1, R1
	if accettabile(e1) or (e1['cop'] > e['cop'] and e1['precisione'] >= e['precisione']): return e1
	return e


def precisione(ref, al, entro=300):
	"""(precisione, aggancio). aggancio = quota di battute allineate che toccano il parlato di riferimento; precisione =
	fra queste, quota con l'inizio entro `entro` ms dall'inizio di una battuta di riferimento. Un allineamento giusto fa
	coincidere gli inizi anche se il riferimento e' parziale; uno casuale no, anche quando copre molto."""
	s = ref.starts
	toccano = vicine = 0
	for A, B, i in al:
		if ref.sovrapposizione(A, B) <= 0: continue
		toccano += 1
		j = bisect.bisect_left(s, A)
		if any(0 <= k < len(s) and abs(s[k] - A) <= entro for k in (j - 1, j)): vicine += 1
	return (vicine / toccano if toccano else 0.0), (toccano / len(al) if al else 0.0)


def accettabile(esito):
	"""Copertura alta basta da sola; media se gli inizi coincidono; bassa solo se gli inizi coincidono bene e meta' delle
	battute tocca il riferimento (riferimento parziale: film multilingue). Sul corpus un sottotitolo sbagliato ha
	precisione <= 0,27; 1 falso accetto (mediocre, non sbagliato) e 1 falso rifiuto su 168 righe con verita'."""
	c, p, a = esito['cop'], esito['precisione'], esito['aggancio']
	return c >= 0.85 or (c >= 0.70 and p >= 0.30) or (c >= 0.45 and p >= 0.55 and a >= 0.45)


def buchi(ref, al, margine=2000):
	"""Quota del parlato di riferimento senza nessuna battuta allineata entro `margine` ms. In parte e' rumore del
	riferimento (i suoni delle tracce SDH, uguali per tutti i candidati), in parte un'edizione diversa: oltre
	SOGLIA_BUCHI si prova il candidato successivo e si tiene quello con meno buchi."""
	if not al: return 1.0
	S = Riferimento([(A - margine, B + margine) for A, B, i in al])
	tot = scoperto = 0
	for a, b in zip(ref.inizi, ref.fini):
		tot += b - a
		scoperto += (b - a) - S.sovrapposizione(a, b)
	return scoperto / tot if tot else 0.0
