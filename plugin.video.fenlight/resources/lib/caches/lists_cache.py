# -*- coding: utf-8 -*-
from caches.base_cache import BaseCache, get_timestamp
# from modules.kodi_utils import logger

GET_ALL = 'SELECT id FROM lists'
DELETE_ALL = 'DELETE FROM lists'
CLEAN = 'DELETE from lists WHERE CAST(expires AS INT) <= ?'

class ListsCache(BaseCache):
	def __init__(self):
		BaseCache.__init__(self, 'lists_db', 'lists')

	def delete_all_lists(self):
		try:
			dbcon = self.manual_connect('lists_db')
			for i in dbcon.execute(GET_ALL): self.delete_memory_cache(str(i[0]))
			dbcon.execute(DELETE_ALL)
			dbcon.execute('VACUUM')
			return True
		except: return False

	def clean_database(self):
		try:
			dbcon = self.manual_connect('lists_db')
			dbcon.execute(CLEAN, (get_timestamp(),))
			dbcon.execute('VACUUM')
			return True
		except: return False

lists_cache = ListsCache()

def lists_cache_object(function, string, args, json=False, expiration=48):
	cache = lists_cache.get(string)
	if cache is not None: return cache
	if isinstance(args, list): args = tuple(args)
	else: args = (args,)
	if json: result = function(*args).json()
	else: result = function(*args)
	# UN FALLIMENTO NON E' UN RISULTATO (lotto 120). None qui vuol dire "la chiamata non e' riuscita":
	# metterlo in cache non serve a niente -- il get qui sopra tratta None come assenza e rifa' la
	# chiamata comunque -- ma soprattutto invita chi produce i dati a convertire l'errore in un valore
	# vuoto pur di avere qualcosa da restituire, e QUELLO si mette in cache eccome. E' il difetto che
	# ha spento 'Latest TV Shows' sulla stick per 24 ore: vedi mdblist_get_list_contents.
	if result is not None: lists_cache.set(string, result, expiration=expiration)
	return result