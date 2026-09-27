# -*- coding: utf-8 -*-
"""
	Fenomscrapers Module
"""

import re
from functools import lru_cache
from string import printable
from cocoscrapers.modules import cleantitle
from cocoscrapers.modules.undesirables import Undesirables
from cocoscrapers.modules.control import homeWindow, setting as getSetting, setSetting


RES_4K = ('2160', '216o', '.4k', 'ultrahd', 'ultra.hd', '.uhd.')
RES_1080 = ('1080', '1o8o', '108o', '1o80', '.fhd.')
RES_720 = ('720', '72o')
SCR = ('dvdscr', 'screener', '.scr.', '.r5', '.r6')
CAM = ('1xbet', 'betwin', '.cam.', 'camrip', 'cam.rip', 'dvdcam', 'dvd.cam', 'dvdts', 'hdcam', '.hd.cam', '.hctc', '.hc.tc', '.hdtc',
				'.hd.tc', 'hdts', '.hd.ts', 'hqcam', '.hg.cam', '.tc.', '.tc1', '.tc7', '.ts.', '.ts1', '.ts7', 'tsrip', 'telecine', 'telesync', 'tele.sync')

LANG = ('arabic', 'bengali', 'bgaudio', 'castellano', 'chinese', 'dutch', 'finnish', 'french', 'german', 'greek', 'indonesian', 'hebrew', 'italian', 'korean', 'latino', 'polish',
				'portuguese', 'russian', 'swedish', 'spanish', 'tamil', 'telugu', 'truefrench', 'truespanish', 'turkish')
ABV_LANG = ('.ara.', '.ces.', '.chi.', '.chs.', '.cze.', '.dan.', '.de.', '.deu.', '.dut.', '.ell.', '.es.', '.esl.', '.esp.', '.fi.', '.fin.', '.fr.', '.fra.', '.fre.', '.frn.', '.gai.', '.ger.', '.gle.', '.gre.',
						'.gtm.', '.he.', '.heb.', '.hi.', '.hin.', '.hun.', '.hindi.', '.ind.', '.iri.', '.it.', '.ita.', '.ja.', '.jap.', '.jpn.', '.ko.', '.kor.', '.lat.', '.nl.', '.lit.', '.nld.', '.nor.', '.pl.', '.pol.',
						'.pt.', '.por.', '.ru.', '.rus.', '.som.', '.spa.', '.sv.', '.sve.', '.swe.', '.tha.', '.tr.', '.tur.', '.uae.', '.uk.', '.ukr.', '.vi.', '.vie.', '.zh.', '.zho.')
DUBBED = ('bengali.dub', 'dublado', 'dubbed', 'pldub')
SUBS = ('subita', 'subfrench', 'subspanish', 'subtitula', 'swesub', 'nl.subs')

ENG_CHECK = ('.eng.', '.en.', 'english', 'multi')
SRT_CHECK = ('with.srt', '.avi', '.mkv', '.mp4')

UNDESIRABLES = ['400p.octopus', '720p.octopus', '1080p.octopus', 'alexfilm', 'amedia', 'audiobook', 'baibako', 'bigsinema', 'bonus.disc', 'casstudio.tv', 'courage.bambey',
				'.cbr', '.cbz', 'coldfilm', 'dilnix', 'dutchreleaseteam', 'e.book.collection', 'empire.minutemen', 'eniahd', '.exe', 'exkinoray', 'extras.only',
				'gears.media', 'gearsmedia', 'good.people', 'gostfilm', 'hamsterstudio', 'hdrezka', 'hdtvrip', 'hurtom', 'idea.film', 'ideafilm', 'jaskier', 'kapatejl6', 'kb.1080p',
				'kb.720p', 'kb.400p', 'kerob', 'kinokopilka', 'kravec', 'kuraj.bambey', 'lakefilm', 'lostfilm', 'megapeer', 'minutemen.empire', 'newstudio',
				'omskbird', '.ost.', 'paravozik', 'profix.media', 'rifftrax', 'sample', 'soundtrack', 'subtitle.only', 'sunshinestudio', 'teaser', 'trailer', 'tumbler.studio',
				'tvshows', 'ultradox', 'viruseproject', 'vostfr', 'vo.stfr', 'web.dlrip', 'webdlrip', 'wish666', 'pa.web.dl', '.p.web.dl', '.d.web.dl', '.dt.web.dl']
# viruseproject has lots of uploads on glotorrents and site fixes the "&dn=???" portion in html title to reflect the true range the pack covers vs. assclowns incomplete pack file name used

season_list = ('one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eigh', 'nine', 'ten', 'eleven', 'twelve', 'thirteen', 'fourteen',
			'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen', 'twenty', 'twenty-one', 'twenty-two', 'twenty-three',
			'twenty-four', 'twenty-five')
season_ordinal_list = ('first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'seventh', 'eighth', 'ninth', 'tenth', 'eleventh', 'twelfth',
			'thirteenth', 'fourteenth', 'fifteenth', 'sixteenth', 'seventeenth', 'eighteenth', 'nineteenth', 'twentieth', 'twenty-first',
			'twenty-second', 'twenty-third', 'twenty-fourth', 'twenty-fifth')
season_ordinal2_list = ('1st', '2nd', '3rd', '4th', '5th', '6th', '7th', '8th', '9th', '10th', '11th', '12th', '13th', '14th', '15th', '16th',
			'17th', '18th', '19th', '20th', '21st', '22nd', '23rd', '24th', '25th')

season_dict = {'1': 'one', '2': 'two', '3': 'three', '4': 'four', '5': 'five', '6': 'six', '7': 'seven', '8': 'eigh', '9': 'nine', '10': 'ten',
			'11': 'eleven', '12': 'twelve', '13': 'thirteen', '14': 'fourteen', '15': 'fifteen', '16': 'sixteen', '17': 'seventeen',
			'18': 'eighteen', '19': 'nineteen', '20': 'twenty', '21': 'twenty-one', '22': 'twenty-two', '23': 'twenty-three',
			'24': 'twenty-four', '25': 'twenty-five'}
