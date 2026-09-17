import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import requests

from config import *


class NewsContext:
    """Lightweight headline-risk context. It never creates a trade by itself."""
    def __init__(self):
        self.cache={}
        self.session=requests.Session()

    def _fetch(self, symbol):
        q=quote_plus(f'{symbol} NIFTY OR BANK NIFTY India markets')
        url=f'https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en'
        r=self.session.get(url,timeout=8,headers={'User-Agent':'Mozilla/5.0'})
        r.raise_for_status()
        root=ET.fromstring(r.text)
        out=[]
        now=time.time()
        for item in root.findall('.//item')[:20]:
            title=(item.findtext('title') or '').strip()
            pub=item.findtext('pubDate') or ''
            try: age=(now-parsedate_to_datetime(pub).timestamp())/3600
            except Exception: age=999
            if age<=NEWS_MAX_AGE_HOURS:
                out.append({'title':title,'age_hours':round(max(age,0),1)})
        return out

    def get(self,symbol):
        key=symbol.upper(); old=self.cache.get(key)
        if old and time.time()-old[0]<300: return old[1]
        try:
            headlines=self._fetch(key)
            positive=('bullish','surge','rally','growth','easing','strong','beats','inflow','record high')
            negative=('bearish','fall','falls','crash','war','shock','inflation','rate hike','selloff','geopolitical','weak','outflow')
            pos=sum(any(k in h['title'].lower() for k in positive) for h in headlines)
            neg=sum(any(k in h['title'].lower() for k in negative) for h in headlines)
            risk=any(k in h['title'].lower() for h in headlines for k in ('war','crash','shock','rate hike','geopolitical'))
            bias='BULLISH' if pos>neg else 'BEARISH' if neg>pos else 'MIXED/NEUTRAL'
            result={'available':True,'bias':bias,'risk_flag':risk,'headlines':headlines[:5],'positive_count':pos,'negative_count':neg}
        except Exception as e:
            result={'available':False,'bias':'UNKNOWN','risk_flag':False,'headlines':[],'reason':str(e)[:160]}
        self.cache[key]=(time.time(),result)
        return result
