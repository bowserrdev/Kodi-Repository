# -*- coding: utf-8 -*-
import re
import json
# 'import requests' rimosso (lotto 51): non c'era una sola occorrenza di requests.* in questo file --
# le richieste passano da make_session() di kodi_utils. Era un import morto, e 'requests' non e' un
# import qualunque: si porta dietro urllib3, certifi, ssl, http.client, email. Pagato da chiunque
# toccasse imdb_api, quindi da chiunque toccasse metadata, quindi anche dalla lista stagioni.
from caches.base_cache import connect_database
from caches.main_cache import cache_object
from caches.settings_cache import get_setting
from modules.dom_parser import parseDOM
from modules.utils import remove_accents, replace_html_codes, normalize
from modules.kodi_utils import make_session, logger

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.64 Safari/537.36 Edge/101.0.1210.53',
			'Accept-Language':'en-us,en;q=0.5'}
base_url = 'https://www.imdb.com/%s'
graphql_url = 'https://api.graphql.imdb.com/'
# IMDb ha iniziato a rispondere 403 alle chiamate GraphQL prive di Referer: l'endpoint ora accetta solo
# richieste che si presentano come provenienti dal sito. Misurato sul campo: il Referer da solo basta,
# l'Origin da solo no, e lo User-Agent e' indifferente (anche uno del 2022 passa). Origin lo mandiamo
# comunque perche' e' cio' che accompagna il Referer in un browser reale.
graphql_headers = {'Content-Type': 'application/json', 'User-Agent': headers['User-Agent'],
			'Origin': 'https://www.imdb.com', 'Referer': 'https://www.imdb.com/'}
more_like_this_url = 'title/%s'
reviews_url = 'title/%s/reviews/?sort=num_votes,desc'
trivia_url = 'title/%s/trivia'
blunders_url = 'title/%s/goofs'
parentsguide_url = 'title/%s/parentalguide'
images_url = 'title/%s/mediaindex?page=%s'
people_images_url = 'name/%s/mediaindex?page=%s'
people_trivia_url = 'name/%s/trivia'
people_search_url_backup = 'search/name/?name=%s'
people_search_url = 'https://sg.media-imdb.com/suggests/%s/%s.json'
timeout = 10.0
# Session pigra (lotto 51 bis): era `session = make_session('https://')` a livello di modulo, e make_session()
# fa `import requests` al suo interno -- quindi ogni modulo che importava questo file
# caricava l'albero di requests SENZA nessuna istruzione `import requests` visibile.
# E' il motivo per cui la prima correzione non aveva prodotto alcun guadagno misurabile.
_session = [None]

def _get_session():
	if _session[0] is None: _session[0] = make_session('https://')
	return _session[0]

def imdb_data(imdb_id, lang):
	# IMDb is always-on (its ratings/votes are more reliable than TMDb's, see metadata merge). No setting gate.
	if not imdb_id or imdb_id == 'tt0000000': return {}
	ietf_lang = '%s-%s' % (lang, lang.upper())
	# v2: query now also returns title_type (used to filter out music videos in advanced search).
	# v3 (lotto 359): la trama porta la sua lingua, `plot_lang`. IMDb risponde in inglese quando non ha la
	# traduzione, e fino al 358 niente lo distingueva: la trama inglese passava davanti a quella italiana di TMDb.
	string = 'imdb_data_v3_%s_%s' % (lang, imdb_id)
	params = {'imdb_id': imdb_id, 'lang': ietf_lang}
	return cache_object(get_imdb_graphql, string, params, False, 720, cache_empty=False)

