# -*- coding: utf-8 -*-
"""Il filtro "uscito": esiste una versione digitale del titolo, in un paese qualsiasi? (lotto 344)

La specifica e' FILTRO-USCITA.md, nella radice del repo. Qui vive la REGOLA, una volta sola; la chiama il servizio
(modules/preparatore.giudica) prima che il titolo entri in lista, e la scheda appena scaricata (metadata) le
regala il verdetto quando i dati li ha gia' in mano.

  Film   U1  TMDb watch/providers: un'offerta in un paese qualsiasi (flatrate, free, ads, rent, buy)
         U2  TMDb release_dates: un'uscita digitale (4), su disco (5) o in TV (6) il cui giorno e' PASSATO
         U3  blu-ray.com, ricerca mobile in tutti i paesi, solo se U1 e U2 dicono no
  Serie  U1, oppure il primo episodio andato in onda in un giorno passato. Niente blu-ray.com: il no di TMDb e'
         il verdetto.

UNA DATA CONTA DAL GIORNO DOPO (decisione dell'utente, 24/09). TMDb da' il giorno, non l'ora, e il giorno e' quello
del paese: il digitale americano apre a mezzanotte del Pacifico, le 9 del mattino in Italia, e i file arrivano dopo.
Contare la data dal giorno stesso mostrerebbe il titolo ore prima che esista. Il "no" di un titolo con una data gia'
annunciata scade proprio alla mezzanotte di quel giorno dopo (caches/dub_cache.scadenza_negativa): la regola e la
scadenza cambiano insieme, quindi il titolo compare il primo giorno in cui la regola lo ammette, non una settimana dopo.
Le edizioni di blu-ray.com (U3) seguono la regola di sempre (bluray_api._on_sale): un disco il giorno dell'uscita
e' gia' comprabile.

Tre esiti, come il filtro doppiaggio: True, False, None. None e' "non si e' potuto sapere": non si scrive in cache,
il titolo resta in attesa e si riprova.

LOTTO 347 -- IL DOPPIATO, la sottovoce. Si chiede solo di un titolo uscito, per ogni lingua scelta non ancora decisa,
dalla fonte piu' economica:
  D0  la lingua originale e' fra quelle scelte (Gomorra), oppure il titolo non ha parlato (lotto 349: un film muto o un
      corto senza dialoghi non ha niente da doppiare; TMDb lo dice con le lingue parlate tutte 'xx'): gratis
  D1  il titolo e' su Netflix in un paese della lingua: gratis, dalla risposta TMDb. Netflix non dichiara l'audio a
      nessuno; decisione dell'utente del 24/09: tutto il catalogo Netflix del paese conta come doppiato
  D2  JustWatch: un'offerta con quella traccia (apis/justwatch_api), una richiesta per tutte le lingue
  D3  blu-ray.com: un disco uscito con quella traccia (apis/bluray_api.tracce_audio)
Basta UNA lingua certificata. Una lingua si nega (e si scrive) solo quando D2 e D3 hanno risposto entrambi.

LA DOMANDA TMDb E' UNA SOLA (DatiTmdb): uscita e doppiato leggono la stessa risposta, chiesta al piu' una volta per
giudizio e solo se nessuna delle due trova in cache cio' che le serve.
"""

OFFERTE = ('flatrate', 'free', 'ads', 'rent', 'buy')
TIPI_USCITA = (4, 5, 6)   # digitale, disco, TV. 1-3 sono le sale.

def _giorno(valore):
	return (valore or '')[:10]

def _prima(*giorni):
	"""Il primo dei giorni non vuoti, '' se nessuno."""
	giorni = [g for g in giorni if g]
	return min(giorni) if giorni else ''

