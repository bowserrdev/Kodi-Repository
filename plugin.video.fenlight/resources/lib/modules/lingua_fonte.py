# -*- coding: utf-8 -*-
"""Lotto 414 (SORGENTI.md) -- la lingua di una fonte, per l'opzione "preferred source language".

Una sola risposta per nome: DOPPIATA (2), SOLO SOTTOTITOLATA (1), NO (0) nella lingua scelta, qualunque sia. La usano
l'ordinamento (sort_preferred_language di modules/sources.py) e la copertura del verificatore (_copertura di
scrapers/external.py). Doppiata per una di tre vie, tutte uguali: la lingua scritta nel nome come audio; la lingua originale
dell'opera; un titolo della lingua nel nome (se il nome non dice che quella lingua c'e' solo nei sottotitoli).

Si prepara una volta per ricerca (`prepara`, che ricorda l'ultima) e risponde per nome (`livello`). Senza Kodi: gira anche sul
banco.
"""
import re
import unicodedata
from modules.classificatore import Domanda, parole, gettoni, _tratto, _leet

DOPPIATA, SOTTOTITOLATA, NO = 2, 1, 0

# iso 639-1: codici a due lettere, codici a tre lettere, nomi (in inglese, nella lingua e nelle lingue delle release), parole
# del doppiaggio, parole dei sottotitoli, paesi (per i titoli alternativi di TMDb). Tutto senza accenti e in minuscolo, tranne i
# paesi. I paesi con piu' lingue non ci sono: non dicono la lingua di un titolo.
LINGUE = {
	'it': (('it',), ('ita',), ('italian', 'italiano', 'italien', 'italienisch'), (), ('subita',), ('IT', 'SM', 'VA')),
	'es': (('es', 'sp'), ('spa', 'esp'), ('spanish', 'espanol', 'castellano', 'latino', 'spagnolo', 'espagnol', 'spanisch'), (),
		   ('vose', 'subesp'), ('ES', 'MX', 'AR', 'CO', 'CL', 'PE', 'VE', 'UY', 'EC', 'BO', 'PY', 'CR', 'CU', 'DO', 'GT', 'HN', 'NI', 'PA', 'SV')),
	'fr': (('fr',), ('fre', 'fra'), ('french', 'francais', 'frances', 'francese', 'franzosisch'),
		   ('vff', 'vfq', 'vfi', 'vf', 'vf2', 'truefrench'), ('vostfr', 'subfrench', 'stfr'), ('FR',)),
	'de': (('de', 'ge'), ('ger', 'deu'), ('german', 'deutsch', 'aleman', 'tedesco', 'allemand'), (), ('subger',), ('DE', 'AT')),
	'pt': (('pt',), ('por',), ('portuguese', 'portugues', 'portoghese', 'portugais'), ('dublado',), ('legendado',), ('PT', 'BR')),
	'en': (('en',), ('eng',), ('english', 'ingles', 'inglese', 'anglais', 'englisch'), (), ('subeng',), ('US', 'GB', 'UK', 'AU', 'NZ', 'IE')),
	# i tracker russi non scrivono la lingua del doppiaggio: "Dub + DVO + Sub (Rus, Eng) + Original Eng" (Dub e VO: _RUSSO)
	'ru': (('ru',), ('rus',), ('russian', 'ruso', 'russo', 'russe', 'russisch'), ('mvo', 'dvo', 'avo', 'vo', 'dub'), (), ('RU',)),
	'ja': (('ja', 'jp'), ('jpn', 'jap'), ('japanese',), (), (), ('JP',)),
	'ko': (('ko', 'kr'), ('kor',), ('korean',), (), (), ('KR',)),
	'zh': (('zh', 'cn'), ('chi', 'zho', 'chn'), ('chinese', 'mandarin', 'cantonese'), (), (), ('CN', 'TW', 'HK')),
	'pl': (('pl',), ('pol',), ('polish', 'polski'), (), (), ('PL',)),
	'tr': (('tr',), ('tur',), ('turkish',), (), (), ('TR',)),
	'hi': (('hi',), ('hin',), ('hindi',), (), (), ()),
	'nl': (('nl',), ('dut', 'nld'), ('dutch',), (), (), ('NL',)),
	'hu': (('hu',), ('hun',), ('hungarian',), (), (), ('HU',)),
	'cs': (('cs', 'cz'), ('cze', 'ces'), ('czech',), (), (), ('CZ',)),
	'uk': (('uk', 'ua'), ('ukr',), ('ukrainian',), (), (), ('UA',)),
	'th': (('th',), ('tha',), ('thai',), (), (), ('TH',)),
	'ar': (('ar',), ('ara',), ('arabic',), (), (), ()),
	'he': (('he',), ('heb',), ('hebrew',), (), (), ('IL',)),
	'sv': (('sv',), ('swe',), ('swedish',), (), (), ('SE',)),
	'da': (('da', 'dk'), ('dan',), ('danish',), (), (), ('DK',)),
	'fi': (('fi',), ('fin',), ('finnish',), (), (), ('FI',)),
	'no': (('no',), ('nor',), ('norwegian',), (), (), ('NO',)),
	'el': (('el', 'gr'), ('gre', 'ell'), ('greek',), (), (), ('GR',)),
	'ro': (('ro',), ('rum', 'ron'), ('romanian',), (), (), ('RO',)),
	'ta': (('ta',), ('tam',), ('tamil',), (), (), ()),
	'te': (('te',), ('tel',), ('telugu',), (), (), ()),
	'vi': (('vi',), ('vie',), ('vietnamese',), (), (), ('VN',)),
	'id': (('id',), ('ind',), ('indonesian',), (), (), ('ID',)),
}
# codici a tre lettere che sono anche parole o sigle ("Tai Chi", "[Fin]" delle release cinesi, "C'est la vie", "Batalla por…",
# il gruppo iND): valgono solo dentro una lista di codici, come quelli a due lettere
AMBIGUI = frozenset(('chi', 'dan', 'fin', 'fra', 'por', 'vie', 'ind', 'nor', 'tha', 'pol'))
_PAESI = dict((p, k) for k, v in LINGUE.items() for p in v[5])
_DUE = sorted(set(c for v in LINGUE.values() for c in v[0]) | {'mx'})
_TRE = sorted(set(c for v in LINGUE.values() for c in v[1]) | {'lat'})
_NOMI = set(c for v in LINGUE.values() for c in v[2])
# le parole che dicono una lingua: una corsa di queste si legge insieme (audio o sottotitoli)
_LINGUA_TOK = frozenset(_DUE) | frozenset(_TRE) | _NOMI
_SUB_TOK = frozenset(('sub', 'subs', 'subbed', 'subtitle', 'subtitles', 'subtitled', 'sottotitoli', 'sottotitolato', 'srt',
					  'multisub', 'multisubs', 'softsub', 'softsubs', 'hardsub', 'subtitulado', 'subtitulos', 'legendas', 'untertitel'))