def get_imdb_graphql(params):
	data = {}
	try:
		query = {
			'query': 'query GetData($id: ID!) { title(id: $id) { titleType { id } plot { plotText { plainText } language { id } } ratingsSummary { aggregateRating voteCount } releaseYear { year } '
					 'directors: credits(first: 5, filter: { categories: ["director"] }) { edges { node { name { nameText { text } } } } } '
					 'writers: credits(first: 5, filter: { categories: ["writer"] }) { edges { node { name { nameText { text } } } } } } }',
			'variables': {'id': params['imdb_id']}
		}
		request_headers = dict(graphql_headers, **{'X-Imdb-User-Language': params['lang']})
		r = _get_session().post(graphql_url, json=query, headers=request_headers, timeout=timeout)
		if r.status_code != 200:
			logger('FenLight IMDb', 'GraphQL data %s -> HTTP %s' % (params['imdb_id'], r.status_code))
			return data
		title = r.json()['data']['title']
		try:
			plot = title['plot']['plotText']['plainText']
			if plot:
				data['plot'] = plot
				try: data['plot_lang'] = title['plot']['language']['id'] or ''
				except: data['plot_lang'] = ''
		except: pass
		try:
			ratings = title['ratingsSummary']
			if ratings.get('aggregateRating'): data['rating'] = ratings['aggregateRating']
			if ratings.get('voteCount'): data['votes'] = ratings['voteCount']
		except: pass
		try:
			year = title['releaseYear']['year']
			if year: data['year'] = year
		except: pass
		try:
			title_type = title['titleType']['id']
			if title_type: data['title_type'] = title_type
		except: pass
		try:
			directors = [e['node']['name']['nameText']['text'] for e in title['directors']['edges']]
			directors = list(dict.fromkeys([n for n in directors if n]))
			if directors: data['directors'] = directors
		except: pass
		try:
			writers = [e['node']['name']['nameText']['text'] for e in title['writers']['edges']]
			writers = list(dict.fromkeys([n for n in writers if n]))
			if writers: data['writers'] = writers
		except: pass
	except: pass
	return data

# EPISODI: VOTO E REGISTA AGGANCIATI PER ID (lotto 358, ANIME.md). Fino al 357 c'era una funzione sola,
# imdb_episode_ratings(imdb_id, stagione), che chiedeva a IMDb la stagione e restituiva i voti per
# (stagione, episodio) NELLA NUMERAZIONE IMDb. Chi la usava la interrogava con i numeri di TMDb, e per gli
# anime con quelli di TVDB: tre numerazioni diverse, e su 22 anime il voto era quello di un altro episodio.
# Adesso le domande sono due, e chi chiama sceglie quale:
#   - imdb_episodi_stagione: la stagione come la numera IMDb, con id e date, per il rivelatore;
#   - imdb_episodi_per_id: gli episodi di cui si conosce gia' l'id (da Trakt), in qualunque stagione IMDb
#     li metta.
# Nessuna delle due ha una cache propria: la cache della stagione (metacache) e' la loro cache. Prima i
# voti stavano 30 giorni in una cache a parte, dentro stagioni che per le serie in corso scadono in 4.
# Tutte e due distinguono None (IMDb non ha risposto) da {} (ha risposto e non ne ha).
_CAMPI_EPISODIO = ('id series { episodeNumber { episodeNumber seasonNumber } } releaseDate { year month day } '
					'ratingsSummary { aggregateRating voteCount } plot { plotText { plainText } language { id } } '
					'directors: credits(first: 3, filter: { categories: ["director"] }) { edges { node { name { nameText { text } } } } }')
# IMDb rifiuta la richiesta INTERA se un solo id e' malformato ("is not a valid ID"), e piu' di 250 id
# ("Too many ids. Maximum: 250"). Un id ben formato che non esiste torna invece con i campi vuoti.
_ID_EPISODIO = re.compile(r'tt\d{7,}$')
_MAX_ID = 250

