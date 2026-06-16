# -*- coding: utf-8 -*-
import re
import json
import requests
from caches.base_cache import connect_database
from caches.main_cache import cache_object
from caches.settings_cache import get_setting
from modules.dom_parser import parseDOM
from modules.utils import remove_accents, replace_html_codes, normalize
from modules.kodi_utils import make_session

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.64 Safari/537.36 Edge/101.0.1210.53',
			'Accept-Language':'en-us,en;q=0.5'}
base_url = 'https://www.imdb.com/%s'
graphql_url = 'https://api.graphql.imdb.com/'
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
session = make_session('https://')

def imdb_data(imdb_id, lang):
	if get_setting('fenlight.imdb_data') != 'true': return {}
	if not imdb_id or imdb_id == 'tt0000000': return {}
	ietf_lang = '%s-%s' % (lang, lang.upper())
	string = 'imdb_data_%s_%s' % (lang, imdb_id)
	params = {'imdb_id': imdb_id, 'lang': ietf_lang}
	return cache_object(get_imdb_graphql, string, params, False, 720)

def get_imdb_graphql(params):
	data = {}
	try:
		query = {
			'query': 'query GetData($id: ID!) { title(id: $id) { plot { plotText { plainText } } ratingsSummary { aggregateRating voteCount } releaseYear { year } '
					 'directors: credits(first: 5, filter: { categories: ["director"] }) { edges { node { name { nameText { text } } } } } '
					 'writers: credits(first: 5, filter: { categories: ["writer"] }) { edges { node { name { nameText { text } } } } } } }',
			'variables': {'id': params['imdb_id']}
		}
		graphql_headers = {'Content-Type': 'application/json', 'User-Agent': headers['User-Agent'], 'X-Imdb-User-Language': params['lang']}
		r = session.post(graphql_url, json=query, headers=graphql_headers, timeout=timeout)
		if r.status_code != 200: return data
		title = r.json()['data']['title']
		try:
			plot = title['plot']['plotText']['plainText']
			if plot: data['plot'] = plot
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

def imdb_episode_ratings(imdb_id, season):
	if get_setting('fenlight.imdb_data') != 'true': return {}
	if not imdb_id or imdb_id == 'tt0000000': return {}
	string = 'imdb_ep_ratings_%s_%s' % (imdb_id, season)
	params = {'imdb_id': imdb_id, 'season': str(season)}
	return cache_object(get_imdb_episode_ratings, string, params, False, 720)

def get_imdb_episode_ratings(params):
	data = {}
	try:
		query = {
			'query': 'query GetEps($id: ID!, $season: [String!]) { title(id: $id) { episodes { episodes(first: 250, filter: { includeSeasons: $season }) '
					 '{ edges { node { series { episodeNumber { episodeNumber seasonNumber } } ratingsSummary { aggregateRating voteCount } } } } } } }',
			'variables': {'id': params['imdb_id'], 'season': [params['season']]}
		}
		graphql_headers = {'Content-Type': 'application/json', 'User-Agent': headers['User-Agent']}
		r = session.post(graphql_url, json=query, headers=graphql_headers, timeout=timeout)
		if r.status_code != 200: return data
		edges = r.json()['data']['title']['episodes']['episodes']['edges']
		for e in edges:
			try:
				node = e['node']
				ep_num = node['series']['episodeNumber']
				s, ep = ep_num['seasonNumber'], ep_num['episodeNumber']
				if s is None or ep is None: continue
				ratings = node.get('ratingsSummary') or {}
				rating, votes = ratings.get('aggregateRating'), ratings.get('voteCount')
				if rating: data['%s_%s' % (s, ep)] = {'rating': rating, 'votes': votes or 0}
			except: pass
	except: pass
	return data


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
			result = session.get(url, timeout=timeout, headers=headers).text
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
		result = session.get(url, timeout=timeout, headers=headers)
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
		result = session.get(url, timeout=timeout, headers=headers)
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
		result = session.get(url, timeout=timeout, headers=headers)
		result = remove_accents(result.text)
		result = result.replace('\n', ' ')
		body = re.findall(r'{"node":{"id":(.*)"__typename":"ReviewEdge"', result)[0]
		all_reviews = body.split('"__typename":"ReviewEdge"}')
		imdb_list = list(_process())
	elif action == 'imdb_people_id':
		try:
			name = params['name']
			result = session.get(url, timeout=timeout)
			results = json.loads(re.sub(r'imdb\$(.+?)\(', '', result.text)[:-1])['d']
			imdb_list = [i['id'] for i in results if i['id'].startswith('nm') and i['l'].lower() == name][0]
		except: imdb_list = []
		if not imdb_list:
			try:
				result = session.get(params['url_backup'], timeout=timeout)
				result = remove_accents(result.text)
				result = result.replace('\n', ' ')
				result = parseDOM(result, 'div', attrs={'class': 'lister-item-image'})[0]
				imdb_list = re.search(r'href="/name/(.+?)"', result, re.DOTALL).group(1)
			except: pass
	elif action == 'imdb_parentsguide':
		imdb_list = []
		imdb_append = imdb_list.append
		result = session.get(url, timeout=timeout, headers=headers)
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