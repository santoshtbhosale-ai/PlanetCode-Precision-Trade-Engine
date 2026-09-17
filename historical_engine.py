import time
from datetime import datetime, timedelta
from statistics import mean

import requests

from config import *


class HistoricalValidationEngine:
    """Validates the underlying directional setup against recent Dhan 5-minute history.

    This is deliberately a validation layer, not an option-profit predictor. It measures
    whether similar underlying conditions reached a target before a stop. Option Greeks,
    spread and premium behaviour are still validated separately by the live engine.
    """

    def __init__(self):
        self.cache = {}
        self.session = requests.Session()

    def _post(self, payload):
        if not DHAN_ACCESS_TOKEN:
            raise RuntimeError('Dhan access token missing')
        r = self.session.post(
            'https://api.dhan.co/v2/charts/intraday',
            headers={'Content-Type': 'application/json', 'Accept': 'application/json', 'access-token': DHAN_ACCESS_TOKEN},
            json=payload,
            timeout=25,
        )
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and str(data.get('status', '')).lower() == 'failure':
            raise RuntimeError(data.get('remarks') or data.get('message') or str(data))
        return data.get('data', data)

    def _load(self, sid, days=60):
        key = (sid, days)
        old = self.cache.get(key)
        if old and time.time() - old[0] < 900:
            return old[1]
        now = datetime.now()
        start = now - timedelta(days=days)
        data = self._post({
            'securityId': str(sid),
            'exchangeSegment': UNDERLYING_SEGMENT,
            'instrument': 'INDEX',
            'interval': '5',
            'oi': False,
            'fromDate': start.strftime('%Y-%m-%d %H:%M:%S'),
            'toDate': now.strftime('%Y-%m-%d %H:%M:%S'),
        })
        c = [float(x) for x in data.get('close', [])]
        h = [float(x) for x in data.get('high', [])]
        l = [float(x) for x in data.get('low', [])]
        ts = [int(x) for x in data.get('timestamp', [])]
        n = min(len(c), len(h), len(l), len(ts))
        rows = [{'c': c[i], 'h': h[i], 'l': l[i], 'ts': ts[i]} for i in range(n)]
        self.cache[key] = (time.time(), rows)
        return rows

    @staticmethod
    def _ema(values, p):
        if not values:
            return 0.0
        alpha = 2 / (p + 1)
        e = values[0]
        for x in values[1:]:
            e = alpha * x + (1 - alpha) * e
        return e

    @staticmethod
    def _atr(rows, p=14):
        if len(rows) < 2:
            return 0.0
        tr=[]
        for i in range(1, len(rows)):
            r=rows[i]; prev=rows[i-1]['c']
            tr.append(max(r['h']-r['l'], abs(r['h']-prev), abs(r['l']-prev)))
        x=tr[-p:]
        return mean(x) if x else 0.0

    @staticmethod
    def _rsi(closes, p=14):
        if len(closes) <= p:
            return 50.0
        g=[]; loss=[]
        for i in range(len(closes)-p, len(closes)):
            d=closes[i]-closes[i-1]
            g.append(max(d,0)); loss.append(max(-d,0))
        ag=mean(g); al=mean(loss)
        if al == 0:
            return 100.0 if ag else 50.0
        return 100 - 100/(1+ag/al)

    def _features(self, rows, i):
        w=rows[max(0,i-40):i+1]
        closes=[x['c'] for x in w]
        e9=self._ema(closes[-25:],9); e21=self._ema(closes[-40:],21)
        mom=(closes[-1]-closes[max(0,len(closes)-7)])/closes[max(0,len(closes)-7)]*100 if len(closes)>7 else 0
        atr=self._atr(w)
        # Session VWAP is approximated from the current day's 5m bars.
        day=datetime.fromtimestamp(rows[i]['ts']).date()
        d=[x for x in rows[:i+1] if datetime.fromtimestamp(x['ts']).date()==day]
        tv=0.0; pv=0.0
        for x in d:
            q=max(x['h']-x['l'], 1.0)
            pv += ((x['h']+x['l']+x['c'])/3)*q; tv += q
        vwap=pv/tv if tv else rows[i]['c']
        c=rows[i]['c']
        return {'spot':c,'ema9':e9,'ema21':e21,'vwap':vwap,'mom':mom,'rsi':self._rsi(closes),'atr':atr}

    @staticmethod
    def _similar(cur, hist, side):
        # Similarity deliberately uses normalized features, avoiding look-ahead.
        want_bull = side == 'CE'
        cur_sep=(cur['ema9']-cur['ema21'])/max(cur['spot'],1)*100
        h_sep=(hist['ema9']-hist['ema21'])/max(hist['spot'],1)*100
        if want_bull:
            if not (hist['spot'] > hist['vwap'] and hist['ema9'] > hist['ema21'] and hist['mom'] > 0): return False
        else:
            if not (hist['spot'] < hist['vwap'] and hist['ema9'] < hist['ema21'] and hist['mom'] < 0): return False
        return abs(h_sep-cur_sep) <= 0.10 and abs(hist['rsi']-cur['rsi']) <= 16 and abs(hist['mom']-cur['mom']) <= 0.30

    def validate(self, sid, current, side, days=60):
        try:
            rows=self._load(sid, days)
            if len(rows) < 300:
                return {'available':False,'reason':'not enough historical candles','samples':0,'hit_rate':None}
            matches=[]
            # Sample every 5m bar after sufficient warm-up. Exclude the last 12 bars so outcome is complete.
            for i in range(80, len(rows)-13):
                hf=self._features(rows,i)
                if not self._similar(current,hf,side):
                    continue
                atr=max(hf['atr'], 0.001)
                entry=hf['spot']; stop=entry-atr if side=='CE' else entry+atr; target=entry+atr if side=='CE' else entry-atr
                outcome='NEUTRAL'
                for j in range(i+1,min(i+13,len(rows))):
                    r=rows[j]
                    hit_t = r['h']>=target if side=='CE' else r['l']<=target
                    hit_s = r['l']<=stop if side=='CE' else r['h']>=stop
                    if hit_t and hit_s:
                        # Conservative if both occur inside the same candle.
                        outcome='STOP_FIRST'
                        break
                    if hit_t:
                        outcome='TARGET'
                        break
                    if hit_s:
                        outcome='STOP_FIRST'
                        break
                if outcome!='NEUTRAL':
                    matches.append(outcome)
                if len(matches)>=80:
                    break
            if not matches:
                return {'available':True,'reason':'no sufficiently similar completed setups','samples':0,'hit_rate':None}
            wins=sum(x=='TARGET' for x in matches)
            rate=round(wins/len(matches)*100,1)
            return {'available':True,'samples':len(matches),'wins':wins,'losses':len(matches)-wins,'hit_rate':rate,
                    'threshold':HISTORICAL_MIN_HIT_RATE,'qualified':len(matches)>=HISTORICAL_MIN_SAMPLES and rate>=HISTORICAL_MIN_HIT_RATE,
                    'reason':'historical directional validation only; not option P&L'}
        except Exception as e:
            return {'available':False,'reason':str(e)[:180],'samples':0,'hit_rate':None}