season_ordinal_dict = {'1': 'first', '2': 'second', '3': 'third', '4': 'fourth', '5': 'fifth', '6': 'sixth', '7': 'seventh', '8': 'eighth', '9': 'ninth',
			'10': 'tenth', '11': 'eleventh', '12': 'twelfth', '13': 'thirteenth', '14': 'fourteenth', '15': 'fifteenth', '16': 'sixteenth',
			'17': 'seventeenth', '18': 'eighteenth', '19': 'nineteenth', '20': 'twentieth', '21': 'twenty-first', '22': 'twenty-second',
			'23': 'twenty-third', '24': 'twenty-fourth', '25': 'twenty-fifth'}
season_ordinal2_dict = {'1': '1st', '2': '2nd', '3': '3rd', '4': '4th', '5': '5th', '6': '6th', '7': '7th', '8': '8th', '9': '9th', '10': '10th',
			'11': '11th', '12': '12th', '13': '13th', '14': '14th', '15': '15th', '16': '16th', '17': '17th', '18': '18th', '19': '19th',
			'20': '20th', '21': '21st', '22': '22nd', '23': '23rd', '24': '24th', '25': '25th'}

unwanted_tags = ('tamilrockers.com', 'www.tamilrockers.com', 'www.tamilrockers.ws', 'www.tamilrockers.pl',
			'www-tamilrockers-cl', 'www.tamilrockers.cl', 'www.tamilrockers.li', 'www-tamilrockers-tw',
			'www.tamilrockerrs.pl',
			'www.tamilmv.bid', 'www.tamilmv.biz', 'www.1tamilmv.org',
			'gktorrent-bz', 'gktorrent-com',
			'www.torrenting.com', 'www.torrenting.org', 'www-torrenting-com', 'www-torrenting-org',
			'katmoviehd.pw', 'katmoviehd-pw',
			'www.torrent9.nz', 'www-torrent9-uno', 'torrent9-cz', 'torrent9.cz', 'torrent9-red', 'torrent9-bz',
			'agusiq-torrents-pl',
			'oxtorrent-bz', 'oxtorrent-com', 'oxtorrent.com', 'oxtorrent-sh', 'oxtorrent-vc',
			'www.movcr.tv', 'movcr-com', 'www.movcr.to',
			'(imax)', 'imax',
			'xtorrenty.org', 'nastoletni.wilkoak', 'www.scenetime.com', 'kst-vn',
			'www.movierulz.vc', 'www-movierulz-ht', 'www.2movierulz.ac', 'www.2movierulz.ms',
			'www.3movierulz.com', 'www.3movierulz.tv', 'www.3movierulz.ws', 'www.3movierulz.ms',
			'www.7movierulz.pw', 'www.8movierulz.ws',
			'mkvcinemas.live', 'torrentcounter-to',
			'www.bludv.tv', 'ramin.djawadi', 'extramovies.casa', 'extramovies.wiki',
			'13+', '18+', 'taht.oyunlar', 'crazy4tv.com', 'karibu', '989pa.com',
			'best-torrents-net', '1-3-3-8.com', 'ssrmovies.club',
			'va:', 'zgxybbs-fdns-uk', 'www.tamilblasters.mx',
			'www.1tamilmv.work', 'www.xbay.me',
			'crazy4tv-com', '(es)')

home_getProperty = homeWindow.getProperty

def get_undesirables():
	if not getSetting('filter.undesirables') == 'true' or home_getProperty('fs_filterless_search') == 'true' : return []
	try: undesirables = Undesirables().get_enabled()
	except: undesirables = UNDESIRABLES
	return undesirables

def check_foreign_audio():
	return False if home_getProperty('fs_filterless_search') == 'true' else getSetting('filter.foreign.single.audio') == 'true'

def get_qual(term):
	if any(i in term for i in SCR): return 'SCR'
	elif any(i in term for i in CAM): return 'CAM'
	elif any(i in term for i in RES_720): return '720p'
	elif any(i in term for i in RES_1080): return '1080p'
	elif any(i in term for i in RES_4K): return '4K'
	elif '.hd.' in term: return '720p'
	else: return 'SD'

def get_release_quality(release_info, release_link=None):
	try:
		quality = None ; info = []
		if release_info: quality = get_qual(release_info)
		if not quality:
			if release_link:
				release_link = release_link.lower()
				quality = get_qual(release_link)
				if not quality: quality = 'SD'
			else: quality = 'SD'
		return quality, info
	except:
		from cocoscrapers.modules import log_utils
		log_utils.error()
		return 'SD', []

def aliases_to_array(aliases, filter=None):
	try:
		if all(isinstance(x, str) for x in aliases): return aliases
		if not filter: filter = []
		if isinstance(filter, str): filter = [filter]
		return [x.get('title') for x in aliases if not filter or x.get('country') in filter]
	except:
		from cocoscrapers.modules import log_utils
		log_utils.error()
		return []

