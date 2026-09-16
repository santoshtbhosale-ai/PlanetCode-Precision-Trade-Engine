from math import isfinite
from config import *


def clamp(x, lo=0, hi=100):
    return max(lo, min(hi, int(round(x))))


class PrecisionEngine:
    """Multi-setup, two-sided options decision engine. Scores are setup quality, never win probability."""

    def _regime(self, f):
        spot=f['spot']; vwap=f['vwap']; e9=f['ema9']; e21=f['ema21']; atr=f.get('atr',0); mom=f.get('short_momentum_pct',0); rsi=f.get('rsi',50)
        sep=abs(e9-e21)/max(abs(spot),1)*100
        bull_points=sum([spot>vwap,e9>e21,e9>=f.get('ema9_prev',e9),mom>0.05,rsi>=52])
        bear_points=sum([spot<vwap,e9<e21,e9<=f.get('ema9_prev',e9),mom<-0.05,rsi<=48])
        if bull_points>=4: regime='STRONG BULLISH'
        elif bull_points>=3: regime='BULLISH'
        elif bear_points>=4: regime='STRONG BEARISH'
        elif bear_points>=3: regime='BEARISH'
        else: regime='NEUTRAL'
        if atr and spot:
            atr_pct=atr/spot*100
        else: atr_pct=0
        return {'regime':regime,'bull_points':bull_points,'bear_points':bear_points,'ema_sep_pct':sep,'atr_pct':atr_pct,'rsi':rsi}

    def _option_candidate(self, rows, side, spot):
        candidates=[r for r in rows if r.get('option_type')==side and float(r.get('ltp',0) or 0)>0]
        if not candidates: return None
        def rank(r):
            dist=abs(float(r['strike'])-spot)/max(spot,1)*100
            mom=float(r.get('momentum',0))*100
            vr=min(float(r.get('volume_ratio',1) or 1),4)
            oi=float(r.get('oi_change_pct',0) or 0)
            spread=float(r.get('spread_pct',99) or 99)
            delta=abs(float(r.get('delta',0) or 0))
            delta_fit=max(0,1-abs(delta-0.50)/0.35) if delta else 0
            return mom*5 + vr*2 + max(-10,min(20,oi))*0.12 + delta_fit*3 - dist*1.5 - max(0,spread-MAX_OPTION_SPREAD_PCT)*2
        return max(candidates,key=rank)

    def _base_direction_score(self, f, side):
        bull=side=='CE'; spot=f['spot']; vwap=f['vwap']; e9=f['ema9']; e21=f['ema21']; mom=f.get('short_momentum_pct',0); rsi=f.get('rsi',50); vr=f.get('volume_ratio',1)
        score=0; reasons=[]; components=[]
        if (spot>vwap and e9>e21) if bull else (spot<vwap and e9<e21):
            score+=18; components.append(('VWAP + EMA alignment',18,'pass')); reasons.append('underlying trend aligned')
        else: components.append(('VWAP + EMA alignment',0,'neutral'))
        sep=abs(e9-e21)/max(abs(spot),1)*100
        if sep>=0.035 and ((e9>e21) if bull else (e9<e21)):
            score+=10; components.append(('EMA separation',10,'pass'))
        if (mom>0.08) if bull else (mom<-0.08):
            score+=8; components.append(('Short momentum',8,'pass'))
        elif abs(mom)<0.04: components.append(('Short momentum',0,'neutral'))
        else: score-=4; components.append(('Short momentum',-4,'partial'))
        if (50<rsi<72) if bull else (28<rsi<50):
            score+=5; components.append(('RSI regime',5,'pass'))
        elif (rsi>=75) if bull else (rsi<=25):
            score-=5; components.append(('RSI extreme',-5,'warning'))
        if vr>=1.2: score+=5; components.append(('Underlying volume',5,'pass'))
        return score,reasons,components

    def _setup_scores(self,f,side):
        bull=side=='CE'; spot=f['spot']; high=f['prev_high']; low=f['prev_low']; orh=f['opening_range_high']; orl=f['opening_range_low']; atr=f.get('atr',0); vr=f.get('volume_ratio',1); mom=f.get('short_momentum_pct',0); regime=self._regime(f)['regime']
        out=[]
        # Trend continuation
        trend=0; rs=[]
        aligned=(spot>f['vwap'] and f['ema9']>f['ema21']) if bull else (spot<f['vwap'] and f['ema9']<f['ema21'])
        if aligned: trend+=45; rs.append('trend aligned with VWAP/EMA')
        if (mom>0.10) if bull else (mom<-0.10): trend+=25; rs.append('momentum confirms')
        if (regime in ('BULLISH','STRONG BULLISH')) if bull else (regime in ('BEARISH','STRONG BEARISH')): trend+=20; rs.append('supportive market regime')
        out.append(('Trend Continuation',min(trend,100),rs))
        # Breakout
        br=0; rs=[]
        crossed=(spot>high) if bull else (spot<low)
        if crossed: br+=45; rs.append('range breakout/breakdown')
        if vr>=1.3: br+=20; rs.append('volume expansion')
        if (mom>0.12) if bull else (mom<-0.12): br+=20; rs.append('momentum expansion')
        out.append(('Breakout',min(br,100),rs))
        # Opening range breakout
        orb=0; rs=[]
        crossed_or=(spot>orh) if bull else (spot<orl)
        if crossed_or: orb+=50; rs.append('opening range broken')
        if vr>=1.2: orb+=20; rs.append('opening range volume')
        if (mom>0.08) if bull else (mom<-0.08): orb+=20; rs.append('momentum confirmation')
        out.append(('Opening Range Breakout',min(orb,100),rs))
        # VWAP bounce/reclaim
        vb=0; rs=[]
        near=abs(spot-f['vwap'])/max(spot,1)*100<0.18
        if near and ((spot>f['vwap']) if bull else (spot<f['vwap'])): vb+=45; rs.append('VWAP reclaim/rejection zone')
        if ((f['ema9']>f['ema21']) if bull else (f['ema9']<f['ema21'])): vb+=25; rs.append('EMA confirmation')
        if (mom>0.04) if bull else (mom<-0.04): vb+=20; rs.append('momentum confirmation')
        out.append(('VWAP Bounce/Rejection',min(vb,100),rs))
        # Pullback continuation
        pb=0; rs=[]
        e9=f['ema9']; e21=f['ema21']
        pullback_zone=abs(spot-e9)/max(spot,1)*100<0.20 or abs(spot-e21)/max(spot,1)*100<0.30
        if pullback_zone and ((e9>e21) if bull else (e9<e21)): pb+=45; rs.append('price near trend EMA')
        if (mom>0) if bull else (mom<0): pb+=20; rs.append('directional momentum retained')
        if (spot>f['vwap']) if bull else (spot<f['vwap']): pb+=20; rs.append('VWAP supports trend')
        out.append(('Trend Pullback',min(pb,100),rs))
        # Momentum continuation
        mm=0; rs=[]
        if (mom>0.18) if bull else (mom<-0.18): mm+=50; rs.append('strong short-term momentum')
        if vr>=1.4: mm+=25; rs.append('volume expansion')
        if (spot>f['vwap']) if bull else (spot<f['vwap']): mm+=20; rs.append('price location confirms')
        out.append(('Momentum Continuation',min(mm,100),rs))
        # False breakout penalty signal is handled separately
        return out

    def _option_score(self, side, c):
        if not c: return 0, ['no option candidate'], [('Option availability',-20,'fail')]
        score=0; reasons=[]; comps=[]
        mom=float(c.get('momentum',0))*100; vr=float(c.get('volume_ratio',1) or 1); oi=float(c.get('oi_change_pct',0) or 0); spread=float(c.get('spread_pct',99) or 99); iv=float(c.get('iv',0) or 0); delta=abs(float(c.get('delta',0) or 0))
        if mom>=0.30: score+=18; reasons.append(f'{side} premium momentum strong'); comps.append((f'{side} premium momentum',18,'pass'))
        elif mom>0: score+=9; comps.append((f'{side} premium momentum',9,'partial'))
        else: score-=12; comps.append((f'{side} premium momentum',-12,'fail'))
        if vr>=1.2: score+=10; comps.append((f'{side} volume confirmation',10,'pass'))
        elif vr>=1: score+=4; comps.append((f'{side} volume confirmation',4,'partial'))
        else: score-=4; comps.append((f'{side} volume confirmation',-4,'fail'))
        if oi>=2: score+=7; comps.append((f'{side} OI participation',7,'pass'))
        elif oi<=-2: score-=2; comps.append((f'{side} OI participation',-2,'partial'))
        if spread<=MAX_OPTION_SPREAD_PCT: score+=9; comps.append((f'{side} spread',9,'pass'))
        else: score-=20; reasons.append(f'{side} spread too wide'); comps.append((f'{side} spread',-20,'fail'))
        if iv>40: score-=5; reasons.append(f'{side} IV elevated'); comps.append((f'{side} IV',-5,'warning'))
        if delta and 0.35<=delta<=0.65: score+=5; comps.append((f'{side} delta zone',5,'pass'))
        elif delta and delta<0.25: score-=4; comps.append((f'{side} delta too low',-4,'warning'))
        return score,reasons,comps

    def _false_breakout(self,f,side):
        closes=f.get('recent_closes',[]); highs=f.get('recent_highs',[]); lows=f.get('recent_lows',[])
        if len(closes)<5: return False
        spot=closes[-1]
        prev=max(highs[:-2]) if side=='CE' else min(lows[:-2])
        if side=='CE': return max(highs[-3:])>prev and spot<prev
        return min(lows[-3:])<prev and spot>prev

    def _trade(self,side,score,reasons,components,candidate,lot_size,capital,risk_pct,setup_name):
        if not candidate or score<MIN_SETUP_SCORE:
            return {'action':'NO TRADE','score':clamp(score),'quality':'WAIT FOR CONFIRMATION','reasons':reasons,'components':components,'direction':side,'setup_name':setup_name}
        entry=float(candidate.get('ask') or candidate.get('ltp') or 0)
        if entry<=0 or not isfinite(entry): return {'action':'NO TRADE','score':clamp(score),'quality':'INVALID PRICE','reasons':reasons+['invalid option premium'],'components':components,'direction':side}
        # Dynamic premium stop: tighter in stronger momentum, wider in weaker setup.
        stop_pct=0.12 if score>=85 else 0.14
        sl=round(entry*(1-stop_pct),2); risk_unit=round(entry-sl,2); target=round(entry+MIN_RR*risk_unit,2)
        risk_budget=capital*(risk_pct/100); qty_units=int(risk_budget//risk_unit) if risk_unit>0 else 0
        lots=int(qty_units//lot_size) if lot_size else 0; qty=lots*lot_size if lot_size else 0
        budget_cap=capital*(MAX_PREMIUM_BUDGET_PCT/100); budget_lots=int(budget_cap//(entry*lot_size)) if lot_size else 0
        if budget_lots>0: qty=min(qty,budget_lots*lot_size)
        if qty<=0:
            return {'action':'NO TRADE','score':clamp(score),'quality':'POSITION SIZE NOT VERIFIED','reasons':reasons+['lot size unavailable or risk budget too small'],'components':components,'direction':side}
        return {'action':'BUY '+side,'score':clamp(score),'quality':'STRONG TRADE CANDIDATE' if score>=85 else 'VALID TRADE CANDIDATE','reasons':reasons,'components':components,'direction':side,'setup_name':setup_name,
                'strike':candidate['strike'],'option_symbol':candidate.get('symbol'),'security_id':candidate.get('security_id'),'entry':entry,'sl':sl,'target':target,
                'risk_per_unit':risk_unit,'lot_size':lot_size,'qty':qty,'risk_budget':round(risk_budget,2),'rr':f'1:{MIN_RR:g}'}

    def evaluate(self,f,rows,lot_lookup=None,capital=100000,risk_pct=0.5):
        spot=float(f.get('spot',0) or 0); regime_info=self._regime(f); regime=regime_info['regime']
        outputs={}
        for side in ('CE','PE'):
            base,base_reasons,base_comps=self._base_direction_score(f,side)
            setups=self._setup_scores(f,side)
            best_name,best_setup,best_rs=max(setups,key=lambda x:x[1])
            opt=self._option_candidate(rows,side,spot)
            opt_score,opt_reasons,opt_comps=self._option_score(side,opt)
            score=base + round(best_setup*0.35) + opt_score
            # directional regime bonus/penalty
            aligned_regime=regime in (('BULLISH','STRONG BULLISH') if side=='CE' else ('BEARISH','STRONG BEARISH'))
            opposite_regime=regime in (('BEARISH','STRONG BEARISH') if side=='CE' else ('BULLISH','STRONG BULLISH'))
            if aligned_regime: score+=10
            if opposite_regime: score-=15
            if self._false_breakout(f,side): score-=15; opt_reasons.append('possible false breakout detected')
            score=clamp(score)
            threshold=CHOPPY_MIN_SCORE if regime=='NEUTRAL' else STRONG_TREND_MIN_SCORE if regime.startswith('STRONG') else MIN_SETUP_SCORE
            valid=score>=threshold and aligned_regime and opt is not None
            reasons=base_reasons + best_rs + opt_reasons
            comps=base_comps + [('Best setup: '+best_name,round(best_setup*0.35), 'pass' if best_setup>=60 else 'wait')] + opt_comps + [('Regime filter',10 if aligned_regime else -15,'pass' if aligned_regime else 'fail')]
            if not aligned_regime: reasons.append('direction does not match current market regime')
            lot=lot_lookup(opt.get('security_id')) if opt and lot_lookup else 0
            trade=self._trade(side,score,reasons,comps,opt,lot,capital,risk_pct,best_name) if valid else {'action':'NO TRADE','score':score,'quality':'WAIT FOR CONFIRMATION','reasons':reasons,'components':comps,'direction':side,'setup_name':best_name}
            trade['threshold']=threshold; trade['best_setup']=best_name; trade['best_setup_score']=best_setup; trade['candidate']={'strike':opt['strike'],'option_symbol':opt.get('symbol'),'security_id':opt.get('security_id')} if opt else None
            outputs[side]=trade
        ce=outputs['CE']; pe=outputs['PE']; ce_score=ce['score']; pe_score=pe['score']
        ce_valid=ce['action'].startswith('BUY'); pe_valid=pe['action'].startswith('BUY')
        chosen=None
        if ce_valid and pe_valid:
            if abs(ce_score-pe_score)>=5: chosen=ce if ce_score>pe_score else pe
        elif ce_valid: chosen=ce
        elif pe_valid: chosen=pe
        bias='CE' if ce_score>pe_score else 'PE' if pe_score>ce_score else 'NEUTRAL'
        if chosen is None:
            reason=['CE score: %d/100'%ce_score,'PE score: %d/100'%pe_score]
            if abs(ce_score-pe_score)<5: reason.append('CE/PE scores too close')
            if not ce_valid and not pe_valid: reason.append('no side passed all confirmation filters')
            return {'action':'NO TRADE','score':max(ce_score,pe_score),'quality':'WAIT FOR CONFIRMATION','direction':bias,'current_bias':bias,'regime':regime,'regime_info':regime_info,
                    'reasons':reason,'components':[('CE independent score',ce_score,'pass' if ce_valid else 'wait'),('PE independent score',pe_score,'pass' if pe_valid else 'wait')],
                    'safety':[f'CE confirmation {"OK" if ce_valid else "missing"}',f'PE confirmation {"OK" if pe_valid else "missing"}',f'Regime: {regime}','No clear directional edge' if not (ce_valid or pe_valid) else 'Both sides need a clear separation'],
                    'ce_score':ce_score,'pe_score':pe_score,'ce_candidate':ce.get('candidate'),'pe_candidate':pe.get('candidate'),'ce_setup':ce.get('best_setup'),'pe_setup':pe.get('best_setup'),'ce_setup_score':ce.get('best_setup_score'),'pe_setup_score':pe.get('best_setup_score')}
        chosen.update({'ce_score':ce_score,'pe_score':pe_score,'current_bias':chosen['direction'],'regime':regime,'regime_info':regime_info,
                       'ce_candidate':ce.get('candidate'),'pe_candidate':pe.get('candidate'),'ce_setup':ce.get('best_setup'),'pe_setup':pe.get('best_setup'),'ce_setup_score':ce.get('best_setup_score'),'pe_setup_score':pe.get('best_setup_score'),
                       'safety':[f'Regime aligned: {regime}',f'{chosen["direction"]} confirmation passed',f'R:R >= {MIN_RR:g}',f'Spread <= {MAX_OPTION_SPREAD_PCT:g}%']})
        return chosen
