# -*- coding: utf-8 -*-
"""
Test suite for the rewritten Fen Light cache layer.
Runs outside Kodi by mocking the Kodi Python bindings.

Usage: python3 test_caches.py
"""
import sys, os, json, time, tempfile, threading, sqlite3, shutil, types

# ── Temp dir ──────────────────────────────────────────────────────────────────
TMPDIR = tempfile.mkdtemp(prefix='fenlight_test_')
os.makedirs(os.path.join(TMPDIR, 'databases'), exist_ok=True)

# ── Window property store ─────────────────────────────────────────────────────
_window_props = {}

# ── Mock kodi_utils ───────────────────────────────────────────────────────────
kodi_utils_mod = types.ModuleType('modules.kodi_utils')
kodi_utils_mod.kodi_refresh    = lambda: None
kodi_utils_mod.sleep           = lambda ms: None
kodi_utils_mod.notification    = lambda *a, **kw: None
kodi_utils_mod.confirm_dialog  = lambda *a, **kw: True
kodi_utils_mod.ok_dialog       = lambda *a, **kw: None
kodi_utils_mod.show_text       = lambda *a, **kw: None
kodi_utils_mod.progress_dialog = lambda *a, **kw: None
kodi_utils_mod.close_all_dialog  = lambda: None
kodi_utils_mod.get_property    = lambda prop: _window_props.get(prop, '')
kodi_utils_mod.set_property    = lambda prop, val: _window_props.__setitem__(prop, val)
kodi_utils_mod.clear_property  = lambda prop: _window_props.pop(prop, None)
kodi_utils_mod.path_exists     = os.path.exists
kodi_utils_mod.list_dirs       = lambda p: ([], os.listdir(p) if os.path.isdir(p) else [])
kodi_utils_mod.make_directory  = lambda p: os.makedirs(p, exist_ok=True)
kodi_utils_mod.delete_file     = os.remove
kodi_utils_mod.open_file       = open
kodi_utils_mod.translatePath   = lambda p: p
kodi_utils_mod.addon_profile   = lambda: TMPDIR
kodi_utils_mod.path_join       = os.path.join

for stub in ('xbmc', 'xbmcgui', 'xbmcaddon', 'xbmcvfs', 'xbmcplugin'):
    sys.modules[stub] = types.ModuleType(stub)

modules_mod = types.ModuleType('modules')
modules_mod.kodi_utils = kodi_utils_mod
sys.modules['modules']            = modules_mod
sys.modules['modules.kodi_utils'] = kodi_utils_mod

# ── Import cache layer ────────────────────────────────────────────────────────
_lib_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _lib_dir)

from caches.base_cache import connect_database, get_timestamp, BaseCache, make_databases
make_databases()   # creates tables in TMPDIR/databases/

# ── Test helpers ──────────────────────────────────────────────────────────────
GREEN = '\033[92m'; RED = '\033[91m'; RESET = '\033[0m'
pass_count = fail_count = 0

def check(name, condition, detail=''):
    global pass_count, fail_count
    if condition:
        print(f'  {GREEN}PASS{RESET}  {name}')
        pass_count += 1
    else:
        print(f'  {RED}FAIL{RESET}  {name}' + (f'  [{detail}]' if detail else ''))
        fail_count += 1

def section(title):
    print(f'\n{"─"*60}\n  {title}\n{"─"*60}')

# ═════════════════════════════════════════════════════════════════════════════
section('1. SQLite Pragmas (WAL + NORMAL synchronous)')

conn = connect_database('maincache_db')
wal_mode  = conn.execute('PRAGMA journal_mode').fetchone()[0]
sync_mode = conn.execute('PRAGMA synchronous').fetchone()[0]
check('journal_mode = WAL',    wal_mode == 'wal',  f'got: {wal_mode}')
check('synchronous = NORMAL',  sync_mode == 1,     f'got: {sync_mode}')  # 1 = NORMAL

# ═════════════════════════════════════════════════════════════════════════════
section('2. Thread-local connection reuse')

conn_a1 = connect_database('maincache_db')
conn_a2 = connect_database('maincache_db')
check('Same thread reuses same connection object', conn_a1 is conn_a2)

other_conn = {}
threading.Thread(target=lambda: other_conn.__setitem__('c', connect_database('maincache_db'))).start()
time.sleep(0.05)
check('Different thread gets its own connection', other_conn.get('c') is not conn_a1)