def episodio_regex(season, episode, absolute=None):
	"""Il riconoscitore dell'episodio nel nome di una release: `SxxEyy` OPPURE il numero assoluto.

	Va passato a check_title al posto di `hdlr`, che lo usa gia' come espressione regolare (re.search e
	re.split). `hdlr` resta la stringa semplice `S23E23` per le query di ricerca e per info_from_name.

	Perche' serve (Fen Light, lotto 361, misurato il 25/09/2026 su One Piece S23E23 = episodio 1178):
	Torrentio, cercando per id, restituiva 45 file dell'episodio giusto e ne teneva 1; DMM 550 della
	stagione, 14 dell'episodio giusto, e ne teneva 1. Tutti gli altri si chiamano "One Piece - 1178",
	"One.Piece.EP1178", "One.Piece.S01E1178": le release anime numerano in assoluto, e il filtro
	pretendeva `S23E23` nel nome.

	Le forme dell'assoluto accettate, con il numero 1178:
	  "- 1178" "_1178_" ".1178." "E1178" "EP1178" "Episode 1178" "S01E1178" "S23E1178" "1178v2"
	(con la stagione, solo la 1 o quella cercata: Bleach S1E19 ha assoluto 19, e "Bleach S17E19" e' un
	altro episodio. Fino al 25/09 qualunque stagione passava, e la ricerca di S1E19 teneva S17E19.)
	e quelle rifiutate, che hanno generato falsi positivi o potrebbero farlo:
	  "1080p" (seguito da una lettera) "x264" "H.264" (codec) "[2094208A]" (codice esadecimale)
	  "1156-1180" (un intervallo: e' un pacchetto) e, sotto il 10, "2.0" "5.1" (canali audio): un
	  assoluto a una cifra deve avere lo zero davanti ("02").
	"""
	hdlr = 'S%02dE%02d' % (int(season), int(episode))
	# "S01EP58": la forma con EP, comune nelle release italiane, per TUTTE le serie (Fen Light, 25/09). Non la
	# prendeva nessuno: Fullmetal Alchemist Brotherhood S01EP58 non passava come episodio, e i suoi 64 fratelli
	# passavano come pacchetti di stagione (vedi filter_season_pack).
	con_ep = r'(?:%s|s0*%d[._ ]?ep[._ ]?0*%d(?![0-9]))' % (hdlr, int(season), int(episode))
	try: n = int(absolute)
	except (TypeError, ValueError): return con_ep
	if n <= 0: return con_ep
	num = ('0*%d' if n >= 10 else '0+%d') % n
	stagione_assoluta = r's0*(?:1|%d)[._ ]?e(?:p[._ ]?)?%s(?![0-9])' % (int(season), num)
	# Gli intervalli ("1156-1180", "1156 - 1180") si riconoscono dal NUMERO prima del trattino: un
	# trattino da solo non basta, "One Piece - 1178" ne ha uno ed e' la forma piu' comune.
	nudo = (r'(?<![a-z0-9])(?:ep?|episode)?[._ ]?'
			r'(?<![-~])(?<![hx][._ ])(?<!\d[-~][._ ])(?<!\d[._ ][-~][._ ])'
			r'%s(?:v\d)?(?![0-9a-z])(?![._ ]?[-~][._ ]?\d)' % num)
	return r'(?:%s|%s|%s)' % (con_ep, stagione_assoluta, nudo)

@lru_cache(maxsize=64)
def _titoli_check(title, aliases, year, years):
	"""Fen Light, lotto 412: i titoli di check_title preparati una volta per ricerca, non per ogni risultato (su 83.521 nomi veri
	check_title costava 10,7 s, 1,1 milioni di cleantitle.get). `aliases` e `years` come tuple. -> (titoli, puliti, pulito del
	titolo, espressioni dei titoli che valgono anche in testa al nome)."""
	title_list = []
	for item in aliases:
		try:
			alias = item.replace('&', 'and').replace(year, '')
			if years: # for movies only, scraper to pass None for episodes
				for i in years: alias = alias.replace(i, '')
			if alias in title_list: continue
			title_list.append(alias)
		except:
			from cocoscrapers.modules import log_utils
			log_utils.error()
	title = title.replace('&', 'and').replace(year, '') # year only in meta title if an addon custom query added it
	if title not in title_list: title_list.append(title)
	clean_titles = tuple(c for c in (cleantitle.get(i) for i in title_list) if c)
	clean_title = cleantitle.get(title)
	in_testa = tuple(re.compile(r'\s*%s(?:\s|[._\-\(\[\]/]|$)' % re.escape(i.strip()), re.I) for i in title_list if i and cleantitle.get(i) != clean_title)
	return tuple(title_list), clean_titles, clean_title, in_testa

def check_title(title, aliases, release_title, hdlr, year, years=None): # non pack file title check, single eps and movies
	if years: # for movies only, scraper to pass None for episodes
		if not any(value in release_title for value in years): return False
	else: 
		if not re.search(r'%s' % hdlr, release_title, re.I): return False
	try:
		title_list, clean_titles, clean_title, in_testa = _titoli_check(title, tuple(aliases_to_array(aliases) or ()), year, tuple(years) if years else None)
		release_title = re.sub(r'([(])(?=((19|20)[0-9]{2})).*?([)])', '\\2', release_title) #remove parenthesis only if surrounding a 4 digit date
		t = re.split(r'%s' % hdlr, release_title, 1, re.I)[0].replace(year, '').replace('&', 'and')
		if years:
			for i in years: t = t.split(i)[0]
		t = re.split(r'2160p|216op|4k|1080p|1o8op|108op|1o80p|720p|72op|480p|48op', t, 1, re.I)[0]
		cleantitle_t = cleantitle.get(t)
		if all(i != cleantitle_t for i in clean_titles):
			title_segments = []
			aka_segments = re.split(r'(?:^|[.\s_-]+)a\.?k\.?a\.?(?:[.\s_-]+|$)', t, flags=re.I)
			if len(aka_segments) > 1: title_segments.extend(aka_segments)
			title_segments.append(re.split(r'[\(\[]', t, 1)[0])
			title_segments.extend(re.findall(r'[\(\[]([^)\]]+)[\)\]]', t))
			segment_match = any(cleantitle.get(i) and cleantitle.get(i) in clean_titles for i in title_segments if i)
			start_match = any(e.match(t) for e in in_testa)
			if not segment_match and not start_match: return False

# filter to remove episode ranges that should be picked up in "filter_season_pack()" ex. "s01e01-08"
		if hdlr != year: # equal for movies but not for shows
			range_regex = (
					r's\d{1,3}e\d{1,3}[-.]e\d{1,3}',
					r's\d{1,3}e\d{1,3}[-.]\d{1,3}(?!p|bit|gb)(?!\d{1,3})',
					r's\d{1,3}[-.]e\d{1,3}[-.]e\d{1,3}',
					r'season[.-]?\d{1,3}[.-]?ep[.-]?\d{1,3}[-.]ep[.-]?\d{1,3}',
					r'season[.-]?\d{1,3}[.-]?episode[.-]?\d{1,3}[-.]episode[.-]?\d{1,3}',
					r's\d{1,3}x\d{1,3}[-]\d{1,3}(?!p|bit|gb)(?!\d{1,3})') # may need to add "to", "thru"
			for regex in range_regex:
				if bool(re.search(regex, release_title, re.I)): return False
		return True
	except:
		from cocoscrapers.modules import log_utils
		log_utils.error()
		return False

