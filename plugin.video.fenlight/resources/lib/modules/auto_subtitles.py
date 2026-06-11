# -*- coding: utf-8 -*-
import os
import json
import xbmc
import xbmcvfs
from urllib.request import urlopen, Request
from urllib.parse import urlencode
from urllib.error import HTTPError

from caches.settings_cache import get_setting
from modules.kodi_utils import sleep, notification, set_property, get_property

_API = 'https://api.opensubtitles.com/api/v1/'
_URL_LOGIN = _API + 'login'
_URL_SEARCH = _API + 'subtitles'
_URL_DOWNLOAD = _API + 'download'
_TOKEN_PROP = 'fenlight.autosub.token'


def _headers(with_auth=False):
    h = {
        'Api-Key': get_setting('autosub.api_key'),
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': 'FenLight/1.0',
    }
    if with_auth:
        token = get_property('autosub.token')
        if token:
            h['Authorization'] = 'Bearer ' + token
    return h


def _login():
    username = get_setting('autosub.username', '')
    password = get_setting('autosub.password', '')
    if not (username and password):
        return False
    body = json.dumps({'username': username, 'password': password}).encode()
    try:
        req = Request(_URL_LOGIN, data=body, headers=_headers(), method='POST')
        with urlopen(req, timeout=10) as r:
            token = json.loads(r.read()).get('token', '')
        if token:
            set_property(_TOKEN_PROP, token)
            return True
    except Exception:
        pass
    return False


def _lang_in_streams(streams, pref_3, pref_2, pref_name):
    targets = {pref_3.lower(), pref_2.lower(), pref_name.lower()}
    for s in streams:
        sl = s.lower().strip()
        if sl in targets or pref_name.lower() in sl:
            return True
    return False


def _search(imdb_id, media_type, season, episode, lang_2):
    raw_id = imdb_id.replace('tt', '') if imdb_id else ''
    if not raw_id:
        return None
    params = {'languages': lang_2, 'type': media_type}
    if media_type == 'episode':
        params.update({'parent_imdb_id': raw_id, 'season_number': season, 'episode_number': episode})
    else:
        params['imdb_id'] = raw_id
    try:
        req = Request('%s?%s' % (_URL_SEARCH, urlencode(params)), headers=_headers())
        with urlopen(req, timeout=15) as r:
            return json.loads(r.read()).get('data')
    except Exception:
        return None


def _best_result(results):
    def key(x):
        a = x.get('attributes', {})
        return (
            bool(a.get('moviehash_match')),
            bool(a.get('from_trusted')),
            a.get('votes', 0) or 0,
            a.get('ratings', 0) or 0,
            a.get('download_count', 0) or 0,
        )
    return max(results, key=key)


def _download(file_id):
    if not get_property('autosub.token') and not _login():
        return None
    body = json.dumps({'file_id': file_id, 'sub_format': 'srt'}).encode()
    try:
        req = Request(_URL_DOWNLOAD, data=body, headers=_headers(with_auth=True), method='POST')
        with urlopen(req, timeout=15) as r:
            link = json.loads(r.read()).get('link')
        if not link:
            return None
        cdn_req = Request(link, headers={'User-Agent': 'Mozilla/5.0'})
        with urlopen(cdn_req, timeout=15) as r:
            return r.read()
    except HTTPError as e:
        if e.code == 406:
            notification('Auto Subtitles: daily download limit reached', 4000)
        return None
    except Exception:
        return None


def _save(content, lang_2):
    dir_path = xbmcvfs.translatePath('special://temp/fenlight_autosub/')
    if not xbmcvfs.exists(dir_path):
        xbmcvfs.mkdirs(dir_path)
    path = os.path.join(dir_path, 'autosub.%s.srt' % lang_2)
    try:
        with open(path, 'wb') as f:
            f.write(content)
        return path
    except Exception:
        return None


def auto_subtitle_check(player):
    if get_setting('autosub.enabled') != 'true':
        return
    if not get_setting('autosub.api_key', ''):
        return

    pref_3 = get_setting('preferred_language', '')
    if not pref_3 or pref_3 == 'empty_setting':
        return
    pref_2 = xbmc.convertLanguage(pref_3, xbmc.ISO_639_1)
    pref_name = xbmc.convertLanguage(pref_3, xbmc.ENGLISH_NAME)
    if not pref_2:
        return

    timeout = 0
    while not getattr(player, '_av_started', False) and timeout < 150:
        sleep(300)
        timeout += 1

    audio_streams = []
    for _ in range(10):
        audio_streams = player.getAvailableAudioStreams()
        if audio_streams:
            break
        sleep(500)

    if audio_streams and _lang_in_streams(audio_streams, pref_3, pref_2, pref_name):
        return

    sub_streams = player.getAvailableSubtitleStreams()
    if sub_streams and _lang_in_streams(sub_streams, pref_3, pref_2, pref_name):
        return

    imdb_id = getattr(player, 'imdb_id', '')
    media_type = getattr(player, 'media_type', 'movie')
    season = getattr(player, 'season', '')
    episode = getattr(player, 'episode', '')

    results = _search(imdb_id, media_type, season, episode, pref_2)
    if not results:
        return

    best = _best_result(results)
    files = best.get('attributes', {}).get('files', [])
    if not files:
        return
    file_id = files[0].get('file_id')
    if not file_id:
        return

    content = _download(file_id)
    if not content:
        return

    path = _save(content, pref_2)
    if not path or not player.isPlayingVideo():
        return

    player.setSubtitles(path)
    player.showSubtitles(True)