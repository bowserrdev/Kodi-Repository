# -*- coding: utf-8 -*-
"""Quale misura chiedere a TMDb per ogni immagine, e quanto lasciarne tenere a Kodi in cache.

IL PATTO. Ogni immagine deve arrivare a schermo alla piena risoluzione della GUI: mai ingrandita.
Fra le misure che lo garantiscono si sceglie la piu' leggera. Il peso si risparmia solo li', mai
sulla qualita'. (Il 19/09 una prima versione usava meta' altezza della GUI -- il compromesso misurato
sulla Mi Stick a 720p -- e sul Mac gli sfondi finivano ingranditi. Sbagliato.)

QUANTO GRANDE MOSTRA LA SKIN OGNI IMMAGINE. Misure su base 1080 di Arctic Fuse 3, prese dalle
maschere media/diffuse (che hanno la dimensione esatta del controllo che ritagliano) e dalle costanti:
  poster      560x820    poster_w560_h820.png, infodialog_poster_w/h
  sfondo      1920x1080  a schermo intero
  landscape   1140x680   landscape_w1140_h680.png; il controllo e' aspectratio scale, quindi un'immagine
                         16:9 lo copre a 680 di altezza -> 1209 di larghezza
  clearlogo   680 largo  riquadro del salvaschermo 680x280 (screensaver-arctic-mirage.xml); nelle info
                         e' alto 135 (info_title_logo_h), nelle card ~650 largo
Lo still dell'episodio ('thumb') la skin lo mostra come landscape (Image_LandscapeOnly_Container).
Si scala per altezza GUI / 1080 e si prende la misura TMDb piu' piccola che copre quella larghezza.

L'ALTEZZA DELLA GUI. xbmcgui.getScreenHeight(), che restituisce GraphicContext::m_iScreenHeight =
RESOLUTION_INFO::iHeight: i pixel in cui Kodi disegna la GUI, quelli della riga "GUI format" del log
(Application.cpp:579). Non prende il lock grafico (ModuleXbmcgui.cpp:41-45), quindi si puo' chiamare
anche da un plugin a riproduzione in corso. NON l'infolabel System.ScreenHeight: quella e'
iScreenHeight (SystemGUIInfo.cpp:225-227), lo schermo -- su Android con limitgui 720 da' 1080, e sul
Mac Retina da' i punti (956) mentre la GUI e' disegnata a 2940x1912. Con quella il 19/09 il Mac aveva
ricevuto immagini a un quarto dei pixel.

  GUI  720:  poster w500,  sfondo w1280,    landscape w1280,    logo w500
  GUI 1080:  poster w780,  sfondo w1920,    landscape w1280,    logo w780    (la Mi Stick)
  GUI 1912:  poster w1280, sfondo original, landscape original, logo w1280   (il Mac Retina)
  GUI 2160:  poster w1280, sfondo original, landscape original, logo w1920

Sfondo e landscape hanno misure diverse di proposito: URL diversi, voci di cache diverse. La miniatura
non si porta dietro i pixel dello sfondo, e lo sfondo non e' limitato dalla miniatura.

LE MISURE SUL CDN DI TMDB. Provate il 19/09: w92 w154 w185 w300 w342 w500 w780 w1280 w1920 e original
valgono per ogni tipo (poster, backdrop, logo); w1080, w1440, w1600, h1080 rispondono 400. Il CDN
INGRANDISCE oltre l'originale -- un logo 788x238 chiesto w1280 torna 1280x387 e pesa il doppio -- e
'original' per gli sfondi e' quasi sempre 3840x2160, fino a 3,3 MB (25 campioni della stick), mentre
w1920 e' 1920x1080 sui 430-500 KB. Pesi sugli stessi file:
  poster     w300 43 KB, w500 98 KB, w780 221 KB, w1280 919 KB
  backdrop   w780 91 KB, w1280 215 KB, w1920 505 KB
  clearlogo  w500 59 KB, w780 128 KB

IL TETTO DI KODI. Kodi non conserva l'immagine scaricata ma una copia ridotta (CPicture::CacheTexture,
Picture.cpp:219-232): alta al massimo imageres, o fanartres per le immagini 16:9 se e' maggiore. I due
valori li scrive la voce Tools -> Cache & Streaming Optimization -> Risoluzione immagini
(modules/advanced_settings.py) da `kodi_limits`: imageres all'altezza del poster piu' grande, cosi' il
w780 (780x1170) resta in cache a 560x820 e non oltre; fanartres all'altezza della GUI, per gli sfondi.

DOVE SI APPLICA. All'uscita, non nel database. I metadati salvati contengono gli URL con la misura del
giorno in cui sono stati scaricati; caches/meta_cache.py passa ogni riga letta da `size_meta` dopo il
json.loads, e la misura viene riscritta secondo le regole attuali. Il database non dipende dalla GUI:
cambiandola non c'e' niente da migrare, e nessun lettore dei metadati (una cinquantina di punti in
quindici file) deve saperne niente. Sul percorso di download (metadata.py) si costruiscono gli URL
gia' con queste misure, cosi' anche la prima consegna, che non passa dalla cache, e' coerente.
"""