def remove_lang(release_info, check_foreign_audio):
	if not release_info: return False
	try:
		if any(value in release_info for value in DUBBED): return True
		if any(value in release_info for value in SUBS): return True
		if check_foreign_audio:
			if any(value in release_info for value in LANG) and not any(value in release_info for value in ENG_CHECK): return True
			if any(value in release_info for value in ABV_LANG) and not any(value in release_info for value in ENG_CHECK): return True
		if release_info.endswith('.srt.') and not any(value in release_info for value in SRT_CHECK): return True
		return False
	except:
		from cocoscrapers.modules import log_utils
		log_utils.error()
		return False

def remove_undesirables(release_info, undesirables):
	if any(value in release_info for value in undesirables): return True

def filter_season_pack(show_title, aliases, year, season, release_title):
	aliases = aliases_to_array(aliases)
	title_list = []
	title_list_append = title_list.append
	if aliases:
		for item in aliases:
			try:
				alias = item.replace('!', '').replace('(', '').replace(')', '').replace('&', 'and').replace(year, '')
				if alias in title_list: continue
				title_list_append(alias)
			except:
				from cocoscrapers.modules import log_utils
				log_utils.error()
	try:
		show_title = show_title.replace('!', '').replace('(', '').replace(')', '').replace('&', 'and').replace(year, '') # year only in meta title if an addon custom query added it
		if show_title not in title_list: title_list_append(show_title)

		season_fill = season.zfill(2)
		season_check = '.s%s.' % season
		season_fill_check = '.s%s.' % season_fill
		season_fill_checke = '.s%se' % season_fill # added 3/2/22 to pick up episode range packs ex "Reacher.s01e01-08"
		season_full_check = '.season.%s.' % season
		season_full_check_ns = '.season%s.' % season
		season_full_fill_check = '.season.%s.' % season_fill
		season_full_fill_check_ns = '.season%s.' % season_fill
		stagione_check = '.stagione.%s.' % season
		stagione_fill_check = '.stagione.%s.' % season_fill
		stagioni_check = '.stagioni.%s.' % season
		stagioni_fill_check = '.stagioni.%s.' % season_fill
		split_list = (season_check, season_fill_check, season_fill_checke, stagione_check, stagione_fill_check,
					  's%sx' % season, 's%sx' % season_fill,
					  '.' + season + '.season', 'total.season', 'stagioni', 'stagione', 'season',
					  'the.complete', 'complete', 'completa', 'completo', year)
		string_list = (season_check, season_fill_check, season_fill_checke, season_full_check, season_full_check_ns,
					   season_full_fill_check, season_full_fill_check_ns,
					   stagione_check, stagione_fill_check, stagioni_check, stagioni_fill_check)

		release_title = release_title_format(release_title)
		t = release_title.replace('-', '.')
		for i in split_list: t = t.split(i)[0]
		cleantitle_t = cleantitle.get(t)
		
		if all(cleantitle.get(x) != cleantitle_t for x in title_list): return False, 0, 0

# remove single episodes ONLY (returned in single ep scrape), keep episode ranges as season packs
		episode_regex = (
				r's\d{1,3}e\d{1,3}[-.](?!\d{2,3}[-.])(?!e\d{1,3})(?!\d{2}gb)',
				r's\d{1,3}x\d{1,3}[-.](?!\d{2,3}[-.])(?!\d{2}gb)',  # NxM single ep (e.g. 3x04)
				r'season[.-]?\d{1,3}[.-]?ep[.-]?\d{1,3}[-.](?!\d{2,3}[-.])(?!e\d{1,3})(?!\d{2}gb)',
				r'season[.-]?\d{1,3}[.-]?episode[.-]?\d{1,3}[-.](?!\d{2,3}[-.])(?!e\d{1,3})(?!\d{2}gb)',
				# Fen Light, 25/09: altre due forme dell'episodio SINGOLO che passavano per pacchetti di stagione.
				# Fullmetal Alchemist Brotherhood S1: 64 "pacchetti" DMM su 108 erano un file solo, "S01EP62" e
				# "S01E01v4". Gli intervalli con EP ("S01EP01-EP12") restano pacchetti: la guardia dopo il trattino.
				r's\d{1,3}ep\d{1,4}(?:v\d)?[-.](?!\d{2,4}[-.])(?!ep?\d{1,4})(?!\d{2}gb)',  # S01EP62
				r's\d{1,3}e\d{1,4}v\d[-.](?!\d{2,4}[-.])(?!e\d{1,4})')  # S01E01v4 (versione della release)
		for item in episode_regex:
			if bool(re.search(item, release_title)): return False, 0, 0

# return and identify episode ranges
		range_regex = (
				r's\d{1,3}e(\d{1,3})[-.]e(\d{1,3})',
				r's\d{1,3}e(\d{1,3})[-.](\d{1,3})(?!p|bit|gb)(?!\d{1,3})',
				r's\d{1,3}x(\d{1,3})-(\d{1,3})(?!p|bit|gb)(?!\d{1,3})',  # SxxXep-ep range (e.g. S03x01-14)
				r's\d{1,3}[-.]e(\d{1,3})[-.]e(\d{1,3})',
				r'season[.-]?\d{1,3}[.-]?ep[.-]?(\d{1,3})[-.]ep[.-]?(\d{1,3})',
				r'season[.-]?\d{1,3}[.-]?episode[.-]?\d{1,3}[-.]episode[.-]?\d{1,3}') # may need to add "to", "thru"
		for regex in range_regex:
			match = re.search(regex, release_title)
			if match:
				episode_start = int(match.group(1))
				episode_end = int(match.group(2))
				return True, episode_start, episode_end

