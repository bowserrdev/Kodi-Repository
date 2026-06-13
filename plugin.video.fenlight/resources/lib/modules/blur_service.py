# -*- coding: utf-8 -*-
import os
import json
import hashlib
from urllib.parse import unquote
import xbmc
import xbmcgui
import xbmcvfs
from modules.kodi_utils import logger

home_window = xbmcgui.Window(10000)
blur_folder = xbmcvfs.translatePath('special://profile/addon_data/plugin.video.fenlight/blur/')
default_size, default_radius = 480, 60
jpeg_quality = 75
max_cache_files = 200

def _settings():
	try: size = int(xbmc.getInfoLabel('Skin.String(TMDbHelper.Blur.Size)') or default_size)
	except: size = default_size
	try: radius = int(xbmc.getInfoLabel('Skin.String(TMDbHelper.Blur.Radius)') or default_radius)
	except: radius = default_radius
	return size, radius

def _texture_cache_path(url):
	try:
		query = {'jsonrpc': '2.0', 'id': 1, 'method': 'Textures.GetTextures',
				'params': {'properties': ['cachedurl'], 'filter': {'field': 'url', 'operator': 'is', 'value': url}}}
		result = json.loads(xbmc.executeJSONRPC(json.dumps(query)))
		cachedurl = result['result']['textures'][0]['cachedurl']
		path = xbmcvfs.translatePath('special://thumbnails/%s' % cachedurl)
		if os.path.exists(path): return path
	except: pass
	return None

def _local_copy(source):
	url = source
	if url.startswith('image://'): url = unquote(url[8:]).rstrip('/')
	cached = _texture_cache_path(url)
	if cached: return cached
	if url.startswith('special://'):
		path = xbmcvfs.translatePath(url)
		return path if os.path.exists(path) else None
	if os.path.exists(url): return url
	if url.startswith('http'):
		try:
			from modules.kodi_utils import make_session
			target = os.path.join(blur_folder, 'src_%s' % hashlib.md5(url.encode()).hexdigest())
			if os.path.exists(target): return target
			response = make_session().get(url, timeout=10.0)
			if not response or response.status_code != 200: return None
			with open(target, 'wb') as f: f.write(response.content)
			return target
		except: return None
	return None

def _blur(source):
	try: from PIL import Image, ImageFilter
	except ImportError:
		logger('FenLight BlurService', 'PIL/Pillow non disponibile, blur disattivato')
		return None
	size, radius = _settings()
	key = hashlib.md5(('%s_%s_%s' % (source, size, radius)).encode()).hexdigest()
	target = os.path.join(blur_folder, '%s.jpg' % key)
	tiled_target = '%s-tiled.jpg' % target
	if os.path.exists(target) and os.path.exists(tiled_target): return target
	local = _local_copy(source)
	if not local: return None
	try:
		if not os.path.exists(blur_folder): os.makedirs(blur_folder)
		try: resample = Image.Resampling.BILINEAR
		except AttributeError: resample = Image.BILINEAR
		with Image.open(local) as img:
			try: img.draft('RGB', (size, size))
			except: pass
			img = img.convert('RGB')
			try: img.thumbnail((size, size), resample, reducing_gap=3.0)
			except TypeError: img.thumbnail((size, size), resample)
		img = img.filter(ImageFilter.GaussianBlur(radius))
		img.save(target, 'JPEG', quality=jpeg_quality)
		_make_tiled(img, tiled_target)
		return target
	except: return None

def _make_tiled(img, target):
	from PIL import Image
	w, h = img.size
	flip_h = img.transpose(Image.FLIP_LEFT_RIGHT)
	flip_v = img.transpose(Image.FLIP_TOP_BOTTOM)
	flip_b = flip_h.transpose(Image.FLIP_TOP_BOTTOM)
	tiled = Image.new('RGB', (w * 2, h * 2))
	tiled.paste(img, (0, 0))
	tiled.paste(flip_h, (w, 0))
	tiled.paste(flip_v, (0, h))
	tiled.paste(flip_b, (w, h))
	tiled.save(target, 'JPEG', quality=jpeg_quality)

def _cleanup():
	try:
		files = [os.path.join(blur_folder, i) for i in os.listdir(blur_folder)]
		if len(files) <= max_cache_files: return
		files.sort(key=os.path.getmtime)
		for path in files[:len(files) - max_cache_files]:
			try: os.remove(path)
			except: pass
	except: pass

def blur_image(params):
	# Mode one-shot dal router: ?mode=blur_image&image=...&prefix=...
	source = params.get('image') or params.get('blur_image')
	prefix = params.get('prefix') or 'ListItem'
	if not source: return
	result = _blur(source)
	if not result: return
	home_window.setProperty('TMDbHelper.%s.BlurImage' % prefix, result)
	home_window.setProperty('TMDbHelper.%s.BlurImage.Original' % prefix, source)

class BlurService:
	def _resolve(self, spec):
		container = xbmc.getInfoLabel('Window.Property(TMDbHelper.WidgetContainer)')
		for token in spec.split('|'):
			token = token.strip().replace('{x}', '')
			if not token: continue
			value = xbmc.getInfoLabel('ListItem.%s' % token)
			if value: return value
			if container:
				value = xbmc.getInfoLabel('Container(%s).ListItem.%s' % (container, token))
				if value: return value
		return ''
	
	def run(self):
		logger('Fen Light', 'BlurService Starting')
		monitor, player = xbmc.Monitor(), xbmc.Player()
		wait_for_abort, is_playing = monitor.waitForAbort, player.isPlayingVideo
		pause_string = 'fenlight.pause_services'
		last_source, failed = None, {}
		_cleanup()
		while not monitor.abortRequested():
			if wait_for_abort(0.3): break
			if is_playing() or home_window.getProperty(pause_string) == 'true': continue
			if not xbmc.getCondVisibility('Skin.HasSetting(TMDbHelper.EnableBlur)'): continue
			spec = home_window.getProperty('TMDbHelper.Blur.SourceImage') or 'Art(fanart)'
			source = self._resolve(spec) or home_window.getProperty('TMDbHelper.Blur.Fallback')
			if source == last_source: continue
			logger('BlurDebug', 'source=%s' % source)
			if not source: continue
			if failed.get(source, 0) > 4: continue
			result = _blur(source)
			logger('BlurDebug', 'result=%s' % result)
			if not result:
				failed[source] = failed.get(source, 0) + 1
				continue
			last_source = source
			home_window.setProperty('TMDbHelper.ListItem.BlurImage', result)
			home_window.setProperty('TMDbHelper.ListItem.BlurImage.Original', source)
			home_window.setProperty('TMDbHelper.ListItem.Current.BlurImage', result)
			home_window.setProperty('TMDbHelper.ListItem.Current.BlurImage.Original', source)
		try: del monitor
		except: pass
		try: del player
		except: pass
		logger('Fen Light', 'BlurService Finished')
