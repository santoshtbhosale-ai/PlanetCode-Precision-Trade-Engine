import csv
import io
import json
import struct
import threading
import time
from datetime import datetime

import requests

from config import *

try:
    import websocket
except Exception:
    websocket = None


class DhanService:
    def __init__(self):
        self.s = requests.Session()
        self.cache = {}
        self.master_cache = None
        self.live = {}
        self.ws = None
        self.ws_thread = None
        self.ws_stop = threading.Event()
        self.ws_status = 'DISABLED'
        self.last_ws_error = ''
        if self.configured() and WEBSOCKET_ENABLED and websocket:
            self.start_websocket()

    def configured(self):
        return bool(DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN)

    def headers(self):
        return {'Content-Type':'application/json','Accept':'application/json','access-token':DHAN_ACCESS_TOKEN,'client-id':DHAN_CLIENT_ID}

    def post(self, path, payload):
        if not self.configured():
            raise RuntimeError('Dhan credentials are missing in .env')
        last = None
        for attempt in range(3):
            try:
                r = self.s.post('https://api.dhan.co/v2' + path, headers=self.headers(), json=payload, timeout=20)
                if r.status_code == 429:
                    time.sleep(3 * (attempt + 1)); continue
                r.raise_for_status()
                data = r.json()
                if isinstance(data, dict) and str(data.get('status','')).lower() == 'failure':
                    raise RuntimeError(data.get('remarks') or data.get('message') or str(data))
                return data
            except Exception as e:
                last = e
                time.sleep(attempt + 1)
        raise RuntimeError(f'Dhan request failed: {last}')

    def expiry(self, sid):
        vals = self.post('/optionchain/expirylist', {'UnderlyingScrip':sid,'UnderlyingSeg':UNDERLYING_SEGMENT}).get('data', [])
        today = datetime.now().date()
        future = []
        for value in vals:
            try:
                d = datetime.strptime(str(value), '%Y-%m-%d').date()
                if d >= today: future.append(d)
            except Exception:
                continue
        if not future: raise RuntimeError('No future expiry returned by Dhan.')
        return min(future).isoformat()

    def chain(self, sid, exp):
        key = (sid, exp)
        old = self.cache.get(key)
        if old and time.time() - old[0] < OPTION_CHAIN_CACHE_SECONDS:
            return old[1]
        data = self.post('/optionchain', {'UnderlyingScrip':sid,'UnderlyingSeg':UNDERLYING_SEGMENT,'Expiry':exp})
        self.cache[key] = (time.time(), data)
        return data

    @staticmethod
    def _ema(values, period):
        if not values: return 0.0
        period = min(period, len(values))
        out = values[0]
        alpha = 2 / (period + 1)
        for x in values[1:]: out = alpha * x + (1 - alpha) * out
        return out

    @staticmethod
    def _atr(high, low, close, period=14):
        if len(close) < 2: return 0.0
        trs=[]
        for i in range(1, len(close)):
            trs.append(max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1])))
        vals = trs[-period:]
        return sum(vals)/len(vals) if vals else 0.0

    @staticmethod
    def _rsi(close, period=14):
        if len(close) <= period: return 50.0
        gains=[]; losses=[]
        for i in range(len(close)-period, len(close)):
            delta=close[i]-close[i-1]
            gains.append(max(delta,0)); losses.append(max(-delta,0))
        ag=sum(gains)/period; al=sum(losses)/period
        if al == 0: return 100.0 if ag else 50.0
        return 100 - (100/(1+ag/al))

    def candles(self, sid):
        now = datetime.now()
        start = now.replace(hour=9, minute=15, second=0, microsecond=0)
        data = self.post('/charts/intraday', {'securityId':str(sid),'exchangeSegment':UNDERLYING_SEGMENT,'instrument':'INDEX','interval':'1','oi':False,'fromDate':start.strftime('%Y-%m-%d %H:%M:%S'),'toDate':now.strftime('%Y-%m-%d %H:%M:%S')})
        x=data.get('data',data)
        c=[float(v) for v in x.get('close',[])]; h=[float(v) for v in x.get('high',[])]; l=[float(v) for v in x.get('low',[])]; vol=[float(v) for v in (x.get('volume',[]) or [])]
        if not c: raise RuntimeError('No intraday candles returned.')
        n=len(c); h=(h[-n:] if h else c); l=(l[-n:] if l else c); vol=(vol[-n:] if vol else [0]*n)
        tv=sum(vol); vwap=sum(((a+b+z)/3)*q for a,b,z,q in zip(h,l,c,vol))/tv if tv else c[-1]
        recent=c[-30:]; mom=((recent[-1]-recent[0])/recent[0]*100) if len(recent)>1 and recent[0] else 0
        atr=self._atr(h,l,c,14)
        avg_vol=sum(vol[-20:])/max(1,min(20,len(vol)))
        last_vol=vol[-1] if vol else 0
        prev_high=max(h[-21:-1]) if len(h)>2 else h[-2]
        prev_low=min(l[-21:-1]) if len(l)>2 else l[-2]
        opening_range_high=max(h[:min(15,n)])
        opening_range_low=min(l[:min(15,n)])
        ema9=self._ema(c[-100:],9); ema21=self._ema(c[-100:],21)
        ema9_prev=self._ema(c[-101:-1],9) if len(c)>101 else ema9
        ema21_prev=self._ema(c[-101:-1],21) if len(c)>101 else ema21
        return {
            'spot':c[-1],'ema9':ema9,'ema21':ema21,'ema9_prev':ema9_prev,'ema21_prev':ema21_prev,'vwap':vwap,
            'prev_high':prev_high,'prev_low':prev_low,'opening_range_high':opening_range_high,'opening_range_low':opening_range_low,
            'candles':n,'session_open':c[0],'short_momentum_pct':mom,'atr':atr,'rsi':self._rsi(c),
            'last_volume':last_vol,'avg_volume20':avg_vol,'volume_ratio':last_vol/avg_vol if avg_vol else 1,
            'recent_closes':c[-30:],'recent_highs':h[-30:],'recent_lows':l[-30:],'data_time':now.isoformat(timespec='seconds')
        }

    def parse(self, d):
        x=d.get('data',d); spot=float(x.get('last_price') or 0); oc=x.get('oc',{}) or {}
        if not oc: return spot,[]
        strikes=sorted(float(k) for k in oc); atm=min(strikes,key=lambda z:abs(z-spot)); i=strikes.index(atm)
        rows=[]
        for st in strikes[max(0,i-OPTION_STRIKE_RANGE):i+OPTION_STRIKE_RANGE+1]:
            node=oc.get(str(st)) or oc.get(f'{st:.6f}') or {}
            for typ,key in (('CE','ce'),('PE','pe')):
                q=node.get(key)
                if not q: continue
                greeks=q.get('greeks') if isinstance(q.get('greeks'),dict) else {}
                ltp=float(q.get('last_price') or 0); bid=float(q.get('top_bid_price') or 0); ask=float(q.get('top_ask_price') or 0)
                prev=float(q.get('previous_close_price') or 0); pv=float(q.get('previous_volume') or 0); vol=float(q.get('volume') or 0)
                oi=float(q.get('oi') or 0); poi=float(q.get('previous_oi') or 0); iv=float(q.get('implied_volatility') or q.get('iv') or 0)
                delta=float(greeks.get('delta') or 0); theta=float(greeks.get('theta') or 0); gamma=float(greeks.get('gamma') or 0); vega=float(greeks.get('vega') or 0)
                mid=(bid+ask)/2 if bid and ask else ltp
                rows.append({'strike':st,'option_type':typ,'ltp':ltp,'bid':bid,'ask':ask,'momentum':(ltp-prev)/prev if prev else 0,
                             'volume_ratio':vol/pv if pv else 1,'oi_change_pct':(oi-poi)/poi*100 if poi else 0,
                             'spread_pct':(ask-bid)/mid*100 if mid>0 and ask>=bid else 99,'iv':iv,'delta':delta,'theta':theta,'gamma':gamma,'vega':vega,
                             'security_id':q.get('security_id'),'symbol':q.get('custom_symbol') or q.get('trading_symbol'),'volume':vol,'oi':oi,'previous_oi':poi})
        return spot,rows

    def start_websocket(self):
        if self.ws_thread and self.ws_thread.is_alive(): return
        self.ws_stop.clear(); self.ws_thread=threading.Thread(target=self._ws_loop,daemon=True,name='dhan-feed'); self.ws_thread.start()

    def _ws_loop(self):
        if not websocket:
            self.ws_status='DISABLED'; return
        url=f'wss://api-feed.dhan.co?version=2&token={DHAN_ACCESS_TOKEN}&clientId={DHAN_CLIENT_ID}&authType=2'
        backoff=2
        while not self.ws_stop.is_set():
            try:
                self.ws_status='CONNECTING'; self.ws=websocket.create_connection(url,timeout=15,enableTrace=False)
                self.ws.send(json.dumps({'RequestCode':15,'InstrumentCount':2,'InstrumentList':[{'ExchangeSegment':UNDERLYING_SEGMENT,'SecurityId':str(NIFTY_SECURITY_ID)},{'ExchangeSegment':UNDERLYING_SEGMENT,'SecurityId':str(BANKNIFTY_SECURITY_ID)}]}))
                self.ws_status='CONNECTED'; self.last_ws_error=''; backoff=2
                while not self.ws_stop.is_set():
                    packet=self.ws.recv()
                    if isinstance(packet,(bytes,bytearray)): self._parse_ws_packet(packet)
            except Exception as e:
                self.last_ws_error=str(e)[:180]; self.ws_status='RECONNECTING'
                time.sleep(backoff); backoff=min(backoff*2,30)
            finally:
                try:
                    if self.ws: self.ws.close()
                except Exception: pass
                self.ws=None
        self.ws_status='STOPPED'

    def _parse_ws_packet(self,b):
        if len(b)<16: return
        code=b[0]; sid=struct.unpack_from('<i',b,4)[0]
        if code==2:
            ltp=struct.unpack_from('<f',b,8)[0]; ltt=struct.unpack_from('<i',b,12)[0]
            self.live[sid]={'ltp':float(ltp),'epoch':int(ltt),'received':time.time()}

    def live_price(self,sid):
        x=self.live.get(sid)
        if not x: return None
        age=time.time()-x['received']
        if age>STALE_DATA_SECONDS: return None
        return {**x,'age_seconds':round(age,1)}

    def websocket_info(self):
        return {'enabled':bool(websocket and WEBSOCKET_ENABLED),'status':self.ws_status,'last_error':self.last_ws_error,
                'nifty':self.live_price(NIFTY_SECURITY_ID),'banknifty':self.live_price(BANKNIFTY_SECURITY_ID)}

    def _load_master(self):
        if self.master_cache is not None: return self.master_cache
        try:
            r=self.s.get(INSTRUMENT_MASTER_URL,timeout=30); r.raise_for_status(); self.master_cache=list(csv.DictReader(io.StringIO(r.text)))
        except Exception: self.master_cache=[]
        return self.master_cache

    def lot_size(self,security_id):
        sid=str(security_id)
        for row in self._load_master():
            if str(row.get('SEM_SMST_SECURITY_ID','')).strip()==sid:
                for key in ('SEM_LOT_SIZE','LOT_SIZE'):
                    try: return int(float(row.get(key) or 0))
                    except Exception: pass
        return LOT_SIZE_FALLBACK

    def stop(self):
        self.ws_stop.set()
        try:
            if self.ws: self.ws.close()
        except Exception: pass
