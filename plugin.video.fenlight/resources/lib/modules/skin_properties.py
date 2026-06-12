# -*- coding: utf-8 -*-
from modules import kodi_utils

set_property, clear_property = kodi_utils.set_property, kodi_utils.clear_property
prop_base = 'FenLight.ListItem.%s'
person_image = 'https://image.tmdb.org/t/p/h632%s'
writer_jobs = ('Screenplay', 'Writer', 'Story', 'Author')
person_props = ('Name', 'TMDb_ID', 'Thumb')

def set_videoinfo_properties(params):
	from modules.metadata import movie_meta, tvshow_meta
	from modules.settings import tmdb_api_key, mpaa_region
	from modules.utils import get_datetime
	def _set_people(key, people):
		for index, person in enumerate(people[:3], 1):
			set_property(prop_base % '%s.%s.Name' % (key, index), person.get('name', ''))
			set_property(prop_base % '%s.%s.TMDb_ID' % (key, index), str(person.get('id', '')))
			set_property(prop_base % '%s.%s.Thumb' % (key, index), person.get('thumbnail', ''))
	def _clear_all():
		for key in ('Director', 'Writer'):
			for index in range(1, 4):
				for prop in person_props: clear_property(prop_base % '%s.%s.%s' % (key, index, prop))
		for prop in ('Studio.1.Name', 'Studio.1.TMDb_ID', 'Set.Name', 'Set.TMDb_ID', 'Language'): clear_property(prop_base % prop)
	tmdb_id, media_type = params['tmdb_id'], params.get('media_type', 'movie')
	_clear_all()
	meta_function = movie_meta if media_type == 'movie' else tvshow_meta
	try: meta = meta_function('tmdb_id', tmdb_id, tmdb_api_key(), mpaa_region(), get_datetime()) or {}
	except: meta = {}
	meta_get = meta.get
	_set_people('Director', meta_get('directors') or [])
	_set_people('Writer', meta_get('writers') or [])
	extra_info = meta_get('extra_info') or {}
	studio = meta_get('studio')
	set_property(prop_base % 'Studio.1.Name', studio[0] if studio else '')
	set_property(prop_base % 'Studio.1.TMDb_ID', str(extra_info.get('studio_id') or ''))
	if extra_info.get('collection_id'):
		set_property(prop_base % 'Set.Name', extra_info.get('collection_name') or '')
		set_property(prop_base % 'Set.TMDb_ID', str(extra_info.get('collection_id')))
	set_property(prop_base % 'Language', meta_get('spoken_language') or '')
	
def open_media_info(params):
	from xbmcgui import Dialog
	from modules.metadata import movie_meta, tvshow_meta
	from modules.settings import tmdb_api_key, mpaa_region
	from modules.utils import get_datetime
	tmdb_id, media_type = params['tmdb_id'], params.get('media_type', 'movie')
	meta_function = movie_meta if media_type == 'movie' else tvshow_meta
	try: meta = meta_function('tmdb_id', tmdb_id, tmdb_api_key(), mpaa_region(), get_datetime())
	except: meta = None
	if not meta: return
	meta_get = meta.get
	listitem = kodi_utils.make_listitem()
	listitem.setLabel(meta_get('title') or '')
	listitem.setArt({'poster': meta_get('poster') or '', 'fanart': meta_get('fanart') or '', 'clearlogo': meta_get('clearlogo') or '',
					'landscape': meta_get('landscape') or '', 'thumb': meta_get('poster') or ''})
	info_tag = listitem.getVideoInfoTag()
	info_tag.setMediaType('movie' if media_type == 'movie' else 'tvshow')
	info_tag.setTitle(meta_get('title') or '')
	info_tag.setOriginalTitle(meta_get('original_title') or '')
	info_tag.setPlot(meta_get('plot') or '')
	try: info_tag.setYear(int(meta_get('year')))
	except: pass
	info_tag.setPremiered(meta_get('premiered') or '')
	info_tag.setRating(meta_get('rating') or 0.0)
	try: info_tag.setVotes(int(meta_get('votes') or 0))
	except: pass
	try: info_tag.setDuration(int(meta_get('duration') or 0))
	except: pass
	info_tag.setMpaa(meta_get('mpaa') or '')
	info_tag.setGenres(meta_get('genre') or [])
	info_tag.setStudios(meta_get('studio') or [])
	info_tag.setCountries(meta_get('country') or [])
	info_tag.setTrailer(str(meta_get('trailer') or ''))
	info_tag.setDirectors(meta_get('director') or [])
	info_tag.setWriters(meta_get('writer') or [])
	info_tag.setUniqueIDs({'imdb': str(meta_get('imdb_id') or ''), 'tmdb': str(meta_get('tmdb_id') or ''), 'tvdb': str(meta_get('tvdb_id') or '')})
	try: info_tag.setCast([kodi_utils.xbmc_actor(name=i['name'], role=i['role'], thumbnail=i['thumbnail']) for i in meta_get('cast') or []])
	except: pass
	from xbmc import executebuiltin, getCondVisibility, sleep
	if getCondVisibility('Window.IsVisible(movieinformation)'):
		executebuiltin('Dialog.Close(movieinformation,true)')
		count = 0
		while getCondVisibility('Window.IsVisible(movieinformation)') and count < 20:
			sleep(50)
			count += 1
	if media_type != 'movie': listitem.setPath('plugin://plugin.video.fenlight/?mode=build_season_list&tmdb_id=%s' % str(meta_get('tmdb_id') or tmdb_id))
	Dialog().info(listitem)

def browse_media(params):
	import xbmc
	tmdb_id = params.get('tmdb_id', '')
	if not tmdb_id: return
	url = 'plugin://plugin.video.fenlight/?mode=build_season_list&tmdb_id=%s' % tmdb_id
	xbmc.executebuiltin('Dialog.Close(movieinformation,true)')
	for _ in range(50):
		if not xbmc.getCondVisibility('Window.IsVisible(movieinformation)'): break
		xbmc.sleep(20)
	if xbmc.getCondVisibility('Window.IsVisible(videos)'): xbmc.executebuiltin('Container.Update(%s)' % url)
	else: xbmc.executebuiltin('ActivateWindow(videos,%s,return)' % url)