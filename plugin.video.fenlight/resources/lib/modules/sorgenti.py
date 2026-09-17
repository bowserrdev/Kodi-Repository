# -*- coding: utf-8 -*-
"""LOTTO 331 -- le sorgenti delle righe paginate, in un posto solo.

Una SORGENTE risponde a una domanda sola: data una riga (i suoi parametri) e un numero di pagina,
quali id ci sono e se ce ne sono altri. Fino al 330 la risposta stava dentro le classi che
COSTRUISCONO le righe -- Movies.build_fetch_page, TVShows.build_fetch_page, e le due liste intere
dentro mdblist_lists e trakt_lists -- quindi per leggere una sorgente bisognava importare il
costruttore, con tutto cio' che si porta dietro.

Il progetto "la costruzione legge, il servizio prepara" (16/09) sposta la lettura delle sorgenti nel
servizio: dal lotto 332 le legge SOLO modules/preparatore.py. Una costruzione non importa questo modulo.

Nessun import pesante a livello di modulo: le API si caricano quando una sorgente si legge davvero.
"""
from collections import namedtuple as _namedtuple

# Le azioni che esistono, per tipo. Stavano in testa a indexers/movies.py e indexers/tvshows.py.
AZIONI = {
	'movie': {
		'main': ('tmdb_movies_popular', 'tmdb_movies_popular_today', 'tmdb_movies_blockbusters', 'tmdb_movies_in_theaters',
				'tmdb_movies_upcoming', 'tmdb_movies_latest_releases', 'tmdb_movies_premieres', 'tmdb_movies_oscar_winners'),
		'special': ('tmdb_movies_languages', 'tmdb_movies_providers', 'tmdb_movies_year', 'tmdb_movies_decade',
				'tmdb_movies_certifications', 'tmdb_movies_recommendations', 'tmdb_movies_genres', 'tmdb_movies_search',
				'tmdb_movies_search_filtered', 'tmdb_movie_keyword_results', 'tmdb_movie_keyword_results_direct'),
		'personal': {'favorites_movies': ('modules.favorites', 'get_favorites'),
				'in_progress_movies': ('modules.watched_status', 'get_in_progress_movies'),
				'watched_movies': ('modules.watched_status', 'get_watched_items'),
				'recent_watched_movies': ('modules.watched_status', 'get_recently_watched')},
		'trakt_main': ('trakt_movies_trending', 'trakt_movies_trending_recent', 'trakt_movies_most_watched',
				'trakt_movies_most_favorited', 'trakt_movies_top10_boxoffice'),
		'trakt_special': (),
		'trakt_personal': ('trakt_collection', 'trakt_watchlist', 'trakt_collection_lists', 'trakt_watchlist_lists', 'trakt_favorites'),
		'discover': 'tmdb_movies_discover',
		# Le liste che hanno un'azione ma non un passo: si costruiscono in un colpo solo.
		'intere': ('recent_watched_movies', 'trakt_movies_top10_boxoffice', 'trakt_collection_lists', 'trakt_watchlist_lists', 'trakt_favorites'),
		'trakt_chiave': 'movie',
		'trakt_collezione': 'movies',
	},
	'tvshow': {
		'main': ('tmdb_tv_popular', 'tmdb_tv_popular_today', 'tmdb_tv_premieres', 'tmdb_tv_airing_today', 'tmdb_tv_on_the_air',
				'tmdb_tv_upcoming', 'tmdb_anime_popular', 'tmdb_anime_popular_recent', 'tmdb_anime_premieres', 'tmdb_anime_upcoming',
				'tmdb_anime_on_the_air'),
		'special': ('tmdb_tv_languages', 'tmdb_tv_networks', 'tmdb_tv_providers', 'tmdb_tv_year', 'tmdb_tv_decade',
				'tmdb_tv_recommendations', 'tmdb_tv_genres', 'tmdb_tv_search', 'tmdb_tv_search_filtered', 'tmdb_tv_keyword_results',
				'tmdb_tv_keyword_results_direct', 'tmdb_anime_year', 'tmdb_anime_decade', 'tmdb_anime_genres', 'tmdb_anime_providers',
				'tmdb_anime_search'),
		'personal': {'in_progress_tvshows': ('modules.watched_status', 'get_in_progress_tvshows'),
				'favorites_tvshows': ('modules.favorites', 'get_favorites'),
				'favorites_anime_tvshows': ('modules.favorites', 'get_favorites'),
				'watched_tvshows': ('modules.watched_status', 'get_watched_items')},
		'trakt_main': ('trakt_tv_trending', 'trakt_tv_trending_recent', 'trakt_tv_most_watched', 'trakt_tv_most_favorited',
				'trakt_anime_trending', 'trakt_anime_trending_recent', 'trakt_anime_most_watched', 'trakt_anime_most_favorited'),
		'trakt_special': ('trakt_tv_certifications', 'trakt_anime_certifications'),
		'trakt_personal': ('trakt_collection', 'trakt_watchlist', 'trakt_collection_lists', 'trakt_watchlist_lists', 'trakt_favorites'),
		'discover': 'tmdb_tv_discover',
		'intere': ('trakt_collection_lists', 'trakt_watchlist_lists', 'trakt_favorites'),
		'trakt_chiave': 'show',
		'trakt_collezione': 'shows',
	},
}