def _serie(ultimo_episodio, prima_messa_in_onda, prossimo_episodio, oggi):
	"""(andata in onda, giorno in cui lo sara'). last_episode_to_air e' nullo finche' non esce il primo episodio e
	presente dal giorno stesso (misurato il 24/09), quindi anche lui conta dal giorno dopo; la prima messa in onda e'
	il ripiego quando manca, il prossimo episodio da' la data di una serie annunciata (Coven Academy: 01/10)."""
	ultimo = _giorno((ultimo_episodio or {}).get('air_date')) if isinstance(ultimo_episodio, dict) else ''
	if ultimo_episodio and not ultimo: return True, ''   # c'e' un episodio uscito, senza data: si crede a TMDb
	prima = _giorno(prima_messa_in_onda)
	if (ultimo and ultimo < oggi) or (prima and prima < oggi): return True, ''
	prossimo = _giorno((prossimo_episodio or {}).get('air_date')) if isinstance(prossimo_episodio, dict) else ''
	return False, _prima(*(g for g in (ultimo, prima, prossimo) if g >= oggi))

def da_tmdb(media_type, data, oggi):
	"""(esito, prossima) sui dati GREZZI di una risposta TMDb. `oggi` e' 'AAAA-MM-GG'.

	esito: True / False; None se la risposta non porta i dati che servono (provider non chiesti, o malformata): un
	dato mancante non e' un "no". prossima: col "no", il primo giorno annunciato in cui il titolo uscira' ('' se
	nessuno), da cui il "no" prende la scadenza.
	"""
	providers = (data.get('watch/providers') or {}).get('results')
	if not isinstance(providers, dict): return None, ''
	if any(any(paese.get(o) for o in OFFERTE) for paese in providers.values() if isinstance(paese, dict)): return True, ''
	if media_type != 'movie':
		return _serie(data.get('last_episode_to_air'), data.get('first_air_date'), data.get('next_episode_to_air'), oggi)
	date = (data.get('release_dates') or {}).get('results')
	if not isinstance(date, list): return None, ''
	future = []
	for paese in date:
		for uscita in (paese.get('release_dates') or ()):
			giorno = _giorno(uscita.get('release_date'))
			if uscita.get('type') not in TIPI_USCITA or not giorno: continue
			if giorno < oggi: return True, ''
			future.append(giorno)
	return False, _prima(*future)

# Le lingue offerte e i paesi in cui ogni fonte le cerca. Misurato nel lotto 0 (FILTRO-USCITA.md), confermato dall'utente
# il 24/09. blu-ray.com scrive 'UK' dove gli altri scrivono 'GB'; dove il sito non ha catalogo (Austria, America
# Latina oltre il Messico) il paese non c'e'.
LINGUE = {
	'it': {'netflix': ('IT',), 'justwatch': ('IT',), 'bluray': ('IT',)},
	'en': {'netflix': ('US', 'GB'), 'justwatch': ('US', 'GB'), 'bluray': ('US', 'UK', 'CA', 'AU')},
	'es': {'netflix': ('ES', 'MX'), 'justwatch': ('ES', 'MX'), 'bluray': ('ES', 'MX')},
	'fr': {'netflix': ('FR', 'CA'), 'justwatch': ('FR', 'CA'), 'bluray': ('FR', 'CA')},
	'de': {'netflix': ('DE',), 'justwatch': ('DE', 'AT'), 'bluray': ('DE',)},
	'pt': {'netflix': ('PT', 'BR'), 'justwatch': ('PT', 'BR'), 'bluray': ('PT', 'BR')},
	'ja': {'netflix': ('JP',), 'justwatch': ('JP',), 'bluray': ('JP',)},
	'pl': {'netflix': ('PL',), 'justwatch': ('PL',), 'bluray': ('PL',)},
}
NETFLIX = (8, 1796, 175)   # Netflix, Netflix Standard with Ads, Netflix Kids (id dei provider di TMDb)
# Il nome inglese che TMDb da' alla lingua parlata 'xx'. La scheda conserva solo la prima lingua parlata, per nome
# (metadata: 'spoken_language'), e di un film muto e' questa: vale anche per le schede gia' in cache.
SENZA_PAROLE = 'No Language'
NETFLIX_OFFERTE = ('flatrate', 'ads', 'free')
PAESI_TMDB = tuple(sorted({p for l in LINGUE.values() for p in l['netflix'] + l['justwatch']}))

