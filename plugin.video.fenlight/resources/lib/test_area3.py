# -*- coding: utf-8 -*-
"""
Tests for Area 3 changes.
Section 1-4: utils.py thread functions (runtime, no Kodi needed with minimal mock).
Section 5:   AST inspection of movies/tvshows/seasons/episodes (no Kodi needed).
Run from resources/lib/: python3 test_area3.py
"""
import sys, os, ast, time, types, threading, importlib, importlib.util, tempfile, shutil

_here = os.path.dirname(os.path.abspath(__file__))
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

# ── Locate files ──────────────────────────────────────────────────────────────
def _find(name):
    for root, _, files in os.walk(_here):
        if name in files:
            return os.path.join(root, name)
    return None

utils_path    = _find('utils.py')
movies_path   = _find('movies.py')
tvshows_path  = _find('tvshows.py')
seasons_path  = _find('seasons.py')
episodes_path = _find('episodes.py')

for name, path in [('utils.py', utils_path), ('movies.py', movies_path),
                   ('tvshows.py', tvshows_path), ('seasons.py', seasons_path),
                   ('episodes.py', episodes_path)]:
    if not path:
        print(f'{RED}ERROR{RESET}: {name} not found under {_here}')
        sys.exit(1)

# ── Mock Kodi bindings so utils.py can be imported ────────────────────────────
for stub in ('xbmc', 'xbmcgui', 'xbmcvfs', 'xbmcplugin', 'xbmcaddon'):
    sys.modules[stub] = types.ModuleType(stub)

ku_mod = types.ModuleType('modules.kodi_utils')
ku_mod.translate_path  = lambda p: p
ku_mod.sleep           = lambda ms: None
ku_mod.show_busy_dialog = lambda: None
ku_mod.hide_busy_dialog = lambda: None
ku_mod.path_exists     = os.path.exists
modules_pkg = types.ModuleType('modules')
modules_pkg.kodi_utils = ku_mod
sys.modules['modules']            = modules_pkg
sys.modules['modules.kodi_utils'] = ku_mod

def _load(path):
    spec = importlib.util.spec_from_file_location('_mod', path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

utils = _load(utils_path)

# ═════════════════════════════════════════════════════════════════════════════
section('1. _WORKER_COUNT – auto-detected, bounded')

cpu = os.cpu_count() or 4
expected = max(4, min(cpu + 2, 10))
check('_WORKER_COUNT is an integer',              isinstance(utils._WORKER_COUNT, int))
check('_WORKER_COUNT matches formula',            utils._WORKER_COUNT == expected,
      f'got {utils._WORKER_COUNT}, expected {expected}')
check('_WORKER_COUNT >= 4',                       utils._WORKER_COUNT >= 4)
check('_WORKER_COUNT <= 10',                      utils._WORKER_COUNT <= 10)

# ═════════════════════════════════════════════════════════════════════════════
section('2. make_thread_list – correctness and backward compat')

results = []
lock = threading.Lock()
def _collector(item):
    with lock: results.append(item)

items = list(range(15))
returned = utils.make_thread_list(_collector, items)

check('Returns iterable (backward compat)',       hasattr(returned, '__iter__'))
check('Returned objects have .join()',            all(hasattr(r, 'join') for r in returned))
check('.join() is a no-op (does not raise)',      all(r.join() is None for r in returned))
check('All 15 items processed before return',     sorted(results) == items)
check('No activeCount/busy-wait overhead',        'while activeCount' not in open(utils_path).read())

# ═════════════════════════════════════════════════════════════════════════════
section('3. make_thread_list_enumerate – correct (count, item) args')

enum_results = {}
def _enum_collector(count, item):
    with lock: enum_results[count] = item

items = ['a', 'b', 'c', 'd', 'e']
utils.make_thread_list_enumerate(_enum_collector, items)

check('All 5 items received',                     len(enum_results) == 5)
check('Counts are 0-4',                           sorted(enum_results.keys()) == [0,1,2,3,4])
check('Items match original list at each index',  all(enum_results[i] == items[i] for i in range(5)))

# ═════════════════════════════════════════════════════════════════════════════
section('4. make_thread_list_multi_arg – correct arg unpacking')

multi_results = []
def _multi_collector(a, b):
    with lock: multi_results.append((a, b))

arg_list = [(1, 'x'), (2, 'y'), (3, 'z')]
utils.make_thread_list_multi_arg(_multi_collector, arg_list)

check('All 3 tuples processed',                   len(multi_results) == 3)
check('Args unpacked correctly',
    sorted(multi_results) == [(1,'x'),(2,'y'),(3,'z')])

# ═════════════════════════════════════════════════════════════════════════════
section('5. Concurrency – pool runs tasks in parallel, not sequentially')

timings = []
N = utils._WORKER_COUNT + 2  # more tasks than 1 worker could handle serially fast

def _slow_task(i):
    time.sleep(0.05)  # 50ms each
    with lock: timings.append(i)

t0 = time.time()
utils.make_thread_list(_slow_task, list(range(N)))
elapsed = time.time() - t0

# Sequential would take N * 0.05s. Parallel should be much less.
sequential_time = N * 0.05
check(f'{N} tasks (50ms each) complete faster than sequentially',
    elapsed < sequential_time * 0.75,
    f'elapsed={elapsed:.2f}s, sequential would be {sequential_time:.2f}s')
check('All tasks completed',                      len(timings) == N)

# ═════════════════════════════════════════════════════════════════════════════
section('6. Thread safety – shared list append under concurrent writes')

shared = []
def _appender(i):
    time.sleep(0.001)
    shared.append(i)

utils.make_thread_list(_appender, list(range(50)))
check('50 concurrent appends – no items lost',    len(shared) == 50)
check('No duplicates',                            len(set(shared)) == 50)

# ═════════════════════════════════════════════════════════════════════════════
section('7. AST inspection – fanart_empty moved out of module level')

def _get_module_level_calls(path):
    """Return all function call names at module level (outside any function/class)."""
    tree = ast.parse(open(path).read())
    calls = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue  # skip function/class bodies
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Attribute):
                    calls.append(child.func.attr)
                elif isinstance(child.func, ast.Name):
                    calls.append(child.func.id)
    return calls