# `leggi(pagina) -> (id, ultima)`: gli id di quella pagina e il numero dell'ultima pagina, se la sorgente lo
#     dichiara (TMDb, liste in memoria), None se non lo sa (Trakt: la lista finisce alla prima pagina vuota).
#     Sapere l'ultima pagina e' cio' che permette al preparatore di leggerne piu' d'una insieme (lotto 334).
# `id_type` e' la forma degli id che torna (tmdb_id o trakt_dict);
# `filtrabile` dice se il filtro doppiaggio si applica a questa riga (mai alle liste personali);
# `intera` dice che la sorgente e' una lista gia' tutta in memoria, letta a fette; `tutti` e' quella lista
#     per le liste miste (Trakt, MDbList), None altrimenti;
# `ammetti(meta)` e' una regola in piu' su un titolo, decisa sulla sua scheda; `ordine(meta)` la chiave con
#     cui si ordinano i titoli DENTRO una pagina. None = nessuna regola, ordine della sorgente. Li usa solo
#     Discover (lotto 334): fino al 333 la sua sorgente scaricava da se' le schede di ogni pagina, un thread
#     per titolo, fuori dal limite di rete del preparatore.
Sorgente = _namedtuple('Sorgente', 'leggi id_type filtrabile intera tutti ammetti ordine')

# TMDb non serve pagine oltre la 500, qualunque cosa dica total_pages.
TMDB_ULTIMA_PAGINA = 500

def continua(pagina, ids, ultima):
	"""Dopo questa pagina ce ne sono altre? Una sola definizione di fine, per ogni sorgente."""
	return bool(ids) if ultima is None else pagina < ultima

def _ultima_tmdb(data):
	return min(int(data['total_pages']), TMDB_ULTIMA_PAGINA)

def filtrabile(tipo, action):
	"""Il filtro doppiaggio si applica a questa azione? Mai alle liste dell'utente."""
	a = AZIONI[tipo]
	return action not in a['personal'] and action not in a['trakt_personal']

def funzione_api(tipo, action):
	"""La funzione che interroga la sorgente di questa azione, o None se non ce n'e' una omonima.

	Non tutte le azioni hanno una funzione: 'tmdb_movies_sets' si risolve con movieset_meta, e l'import
	che fallisce qui e' il comportamento giusto (lotto 85: il chiamante deve ricevere None, non un nome
	non assegnato).
	"""
	if not action: return None
	personal = AZIONI[tipo]['personal']
	if action in personal: modulo, nome = personal[action]
	else: modulo, nome = 'apis.%s_api' % action.split('_')[0], action
	try:
		from modules.utils import manual_function_import
		return manual_function_import(modulo, nome)
	except Exception: return None

def paginabile(tipo, params):
	"""Questa riga di film o serie ha una sorgente paginata? Senza importare nessuna API (lotto 333).

	E' la domanda che si fa la COSTRUZIONE, che le sorgenti non le legge: deve solo sapere se la sua riga
	la prepara il servizio. Risponde come sorgente(), guardando i soli nomi delle azioni.
	"""
	params = params or {}
	action = params.get('action')
	a = AZIONI.get(tipo)
	if not a or not action or action in a['intere']: return False
	if action in a['main'] or action in a['personal'] or action in a['trakt_main'] or action in a['trakt_personal']: return True
	if action in a['special']: return bool(params.get('key_id') or params.get('query'))
	if action in a['trakt_special']: return bool(params.get('key_id'))
	return action in (a['discover'], 'trakt_recommendations')