_DUB_TOK = frozenset(('dub', 'dubs', 'dubbed', 'audio', 'dual', 'multiaudio'))
_PARENTESI = frozenset('[]()')
# la regione dopo un codice non chiude la lista: "[POR-BR][SPA-LA]", "ES-419", "EN-US"
_REGIONI = frozenset(('br', 'la', 'lat', 'latam', 'us', 'uk', 'mx', 'eu', 'ca', '419'))
# una lista di codici di lingua: almeno due, i codici a due lettere solo in maiuscolo, con il numero delle tracce ("2Rus")
_CODICE = r'(?:\d*(?:%s)|\d*(?i:%s))' % ('|'.join(c.upper() for c in _DUE), '|'.join(_TRE))
_LISTA = re.compile(r'(?<![A-Za-z0-9])(?:{0}[ .+\-,/_|·\]\[()]+)+{0}(?![A-Za-z0-9])'.format(_CODICE))
_MARCA = 'zzlinguazz'
_TOKEN = re.compile(r'[^a-z0-9\[\]()]+|(?=[\[\]()])|(?<=[\[\]()])')
# il numero delle tracce attaccato al codice: "2rus", "23xrus", "itax2"
_TRACCE = re.compile(r'^\d+x?(?=[a-z]{3}$)|(?<=^[a-z]{3})x\d+$')
_LINGUE_RE = '|'.join(sorted(_LINGUA_TOK, key=len, reverse=True))
_ANNO = re.compile(r'(19|20)\d\d$')

def _piano(s):
	return ''.join(c for c in unicodedata.normalize('NFKD', s or '') if not unicodedata.combining(c))

def lingua_scelta(valore):
	"""Il codice iso 639-1 della lingua scritta nell'opzione ("ita", "Italian", "it"), o None se non e' nella tabella."""
	v = _piano(valore or '').strip().lower()
	if not v: return None
	return next((k for k, t in LINGUE.items() if v == k or v in t[0] or v in t[1] or v in t[2]), None)

def lingua_dell_alias(codice, originale):
	"""La lingua di un alias di make_alias_dict: le traduzioni hanno la lingua ("it"), i titoli alternativi il paese ("IT"), il
	titolo originale la lingua originale. Gli alias "titolo + paese" (codice vuoto) e i paesi con piu' lingue: None."""
	if not codice: return None
	if codice == 'original': return originale or None
	if codice.isupper(): return _PAESI.get(codice)
	return _iso(codice)