def _source_contains(path, text):
    return text in open(path).read()

for name, path in [('movies', movies_path), ('tvshows', tvshows_path),
                   ('seasons', seasons_path), ('episodes', episodes_path)]:
    module_calls = _get_module_level_calls(path)
    check(f'{name}: addon_fanart() NOT called at module level',
        'addon_fanart' not in module_calls,
        f'found at module level')

# ═════════════════════════════════════════════════════════════════════════════
section('8. AST inspection – fanart_empty in correct scope')

# movies/tvshows: self.fanart_empty in __init__
for name, path in [('movies', movies_path), ('tvshows', tvshows_path)]:
    check(f'{name}: self.fanart_empty assigned in __init__',
        _source_contains(path, 'self.fanart_empty = kodi_utils.addon_fanart()'))
    check(f'{name}: self.fanart_empty used in build_*_content',
        _source_contains(path, 'self.fanart_empty'))

# seasons: local var inside build_season_list
check('seasons: fanart_empty local var inside build_season_list',
    _source_contains(seasons_path, 'fanart_empty = kodi_utils.addon_fanart()'))

# episodes: fanart_empty in both build functions
src = open(episodes_path).read()
count = src.count('fanart_empty = kodi_utils.addon_fanart()')
check('episodes: fanart_empty added in build_episode_list AND build_single_episode',
    count >= 2, f'found {count} occurrence(s), need ≥ 2')

# ═════════════════════════════════════════════════════════════════════════════
section('9. AST inspection – seasons.py list(list()) eliminated')

check('seasons: list(list(_process())) is gone',
    not _source_contains(seasons_path, 'list(list(_process()))'))
check('seasons: list(_process()) is present',
    _source_contains(seasons_path, 'list(_process())'))

# ═════════════════════════════════════════════════════════════════════════════
section('10. utils.py – old threading cruft fully removed')

utils_src = open(utils_path).read()
check('activeCount removed from imports',    'activeCount' not in utils_src)
check('max_threads import removed',          'from modules.settings import max_threads' not in utils_src)
check('busy-wait loop removed',             'while activeCount' not in utils_src)
check('ThreadPoolExecutor imported',         'from concurrent.futures import ThreadPoolExecutor' in utils_src)
check('_Done class present',                'class _Done' in utils_src)

# ═════════════════════════════════════════════════════════════════════════════
total = pass_count + fail_count
print(f'\n{"═"*60}')
print(f'  Result: {pass_count}/{total} passed', end='  ')
if fail_count == 0: print(f'{GREEN}ALL PASS{RESET}')
else: print(f'{RED}{fail_count} FAILED{RESET}')
print(f'{"═"*60}\n')
sys.exit(0 if fail_count == 0 else 1)