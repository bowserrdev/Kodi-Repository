# -*- coding: utf-8 -*-
import sys
from threading import Thread
from indexers.movies import Movies
from indexers.episodes import build_single_episode
from modules import kodi_utils, settings
from modules.watched_status import get_in_progress_movies, get_in_progress_episodes, get_next_episodes, get_hidden_progress_items

add_items, set_content, set_category, end_directory = kodi_utils.add_items, kodi_utils.set_content, kodi_utils.set_category, kodi_utils.end_directory
set_view_mode, external, home = kodi_utils.set_view_mode, kodi_utils.external, kodi_utils.home
nextep_method, watched_indicators = settings.nextep_method, settings.watched_indicators

# Lista interna "Continua a guardare": fonde Film in pausa + Episodi in pausa + Prossimo episodio
# in un'unica directory ordinata per last_played. Gli episodi sono deduplicati per chiave esatta
# (serie, stagione, episodio): se lo stesso episodio compare sia come "in pausa" sia come "prossimo",
# resta solo la voce in pausa (quella con il punto di ripresa).
def build_continue_watching(params):
	handle, is_external = int(sys.argv[1]), external()
	indicators = watched_indicators()
	nextep_content = nextep_method()
	try:
		movies = get_in_progress_movies('movie', 1)
	except: movies = []
	try:
		prog_eps = get_in_progress_episodes()
	except: prog_eps = []
	try:
		hidden = get_hidden_progress_items(indicators)
		next_eps = [i for i in get_next_episodes(nextep_content) if not i['media_ids']['tmdb'] in hidden]
	except: next_eps = []
	# chiavi degli episodi in pausa (S/E esatta, già nota dai dati): usate per scartare i prossimi episodi identici
	exclude_keys = set((int(i['media_ids']['tmdb']), int(i['season']), int(i['episode'])) for i in prog_eps)
	# pool unico ordinato per last_played desc; tutte le sorgenti usano lo stesso formato (stesso DB locale),
	# quindi l'ordinamento lessicografico della stringa è cronologicamente corretto
	pool = [(m.get('last_played') or '', 'movie', m) for m in movies]
	pool += [(e.get('last_played') or '', 'prog', e) for e in prog_eps]
	pool += [(n.get('last_played') or '', 'next', n) for n in next_eps]
	pool.sort(key=lambda x: x[0], reverse=True)
	# assegna un custom_order globale: l'indice nel pool ordinato diventa la chiave di sort condivisa
	movie_items, prog_items, next_items = [], [], []
	for order, (_lp, kind, payload) in enumerate(pool):
		if kind == 'movie': movie_items.append((order, payload['media_id']))
		elif kind == 'prog': prog_items.append({**payload, 'custom_order': order})
		else: next_items.append({**payload, 'custom_order': order})
	item_list = []
	item_list_extend = item_list.extend
	def _do_movies():
		try: item_list_extend(Movies({'list': movie_items, 'custom_order': 'true', 'id_type': 'tmdb_id'}).worker())
		except: pass
	def _do_progress():
		try: item_list_extend(build_single_episode('episode.continue_progress', prog_items))
		except: pass
	def _do_next():
		try: item_list_extend(build_single_episode('episode.next_continue', next_items, exclude_keys=exclude_keys, exclude_unaired=True))
		except: pass
	threads = [Thread(target=t) for t, data in ((_do_movies, movie_items), (_do_progress, prog_items), (_do_next, next_items)) if data]
	[t.start() for t in threads]
	[t.join() for t in threads]
	item_list.sort(key=lambda k: k[1])
	final_items = [i[0] for i in item_list]
	content = 'movies' if len(movie_items) > (len(prog_items) + len(next_items)) else 'episodes'
	add_items(handle, final_items)
	set_content(handle, content)
	set_category(handle, 'Continue Watching')
	end_directory(handle, cacheToDisc=False if is_external else True)
	if not is_external: set_view_mode('view.%s' % content, content, is_external)