def _iso(codice):
	# i codici di TMDb nella forma della tabella: "cn" (il cantonese per TMDb) e' cinese
	codice = (codice or '').lower()
	return lingua_scelta(codice) or codice

def _norma(t):
	# le parole di un titolo, senza gli anni ("Dororo (2019)" e' "Dororo")
	return tuple(w for w in parole(t or '') if not _ANNO.match(w))

def _dentro(a, b):
	return any(b[i:i + len(a)] == a for i in range(len(b) - len(a) + 1))


class LinguaFonte:
	def __init__(self, lingua, info=None, parola=None):
		self.lingua = lingua
		info = info or {}
		if not lingua:
			# lingua fuori dalla tabella: il comportamento di prima del lotto, la parola scritta nell'opzione
			self._parola = re.compile(r'(?<![a-z])' + re.escape(parola) + r'(?![a-z])') if parola else None
			return
		due, tre, nomi, doppiaggio, sottotitoli = LINGUE[lingua][:5]
		self._doppiaggio, self._sottotitoli = frozenset(doppiaggio), frozenset(sottotitoli)
		self._mie = (frozenset(tre) - AMBIGUI) | frozenset(nomi) | self._doppiaggio
		self._in_lista = re.compile(r'(?<![A-Za-z])\d*(?:%s|(?i:%s))(?![A-Za-z])' % ('|'.join(c.upper() for c in due), '|'.join(tre)))
		originale = _iso(info.get('original_language'))
		self._originale = originale == lingua
		alias = [a for a in info.get('aliases') or [] if isinstance(a, dict)]
		# una parola della lingua che e' una parola del titolo non dice la lingua (il film "It")
		self._parole_titolo = frozenset(w for t in [info.get('title')] + [a.get('title') for a in alias] for w in parole(t or ''))
		# i titoli della lingua, tranne quelli uguali o contenuti in un titolo di un'altra lingua ("Inception" e' anche il titolo
		# italiano, "Grand Budapest Hotel" sta dentro "The Grand Budapest Hotel")
		mie, altre = [], []
		for a in alias:
			l, n = lingua_dell_alias(a.get('country'), originale), _norma(a.get('title'))
			if not n: continue
			# un paese con piu' lingue (o sconosciuto) non dice che il titolo e' di un'altra lingua
			if l == lingua: mie.append(a.get('title'))
			elif l: altre.append(n)
		mie = [t for t in dict.fromkeys(mie) if not any(_dentro(_norma(t), x) for x in altre)]
		args = (info.get('year'), 0, info.get('season'), info.get('episode'), info.get('absolute'), info.get('ultimo_anno'))
		self._domanda = Domanda(info.get('media_type'), mie, *args, esatto=True) if mie else None
		# i nomi bilingui ("Il Padrino - The Godfather (1972)"): il nome e' dell'opera (con tutti i suoi titoli) e nel tratto del
		# titolo c'e' un titolo della lingua. La domanda con tutti i titoli si fa solo se serve
		self._tutti = (info.get('media_type'), [info.get('title')] + [a.get('title') for a in alias], args)
		self._opera = None
		self._mie_parole = [p for p in (tuple(gettoni(t, parentesi=False)) for t in mie) if p]
		# il filtro che evita il classificatore sui nomi che non possono avere il titolo: il confronto e' esatto, quindi la prima
		# parola di un titolo (in una delle sue forme: incollata, letta, senza "part") c'e' nel nome
		self._prime = frozenset(t[0] for t in self._domanda._gettoni if t) if mie else frozenset()
		self._memo = {}

	def livello(self, nome, nome_file=None):
		"""DOPPIATA, SOTTOTITOLATA o NO per la fonte che si chiama `nome` (e il cui file si chiama `nome_file`, se si sa)."""
		if not self.lingua:
			return DOPPIATA if self._parola and self._parola.search((nome or '').lower()) else NO
		chiave = (nome, nome_file)
		esito = self._memo.get(chiave)
		if esito is None: esito = self._memo[chiave] = self._livello(nome, nome_file)
		return esito

	def _livello(self, nome, nome_file):
		audio, sott = self._nel_nome(nome or '')
		if nome_file and not audio:
			# anche il file dice la lingua ("Parthenope.2024.1080p.WEBRip" col file "Parthenope.2024.ITA-ENG…": 23 fonti su 14.866)
			a, s = self._nel_nome(nome_file)
			audio, sott = audio or a, sott or s
		if audio or self._originale: return DOPPIATA
		if self._domanda and not sott and any(self._titolo(n) for n in (nome, nome_file) if n): return DOPPIATA
		return SOTTOTITOLATA if sott else NO

	def _titolo(self, nome):
		# tutte le parole del nome, non i gettoni: il titolo si cerca anche dopo un separatore ("www.1TamilMV.fi - Titolo (2005)")
		w = parole(nome)
		if not self._prime.intersection(w) and not self._prime.intersection(_leet(x) for x in w): return False
		if self._domanda.titolo_nel_nome(nome): return True
		tratto = tuple(_tratto(gettoni(nome, parentesi=False)))
		if not any(_dentro(p, tratto) for p in self._mie_parole): return False
		if self._opera is None: self._opera = Domanda(self._tutti[0], self._tutti[1], *self._tutti[2], esatto=True)
		return self._opera.titolo_nel_nome(nome)

	def _nel_nome(self, nome):
		"""(audio, sottotitoli): la lingua scritta nel nome come audio e come sottotitoli."""
		testo = _piano(nome)
		# dentro una lista di codici valgono anche i codici a due lettere e quelli ambigui: si riscrivono con un segno solo
		testo = _LISTA.sub(lambda m: self._in_lista.sub(_MARCA, m.group(0)), testo)
		basso = testo.lower()
		tok = [_TRACCE.sub('', t) for t in _TOKEN.split(basso) if t]
		def lingua(t): return t in _LINGUA_TOK or t == _MARCA or t in self._doppiaggio
		def mia(t): return (t == _MARCA or t in self._mie) and t not in self._parole_titolo
		audio = sott = False
		i, n = 0, len(tok)
		while i < n:
			t = tok[i]
			if t in self._sottotitoli and t not in self._parole_titolo:
				sott = True
				i += 1
				continue
			if not lingua(t):
				i += 1
				continue
			# una corsa di lingue, anche attraverso le parentesi ("[ENG][POR-BR][ITA]")
			j, corsa = i, []
			while j < n and (lingua(tok[j]) or tok[j] in _PARENTESI or (tok[j] in _REGIONI and corsa)):
				if tok[j] not in _PARENTESI and tok[j] not in _REGIONI: corsa.append(tok[j])
				j += 1
			prima = next((tok[k] for k in range(i - 1, -1, -1) if tok[k] not in _PARENTESI), '')
			# la parola dopo la corsa conta solo nello stesso gruppo: "[Subs.ITA-ENG][Audio.JPN]", l'audio e' dell'altro gruppo
			dopo = tok[j] if j < n and tok[j - 1] not in _PARENTESI else ''
			# "(… Italian Dubs)" e' audio anche dopo "[Multi-Subs]"; "sub.ita.eng" e "[Multiple.Subtitle].[ENG]…" sono
			# sottotitoli; "iTALiAN.SUBBED" pure; "ITA.ENG.SUBS" e' audio, con i sottotitoli
			if dopo in _DUB_TOK: sotto = False
			elif prima in _SUB_TOK or dopo in ('subbed', 'subtitled'): sotto = True
			else: sotto = False
			mie = [x for x in corsa if mia(x)]
			if self.lingua == 'ru' and any(x in ('dub', 'vo') for x in mie):
				mie = [x for x in mie if x not in ('dub', 'vo') or _russo(basso, x)]
			if mie:
				if sotto: sott = True
				else: audio = True
			i = j
		return audio, sott


