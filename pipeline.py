#!/usr/bin/env python3
"""Reproducible Lending Club + PaySim risk analytics pipeline."""
import csv, gzip, io, json, math, os, sqlite3, sys, zipfile
import re
from collections import Counter
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parent; DATA=ROOT/'data'; DB=ROOT/'warehouse.sqlite'
LOAN=next((p for p in DATA.glob('*') if 'accepted_2007_to_2018' in p.name),None)
PAY=next((p for p in DATA.glob('*') if '1491204439457' in p.name),None)
LOAN_USE=['id','loan_amnt','term','int_rate','grade','sub_grade','home_ownership','annual_inc','issue_d','loan_status','purpose','addr_state','dti']
PAY_USE=['step','type','amount','nameOrig','oldbalanceOrg','newbalanceOrig','nameDest','oldbalanceDest','newbalanceDest','isFraud','isFlaggedFraud']
KNOWN_STATUS={'current','fully paid','charged off','default','in grace period','late (16-30 days)','late (31-120 days)','issued','does not meet the credit policy. status:charged off','does not meet the credit policy. status:fully paid'}

def source_open(path):
    if path.suffix=='.gz': return gzip.open(path,'rt',encoding='utf-8-sig',newline='')
    if path.suffix=='.zip':
        z=zipfile.ZipFile(path); return io.TextIOWrapper(z.open(z.namelist()[0]),encoding='utf-8-sig',newline='')
    return path.open('r',encoding='utf-8-sig',newline='')

def clean_db():
    for suffix in ('','-wal','-shm'):
      p=Path(str(DB)+suffix)
      if p.exists(): p.unlink()

def table_sql(table,cols,extra=''):
    names=','.join('"'+c+'" TEXT' for c in cols)
    return f'CREATE TABLE {table} ({names}{extra})'

def etl_one(conn, path, dataset, requested):
    with source_open(path) as f: headers=next(csv.reader(f))
    cols=[c for c in requested if c in headers]
    if not cols: raise RuntimeError(f'{dataset}: no expected columns found; actual headers={headers}')
    missing=[c for c in requested if c not in headers]
    raw,clean,reject=f'raw_{dataset}',f'clean_{dataset}',f'rejected_{dataset}'
    conn.execute(table_sql(raw,cols))
    extra=', issue_date TEXT' if dataset=='loans' and 'issue_d' in cols else ''
    conn.execute(table_sql(clean,cols,extra))
    conn.execute(f'CREATE TABLE {reject}(row_key TEXT, reason TEXT, record_json TEXT)')
    conn.execute(f'CREATE TABLE flagged_{dataset}(row_key TEXT, reason TEXT, record_json TEXT)')
    dq=Counter(); nulls=Counter(); unique=set()
    raw_n=clean_n=reject_n=0; categories=Counter()
    with source_open(path) as f:
      reader=csv.DictReader(f)
      chunk=[]
      for row in reader:
        chunk.append({c:row.get(c) for c in cols})
        if len(chunk)>=50000:
          a,b,c=_insert_batch(conn,dataset,cols,chunk,unique,dq,nulls,categories); raw_n+=a;clean_n+=b;reject_n+=c;chunk=[]
      if chunk:
        a,b,c=_insert_batch(conn,dataset,cols,chunk,unique,dq,nulls,categories); raw_n+=a;clean_n+=b;reject_n+=c
    for k,n in nulls.items(): dq['null:'+k]=n
    rows=[(name,count,action) for name,count,action in [
      ('missing_expected_columns',len(missing),'reported; available columns used'),('duplicate_key',dq['duplicate_key'],'quarantined'),
      ('negative_amount',dq['negative_amount'],'quarantined'),('negative_dti',dq['negative_dti'],'quarantined'),
      ('int_rate_out_of_range',dq['int_rate_out_of_range'],'quarantined'),('invalid_or_out_of_range_date',dq['invalid_or_out_of_range_date'],'quarantined'),
      ('unknown_category',dq['unknown_category'],'quarantined'),('negative_balance_or_step',dq['negative_balance_or_step'],'quarantined')]]
    for k in cols: rows.append((f'null_rate:{k}',nulls[k],f'flagged; retained when other checks pass (rate={nulls[k]/max(raw_n,1):.6f})'))
    pd.DataFrame(rows,columns=['check','rows_affected','action_taken']).to_csv(ROOT/f'dq_report_{dataset}.csv',index=False)
    conn.commit()
    print(f'ETL {dataset}: raw={raw_n:,}, clean={clean_n:,}, rejected={reject_n:,}, columns={len(cols)}')
    if missing: print(f'  unavailable hint columns: {missing}')
    return {'raw':raw_n,'clean':clean_n,'rejected':reject_n,'columns':cols,'categories':categories}

