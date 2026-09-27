# -*- coding: utf-8 -*-
"""LOTTO 365 -- il classificatore del contenuto di un torrent (SORGENTI.md, sezione C).

Funzione PURA: niente rete, niente database, niente Kodi. Riceve l'elenco dei file di un torrent e la domanda
(questo film? questo episodio?) e risponde:

	(True,  file, motivo)   contiene cio' che si cerca, ed e' `file`
	(False, None, motivo)   non lo contiene, o non si puo' riprodurre per intero
	(None,  None, motivo)   non si sa (elenco assente)

Un file e' una tupla (percorso, nome, byte). Le regole e i numeri tra parentesi vengono dal test del 25/09/2026
(5.337 elenchi veri di TorBox, 67 ricerche); ogni soglia e' spiegata dove si usa. Lo stesso verdetto decide
l'elenco delle sorgenti (scrapers/external.py) e il file che la riproduzione sblocca (TorBoxAPI.resolve_magnet).

La Domanda si costruisce UNA volta per ricerca: espressioni e titoli normalizzati stanno li', non si rifanno
per file.
"""
import re
import unicodedata
from functools import lru_cache

VERSIONE = 28         # cambia quando cambia una regola: i verdetti salvati con un'altra versione si rifanno

# I contenitori video veri. NON supported_video_extensions: quella e' la lista dei "video" di Kodi e comprende
# playlist e collegamenti (.xspf, .m3u, .url, .ifo, .bin, .dat, .img...): nel test un torrent di Star Wars 4K77
# aveva "00-Playlist.xspf" accanto al film. pack_cache usa la stessa lista.
VIDEO = ('.mkv', '.mp4', '.avi', '.m4v', '.ts', '.m2ts', '.mts', '.mov', '.wmv', '.mpg', '.mpeg', '.webm', '.flv', '.vob',
		 '.divx', '.xvid', '.ogm', '.ogv', '.3gp', '.asf', '.rmvb', '.f4v', '.m2v', '.evo', '.wtv', '.trp', '.tp')
ARCHIVI = ('.zip', '.rar', '.7z', '.iso', '.exe', '.lnk', '.scr', '.bat', '.cmd')
CARTELLE_EXTRA = re.compile(r'(?:^|/)(?:samples?|extras?|featurettes?|behind[ ._-]the[ ._-]scenes|deleted[ ._-]scenes|trailers?|'
							r'bonus|interviews?|shorts|specials?[ ._-]features?)/', re.I)
SIGLE_ANIME = re.compile(r'(?<![a-z])(?:ncop|nced|creditless|nc[ ._-]?(?:op|ed))(?![a-z])', re.I)
# Le parti di UN film: "CD1", "disc 2", "PT1" (la versione estesa del Signore degli Anelli in due file), o
# "part N of M". NON "part 2" da solo: e' nel titolo di troppi film (prova del 25/09: la trilogia
# "the.godfather.part.2.1974" / "part.3.1990" passava per un film in parti).
# lotto 395: anche la parte in polacco ("Ania dalsze dzieje 1987 cz4"), non l'audio ceco ("CZ 5.1")
PARTI = re.compile(r'(?<![a-z0-9])(?:(?:cd|disc|disk|pt|reel)[ ._-]?0?[1-9](?![0-9])|cz[ ._-]?0?[1-9](?![0-9])(?![.,]\d)|'
				   r'part[ ._-]?0?[1-9][ ._-]?of[ ._-]?[1-9](?![0-9]))', re.I)
CD = PARTI
# lotto 392: anche la parola ("[FSP] Tales of Herding Gods Episode 74" per Tale of Tales, 1979)
# lotto 400: e gli OVA ("Naruto OVA 07 - Naruto, the Genie, and the Three Wishes" per The Last: Naruto the Movie)
EPISODIO = re.compile(r'(?<![a-z0-9])(?:s\d{1,2}[ ._-]?e\d{1,3}|(?:episode|episodio|[ée]pisode|folge|serie|ova|oad)[ ._-]?\d{1,4})(?![0-9])', re.I)
SPECIALE = re.compile(r'(?<![a-z0-9])s0*0[ ._-]?e\d', re.I)
ANNO = re.compile(r'(?<!\d)((?:19|20)\d\d)(?!\d)')
ETICHETTE_IN_TESTA = re.compile(r'^\s*((?:\[[^\]]*\]\s*)+)')
# lotto 402: anche il sito fra parentesi tonde ("(www.bwt.pw) Koi... Mil Gaya.2003")
TESTA = re.compile(r'^\s*(?:(?:\[[^\]]*\]|\{[^}]*\}|www\.[^ ]+\s*-?|\(\s*www\.[^)]*\)\s*-?|\(\s*(?:19|20)\d\d\s*\))\s*)+')
FINE_TITOLO = re.compile(r'^(?:19\d\d|20\d\d|2160p|1080p|720p|576p|480p|4k|uhd|bluray|blu|bdrip|brrip|bdremux|remux|web|webrip|'
						 r'webdl|dl|hdtv|dvdrip|dvd|hdrip|x264|x265|h264|h265|hevc|avc|xvid|divx|10bit|hdr|dv|imax|extended|'
						 r'unrated|directors|dc|remastered|criterion|repack|proper|ita|eng|multi|italian|english|dual|sub|subs|'
						 r'limited|internal|theatrical|restored|mkv|mp4|avi|'
						 # lotto 377: audio e formati ("American History X (1988) AC3 ...": tolte le parentesi, AC3 pareva titolo)
						 r'aac\d?|ac3|eac3|dts|dd\d?|ddp\d?|truehd|atmos|flac|opus|mp3|av1|sdr|rip|'
						 # lotto 386: descrittori tecnici ("Матрица (Open Matte)", "Toy.Story.3D", "The.Elephant.Man.HDDVD", "One Piece
						 # Film RED [BD Remux]") e lingue ("MATRIX.French", "Dune Part Two Castellano"); "open matte" e' una parola sola
						 r'3d|hsbs|sbs|hou|hddvd|bd|openmatte|french|truefrench|vff|vfq|vostfr|spanish|castellano|latino|german|'
						 r'rus|ukr|jap|jpn|kor|chi|'
						 # lotto 388: le lingue per intero ("[Anime Land] Godzilla Minus One (2023) (BDRip ...) JAPANESE")
						 r'japanese|korean|chinese|mandarin|cantonese|russian|ukrainian|hindi|tamil|telugu|portuguese|polish|dutch|'
						 r'swedish|danish|norwegian|finnish|turkish|arabic|hungarian|czech|thai|vietnamese|italiano|deutsch|'
						 # lotto 387: "Princess.Mononoke.HD"
						 r'hd|fhd|'
						 # lotto 407: la qualita' delle release di newpct ("Ratatouille [MicroHD][1080 px][AC3 5.1-Castellano...]", senza anno)
						 r'microhd|'
						 # e la risoluzione scritta per intero ("1972.The.Godfather.1920x1080.BDRip")
						 r'\d{3,4}x\d{3,4})$', re.I)
# lotto 386: una lettera di un'altra scrittura (non latina: cirillico, greco, CJK, coreano, arabo...)
NON_LATINO = re.compile(r'[^\W\d_\u0000-\u024F\u1E00-\u1EFF]')
ROMANI = re.compile(r'^(?:i|ii|iii|iv|v|vi|vii|viii|ix|x)$')
CODICE_COLLANA = re.compile(r'^[a-z]{1,3}\d{1,3}$')
EMITTENTI = frozenset(('bbc', 'hbo', 'nhk', 'pbs', 'itv', 'cbc', 'abc', 'nbc', 'cbs', 'amc', 'fx', 'rai', 'zdf', 'arte', 'ch4', 'natgeo', 'netflix', 'hulu'))
# lotto 413: le espressioni che le funzioni scrivevano ogni volta (re le ritrova in una cache, ma la ricerca costava 406.000 chiamate)
_ARTICOLO_IN_TESTA = re.compile(r'^\W*(?:the|a|an|il|lo|la|le|les|el|los|las|der|die|das)[\W_]+', re.I)
_APERTA, _GRUPPO_APERTO, _LETTERA_CIFRA = re.compile(r'[(\[{]'), re.compile(r'[(\[{]([^)\]}]*)'), re.compile(r'(?<=[a-z])\d')
ARTICOLO_IN_CODA = re.compile(r'^\s*(?:\[[^\]]*\]\s*)*([^,\[\]()]+?),[\s._]*(the|a|an|le|la|les|il|lo|der|die|das|el|los|las)\b(.*)$', re.I)
SEPARATORE = re.compile(r'\s+[-–]\s+|\.-\.|_-_')
# Lotto 366 -- negli episodi il titolo della serie finisce anche a "S03E13", "S04", "3x04", "season", o a un numero
# ("One Piece - 584"): e' li' che comincia la parte che dice QUALE episodio.
# lotto 391: anche l'ordinale della stagione ("Fruits Basket 1st Season - 08")
# lotto 410: anche "aka" ("Parasyte.The.Grey.A.K.A.Gisaengsu.Deo.Geurei.S01": dopo viene l'altro titolo della stessa serie)
FINE_SERIE = re.compile(r'^(?:s\d{1,2}(?:e\d{1,4}[a-z]{0,2})?|\d{1,2}x\d{1,4}|e?p?\d{1,4}|\d{1,2}(?:st|nd|rd|th)|season|seasons|stagione|saison|temporada|complete|completa|aka)$', re.I)
# Sotto questo peso per minuto della durata TMDb un file non e' il film: nel test l'unico caso e' un trailer
# (0,1 MB/min), e i film veri piu' leggeri stanno a 2,5 MB/min (una codifica 360p, un AV1).
MIN_MB_MINUTO = 1.0
# lotto 385: i paesi che distinguono due serie omonime ("The Office (US)" e "(UK)"), e la radice del disco degli extra
PAESI = frozenset(('us', 'usa', 'uk', 'au', 'nz'))
BONUS_DISC = re.compile(r'(?<![a-z])bonus[ ._-]?dis[ck](?![a-z])')
# Il piu' grande "domina" il secondo sopra questo rapporto: nel test i rapporti veri sono 20x e oltre (film
# contro campione o trailer), due film di una collezione stanno fra 1x e 2x.
DOMINIO = 4.0