def _voce_episodio(node):
	"""Un episodio IMDb come dizionario: id, coppia nella numerazione IMDb, data, voto, voti, registi."""
	voce = {'id': node.get('id'), 'coppia': None, 'data': None}
	try:
		numero = node['series']['episodeNumber']
		voce['coppia'] = (int(numero['seasonNumber']), int(numero['episodeNumber']))
	except: pass
	try:
		uscita = node['releaseDate']
		voce['data'] = '%04d-%02d-%02d' % (uscita['year'], uscita['month'], uscita['day'])
	except: pass
	try:
		trama = node['plot']
		voce['plot'] = trama['plotText']['plainText'] or ''
		voce['plot_lang'] = (trama.get('language') or {}).get('id') or ''
	except: voce['plot'], voce['plot_lang'] = '', ''
	voti = node.get('ratingsSummary') or {}
	voce['rating'], voce['votes'] = voti.get('aggregateRating'), voti.get('voteCount') or 0
	try: registi = [e['node']['name']['nameText']['text'] for e in node['directors']['edges']]
	except: registi = []
	voce['directors'] = list(dict.fromkeys(n for n in registi if n))
	return voce

def _graphql_dati(query, variables, cosa, lang=None):
	"""Il campo 'data' della risposta GraphQL, o None se IMDb non ha risposto come doveva.

	`lang` ('it') chiede le trame in quella lingua dove IMDb le ha (lotto 359): la lingua di quella che arriva
	sta comunque in `plot.language`.
	"""
	intestazioni = dict(graphql_headers, **{'X-Imdb-User-Language': '%s-%s' % (lang, lang.upper())}) if lang else graphql_headers
	try:
		r = _get_session().post(graphql_url, json={'query': query, 'variables': variables}, headers=intestazioni, timeout=timeout)
		if r.status_code != 200:
			logger('FenLight IMDb', 'GraphQL %s -> HTTP %s' % (cosa, r.status_code))
			return None
		return r.json().get('data')
	except Exception as e:
		logger('FenLight IMDb', 'GraphQL %s -> %s' % (cosa, type(e).__name__))
		return None

def imdb_episodi_stagione(imdb_id, season, lang=None):
	"""Gli episodi della stagione `season` COME LI NUMERA IMDb: {(stagione, episodio): voce}.

	{} se IMDb risponde ma non ha niente (o la serie non ha un id IMDb), None se non ha risposto.
	"""
	if not imdb_id or imdb_id == 'tt0000000': return {}
	query = ('query GetEps($id: ID!, $season: [String!]) { title(id: $id) { episodes { episodes(first: 250, '
			 'filter: { includeSeasons: $season }) { edges { node { %s } } } } } }' % _CAMPI_EPISODIO)
	dati = _graphql_dati(query, {'id': imdb_id, 'season': [str(season)]}, 'episodi %s S%s' % (imdb_id, season), lang)
	if dati is None: return None
	try: edges = dati['title']['episodes']['episodes']['edges'] or ()
	except: return {}
	fuori = {}
	for e in edges:
		try: voce = _voce_episodio(e['node'])
		except: continue
		if voce['coppia'] is not None: fuori[voce['coppia']] = voce
	return fuori

def imdb_episodi_per_id(ids, lang=None):
	"""Gli episodi IMDb con questi id, dovunque IMDb li metta: {id: voce}.

	A blocchi di 250 richieste l'una. None se anche un solo blocco non e' arrivato: un risultato a meta'
	non si distinguerebbe da "IMDb non conosce questi episodi".
	"""
	validi = list(dict.fromkeys(i for i in ids if i and _ID_EPISODIO.match(str(i))))
	fuori = {}
	for inizio in range(0, len(validi), _MAX_ID):
		blocco = validi[inizio:inizio + _MAX_ID]
		dati = _graphql_dati('query GetEpsById($ids: [ID!]!) { titles(ids: $ids) { %s } }' % _CAMPI_EPISODIO,
							{'ids': blocco}, 'episodi per id (%d)' % len(blocco), lang)
		if dati is None: return None
		for node in dati.get('titles') or ():
			try:
				if node and node.get('id'): fuori[node['id']] = _voce_episodio(node)
			except: pass
	return fuori