def _insert_batch(conn,dataset,cols,rows,unique,dq,nulls,categories):
    raw_rows=[]; clean_rows=[]; rejects=[]; flags=[]
    for r in rows:
        null_columns=[]
        for k,v in r.items():
            if v is None or str(v).strip()=='': nulls[k]+=1; null_columns.append(k)
        why=[]
        key=r.get('id') if dataset=='loans' else '|'.join(str(r.get(k,'')) for k in ['step','nameOrig','nameDest','type','amount'])
        if dataset=='loans':
            status=str(r.get('loan_status') or '').strip().lower(); categories[status]+=1
            if key in unique: why.append('duplicate loan id')
            unique.add(key)
            amount=_num(r.get('loan_amnt')); dti=_num(r.get('dti')); rate=_num(r.get('int_rate'))
            if amount is not None and amount<0: why.append('negative loan amount')
            if dti is not None and dti<0: why.append('negative dti')
            if rate is not None and not 0<=rate<=100: why.append('interest rate outside 0..100')
            date=pd.to_datetime(r.get('issue_d'),format='%b-%Y',errors='coerce')
            if pd.isna(date) or not (pd.Timestamp('2007-01-01')<=date<=pd.Timestamp('2018-12-31')): why.append('unparseable or out-of-range issue_d')
            if status and status not in KNOWN_STATUS: why.append('unknown loan_status: '+status)
            vals=tuple(r.get(c) for c in cols)+(None if pd.isna(date) else date.strftime('%Y-%m-%d'),)
        else:
            trans_type=str(r.get('type') or '').strip()
            categories[trans_type]+=1
            if trans_type not in {'CASH_IN','CASH_OUT','DEBIT','PAYMENT','TRANSFER'}: why.append('unknown transaction type: '+trans_type)
            if key in unique: why.append('duplicate transaction composite key')
            unique.add(key)
            amount=_num(r.get('amount')); step=_num(r.get('step'))
            balances=[_num(r.get(k)) for k in ['oldbalanceOrg','newbalanceOrig','oldbalanceDest','newbalanceDest']]
            if amount is not None and amount<0: why.append('negative transaction amount')
            if step is not None and step<1: why.append('non-positive step')
            if any(v is not None and v<0 for v in balances): why.append('negative balance')
            if str(r.get('isFraud')) not in {'0','1'}: why.append('invalid isFraud category')
            vals=tuple(r.get(c) for c in cols)
        raw_rows.append(tuple(r.get(c) for c in cols))
        if null_columns: flags.append((str(key),'null values: '+', '.join(null_columns),json.dumps(r,ensure_ascii=False)))
        if why:
            rejects.append((str(key),'; '.join(why),json.dumps(r,ensure_ascii=False)))
            for w in why:
                if w.startswith('duplicate'): dq['duplicate_key']+=1
                elif 'negative loan amount' in w or 'negative transaction' in w: dq['negative_amount']+=1
                elif 'negative dti' in w: dq['negative_dti']+=1
                elif 'interest rate' in w: dq['int_rate_out_of_range']+=1
                elif 'issue_d' in w: dq['invalid_or_out_of_range_date']+=1
                elif 'unknown loan_status' in w or 'invalid isFraud' in w or 'unknown transaction type' in w: dq['unknown_category']+=1
                else: dq['negative_balance_or_step']+=1
        else: clean_rows.append(vals)
    conn.executemany(f'INSERT INTO raw_{dataset} VALUES ({",".join("?" for _ in cols)})',raw_rows)
    clean_cols=cols+(['issue_date'] if dataset=='loans' else [])
    conn.executemany(f'INSERT INTO clean_{dataset} VALUES ({",".join("?" for _ in clean_cols)})',clean_rows)
    conn.executemany(f'INSERT INTO rejected_{dataset} VALUES (?,?,?)',rejects)
    conn.executemany(f'INSERT INTO flagged_{dataset} VALUES (?,?,?)',flags)
    return len(rows),len(clean_rows),len(rejects)

def _num(x):
    try: return float(str(x).replace('%','').strip()) if x not in (None,'') else None
    except (TypeError,ValueError): return None

def stage_etl():
    if not LOAN or not PAY: raise FileNotFoundError(f'Required downloads missing from data/: loan={LOAN}, paysim={PAY}')
    clean_db(); c=sqlite3.connect(DB); c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA synchronous=NORMAL')
    l=etl_one(c,LOAN,'loans',LOAN_USE); p=etl_one(c,PAY,'paysim',PAY_USE); c.close()
    return l,p

def run_sql(conn,path):
    script=re.sub(r'(?m)^\s*--.*$','',(ROOT/'sql'/path).read_text()); statements=[s.strip() for s in script.split(';') if s.strip()]
    for s in statements:
      if s.upper().startswith('SELECT'): continue
      conn.executescript(s+';')