def _piano(s):
	# lotto 386: NFKD senza i segni combinanti e minuscole. Il latino resta come prima ("é" -> "e"); le altre scritture restano
	# lettere ("Гарри Поттер", "千与千寻"). Fino al 385 si riduceva tutto ad ASCII, e gli alias non latini si scartavano
	# (lotto 366: "ダークナイト・ライジング：2012" diventava "2012" e prendeva il film "2012")
	s = s or ''
	if s.isascii(): return s.lower().replace('&', ' and ')
	t = ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))
	return t.casefold().replace('&', ' and ')

def parole(s):
	return [w for w in re.split(r'[\W_]+', _piano(s)) if w]

_LETTERA, _CIFRA, _TECNICO, _DA_LEET = re.compile(r'[a-z]'), re.compile(r'\d'), re.compile(r'^\d+(?:p|k|bit)$'), str.maketrans('01345', 'oiaes')

# lotto 386: _leet e _uguali sono funzioni pure chiamate decine di milioni di volte sulla passata (74 milioni _uguali): i
# risultati si ricordano per la durata della ricerca (ogni ricerca e' un interprete nuovo), cosi' i titoli in piu' non costano
@lru_cache(maxsize=65536)
def _leet(w):
	# le cifre DENTRO una parola si leggono come lettere ("fant0zzi"); non "1080p", "4k", "10bit"
	if _LETTERA.search(w) and _CIFRA.search(w) and not _TECNICO.match(w):
		return w.translate(_DA_LEET)
	return w

_ROMANI_CIFRE = dict(zip(('i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x'), ('1', '2', '3', '4', '5', '6', '7', '8', '9', '10')))
# lotto 404: le lettere che distinguono una serie ("Sailor Moon R", "S"): consonanti, non un romano ("I", "V", "X") ne' una
# congiunzione ("y", "e")
_LETTERE_SERIE = frozenset('bcdfghjklmnpqrstwz')
# lotto 403: i numeri in lettere delle parti ("Gabriel's Redemption: Part Three" contro "Part II"): solo per il VALORE di un
# numero di parte, non per l'uguaglianza delle parole ("one" sarebbe il "1" di "DDP5.1", "two" il "II" di un altro titolo). Solo
# l'inglese (in italiano "tre", "due" sono parole comuni); "one" non e' un numero di parte ("One Piece")
_VALORI = dict(_ROMANI_CIFRE, **dict(zip(('one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'), ('1', '2', '3', '4', '5', '6', '7', '8', '9', '10'))))

_FINALI_TRASLITTERATE = frozenset(('ij', 'ji', 'iy', 'yi', 'jy', 'yj'))

@lru_cache(maxsize=262144)
def _uguali(a, b):
	if a == b: return True
	# "Part II" e "part.2" sono lo stesso titolo (prova del 25/09: la trilogia Mkvking); Rocky II resta diverso da III
	if _ROMANI_CIFRE.get(a, a) == _ROMANI_CIFRE.get(b, b): return True
	# numeri e numeri romani esatti: Rocky II non e' Rocky III
	if a.isdigit() or b.isdigit() or ROMANI.match(a) or ROMANI.match(b): return False
	# una lettera diversa, solo su parole alfabetiche di almeno 5 lettere ("fantozi")
	if len(a) < 5 or len(b) < 5 or abs(len(a) - len(b)) > 1: return False
	# lotto 397: la lettera diversa non in fondo, come quella in piu' (387): "Ghost Trail" non e' Ghost Train. Tranne le lettere
	# che le traslitterazioni scambiano ("Volshebnyj" = "Volshebnyy", il russo -ый)
	if len(a) == len(b): return sum(x != y for x, y in zip(a, b)) == 1 and (a[-1] == b[-1] or a[-1] + b[-1] in _FINALI_TRASLITTERATE)
	if len(a) > len(b): a, b = b, a
	# lotto 387: la lettera in piu' non in fondo. In fondo cambia la parola, non e' un refuso: "Vigilantes" non e' "Vigilante",
	# "DragonBallZ" (forma incollata) non e' "Dragon Ball"
	# lotto 391: tranne la vocale lunga delle romanizzazioni giapponesi ("Daimakyou" = "Daimakyo", "Ippou" = "Ippo")
	if b == a + 'u' and a[-1] in 'ou': return True
	return any(b[:i] + b[i + 1:] == a for i in range(len(b) - 1))

def etichette(nome):
	"""Lotto 393. Le letture di un'etichetta di un provider, che non e' un percorso: il nome intero e cio' che segue ogni barra
	SEPARATRICE, perche' i tracker mettono i titoli uno dopo l'altro ("Плохие дети / Yin mi de jiao luo / The Bad Kids [S01]",
	"[王者天下.第一季/Kingdom.S1]"). Prima i gettoni ne tenevano solo l'ultimo pezzo, come un nome di file. Non separano la
	barra fra due cifre ("Ranma 1/2") ne' quella doppia dei titoli stilizzati ("Sword Art Online: Unanswered//butterfly",
	che passava per Butterfly). In ogni lettura le barre diventano trattini."""
	s = nome or ''
	piano = lambda x: re.sub(r'[/\\]+', ' - ', x)
	tagli = [m.end() for m in re.finditer(r'(?<![/\\])[/\\](?![/\\])', s) if not (s[m.start() - 1:m.start()].isdigit() and s[m.end():m.end() + 1].isdigit())]
	return [piano(s)] + [piano(s[t:]) for t in tagli]

def pulisci_nome(nome):
	"""Il nome del file senza cartelle ne' etichette in testa ([gruppo], [ Sito.cc ], www.sito.xx -, (1984))."""
	return TESTA.sub('', (nome or '').replace('\\', '/').split('/')[-1])

# ------------------------------------------------------------------------------------------------ lotto 372: i nomi
ESTENSIONI = VIDEO + ARCHIVI + ('.srt', '.ass', '.ssa', '.sub', '.idx', '.nfo', '.txt', '.jpg', '.png')
PARENTESI = re.compile(r'\([^)]*\)|\[[^\]]*\]|\{[^}]*\}')
ANNO_GETTONE = re.compile(r'^(?:19|20)\d\d$')
VUOTE = frozenset(('the', 'and', 'of', 'a', 'an', 'il', 'la', 'le', 'lo', 'gli', 'i', 'e', 'di', 'del', 'della', 'dei', 'de', 'el',
				   'los', 'las', 'no', 'to', 'in'))
# parole che nominano il genere di opera, non QUALE: non sono distintive ("Dragon Ball Movie 02" passava per The World's
# Strongest grazie all'alias "Dragon Ball Z The Movie: The World's Strongest", prova del 26/09)
# lotto 403: anche "hen" e "arc" (篇, il capitolo: "Gurren Hen" e "Lagann Hen" sono due film)
# gli articoli (quelli di _senza_articolo): non contano fra le parole di un titolo
ARTICOLI = frozenset(('the', 'a', 'an', 'il', 'lo', 'la', 'le', 'les', 'el', 'los', 'las', 'der', 'die', 'das'))
GENERICHE = frozenset(('movie', 'movies', 'film', 'films', 'filme', 'filmes', 'pelicula', 'peliculas', 'pelicola', 'hen', 'arc'))
# i segni che dicono QUALE episodio: dopo il titolo di una serie finiscono il titolo
SEGNI_SERIE = re.compile(r'^(?:s\d{1,3}(?:e\d{1,4}[a-z]{0,2})?|\d{1,2}x\d{1,4}|e?p?\d{1,4}(?:v\d)?|season|seasons|stagione|saison|temporada|'
						 r'complete|completa|episode|episodes|episodio|episodi|ep|eps|capitulo|capítulo|odcinek|серия|aka|\d+(?:st|nd|rd|th)|part|cour|vol)$', re.I)