def _russo(basso, parola):
	"""Lotto 414: "Dub" e "VO" sono il doppiaggio russo solo nella forma dei tracker russi, accanto a un "+" e senza una lingua
	vicino ("Dub + DVO + Sub (Rus, Eng)"); da soli sono il "VO" francese, "Multi-Dub", "English.Dub"."""
	for m in re.finditer(r'(?<![a-z])%s(?![a-z])' % parola, basso):
		prima, dopo = basso[max(0, m.start() - 16):m.start()], basso[m.end():]
		forma = re.match(r'(?:[ ._]*\([^)]*\))?[ ._]*\+', dopo) or re.search(r'\+[ ._]*(?:\d+x[ ._]*)?$', prima)
		vicina = re.search(r'(?:^|[^a-z])(?:%s)[ ._-]$' % _LINGUE_RE, prima.split('+')[-1]) or re.match(r'[ ._-](?:%s)(?![a-z])' % _LINGUE_RE, dopo)
		if forma and not vicina: return True
	return False


_ultima = [None, None, None]

def prepara(info, valore):
	"""La LinguaFonte per una ricerca (`info`: search_info) e il valore dell'opzione, o None se l'opzione e' vuota. La stessa
	ricerca (lo stesso dizionario: search_info passa invariato a scrapers/external.py) riceve lo stesso oggetto, con la sua
	memoria: il verificatore e l'ordinamento non rifanno il lavoro."""
	valore = (valore or '').strip().lower()
	if not valore: return None
	if _ultima[0] is not None and _ultima[0] is info and _ultima[1] == valore: return _ultima[2]
	lf = LinguaFonte(lingua_scelta(valore), info, parola=valore)
	if info is not None: _ultima[:] = [info, valore, lf]
	return lf
