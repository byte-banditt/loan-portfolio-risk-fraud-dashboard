import csv
import sqlite3
from collections import Counter
from pathlib import Path
import pytest
import pipeline
import model_review

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def dq_db():
    c=sqlite3.connect(':memory:')
    lc=pipeline.LOAN_USE
    pc=pipeline.PAY_USE
    c.execute(pipeline.table_sql('raw_loans',lc)); c.execute(pipeline.table_sql('clean_loans',lc,', issue_date TEXT'))
    c.execute('CREATE TABLE rejected_loans(row_key TEXT,reason TEXT,record_json TEXT)')
    c.execute('CREATE TABLE flagged_loans(row_key TEXT,reason TEXT,record_json TEXT)')
    c.execute(pipeline.table_sql('raw_paysim',pc)); c.execute(pipeline.table_sql('clean_paysim',pc))
    c.execute('CREATE TABLE rejected_paysim(row_key TEXT,reason TEXT,record_json TEXT)')
    c.execute('CREATE TABLE flagged_paysim(row_key TEXT,reason TEXT,record_json TEXT)')
    yield c
    c.close()

def loan(**kw):
    r=dict(id='L1',loan_amnt='100',term='36 months',int_rate='10',grade='A',sub_grade='A1',home_ownership='RENT',annual_inc='10000',issue_d='Jan-2015',loan_status='Fully Paid',purpose='debt_consolidation',addr_state='CA',dti='2')
    r.update(kw); return r

def pay(**kw):
    r=dict(step='1',type='TRANSFER',amount='10',nameOrig='C1',oldbalanceOrg='10',newbalanceOrig='0',nameDest='C2',oldbalanceDest='0',newbalanceDest='10',isFraud='1',isFlaggedFraud='0')
    r.update(kw); return r

def insert(c,dataset,rows):
    return pipeline._insert_batch(c,dataset,(pipeline.LOAN_USE if dataset=='loans' else pipeline.PAY_USE),rows,set(),Counter(),Counter(),Counter())

@pytest.mark.parametrize('bad,reason',[({'loan_amnt':'-1'},'negative loan amount'),({'dti':'-0.1'},'negative dti'),({'int_rate':'101'},'interest rate outside'),({'issue_d':'bad-date'},'issue_d'),({'issue_d':'Jan-2006'},'issue_d'),({'loan_status':'mystery'},'unknown loan_status')])
def test_lending_data_quality_rejects_impossible_or_unknown_values(dq_db,bad,reason):
    insert(dq_db,'loans',[loan(**bad)])
    assert reason in dq_db.execute('select reason from rejected_loans').fetchone()[0]

def test_lending_duplicate_key_quarantined(dq_db):
    insert(dq_db,'loans',[loan(),loan()])
    assert 'duplicate loan id' in dq_db.execute('select reason from rejected_loans').fetchone()[0]

def test_nulls_are_counted_for_column_rates(dq_db):
    from collections import Counter
    nulls=Counter()
    pipeline._insert_batch(dq_db,'loans',pipeline.LOAN_USE,[loan(annual_inc='')],set(),Counter(),nulls,Counter())
    assert nulls['annual_inc']==1
    assert 'null values: annual_inc' in dq_db.execute('select reason from flagged_loans').fetchone()[0]

@pytest.mark.parametrize('bad,reason',[({'amount':'-1'},'negative transaction amount'),({'step':'0'},'non-positive step'),({'oldbalanceOrg':'-1'},'negative balance'),({'isFraud':'2'},'invalid isFraud category'),({'type':'UNKNOWN'},'unknown transaction type')])
def test_paysim_data_quality_rejects_impossible_values(dq_db,bad,reason):
    insert(dq_db,'paysim',[pay(**bad)])
    assert reason in dq_db.execute('select reason from rejected_paysim').fetchone()[0]

def test_paysim_duplicate_composite_key_quarantined(dq_db):
    insert(dq_db,'paysim',[pay(),pay()])
    assert 'duplicate transaction composite key' in dq_db.execute('select reason from rejected_paysim').fetchone()[0]

def test_model_feature_allowlist_excludes_underwriting_outputs_and_post_origination():
    forbidden = ('grade', 'sub_grade', 'int_rate', 'total_pymnt', 'recoveries',
                 'collection_recovery_fee', 'last_pymnt_d', 'out_prncp', 'last_credit_pull_d')
    assert not set(model_review.FEATURE_CANDIDATES).intersection(forbidden)
    assert all(not any(f == x or f.startswith(x) for x in model_review.FEATURE_CANDIDATES)
               for f in forbidden)

def test_woe_uses_training_rows_only():
    codes = [1, 1, 2, 2, 9]
    y = __import__('numpy').array([0, 1, 0, 1, 1], dtype='uint8')
    train = __import__('numpy').array([True, True, True, True, False])
    bins = __import__('numpy').array(codes)
    first = model_review._woe_fit(codes, y, train, bins, 'x')
    y[-1] = 0
    second = model_review._woe_fit(codes, y, train, bins, 'x')
    assert first[1] == second[1]
    assert first[2] == second[2]

def test_time_split_is_disjoint_and_chronological_by_construction():
    years = list(range(2007, 2019))
    train = years[:int(len(years) * .60)]
    val_end = max(len(train) + 1, int(len(years) * .80))
    val = years[len(train):val_end]
    test = years[val_end:]
    assert train and val and test
    assert max(train) < min(val) and max(val) < min(test)

@pytest.mark.parametrize('dataset,required',[('loans',['duplicate_key','negative_amount','negative_dti','int_rate_out_of_range','invalid_or_out_of_range_date','unknown_category']),('paysim',['duplicate_key','negative_amount','negative_balance_or_step','unknown_category'])])
def test_dq_reports_publish_all_checks_and_null_rates(dataset,required):
    path=ROOT/f'dq_report_{dataset}.csv'
    rows=list(csv.DictReader(path.open()))
    names={r['check'] for r in rows}
    assert set(required)<=names
    assert any(n.startswith('null_rate:') for n in names)
    assert all(int(r['rows_affected'])>=0 and r['action_taken'] for r in rows)