def imdb_lingue_trama(ids, lang):
	"""{id: lingua della trama IMDb ('' se non ne ha)} per molti titoli, a blocchi di 250. None se un blocco manca.

	Serve solo alla migrazione del lotto 359 (metadata.migra_trame): chiede la lingua, non il testo, quindi
	le risposte restano piccole.
	"""
	validi = list(dict.fromkeys(i for i in ids if i and _ID_EPISODIO.match(str(i))))
	fuori = {}
	for inizio in range(0, len(validi), _MAX_ID):
		blocco = validi[inizio:inizio + _MAX_ID]
		dati = _graphql_dati('query GetPlotLang($ids: [ID!]!) { titles(ids: $ids) { id plot { language { id } } } }',
							{'ids': blocco}, 'lingue delle trame (%d)' % len(blocco), lang)
		if dati is None: return None
		for node in dati.get('titles') or ():
			try:
				if node and node.get('id'): fuori[node['id']] = ((node.get('plot') or {}).get('language') or {}).get('id') or ''
			except: pass
	return fuori

def aggancio_sospetto(episodi_imdb, date_tmdb):
	"""Il rivelatore del lotto 358: IMDb numera questa stagione diversamente da TMDb?

	`episodi_imdb` e `date_tmdb` sono {(stagione, episodio): data 'AAAA-MM-GG' o None}, la stessa stagione
	vista dalle due parti. Allarme se le coppie non sono le stesse, oppure se ANCHE UN SOLO episodio ha le due
	date distanti piu' di 2 giorni. Misurato su 224 stagioni di 50 serie normali (ANIME.md): prende 24
	stagioni sbagliate su 32, e le 8 perse sono 7 errori di Trakt (dove la posizione e' giusta) e un caso con
	due episodi usciti lo stesso giorno. Con la soglia al 5% degli episodi ne perdeva una in piu'.

	Decide soltanto SE chiedere gli id a Trakt: quando sbaglia costa una chiamata in piu', o lascia
	l'aggancio per posizione di prima. Pura: le costanti stanno dentro, per tests/harness.load_pure.
	"""
	from datetime import date
	SOGLIA_GIORNI = 2
	if set(episodi_imdb) != set(date_tmdb): return True
	for coppia, data_tmdb in date_tmdb.items():
		try: scarto = abs((date.fromisoformat(str(episodi_imdb[coppia])[:10]) - date.fromisoformat(str(data_tmdb)[:10])).days)
		except: continue
		if scarto > SOGLIA_GIORNI: return True
	return False


def imdb_more_like_this(imdb_id):
	url = base_url % more_like_this_url % imdb_id
	string = 'imdb_more_like_this_%s' % imdb_id
	params = {'url': url, 'action': 'imdb_more_like_this', 'imdb_id': imdb_id}
	return cache_object(get_imdb, string, params, False, 168)

def imdb_people_id(actor_name):
	name = actor_name.lower()
	string = 'imdb_people_id_%s' % name
	url, url_backup = people_search_url % (name[0], name.replace(' ', '%20')), base_url % people_search_url_backup % name
	params = {'url': url, 'action': 'imdb_people_id', 'name': name, 'url_backup': url_backup}
	return cache_object(get_imdb, string, params, False, 8736)

def imdb_reviews(imdb_id):
	url = base_url % reviews_url % imdb_id
	string = 'imdb_reviews_%s' % imdb_id
	params = {'url': url, 'action': 'imdb_reviews'}
	return cache_object(get_imdb, string, params, False, 168)

def imdb_parentsguide(imdb_id):
	url = base_url % parentsguide_url % imdb_id
	string = 'imdb_parentsguide_%s' % imdb_id
	params = {'url': url, 'action': 'imdb_parentsguide'}
	return cache_object(get_imdb, string, params, False, 168)

def imdb_trivia(imdb_id):
	url = base_url % trivia_url % imdb_id
	string = 'imdb_trivia_%s' % imdb_id
	params = {'url': url, 'action': 'imdb_trivia'}
	return cache_object(get_imdb, string, params, False, 168)

def imdb_blunders(imdb_id):
	url = base_url % blunders_url % imdb_id
	string = 'imdb_blunders_%s' % imdb_id
	params = {'url': url, 'action': 'imdb_blunders'}
	return cache_object(get_imdb, string, params, False, 168)

