"""Transparent, experimental score snapshots for paper BTC option opportunities."""
import json
import sqlite3
from contextlib import closing
from decimal import Decimal, InvalidOperation
import time
import uuid


VERSION='experimental-v1'
DEFAULT_WEIGHTS={'liquidity':40,'economics':35,'objective_fit':25}


def evaluate(db_path, data, now_ms=None):
    try:
        objective=str(data['objective']).strip()
        if objective not in ('protecao','rendimento','aposta'):
            raise ValueError('Objetivo deve ser proteção, rendimento ou aposta.')
        weights={key:Decimal(str(data.get('weights',DEFAULT_WEIGHTS).get(key))) for key in DEFAULT_WEIGHTS}
        if any(not x.is_finite() or x<0 for x in weights.values()) or sum(weights.values())!=100:
            raise ValueError('Pesos válidos devem somar exatamente 100%.')
        max_risk=Decimal(str(data.get('max_risk_usd','1000000000')))
        age_limit=Decimal(str(data.get('max_quote_age_ms',30000)))
        if any(not x.is_finite() or x<0 for x in (max_risk,age_limit)):
            raise ValueError('Orçamento, risco e idade limite devem ser não negativos.')
        with closing(sqlite3.connect(db_path)) as con:
            try:wallet_row=con.execute('SELECT payload FROM funds WHERE id=1').fetchone()
            except sqlite3.OperationalError:wallet_row=None
        wallet=json.loads(wallet_row[0]) if wallet_row else None
        candidates=data.get('candidates',[])
        if not isinstance(candidates,list):raise ValueError('Candidatas devem formar uma lista.')
        now=Decimal(str(now_ms if now_ms is not None else time.time()*1000))
        eligible=[];excluded=[]
        for index,candidate in enumerate(candidates):
            reasons=[]
            try:
                timestamp=Decimal(str(candidate['timestamp']));risk=Decimal(str(candidate['risk_estimate_usd']))
                currency=str(candidate.get('entry_currency',''))
                venue=str(candidate.get('venue','')).lower()
                balance=next((x for x in (wallet or {}).get('balances',[]) if x['location'].lower()==venue and x['token'].upper()==currency),None)
                if not balance:budget=Decimal(0);reasons.append(f'Saldo livre de {currency} em {venue or "exchange desconhecida"} não cadastrado.')
                elif currency=='BTC':budget=Decimal(str(balance['available']))*Decimal(str(candidate['reference_btc_usd']))
                else:budget=Decimal(str(balance['available']))
                if not timestamp.is_finite() or now-timestamp>age_limit or timestamp>now+5000:reasons.append(f'Cotação fora da janela: idade {now-timestamp} ms, máximo {age_limit} ms.')
                if not risk.is_finite() or risk<0:reasons.append('Risco estimado inválido.')
                else:
                    if risk>max_risk:reasons.append(f'Risco {risk} USD excede o limite {max_risk} USD.')
                    if risk>budget:reasons.append(f'Orçamento {budget} USD insuficiente para risco de {risk} USD.')
                quantity=Decimal(str(candidate['size']))
                executable=Decimal(str(candidate.get('executable_size',candidate['size'])))
                if executable<quantity:reasons.append(f'Profundidade executável {executable} abaixo de {quantity}.')
                if currency not in ('BTC','USDC'):reasons.append('Moeda de liquidação não reconhecida.')
                factors=candidate.get('factors',data.get('factors',{}))
                potential=max(Decimal(0),Decimal(str(candidate.get('maximum_gain_usd',0))))
                risk_nonzero=max(Decimal(0),risk)
                normalized={'liquidity':Decimal(str(factors.get('liquidity',min(Decimal(100),executable/quantity*100 if quantity else 0)))),
                            'economics':Decimal(str(factors.get('economics',potential/(potential+risk_nonzero)*100 if potential+risk_nonzero else 0))),
                            'objective_fit':Decimal(str(factors.get('objective_fit',data.get('objective_fit_score',50))))}
                if any(not x.is_finite() or x<0 or x>100 for x in normalized.values()):reasons.append('Fatores normalizados devem estar entre 0 e 100.')
            except (KeyError,TypeError,InvalidOperation,ValueError) as exc:
                reasons.append(f'Dados ausentes ou inválidos: {exc}.')
                normalized={key:Decimal(0) for key in DEFAULT_WEIGHTS}
                risk=Decimal(0)
            reason_map={'protecao':'aderência à meta de recomposição e déficit residual em BTC',
                        'rendimento':'resultado incremental líquido comparado à carteira protegida',
                        'aposta':'aderência à tese e perda máxima no orçamento de risco'}
            if reasons:
                excluded.append({'candidate':candidate.get('buy','?')+'/'+candidate.get('sell','?'),'reasons':reasons,
                                 'observed_risk_usd':str(risk)})
                continue
            score=sum((normalized[k]*weights[k]/100 for k in DEFAULT_WEIGHTS),Decimal(0))
            eligible.append({'candidate':candidate,'score':str(score),'factors':{k:str(v) for k,v in normalized.items()},
                             'weights':{k:str(v) for k,v in weights.items()},'objective_fit_meaning':reason_map[objective],
                             'normalization':'liquidez = preenchimento/quantidade; economia = ganho máximo/(ganho máximo + perda máxima); aderência à meta pode ser informada; fatores experimentais'})
        eligible.sort(key=lambda x:Decimal(x['score']),reverse=True)
        result={'objective':objective,'version':VERSION,'calibration':'experimental',
                'evaluated_at':str(now),'weights':{k:str(v) for k,v in weights.items()},
                'budget_policy':'saldo livre já descontadas as alocações prioritárias cadastradas; BTC convertido pelo índice da candidata; Derive assume USDC ≈ 1 USD',
                'ranked':eligible,'excluded':excluded,'empty_reason':
                'Nenhuma candidata passou pelos limites; veja os valores e motivos observados.' if not eligible else None}
        event_id=str(data.get('evaluation_id') or uuid.uuid4()).strip()
        if not event_id:raise ValueError('Identificador da avaliação é obrigatório.')
        signature=json.dumps(data,sort_keys=True,default=str)
        result['request_signature']=signature
        with closing(sqlite3.connect(db_path,timeout=10)) as con,con:
            con.execute('CREATE TABLE IF NOT EXISTS radar_evaluations (evaluation_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)')
            prior=con.execute('SELECT payload FROM radar_evaluations WHERE evaluation_id=?',(event_id,)).fetchone()
            if prior:
                existing=json.loads(prior[0])
                if existing.get('request_signature')!=signature:raise ValueError('Identificador da avaliação reutilizado com outros dados.')
                return existing
            result['evaluation_id']=event_id
            con.execute('INSERT INTO radar_evaluations VALUES(?,?,?)',(event_id,str(now),json.dumps(result)))
        return result
    except (KeyError,TypeError,InvalidOperation,sqlite3.OperationalError) as exc:
        raise ValueError('Dados de avaliação do radar inválidos.') from exc


def history(db_path):
    with closing(sqlite3.connect(db_path)) as con:
        try:rows=con.execute('SELECT payload FROM radar_evaluations ORDER BY created_at DESC').fetchall()
        except sqlite3.OperationalError:return []
    return [json.loads(row[0]) for row in rows]
