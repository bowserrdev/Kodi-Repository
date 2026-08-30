# -*- coding: utf-8 -*-
# Filtro "contenuto doppiato" per i widget, estratto da indexers/trakt_lists.py (lotto 110).
#
# Perche' un modulo a parte: indexers/mdblist_lists.py usava DUE di queste funzioni e per averle
# importava indexers.trakt_lists a livello di modulo -- che si tira dietro apis.trakt_api,
# indexers.movies, indexers.tvshows, indexers.seasons e indexers.episodes. Sono 2811 righe e 5
# moduli caricati per due helper che non toccano nulla di tutto cio': ogni loro dipendenza e' gia'
# un import PIGRO dentro la funzione che la usa. Con reuselanguageinvoker=false quel conto si
# ripaga a ogni singola costruzione del widget mdblist, tre volte solo all'avvio.
#
# Il blocco e' spostato TALE E QUALE: nessuna riga di logica e' cambiata, solo la casa.
# Le dipendenze restano volutamente pigre -- non aggiungere import a livello di modulo qui,
# altrimenti si ricrea il problema che questo file esiste per risolvere.

# Extra "pages" the dub fill may consume past the requested window before giving up and returning whatever
# it gathered -- the in-memory mirror of paginator._FILL_PAGE_CAP (which bounds the equivalent fetch-page
# fill). A list that is mostly filtered out must not spin through its entire length chasing the target.
_DUB_FILL_PAGE_CAP = 12

def _dub_active(is_external):
	# True only when the dub widget filter applies to this build: a widget (is_external), the toggle on, and
	# the chosen language mapped to a country. Mirrors the gate inside _dub_filter_items.
	if not is_external: return False
	from modules.settings import dub_filter_enabled, dub_filter_country
	return dub_filter_enabled() and bool(dub_filter_country())

def _dub_context():
	from modules.settings import dub_filter_country, tmdb_api_key, mpaa_region
	from modules.utils import get_datetime, get_current_timestamp
	return dub_filter_country(), tmdb_api_key(), mpaa_region(), get_datetime(), get_current_timestamp()

def _dub_keep_chunk(chunk, country, api_key, mpaa, cdate, ctime):
	# Dub-filter one chunk of list items, preserving order. Movies and shows are masked separately (each in a
	# single threaded dub_keep_mask batch); seasons/episodes carry no media to localise and pass through.
	from modules.metadata import dub_keep_mask
	drop = set()
	for media_type, item_type in (('movie', 'movie'), ('tvshow', 'show')):
		group = [(idx, it) for idx, it in enumerate(chunk) if it['type'] == item_type]
		if not group: continue
		ids = [it['media_ids'] for _, it in group]
		mask = dub_keep_mask(media_type, 'trakt_dict', ids, country, api_key, mpaa, cdate, ctime)
		for (idx, _), keep in zip(group, mask):
			if not keep: drop.add(idx)
	return [it for idx, it in enumerate(chunk) if idx not in drop]

def _dub_paginate(result, pages_to_load, is_external):
	# Interactive-widget fill for builders whose full list is already in memory (Trakt/MDbList). Returns
	# (process_list, pages_consumed, has_more). When the dub filter is OFF this is the plain window cut
	# result[:pages_to_load*limit]. When ON it mirrors load_cumulative(min_items=...): keep consuming pages
	# past the requested window -- dropping titles with no localised release -- until a full window of
	# SURVIVORS is gathered, bounded by _DUB_FILL_PAGE_CAP extra pages. So a heavily-filtered list still
	# fills the screen in one build instead of leaving the widget short (which makes the watcher cascade many
	# tiny load-ahead refreshes). process_list is already dub-filtered; ORDER PRESERVED (append-only invariant).
	#
	# pages_consumed e' il numero di pagine GREZZE lette dalla sorgente, ed e' solo diagnostica: serve al
	# log per capire quanto il filtro sta sfoltendo. NON va dato a set_state -- vedi il commento nei
	# chiamanti. Il riempimento e' PROPORZIONALE (target = pages_to_load * limit), quindi a parita' di
	# pages_to_load questa funzione rende sempre la stessa lunghezza: e' cio' che rende sicuro registrare
	# la richiesta invece del consumo.
	from modules.settings import page_limit
	limit = page_limit(True)
	target = pages_to_load * limit
	if not _dub_active(is_external):
		process = result[:target]
		return process, pages_to_load, len(result) > len(process)
	from modules.paginator import deferred_count
	country, api_key, mpaa, cdate, ctime = _dub_context()
	kept, consumed, total = [], 0, len(result)
	page_cap = pages_to_load + _DUB_FILL_PAGE_CAP
	pages_consumed = 0
	while pages_consumed < page_cap and consumed < total:
		pages_consumed += 1
		chunk = result[consumed:consumed + limit]
		consumed += len(chunk)
		kept.extend(_dub_keep_chunk(chunk, country, api_key, mpaa, cdate, ctime))
		# Gli elementi RIMANDATI (lotto 95) contano verso il bersaglio: sono nascosti adesso ma
		# ricompariranno appena il servizio li risolve. Senza, su cache fredda questo ciclo andrebbe
		# sempre al suo tetto -- vedi paginator.deferred_count.
		if pages_consumed >= pages_to_load and len(kept) + deferred_count() >= target: break
	return kept, pages_consumed, consumed < total

def _dub_filter_items(items, media_type, is_external):
	# Widget "dubbed content" filter for builders that pass per-item {'media_ids':...} dicts to worker()
	# (Trakt lists, MDbList) and so bypass the indexers' fetch_page hook. Drops items with no localised
	# release (streaming or home video) in the chosen language's country, preserving order. Widgets only
	# (is_external), matching the fetch_page hook's scope. No-op when the filter is off / language unmapped.
	# Used by the NON-interactive (legacy Next-Page) path; the interactive path fills via _dub_paginate.
	if not items or not is_external: return items
	from modules.settings import dub_filter_enabled, dub_filter_country, tmdb_api_key, mpaa_region
	if not dub_filter_enabled(): return items
	country = dub_filter_country()
	if not country: return items
	from modules.metadata import dub_keep_mask
	from modules.utils import get_datetime, get_current_timestamp
	ids = [i['media_ids'] for i in items]
	mask = dub_keep_mask(media_type, 'trakt_dict', ids, country, tmdb_api_key(), mpaa_region(), get_datetime(), get_current_timestamp())
	return [it for it, keep in zip(items, mask) if keep]
