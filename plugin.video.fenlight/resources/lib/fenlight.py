# -*- coding: utf-8 -*-
import sys
from time import time as _now, process_time as _cpu
# PERF (lotto 47): i due tempi che finora non erano mai stati misurati. Nel log della stick del 22/08
# fra l'ordine di ricarica (23:15:09.240) e la prima riga di una costruzione (23:15:20.219) ci sono
# ELEVEN secondi senza una sola riga di log, e nessuno sapeva come fossero divisi fra avvio
# dell'interprete, import dell'albero dei moduli e lavoro vero. Con reuselanguageinvoker=false ogni
# invocazione reimporta tutto da capo, quindi l'import e' il sospetto principale -- ma restava un
# sospetto, e su un sospetto non si ottimizza.
# 'avvio' e' la CPU gia' bruciata prima di arrivare a questa riga: e' il costo dell'interprete Python
# che parte, l'unica parte che non possiamo strumentare dall'interno.
_T0, _CPU0 = _now(), _cpu()
from modules.router import routing, sys_exit_check
_T1 = _now()

routing(sys)

try:
	from modules.kodi_utils import logger
	_T2 = _now()
	logger('FenLight PERF AVVIO', 'avvio interprete ~%.0f ms + import %.0f ms + esecuzione %.0f ms = %.0f ms | %s'
			% (_CPU0 * 1000, (_T1 - _T0) * 1000, (_T2 - _T1) * 1000, (_T2 - _T0) * 1000,
				(sys.argv[2][1:71] if len(sys.argv) > 2 and sys.argv[2] else '-')))
except: pass

# NON rimuovere: e' questo sys.exit(1) a prevenire il segfault di Kodi con reuselanguageinvoker.
if sys_exit_check(): sys.exit(1)