# ═════════════════════════════════════════════════════════════════════════════
section('3. BaseCache – JSON serialization round-trip')

cache = BaseCache('maincache_db', 'maincache')

test_data = {
    'title': 'Spirited Away',
    'original_title': '千と千尋の神隠し',
    'year': '2001',
    'genre': ['Animation', 'Adventure'],
    'rating': 8.6,
    'cast': [{'name': 'Daveigh Chase', 'role': 'Chihiro', 'thumbnail': ''}],
    'keywords': None,
    'tvdb_id': 'None',
}
cache.set('test_movie_1', test_data, expiration=1)
result = cache.get('test_movie_1')

check('get() returns data after set()',        result is not None)
check('dict round-trip is identical',          result == test_data)
check('non-ASCII (Japanese) title preserved',  result.get('original_title') == '千と千尋の神隠し')
check('None value preserved',                  result.get('keywords') is None)
check('list value preserved',                  result.get('genre') == ['Animation', 'Adventure'])
check('nested dict preserved',                 result.get('cast', [{}])[0].get('name') == 'Daveigh Chase')

raw = conn.execute('SELECT data FROM maincache WHERE id = ?', ('test_movie_1',)).fetchone()
check('Data stored as JSON in DB (not repr)',  raw is not None and raw[0].startswith('{'))
try:
    json.loads(raw[0])
    check('Stored value is valid JSON',  True)
except Exception as e:
    check('Stored value is valid JSON',  False, str(e))

# ═════════════════════════════════════════════════════════════════════════════
section('4. BaseCache – cache expiry')

cache.set('test_expiry', {'x': 1}, expiration=0)
time.sleep(0.01)
check('Expired entry (expiration=0) returns None', cache.get('test_expiry') is None)

cache.set('test_valid', {'x': 2}, expiration=1)
check('Non-expired entry is returned',             cache.get('test_valid') is not None)

# ═════════════════════════════════════════════════════════════════════════════
section('5. MetaCache – window property memory cache')

from caches.meta_cache import MetaCache
mc = MetaCache()

fake_meta = {'tmdb_id': 12345, 'title': 'Test', 'imdb_id': 'tt0000001', 'tvdb_id': 'None', 'genre': ['Drama']}
expires = get_timestamp(168)
mc.set_memory_cache('movie', 'tmdb_id', fake_meta, expires, '12345')

raw_prop = _window_props.get('fenlight.movie_tmdb_id_12345', '')
check('Memory cache written as JSON string',        raw_prop.startswith('['))
try:
    parsed = json.loads(raw_prop)
    check('Memory cache is valid JSON',              True)
    check('Format is [expires, meta] list',          isinstance(parsed, list) and len(parsed) == 2)
    check('expires value is correct',               parsed[0] == expires)
    check('meta value is correct',                  parsed[1] == fake_meta)
except Exception as e:
    check('Memory cache is valid JSON',              False, str(e))

result_mem = mc.get_memory_cache('movie', 'tmdb_id', '12345', get_timestamp())
check('get_memory_cache returns correct meta',      result_mem == fake_meta)

# ═════════════════════════════════════════════════════════════════════════════
section('6. MetaCache – delete_all_seasons (single LIKE query)')

from caches.meta_cache import meta_cache as mc_s

for season in range(1, 6):
    mc_s.set_season('99999_%s' % season, [{'ep': i} for i in range(1, 4)], expiration=168)

dbcon = connect_database('metacache_db')
before = dbcon.execute('SELECT COUNT(*) FROM season_metadata WHERE tmdb_id LIKE ?', ('99999_%',)).fetchone()[0]
check('5 season rows exist before delete_all_seasons',  before == 5, f'got {before}')

mc_s.delete_all_seasons('99999')
after = dbcon.execute('SELECT COUNT(*) FROM season_metadata WHERE tmdb_id LIKE ?', ('99999_%',)).fetchone()[0]
check('All 5 rows removed by single LIKE DELETE',       after == 0,  f'got {after}')

# Window properties should also be cleared
for season in range(1, 6):
    prop = 'fenlight.meta_season_99999_%s' % season
    check(f'Window prop season {season} cleared',  _window_props.get(prop) is None)

# ═════════════════════════════════════════════════════════════════════════════
section('7. TraktCache – JSON serialization')

from caches.trakt_cache import TraktCache
tc = TraktCache()

