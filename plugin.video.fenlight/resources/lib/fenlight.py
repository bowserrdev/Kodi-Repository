# -*- coding: utf-8 -*-
import sys
from time import perf_counter as _pc
_T_START = _pc()

# Profilatore di import (lotto 54, DIAGNOSTICO -- va rimosso quando la potatura e' finita).
# Il segmento 'import pigri' vale 4,2-4,8 s per widget ed e' UNA sola istruzione (`from indexers
# import mdblist_lists` e simili): senza sapere quale modulo dell'albero costa cosa si potrebbe solo
# tirare a indovinare. Misura il tempo PROPRIO di ciascun modulo, cioe' al netto di quelli che
# importa a sua volta, altrimenti la radice si prenderebbe il merito di tutto.
# reuselanguageinvoker=false garantisce un interprete nuovo per invocazione: la patch a
# builtins.__import__ non sopravvive e non puo' contaminare altre invocazioni.
_IMPORT_TIMES, _IMPORT_ORDER, _IMPORT_PARENT = {}, [], {}
try:
	import builtins as _builtins
	_real_import = _builtins.__import__
	_import_stack = []
	def _timed_import(name, *args, **kwargs):
		if name in sys.modules: return _real_import(name, *args, **kwargs)
		_t0 = _pc()
		_import_stack.append(0.0)
		try: return _real_import(name, *args, **kwargs)
		finally:
			_elapsed = _pc() - _t0
			_children = _import_stack.pop()
			if _import_stack: _import_stack[-1] += _elapsed
			if name not in _IMPORT_TIMES:
				_IMPORT_ORDER.append(name)
				# Chi ha chiesto questo modulo per primo: senza il richiedente si sa QUANTO costa la
				# libreria standard ma non da dove entra, che e' l'unica informazione azionabile.
				try:
					_caller = sys._getframe(1).f_globals.get('__name__') or '?'
					# un import relativo arriva con name='' : il richiedente e' l'unico indizio utile
					_IMPORT_PARENT[name] = _caller
				except: pass
			_IMPORT_TIMES[name] = _IMPORT_TIMES.get(name, 0.0) + (_elapsed - _children)
	_builtins.__import__ = _timed_import
except: pass

from modules.router import routing, sys_exit_check
_T_IMPORT = _pc()
# from modules.kodi_utils import logger

routing(sys)
_T_END = _pc()
# Marcatori (lotto 50) -- vedi kodi_utils.log_invocation per il perche'. La riga sta PRIMA di
# sys_exit_check() perche' quello chiama external(), cioe' una traversata verso la GUI, e subito dopo
# si esce: la misura non deve dipendere da come finisce l'uscita. Il sys.exit(1) resta l'ULTIMA
# istruzione e non va toccato: e' cio' che previene il segfault di Kodi sulle invocazioni dei widget.
try:
	import builtins as _b
	_b.__import__ = _real_import
except: pass
try:
	from modules.kodi_utils import log_invocation, log_import_profile
	log_invocation(sys.argv, _T_START, _T_IMPORT, _T_END)
	log_import_profile(sys.argv, _IMPORT_TIMES, _IMPORT_ORDER, _IMPORT_PARENT)
except: pass
if sys_exit_check(): sys.exit(1)