def riassunto_tmdb(data, oggi=None):
	"""Cio' che le regole del doppiato leggono di una risposta TMDb, in poco spazio: la lingua originale e, per i soli
	paesi delle lingue, offerte si'/no, Netflix si'/no e il link della pagina "dove guardarlo" (serve a JustWatch).

	LOTTO 348 -- e `uscite`: per paese, il primo giorno ancora da venire di un'uscita digitale, su disco o in TV (i
	soli film: le serie non hanno date per paese). Un "no" del doppiato in quella lingua scade il giorno dopo, come il
	"no" dell'uscita (decisione dell'utente del 24/09): l'edizione annunciata porta quasi sempre il doppiaggio.
	"""
	providers = (data.get('watch/providers') or {}).get('results')
	if not isinstance(providers, dict): return None
	oggi = oggi or _oggi()
	uscite = {}
	for paese in ((data.get('release_dates') or {}).get('results') or ()):
		codice = paese.get('iso_3166_1')
		if codice not in PAESI_TMDB: continue
		future = [_giorno(u.get('release_date')) for u in (paese.get('release_dates') or ())
				  if u.get('type') in TIPI_USCITA and _giorno(u.get('release_date')) >= oggi]
		if future: uscite[codice] = min(future)
	paesi = {}
	for paese in PAESI_TMDB:
		v = providers.get(paese)
		if not isinstance(v, dict): continue
		paesi[paese] = {'offerte': any(v.get(o) for o in OFFERTE),
						'netflix': any((p or {}).get('provider_id') in NETFLIX for o in NETFLIX_OFFERTE for p in (v.get(o) or ())),
						'link': v.get('link') or ''}
	parlate = [p.get('iso_639_1') for p in (data.get('spoken_languages') or ()) if isinstance(p, dict)]
	return {'lingua': data.get('original_language') or '', 'paesi': paesi, 'uscite': uscite,
			'muto': bool(parlate) and all(p == 'xx' for p in parlate)}

def _oggi():
	from modules.utils import get_datetime
	return get_datetime(string=True)

def _prossima_uscita(riassunto, lingua, oggi):
	"""Il primo giorno annunciato (ancora da venire) di un'uscita nei paesi di `lingua`, '' se nessuno."""
	uscite = riassunto.get('uscite') or {}
	return _prima(*(g for g in (uscite.get(p) for p in LINGUE[lingua]['justwatch']) if g and g >= oggi))

class DatiTmdb:
	"""La domanda TMDb unica di UN titolo (tmdb_api.dati_uscita), fatta al piu' una volta e solo se serve.

	La crea chi giudica e la passa a entrambe le regole. Quando la domanda parte davvero, il riassunto per il doppiato
	si scrive subito in cache: chi viene dopo non la rifa'.
	"""
	def __init__(self, media_type, tmdb_id, api_key):
		self.media_type, self.tmdb_id, self.api_key = media_type, tmdb_id, api_key
		self._chiesta, self._dati = False, None

	def dati(self):
		if not self._chiesta:
			self._chiesta = True
			from apis.tmdb_api import dati_uscita
			self._dati = dati_uscita(self.media_type, self.tmdb_id, self.api_key)
			if self._dati: _registra_riassunto(self.media_type, self.tmdb_id, self._dati)
		return self._dati

def _registra_riassunto(media_type, tmdb_id, data):
	riassunto = riassunto_tmdb(data)
	if riassunto is None: return None
	from caches.dub_cache import dub_cache
	dub_cache.set_riassunto_tmdb(media_type, tmdb_id, riassunto)
	return riassunto