def a_fette(tutti):
	"""Una lista gia' in memoria letta a fette di un passo: la stessa forma delle pagine di TMDb."""
	from modules.paginator import passo
	limite = passo()
	ultima = -(-len(tutti) // limite)
	def leggi(pagina):
		inizio = (pagina - 1) * limite
		return tutti[inizio:inizio + limite], ultima
	return leggi

def sorgente(tipo, params):
	"""La sorgente paginata di una riga. None se la riga non ne ha.

	tipo: 'movie' | 'tvshow' (il corpo e' quello dei due build_fetch_page, riunito) oppure 'mdblist' |
	'trakt' (liste intere, miste: gli elementi sono voci con 'type' e 'media_ids').
	"""
	params = params or {}
	if tipo in ('mdblist', 'trakt'):
		tutti = (lista_mdblist if tipo == 'mdblist' else lista_trakt)(params) or []
		return Sorgente(a_fette(tutti), 'trakt_dict', True, True, tutti, None, None)
	action = params.get('action')
	a = AZIONI.get(tipo)
	if not a or not action or action in a['intere']: return None
	function = funzione_api(tipo, action)
	if not function: return None
	id_type = params.get('id_type', 'tmdb_id')
	adatta = filtrabile(tipo, action)
	if action in a['main']:
		def leggi(pagina):
			data = function(pagina)
			return [i['id'] for i in data['results']], _ultima_tmdb(data)
		return Sorgente(leggi, id_type, adatta, False, None, None, None)
	if action in a['special']:
		key_id = params.get('key_id') or params.get('query')
		if not key_id: return None
		def leggi(pagina):
			data = function(key_id, pagina)
			return [i['id'] for i in data['results']], _ultima_tmdb(data)
		return Sorgente(leggi, id_type, adatta, False, None, None, None)
	if action == a['discover']:
		# Ricerca avanzata: TMDb ordina e filtra sul SUO voto, poco affidabile. Ogni titolo si riqualifica con la
		# sua scheda (che porta i dati IMDb) e, se si ordina per voto o non si ordina, la pagina si riordina per
		# voto IMDb. La scheda la scarica il preparatore, come per ogni altro titolo.
		from modules.metadata import discover_imdb_sort_from_url, discover_min_rating_from_url, discover_ammesso, discover_voto
		url = params.get('url')
		verso, minimo = discover_imdb_sort_from_url(url), discover_min_rating_from_url(url)
		def leggi(pagina):
			data = function(url, pagina)
			return [i['id'] for i in data['results']], _ultima_tmdb(data)
		ammetti = lambda meta: discover_ammesso(tipo, meta, minimo)
		ordine = None
		if verso in ('asc', 'desc'):
			segno = -1 if verso == 'desc' else 1
			ordine = lambda meta: segno * discover_voto(meta)
		return Sorgente(leggi, id_type, adatta, False, None, ammetti, ordine)
	if action in a['personal']:
		chi = 'movie' if tipo == 'movie' else ('anime' if '_anime_' in action else 'tvshow')
		return Sorgente(a_fette([i['media_id'] for i in function(chi, 1)]), id_type, adatta, True, None, None, None)
	chiave = a['trakt_chiave']
	if action in a['trakt_main']:
		def leggi(pagina):
			data = function(pagina)
			try: ids = [i[chiave]['ids'] for i in data]
			except: ids = [i['ids'] for i in data]
			return ids, None
		return Sorgente(leggi, 'trakt_dict', adatta, False, None, None, None)
	if action in a['trakt_special']:
		key_id = params.get('key_id', None)
		if not key_id: return None
		def leggi(pagina):
			data = function(key_id, pagina)
			return [i[chiave]['ids'] for i in data], None
		return Sorgente(leggi, 'trakt_dict', adatta, False, None, None, None)
	if action in a['trakt_personal']:
		return Sorgente(a_fette([i['media_ids'] for i in function(a['trakt_collezione'], 1)]), 'trakt_dict', adatta, True, None, None, None)
	if action == 'trakt_recommendations':
		return Sorgente(a_fette([i['ids'] for i in function(a['trakt_collezione'])]), 'trakt_dict', adatta, True, None, None, None)
	return None

# --- le liste che arrivano INTERE ---------------------------------------------------------------------------

def lista_mdblist(params):
	"""Il contenuto di una lista MDbList: una chiamata sola, la lista intera."""
	from apis.mdblist_api import mdblist_get_list_contents
	return mdblist_get_list_contents(params.get('list_id'))

def lista_trakt(params):
	"""Il contenuto di una lista Trakt: una chiamata sola, la lista intera."""
	from apis.trakt_api import get_trakt_list_contents
	list_type = params.get('list_type')
	return get_trakt_list_contents(list_type, params.get('user'), params.get('slug'), list_type == 'my_lists')
