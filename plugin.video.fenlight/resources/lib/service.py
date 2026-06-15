# -*- coding: utf-8 -*-
import xbmc, xbmcgui
import json
from threading import Thread
from modules.blur_service import BlurService

pause_services_prop = 'fenlight.pause_services'
current_skin_prop = 'fenlight.current_skin'
trakt_service_string = 'TraktMonitor Service Update %s - %s'
trakt_success_line_dict = {'success': 'Trakt Update Performed', 'no account': '(Unauthorized) Trakt Update Performed'}
update_string = 'Next Update in %s minutes...'

def logger(heading, function):
	xbmc.log('###%s###: %s' % (heading, function), 1)

class SetAddonConstants:
	def run(self):
		logger('Fen Light', 'SetAddonConstants Service Starting')
		import xbmcgui, xbmcaddon, xbmcvfs
		addon_object = xbmcaddon.Addon('plugin.video.fenlight')
		self.window = xbmcgui.Window(10000)
		_info = addon_object.getAddonInfo
		addon_items = [('fenlight.addon_version', _info('version')),
					('fenlight.addon_path', _info('path')),
					('fenlight.addon_profile', xbmcvfs.translatePath(_info('profile'))),
					('fenlight.addon_icon', xbmcvfs.translatePath(_info('icon'))),
					('fenlight.addon_fanart', xbmcvfs.translatePath(_info('fanart')))]
		for item in addon_items: self.set_property(*item)
		return logger('Fen Light', 'SetAddonConstants Service Finished')

	def set_property(self, prop, value):
		self.window.setProperty(prop, value)

class DatabaseMaintenance:
	def run(self):
		logger('Fen Light', 'DatabaseMaintenance Service Starting')
		from caches.base_cache import make_databases
		make_databases()
		return logger('Fen Light', 'DatabaseMaintenance Service Finished')

class SyncSettings:
	def run(self):
		logger('Fen Light', 'SyncSettings Service Starting')
		from caches.settings_cache import sync_settings
		sync_settings()
		logger('Fen Light', 'SyncSettings Service Finished')

class CustomFonts:
	def run(self):
		logger('Fen Light', 'CustomFonts Service Starting')
		from windows.base_window import FontUtils
		monitor, player, window = xbmc.Monitor(), xbmc.Player(), xbmcgui.Window(10000)
		wait_for_abort, is_playing = monitor.waitForAbort, player.isPlayingVideo
		window.clearProperty(current_skin_prop)
		font_utils = FontUtils()
		while not monitor.abortRequested():
			font_utils.execute_custom_fonts()
			if window.getProperty(pause_services_prop) == 'true' or is_playing(): sleep = 20
			else: sleep = 10
			wait_for_abort(sleep)
		try: del monitor
		except: pass
		try: del player
		except: pass
		return logger('Fen Light', 'CustomFonts Service Finished')

class TraktMonitor:
	def run(self):
		logger('Fen Light', 'TraktMonitor Service Starting')
		from apis.trakt_api import trakt_sync_activities
		from caches.settings_cache import get_setting
		from modules.kodi_utils import run_plugin
		from modules.settings import trakt_sync_interval
		monitor, player, window = xbmc.Monitor(), xbmc.Player(), xbmcgui.Window(10000)
		wait_for_abort, is_playing = monitor.waitForAbort, player.isPlayingVideo
		while not monitor.abortRequested():
			while is_playing() or window.getProperty(pause_services_prop) == 'true': wait_for_abort(10)
			wait_time = 1800
			try:
				sync_interval, wait_time = trakt_sync_interval()
				next_update_string = update_string % sync_interval
				status = trakt_sync_activities()
				if status == 'failed': logger('Fen Light', trakt_service_string % ('Failed. Error from Trakt', next_update_string))
				else:
					if status in ('success', 'no account'): logger('Fen Light', trakt_service_string % ('Success. %s' % trakt_success_line_dict[status], next_update_string))
					else: logger('Fen Light', trakt_service_string % ('Success. No Changes Needed', next_update_string))# 'not needed'
					if status == 'success' and get_setting('fenlight.trakt.refresh_widgets', 'false') == 'true': run_plugin({'mode': 'kodi_refresh'})
			except Exception as e: logger('Fen Light', trakt_service_string % ('Failed', 'The following Error Occured: %s' % str(e)))
			wait_for_abort(wait_time)
		try: del monitor
		except: pass
		try: del player
		except: pass
		return logger('Fen Light', 'TraktMonitor Service Finished')