def stage_credit():
    c=sqlite3.connect(DB); run_sql(c,'credit.sql')
    # SQL script's final SELECT is executed explicitly.
    summary=c.execute('SELECT (SELECT COUNT(*) FROM raw_loans),COUNT(*),(SELECT COUNT(*) FROM credit_resolved),(SELECT AVG(default_flag) FROM credit_resolved) FROM clean_loans').fetchone()
    c.execute("SELECT * FROM credit_vintage").fetchall()
    pd.read_sql_query('SELECT * FROM credit_vintage',c).to_csv(ROOT/'tableau_extracts'/'vintage_default_rate.csv',index=False)
    pd.read_sql_query('SELECT * FROM credit_segments',c).to_csv(ROOT/'tableau_extracts'/'segment_default_rate.csv',index=False)
    pd.read_sql_query('SELECT * FROM credit_delinquency',c).to_csv(ROOT/'tableau_extracts'/'delinquency_buckets.csv',index=False)
    # Match overall rates, segment deterioration and shift-share windows exactly.
    q=c.execute('SELECT issue_quarter FROM credit_vintage ORDER BY issue_quarter').fetchall(); qs=[r[0] for r in q]
    worst='NOT AVAILABLE'; rca='No comparable vintage windows available.'; driver='NOT AVAILABLE'; pp=None
    if len(qs)>=4:
      n=max(1,len(qs)//4); early=qs[:n]; late=qs[-n:]
      c.execute('CREATE TEMP TABLE IF NOT EXISTS rca_windows(issue_quarter TEXT PRIMARY KEY,period INTEGER)')
      c.execute('DELETE FROM rca_windows')
      c.executemany('INSERT INTO rca_windows VALUES (?,?)',[(x,0) for x in early]+[(x,1) for x in late])
      run_sql(c,'rca.sql')
      rates=pd.read_sql_query("SELECT CASE period WHEN 0 THEN 'earliest quartile' ELSE 'latest quartile' END period,loans,default_rate FROM rca_window_rates ORDER BY period",c)
      rates.to_csv(ROOT/'credit_period_rates.csv',index=False)
      worst_row=pd.read_sql_query('SELECT * FROM rca_worst_segment',c)
      decomps=pd.read_sql_query('SELECT * FROM rca_decomposition ORDER BY dimension',c)
      if len(worst_row):
        w=worst_row.iloc[0]; worst=f"{w.dimension}={w.segment}"; ar=float(w.early_rate); br=float(w.late_rate); wn0=int(w.early_n); wn1=int(w.late_n)
      top=decomps.sort_values('rate_effect_pp',ascending=False).iloc[0]
      driver=f'{top.dimension} within-segment rate effect'; pp=float(top.rate_effect_pp)
      rca=f"# Credit portfolio root-cause analysis\n\n## Finding\nWorst matched segment deterioration (minimum 100 resolved loans in each window): **{worst}**, default rate moved from {ar:.4%} to {br:.4%} (+{(br-ar)*100:.2f} percentage points; n={wn0:,} earliest, {wn1:,} latest) between issue-quarter windows {min(early)}–{max(early)} and {min(late)}–{max(late)}.\n\n## Evidence\nOverall resolved-loan rate moved from {rates.iloc[0].default_rate:.4%} (n={int(rates.iloc[0].loans):,}) to {rates.iloc[1].default_rate:.4%} (n={int(rates.iloc[1].loans):,}). SQL shift-share by grade, term and purpose: "+'; '.join(f"{r.dimension}: total {r.total_change_pp:+.3f} pp = within-segment rate {r.rate_effect_pp:+.3f} pp + mix {r.mix_effect_pp:+.3f} pp" for r in decomps.itertuples())+f". Largest positive within-segment effect: **{driver}**, {pp:+.3f} pp.\n\n## Caveats\nWindows are earliest/latest quartiles of available issue quarters; default uses resolved loans only, excluding current/unresolved loans. Each dimension independently decomposes the same overall change, so grade, term and purpose results are alternative explanations and must not be summed across dimensions. Effects are associations, not causal attributions. Worst segment requires at least 100 resolved loans per window. No month-on-book fields establish comparable exposure, so this is issue-quarter analysis, not a months-on-book curve.\n"
    (ROOT/'RCA.md').write_text(rca)
    clean_count=summary[1]
    c.close(); print(f'Credit: loaded={summary[0]:,}, clean={clean_count:,}, resolved={summary[2]:,}, default_rate={summary[3]:.6f}, quarters={len(qs)}')
    return {'total':summary[0],'clean':clean_count,'resolved':summary[2],'default_rate':summary[3],'worst':worst,'driver':driver,'pp':pp}

def _metrics(conn, expr, where, params=()):
    tp,fp,fn=conn.execute(f'SELECT SUM(CASE WHEN ({expr}) AND CAST(isFraud AS INTEGER)=1 THEN 1 ELSE 0 END), SUM(CASE WHEN ({expr}) AND CAST(isFraud AS INTEGER)=0 THEN 1 ELSE 0 END), SUM(CASE WHEN NOT ({expr}) AND CAST(isFraud AS INTEGER)=1 THEN 1 ELSE 0 END) FROM clean_paysim WHERE {where}',tuple(params)*3).fetchone()
    tp,fp,fn=(x or 0 for x in (tp,fp,fn)); prec=tp/(tp+fp) if tp+fp else 0; rec=tp/(tp+fn) if tp+fn else 0
    return {'tp':tp,'fp':fp,'fn':fn,'precision':prec,'recall':rec,'f1':2*prec*rec/(prec+rec) if prec+rec else 0,'alerts':tp+fp}

def _best_threshold(conn, candidates, make_expr, where):
    best=None
    for threshold in sorted(set(candidates)):
      m=_metrics(conn,make_expr(threshold),where)
      candidate=(m['f1'],m['precision'],threshold,m)
      if best is None or candidate[:3]>best[:3]: best=candidate
    return best[2],best[3]

def stage_fraud():
    c=sqlite3.connect(DB)
    steps=[int(r[0]) for r in c.execute('SELECT DISTINCT CAST(step AS INTEGER) FROM clean_paysim ORDER BY 1')]
    if len(steps)<2: raise RuntimeError('PaySim needs at least two distinct steps for time split')
    train_max=steps[max(0,math.ceil(len(steps)*.7)-1)]; test_min=steps[max(0,math.ceil(len(steps)*.7))]
    train=f'CAST(step AS INTEGER)<={train_max}'; test=f'CAST(step AS INTEGER)>={test_min}'
    # Threshold candidates computed only from first 70% time window.
    amounts=[float(r[0]) for r in c.execute(f"SELECT CAST(amount AS REAL) FROM clean_paysim WHERE {train} AND type='TRANSFER' ORDER BY CAST(amount AS REAL)")]
    import numpy as np
    if amounts:
      large_candidates=[float(np.quantile(amounts,q)) for q in (.75,.85,.90,.95,.99)]
      large,large_train=_best_threshold(c,large_candidates,lambda x:f"type='TRANSFER' AND CAST(amount AS REAL)>={x}",train)
    else: large,large_train=float('inf'),{}
    print(f'Fraud tuning: steps={len(steps)}, train_end={train_max}, test_start={test_min}, large-transfer threshold={large:.2f}',flush=True)
    drain="ABS(CAST(amount AS REAL)-CAST(oldbalanceOrg AS REAL))<0.01 AND ABS(CAST(newbalanceOrig AS REAL))<0.01"
    drain_train=_metrics(c,drain,train)
    # One-hour destination fan-in; time partition by step means no future step is used.
    has_fanin=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fraud_fanin'").fetchone()
    if not has_fanin:
      c.execute('CREATE TABLE fraud_fanin AS SELECT CAST(step AS INTEGER) step,nameDest,COUNT(*) dest_count FROM clean_paysim GROUP BY step,nameDest')
    c.execute('CREATE INDEX IF NOT EXISTS idx_fanin_dest ON fraud_fanin(step,nameDest,dest_count)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_fanin_step ON fraud_fanin(step,dest_count)')
    print('Fraud tuning: one-hour destination fan-in aggregates and indexes ready.',flush=True)
    fan_hist=[(int(r[0]),int(r[1])) for r in c.execute(f'SELECT dest_count,COUNT(*) FROM fraud_fanin WHERE step<={train_max} GROUP BY dest_count ORDER BY dest_count')]
    def exact_quantile(hist,q):
      n=sum(count for _,count in hist); target=math.floor((n-1)*q); cum=0
      for value,count in hist:
        cum+=count
        if cum>target: return value
      return 2
    fan_candidates=sorted(set(max(2,exact_quantile(fan_hist,q)) for q in (.90,.95,.99))) if fan_hist else [2]
    # Candidate score evaluated on training hours only.
    best_fan=None
    for threshold in fan_candidates:
      expr=f"EXISTS(SELECT 1 FROM fraud_fanin f WHERE f.step=CAST(p.step AS INTEGER) AND f.nameDest=p.nameDest AND f.dest_count>={threshold})"
      # Query alias p is required for correlated destination key.
      row=c.execute(f"SELECT SUM(CASE WHEN ({expr}) AND CAST(p.isFraud AS INTEGER)=1 THEN 1 ELSE 0 END),SUM(CASE WHEN ({expr}) AND CAST(p.isFraud AS INTEGER)=0 THEN 1 ELSE 0 END),SUM(CASE WHEN NOT ({expr}) AND CAST(p.isFraud AS INTEGER)=1 THEN 1 ELSE 0 END) FROM clean_paysim p WHERE CAST(p.step AS INTEGER)<={train_max}").fetchone()
      tp,fp,fn=(v or 0 for v in row); pr=tp/(tp+fp) if tp+fp else 0; re=tp/(tp+fn) if tp+fn else 0; f1=2*pr*re/(pr+re) if pr+re else 0
      if best_fan is None or (f1,pr,threshold)>(best_fan[0],best_fan[1],best_fan[2]): best_fan=(f1,pr,threshold,{'tp':tp,'fp':fp,'fn':fn,'precision':pr,'recall':re,'f1':f1,'alerts':tp+fp})
    fan_threshold=best_fan[2]; fan_train=best_fan[3]
    print(f'Fraud tuning: destination fan-in threshold={fan_threshold}',flush=True)
    bal="type IN ('TRANSFER','CASH_OUT') AND ABS(CAST(oldbalanceOrg AS REAL)-CAST(amount AS REAL)-CAST(newbalanceOrig AS REAL))>0.01"
    bal_train=_metrics(c,bal,train)
    rules=[('Large TRANSFER',f"type='TRANSFER' AND CAST(amount AS REAL)>={large}",large_train,'maximize training F1 over exact training TRANSFER amount quantiles 75%, 85%, 90%, 95%, and 99%'),('Account drain',drain,drain_train,'exact amount=old origin balance and new origin balance=0, with 0.01 balance tolerance'),('Destination fan-in',f"EXISTS(SELECT 1 FROM fraud_fanin f WHERE f.step=CAST(p.step AS INTEGER) AND f.nameDest=p.nameDest AND f.dest_count>={fan_threshold})",fan_train,'maximize training F1 over exact training destination-count quantiles 90%, 95%, and 99%'),('Origin balance inconsistency',bal,bal_train,'origin arithmetic mismatch greater than 0.01; candidate removed when training F1 did not beat baseline')]
    baseline_train=_metrics(c,'CAST(isFlaggedFraud AS INTEGER)=1',train)
    supported=[]
    for name,expr,m,method in rules:
      if m.get('tp',0)>0 and m.get('alerts',0)>0 and m.get('f1',0)>baseline_train['f1']: supported.append((name,expr,m,method))
    if not supported: raise RuntimeError('No candidate rule fired on training frauds; cannot form supported rule set')
    # SQL file owns rule evaluation; unsupported candidate flags disabled after table materialization.
    script=(ROOT/'sql'/'fraud_rules.sql').read_text()
    for tok,val in {':large_threshold':repr(large),':fanin_threshold':str(fan_threshold),':train_max':str(train_max),':test_min':str(test_min)}.items(): script=script.replace(tok,val)
    c.executescript(script)
    mapping={'Large TRANSFER':'rule_large_transfer','Account drain':'rule_account_drain','Destination fan-in':'rule_dest_fanin','Origin balance inconsistency':'rule_balance_inconsistency'}
    for name,col in mapping.items():
      if name not in {x[0] for x in supported}: c.execute(f'UPDATE fraud_alerts SET {col}=0')
    c.execute('UPDATE fraud_alerts SET rule_count=rule_large_transfer+rule_account_drain+rule_dest_fanin+rule_balance_inconsistency, combined_alert=CASE WHEN rule_large_transfer+rule_account_drain+rule_dest_fanin+rule_balance_inconsistency>0 THEN 1 ELSE 0 END')
    c.commit()
    # EDA SQL queried before interpreting rule support.
    eda=pd.read_sql_query((ROOT/'sql'/'fraud_eda.sql').read_text().split(';')[0],c)
    balance=pd.read_sql_query((ROOT/'sql'/'fraud_eda.sql').read_text().split(';')[1],c)
    c.execute('DROP VIEW IF EXISTS temp.fraud_test_alerts')
    c.execute('CREATE TEMP VIEW fraud_test_alerts AS SELECT * FROM fraud_alerts WHERE is_test=1')
    evals=pd.read_sql_query((ROOT/'sql'/'fraud_eval.sql').read_text(),c)
    test_steps=int(evals.test_steps.iloc[0])
    days=test_steps/24
    perfs=[]
    kept_names={x[0] for x in supported}|{'Combined rule set','Dataset isFlaggedFraud baseline'}
    for r in evals.to_dict('records'):
      if r['rule'] not in kept_names: continue
      alerts=int(r['alerts'] or 0)
      perfs.append({'rule':r['rule'],'alerts':alerts,'alerts_per_day':alerts/days if days else 0,'precision':r['precision'],'recall':r['recall'],'f1':r['f1'],'tp':r['tp'],'fp':r['fp'],'fn':r['fn']})
    perf=pd.DataFrame(perfs); perf.to_csv(ROOT/'tableau_extracts'/'fraud_rule_performance.csv',index=False)
    perf[['rule','alerts','alerts_per_day']].to_csv(ROOT/'tableau_extracts'/'alerts_per_day.csv',index=False)
    # transparent score: fired-rule count + transaction amount / max test alert amount
    max_amount=c.execute('SELECT MAX(amount) FROM fraud_alerts WHERE is_test=1 AND combined_alert=1').fetchone()[0] or 1
    queue=pd.read_sql_query(f"SELECT tx_id,step,type,amount,nameOrig,nameDest,actual,rule_count, (CASE WHEN rule_large_transfer=1 THEN 'Large TRANSFER;' ELSE '' END || CASE WHEN rule_account_drain=1 THEN 'Account drain;' ELSE '' END || CASE WHEN rule_dest_fanin=1 THEN 'Destination fan-in;' ELSE '' END || CASE WHEN rule_balance_inconsistency=1 THEN 'Origin balance inconsistency;' ELSE '' END) fired_rules, rule_count + amount/{max_amount} AS score FROM fraud_alerts WHERE is_test=1 AND combined_alert=1 ORDER BY score DESC,tx_id LIMIT 100",c)
    queue.to_csv(ROOT/'investigator_queue.csv',index=False)
    perf_comb=next(x for x in perfs if x['rule']=='Combined rule set')
    eda_rows='\n'.join(f"| {r.type} | {r.n:,} | {r.frauds:,} | {r.fraud_rate:.5%} | {r.avg_amount:.2f} |" for r in eda.itertuples())
    bal_rows='\n'.join(f"| {r.isFraud} | {r.n:,} | {r.avg_amount:.2f} | {r.min_amount:.2f} | {r.max_amount:.2f} | {r.avg_old_origin:.2f} | {r.avg_new_origin:.2f} | {r.avg_old_dest:.2f} | {r.avg_new_dest:.2f} |" for r in balance.itertuples())
    rule_desc='\n'.join(f"### {name}\n\n- Rule: `{expr}`\n- Train F1: {m['f1']:.5f}; train precision: {m['precision']:.5f}; train recall: {m['recall']:.5f}.\n- Tuning: {method}.\n- Test result: "+str(perf[perf.rule==name].iloc[0].to_dict())+"\n- Limit: PaySim is synthetic; same-hour fan-in is batch-scoped and may not represent online availability.\n" for name,expr,m,method in supported)
    doc=f"# Fraud rule analysis\n\nPaySim is synthetic. Dataset has {c.execute('SELECT COUNT(*) FROM clean_paysim').fetchone()[0]:,} cleaned transactions. EDA ran before rule selection.\n\n## EDA: fraud by transaction type\n\n| Type | Transactions | Fraud | Fraud rate | Mean amount |\n|---|---:|---:|---:|---:|\n{eda_rows}\n\n## Balance and amount patterns\n\n| isFraud | Transactions | Mean amount | Min amount | Max amount | Mean old origin balance | Mean new origin balance | Mean old destination balance | Mean new destination balance |\n|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n{bal_rows}\n\n## Split and tuning\n\nOrdered distinct steps: {len(steps)}. Training ended at step {train_max}; test began at step {test_min}. Split by distinct step, first 70% train, last 30% test. All thresholds selected using training only. Test window has {test_steps} hourly steps ({days:.2f} days). Candidate rules retained only when training F1 exceeded the dataset-flagged baseline F1 ({baseline_train['f1']:.5f}); this criterion was fixed before held-out evaluation.\n\n{rule_desc}\n## Rules dropped\n\n"+'\n'.join(f"- {n}: training F1 {m.get('f1',0):.5f} did not exceed flagged-baseline F1 {baseline_train['f1']:.5f}; training precision {m.get('precision',0):.5f}, recall {m.get('recall',0):.5f}." for n,_,m,_ in rules if n not in {x[0] for x in supported})+f"\n\nCombined test precision {perf_comb['precision']:.5f}, recall {perf_comb['recall']:.5f}, F1 {perf_comb['f1']:.5f}, alerts/day {perf_comb['alerts_per_day']:.3f}. Baseline included in `tableau_extracts/fraud_rule_performance.csv`. Performance on synthetic PaySim is not evidence of production fraud control performance.\n"
    (ROOT/'FRAUD_RULES.md').write_text(doc)
    transaction_count=c.execute('SELECT COUNT(*) FROM clean_paysim').fetchone()[0]
    print(f"Fraud: n={transaction_count:,}, train_end={train_max}, test_start={test_min}, supported_rules={len(supported)}, combined precision={perf_comb['precision']:.5f}, recall={perf_comb['recall']:.5f}, alerts/day={perf_comb['alerts_per_day']:.3f}")
    c.close()
    return {'n':transaction_count,'rules':len(supported),'perf':perf_comb,'performance':perf,'eda':eda,'balance':balance}

def stage_reporting(credit,fraud):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    from pptx import Presentation
    from pptx.util import Inches,Pt
    c=sqlite3.connect(DB); spec='''# Tableau dashboard specification

## KPI cards (7)

1. Total loans loaded — `loan_quality.csv`
2. Loans retained after quality checks — `loan_quality.csv`
3. Resolved-loan default rate — `vintage_default_rate.csv` (weighted across rows)
4. PaySim transaction count — `fraud_transaction_summary.csv`
5. Combined-rule precision — `fraud_rule_performance.csv`
6. Combined-rule recall — `fraud_rule_performance.csv`
7. Combined alerts per day — `alerts_per_day.csv`

## Charts, filters and extracts

- Issue-quarter line chart: `vintage_default_rate.csv`; filter issue quarter.
- Segment bar chart: `segment_default_rate.csv`; filter dimension and minimum resolved count.
- Active-book delinquency distribution: `delinquency_buckets.csv`; filter bucket.
- Fraud rule comparison bars for precision, recall, F1: `fraud_rule_performance.csv`; filter rule and test window.
- Operational alert volume by rule: `alerts_per_day.csv`; filter rule.
- Suggested global filters: issue quarter, segment dimension, segment, fraud rule. Fraud evaluates only the held-out final time window.
'''
    (ROOT/'DASHBOARD_SPEC.md').write_text(spec)
    clean_loans=c.execute('SELECT COUNT(*) FROM clean_loans').fetchone()[0]
    loan_quality=pd.DataFrame([{'metric':'Total loans loaded','value':credit['total']},{'metric':'Loans after cleaning','value':clean_loans}])
    loan_quality.to_csv(ROOT/'tableau_extracts'/'loan_quality.csv',index=False)
    pd.DataFrame([{'dataset':'PaySim','transactions':c.execute('SELECT COUNT(*) FROM clean_paysim').fetchone()[0]}]).to_csv(ROOT/'tableau_extracts'/'fraud_transaction_summary.csv',index=False)
    # Stream up to Excel's hard row cap, leaving header row.
    wb=Workbook(); ws=wb.active; ws.title='Data'; headers=['id','issue_d','loan_status','grade','loan_amnt','purpose','addr_state','grade_default_rate']; ws.append(headers)
    lookup=pd.read_sql_query("SELECT 'grade|'||COALESCE(NULLIF(grade,''),'Unknown') key, COUNT(*) loans, SUM(default_flag) defaults, AVG(default_flag) rate FROM credit_resolved GROUP BY grade",c)
    sl=wb.create_sheet('Segment_Lookup'); sl.append(list(lookup.columns))
    for row in lookup.itertuples(index=False,name=None): sl.append(list(row))
    for row in c.execute('SELECT id,issue_d,loan_status,grade,loan_amnt,purpose,addr_state FROM clean_loans ORDER BY rowid LIMIT 20000'):
      ws.append(list(row)+[f'=IFERROR(VLOOKUP("grade|"&D{ws.max_row+1},Segment_Lookup!$A$2:$D${len(lookup)+1},4,FALSE),"")'])
    summary=wb.create_sheet('Summary',0); summary.append(['Metric','Value'])
    for k,v in [('Loans loaded',credit['total']),('Loans after cleaning',c.execute('SELECT COUNT(*) FROM clean_loans').fetchone()[0]),('Resolved loans',credit['resolved']),('Resolved default rate',c.execute('SELECT AVG(default_flag) FROM credit_resolved').fetchone()[0]),('PaySim transactions',c.execute('SELECT COUNT(*) FROM clean_paysim').fetchone()[0]),('Combined precision',fraud['perf']['precision']),('Combined recall',fraud['perf']['recall']),('Combined alerts per day',fraud['perf']['alerts_per_day'])]: summary.append([k,v])
    ps=wb.create_sheet('Fraud_Performance'); ps.append(list(fraud['performance'].columns))
    for row in fraud['performance'].itertuples(index=False,name=None): ps.append(list(row))
    inst=wb.create_sheet('INSTRUCTIONS'); inst.append(['Excel reporting instructions']); inst.append(['Data sheet contains first 20,000 cleaned loans as a manageable workbook extract; underlying complete portfolio is in warehouse.sqlite.']); inst.append(['Select Data sheet, then Insert > PivotTable.']); inst.append(['Use issue_d, loan_status, grade, purpose, addr_state and loan_amnt to build pivots.']); inst.append(['VLOOKUP in Data!H:H returns grade resolved default rate from Segment_Lookup.'])
    for sh in wb.worksheets:
      sh.freeze_panes='A2'; sh.auto_filter.ref=sh.dimensions
      for cell in sh[1]: cell.font=Font(bold=True,color='FFFFFF'); cell.fill=PatternFill('solid',fgColor='17365D')
      for i,col in enumerate(sh.columns,1):
        sh.column_dimensions[get_column_letter(i)].width=min(32,max(12,max((len(str(x.value or '')) for x in list(col)[:1000]),default=10)+2))
    wb.save(ROOT/'report.xlsx')
    # Six-slide decision summary.
    prs=Presentation()
    def slide(title,lines):
      s=prs.slides.add_slide(prs.slide_layouts[1]); s.shapes.title.text=title; tf=s.placeholders[1].text_frame; tf.clear()
      for i,line in enumerate(lines):
        p=tf.paragraphs[0] if i==0 else tf.add_paragraph(); p.text=str(line); p.font.size=Pt(20); p.level=0
    dq_l=pd.read_csv(ROOT/'dq_report_loans.csv'); dq_p=pd.read_csv(ROOT/'dq_report_paysim.csv')
    slide('Scope',['Credit risk: Lending Club accepted loans, 2007–2018','Fraud risk: PaySim synthetic mobile money transactions','SQLite warehouse, SQL analytics, Tableau extracts, Excel and this deck'])
    slide('Data quality',[f"Loans loaded {credit['total']:,}; clean {clean_loans:,}; quarantined {int(dq_l.loc[dq_l.check=='invalid_or_out_of_range_date','rows_affected'].iloc[0])+int(dq_l.loc[dq_l.check=='negative_dti','rows_affected'].iloc[0]):,}",f"PaySim loaded {fraud['n']:,}; clean {c.execute('SELECT COUNT(*) FROM clean_paysim').fetchone()[0]:,}; quarantined {int(dq_p.loc[dq_p.check=='duplicate_key','rows_affected'].iloc[0])+int(dq_p.loc[dq_p.check=='negative_amount','rows_affected'].iloc[0])+int(dq_p.loc[dq_p.check=='negative_balance_or_step','rows_affected'].iloc[0])+int(dq_p.loc[dq_p.check=='unknown_category','rows_affected'].iloc[0]):,}"])
    slide('Credit findings',[f"Loans loaded {credit['total']:,}; resolved {credit['resolved']:,}",f"Resolved default rate {c.execute('SELECT AVG(default_flag) FROM credit_resolved').fetchone()[0]:.2%}",f"Issue-quarter vintage points {len(pd.read_csv(ROOT/'tableau_extracts'/'vintage_default_rate.csv'))}",f"Worst deterioration: {credit['worst']}"])
    slide('Root-cause analysis',[f"Worst segment: {credit['worst']}",f"Top marginal shift-share driver: {credit['driver']} ({credit['pp']:+.3f} pp)","Marginal shift-share dimensions overlap; association is not causation.","See RCA.md for windows, rates and caveats."])
    slide('Fraud rules and performance',[f"PaySim transactions {fraud['n']:,}; supported rules {fraud['rules']}",f"Combined precision {fraud['perf']['precision']:.3%}; recall {fraud['perf']['recall']:.3%}",f"Alerts/day {fraud['perf']['alerts_per_day']:.2f}","Held-out final 30% of ordered steps; thresholds selected on first 70%."])
    slide('Limitations',["US Lending Club data; not Navi portfolio or policy context.","Default rate uses resolved loans only; current loans censored/excluded.","Issue-quarter vintage rates only; no comparable months-on-book curves.","PaySim is synthetic; no production performance or regulator conclusions.","No real policy, underwriting, investigation or regulator context."])
    prs.save(ROOT/'summary.pptx'); c.close()
    print('Reporting: Tableau extracts, formatted Excel workbook, six-slide deck created.')

def write_docs(credit,fraud):
    vals=pd.read_csv(ROOT/'tableau_extracts'/'loan_quality.csv').set_index('metric').value
    spec=(ROOT/'DASHBOARD_SPEC.md').read_text(); kpi_section=spec.split('## Charts, filters and extracts')[0]; kpis=sum(1 for line in kpi_section.splitlines() if line.lstrip()[:1].isdigit() and '. ' in line)
    resume=f"# Resume numbers (computed from this run)\n\n| Value | Result | Code path |\n|---|---:|---|\n| Total loans loaded | {credit['total']:,} | `pipeline.py:stage_etl`, `raw_loans` |\n| Loans after cleaning | {int(vals['Loans after cleaning']):,} | `pipeline.py:stage_etl`, `clean_loans` |\n| Worst segment | {credit['worst']} | `pipeline.py:stage_credit`, `RCA.md` |\n| Percentage-point increase attributed to top driver | {credit['pp']:+.3f} pp ({credit['driver']}) | `pipeline.py:stage_credit`, `RCA.md` |\n| Dashboard KPI cards | {kpis} | `DASHBOARD_SPEC.md` |\n| Fraud rules | {fraud['rules']} | `pipeline.py:stage_fraud`, `FRAUD_RULES.md` |\n| PaySim transactions | {fraud['n']:,} | `pipeline.py:stage_etl`, `clean_paysim` |\n| Combined test precision | {fraud['perf']['precision']:.6f} | `pipeline.py:stage_fraud`, test window |\n| Combined test recall | {fraud['perf']['recall']:.6f} | `pipeline.py:stage_fraud`, test window |\n| Alerts per day | {fraud['perf']['alerts_per_day']:.6f} | `pipeline.py:stage_fraud`, 24 steps/day |\n"
    (ROOT/'RESUME_NUMBERS.md').write_text(resume)
    readme=f"""# Loan Portfolio Risk & Fraud Early-Warning Dashboard

Portfolio project for credit risk, fraud monitoring and data analytics. Built from Kaggle Lending Club accepted-loan records and PaySim synthetic transaction records. Python ETL loads chunked CSV data to SQLite `raw_*`, `clean_*`, and `rejected_*` tables; SQL files define analysis views/rules. Outputs: DQ reports, credit vintage/segment/delinquency analysis, fraud EDA and held-out rule metrics, RCA, Tableau extracts, Excel workbook and six-slide presentation.

## Run

Python 3.11+ required. Install packages with `python -m pip install -r requirements.txt`. Keep downloaded source files in `data/`; run all stages with `make all` (equivalent to `python pipeline.py all`). Re-run is idempotent: warehouse and generated outputs are rebuilt. Fixed split is by sorted unique PaySim step with first 70% training and final 30% testing; no random sampling is used. SQLite is local; no cloud services.

## Data sources and download

- Lending Club accepted loans 2007–2018 Q4: Kaggle `wordsforthewise/lending-club`, file `accepted_2007_to_2018Q4.csv.gz`.
- PaySim synthetic financial transactions: Kaggle `ealaxi/paysim1`, file `PS_20174392719_1491204439457_log.csv`.

Download via authenticated Kaggle CLI: `kaggle datasets download -d wordsforthewise/lending-club -f accepted_2007_to_2018Q4.csv.gz -p data` and `kaggle datasets download -d ealaxi/paysim1 -f PS_20174392719_1491204439457_log.csv -p data`. The pipeline reads these compressed downloads directly. Source headers are inspected and selected columns adapted to fields actually present.

## Architecture

```text
Kaggle CSV/GZ/ZIP → chunked Python ETL + DQ → SQLite raw_* / clean_* / rejected_*
                                                   ↓ SQL in sql/*.sql
                             credit & fraud marts/views → CSV extracts + XLSX + PPTX + Markdown
```

## Design decisions

- `id` uniquely keys Lending Club rows. PaySim has no transaction ID, so duplicate check uses step, origin, destination, type and amount as a composite signature. Rejected rows persist in `rejected_*` with JSON record and reason; rows with nulls persist in `flagged_*` with column list and JSON record while remaining in clean tables. Date parsing and range checks use observed `issue_d` values.
- Credit default = Charged Off or Default, including policy-status Charged Off variant when present. Rates use only Fully Paid, Charged Off and Default resolved loans. Current and other unresolved statuses are excluded to reduce censoring bias; this also means rates can differ from eventual full-cohort outcomes.
- Vintage is issue-quarter default rate on resolved loans only. Available fields do not establish comparable months-on-book exposure, so no true months-on-book curve is claimed.
- RCA compares earliest and latest quartiles of available issue quarters. Marginal shift-share is computed independently for grade, term and purpose; effects overlap and do not sum to portfolio change. No causal interpretation.
- Fraud candidates are selected from EDA and tuned on training period only. Test period is final 30% of ordered distinct hourly steps. Alerts/day = test alerts divided by test hours / 24. Investigative score is fired-rule count plus alert amount divided by max test-alert amount.
- Excel `Data` contains first 20,000 cleaned rows as a manageable workbook extract; full data remains in SQLite. Excel includes actual VLOOKUP formulas. Native PivotTables must be inserted manually as described in `INSTRUCTIONS`.

## Outputs

`warehouse.sqlite`, `dq_report_loans.csv`, `dq_report_paysim.csv`, `RCA.md`, `FRAUD_RULES.md`, `DASHBOARD_SPEC.md`, `tableau_extracts/`, `investigator_queue.csv`, `report.xlsx`, `summary.pptx`, `RESUME_NUMBERS.md`.

## Limitations

- Lending Club is US marketplace lending data. It is not Navi data, policy, product or customer behavior.
- Resolved-only default rates exclude unresolved/current loans, creating selection and censoring limitations.
- Issue-quarter vintage analysis is not exposure-aligned months-on-book analysis.
- PaySim is synthetic. Rule results are not evidence of production fraud detection quality or real loss prevention.
- Data contains no Navi decision policy, real investigator outcomes, RBI/SEBI/IRDA requirements or regulator context. This is an analytical portfolio exercise, not policy or compliance advice.
"""
    (ROOT/'README.md').write_text(readme)

def _tests():
    import subprocess
    p=subprocess.run([sys.executable,'-m','pytest','-q'],cwd=ROOT,text=True,capture_output=True)
    print(p.stdout.strip())
    if p.returncode: print(p.stderr); raise RuntimeError('pytest failed')

def all_stages():
    (ROOT/'tableau_extracts').mkdir(exist_ok=True)
    loan,pay=stage_etl(); _tests(); print(f"Stage summary: loans {loan['raw']:,}/{loan['clean']:,}/{loan['rejected']:,} raw/clean/rejected; PaySim {pay['raw']:,}/{pay['clean']:,}/{pay['rejected']:,}.")
    credit=stage_credit(); _tests(); print(f"Stage summary: resolved loans {credit['resolved']:,}; overall resolved default rate {credit['default_rate']:.2%}; worst {credit['worst']}.")
    fraud=stage_fraud(); _tests(); print(f"Stage summary: fraud rules {fraud['rules']}; test precision {fraud['perf']['precision']:.5f}; recall {fraud['perf']['recall']:.5f}.")
    stage_reporting(credit,fraud); write_docs(credit,fraud); _tests()
    print('Stage summary: Tableau extracts, Excel, PowerPoint, README, resume numbers generated.')

if __name__=='__main__' and len(sys.argv)>1:
    stage=sys.argv[1]
    if stage=='all': all_stages()
    elif stage=='etl': stage_etl(); _tests()
    elif stage=='credit': stage_credit(); _tests()
    elif stage=='fraud': stage_fraud(); _tests()
    elif stage=='reporting':
      credit=stage_credit()
      perf=pd.read_csv(ROOT/'tableau_extracts'/'fraud_rule_performance.csv')
      combined=perf[perf.rule=='Combined rule set'].iloc[0].to_dict()
      c=sqlite3.connect(DB); transaction_count=c.execute('SELECT COUNT(*) FROM clean_paysim').fetchone()[0]; c.close()
      fraud={'n':transaction_count,'rules':len(perf)-2,'perf':combined,'performance':perf}
      stage_reporting(credit,fraud); write_docs(credit,fraud); _tests()
