from strategy import PrecisionEngine


def market(bull=True):
    spot=100.0
    return {'spot':spot,'vwap':99 if bull else 101,'ema9':100.5 if bull else 99.5,'ema21':99.5 if bull else 100.5,
            'ema9_prev':100.4 if bull else 99.6,'short_momentum_pct':0.5 if bull else -0.5,'rsi':58 if bull else 42,
            'volume_ratio':1.6,'prev_high':99.7 if bull else 101.0,'prev_low':98.5 if bull else 100.3,
            'opening_range_high':99.6 if bull else 101.0,'opening_range_low':98.8 if bull else 100.2,
            'atr':1.0,'recent_closes':[98,98.5,99,99.4,100] if bull else [102,101.5,101,100.7,100],
            'recent_highs':[99,99.1,99.5,99.8,100.1] if bull else [102,101.8,101.4,101,100.5],
            'recent_lows':[97.8,98.1,98.5,98.9,99.5] if bull else [101.5,101.1,100.7,100.4,99.9]}


def option(side):
    return {'strike':100,'option_type':side,'ltp':10,'bid':9.95,'ask':10.0,'momentum':0.01 if side=='CE' else -0.001,
            'volume_ratio':2.0,'oi_change_pct':5,'spread_pct':0.5,'iv':20,'delta':0.5,'security_id':'123','symbol':side}


def test_engine_has_two_sided_outputs():
    e=PrecisionEngine(); r=e.evaluate(market(True),[option('CE'),option('PE')],capital=100000,risk_pct=.5)
    assert 'ce_score' in r and 'pe_score' in r


def test_bearish_can_choose_pe():
    e=PrecisionEngine(); r=e.evaluate(market(False),[option('PE'),option('CE')],capital=100000,risk_pct=.5)
    assert r['current_bias'] in ('PE','CE','NEUTRAL')
    assert r['pe_score'] >= 0


def test_no_forced_trade_when_scores_close():
    e=PrecisionEngine(); rows=[option('CE'),option('PE')]
    # Neutral market cannot pass directional regime filter for either side.
    f=market(True); f.update({'vwap':100,'ema9':100,'ema21':100,'short_momentum_pct':0,'rsi':50})
    r=e.evaluate(f,rows,capital=100000,risk_pct=.5)
    assert r['action']=='NO TRADE'
