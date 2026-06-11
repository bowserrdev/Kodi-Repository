# -*- coding: utf-8 -*-
"""
Tests for Area 2 changes in kodi_utils.py.
Run from resources/lib/: python3 test_kodi_utils.py
"""
import sys, os, types, tempfile, shutil, importlib, importlib.util

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

# ── Locate kodi_utils.py (same dir as this script, or modules/ subdir) ────────
_here = os.path.dirname(os.path.abspath(__file__))
_ku_candidates = [
    os.path.join(_here, 'kodi_utils.py'),
    os.path.join(_here, 'modules', 'kodi_utils.py'),
]
_ku_path = next((p for p in _ku_candidates if os.path.exists(p)), None)
if not _ku_path:
    print(f'{RED}ERROR{RESET}: kodi_utils.py not found. Run from resources/lib/ or place the file there.')
    sys.exit(1)

# ── Mock Kodi bindings ────────────────────────────────────────────────────────
_mock_db_dir = tempfile.mkdtemp(prefix='fenlight_kodi_test_')

class _CountingWindow:
    _instance_count = 0
    def __init__(self, wid=10000):
        _CountingWindow._instance_count += 1
    def getProperty(self, p): return 'test_val'
    def setProperty(self, p, v): pass
    def clearProperty(self, p): pass
    def clearProperties(self): pass

def _mock_list_dirs(path):
    real = path.replace('special://profile/Database/', _mock_db_dir + '/')
    if os.path.isdir(real): return ([], os.listdir(real))
    return ([], [])

xbmc_mod = types.ModuleType('xbmc')
xbmc_mod.getInfoLabel       = lambda label: '21.0 Git:20240101' if 'BuildVersion' in label else ''
xbmc_mod.log                = lambda *a: None
xbmc_mod.getSkinDir         = lambda: 'skin.estuary'
xbmc_mod.getCondVisibility  = lambda *a: False
xbmc_mod.executeJSONRPC     = lambda *a: '{}'
xbmc_mod.sleep              = lambda *a: None
xbmc_mod.Player             = type('Player', (), {})
xbmc_mod.Monitor            = type('Monitor', (), {})
xbmc_mod.executebuiltin     = lambda *a: None
xbmc_mod.convertLanguage    = lambda *a: ''
xbmc_mod.getSupportedMedia  = lambda *a: ''
xbmc_mod.PlayList           = lambda *a: None
xbmc_mod.Actor              = None

xbmcgui_mod = types.ModuleType('xbmcgui')
xbmcgui_mod.Window              = _CountingWindow
xbmcgui_mod.ListItem            = type('ListItem', (), {'__init__': lambda self, **kw: None})
xbmcgui_mod.getCurrentWindowId = lambda: 10000
xbmcgui_mod.Dialog              = type('Dialog', (), {})
xbmcgui_mod.WindowXMLDialog     = type('WindowXMLDialog', (), {})
xbmcgui_mod.DialogProgressBG    = type('DialogProgressBG', (), {})

xbmcvfs_mod = types.ModuleType('xbmcvfs')
xbmcvfs_mod.translatePath   = lambda p: p.replace('special://profile/Database/', _mock_db_dir + '/')
xbmcvfs_mod.exists          = os.path.exists
xbmcvfs_mod.File            = open
xbmcvfs_mod.copy            = lambda *a: None
xbmcvfs_mod.delete          = lambda *a: None
xbmcvfs_mod.rmdir           = lambda *a: None
xbmcvfs_mod.rename          = lambda *a: None
xbmcvfs_mod.listdir         = _mock_list_dirs
xbmcvfs_mod.mkdir           = lambda *a: None
xbmcvfs_mod.mkdirs          = lambda *a: None

xbmcplugin_mod = types.ModuleType('xbmcplugin')
for _a in ('endOfDirectory','addSortMethod','addDirectoryItem','addDirectoryItems','setContent','setPluginCategory'):
    setattr(xbmcplugin_mod, _a, lambda *a, **kw: None)

xbmcaddon_mod = types.ModuleType('xbmcaddon')
xbmcaddon_mod.Addon = type('Addon', (), {'getAddonInfo': lambda self, k: ''})

icons_mod = types.ModuleType('modules.icons')
for _a in ('box_office', 'nextpage', 'nextpage_landscape'): setattr(icons_mod, _a, 'I1JJhji')
modules_stub = types.ModuleType('modules')
modules_stub.icons = icons_mod

for _n, _m in [('xbmc', xbmc_mod), ('xbmcgui', xbmcgui_mod), ('xbmcvfs', xbmcvfs_mod),
               ('xbmcplugin', xbmcplugin_mod), ('xbmcaddon', xbmcaddon_mod),
               ('modules', modules_stub), ('modules.icons', icons_mod)]:
    sys.modules[_n] = _m

