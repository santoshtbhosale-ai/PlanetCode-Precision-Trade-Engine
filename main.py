from datetime import datetime, time
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from dhan_service import DhanService
from historical_engine import HistoricalValidationEngine
from news_engine import NewsContext
from strategy import PrecisionEngine
from config import *

app=FastAPI(title='PlanetCode Precision Trade Engine V6.0')
t=Jinja2Templates(directory='templates'); d=DhanService(); engine=PrecisionEngine(); historical_engine=HistoricalValidationEngine(); news_engine=NewsContext()
signal_history={'NIFTY':[],'BANKNIFTY':[]}; last_action={'NIFTY':None,'BANKNIFTY':None}; last_signal_at={'NIFTY':0,'BANKNIFTY':0}; signal_date=datetime.now().date()


def market_status():
    now=datetime.now(); open_=now.weekday()<5 and time(9,15)<=now.time()<=time(15,40)
    return {'open':open_,'label':'MARKET OPEN' if open_ else 'MARKET CLOSED','time':now.strftime('%H:%M:%S')}


def entry_window_open():
    now=datetime.now().time(); sh,sm=map(int,TRADING_START_TIME.split(':')); eh,em=map(int,TRADING_END_TIME.split(':'))
    return time(sh,sm)<=now<=time(eh,em)


def reset_daily():
    global signal_date
    today=datetime.now().date()
    if today!=signal_date:
        signal_date=today
        for s in signal_history: signal_history[s]=[]; last_action[s]=None; last_signal_at[s]=0


def guarded_result(symbol,r):
    reset_daily(); now=datetime.now(); reasons=list(r.get('reasons',[])); action=r.get('action','NO TRADE')
    if not market_status()['open']:
        r['action']='NO TRADE'; r['quality']='MARKET CLOSED'; reasons.append('outside regular market session')
    elif not entry_window_open() and action.startswith('BUY'):
        r['action']='NO TRADE'; r['quality']='ENTRY WINDOW CLOSED'; reasons.append(f'fresh entries allowed only {TRADING_START_TIME}-{TRADING_END_TIME}')
    elif action.startswith('BUY'):
        if last_action[symbol]==action and now.timestamp()-last_signal_at[symbol]<SIGNAL_COOLDOWN_SECONDS:
            r['action']='WAIT'; r['quality']='SIGNAL COOLDOWN'; reasons=['same signal already generated; waiting for fresh confirmation']
        elif len(signal_history[symbol])>=MAX_SIGNALS_PER_DAY:
            r['action']='NO TRADE'; r['quality']='DAILY SIGNAL LIMIT'; reasons=['daily signal limit reached']
        else:
            last_action[symbol]=action; last_signal_at[symbol]=now.timestamp(); signal_history[symbol].append({'time':now.strftime('%H:%M:%S'),'action':action,'score':r.get('score'),'setup':r.get('setup_name')})
    r['reasons']=reasons; r['signal_count_today']=len(signal_history[symbol]); r['signal_history']=signal_history[symbol][-8:]
    return r

@app.on_event('shutdown')
def shutdown(): d.stop()

@app.get('/',response_class=HTMLResponse)
def home(request:Request):
    return t.TemplateResponse(request=request,name='index.html',context={'scan_seconds':AUTO_SCAN_SECONDS,'capital':CAPITAL,'risk_pct':RISK_PCT})

@app.get('/api/health')
def health():
    return {'status':'ok','dhan_configured':d.configured(),'auto_trade':False,'trading_mode':'PAPER' if PAPER_MODE else 'MANUAL','websocket':d.websocket_info(),**market_status(),'entry_window':entry_window_open()}

@app.get('/api/scan/{symbol}')
def scan(symbol:str):
    symbol=symbol.upper(); sid=NIFTY_SECURITY_ID if symbol=='NIFTY' else BANKNIFTY_SECURITY_ID if symbol=='BANKNIFTY' else None
    if not sid: raise HTTPException(400,'Unsupported symbol')
    try:
        f=d.candles(sid); live=d.live_price(sid); exp=d.expiry(sid); chain=d.chain(sid,exp); spot,rows=d.parse(chain)
        if live: spot=live['ltp']
        f['spot']=spot
        hist={side: historical_engine.validate(sid,f,side,HISTORICAL_LOOKBACK_DAYS) for side in ('CE','PE')} if HISTORICAL_VALIDATION_ENABLED else {}
        news=news_engine.get(symbol) if NEWS_VALIDATION_ENABLED else {'available':False,'bias':'DISABLED','risk_flag':False,'headlines':[]}
        r=engine.evaluate(f,rows,lot_lookup=d.lot_size,capital=CAPITAL,risk_pct=RISK_PCT,historical=hist,news=news); r=guarded_result(symbol,r)
        op='BUY '+r.get('direction','') if r.get('action','').startswith('BUY') else r.get('action')
        session_move=round(spot-f.get('session_open',spot),2); session_pct=round(session_move/max(f.get('session_open',spot),1)*100,2)
        return {'timestamp':datetime.now().isoformat(timespec='seconds'),'symbol':symbol,'expiry':exp,'spot':round(spot,2),'session_open':round(f.get('session_open',spot),2),'session_move':session_move,'session_pct':session_pct,
                'vwap':round(f['vwap'],2),'ema9':round(f['ema9'],2),'ema21':round(f['ema21'],2),'rsi':round(f.get('rsi',50),1),'atr':round(f.get('atr',0),2),'volume_ratio':round(f.get('volume_ratio',1),2),
                'candles':f['candles'],'short_momentum_pct':round(f.get('short_momentum_pct',0),3),'live_feed':live,'mode':'LIVE WEBSOCKET + REST + HISTORICAL + NEWS CONFIRMATION / MANUAL TRADE','auto_trade':False,'capital':CAPITAL,'risk_pct':RISK_PCT,'entry_window':entry_window_open(),**market_status(),**r}
    except Exception as e:
        raise HTTPException(502,str(e))