# remove season ranges - returned in showPack scrape, plus non conforming season and specific crap
		rt = release_title.replace('-', '.')
		if any(i in rt for i in string_list):
			for item in (
				season_check.rstrip('.') + r'[.-]s([2-9]{1}|[1-3]{1}[0-9]{1})(?:[.-]|$)', # ex. ".s1-s9.", .s1-s39.
				season_fill_check.rstrip('.') + r'[.-]s\d{2}(?:[.-]|$)', # ".s01-s09.", .s01-s39.
				season_fill_check.rstrip('.') + r'[.-]\d{2}(?:[.-]|$)', # ".s01.09."
				r'\Ws\d{2}\W%s' % season_fill_check.lstrip('.'), # may need more reverse ranges
				season_full_check.rstrip('.') + r'[.-]to[.-]([2-9]{1}|[1-3]{1}[0-9]{1})(?:[.-]|$)', # ".season.1.to.9.", ".season.1.to.39"
				season_full_check.rstrip('.') + r'[.-]season[.-]([2-9]{1}|[1-3]{1}[0-9]{1})(?:[.-]|$)', # ".season.1.season.9.", ".season.1.season.39"
				season_full_check.rstrip('.') + r'[.-]([2-9]{1}|[1-3]{1}[0-9]{1})(?:[.-]|$)', # "season.1.9.", "season.1.39.
				season_full_check.rstrip('.') + r'[.-]\d{1}[.-]\d{1,2}(?:[.-]|$)', # "season.1.9.09."
				season_full_check.rstrip('.') + r'[.-]\d{3}[.-](?:19|20)[0-9]{2}(?:[.-]|$)', # single season followed by 3 digit followed by 4 digit year ex."season.1.004.1971"
				season_full_fill_check.rstrip('.') + r'[.-]\d{3}[.-]\d{3}(?:[.-]|$)', # 2 digit season followed by 3 digit dash range ex."season.10.001-025."
				season_full_fill_check.rstrip('.') + r'[.-]season[.-]\d{2}(?:[.-]|$)', # 2 digit season followed by 2 digit season range ex."season.01-season.09."
				stagione_check.rstrip('.') + r'[.-](?:stagion[ei]|s)[.-]?\d{1,2}(?:[.-]|$)', # ".stagione.3-stagione.4" or ".stagione.3.s4"
				stagione_check.rstrip('.') + r'[.-]([2-9]{1}|[1-3]{1}[0-9]{1})(?:[.-]|$)', # ".stagione.3.4."
				stagione_fill_check.rstrip('.') + r'[.-](?:stagion[ei]|s)[.-]?\d{2}(?:[.-]|$)',
				stagione_fill_check.rstrip('.') + r'[.-]\d{1,2}(?:[.-]|$)', # ".stagione.03.04."
					):
				if bool(re.search(item, release_title)): return False, 0, 0
			return True, 0, 0
		return False, 0, 0
	except:
		from cocoscrapers.modules import log_utils
		log_utils.error()
		return True

def filter_show_pack(show_title, aliases, imdb, year, season, release_title, total_seasons):
	aliases = aliases_to_array(aliases)
	title_list = []
	title_list_append = title_list.append
	if aliases:
		for item in aliases:
			try:
				alias = item.replace('!', '').replace('(', '').replace(')', '').replace('&', 'and').replace(year, '')
				if alias in title_list: continue
				title_list_append(alias)
			except:
				from cocoscrapers.modules import log_utils
				log_utils.error()
	try:
		show_title = show_title.replace('!', '').replace('(', '').replace(')', '').replace('&', 'and').replace(year, '') # year only in meta title if an addon custom query added it
		if show_title not in title_list: title_list_append(show_title)

		split_list = ('.all.seasons', 'stagioni', 'stagione', 'seasons', 'season', 'the.complete', 'complete',
					  'completa', 'completo', 'all.torrent', 'total.series', 'tv.series', 'series', 'edited', 's1', 's01', year)
		release_title = release_title_format(release_title)
		t = release_title.replace('-', '.')
		for i in split_list: t = t.split(i)[0]
		cleantitle_t = cleantitle.get(t)
		if all(cleantitle.get(x) != cleantitle_t for x in title_list): return False, 0

# remove single episodes(returned in single ep scrape)
		episode_regex = (
				r's\d{1,3}e\d{1,3}',
				r's[0-3]{1}[0-9]{1}[.-]e\d{1,2}',
				r's\d{1,3}[.-]\d{1,3}e\d{1,3}',
				r's\d{1,3}x\d{1,3}(?![-]\d)',  # NxM single ep, not a range like S03x01-14
				r'season[.-]?\d{1,3}[.-]?ep[.-]?\d{1,3}',
				r'season[.-]?\d{1,3}[.-]?episode[.-]?\d{1,3}')
		for item in episode_regex:
			if bool(re.search(item, release_title)):
				return False, 0

# detect season ranges (NxM or stagione/season N-M), accept only if target season is within range
		range_pattern = re.compile(
			r'(?:stagion[ei]|season|seasons|s)[.-]?(\d{1,2})(?:[.-]?(?:to|thru)[.-]?|-(?!\d+-))(?:stagion[ei]|season|seasons|s|)[.-]?(\d{1,2})(?!\d{2}p)',
			re.I)
		m_range = range_pattern.search(release_title)
		if m_range:
			start_s, end_s = int(m_range.group(1)), int(m_range.group(2))
			if not (start_s <= int(season) <= end_s):
				return False, 0
			return True, end_s

# remove single seasons - returned in seasonPack scrape
		season_regex = (
				r'season[.-]?([1-9]{1})[.-]0{1}\1[.-]?complete', # "season.1.01.complete" when 2nd number matches the fiirst group with leading 0
				r'season[.-]?([2-9]{1})[.-](?:[0-9]+)[.-]?complete', # "season.9.10.complete" when first number is >1 followed by 2 digit number
				r'season[.-]?\d{1,2}[.-]s\d{1,2}', # season.02.s02
				r'season[.-]?\d{1,2}[.-]complete', # season.02.complete
				r'season[.-]?\d{1,2}[.-]\d{3,4}p{0,1}', # "season.02.1080p" and no seperator "season02.1080p"
				r'season[.-]?\d{1,2}[.-](?!thru|to|\d{1,2}[.-])', # "season.02." or "season.1" not followed by "to", "thru", or another single or 2 digit number then a dot(which would be a range)
				r'season[.-]?\d{1,2}[.]?$', # end of line ex."season.1", "season.01", "season01" can also have trailing dot or end of line(dash would be a range)
				r'season[.-]?\d{1,2}[.-](?:19|20)[0-9]{2}', # single season followed by 4 digit year ex."season.1.1971", "season.01.1971", or "season01.1971"
				r'season[.-]?\d{1,2}[.-]\d{3}[.-]{1,2}(?:19|20)[0-9]{2}', # single season followed by 3 digits then 4 digit year ex."season.1.004.1971" or "season.01.004.1971" (comic book format)
				r'(?<!thru)(?<!to)(?<!\d{2})[.-]s\d{2}[.-]complete', # ".s01.complete" not preceded by "thru", "to", or 2 digit number
				r'(?<!thru)(?<!to)(?<!s\d{2})[.-]s\d{2}(?![.-]thru)(?![.-]to)(?![.-]s\d{2})(?![.-]\d{2}[.-])', # .s02. not preceded by "thru", "to", or "s01". Not followed by ".thru", ".to", ".s02", "-s02", ".02.", or "-02."
				r'stagion[ei][.-]?\d{1,2}[.-]completa',
				r'stagion[ei][.-]?\d{1,2}[.-]s\d{1,2}',
				r'stagion[ei][.-]?\d{1,2}[.-]\d{3,4}p{0,1}',
				r'stagion[ei][.-]?\d{1,2}[.-](?!thru|to|\d{1,2}[.-])',
				r'stagion[ei][.-]?\d{1,2}[.]?$',
				)
		for item in season_regex:
			if bool(re.search(item, release_title)):
				return False, 0


