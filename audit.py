"""Append-only option decision and cash-flow diary."""
import json
import sqlite3
import uuid
from contextlib import closing
from decimal import Decimal,InvalidOperation
import time


def disposition(db_path,data,now_ms=None):
    try:
        evaluation_id=str(data['evaluation_id']).strip();candidate=data['candidate']
        status=str(data['status']).strip();event_id=str(data.get('event_id') or uuid.uuid4()).strip()
        if status not in ('ignorada','expirada','bloqueada') or not evaluation_id or not event_id or not isinstance(candidate,dict):
            raise ValueError('Status ou dados da oportunidade inválidos.')
        payload={'event_id':event_id,'evaluation_id':evaluation_id,'status':status,'candidate':candidate,
                 'note':str(data.get('note','')).strip(),'observed_at':str(now_ms or time.time()*1000)}
        signature=json.dumps(payload,sort_keys=True)
        with closing(sqlite3.connect(db_path,timeout=10)) as con,con:
            con.execute('CREATE TABLE IF NOT EXISTS audit_dispositions (event_id TEXT PRIMARY KEY,evaluation_id TEXT NOT NULL,status TEXT NOT NULL,payload TEXT NOT NULL)')
            old=con.execute('SELECT payload FROM audit_dispositions WHERE event_id=?',(event_id,)).fetchone()
            if old:
                existing=json.loads(old[0])
                for key in ('evaluation_id','status','candidate','note'):
                    if existing.get(key)!=payload.get(key):raise ValueError('ID do evento reutilizado com dados diferentes.')
                return existing
            exists=con.execute('SELECT 1 FROM radar_evaluations WHERE evaluation_id=?',(evaluation_id,)).fetchone()
            if not exists:raise ValueError('Avaliação do radar não encontrada.')
            con.execute('INSERT INTO audit_dispositions VALUES(?,?,?,?)',(event_id,evaluation_id,status,signature))
        return payload
    except (KeyError,TypeError,sqlite3.OperationalError) as exc:
        raise ValueError('Dados do evento de auditoria inválidos.') from exc


