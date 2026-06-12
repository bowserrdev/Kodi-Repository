# -*- coding: utf-8 -*-
import os
import sys
from urllib.parse import unquote
from apis.tmdb_api import tmdb_people_info, tmdb_people_full_info
from windows.base_window import open_window
from indexers.images import Images
from modules import kodi_utils
# logger = kodi_utils.logger

get_icon, addon_fanart = kodi_utils.get_icon, kodi_utils.get_addon_fanart()
add_items, set_content, set_category, end_directory = kodi_utils.add_items, kodi_utils.set_content, kodi_utils.set_category, kodi_utils.end_directory
build_url, make_listitem = kodi_utils.build_url, kodi_utils.make_listitem
tmdb_image_base = 'https://image.tmdb.org/t/p/%s%s'
default_image = get_icon('genre_family')

def tmdb_people(params):
	return Images().run({'mode': 'tmdb_people_list_image_results', 'action': params['action'], 'page_no': 1})

def person_search(key_id=None):
	return Images().run({'mode': 'tmdb_people_search_image_results', 'key_id': unquote(key_id), 'page_no': 1})

def favorite_people():
	return Images().run({'mode': 'favorite_people_list_image_results'})

def person_data_dialog(params):
	if 'key_id' in params: key_id = unquote(params.get('key_id'))
	elif 'query' in params: key_id = unquote(params.get('query'))
	else: key_id = None
	open_window(('windows.people', 'People'), 'people.xml', key_id=key_id, actor_name=params.get('actor_name'), actor_image=params.get('actor_image'),
				actor_id=params.get('actor_id'), reference_tmdb_id=params.get('reference_tmdb_id'), is_external=params.get('is_external', 'false'),
				starting_position=params.get('starting_position', None))

def person_direct_search(key_id):
	def _builder():
		for item in data:
			actor_id = int(item['id'])
			actor_name = item['name']
			image_path = item['profile_path']
			if item['profile_path']: actor_image = tmdb_image_base % ('h632', item['profile_path'])
			else: actor_image = default_image
			known_for_list = [i.get('title', 'NA') for i in item['known_for']]
			known_for_list = [i for i in known_for_list if not i == 'NA']
			known_for = '[B]Known for:[/B]\n%s' % '\n'.join(known_for_list) if known_for_list else ' '
			url_params = {'mode': 'person_data_dialog', 'actor_name': actor_name, 'actor_image': actor_image, 'actor_id': actor_id}
			url = build_url(url_params)
			listitem = make_listitem()
			listitem.setLabel(actor_name)
			listitem.setArt({'icon': actor_image, 'poster': actor_image, 'thumb': actor_image, 'fanart': addon_fanart, 'banner': actor_image})
			info_tag = listitem.getVideoInfoTag()
			info_tag.setPlot(known_for)
			yield (url, listitem, False)
	try:
		key_id = unquote(key_id)
		data = tmdb_people_info(key_id)['results']
	except: data = []
	handle = int(sys.argv[1])
	add_items(handle, list(_builder()))
	set_content(handle, 'movies')
	set_category(handle, key_id)
	end_directory(handle, cacheToDisc=False)

def build_cast_list(params):
	def _builder():
		for item in cast_data:
			try:
				person_id = item.get('id')
				if not person_id: continue
				listitem = make_listitem()
				listitem.setLabel(item.get('name', ''))
				listitem.setLabel2(item.get('role', ''))
				image = item.get('thumbnail') or default_image
				listitem.setArt({'icon': image, 'poster': image, 'thumb': image, 'fanart': addon_fanart, 'banner': image})
				listitem.setProperties({'tmdb_id': str(person_id), 'tmdb_type': 'person'})
				yield ('', listitem, False)
			except: pass
	from modules.metadata import movie_meta, tvshow_meta
	from modules.settings import tmdb_api_key, mpaa_region
	from modules.utils import get_datetime
	media_type = params.get('media_type', 'movie')
	meta_function = movie_meta if media_type == 'movie' else tvshow_meta
	try: cast_data = meta_function('tmdb_id', params['tmdb_id'], tmdb_api_key(), mpaa_region(), get_datetime()).get('cast') or []
	except: cast_data = []
	handle = int(sys.argv[1])
	add_items(handle, list(_builder()))
	set_content(handle, 'actors')
	set_category(handle, 'Cast')
	end_directory(handle, cacheToDisc=False)

def build_person_credits_list(params):
	def _builder():
		for item in credits_data:
			try:
				media_type = item.get('media_type')
				if media_type not in ('movie', 'tv'): continue
				tmdb_id = item['id']
				if tmdb_id in seen: continue
				seen_add(tmdb_id)
				title = item.get('title') or item.get('name') or ''
				date = item.get('release_date') or item.get('first_air_date') or ''
				poster_path = item.get('poster_path')
				poster = tmdb_image_base % ('w500', poster_path) if poster_path else default_image
				listitem = make_listitem()
				listitem.setLabel(title)
				listitem.setLabel2(item.get('job') or item.get('character') or '')
				listitem.setArt({'poster': poster, 'thumb': poster, 'icon': poster, 'fanart': addon_fanart})
				listitem.setProperties({'tmdb_id': str(tmdb_id), 'tmdb_type': media_type})
				info_tag = listitem.getVideoInfoTag()
				info_tag.setMediaType('movie' if media_type == 'movie' else 'tvshow')
				info_tag.setTitle(title), info_tag.setPlot(item.get('overview') or '')
				if date: info_tag.setYear(int(date.split('-')[0]))
				info_tag.setUniqueIDs({'tmdb': str(tmdb_id)})
				yield (media_details_url % (media_type, tmdb_id), listitem, True)
			except: pass
	media_details_url = 'plugin://plugin.video.themoviedb.helper/?info=details&tmdb_type=%s&tmdb_id=%s'
	person_id, job = params['person_id'], params.get('job')
	seen = set()
	seen_add = seen.add
	try:
		data = tmdb_people_full_info(person_id)
		# il layer cache puo restituire la response grezza o il dict gia decodificato
		try: data = data.json()
		except: pass
		credits_data = data['combined_credits']['crew']
		if job: credits_data = [i for i in credits_data if i.get('job') == job]
		credits_data.sort(key=lambda k: k.get('release_date') or k.get('first_air_date') or '0', reverse=True)
	except: credits_data = []
	handle = int(sys.argv[1])
	add_items(handle, list(_builder()))
	set_content(handle, 'movies')
	set_category(handle, 'Credits')
	end_directory(handle, cacheToDisc=False)