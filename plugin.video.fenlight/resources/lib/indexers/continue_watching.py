# -*- coding: utf-8 -*-
import sys
from time import perf_counter as _perf
# indexers.movies NON si importa piu' qui (lotto 82): era il modulo Fen Light piu' caro di questa
# build -- 368 ms nel log del 25/08 -- e Movies serve solo se ci sono film in pausa, che negli ultimi
# cinque avvii sono sempre stati zero. Ora si carica dentro _do_movies, che parte solo se la lista non
# e' vuota.
from indexers.episodes import build_single_episode
from modules import kodi_utils, settings, paginator
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
	# Misura (lotto 78). Questo widget e' l'unico dei quattro dell'avvio il cui segmento 'indexer' non
	# era scomponibile: fonde tre sorgenti e due costruttori diversi, e la strada che usa
	# (build_single_episode con return_results) usciva prima di qualunque riga di log. I marcatori qui
	# separano le LETTURE dalle COSTRUZIONI, e ogni costruzione dalle altre due che le girano accanto.
	# "Sto costruendo" dichiarato a voce (lotto 106). Questo widget non e' paginato, quindi non passa
	# da get_pages e non si timbrerebbe da solo: sarebbe l'unico dei tre della Home invisibile al
	# canale dei rinvii, ed e' quello che ci mette di piu'. La skin gli passa la posizione
	# (pgctl=home.501), quindi la chiave e' la stessa forma degli altri.
	_pg_key = None
	try:
		_pg_key = paginator.widget_key(params)
		paginator.mark_build_start(_pg_key)
	except: pass
	_c0 = _perf()
	indicators = watched_indicators()
	nextep_content = nextep_method()
	try:
		movies = get_in_progress_movies('movie', 1)
	except: movies = []
	_c1 = _perf()
	try:
		prog_eps = get_in_progress_episodes()
	except: prog_eps = []
	_c2 = _perf()
	try:
		hidden = get_hidden_progress_items(indicators)
		next_eps = [i for i in get_next_episodes(nextep_content) if not i['media_ids']['tmdb'] in hidden]
	except: next_eps = []
	_c3 = _perf()
	# Marcatore diagnostico (lotto 59): 'continua a guardare' fonde TRE sorgenti indipendenti e a
	# schermo sono indistinguibili. Segnalato il caso di una serie con UN solo episodio visto che,
	# tolto il visto, continua a mostrare il successivo: senza sapere da quale sorgente esce quella
	# voce si correggerebbe a caso. Una riga per costruzione, solo id e S/E, nessuna chiamata di rete.
	try:
		_fmt = lambda seq: ','.join('%s(S%sE%s)' % (i.get('media_ids', {}).get('tmdb'), i.get('season'), i.get('episode')) for i in seq[:12])
		kodi_utils.perf_log('FenLight CW', 'film in pausa %d | episodi in pausa %d [%s] | prossimi %d [%s] | nascosti %d'
				% (len(movies), len(prog_eps), _fmt(prog_eps), len(next_eps), _fmt(next_eps), len(hidden or [])))
	except: pass
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
	# tempo di PARETE di ciascun costruttore: i tre girano insieme, quindi la somma non e' il tempo
	# speso ma il massimo lo e' -- ed e' quello che fissa la durata del widget.
	_wall = {}
	def _timed(name, fn):
		def _run():
			_s = _perf()
			try: fn()
			finally: _wall[name] = _perf() - _s
		return _run
	def _do_movies():
		try:
			from indexers.movies import Movies
			item_list_extend(Movies({'list': movie_items, 'custom_order': 'true', 'id_type': 'tmdb_id'}).worker())
		except: pass
	def _do_progress():
		try: item_list_extend(build_single_episode('episode.continue_progress', prog_items))
		except: pass
	def _do_next():
		try: item_list_extend(build_single_episode('episode.next_continue', next_items, exclude_keys=exclude_keys, exclude_unaired=True))
		except: pass
	# Lotto 101. Con UNA sola sorgente popolata non c'e' niente da parallelizzare: il costruttore gira
	# in linea. Non e' solo la nascita del thread risparmiata -- e' l'import di threading, che sul Mi
	# Stick e' 119 ms piu' i 131 di _weakrefset che si trascina (vedi la nota in caches/base_cache.py).
	# Con due o tre sorgenti i thread servono davvero e threading si importa qui, non in testa al file.
	runners = [_timed(name, t) for name, t, data in
				(('film', _do_movies, movie_items), ('pausa', _do_progress, prog_items), ('prossimi', _do_next, next_items)) if data]
	_c4 = _perf()
	if len(runners) == 1: runners[0]()
	elif runners:
		from threading import Thread
		threads = [Thread(target=r) for r in runners]
		[t.start() for t in threads]
		[t.join() for t in threads]
	_c5 = _perf()
	item_list.sort(key=lambda k: k[1])
	final_items = [i[0] for i in item_list]
	try:
		kodi_utils.perf_log('FenLight PERF CW',
			'sorgenti %.0f ms (film %.0f / pausa %.0f / prossimi+nascosti %.0f) | ordinamento %.0f ms | costruttori %.0f ms di parete [%s] | %s elementi finali'
			% ((_c3 - _c0) * 1000, (_c1 - _c0) * 1000, (_c2 - _c1) * 1000, (_c3 - _c2) * 1000, (_c4 - _c3) * 1000, (_c5 - _c4) * 1000,
				', '.join('%s %s el in %.0f ms' % (k, n, _wall.get(k, 0) * 1000)
					for k, n in (('film', len(movie_items)), ('pausa', len(prog_items)), ('prossimi', len(next_items))) if n),
				len(final_items)))
	except: pass
	content = 'movies' if len(movie_items) > (len(prog_items) + len(next_items)) else 'episodes'
	add_items(handle, final_items)
	# IDENTITA' PUBBLICATA (lotto 114). Qui c'era la sola mark_build_end: questo widget non e' paginato
	# e non chiamava set_head, quindi non pubblicava ne' BUILT_PROP ne' l'elenco degli id ne' l'azione.
	# Conseguenza misurata nel log del 30/08: una ricarica mirata lanciata da un'ALTRA finestra --
	# 'azzera avanzamento' premuto stando in un hub -- lo saltava sempre, perche' il giro sulle altre
	# finestre esce con 'if not BUILT_PROP: continue'. Alle 05:01:54 si legge
	# 'refresh_for_ids ricaricati=1 altre_finestre=1 saltati=4': la Home ha ricevuto il token nuovo per
	# 'ultime uscite' e NON per 'continua a guardare', che al rientro mostrava ancora il film con la
	# sua percentuale. Dalla Home invece funzionava (05:01:03/13/35: film in pausa 6 -> 5 -> 4 -> 3),
	# perche' li' il contenitore e' a schermo e senza chiave viene ricaricato per prudenza.
	# set_head fa esattamente il lavoro che serve -- BUILT_PROP, elenco id, azione, registro,
	# mark_build_end -- ed e' lo stesso punto in cui lo chiamano gli altri costruttori: dopo add_items.
	# L'AZIONE e' indispensabile e non basta l'elenco degli id: quando un film ENTRA in 'continua a
	# guardare' il suo id non e' ancora nell'elenco pubblicato, quindi la regola per id lo
	# scarterebbe proprio mentre va ricostruito. E' lo stesso motivo per cui la watchlist di Trakt ha
	# gia' la sua ('trakt_watchlist', vedi trakt_api._refresh_watchlist).
	if _pg_key:
		try: paginator.set_head(_pg_key, final_items, kodi_utils.CONTINUE_WATCHING_ACTION)
		except: pass
	set_content(handle, content)
	set_category(handle, 'Continue Watching')
	# ESPERIMENTO DEL LOTTO 61, REVOCATO: cacheToDisc=True qui NON cambia niente. Provato il 24/08 con
	# gli altri tre widget lasciati a False come gruppo di controllo: al rientro in Home questo widget
	# e' stato ri-invocato esattamente come loro (16:25:05 e 16:25:09). Un CDirectoryProvider che si
	# aggiorna rilegge la sorgente e scavalca la cache delle cartelle: non e' un attrezzo che abbiamo.
	end_directory(handle, cacheToDisc=False if is_external else True)
	if not is_external: set_view_mode('view.%s' % content, content, is_external)