class WidgetRefresher:
	def run(self):
		logger('Fen Light', 'WidgetRefresher Service Starting')
		from time import time
		from caches.settings_cache import get_setting
		from modules.kodi_utils import home, run_plugin
		monitor, player = xbmc.Monitor(), xbmc.Player()
		wait_for_abort, self.is_playing = monitor.waitForAbort, player.isPlayingVideo
		self.window = xbmcgui.Window(10000)
		self.get_setting = get_setting
		self.home = home
		self.window.setProperty('fenlight.refresh_widgets', 'true')
		self.set_next_refresh(time())
		wait_for_abort(20)
		while not monitor.abortRequested():
			try:
				wait_for_abort(10)
				self.window.clearProperty('fenlight.refresh_widgets')
				offset = int(self.get_setting('fenlight.widget_refresh_timer', '60'))
				if offset != self.offset:
					self.set_next_refresh(time())
					continue
				if self.condition_check(): continue
				if self.next_refresh < time():
					run_plugin({'mode': 'refresh_widgets', 'show_notification': self.get_setting('fenlight.widget_refresh_notification', 'false')}, block=True)
					logger('Fen Light', 'WidgetRefresher Service - Widgets Refreshed')
					self.set_next_refresh(time())
			except: pass
		try: del monitor
		except: pass
		try: del player
		except: pass
		return logger('Fen Light', 'WidgetRefresher Service Finished')

	def condition_check(self):
		if not self.home(): return True
		if self.next_refresh == None or self.is_playing() or self.window.getProperty(pause_services_prop) == 'true': return True
		if self.window.getProperty('fenlight.window_loaded') == 'true': return True 
		try:
			window_stack = json.loads(self.window.getProperty('fenlight.window_stack'))
			if isinstance(window_stack, list): return True
		except: pass
		return False

	def set_next_refresh(self, _time):
		self.offset = int(self.get_setting('fenlight.widget_refresh_timer', '60'))
		if self.offset: self.next_refresh = _time + (self.offset*60)
		else: self.next_refresh = None