# remove spelled out single seasons
		season_regex = ()
		season_regex += tuple([r'complete[.-]%s[.-]season' % x for x in season_ordinal_list])
		season_regex += tuple([r'complete[.-]%s[.-]season' % x for x in season_ordinal2_list])
		season_regex += tuple([r'season[.-]%s' % x for x in season_list]) 
		for item in season_regex:
			if bool(re.search(item, release_title)):
				return False, 0


# from here down we don't filter out, we set and pass "last_season" it covers for the range and addon can filter it so the db will have full valid showPacks.
# set last_season for range type ex "1.2.3.4" or "1.2.3.and.4" (dots or dashes)
		dot_release_title = release_title.replace('-', '.')
		dot_season_ranges = []
		all_seasons = '1'
		season_count = 2
		while season_count <= int(total_seasons):
			dot_season_ranges.append(all_seasons + '.and.%s' % str(season_count))
			all_seasons += '.%s' % str(season_count)
			dot_season_ranges.append(all_seasons)
			season_count += 1
		if any(i in dot_release_title for i in dot_season_ranges):
			keys = [i for i in dot_season_ranges if i in dot_release_title]
			last_season = int(keys[-1].split('.')[-1])
			return True, last_season



# "1.to.9" type range filter (dots or dashes)
		to_season_ranges = []
		start_season = '1'
		season_count = 2
		while season_count <= int(total_seasons):
			to_season_ranges.append(start_season + '.to.%s' % str(season_count))
			season_count += 1
		if any(i in dot_release_title for i in to_season_ranges):
			keys = [i for i in to_season_ranges if i in dot_release_title]
			last_season = int(keys[0].split('to.')[1])
			return True, last_season

# "1.thru.9" range filter (dots or dashes)
		thru_ranges = [i.replace('to', 'thru') for i in to_season_ranges]
		if any(i in dot_release_title for i in thru_ranges):
			keys = [i for i in thru_ranges if i in dot_release_title]
			last_season = int(keys[0].split('thru.')[1])
			return True, last_season

# "1-9" range filter
		dash_ranges = [i.replace('.to.', '-') for i in to_season_ranges]
		if any(i in release_title for i in dash_ranges):
			keys = [i for i in dash_ranges if i in release_title]
			last_season = int(keys[0].split('-')[1])
			return True, last_season

# "1~9" range filter
		tilde_ranges = [i.replace('.to.', '~') for i in to_season_ranges]
		if any(i in release_title for i in tilde_ranges):
			keys = [i for i in tilde_ranges if i in release_title]
			last_season = int(keys[0].split('~')[1])
			return True, last_season



# "01.to.09" 2 digit range filter (dots or dashes)
		to_season_ranges = []
		start_season = '01'
		season_count = 2
		while season_count <= int(total_seasons):
			to_season_ranges.append(start_season + '.to.%s' % '0' + str(season_count) if int(season_count) < 10 else start_season + '.to.%s' % str(season_count))
			season_count += 1
		if any(i in dot_release_title for i in to_season_ranges):
			keys = [i for i in to_season_ranges if i in dot_release_title]
			last_season = int(keys[0].split('to.')[1])
			return True, last_season

# "01.thru.09" 2 digit range filter (dots or dashes)
		thru_ranges = [i.replace('to', 'thru') for i in to_season_ranges]
		if any(i in dot_release_title for i in thru_ranges):
			keys = [i for i in thru_ranges if i in dot_release_title]
			last_season = int(keys[0].split('thru.')[1])
			return True, last_season

# "01-09" 2 digit range filtering
		dash_ranges = [i.replace('.to.', '-') for i in to_season_ranges]
		if any(i in release_title for i in dash_ranges):
			keys = [i for i in dash_ranges if i in release_title]
			last_season = int(keys[0].split('-')[1])
			return True, last_season

# "01~09" 2 digit range filtering
		tilde_ranges = [i.replace('.to.', '~') for i in to_season_ranges]
		if any(i in release_title for i in tilde_ranges):
			keys = [i for i in tilde_ranges if i in release_title]
			last_season = int(keys[0].split('~')[1])
			return True, last_season



# "s1.to.s9" single digit range filter (dots or dashes)
		to_season_ranges = []
		start_season = 's1'
		season_count = 2
		while season_count <= int(total_seasons):
			to_season_ranges.append(start_season + '.to.s%s' % str(season_count))
			season_count += 1
		if any(i in dot_release_title for i in to_season_ranges):
			keys = [i for i in to_season_ranges if i in dot_release_title]
			last_season = int(keys[0].split('to.s')[1])
			return True, last_season

# "s1.thru.s9" single digit range filter (dots or dashes)
		thru_ranges = [i.replace('to', 'thru') for i in to_season_ranges]
		if any(i in dot_release_title for i in thru_ranges):
			keys = [i for i in thru_ranges if i in dot_release_title]
			last_season = int(keys[0].split('thru.s')[1])
			return True, last_season

# "s1-s9" single digit range filtering (dashes)
		dash_ranges = [i.replace('.to.', '-') for i in to_season_ranges]
		if any(i in release_title for i in dash_ranges):
			keys = [i for i in dash_ranges if i in release_title]
			last_season = int(keys[0].split('-s')[1])
			return True, last_season