TOKEN_WIDTHS = (92, 154, 185, 300, 342, 500, 780, 1280, 1920)
# Le misure che la regola sceglie per GUI da 720 a 2160, piu' quelle delle regole precedenti (fisse
# fino al 19/09, poi meta' altezza). Servono alla pulizia della cache texture
# (advanced_settings._stale_textures) per riconoscere le voci che nessuno chiedera' piu'. Non ci sono
# w185/h632, usate a misura fissa da cast e persone. w300, w500, w780 e original le usano anche extra,
# finestra persone e visore immagini: una loro voce tolta si riscarica alla prossima apertura.
MANAGED_TOKENS = frozenset(('w300', 'w342', 'w500', 'w780', 'w1280', 'w1920', 'original'))
SKIN_BASE_HEIGHT = 1080
# Larghezza massima a schermo, su base 1080, per tipo (vedi sopra).
MAX_WIDTH = {'poster': 560, 'fanart': 1920, 'landscape': 680 * 16 // 9, 'logo': 680}
POSTER_MAX_HEIGHT = 820
TMDB_PREFIX = 'https://image.tmdb.org/t/p/'
# Le chiavi dei metadati che contengono un URL TMDb di immagine, e il tipo di ciascuna. 'thumb' e'
# lo still dell'episodio. Il cast ('thumbnail', h632) resta com'e'.
KEY_KIND = {'poster': 'poster', 'fanart': 'fanart', 'landscape': 'landscape', 'thumb': 'landscape', 'clearlogo': 'logo'}

_tokens = []

def _token_for_width(width):
	for size in TOKEN_WIDTHS:
		if size >= width: return 'w%d' % size
	return 'original'

def _scaled(value, height):
	return -(-value * height // SKIN_BASE_HEIGHT)

def gui_size():
	try:
		import xbmcgui
		return int(xbmcgui.getScreenWidth()), int(xbmcgui.getScreenHeight())
	except Exception:
		return 0, 0

def compute_tokens(height):
	return dict((kind, _token_for_width(_scaled(width, height))) for kind, width in MAX_WIDTH.items())

def kodi_limits(height):
	"""(imageres, fanartres) che non tagliano niente di cio' che la GUI mostra, e niente di piu'."""
	return _scaled(POSTER_MAX_HEIGHT, height), height

def tokens():
	# Una volta per processo: il plugin e' un processo per invocazione, il servizio vive quanto
	# Kodi, e la GUI cambia solo con un riavvio.
	if not _tokens: _tokens.append(compute_tokens(gui_size()[1] or SKIN_BASE_HEIGHT))
	return _tokens[0]

def poster_token(): return tokens()['poster']
def fanart_token(): return tokens()['fanart']
def landscape_token(): return tokens()['landscape']
def logo_token(): return tokens()['logo']

def _resize(meta, current):
	for key, kind in KEY_KIND.items():
		url = meta.get(key)
		if url and url.startswith(TMDB_PREFIX):
			token, _, rest = url[len(TMDB_PREFIX):].partition('/')
			if token != current[kind]: meta[key] = '%s%s/%s' % (TMDB_PREFIX, current[kind], rest)

def size_meta(meta):
	"""Riscrive, sul posto, la misura degli URL TMDb di una riga di metacache appena decodificata.

	Dove stanno le chiavi, censito il 19/09 sui 5.407 record della stick: al primo livello nei film e
	nelle serie (poster, fanart, landscape, clearlogo), e in ogni episodio della lista che e' una riga
	di season_metadata (thumb). Nessun'altra posizione. Si lavora sull'oggetto e non sul testo: una
	regex sul JSON costava il 40% del json.loads, perche' deve scorrere anche le decine di URL del cast;
	cosi' sono cinque accessi a dizionario per riga."""
	current = tokens()
	if isinstance(meta, dict): _resize(meta, current)
	elif isinstance(meta, list):
		for item in meta:
			if isinstance(item, dict): _resize(item, current)
	return meta