def _registra_tmdb(media_type, tmdb_id, esito, prossima, anno):
	"""Scrive cio' che TMDb ha deciso. Il no di un FILM non e' ancora il verdetto: manca blu-ray.com."""
	from caches.dub_cache import dub_cache
	if esito: dub_cache.set_released(media_type, tmdb_id, True, anno)
	elif media_type != 'movie': dub_cache.set_released(media_type, tmdb_id, False, anno, prossima)
	else: dub_cache.set_released_tmdb(media_type, tmdb_id, prossima, anno)

def registra_da_scheda(media_type, data, anno):
	"""I verdetti che una scheda APPENA scaricata regala: l'uscita e il riassunto per il doppiato (da metadata).

	Solo su dati freschi: i provider cambiano, e il verdetto va nella cache del filtro, che ha il suo TTL, non nella
	scheda. Con il filtro spento non si scrive niente: nessuno lo leggerebbe.
	"""
	try:
		from modules.settings import release_filter_enabled
		if not release_filter_enabled(): return
		tmdb_id = data.get('id')
		if not tmdb_id: return
		from modules.utils import get_datetime
		esito, prossima = da_tmdb(media_type, data, get_datetime(string=True))
		if esito is None: return
		_registra_tmdb(media_type, tmdb_id, esito, prossima, anno)
		_registra_riassunto(media_type, tmdb_id, data)   # lotto 347: D0/D1 del doppiato, senza rete
	except Exception: pass

def verdetto(media_type, tmdb_id, meta, ctx, domanda=None):
	"""True / False / None per UN titolo. Dalla cache se c'e'; altrimenti la regola, dalla fonte piu' economica.

	`meta` e' la scheda (dalla cache o appena scaricata), `ctx` il Contesto del preparatore (api_key, data), `domanda`
	la DatiTmdb del giudizio, condivisa col doppiato (se manca se ne fa una).
	"""
	from caches.dub_cache import dub_cache
	noto = dub_cache.get_released(media_type, tmdb_id)
	if noto is not None: return noto
	oggi = ctx.data.isoformat()
	anno = meta.get('imdb_year') or meta.get('year')
	prossima = dub_cache.get_released_tmdb(media_type, tmdb_id)
	if prossima is None:
		if media_type != 'movie':
			# La scheda di una serie porta gia' la messa in onda: se c'e' stata, il verdetto non costa niente.
			# Una scheda vecchia puo' dire "non ancora" per una serie uscita dopo: allora si chiede, sotto.
			extra = meta.get('extra_info') or {}
			if _serie(extra.get('last_episode_to_air'), meta.get('premiered'), None, oggi)[0]:
				dub_cache.set_released(media_type, tmdb_id, True, anno)
				return True
		data = (domanda or DatiTmdb(media_type, tmdb_id, ctx.api_key)).dati()
		if not data: return None
		esito, prossima = da_tmdb(media_type, data, oggi)
		if esito is None: return None
		_registra_tmdb(media_type, tmdb_id, esito, prossima, anno)
		if esito or media_type != 'movie': return esito
	# Film che TMDb non da' per uscito: U3. blu-ray.com indicizza i titoli inglesi/originali, con l'anno IMDb.
	from modules.metadata import _entry_query
	from apis.bluray_api import uscito_su_disco
	titolo, anno_disco, verifica = _entry_query(meta, ctx.data)
	disco = uscito_su_disco(titolo, anno_disco, verifica)
	if disco is None: return None
	dub_cache.set_released(media_type, tmdb_id, disco, anno, prossima or '')
	return disco

# --- LOTTO 347: il doppiato ----------------------------------------------------------------------------------------

def _riassunto(media_type, tmdb_id, domanda):
	"""Il riassunto dalla domanda TMDb del giudizio (chi chiama ha gia' guardato la cache)."""
	data = domanda.dati()
	return riassunto_tmdb(data) if data else None   # dati() l'ha gia' scritto in cache