class WidgetPaginator:
	# Drives interactive "infinite scroll" pagination for home widgets. While a Fen Light widget is
	# focused it polls its scroll position; when the focus enters the last loaded page it bumps the
	# widget's page count (a Window(10000) property keyed per widget) and triggers a silent
	# Container.Refresh, so the plugin appends the next page in place and the focus is preserved.
	def run(self):
		logger('Fen Light', 'WidgetPaginator Service Starting')
		from time import time
		from caches.settings_cache import get_setting
		from modules.kodi_utils import execute_builtin
		from modules.settings import page_limit
		from modules import paginator
		monitor, player = xbmc.Monitor(), xbmc.Player()
		wait_for_abort, is_playing = monitor.waitForAbort, player.isPlayingVideo
		window = xbmcgui.Window(10000)
		get_infolabel = xbmc.getInfoLabel
		pending = {}  # key -> time the loading flag was set, to self-heal a build that never finishes
		triggered_at = {}  # key -> NumItems at last trigger; guards against runaway if a refresh doesn't grow the list
		stuck_timeout = 8
		last_log = None  # dedup: only log when the observed state actually changes
		def log_change(state):
			nonlocal last_log
			if state != last_log:
				paginator.log('watcher %s' % state); last_log = state
		while not monitor.abortRequested():
			try:
				if get_setting('fenlight.paginate.interactive', 'true') != 'true' \
						or is_playing() or window.getProperty(pause_services_prop) == 'true':
					log_change('idle (off/playing/paused)')
					wait_for_abort(1); continue
				# Identify the focused Fen Light widget. The skin sets fenlight.active_widget (the container id)
				# and fenlight.active_widget_path (its plugin path) on focus. Hub widgets load in 'browse' mode,
				# so Container(id).FolderPath is empty for them -> we fall back to the stored path.
				cur_ctrl = get_infolabel('System.CurrentControlID')
				prop_id = window.getProperty('fenlight.active_widget')
				prop_path = window.getProperty('fenlight.active_widget_path')
				widget_id, folderpath = None, ''
				if prop_id and xbmc.getCondVisibility('Control.HasFocus(%s)' % prop_id):
					widget_id = prop_id
					folderpath = get_infolabel('Container(%s).FolderPath' % prop_id) or prop_path
				else:
					for c in (cur_ctrl, '501', '502', '503', '504', '505', '506', '301'):
						if not c: continue
						fp = get_infolabel('Container(%s).FolderPath' % c)
						if 'plugin.video.fenlight' in fp and xbmc.getCondVisibility('Control.HasFocus(%s)' % c):
							widget_id, folderpath = c, fp; break
				if widget_id is None or not folderpath:
					log_change('idle cur_ctrl=%s prop=%s picked=%s' % (cur_ctrl, prop_id, widget_id))
					wait_for_abort(0.3); continue
				numitems = int(get_infolabel('Container(%s).NumItems' % widget_id) or 0)
				current = int(get_infolabel('Container(%s).CurrentItem' % widget_id) or 0)
				if numitems and current:
					key = paginator.make_key(paginator.query_from_path(folderpath))
					loading = window.getProperty(paginator.LOADING_PROP % key) == 'true'
					hasmore = window.getProperty(paginator.HASMORE_PROP % key) == 'true'
					runway = page_limit(True) * paginator.lookahead_pages()
					log_change('id=%s key=%s current=%s/%s remaining=%s runway=%s hasmore=%s loading=%s' %
								(widget_id, paginator.short(key), current, numitems, numitems - current, runway, hasmore, loading))
					if loading:
						# A refresh is in flight; clear a flag left stuck by a build that errored out.
						if time() - pending.get(key, 0) > stuck_timeout:
							window.clearProperty(paginator.LOADING_PROP % key); pending.pop(key, None)
							paginator.log('watcher STUCK loading flag cleared key=%s after %ss' % (paginator.short(key), stuck_timeout))
					else:
						pending.pop(key, None)
						# Anti-runaway: only fire if the container grew since our last trigger for this key.
						# If a previous refresh at this exact NumItems didn't add items, stop hammering it.
						if hasmore and numitems - current <= runway and triggered_at.get(key) != numitems:
							pages = paginator.raw_pages(key, paginator.initial_batch())
							window.setProperty(paginator.LOADING_PROP % key, 'true')
							window.setProperty(paginator.PAGES_PROP % key, str(pages + 1))
							pending[key] = time()
							triggered_at[key] = numitems
							paginator.log('watcher TRIGGER key=%s pages %s->%s current=%s/%s -> kodi_refresh(%s)' %
										(paginator.short(key), pages, pages + 1, current, numitems, widget_id))
							# Same focus-preserving primitive the Trakt monitor uses: a soft widget reload that
							# appends the new page in place without rebuilding/flickering the container.
							execute_builtin('UpdateLibrary(video,special://skin/foo)')
							wait_for_abort(0.5); continue
			except Exception as e:
				paginator.log('watcher EXC %s' % e)
			wait_for_abort(0.2)
		try: del monitor
		except: pass
		try: del player
		except: pass
		return logger('Fen Light', 'WidgetPaginator Service Finished')

class AutoStart:
	def run(self):
		logger('Fen Light', 'AutoStart Service Starting')
		from modules.settings import auto_start_fenlight
		if auto_start_fenlight():
			from modules.kodi_utils import run_addon
			run_addon()
		return logger('Fen Light', 'AutoStart Service Finished')

class FenLightMonitor(xbmc.Monitor):
	def __init__ (self):
		xbmc.Monitor.__init__(self)
		self.startServices()

	def startServices(self):
		SetAddonConstants().run()
		DatabaseMaintenance().run()
		SyncSettings().run()
		Thread(target=CustomFonts().run).start()
		Thread(target=BlurService().run).start()
		Thread(target=TraktMonitor().run).start()
		Thread(target=WidgetRefresher().run).start()
		Thread(target=WidgetPaginator().run).start()
		AutoStart().run()

	def onNotification(self, sender, method, data):
		if method in ('GUI.OnScreensaverActivated', 'System.OnSleep'):
			xbmcgui.Window(10000).setProperty(pause_services_prop, 'true')
			logger('OnNotificationActions', 'PAUSING Fen Light Services Due to Device Sleep')
		elif method in ('GUI.OnScreensaverDeactivated', 'System.OnWake'):
			xbmcgui.Window(10000).clearProperty(pause_services_prop)
			logger('OnNotificationActions', 'UNPAUSING Fen Light Services Due to Device Awake')

logger('Fen Light', 'Main Monitor Service Starting')
FenLightMonitor().waitForAbort()
logger('Fen Light', 'Main Monitor Service Finished')