# lotto 375: le parole che annunciano il numero di un seguito o di una parte ("The Godfather Part II" = "The Godfather 2",
# "Kill Bill: Volume 1" = "Kill Bill Vol. 1"). Non "pt": "PT1" e' un pezzo di file (PARTI)
PAROLE_PARTE = frozenset(('part', 'parte', 'partie', 'teil', 'vol', 'volume', 'chapter', 'capitolo'))
# lotto 389: i numeri scritti in lettere, come le parole di parte, non distinguono un titolo ("Dune Part One" non ha niente di
# "Brahmastra Part One")
NUMERI_PAROLA = frozenset(('one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'uno', 'due', 'tre'))

def incollato(p):
	"""Lotto 387. Le parole di un titolo di 2-4 parole alfabetiche, incollate ("three body" -> "threebody"), se fanno almeno 6
	lettere; altrimenti None."""
	if 2 <= len(p) <= 4 and all(x.isalpha() for x in p) and len(''.join(p)) >= 6: return ''.join(p)
	return None

def _senza_apostrofi(s):
	return (s or '').replace("'", '').replace('’', '').replace('`', '')

def _senza_parte(g):
	# i gettoni senza la parola che annuncia un numero ("part 2" -> "2"); la lista stessa se non ce n'e'
	return [x for i, x in enumerate(g) if not (x in PAROLE_PARTE and i + 1 < len(g)
			and ((g[i + 1].isdigit() and len(g[i + 1]) <= 2) or ROMANI.match(g[i + 1]) or g[i + 1] in _NUMERI_LETTERE or g[i + 1] == 'one'))]

def senza_estensione(nome):
	basso = (nome or '').lower()
	for e in ESTENSIONI:
		if basso.endswith(e): return nome[:-len(e)]
	return nome or ''

def gettoni(nome, parentesi=True, tracce=True):
	"""Le parole di un nome: etichette in testa, estensione VERA e numeri di traccia tolti (con `tracce`), apostrofi uniti;
	con `parentesi` anche cio' che sta fra parentesi (per il titolo: "Seven Samurai (The Criterion Collection 2024)").
	Lotto 413: ricordata (lo stesso nome torna decine di volte in una ricerca: 90.000 chiamate su 205 ricerche); si restituisce
	una lista nuova, chi la riceve puo' cambiarla."""
	return list(_gettoni(nome, parentesi, tracce))

_PER = re.compile(r'(?<=\d)\s*×\s*(?=\d)')

@lru_cache(maxsize=65536)
def _gettoni(nome, parentesi, tracce):
	n = senza_estensione(pulisci_nome(nome))
	# lotto 387: la risoluzione col segno di moltiplicazione ("1920×1080") e' una parola sola, come "1920x1080": divisa, "1920"
	# pareva un anno (Paprika dei Kamigami fuori per "anno fuori"). Con le etichette Unicode di cocoscrapers arriva anche li'
	n = _PER.sub('x', n)
	if parentesi: n = PARENTESI.sub(' ', n)
	g = parole(_senza_apostrofi(n))
	# lotto 386: l'anno col "г" russo ("Братство кольца 2001г") e' un anno; "open matte" e' un descrittore solo
	g = [x[:4] if len(x) == 5 and x[4] == 'г' and ANNO_GETTONE.match(x[:4]) else x for x in g]
	for i in range(len(g) - 2, -1, -1):
		if g[i] == 'open' and g[i + 1] == 'matte': g[i:i + 2] = ['openmatte']
	# lotto 410: "A.K.A." puntato e' "aka" ("Parasyte.The.Grey.A.K.A.Gisaengsu.Deo.Geurei.S01" non e' un'altra serie)
	for i in range(len(g) - 3, -1, -1):
		if g[i:i + 3] == ['a', 'k', 'a']: g[i:i + 3] = ['aka']
	while tracce and g and g[0].isdigit() and len(g[0]) <= 3: g = g[1:]
	return tuple(g)

def anni_del_nome(nome):
	"""Lotto 387. Gli anni di un nome letti in TUTTO il nome, anche nelle etichette in testa che gettoni toglie: "[Oreldo] [South
	Wind Subs] [1962] Arabian Night - Sindbad no Bouken" passava per The Wind Rises (2013), ripescato per id senza anno."""
	n = senza_estensione((nome or '').replace('\\', '/').split('/')[-1])
	return _anni(parole(_PER.sub('x', n)))

def _da_etichette(nome):
	"""Lotto 386. Le parole del nome da ciascuna etichetta in testa in poi: TESTA toglie tutte le parentesi quadre iniziali,
	anche quella che porta il titolo ("[4K][DBD-Raws][千与千寻][2160P]", "[DBD-Raws][火影忍者][135]")."""
	base = senza_estensione((nome or '').replace('\\', '/').split('/')[-1])
	m = ETICHETTE_IN_TESTA.match(base)
	if not m: return []
	gruppi = re.findall(r'\[([^\]]*)\]', m.group(1))
	return [gettoni(' '.join(gruppi[i:]) + ' ' + base[m.end():], parentesi=False) for i in range(len(gruppi))]

def nome_vero(files):
	"""Il nome del torrent dall'elenco: la cartella radice dei percorsi, o il file se e' uno solo senza cartella.
	L'etichetta del provider non lo e' sempre: Comet e MediaFusion danno il nome del primo file visto, DMM a volte
	quello di un altro torrent (prova del 26/09)."""
	radici = {}
	for f in files or []:
		p = (f[0] or '').replace('\\', '/')
		if '/' in p:
			r = p.split('/')[0]
			radici[r] = radici.get(r, 0) + 1
	if radici: return max(radici.items(), key=lambda x: x[1])[0]
	return files[0][1] if files and len(files) == 1 else None


class Domanda:
	"""Cio' che si cerca. Film: titoli (titolo + alias), anno, durata in secondi. Episodio: stagione, episodio,
	assoluto (solo per la numerazione TVDB)."""

	def __init__(self, tipo, titoli=(), anno=None, durata=0, stagione=None, episodio=None, assoluto=None, ultimo_anno=None):
		self.tipo = 'movie' if tipo == 'movie' else 'episode'
		# lotto 386: i titoli in ogni scrittura (prima solo quelli latini: i film russi, cinesi, giapponesi, coreani si perdevano)
		self.titoli = [t for t in dict.fromkeys(t for t in titoli if t) if parole(t)]
		self._titoli_parole = [p for p in (parole(t) for t in self.titoli) if p]
		# lotto 372: i titoli come gettoni in due forme, con l'apostrofo che unisce ("L'Ordre" = "LOrdre") e che separa
		# ("L.Ordre"): i nomi dei torrent usano l'una e l'altra
		self._gettoni = [list(p) for p in dict.fromkeys(tuple(p) for t in self.titoli for p in (parole(_senza_apostrofi(t)), parole(t)) if p)]
		# lotto 375: anche senza "part"/"vol" davanti al numero
		self._gettoni = [list(p) for p in dict.fromkeys(tuple(p) for p in self._gettoni + [_senza_parte(p) for p in self._gettoni] if p)]
		# lotto 410: il nome si confronta letto con _leet (le cifre dentro una parola come lettere, "fant0zzi"): anche il titolo, o
		# "NieR Automata Ver1.1a" ("veri", "ia") non e' mai "NieR:Automata Ver1.1a" ("ver1", "1a"). Si aggiunge la forma letta,
		# quella scritta resta
		self._gettoni += [list(p) for p in dict.fromkeys(tuple(_leet(x) for x in p) for p in self._gettoni) if list(p) not in self._gettoni]
		# lotto 387: la forma incollata dei titoli di 2-4 parole ("ThreeBody.S01E08", "DragonBall.S01E05", "Deathnote - 05")
		self._gettoni += [[x] for x in dict.fromkeys(incollato(p) for p in self._gettoni) if x and [x] not in self._gettoni]
		# lotto 386: i titoli in caratteri latini a parte (titoli_per)
		self._gettoni_latini = [p for p in self._gettoni if not NON_LATINO.search(''.join(p))]
		self._parole_titolo = set(w for p in self._titoli_parole for w in p)
		self._parole_titolo |= set(_leet(w) for w in self._parole_titolo)   # lotto 410
		# lotto 386: un numero non e' una parola distintiva: gli alias giapponesi portano l'anno ("バットマン ビギンズ：2005"), e
		# nelle raccolte "The Phoenix Lights (2005)" passava per Batman Begins. Nel confronto del titolo il numero conta ancora
		self._parole_lunghe = set(w for w in self._parole_titolo if len(w) >= 4 and not w.isdigit())
		try: a = int(anno)
		except (TypeError, ValueError): a = 0
		self.anno = str(a) if a else ''
		self.anni = [str(a - 1), str(a), str(a + 1)] if a else []
		# lotto 372: gli anni di messa in onda della serie (prima e ultima), per le serie omonime
		try: u = int(ultimo_anno or 0)
		except (TypeError, ValueError): u = 0
		self.anni_serie = (a - 1, max(u, a) + 1) if a and u else None
		try: self.durata = int(durata or 0)
		except (TypeError, ValueError): self.durata = 0
		self.stagione, self.episodio, self.assoluto = stagione, episodio, assoluto
		if self.tipo == 'episode':
			numeri = [int(episodio)] + ([int(assoluto)] if assoluto else [])
			# il pre-filtro: il numero dell'episodio (o l'assoluto) come numero a se' nel nome. Nel test rende
			# il classificatore 3,7 volte piu' veloce sugli episodi.
			self._numero = re.compile(r'(?<!\d)0*(?:%s)(?!\d)' % '|'.join(str(n) for n in numeri))
		titoli_bassi = ' '.join(self.titoli).lower()
		self._extra = tuple(x for x in _EXTRAS() if x not in titoli_bassi)
		# lotto 413: le parole distintive dei titoli (parola_del_titolo) una volta sola, e titolo_nel_nome ricordata per nome: la
		# stessa domanda la chiede sugli stessi nomi dal classificatore, da contraddice e dal giudizio delle segnate
		self._distintive = set(x for t in self._gettoni for x in t if len(x) >= 3 and x not in VUOTE and x not in GENERICHE and not x.isdigit()
							   and x not in PAROLE_PARTE and x not in NUMERI_PAROLA)
		self._memo_titolo = {}

	def chiave(self, identita):
		"""La chiave del verdetto salvato: versione delle regole + cio' che si cerca."""
		if self.tipo == 'movie': return 'v%d|m|%s|%s' % (VERSIONE, identita, self.anno)
		return 'v%d|e|%s|%s|%s|%s' % (VERSIONE, identita, self.stagione, self.episodio, self.assoluto or '')

	def titoli_per(self, g):
		"""Lotto 386. I titoli da confrontare con le parole `g` di un nome: quelli in altre scritture solo se il nome ne contiene
		(un nome latino non puo' essere "Гарри Поттер"): cosi' il giudizio costa come prima per i nomi latini."""
		if any(NON_LATINO.search(x) for x in g): return self._gettoni
		return self._gettoni_latini

	def anni_fuori(self, nome, senza_titolo=False):
		"""Lotto 386. Il nome porta un anno fuori da quelli della domanda (un intervallo che comprende l'anno va bene). Lotto 403:
		con `senza_titolo` non contano gli anni che sono parole del nostro titolo ("Blade Runner 2049")."""
		a = anni_del_nome(nome)
		if senza_titolo: a = [x for x in a if not any(x in t for t in self._gettoni)]
		if not a or not self.anni: return False
		if len(a) >= 2 and int(min(a)) <= int(self.anno) <= int(max(a)): return False
		return any(x not in self.anni for x in a)

	def titolo_in_testa_con_anno(self, nome):
		"""Lotto 386. Un titolo intero in testa, seguito da qualunque cosa, in un nome che porta l'anno esatto: "El señor de los
		anillos El retorno del rey (Version Extendida) (2003)". La conferma larga del ripescaggio dei film."""
		g = gettoni(nome, parentesi=False)
		if not self.anno or self.anno not in _anni(g): return False
		for originali in self._varianti(nome, g):
			w = [_leet(x) for x in originali]
			for tw in self.titoli_per(originali):
				# lotto 407: la conferma larga (seguito da qualunque cosa) solo per un titolo di almeno due parole, articoli esclusi: una
				# parola sola in testa e' spesso l'inizio di un altro titolo ("Guardians.Of.The.Galaxy.Vol.2.2017" per Guardians, 2017,
				# 53 fonti tenute). Il titolo di una parola resta alla regola stretta, titolo_nel_nome
				if len([x for x in tw if x not in ARTICOLI]) < 2: continue
				if len(w) >= len(tw) and all(_uguali(a, b) for a, b in zip(w, tw)): return True
		return False

	def _varianti(self, nome, g):
		# lotto 375: anche senza "part"/"vol" davanti al numero ("The Godfather Part 2" = "The Godfather II"); lotto 386: senza
		# l'anno in testa se e' uno degli anni del film ("1972.The.Godfather": "2001 A Space Odyssey" del 1968 resta com'e'), e
		# da ciascuna etichetta in testa in poi
		varianti = [g, _senza_parte(g)]
		if len(g) > 1 and ANNO_GETTONE.match(g[0]) and g[0] in self.anni: varianti += [g[1:], _senza_parte(g[1:])]
		# lotto 387: il numero in testa puo' essere il titolo ("12 Angry Men", "300", "9 Рота"): i numeri di traccia si
		# tolgono ("01 - Title"), ma si prova anche il nome com'e'
		con_numero = gettoni(nome, parentesi=False, tracce=False)
		if con_numero != g: varianti += [con_numero, _senza_parte(con_numero)]
		# lotto 389: il codice di collana in testa ("F1 Finding Nemo (2003)", "JB3 Skyfall (2012)", "M05 Captain America ...")
		# nelle raccolte: poche lettere e un numero. Si prova anche senza ("F1" puo' essere il titolo)
		if len(g) > 1 and CODICE_COLLANA.match(g[0]): varianti += [g[1:], _senza_parte(g[1:])]
		# lotto 399: l'emittente in testa ("BBC The Hunt (2015) - S01E06", "NHK Special ...")
		if len(g) > 1 and g[0] in EMITTENTI: varianti += [g[1:], _senza_parte(g[1:])]
		# lotto 390: l'articolo in coda, la convenzione degli elenchi ("Departed, The - Отступники.2006" per The Departed)
		m = ARTICOLO_IN_CODA.match(nome or '')
		if m: varianti.append(gettoni('%s %s %s' % (m.group(2), m.group(1), m.group(3)), parentesi=False))
		return varianti + _da_etichette(nome)

	def parola_del_titolo(self, nome):
		"""Lotto 381. Il nome porta almeno una parola distintiva di un titolo (3 lettere o piu', non vuota ne' generica)."""
		return any(_uguali(_leet(a), b) for a in gettoni(nome, parentesi=False) for b in self._distintive)

	def titolo_nel_nome(self, nome, separatore=True):
		"""Il titolo cercato nel nome di un FILE (variante del lotto 365 di check_title): etichette in testa e
		numeri di traccia tolti, il titolo finisce a un segno di fine titolo, anno facoltativo ma giusto se c'e'.
		Lotto 413: ricordata per (nome, separatore), la risposta dipende solo da loro e dalla domanda."""
		chiave = (nome, separatore)
		esito = self._memo_titolo.get(chiave)
		if esito is None: esito = self._memo_titolo[chiave] = bool(self._titolo_nel_nome(nome, separatore))
		return esito

	def _titolo_nel_nome(self, nome, separatore):
		# lotto 372: si toglie solo un'estensione VERA ("Dragon.Ball.Kai" perdeva ".Kai" e passava per Dragon Ball)
		g = gettoni(nome, parentesi=False)
		for originali in self._varianti(nome, g):
			# i refusi ("fant0zzi") si leggono solo per il confronto col titolo; i segni di fine titolo ("s03e13",
			# "4x08") si guardano sulla parola com'e'
			w = [_leet(x) for x in originali]
			for tw in self.titoli_per(originali):
				if len(w) < len(tw) or not all(_uguali(a, b) for a, b in zip(w, tw)): continue
				# lotto 375: "Il Cavaliere Oscuro - The Dark Knight IMAX (2008)", l'altro titolo dell'opera si salta
				resto = _dopo_alias(self, originali[len(tw):])
				# lotto 387: "Movie", "The Movie", "Film" dopo il titolo lo chiudono se dopo di loro c'e' la fine, un altro titolo
				# dell'opera, un segno di fine titolo o un anno ("… Kizuna Movie [1080p]"); "Digimon Adventure Movie 02 Our War
				# Game" resta un altro film
				generico = 2 if resto[:2] == ['the', 'movie'] else 1 if resto[:1] in (['movie'], ['film']) else 0
				if generico:
					resto = _dopo_alias(self, resto[generico:])
					if resto and not (FINE_TITOLO.match(resto[0]) or ANNO_GETTONE.match(resto[0])): continue
				if not resto: return True
				if self.tipo == 'episode' and FINE_SERIE.match(resto[0]): return True
				if ANNO_GETTONE.match(resto[0]): return not self.anni or resto[0] in self.anni
				if FINE_TITOLO.match(resto[0]):
					anni = [x for x in resto if ANNO_GETTONE.match(x)]
					return not anni or not self.anni or anni[0] in self.anni
		return (self._chiuso_da_parentesi(nome) or self._senza_articolo(nome) or self._senza_numero_inserito(nome)
				or (separatore and self._dopo_separatore(nome)))

	def _senza_numero_inserito(self, nome):
		"""Lotto 401. Film: il numero della saga messo in mezzo al titolo ("The Avengers 4 Endgame (2019)", "Hunger Games 3
		Mockingjay"), solo con l'anno esatto, come l'articolo in piu' (395): si prova il nome senza quel numero. Lotto 406: anche
		il segno del film della serie, "Movie 3", "Film 03", "The Movie" ("Dragon Ball Z Movie 3 The Tree of Might 1990")."""
		if self.tipo != 'movie' or not self.anno: return False
		g = gettoni(nome, parentesi=False)
		if self.anno not in _anni(g): return False
		for i in range(1, len(g) - 1):
			n = 1 if g[i].isdigit() and len(g[i]) <= 2 else 2 if (g[i] in ('movie', 'film') and g[i + 1].isdigit() and len(g[i + 1]) <= 2
																	or g[i] == 'the' and g[i + 1] == 'movie') else 0
			if n and i + n < len(g) and g[i + n].isalpha():
				if self.titolo_nel_nome('.'.join(g[:i] + g[i + n:]), separatore=False): return True
		return False

	def _senza_articolo(self, nome):
		"""Lotto 395. Film: un articolo in piu' davanti al titolo ("The Avengers. Infinity War (2018)", "Laputa the Castle in the
		Sky"), solo con l'anno esatto (un altro anno, se c'e', fa con lui un intervallo che lo comprende): senza anno l'articolo puo' distinguere due film (The Batman, 2022, e
		Batman, 1989)."""
		if self.tipo != 'movie' or not self.anno: return False
		m = _ARTICOLO_IN_TESTA.match(nome or '')
		if not m: return False
		resto = nome[m.end():]
		return self.anno in anni_del_nome(resto) and self.titolo_nel_nome(resto, separatore=False)

	def _dopo_separatore(self, nome):
		"""Lotto 390. Film: dopo un trattino SEPARATORE (spaziato o fra punti, non "Spider-Man") il titolo intero in testa, con
		l'anno esatto: prima c'e' il titolo locale che TMDb non ha o l'autore ("Kraina Bogów - Spirited Away
		2001", "Tohle je nas svet - Captain.Fantastic.2016", "Jafar Panahi - The White Balloon (1995)"). L'anno esatto serve: in
		coda c'e' spesso il gruppo ("Never Look Away 2018 ... - SHADOW[TGx]" non e' Shadow); e per le serie davanti al trattino c'e'
		spesso un'altra serie ("Gankutsuou - The Count of Monte Cristo", "The Slime Diaries - That Time I Got Reincarnated…")."""
		if self.tipo != 'movie': return False
		for m in list(SEPARATORE.finditer(nome or ''))[:2]:
			dopo = nome[m.end():]
			if self.anno in anni_del_nome(dopo) and self.titolo_nel_nome(dopo, separatore=False): return True
		return False

	def _chiuso_da_parentesi(self, nome):
		"""Lotto 387. Il titolo intero (o seguito da un altro titolo dell'opera) e subito dopo una parentesi TECNICA:
		"… Nymph Circe [Bilibili WEB-DL 1080P]", "… Kizuna [Movie]". Tecnica: porta un segno di fine titolo o un anno, o
		solo parole generiche; "Dune [Part Two]" resta fuori. Gli anni dopo il titolo contano come sempre: "Dune (1984)" non e'
		Dune del 2021."""
		base = senza_estensione(pulisci_nome(nome))
		m = _APERTA.search(base)
		if not m or not base[:m.start()].strip(): return False
		testa, coda = base[:m.start()], base[m.start():]
		gruppo = parole(_GRUPPO_APERTO.match(coda).group(1))
		if not gruppo or not (any(FINE_TITOLO.match(x) for x in gruppo) or all(x in GENERICHE or x == 'the' for x in gruppo)): return False
		g = gettoni(testa, parentesi=False)
		for originali in self._varianti(testa, g):
			w = [_leet(x) for x in originali]
			for tw in self.titoli_per(originali):
				if len(w) >= len(tw) and all(_uguali(a, b) for a, b in zip(w, tw)) and not _dopo_alias(self, originali[len(tw):]):
					anni = _anni(gettoni(coda, parentesi=False))
					return not anni or not self.anni or anni[0] in self.anni
		return False


def domanda_da_info(info, durata=0):
	"""La Domanda dai dati della ricerca (`search_info` di modules/sources.py, `info` di scrapers/external.py).
	La costruiscono cosi' sia l'elenco delle sorgenti sia la riproduzione: giudicano con la stessa domanda."""
	titoli = [info.get('title')]
	for a in info.get('aliases') or []:
		titoli.append(a.get('title') if isinstance(a, dict) else a)
	# lotto 388: in una serie di una stagione sola l'assoluto E' l'episodio: "Night Head 2041 - 01", "Coffee Prince - 12",
	# "Tokyo love story ep09" dicono l'episodio senza ambiguita' (nella prova del 28/09 restavano fuori come forme deboli).
	# Solo per il giudizio: le ricerche degli scraper restano quelle di prima
	assoluto = info.get('absolute')
	try: unica = not assoluto and info.get('media_type') == 'episode' and int(info.get('season')) == 1 and int(info.get('total_seasons') or 0) == 1
	except (TypeError, ValueError): unica = False
	if unica: assoluto = info.get('episode')
	return Domanda(info.get('media_type'), titoli, info.get('year'), durata, info.get('season'), info.get('episode'), assoluto,
				   info.get('ultimo_anno'))


# ------------------------------------------------------------------------ lotto 372: il nome che contraddice
# Non si CONFERMA il titolo sul nome vero (nella prova del 26/09 avrebbe perso ~500 sorgenti giuste: nomi bilingui,
# raccolte, cirillico): si SCARTA quando il nome dice esplicitamente un'altra opera. Un titolo e' il titolo o un alias.

def _anni(g):
	# gli anni di un nome, tranne quelli di una data ("…_2026_08_31_21_10.ts": una registrazione, non l'anno del film)
	fuori = []
	for i, x in enumerate(g):
		if not ANNO_GETTONE.match(x): continue
		m, d = (g[i + 1:i + 3] + ['', ''])[:2]
		if len(m) == 2 and len(d) == 2 and m.isdigit() and d.isdigit() and 1 <= int(m) <= 12 and 1 <= int(d) <= 31: continue
		fuori.append(x)
	return fuori

_NUMERI_LETTERE = frozenset(('two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'))

def _numero_serie(t):
	# un numero di seguito o di parte: cifre che non sono un anno, o un romano (non la "i" italiana)
	return (t.isdigit() and not ANNO_GETTONE.match(t)) or (t != 'i' and bool(ROMANI.match(t))) or t in _NUMERI_LETTERE

def _valore(t):
	return int(_VALORI.get(t, t))

def _ug(a, b):
	# i numeri per valore ("04" = "4", "vi" = "6"), le parole come _uguali
	if _numero_serie(a) and _numero_serie(b): return _valore(a) == _valore(b)
	return _uguali(a, b)

def _in_comune(w, tw):
	k = 0
	while k < len(tw) and k < len(w) and _ug(w[k], tw[k]): k += 1
	return k

def _copre(g, tw):
	# quanti gettoni in testa a g fanno il titolo tw, articoli e preposizioni ignorati da entrambe le parti ("The Lord of
	# the Rings Two Towers" = "The Lord of the Rings: The Two Towers"); 0 se non lo fanno
	i = j = 0
	while j < len(tw):
		if tw[j] in VUOTE:
			j += 1
			continue
		while i < len(g) and g[i] in VUOTE: i += 1
		if i >= len(g) or not _ug(_leet(g[i]), tw[j]): return 0
		i, j = i + 1, j + 1
	return i

def _tratto(g):
	"""Lotto 388 -- le parole di un titolo: fino al primo segno di fine titolo o anno. Una parola dopo e' della release
	("... (2023) (BDRip 1080p) JAPANESE"), non del titolo, e non scusa un'estensione."""
	fuori = []
	for x in g:
		if FINE_TITOLO.match(x) or ANNO_GETTONE.match(x): break
		fuori.append(x)
	return fuori

def _dopo_alias(domanda, resto):
	"""Lotto 375 -- il resto del nome dopo un altro titolo intero della stessa opera: i nomi italiani sono spesso
	"Titolo IT - Titolo EN (anno)" ("Il Cavaliere Oscuro - The Dark Knight IMAX (2008)", "Il Trono di Spade - Game of
	Thrones - Stagione 1"). Titoli di almeno 4 lettere, al piu' due di fila."""
	for _ in range(2):
		for tw in domanda.titoli_per(resto):
			if len(''.join(x for x in tw if x not in VUOTE)) < 4: continue
			n = _copre(resto, tw)
			if n:
				resto = resto[n:]
				break
		else: break
	return resto

def _contiene(g, tw):
	# il titolo intero piu' avanti nel nome ("Movie 01 - Jujutsu Kaisen 0")
	n = len(tw)
	return any(all(_uguali(_leet(g[i + j]), tw[j]) for j in range(n)) for i in range(1, len(g) - n + 1))

def contraddice(domanda, nome, e_file=True):
	"""Il motivo per cui `nome` (un file, o il nome vero del torrent con e_file=False) e' un'ALTRA opera, o None."""
	g_tit = gettoni(nome, parentesi=(domanda.tipo == 'movie'))
	if not g_tit: return None
	g_tutti = gettoni(nome, parentesi=False)
	w = [_leet(x) for x in g_tit]
	anni_nome = _anni(g_tutti)
	anno_ok = (not domanda.anni) or any(a in domanda.anni for a in anni_nome)
	# lotto 385: la tolleranza di un anno CONFERMA, non scusa un'altra strada. Nelle saghe esce un film all'anno ("Naruto
	# Shippuden the Movie The Lost Tower 2010" per The Will of Fire, 2009): scusa solo l'anno esatto
	anno_esatto = (not domanda.anno) or domanda.anno in anni_nome
	titoli = domanda.titoli_per(g_tutti)
	unito = ''.join(g_tit)
	# dove finiscono le parole del nome incollato: un titolo incollato vale solo se finisce con una parola (lotto 375:
	# "thegodfatherpartii" e' l'inizio di "thegodfatherpartiii", e Part III passava per Part II), o dove una parola passa
	# dalle lettere alle cifre ("theSpider.Verse2023")
	confini, n = set(), 0
	for x in g_tit:
		confini.update(n + m.start() for m in _LETTERA_CIFRA.finditer(x))
		n += len(x)
		confini.add(n)
	# lotto 385: il paese che distingue due serie omonime, anche fra parentesi ("The Office US S01-S09" per The Office (UK)):
	# un'altra serie se nessun titolo della nostra lo contiene. Solo il paese: la regola 1b intera sulla radice toglieva
	# 88 sorgenti giuste ("Bleach - Box 1", "The Complete Series", "INTEGRALE")
	if domanda.tipo == 'episode':
		nostri = set(x for t in titoli for x in t)
		wt = [_leet(x) for x in g_tutti]
		for tw in titoli:
			k = _in_comune(wt, tw)
			if k == len(tw) and k < len(g_tutti) and g_tutti[k] in PAESI and g_tutti[k] not in nostri: return 'altra serie (%s)' % g_tutti[k]
	# 1 -- un titolo intero in testa (anche con le parole incollate, "theSpider.Verse"): decide lui
	resti, coppie = [], []
	for tw in titoli:
		k = _in_comune(w, tw)
		if k == len(tw):
			resti.append(_dopo_alias(domanda, g_tit[k:]))   # lotto 375: "Titolo IT - Titolo EN"
			coppie.append((tw, resti[-1]))
		elif len(''.join(tw)) >= 6 and unito.startswith(''.join(tw)) and len(''.join(tw)) in confini:
			# lotto 385: se il titolo incollato finisce dove finisce una parola ("dragonball" su "Dragon ball Z - 001"), il
			# resto si giudica come per il titolo intero; se finisce dentro una parola ("theSpider.Verse2023"), decide lui
			fine, j = 0, 0
			while j < len(g_tit) and fine < len(''.join(tw)):
				fine += len(g_tit[j])
				j += 1
			if fine == len(''.join(tw)):
				resti.append(_dopo_alias(domanda, g_tit[j:]))
				coppie.append((tw, resti[-1]))
			else: resti.append(None)
	if resti:
		# lotto 389: film, il titolo seguito da un numero di parte diverso da quello che un altro nostro titolo mette allo stesso
		# posto: "Kill Bill - Vol.2" per Kill Bill: Volume 1, che ha anche l'alias "Kill Bill"
		if domanda.tipo == 'movie':
			for tw, resto in coppie:
				rs = _senza_parte(resto or [])
				# "Ghost in the Shell 2.0" e' una versione (il 1995 rimontato), non il 2
				if not rs or not _numero_serie(rs[0]) or (len(rs) > 1 and rs[1].isdigit() and len(rs[1]) == 1): continue
				nostri = [t2[len(tw)] for t2 in (_senza_parte(x) for x in titoli) if len(t2) > len(tw) and t2[:len(tw)] == tw and _numero_serie(t2[len(tw)])]
				if nostri and all(_valore(x) != _valore(rs[0]) for x in nostri): return 'altro numero (%s invece di %s)' % (rs[0], nostri[0])
		for resto in resti:
			if not resto: return None
			r0 = resto[0]
			# serie omonime: "Titolo (2005)" fuori dagli anni di messa in onda e' un'altra serie. Solo fra parentesi, la
			# convenzione per distinguerle ("The Office (2024)"): un anno nudo e' spesso l'edizione ("Neon Genesis
			# Evangelion 2021 GKIDS BD REMUX", prova del 26/09)
			if domanda.tipo == 'episode' and ANNO_GETTONE.match(r0) and domanda.anni_serie and re.search(r'[(\[]\s*%s' % r0, nome or ''):
				if not domanda.anni_serie[0] <= int(r0) <= domanda.anni_serie[1]: return 'altra serie (%s)' % r0
				return None
			# lotto 388: film, il titolo seguito da un numero e un altro anno e' un altro film della serie ("Cars 2 (2011)" per
			# Cars, 2006: l'etichetta di DMM diceva "Cars.2.2006")
			if domanda.tipo == 'movie' and r0.isdigit() and len(r0) <= 2 and anni_nome and not anno_ok: return 'altro numero (%s)' % r0
			if FINE_TITOLO.match(r0) or ANNO_GETTONE.match(r0) or SEGNI_SERIE.match(r0) or r0.isdigit(): return None
		# 1a -- film: il titolo intero, altre parole e un altro anno ("Spirited Away Live On Stage 2022")
		if domanda.tipo == 'movie':
			if not anni_nome or anno_esatto: return None
			# lotto 385: una parola distintiva di un altro titolo dell'opera dopo il titolo non e' un'estensione ("One Piece -
			# Movie 13 (2017) Film Gold" per One Piece Film: GOLD, 2016)
			# lotto 388: solo nel tratto del titolo: "Godzilla Minus One (2023) (BDRip) JAPANESE" era scusato da "Japanese"
			# dell'alias "Gojira: The Original Japanese Masterpiece"
			for tw, resto in coppie:
				altre = set(x for t2 in titoli for x in t2 if x.isalpha() and len(x) >= 3 and x not in VUOTE and x not in GENERICHE and x not in tw)
				if any(_uguali(_leet(a), b) for a in _tratto(resto or ()) for b in altre): return None
			return 'estensione e altro anno'
		# 1b -- episodio: parole fra il titolo e il segno dell'episodio = un'altra serie ("Dragon Ball Kai - 04");
		# le parole fra parentesi non contano ("My Hero Academia (Dubs) - S06E118")
		if e_file:
			g2 = gettoni(nome, parentesi=True)
			w2 = [_leet(x) for x in g2]
			for tw in titoli:
				if _in_comune(w2, tw) < len(tw): continue
				resto = _dopo_alias(domanda, g2[len(tw):])   # lotto 375: "Les Soprano - The Sopranos - S01E05"
				for i, t in enumerate(resto):
					if SEGNI_SERIE.match(t): return ('altra serie (%s)' % ' '.join(resto[:i])) if i else None
					# lotto 385: anche una lettera sola ("Dragon ball Z - 001")
					if FINE_TITOLO.match(t) or not t.isalpha(): break
				else: continue
				if not resto or SEGNI_SERIE.match(resto[0]) or not resto[0].isalpha(): return None
		return None
	# lotto 399: episodio, il nostro titolo SENZA il suo numero finale, subito seguito dal segno dell'episodio, e' la serie
	# precedente ("Frozen Planet S01E05" per Frozen Planet II)
	if domanda.tipo == 'episode':
		for tw in titoli:
			if len(tw) < 2 or not _numero_serie(tw[-1]) or _valore(tw[-1]) < 2: continue
			k = _in_comune(w, tw[:-1])
			if k == len(tw) - 1 and k < len(g_tit) and SEGNI_SERIE.match(g_tit[k]):
				return 'titolo senza il suo numero (%s)' % tw[-1]
		return None
	# 2 -- film: un alias che corrisponde attraverso un numero ("One Piece Film 04" = "One Piece Film 4") ha detto quale
	for tw in titoli:
		k = _in_comune(w, tw)
		# lotto 391: solo se l'anno del nome non dice un altro film: "Lupin III - Dead or Alive (1996)" per Il castello di Cagliostro
		# (1979) passava perche' "III" e' nel nome del personaggio
		if k >= 2 and any(_numero_serie(x) for x in tw[:k]) and (not anni_nome or anno_ok): return None
	# 3 -- film: la stessa famiglia (almeno due parole in testa), poi un altro numero o un'altra strada
	for tw in titoli:
		k = _in_comune(w, tw)
		prefisso = tw[:k]
		if k < 2 or k >= len(w) or not any(len(x) >= 3 and x not in VUOTE for x in prefisso): continue
		nt, tt = g_tit[k], tw[k]
		if _numero_serie(nt) and _numero_serie(tt) and _valore(nt) != _valore(tt): return 'altro numero (%s invece di %s)' % (nt, tt)
		# lotto 393: anche oltre le parole generiche e di parte ("Boku no Hero Academia - Movie 01 - Two Heroes" per "... the Movie 2:
		# Heroes Rising": "movie" e "the" stavano in mezzo e "Heroes" scusava)
		# (non se il titolo intero c'e' piu' avanti: "Jujutsu Kaisen - Movie 01 - Jujutsu Kaisen 0")
		rn = [x for x in _senza_parte(g_tit[k:]) if x not in GENERICHE and x != 'the']
		rt = [x for x in _senza_parte(tw[k:]) if x not in GENERICHE and x != 'the']
		if rn and rt and not any(_contiene(g_tutti, t2) for t2 in titoli) and _numero_serie(rn[0]) and _numero_serie(rt[0]) and _valore(rn[0]) != _valore(rt[0]):
			return 'altro numero (%s invece di %s)' % (rn[0], rt[0])
		# lotto 404: anche la lettera della serie, se al suo posto il nostro titolo ne ha un'altra ("Sailor Moon R -The Movie-" per
		# "Sailor Moon S the Movie")
		if (len(nt) == 1 and len(tt) == 1 and nt != tt and nt in _LETTERE_SERIE and tt in _LETTERE_SERIE
				and not any(_contiene(g_tutti, t2) for t2 in titoli)):
			return 'altra serie (%s invece di %s)' % (nt, tt)
		if not ((nt.isalpha() and len(nt) >= 3 and not FINE_TITOLO.match(nt)) or _numero_serie(nt)): continue
		distintive = set(x for t2 in titoli for x in t2 if x.isalpha() and len(x) >= 3 and x not in VUOTE and x not in GENERICHE and x not in prefisso)
		if any(_uguali(_leet(a), b) for a in _tratto(g_tutti[k:]) for b in distintive): continue
		if any(_contiene(g_tutti, t2) for t2 in titoli): continue
		if anni_nome and anno_esatto: continue
		return 'altra strada dopo "%s" (%s)' % (' '.join(prefisso), nt)
	# 4a -- lotto 392: film, il nome porta solo l'inizio di un nostro titolo e subito un anno che non e' quello esatto
	# ("Sardar 2022" per Sardar Udham, 2021: e' un altro film)
	if anni_nome and not anno_esatto:
		for tw in titoli:
			k = _in_comune(w, tw)
			if 1 <= k < len(tw) and k < len(g_tutti) and ANNO_GETTONE.match(g_tutti[k]) and any(len(x) >= 3 and x not in VUOTE for x in tw[:k]):
				return 'titolo troncato e altro anno'
	# 4b -- lotto 404: film, il nome e' SOLO l'inizio di un nostro titolo che continua con il numero del seguito (almeno due parole
	# vere, poi niente o soli segni tecnici) e nessun anno: e' il film precedente ("Iron Man [dvdrip]" per Iron Man 2, "Toy
	# Story" per Toy Story 3). Solo i seguiti: un titolo abbreviato ("ETERNAL_SUNSHINE") o tradotto a meta' e' il nostro film
	if not anni_nome:
		for tw in titoli:
			k = _in_comune(w, tw)
			if (2 <= k < len(tw) and (_numero_serie(tw[k]) or tw[k] in PAROLE_PARTE) and sum(1 for x in tw[:k] if len(x) >= 3 and x not in VUOTE) >= 2
					and all(FINE_TITOLO.match(x) for x in g_tit[k:])):
				if not any(_contiene(g_tutti, t2) for t2 in titoli): return 'titolo troncato'
	# 4 -- film: nessun titolo, nessuna parola del titolo, un altro anno ("Manie-Manie (1989)" per Viaggio a Tokyo)
	# lotto 388: la scusa e' un titolo con TUTTE le sue parole nel nome (numeri compresi), non una parola sola: "The Tunnel to
	# Summer, the Exit of Goodbyes 2022" passava per Exit 8 (2025) grazie a "exit". Il titolo deve avere una parola
	# distintiva (3 lettere o piu', non un numero): "AK-47" da solo non scusa niente
	if anni_nome and not anno_ok:
		wt = [_leet(a) for a in g_tutti]
		def c_e(b): return any(_uguali(a, b) for a in wt)
		def scusa(t2):
			parole_t = [x for x in t2 if x not in VUOTE and x not in GENERICHE]
			# lotto 394: un titolo di una parola sola, in mezzo a un altro nome, non scusa ("Andrew Lloyd Webber Love Never Dies 2010"
			# per Amour, 2012, che ha l'alias "Love"): in testa al nome decide gia' la regola 1
			return len(parole_t) >= 2 and any(len(x) >= 3 and not x.isdigit() for x in parole_t) and all(c_e(x) for x in parole_t)
		if not any(scusa(t2) for t2 in titoli): return 'altro titolo e altro anno'
	return None

def altro_anno_dopo_titolo(domanda, nome):
	"""Lotto 378 -- il nome porta un titolo intero seguito subito da un anno fuori +-1: "The Magnificent Seven 1960" per I
	sette samurai (che ha l'alias "The Magnificent Seven"), "Spider-Man 3 2007" per No Way Home. Serve al ripescaggio delle
	sorgenti segnate dal nome, dove l'alias coincide col titolo di un'altra opera; le altre non passano di qui."""
	if not domanda.anni: return False
	g = gettoni(nome, parentesi=False)
	w = [_leet(x) for x in g]
	for tw in domanda.titoli_per(g):
		if _in_comune(w, tw) < len(tw): continue
		resto = _dopo_alias(domanda, g[len(tw):])
		# lotto 388: oltre i segni di fine titolo, come titolo_nel_nome ("Dracula 3D (2012)" per Dracula, 2025)
		# lotto 400: anche le cifre sole dei canali audio ("Cold War [BluRay Rip][AC3 5.1 Castellano][2019]")
		while resto and ((FINE_TITOLO.match(resto[0]) and not ANNO_GETTONE.match(resto[0])) or (resto[0].isdigit() and len(resto[0]) == 1)): resto = resto[1:]
		if not resto or not ANNO_GETTONE.match(resto[0]) or resto[0] in domanda.anni: continue
		# un intervallo che comprende l'anno e' una raccolta, non un'altra opera ("The Dark Knight (2005-2012)")
		if len(resto) > 1 and ANNO_GETTONE.match(resto[1]) and int(resto[0]) <= int(domanda.anno) <= int(resto[1]): continue
		return True
	return False

def confermato_forte(domanda, nome):
	"""Il nome porta un titolo intero di almeno 4 lettere, in testa, seguito dalla fine o da un segno di fine titolo."""
	g = gettoni(nome, parentesi=True)
	w = [_leet(x) for x in g]
	for tw in domanda.titoli_per(g):
		if len(''.join(tw)) < 4: continue
		k = _in_comune(w, tw)
		if k == len(tw) and (k == len(g) or FINE_TITOLO.match(g[k]) or ANNO_GETTONE.match(g[k])): return True
	return False


_extras_cache = []
def _EXTRAS():
	if not _extras_cache:
		try:
			from modules.source_utils import EXTRAS
			_extras_cache.extend(EXTRAS)
		except: _extras_cache.extend(('sample', 'extra', 'extras', 'deleted', 'unused', 'footage', 'inside', 'blooper',
									  'bloopers', 'making.of', 'feature', 'featurette', 'behind.the.scenes', 'trailer'))
	return _extras_cache

def classifica(files, domanda):
	"""Il verdetto su un torrent. `files`: lista di (percorso, nome, byte)."""
	if not files: return None, None, 'elenco assente'
	vid = [f for f in files if (f[1] or '').lower().endswith(VIDEO)]
	# 1-2 -- niente video: archivio o disco (172 nel test: collezioni esposte da TorBox come un solo .zip,
	# immagini .iso; oggi compaiono in lista e falliscono all'avvio), o niente del tutto (colonne sonore FLAC)
	if not vid:
		if any((f[1] or '').lower().endswith(ARCHIVI) for f in files): return False, None, 'archivio o immagine disco'
		return False, None, 'nessun video'
	# 3 -- film su DVD: i .vob sono pezzi da 1 GB del film. I dischi blu-ray li guarda la regola 8b (lotto 383)
	if domanda.tipo == 'movie':
		if any(f[1].lower().endswith('.vob') for f in vid): return False, None, 'disco dvd'
	# 4 -- campioni ed extra: cartella, sigle anime, poi le parole (l'indizio piu' debole)
	# lotto 377: le parole degli extra annunciate come AGGIUNTA nel nome della release ("+ Extras", "with ... and Extras")
	# parlano del pacchetto, non dei suoi file: "Fight Club (1999) AI UHD - 10th Anniversary Edition + Extras.mkv" e' il film.
	# "Memories.of.Murder.2003.Criterion.Extras" no: li' e' cio' che la release contiene. Le cartelle degli extra restano.
	radice = (nome_vero(files) or '').lower()
	parole_extra = tuple(x for x in domanda._extra if not re.search(
		r'(?:\+|&|\b(?:with|and|plus|incl|including)\b)[^a-z0-9]*(?:[a-z0-9]+[^a-z0-9]+)?' + re.escape(x), radice))
	# lotto 407: le parole degli extra come parole intere: "extra" dentro "ExtraFlix" o "ExtraMovies" (i siti che firmano i file,
	# "Filing.For.Love.S01E04...Extraflix.Pw.mkv") faceva di ogni episodio un extra
	parola_extra = re.compile(r'(?<![a-z])(?:%s)(?![a-z])' % '|'.join(re.escape(x).replace(r'\.', r'[\W_]*') for x in parole_extra)) if parole_extra else None
	def extra(f):
		if CARTELLE_EXTRA.search('/' + (f[0] or f[1] or '').replace('\\', '/')): return True
		if SIGLE_ANIME.search(f[1]): return True
		return bool(parola_extra and parola_extra.search(f[1].lower()))
	buoni = [f for f in vid if not extra(f)]
	if not buoni: return False, None, 'solo extra'
	# lotto 385: la radice che dice di essere il disco degli extra ("Star.Wars...1977.BONUS.DISC.1080p"). Solo la frase: ogni
	# radice con "Bonus" o "Extras" toglieva i film che li hanno IN PIU' ("Inception 2010 Bonus BR", "WALL-E 1080p EXTRA")
	if BONUS_DISC.search(radice): return False, None, 'solo extra'
	# 5 -- episodio: pre-filtro sul numero, poi la scelta comune (lotto 362: vince la forma assoluta), poi il
	# file piu' grande (non il primo: un campione puo' arrivare primo)
	if domanda.tipo == 'episode':
		candidati = [f for f in buoni if domanda._numero.search(f[1])]
		if candidati:
			from modules.source_utils import file_dell_episodio
			candidati = file_dell_episodio(candidati, domanda.stagione, domanda.episodio, domanda.assoluto, lambda f: f[1], lambda f: f[0])
		if not candidati: return False, None, 'episodio assente'
		# lotto 382: fra i candidati sceglie il titolo, come per i film (regola 7): "Dragon Ball - 001" e non "Dragon Ball
		# Special - 01", che corrisponde anche lui all'assoluto 1 ed e' piu' grande. Poi il piu' grande.
		col_titolo = [f for f in candidati if domanda.titolo_nel_nome(f[1])]
		scelto = max(col_titolo or candidati, key=lambda f: f[2] or 0)
		# lotto 372: il file scelto non deve dire un'altra serie; il nome del torrent solo con l'anno (serie omonime)
		motivo = contraddice(domanda, scelto[1], True) or contraddice(domanda, nome_vero(files) or '', False)
		if motivo: return False, None, 'altra opera: %s' % motivo
		return True, scelto, 'episodio'
	# 6 -- film diviso in parti: sceglierne uno riproduce meta' film
	parti = [f for f in buoni if PARTI.search(f[1])]
	if len(parti) >= 2 and len(parti) >= len(buoni) - 1: return False, None, 'film in parti'
	def film(f, motivo):
		# 9 -- due eccezioni, con prova: un episodio (tranne S00, i film catalogati come speciali) e un file
		# troppo leggero per la durata; e la parte sola (CD1 di un cofanetto)
		if CD.search(f[1]): return False, None, 'parte sola'
		ep = EPISODIO.search(f[1])
		# lotto 392: la parola dell'episodio non conta se e' nel titolo ("Star Wars: Episode IV - A New Hope")
		if ep and not SPECIALE.search(f[1]) and not (ep.group()[:1].lower() != 's' and re.match(r'[^\d ._-]+', ep.group()).group().lower() in ' '.join(domanda.titoli).lower()):
			# lotto 400: un OVA che porta tutte le parole distintive di un nostro titolo e' il film uscito come OVA ("Mobile Suit
			# Gundam The Origin (2017) - OVA 05 - Clash at Loum")
			parole_f = set(_leet(x) for x in gettoni(f[1], parentesi=False))
			if not (ep.group()[:1].lower() == 'o' and any(all(any(_uguali(a, b) for a in parole_f) for b in t if len(b) >= 3 and not b.isdigit() and b not in VUOTE and b not in GENERICHE)
													   and sum(1 for b in t if len(b) >= 3 and not b.isdigit() and b not in VUOTE and b not in GENERICHE) >= 2
													   for t in domanda._gettoni)):
				return False, None, 'episodio in un film'
		if domanda.durata and (f[2] or 0) / 1e6 / (domanda.durata / 60.0) < MIN_MB_MINUTO: return False, None, 'troppo piccolo per la durata'
		# lotto 372: il nome del file, e per un solo video anche il nome vero del torrent, non devono dire un'altra
		# opera; un file che porta il titolo per intero vale piu' della cartella ("Rebuild 1" per Evangelion 1.11)
		altra = contraddice(domanda, f[1], True)
		# lotto 385: e il simmetrico, un solo video col titolo abbreviato ("Harry Potter 3 Bluray Remux") nella cartella che porta
		# titolo intero e anno esatto ("Harry Potter and the Prisoner of Azkaban (2004)")
		if altra and len(vid) == 1 and confermato_forte(domanda, nome_vero(files) or ''): altra = None
		if not altra and len(vid) == 1 and not confermato_forte(domanda, f[1]):
			altra = contraddice(domanda, nome_vero(files) or '', False)
		if altra: return False, None, 'altra opera: %s' % altra
		return True, f, motivo
	# 8b -- lotto 383: un disco blu-ray (BDMV/STREAM/*.m2ts). Il flusso che domina il disco e' il film intero (147 dischi su
	# 209 nella cache del 26/09 hanno un flusso da almeno il 90%); il film spezzato in molti flussi montati da una playlist
	# (Toy Story 4: 184 flussi) non domina e resta fuori, come i torrent con piu' dischi e il disco di una parte ("DISC1").
	# Il nome del flusso non dice niente: il nome e le parole degli extra si leggono sulla cartella del disco.
	def _disco(f):
		p = '/' + (f[0] or '').replace('\\', '/').lower()
		return p.split('/bdmv/')[0] if f[1].lower().endswith('.m2ts') and '/bdmv/' in p else None
	flussi = [f for f in buoni if _disco(f) is not None]
	if flussi:
		# lotto 385: un video fuori dal disco conta solo se il flusso principale non lo domina: un file pubblicitario di pochi
		# MB ("RARBG.com.mp4") faceva scartare dischi da 45-90 GB come "troppo piccolo per la durata"
		grande = max(f[2] or 0 for f in flussi)
		altri = [f for f in buoni if _disco(f) is None and (f[2] or 0) * DOMINIO >= grande]
		if altri: buoni = altri          # c'e' anche un video fuori dal disco: decidono le regole di sempre
		else:
			dischi = set(_disco(f) for f in flussi)
			if len(dischi) > 1: return False, None, 'disco blu-ray su piu dischi'
			cartella = next(iter(dischi))
			if PARTI.search(cartella): return False, None, 'parte sola'
			if re.search(r'(?<![a-z])bonus(?![a-z])', cartella) or (parola_extra and parola_extra.search(cartella)): return False, None, 'solo extra'
			flussi.sort(key=lambda f: -(f[2] or 0))
			if len(flussi) > 1 and (flussi[0][2] or 0) < DOMINIO * (flussi[1][2] or 0): return False, None, 'disco blu-ray in pezzi'
			altra = contraddice(domanda, nome_vero(files) or '', False)
			if altra: return False, None, 'altra opera: %s' % altra
			return film(flussi[0], 'disco blu-ray')
	# 7 -- piu' video: il titolo nel nome del file sceglie
	col_titolo = [f for f in buoni if domanda.titolo_nel_nome(f[1])]
	# lotto 385: fra piu' file col titolo, quelli che il nome non contraddice, poi quelli con l'anno esatto, poi il piu' grande
	# (nella raccolta di Naruto "Naruto the Movie (2005) Legend of the Stone of Gelel" vinceva su "(2004) Ninja Clash")
	if len(col_titolo) > 1:
		col_titolo = [f for f in col_titolo if not contraddice(domanda, f[1], True)] or col_titolo
		col_titolo = [f for f in col_titolo if domanda.anno and domanda.anno in _anni(gettoni(f[1], parentesi=False))] or col_titolo
	if col_titolo: return film(max(col_titolo, key=lambda f: f[2] or 0), 'titolo nel nome')
	ordinati = sorted(buoni, key=lambda f: -(f[2] or 0))
	# 9 -- un solo video: e' il film (il nome non si controlla: nel test 185 file unici giusti con nomi che
	# nessuna regola riconoscerebbe, cirillico, "[ OxTorrent.cc ]", "video.mkv")
	if len(ordinati) == 1: return film(ordinati[0], 'unico video')
	# 8 -- piu' video senza titolo: il dominante, poi l'anno esatto nel proprio nome, poi niente
	if (ordinati[0][2] or 0) >= DOMINIO * (ordinati[1][2] or 0): return film(ordinati[0], 'domina')
	if domanda.anno:
		con_anno = [f for f in buoni if domanda.anno in ANNO.findall(pulisci_nome(f[1]))
					and set(parole(pulisci_nome(f[1]))) & domanda._parole_lunghe]
		if len(con_anno) == 1: return film(con_anno[0], 'anno esatto in collezione')
		# lotto 392: fra piu' file con l'anno esatto, quelli che portano parole del nostro titolo che gli altri non hanno ("OVA 05 -
		# Clash at Loum (2017)" e non "OVA 06 - Rise of the Red Comet (2017)" per Gundam The Origin V: Clash at Loum)
		if len(con_anno) > 1:
			comuni = set.intersection(*[set(parole(pulisci_nome(f[1]))) for f in con_anno])
			proprie = [f for f in con_anno if (set(parole(pulisci_nome(f[1]))) - comuni) & domanda._parole_lunghe]
			if len(proprie) == 1: return film(proprie[0], 'parole del titolo in collezione')
		# lotto 377: piu' file con l'anno esatto e lo STESSO nome fino all'anno sono versioni dello stesso film ("T2 Judgment
		# Day (1991) [35mm Scan]" e "... Re-rip"): il piu' grande. Nomi diversi sono film diversi dello stesso anno (Bojack e
		# Broly, 1993, nella raccolta di Dragon Ball Z)
		def fino_all_anno(f):
			g = gettoni(f[1], parentesi=False)
			return tuple(g[:next((i for i, x in enumerate(g) if x == domanda.anno), len(g))])
		# lotto 398: e devono essere versioni del NOSTRO film: il nome fino all'anno porta un nostro titolo intero, o almeno qualcosa, e
		# dopo l'anno non c'e' un altro titolo (due parole che non sono nostre): "Bruce Lee - 1973 - Operation Dragon" e "...
		# Opération Dragon" non sono Bruce Lee: The Man and the Legend; "2001.The Fellowship of the Ring (1)" e "(2)" sono i due
		# dischi, non due versioni. "T2 Judgment Day (1991) [35mm Scan]" e "... Re-rip" restano
		def nostre_versioni(f):
			testa = list(fino_all_anno(f))
			if any(_contiene(testa, t) for t in domanda.titoli_per(testa)): return True
			coda = gettoni(f[1], parentesi=False)[len(testa) + 1:]
			estranee = [x for x in coda if x.isalpha() and len(x) >= 4 and x not in VUOTE and x not in GENERICHE and not FINE_TITOLO.match(x)
						and not any(_uguali(_leet(x), w) for w in domanda._parole_titolo)]
			return bool(testa) and len(estranee) < 2
		if con_anno and len(set(fino_all_anno(f) for f in con_anno)) == 1 and nostre_versioni(con_anno[0]):
			return film(max(con_anno, key=lambda f: f[2] or 0), 'versioni dello stesso film')
	return False, None, 'collezione senza il film'


def classifica_tutti(elenchi, domanda):
	"""{hash: files} -> {hash: (esito, file, motivo)}. Tutti gli elenchi di una ricerca in una chiamata."""
	fuori = {}
	for h, files in (elenchi or {}).items():
		try: fuori[h] = classifica(files, domanda)
		except: fuori[h] = (None, None, 'errore')
	return fuori