trakt_data = {'movie': {'watched_at': '2024-01-01T00:00:01.000Z'}, 'ids': {'tmdb': 1234, 'imdb': 'tt1234567'}}
tc.set('trakt_test', trakt_data)
result = tc.get('trakt_test')
check('TraktCache get() after set()',  result == trakt_data)

raw = connect_database('trakt_db').execute('SELECT data FROM trakt_data WHERE id = ?', ('trakt_test',)).fetchone()
check('TraktCache stored as JSON',     raw is not None and raw[0].startswith('{'))
check('TraktCache missing key → None', tc.get('does_not_exist') is None)

# ═════════════════════════════════════════════════════════════════════════════
section('8. EpisodeGroupsCache – JSON')

from caches.episode_groups_cache import EpisodeGroupsCache
egc = EpisodeGroupsCache()

eg_data = {'id': 'abc123', 'name': 'Chronological', 'groups': [1, 2, 3]}
egc.set('55555', eg_data)
check('EpisodeGroupsCache round-trip',         egc.get('55555') == eg_data)
check('Missing key returns empty dict {}',     egc.get('nonexistent') == {})

# ═════════════════════════════════════════════════════════════════════════════
section('9. NavigatorCache – JSON in DB and window properties')

from caches.navigator_cache import NavigatorCache
nc = NavigatorCache()

test_list = [{'name': 'Movies', 'mode': 'navigator.main', 'action': 'MovieList', 'iconImage': 'movies'}]
nc.set_list('TestList', 'default', test_list)
check('NavigatorCache DB round-trip',             nc.get_list('TestList', 'default') == test_list)
check('NavigatorCache memory cache round-trip',   nc.get_memory_cache('TestList', 'default') == test_list)

raw_prop = _window_props.get('fenlight_TestList_default', '')
check('Navigator window prop stored as JSON',  raw_prop.startswith('[') or raw_prop.startswith('{'))
check('Navigator missing key returns None',    nc.get_list('NoSuchList', 'default') is None)

# ═════════════════════════════════════════════════════════════════════════════
section('10. Thread safety – 20 concurrent writers/readers')

errors = []
results = {}

def _worker(tid):
    try:
        data = {'thread': tid, 'payload': list(range(50)), 'title': '千と千尋の神隠し'}
        cache.set(f'thread_{tid}', data, expiration=1)
        results[tid] = cache.get(f'thread_{tid}')
    except Exception as e:
        errors.append((tid, str(e)))

threads = [threading.Thread(target=_worker, args=(i,)) for i in range(20)]
for t in threads: t.start()
for t in threads: t.join()

check('No exceptions during 20 concurrent writes',  len(errors) == 0, str(errors[:3]))
correct = all(results.get(i, {}).get('thread') == i for i in range(20))
check('All 20 threads wrote and read correctly',    correct)

# ═════════════════════════════════════════════════════════════════════════════
section('11. MainCache – parameterized LIKE queries')

from caches.main_cache import MainCache
mc_main = MainCache()

for i in range(3):
    mc_main.set('FOLDERSCRAPER_path_%s' % i, {'data': i}, expiration=1)
mc_main.set('OTHER_key', {'data': 99}, expiration=1)

result = mc_main.delete_all_folderscrapers()
check('delete_all_folderscrapers returns True',   result is True)

dbcon2 = connect_database('maincache_db')
remaining_folders = dbcon2.execute('SELECT COUNT(*) FROM maincache WHERE id LIKE ?', ('FOLDERSCRAPER_%',)).fetchone()[0]
other_exists = dbcon2.execute('SELECT COUNT(*) FROM maincache WHERE id = ?', ('OTHER_key',)).fetchone()[0]
check('FOLDERSCRAPER rows deleted',       remaining_folders == 0, f'got {remaining_folders}')
check('OTHER_key row not affected',       other_exists == 1,      f'got {other_exists}')

# ═════════════════════════════════════════════════════════════════════════════
shutil.rmtree(TMPDIR, ignore_errors=True)

total = pass_count + fail_count
print(f'\n{"═"*60}')
print(f'  Result: {pass_count}/{total} passed', end='  ')
if fail_count == 0:
    print(f'{GREEN}ALL PASS{RESET}')
else:
    print(f'{RED}{fail_count} FAILED{RESET}')
print(f'{"═"*60}\n')
sys.exit(0 if fail_count == 0 else 1)