# ── Load kodi_utils directly from file ───────────────────────────────────────
def _load_ku(path):
    spec = importlib.util.spec_from_file_location('kodi_utils', path)
    mod  = importlib.util.module_from_spec(spec)
    _CountingWindow._instance_count = 0  # reset before each load
    spec.loader.exec_module(mod)
    return mod

ku = _load_ku(_ku_path)

# ═════════════════════════════════════════════════════════════════════════════
section('1. make_session() – pool_maxsize = 8')

import requests
session = ku.make_session('https://api.themoviedb.org')
adapter = session.get_adapter('https://api.themoviedb.org')
check('Returns a requests.Session',  isinstance(session, requests.Session))
check('Adapter is HTTPAdapter',      isinstance(adapter, requests.adapters.HTTPAdapter))
try:
    pool_size = adapter.poolmanager.connection_pool_kw.get('maxsize')
    check('pool_maxsize is 8 (not 100)', pool_size == 8, f'got: {pool_size}')
except Exception as e:
    check('pool_maxsize is 8 (not 100)', False, str(e))

# ═════════════════════════════════════════════════════════════════════════════
section('2. kodi_version() – returns module-level constant')

check('_KODI_VERSION is an integer',           isinstance(ku._KODI_VERSION, int))
check('kodi_version() returns _KODI_VERSION',  ku.kodi_version() is ku._KODI_VERSION)
check('Consistent across repeated calls',      ku.kodi_version() == ku.kodi_version())

# ═════════════════════════════════════════════════════════════════════════════
section('3. get_video_database_path() – known version dict lookup')

for version, suffix in ku.myvideos_db_paths.items():
    saved = ku._KODI_VERSION
    ku._KODI_VERSION = version
    path = ku.get_video_database_path()
    ku._KODI_VERSION = saved
    check(f'Kodi {version} → MyVideos{suffix}.db',
        path is not None and path.endswith('MyVideos%s.db' % suffix), f'got: {path}')

# ═════════════════════════════════════════════════════════════════════════════
section('4. get_video_database_path() – filesystem fallback for unknown version')

for f in ['MyVideos119.db', 'MyVideos124.db', 'MyVideos131.db']:
    open(os.path.join(_mock_db_dir, f), 'w').close()

saved = ku._KODI_VERSION
ku._KODI_VERSION = 22
path = ku.get_video_database_path()
ku._KODI_VERSION = saved

check('Unknown version uses fallback (not None)',    path is not None,                          f'got: {path}')
check('Fallback picks highest-numbered DB file',     path is not None and 'MyVideos131' in path, f'got: {path}')

# ═════════════════════════════════════════════════════════════════════════════
section('5. get_video_database_path() – returns None when directory is empty')

empty_dir = tempfile.mkdtemp(prefix='fenlight_empty_')
saved_translate = ku.translatePath
ku.translatePath = lambda p: p.replace('special://profile/Database/', empty_dir + '/')

saved = ku._KODI_VERSION
ku._KODI_VERSION = 22
path = ku.get_video_database_path()
ku._KODI_VERSION = saved
ku.translatePath = saved_translate

check('Returns None when no MyVideos*.db found', path is None, f'got: {path}')

# ═════════════════════════════════════════════════════════════════════════════
section('6. _WINDOW – created once, reused by all property functions')

check('Window(10000) instantiated exactly once on import',
    _CountingWindow._instance_count == 1,
    f'instantiated {_CountingWindow._instance_count} times')
check('kodi_window() returns _WINDOW (same object)',
    ku.kodi_window() is ku._WINDOW)
check('get_property delegates to _WINDOW',
    ku.get_property('x') == ku._WINDOW.getProperty('x'))

# Calling property functions many times must NOT create new Window objects
before = _CountingWindow._instance_count
for _ in range(50):
    ku.get_property('fenlight.test')
    ku.set_property('fenlight.test', 'v')
    ku.clear_property('fenlight.test')
after = _CountingWindow._instance_count
check('50× get/set/clear_property → zero additional Window() calls',
    after == before, f'created {after - before} extra instances')

# ═════════════════════════════════════════════════════════════════════════════
shutil.rmtree(_mock_db_dir, ignore_errors=True)
shutil.rmtree(empty_dir, ignore_errors=True)

total = pass_count + fail_count
print(f'\n{"═"*60}')
print(f'  Result: {pass_count}/{total} passed', end='  ')
if fail_count == 0: print(f'{GREEN}ALL PASS{RESET}')
else: print(f'{RED}{fail_count} FAILED{RESET}')
print(f'{"═"*60}\n')
sys.exit(0 if fail_count == 0 else 1)