def cashflow(db_path,data,now_ms=None):
    try:
        event_id=str(data.get('event_id') or uuid.uuid4()).strip();category=str(data['category']).strip()
        currency=str(data['currency']).strip().upper();amount=Decimal(str(data['amount']))
        observed_at=str(data['observed_at']).strip();note=str(data.get('note','')).strip()
        allowed=('juros_divida','resultado_grid','funding_perpetuo','outro')
        if category not in allowed or not event_id or not currency or not amount.is_finite() or not observed_at:
            raise ValueError('Informe categoria, moeda, valor finito e horário.')
        payload={'event_id':event_id,'category':category,'currency':currency,'amount':str(amount),
                 'observed_at':observed_at,'note':note}
        signature=json.dumps(payload,sort_keys=True)
        with closing(sqlite3.connect(db_path,timeout=10)) as con,con:
            con.execute('CREATE TABLE IF NOT EXISTS audit_cashflows (event_id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
            old=con.execute('SELECT payload FROM audit_cashflows WHERE event_id=?',(event_id,)).fetchone()
            if old:
                existing=json.loads(old[0])
                for key in ('category','currency','amount','observed_at','note'):
                    if existing.get(key)!=payload.get(key):raise ValueError('ID do fluxo reutilizado com dados diferentes.')
                return existing
            con.execute('INSERT INTO audit_cashflows VALUES(?,?)',(event_id,signature))
        return payload
    except (KeyError,TypeError,InvalidOperation,sqlite3.OperationalError) as exc:
        raise ValueError('Dados do fluxo financeiro inválidos.') from exc


def history(db_path,now_ms=None):
    now=now_ms or time.time()*1000
    with closing(sqlite3.connect(db_path)) as con:
        def rows(query):
            try:return con.execute(query).fetchall()
            except sqlite3.OperationalError:return []
        evaluations=[json.loads(x[0]) for x in rows('SELECT payload FROM radar_evaluations ORDER BY created_at DESC')]
        dispositions=[json.loads(x[0]) for x in rows('SELECT payload FROM audit_dispositions ORDER BY rowid DESC')]
        cashflows=[json.loads(x[0]) for x in rows('SELECT payload FROM audit_cashflows ORDER BY rowid DESC')]
        positions=[json.loads(x[0]) for x in rows('SELECT payload FROM paper_spreads ORDER BY id DESC')]
        closures=[json.loads(x[0]) for x in rows('SELECT payload FROM paper_closures ORDER BY rowid DESC')]
        recoveries=[json.loads(x[0]) for x in rows('SELECT payload FROM recovery_events ORDER BY id DESC')]
    execution_keys={(x.get('evaluation_id'),x.get('quote',{}).get('buy'),x.get('quote',{}).get('sell'))
                    for x in positions if x.get('evaluation_id')}
    manual={(x['evaluation_id'],json.dumps(x['candidate'],sort_keys=True)):x for x in dispositions}
    opportunities=[];empty_periods=[]
    for evaluation in evaluations:
        if not evaluation.get('ranked'):
            empty_periods.append({'evaluation_id':evaluation.get('evaluation_id'),'objective':evaluation.get('objective'),
                                  'observed_at':evaluation.get('evaluated_at'),'reason':evaluation.get('empty_reason') or 'Nenhuma candidata no período.'})
        for status_key,status in (('ranked','sugerida'),('excluded','bloqueada')):
            for item in evaluation.get(status_key,[]):
                candidate=item.get('candidate',item)
                event=manual.get((evaluation.get('evaluation_id'),json.dumps(candidate,sort_keys=True)))
                expiry=candidate.get('expiry')
                expired=expiry is not None and float(expiry)<=float(now)
                if (evaluation.get('evaluation_id'),candidate.get('buy'),candidate.get('sell')) in execution_keys:
                    status='executada'
                elif event:status=event['status']
                elif status_key=='ranked' and expired:status='expirada'
                else:status='bloqueada' if status_key=='excluded' else 'disponível'
                opportunities.append({'evaluation_id':evaluation.get('evaluation_id'),'status':status,
                                      'score':item.get('score'),'candidate':candidate,'reasons':item.get('reasons',[]),
                                      'factors':item.get('factors'),'weights':item.get('weights'),
                                      'observed_at':evaluation.get('evaluated_at'),'calibration':evaluation.get('calibration')})
    closed=[]
    for item in closures:
        closed.append({'request_id':item.get('request_id'),'venue':item.get('quote',{}).get('venue'),
                       'family':item.get('quote',{}).get('direction')+'/'+item.get('quote',{}).get('entry'),
                       'score':item.get('opportunity',{}).get('score'),'native_pnl':item.get('realized_pnl'),
                       'currency':item.get('realized_currency'),'pnl_usd':item.get('realized_pnl_usd'),
                       'suggested':item.get('proposed_debit'),'executed':item.get('recotado'),
                       'slippage_percent':item.get('slippage_percent'),'fees_open':item.get('fees'),
                       'fees_close':item.get('exit_quote',{}).get('fees'),'closed_at':item.get('closed_at'),
                       'pnl_adjustment_note':'PnL da opção já inclui prêmio e taxas de entrada/saída; juros de dívida, grid e funding ficam nos fluxos separados.'})
    performance={}
    for item in closed:
        score=Decimal(str(item['score'])) if item['score'] is not None else None
        band=('sem_score' if score is None else '0-59' if score<60 else '60-79' if score<80 else '80-100')
        key=(item['family'],item['venue'],band)
        performance[key]=performance.get(key,Decimal(0))+Decimal(str(item['pnl_usd'] or 0))
    return {'opportunities':opportunities,'empty_periods':empty_periods,'evaluations':evaluations,
            'dispositions':dispositions,'cashflows':cashflows,'closed_positions':closed,
            'aave_recovery_events':recoveries,'summary':{'suggested':sum(x['status']=='disponível' for x in opportunities),
            'ignored':sum(x['status']=='ignorada' for x in opportunities),'expired':sum(x['status']=='expirada' for x in opportunities),
            'blocked':sum(x['status']=='bloqueada' for x in opportunities),'executed':sum(x['status']=='executada' for x in opportunities),
            'realized_option_pnl_usd':str(sum((Decimal(str(x['pnl_usd'])) for x in closed if x['pnl_usd'] is not None),Decimal(0))),
            'performance_by_family_score':[{'family':k[0],'venue':k[1],'score_band':k[2],'option_pnl_usd':str(v)} for k,v in performance.items()]}}