# "s1~s9" single digit range filtering (dashes)
		tilde_ranges = [i.replace('.to.', '~') for i in to_season_ranges]
		if any(i in release_title for i in tilde_ranges):
			keys = [i for i in tilde_ranges if i in release_title]
			last_season = int(keys[0].split('~s')[1])
			return True, last_season



# "s01.to.s09"  2 digit range filter (dots or dash)
		to_season_ranges = []
		start_season = 's01'
		season_count = 2
		while season_count <= int(total_seasons):
			to_season_ranges.append(start_season + '.to.s%s' % '0' + str(season_count) if int(season_count) < 10 else start_season + '.to.s%s' % str(season_count))
			season_count += 1
		if any(i in dot_release_title for i in to_season_ranges):
			keys = [i for i in to_season_ranges if i in dot_release_title]
			last_season = int(keys[0].split('to.s')[1])
			return True, last_season

# "s01.thru.s09" 2 digit  range filter (dots or dashes)
		thru_ranges = [i.replace('to', 'thru') for i in to_season_ranges]
		if any(i in dot_release_title for i in thru_ranges):
			keys = [i for i in thru_ranges if i in dot_release_title]
			last_season = int(keys[0].split('thru.s')[1])
			return True, last_season

# "s01-s09" 2 digit  range filtering (dashes)
		dash_ranges = [i.replace('.to.', '-') for i in to_season_ranges]
		if any(i in release_title for i in dash_ranges):
			keys = [i for i in dash_ranges if i in release_title]
			last_season = int(keys[0].split('-s')[1])
			return True, last_season

# "s01~s09" 2 digit  range filtering (dashes)
		tilde_ranges = [i.replace('.to.', '~') for i in to_season_ranges]
		if any(i in release_title for i in tilde_ranges):
			keys = [i for i in tilde_ranges if i in release_title]
			last_season = int(keys[0].split('~s')[1])
			return True, last_season

# "s01.s09" 2 digit  range filtering (dots)
		dot_ranges = [i.replace('.to.', '.') for i in to_season_ranges]
		if any(i in release_title for i in dot_ranges):
			keys = [i for i in dot_ranges if i in release_title]
			last_season = int(keys[0].split('.s')[1])
			return True, last_season

		return True, total_seasons
	except:
		from cocoscrapers.modules import log_utils
		log_utils.error()
		# return True, total_seasons

def info_from_name(release_title, title, year, hdlr=None, episode_title=None, season=None, pack=None):
	try:
		release_title = release_title.lower().replace('&', 'and').replace("'", "")
		release_title = re.sub(r'[^a-z0-9]+', '.', release_title)
		title = title.lower().replace('&', 'and').replace("'", "")
		title = re.sub(r'[^a-z0-9]+', '.', title)
		name_info = release_title.replace(title, '').replace(year, '')
		if hdlr: name_info = name_info.replace(hdlr.lower(), '')
		if episode_title:
			episode_title = episode_title.lower().replace('&', 'and').replace("'", "")
			episode_title = re.sub(r'[^a-z0-9]+', '.', episode_title)
			name_info = name_info.replace(episode_title, '')
		if pack:
			if pack == 'season':
				season_fill = season.zfill(2)
				str1_replace = ('.s%s' % season, '.s%s' % season_fill, '.season.%s' % season, '.season%s' % season, '.season.%s' % season_fill, '.season%s' % season_fill, 'complete')
				for i in str1_replace: name_info = name_info.replace(i, '')
			elif pack == 'show':
				str2_replace = ('.all.seasons', 'seasons', 'season', 'the.complete', 'complete', 'all.torrent', 'total.series', 'tv.series', 'series', 'edited', 's1', 's01')
				for i in str2_replace: name_info = name_info.replace(i, '')
		name_info = name_info.lstrip('.').rstrip('.')
		name_info = '.%s.' % name_info
		return name_info
	except:
		from cocoscrapers.modules import log_utils
		log_utils.error()
		return release_title

def release_title_format(release_title):
	try:
		release_title = release_title.lower().replace("'", "").lstrip('.').rstrip('.')
		fmt = '.%s.' % re.sub(r'[^a-z0-9-~]+', '.', release_title).replace('.-.', '-').replace('-.', '-').replace('.-', '-').replace('--', '-')
		return fmt
	except:
		from cocoscrapers.modules import log_utils
		log_utils.error()
		return release_title

def clean_name(release_title):
	try:
		release_title = re.sub(r'【.*?】', '', release_title)
		# Fen Light, lotto 387: le lettere di ogni scrittura restano. Prima strip_non_ascii_and_unprintable toglieva tutto
		# cio' che non era ASCII: "Сталкер 1979" arrivava come "1979", "Kraina Bogów" come "Kraina Bogw", "우영우 E01~E10" come
		# "E01~E10", e il setaccio degli episodi scartava le release coreane e cinesi prima della cache (prova del 27/09).
		# Si tolgono solo i caratteri di controllo; la larghezza piena si normalizza (NFKC: "ＳＰＹ" = "SPY"), ogni spazio
		# (anche quello ideografico) diventa un punto come prima.
		release_title = re.sub(r'\s', '.', solo_stampabili(release_title)).lstrip('+.-:/')
		releasetitle_startswith = release_title.lower().startswith
		if releasetitle_startswith('rifftrax'): return release_title # removed by "undesirables" anyway so exit
		for i in unwanted_tags:
			if releasetitle_startswith(i):
				#release_title = re.sub(r'^%s' % i.replace('+', '\+'), '', release_title, 1, re.I)
				release_title = re.sub(r'^%s' % re.escape(i), '', release_title, 1, re.I)
		release_title = release_title.lstrip('+.-:/ ')
		release_title = re.sub(r'^\[.*?]', '', release_title, 1, re.I)
		release_title = release_title.lstrip('.-[](){}:/')
		return release_title
	except:
		from cocoscrapers.modules import log_utils
		log_utils.error()
		return release_title