def imdb_people_trivia(imdb_id):
	url = base_url % people_trivia_url % imdb_id
	string = 'imdb_people_trivia_%s' % imdb_id
	params = {'url': url, 'action': 'imdb_people_trivia'}
	return cache_object(get_imdb, string, params, False, 168)

def get_imdb(params):
	imdb_list = []
	action = params.get('action')
	url = params.get('url')
	if action == 'imdb_more_like_this':
		def _process():
			for item in items:
				try:
					_id = item.split('href="/title/')[1].split('/?ref_')[0]
					if _id.replace('tt','').isnumeric(): yield (_id)
				except: pass
		try:
			result = _get_session().get(url, timeout=timeout, headers=headers).text
			result = result.split('<span>Storyline</span>')[0].split('<span>More like this</span>')[1]
			items = str(result).split('poster-card__title--clickable" aria-label="')
		except: items = []
		imdb_list = list(_process())
		imdb_list = [i for n, i in enumerate(imdb_list) if i not in imdb_list[n + 1:]] # remove duplicates
	if action in ('imdb_trivia', 'imdb_blunders'):
		def _process():
			for count, item in enumerate(items, 1):
				try:
					content = re.sub(r'<a class="ipc-md-link ipc-md-link--entity" href="\S+">', '', item).replace('</a>', '')
					content = replace_html_codes(content)
					content = content.replace('<br/><br/>', '\n')
					content = '[B]%s %02d.[/B][CR][CR]%s' % (_str, count, content)
					yield content
				except: pass
		if action == 'imdb_trivia': _str = 'TRIVIA'
		else: _str =  'BLUNDERS'
		result = _get_session().get(url, timeout=timeout, headers=headers)
		result = remove_accents(result.text)
		result = result.replace('\n', ' ')
		items = parseDOM(result, 'div', attrs={'class': 'ipc-html-content-inner-div'})
		imdb_list = list(_process())
	elif action == 'imdb_people_trivia':
		def _process():
			for count, item in enumerate(items, 1):
				try:
					content = re.sub(r'<a href=".+?">', '', item).replace('</a>', '').replace('<p> ', '').replace('<br />', '').replace('  ', '')
					content = re.sub(r'<a class=".+?">', '', item).replace('</a>', '').replace('<p> ', '').replace('<br />', '').replace('  ', '')
					content = replace_html_codes(content)
					content = '[B]%s %02d.[/B][CR][CR]%s' % (trivia_str, count, content)
					yield content
				except: pass
		trivia_str = 'TRIVIA'
		result = _get_session().get(url, timeout=timeout, headers=headers)
		result = remove_accents(result.text)
		result = result.replace('\n', ' ')
		items = parseDOM(result, 'div', attrs={'class': 'ipc-html-content-inner-div'})
		imdb_list = list(_process())
	elif action == 'imdb_reviews':
		def _process():
			count = 1
			for item in all_reviews:
				try:
					try:
						content = re.findall(r'plaidHtml":"(.*)","__typename":"Markdown', item)[0]
						try: content = content.encode('ascii').decode('unicode-escape')
						except: pass
						content = replace_html_codes(content.replace('</a>', '').replace('<p> ', '').replace('<br />', '').replace('  ', ''))
					except: continue
					try: spoiler = re.findall(r'"spoiler":(.*),"reportingLink', item)[0]
					except: spoiler = 'false'
					try: rating = re.findall(r'"authorRating":(.*),"submissionDate', item)[0]
					except: rating = '-'
					try:
						title = re.findall(r'"summary":{"originalText":"(.*)","__typename":"ReviewSummary', item)[0]
						title = replace_html_codes(title.replace('</a>', '').replace('<p> ', '').replace('<br />', '').replace('  ', ''))
					except: title = '-----'
					try: date = re.findall(r'"submissionDate":"(.*)","helpfulness', item)[0]
					except: date = '-----'
					try: review = '[B]%02d. [I]%s/10 - %s - %s[/I][/B][CR][CR]%s' % (count, rating, date, title, content)
					except: continue
					if spoiler == 'true': review = '[B][COLOR red][%s][/COLOR][CR][/B]' % spoiler_str + review
					count += 1
					yield review
				except: pass
		spoiler_str = 'CONTAINS SPOILERS'
		result = _get_session().get(url, timeout=timeout, headers=headers)
		result = remove_accents(result.text)
		result = result.replace('\n', ' ')
		body = re.findall(r'{"node":{"id":(.*)"__typename":"ReviewEdge"', result)[0]
		all_reviews = body.split('"__typename":"ReviewEdge"}')
		imdb_list = list(_process())
	elif action == 'imdb_people_id':
		try:
			name = params['name']
			result = _get_session().get(url, timeout=timeout)
			results = json.loads(re.sub(r'imdb\$(.+?)\(', '', result.text)[:-1])['d']
			imdb_list = [i['id'] for i in results if i['id'].startswith('nm') and i['l'].lower() == name][0]
		except: imdb_list = []
		if not imdb_list:
			try:
				result = _get_session().get(params['url_backup'], timeout=timeout)
				result = remove_accents(result.text)
				result = result.replace('\n', ' ')
				result = parseDOM(result, 'div', attrs={'class': 'lister-item-image'})[0]
				imdb_list = re.search(r'href="/name/(.+?)"', result, re.DOTALL).group(1)
			except: pass
	elif action == 'imdb_parentsguide':
		imdb_list = []
		imdb_append = imdb_list.append
		result = _get_session().get(url, timeout=timeout, headers=headers)
		result = remove_accents(result.text)
		result = result.replace('\n', ' ')
		results = parseDOM(result, 'section', attrs={'class': 'ipc-page-section ipc-page-section--base'})
		for item in results:
			if 'contentRating' in item: continue
			if 'Certifications' in item: continue
			item_dict = {}
			try:
				title_data = re.search(r'<span id="(.+?)">(.+?)</span>', item, re.DOTALL).group(0)
				title = replace_html_codes(re.search(r'">(.+?)</span>', title_data, re.DOTALL).group(1))
				item_dict['title'] = title
			except: continue
			try:
				ranking = replace_html_codes(re.search(r'<div class="ipc-signpost__text" role="presentation">(.+?)</div>', item, re.DOTALL).group(1))
				item_dict['ranking'] = ranking
			except: item_dict['ranking'] = 'none'
			try:
				listings = re.findall(r'<div class="ipc-html-content-inner-div" role="presentation">(.+?)</div>', item)
				listings = [replace_html_codes(i) for i in listings]
			except: listings = []
			if listings:
				item_dict['content'] = '\n\n'.join(['%02d. %s' % (count, i) for count, i in enumerate(listings, 1)])
			elif item_dict['ranking'] == 'none': continue
			item_dict['total_count'] = len(listings)
			if item_dict: imdb_append(item_dict)
	return imdb_list

def clear_imdb_cache(silent=False):
	from modules.kodi_utils import clear_property
	try:
		dbcon = connect_database('maincache_db')
		imdb_results = [str(i[0]) for i in dbcon.execute("SELECT id FROM maincache WHERE id LIKE ?", ('imdb_%',)).fetchall()]
		if not imdb_results: return True
		dbcon.execute("DELETE FROM maincache WHERE id LIKE ?", ('imdb_%',))
		for i in imdb_results: clear_property(i)
		return True
	except: return False

def refresh_imdb_meta_data(imdb_id):
	from modules.kodi_utils import clear_property
	try:
		imdb_results = []
		insert1, insert2 = '%%_%s' % imdb_id, '%%_%s_%%' % imdb_id
		dbcon = connect_database('maincache_db')
		for item in (insert1, insert2):
			imdb_results += [str(i[0]) for i in dbcon.execute("SELECT id FROM maincache WHERE id LIKE ?", (item,)).fetchall()]
		if not imdb_results: return True
		dbcon.execute("DELETE FROM maincache WHERE id LIKE ?", (insert1,))
		dbcon.execute("DELETE FROM maincache WHERE id LIKE ?", (insert2,))
		for i in imdb_results: clear_property(i)
	except: pass