def _offerte_per_justwatch(riassunto):
	"""Il riassunto nella forma di watch/providers che apis/justwatch_api legge: un paese e' presente solo se ha
	offerte, e porta il suo link."""
	return {p: {'flatrate': [True] if v.get('offerte') else [], 'link': v.get('link') or ''} for p, v in riassunto['paesi'].items()}

def doppiato(media_type, tmdb_id, meta, lingue, ctx, domanda=None):
	"""True / False / None: il titolo e' doppiato in almeno una delle `lingue`? Va chiesto solo di un titolo uscito.

	Ogni lingua decisa si scrive per conto suo (dubl_). Si scrive un "no" solo per le lingue che D2 e D3 hanno
	entrambe negato; se una delle due non ha risposto e nessuna lingua e' certificata, None.
	"""
	from caches.dub_cache import dub_cache
	lingue = [l for l in lingue if l in LINGUE]
	if not lingue: return None
	aperte = []
	for lingua in lingue:
		noto = dub_cache.get_doppiato(lingua, media_type, tmdb_id)
		if noto: return True
		if noto is None: aperte.append(lingua)
	if not aperte: return False
	anno = meta.get('imdb_year') or meta.get('year')
	def certifica(trovate):
		for lingua in trovate: dub_cache.set_doppiato(lingua, media_type, tmdb_id, True, anno)
		return True
	# D0, senza parlato. Il riassunto TMDb, se e' in cache, e' piu' fresco della scheda e guarda TUTTE le lingue parlate:
	# la scheda ne conserva solo la prima, e puo' essere vecchia (revisione del 25/09: su 51 schede "No Language" del Mac,
	# una -- Chase Me -- per TMDb oggi e' parlata in inglese). La scheda vale quando il riassunto manca, o e' di prima
	# del lotto 349 e il campo non ce l'ha.
	riassunto = dub_cache.get_riassunto_tmdb(media_type, tmdb_id)
	if riassunto is not None and 'muto' in riassunto: muto = riassunto['muto']
	else: muto = meta.get('spoken_language') == SENZA_PAROLE
	if muto: return certifica(aperte)
	originale = meta.get('original_language')
	if originale in aperte: return certifica([originale])   # D0, dalla scheda
	if riassunto is None:
		riassunto = _riassunto(media_type, tmdb_id, domanda or DatiTmdb(media_type, tmdb_id, ctx.api_key))
		if riassunto is None: return None   # senza TMDb non si sa nemmeno dove guardare
		if riassunto.get('muto'): return certifica(aperte)   # D0, senza parlato (da TMDb appena chiesto)
	if not originale and riassunto.get('lingua') in aperte: return certifica([riassunto['lingua']])   # D0, schede vecchie
	paesi = riassunto['paesi']
	netflix = [l for l in aperte if any((paesi.get(p) or {}).get('netflix') for p in LINGUE[l]['netflix'])]
	if netflix: return certifica(netflix)   # D1
	from modules.metadata import _entry_query
	titolo, anno_titolo, verifica = _entry_query(meta, ctx.data)
	paesi_jw = []
	for lingua in aperte:
		for paese in LINGUE[lingua]['justwatch']:
			if paese not in paesi_jw: paesi_jw.append(paese)
	from apis.justwatch_api import lingue_audio
	jw = lingue_audio(media_type, tmdb_id, meta.get('imdb_id'), titolo, aperte, paesi_jw, _offerte_per_justwatch(riassunto))
	if jw: return certifica(jw)   # D2
	from apis.bluray_api import tracce_audio
	disco = tracce_audio(titolo, anno_titolo, media_type, dict((l, LINGUE[l]['bluray']) for l in aperte), verifica)
	if disco: return certifica(disco)   # D3
	if jw is None or disco is None: return None
	oggi = ctx.data.isoformat()
	for lingua in aperte: dub_cache.set_doppiato(lingua, media_type, tmdb_id, False, anno, _prossima_uscita(riassunto, lingua, oggi))
	return False