def ripara_codifica(text):
	"""Fen Light, lotto 387: l'UTF-8 letto come cp1252 ("ÐŸÐ°Ñ€Ð°Ð½Ð¾Ñ€Ð¼Ð°Ð»ÑŒÐ½Ð¾Ðµ" = "Паранормальное", nomi di DMM). Si ripara
	solo se i byte si rileggono come UTF-8 senza errori (un nome troncato perde solo l'ultima lettera): "São" resta com'e'."""
	if not text or not re.search(r'[ÂÃÐÑ][\u0080-\u00bf\u0152-\u2122]', text): return text
	b = bytearray()
	for c in text.replace('\ufffd', ''):
		if ord(c) < 256: b.append(ord(c))
		else:
			try: b += c.encode('cp1252')
			except UnicodeEncodeError: return text
	try: return b.decode('utf-8')
	except UnicodeDecodeError as e:
		if e.start < len(b) - 3: return text
		try: return b[:e.start].decode('utf-8')
		except UnicodeDecodeError: return text

def solo_stampabili(text):
	"""Fen Light, lotto 387: il testo senza caratteri di controllo (categorie Unicode C*), in forma NFKC, con la codifica
	riparata (ripara_codifica) prima della normalizzazione."""
	from unicodedata import normalize, category
	return ''.join(c for c in normalize('NFKC', ripara_codifica(text or '')) if not category(c).startswith('C'))

def strip_non_ascii_and_unprintable(text):
	try:
		result = ''.join(char for char in text if char in printable)
		return result.encode('ascii', errors='ignore').decode('ascii', errors='ignore')
	except:
		from cocoscrapers.modules import log_utils
		log_utils.error()
		return text

def _size(siz):
	try:
		if siz in ('0', 0, '', None): return 0, ''
		div = 1 if siz.lower().endswith(('gb', 'gib')) else 1024
		# if ',' in siz and siz.lower().endswith(('mb', 'mib')): siz = size.replace(',', '')
		# elif ',' in siz and siz.lower().endswith(('gb', 'gib')): siz = size.replace(',', '.')
		dec_count = len(re.findall(r'[.]', siz))
		if dec_count == 2: siz = siz.replace('.', ',', 1) # torrentproject2 likes to randomly use 2 decimals vs. a comma then a decimal
		float_size = round(float(re.sub(r'[^0-9|/.|/,]', '', siz.replace(',', ''))) / div, 2) #comma issue where 2,750 MB or 2,75 GB (sometimes replace with "." and sometimes not)
		str_size = '%.2f GB' % float_size
		return float_size, str_size
	except:
		from cocoscrapers.modules import log_utils
		log_utils.error('failed on siz=%s' % siz)
		return 0, ''

def convert_size(size_bytes, to='GB'):
	try:
		import math
		if size_bytes == 0: return 0, ''
		power = {'B' : 0, 'KB': 1, 'MB' : 2, 'GB': 3, 'TB' : 4, 'EB' : 5, 'ZB' : 6, 'YB': 7}
		i = power[to]
		p = math.pow(1024, i)
		float_size = round(size_bytes / p, 2)
		# if to == 'B' or to  == 'KB': return 0, ''
		str_size = "%s %s" % (float_size, to)
		return float_size, str_size
	except:
		from cocoscrapers.modules import log_utils
		log_utils.error()
		return 0, ''

def base32_to_hex(hash, caller):
	from base64 import b32decode
	from cocoscrapers.modules import log_utils
	hex = b32decode(hash).hex()
	log_utils.log('%s: base32 hash  "%s"  converted to hex 40  "%s" ' % (caller, hash, hex), __name__, log_utils.LOGDEBUG)
	return hex

def scraper_error(provider):
	import traceback
	from cocoscrapers.modules import log_utils
	failure = traceback.format_exc()
	log_utils.log(provider.upper() + ' - Exception: \n' + str(failure), caller='scraper_error', level=log_utils.LOGERROR)

def is_host_valid(url, domains):
	try:
		if any(x in url.lower() for x in ('.rar.', '.zip.', '.part.', '.sample.')) or any(url.lower().endswith(x) for x in ('.bmp', '.gif', '.jpg', '.nfo', '.part', '.png', '.rar', '.sample.', '.srt', '.txt', '.zip')):
			return False, ''
		host = __top_domain(url)
		hosts = [domain.lower() for domain in domains if host and host in domain.lower()]
		if hosts and '.' not in host: host = hosts[0]
		if hosts and any([h for h in ('google', 'picasa', 'blogspot') if h in host]): host = 'gvideo'
		if hosts and any([h for h in ('akamaized', 'ocloud') if h in host]): host = 'CDN'
		return any(hosts), host
	except:
		from cocoscrapers.modules import log_utils
		log_utils.error()
		return False, ''

def __top_domain(url):
	from urllib.parse import urlparse
	try:
		elements = urlparse(url)
		domain = elements.netloc or elements.path
		domain = domain.split('@')[-1].split(':')[0]
		regex = r"(?:www\.)?([\w\-]*\.[\w\-]{2,3}(?:\.[\w\-]{2,3})?)$"
		res = re.search(regex, domain)
		if res: domain = res.group(1)
		domain = domain.lower()
		return domain
	except:
		from cocoscrapers.modules import log_utils
		log_utils.error()

def copy2clip(txt):
	from sys import platform as sys_platform
	platform = sys_platform
	if platform == "win32":
		try:
			from subprocess import check_call
			# cmd = "echo " + txt.strip() + "|clip"
			cmd = "echo " + txt.replace('&', '^&').strip() + "|clip" # "&" is a command seperator
			return check_call(cmd, shell=True)
		except:
			from cocoscrapers.modules import log_utils
			log_utils.error('Windows: Failure to copy to clipboard')
	elif platform == "darwin":
		try:
			from subprocess import check_call
			cmd = "echo " + txt.strip() + "|pbcopy"
			return check_call(cmd, shell=True)
		except:
			from cocoscrapers.modules import log_utils
			log_utils.error('Mac: Failure to copy to clipboard')
	elif platform == "linux":
		try:
			from subprocess import Popen, PIPE
			p = Popen(["xsel", "-pi"], stdin=PIPE)
			p.communicate(input=txt)
		except:
			from cocoscrapers.modules import log_utils
			log_utils.error('Linux: Failure to copy to clipboard')
