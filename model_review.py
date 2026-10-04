"""Time-based Lending Club scorecard, validation, drift and strategy analysis."""
from __future__ import annotations

import csv
import gzip
import io
import json
import math
import sqlite3
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, roc_curve

SEED = 20261004
NUMERIC = [
    "loan_amnt", "annual_inc", "dti", "delinq_2yrs", "fico_range_low",
    "inq_last_6mths", "open_acc", "pub_rec", "revol_util", "total_acc",
    "collections_12_mths_ex_med", "acc_now_delinq", "delinq_amnt",
    "pub_rec_bankruptcies", "tax_liens",
]
CATEGORICAL = ["term", "emp_length", "home_ownership", "verification_status", "purpose", "addr_state", "application_type"]
FEATURE_CANDIDATES = NUMERIC + CATEGORICAL
OUTCOME = {"fully paid": 0, "charged off": 1, "default": 1,
           "does not meet the credit policy. status:charged off": 1}
UNDERWRITING_OUTPUTS = ("grade", "sub_grade", "int_rate")
POST_ORIGINATION = ("total_pymnt", "recoveries", "collection_recovery_fee", "last_pymnt_",
                    "out_prncp", "last_credit_pull_d")


def _open_source(path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8-sig", newline="")
    if path.suffix == ".zip":
        z = zipfile.ZipFile(path)
        return io.TextIOWrapper(z.open(z.namelist()[0]), encoding="utf-8-sig", newline="")
    return path.open("r", encoding="utf-8-sig", newline="")


def _woe_fit(codes, y, train_mask, bins, feature):
    ids = np.unique(bins[train_mask])
    good_total = int(((y == 0) & train_mask).sum())
    bad_total = int(((y == 1) & train_mask).sum())
    stats = {}
    iv = 0.0
    k = max(len(ids), 1)
    for b in ids:
        m = train_mask & (bins == b)
        good = int(((y == 0) & m).sum())
        bad = int(((y == 1) & m).sum())
        gd = (good + .5) / (good_total + .5 * k)
        bd = (bad + .5) / (bad_total + .5 * k)
        w = math.log(gd / bd)
        stats[int(b)] = w
        iv += (gd - bd) * w
    # unseen validation/test bins use neutral evidence.
    return np.fromiter((stats.get(int(b), 0.0) for b in bins), dtype=np.float32, count=len(bins)), iv, stats


def _metrics(y, p):
    auc = float(roc_auc_score(y, p))
    fpr, tpr, _ = roc_curve(y, p)
    ks = float(np.max(tpr - fpr))
    return {"auc": auc, "ks": ks, "gini": 2 * auc - 1}


def _load_features(db: Path, source: Path):
    """Build compact model input table from inspected source headers, idempotently."""
    with _open_source(source) as f:
        headers = next(csv.reader(f))
    if "issue_d" not in headers or "loan_status" not in headers or "id" not in headers:
        raise RuntimeError(f"Model needs id, issue_d and loan_status; observed headers: {headers}")
    features = [c for c in FEATURE_CANDIDATES if c in headers]
    missing = [c for c in FEATURE_CANDIDATES if c not in headers]
    forbidden_present = [c for c in headers if any(c == p or c.startswith(p) for p in POST_ORIGINATION)]
    underwriting_present = [c for c in UNDERWRITING_OUTPUTS if c in headers]
    if not features:
        raise RuntimeError("No inspected application-time features available")
    usecols = ["issue_d", "loan_status", "grade", "id"] + features
    usecols = list(dict.fromkeys(c for c in usecols if c in headers))
    c = sqlite3.connect(db)
    c.execute("DROP VIEW IF EXISTS model_review_resolved")
    c.execute("DROP VIEW IF EXISTS model_review_year_counts")
    c.execute("DROP TABLE IF EXISTS model_input_loans")
    col_sql = ",".join('"' + x + '" TEXT' for x in ["issue_date", "issue_year", "default_flag", "grade"] + features)
    c.execute(f"CREATE TABLE model_input_loans ({col_sql})")
    c.execute("CREATE TABLE IF NOT EXISTS rejected_model_loans (source_row INTEGER, reason TEXT, record_json TEXT)")
    c.execute("DELETE FROM rejected_model_loans")
    rejected_reasons = {}
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='rejected_loans'").fetchone():
        for reason, record_json in c.execute("SELECT reason,record_json FROM rejected_loans"):
            try:
                rejected_row = json.loads(record_json)
            except (TypeError, json.JSONDecodeError):
                continue
            rid = str(rejected_row.get("id", ""))
            if rid and "duplicate loan id" not in reason:
                rejected_reasons[rid] = reason
    raw_n = resolved_n = quarantined_n = 0
    seen_ids = set()
    sql = f"INSERT INTO model_input_loans VALUES ({','.join('?' for _ in range(4 + len(features)))} )"
    with _open_source(source) as f:
        reader = pd.read_csv(f, usecols=usecols, chunksize=100_000, dtype=str, keep_default_na=False)
        offset = 0
        for part in reader:
            raw_n += len(part)
            status = part.loan_status.str.strip().str.lower()
            y = status.map(OUTCOME)
            resolved = y.notna()
            dates = pd.to_datetime(part.issue_d, format="%b-%Y", errors="coerce")
            valid_date = dates.notna() & dates.between("2007-01-01", "2018-12-31")
            dq_rejected = part.id.astype(str).isin(rejected_reasons) if "id" in part else pd.Series(False, index=part.index)
            duplicate_flags = []
            for loan_id in part.id.astype(str):
                duplicate_flags.append(loan_id in seen_ids)
                seen_ids.add(loan_id)
            duplicate = pd.Series(duplicate_flags, index=part.index)
            amount = pd.to_numeric(part["loan_amnt"], errors="coerce") if "loan_amnt" in part else pd.Series(np.nan, index=part.index)
            dti = pd.to_numeric(part["dti"], errors="coerce") if "dti" in part else pd.Series(np.nan, index=part.index)
            bad_amount = amount.notna() & (amount < 0)
            bad_dti = dti.notna() & (dti < 0)
            invalid = resolved & (~valid_date | dq_rejected | duplicate | bad_amount | bad_dti)
            if invalid.any():
                quarantined_n += int(invalid.sum())
                rejects = []
                for local_i in np.flatnonzero(invalid.to_numpy()):
                    row = part.iloc[local_i]
                    reasons = []
                    if not valid_date.iloc[local_i]: reasons.append("unparseable or out-of-range issue_d")
                    if str(row.get("id", "")) in rejected_reasons: reasons.append(rejected_reasons[str(row.get("id", ""))])
                    if duplicate.iloc[local_i]: reasons.append("duplicate loan id")
                    if bad_amount.iloc[local_i]: reasons.append("negative loan amount")
                    if bad_dti.iloc[local_i]: reasons.append("negative dti")
                    rejects.append((offset + int(local_i), "; ".join(dict.fromkeys(reasons)), json.dumps(row.to_dict(), ensure_ascii=False)))
                c.executemany("INSERT INTO rejected_model_loans VALUES (?,?,?)", rejects)
            keep = resolved & valid_date & ~dq_rejected & ~duplicate & ~bad_amount & ~bad_dti
            if keep.any():
                q = part.loc[keep]
                d = dates.loc[keep]
                date_text = d.dt.strftime("%Y-%m-%d").to_numpy()
                years_text = d.dt.year.astype(str).to_numpy()
                labels_text = y.loc[keep].astype(int).astype(str).to_numpy()
                arrays = [q.get("grade", pd.Series([""] * len(q))).to_numpy()]
                arrays.extend(q[f].to_numpy() for f in features)
                records = zip(date_text, years_text, labels_text, *arrays)
                c.executemany(sql, records)
                resolved_n += len(q)
            offset += len(part)
            if offset % 500_000 < len(part):
                c.commit()
                print(f"Model input: scanned {offset:,}; resolved {resolved_n:,}", flush=True)
    c.execute("CREATE INDEX idx_model_year ON model_input_loans(issue_year)")
    c.executescript((Path(__file__).resolve().parent / "sql" / "model_review.sql").read_text())
    c.commit()
    print(f"Model input: raw={raw_n:,}, resolved={resolved_n:,}, DQ-quarantined resolved rows={quarantined_n:,}, features={features}; unavailable={missing}; underwriting benchmark-only={underwriting_present}; post-origination excluded={forbidden_present}")
    c.close()
    return {"raw": raw_n, "resolved": resolved_n, "invalid": quarantined_n, "features": features, "missing": missing, "forbidden": forbidden_present, "underwriting": underwriting_present}


def run(db: Path, source: Path, output: Path, extracts: Path):
    loaded = _load_features(db, source)
    c = sqlite3.connect(db)
    years = pd.read_sql_query("SELECT issue_year, resolved_loans FROM model_review_year_counts", c)
    distinct = years.issue_year.astype(int).tolist()
    if len(distinct) < 3:
        raise RuntimeError("Time-based train/validation/test requires at least three issue years")
    train_end_idx = max(1, int(len(distinct) * .60))
    val_end_idx = max(train_end_idx + 1, int(len(distinct) * .80))
    val_end_idx = min(val_end_idx, len(distinct) - 1)
    train_years = distinct[:train_end_idx]
    val_years = distinct[train_end_idx:val_end_idx]
    test_years = distinct[val_end_idx:]
    query_cols = ["issue_year", "default_flag", "grade"] + loaded["features"]
    query = "SELECT " + ",".join('"'+x+'"' for x in query_cols) + " FROM model_review_resolved ORDER BY issue_date,grade"
    n = loaded["resolved"]
    y = np.empty(n, dtype=np.uint8); yr = np.empty(n, dtype=np.int16); grade_codes = np.empty(n, dtype=np.int16)
    grade_map = {}; feature_codes = {f: np.empty(n, dtype=np.int32 if f in CATEGORICAL else np.float32) for f in loaded["features"]}
    category_maps = {f: {} for f in loaded["features"] if f in CATEGORICAL}
    offset = 0
    for chunk in pd.read_sql_query(query, c, chunksize=50_000):
        k = len(chunk); sl = slice(offset, offset + k)
        y[sl] = chunk.default_flag.astype(np.uint8).to_numpy()
        yr[sl] = chunk.issue_year.astype(np.int16).to_numpy()
        for i, value in enumerate(chunk.grade.fillna("")):
            if value not in grade_map: grade_map[value] = len(grade_map) + 1
            grade_codes[offset + i] = grade_map[value]
        for f in loaded["features"]:
            if f in CATEGORICAL:
                mapping = category_maps[f]
                vals = chunk[f].fillna("").astype(str)
                for value in vals.unique():
                    if value and value not in mapping: mapping[value] = len(mapping) + 1
                feature_codes[f][sl] = vals.map(lambda v: mapping.get(v, 0)).to_numpy(dtype=np.int32)
            else:
                feature_codes[f][sl] = pd.to_numeric(chunk[f], errors="coerce").to_numpy(dtype=np.float32)
        offset += k
    if offset != n: raise RuntimeError(f"Model input count mismatch: expected {n}, read {offset}")
    train_mask = np.isin(yr, train_years); val_mask = np.isin(yr, val_years); test_mask = np.isin(yr, test_years)
    if not train_mask.any() or not val_mask.any() or not test_mask.any(): raise RuntimeError("Empty temporal split")
    woe_columns = []; iv_rows = []; fitted_bins = {}; fitted_woe = {}
    # Fit all bin edges and WoE maps on training vintages only.
    for f in loaded["features"]:
        values = feature_codes[f]
        if f in CATEGORICAL:
            bins = values.astype(np.int32)
            edges = None
        else:
            valid = np.isfinite(values[train_mask])
            raw = values[train_mask][valid]
            edges = np.unique(np.quantile(raw, np.linspace(0, 1, 11))) if len(raw) else np.array([])
            bins = np.zeros(n, dtype=np.int16)  # missing bin
            if len(edges) > 1:
                bins[np.isfinite(values)] = np.digitize(values[np.isfinite(values)], edges[1:-1], right=True).astype(np.int16) + 1
        transformed, iv, woe = _woe_fit(values, y, train_mask, bins, f)
        woe_columns.append(transformed); iv_rows.append({"feature": f, "information_value": float(iv), "kind": "categorical" if f in CATEGORICAL else "numeric"})
        fitted_bins[f] = (bins, edges); fitted_woe[f] = woe
    X = np.column_stack(woe_columns).astype(np.float32)
    model = LogisticRegression(random_state=SEED, solver="lbfgs", max_iter=300, C=1.0)
    model.fit(X[train_mask], y[train_mask])
    val_p = model.predict_proba(X[val_mask])[:, 1]; test_p = model.predict_proba(X[test_mask])[:, 1]
    val_metrics = _metrics(y[val_mask], val_p); test_metrics = _metrics(y[test_mask], test_p)
    # Grade-only reference model, fitted on identical training vintages and evaluated on identical test rows.
    gX = np.column_stack([grade_codes == code for code in sorted(set(grade_codes[train_mask]))]).astype(np.float32)
    grade_model = LogisticRegression(random_state=SEED, solver="lbfgs", max_iter=300, C=1.0).fit(gX[train_mask], y[train_mask])
    grade_p = grade_model.predict_proba(gX[test_mask])[:, 1]
    grade_metrics = _metrics(y[test_mask], grade_p)
    # Points: 600 at 50:1 good:bad odds; 20 points per odds doubling.
    factor = 20 / math.log(2); offset_points = 600 - factor * math.log(50)
    logits = np.log(np.clip(test_p, 1e-12, 1-1e-12) / np.clip(1-test_p, 1e-12, 1))
    scores = offset_points - factor * logits
    score_all = np.empty(n, dtype=np.float32)
    score_all[test_mask] = scores
    all_p = np.empty(n, dtype=np.float32); all_p[test_mask] = test_p
    # Calibration table from held-out test scores.
    test_frame = pd.DataFrame({"score": scores, "observed_default": y[test_mask]})
    test_frame["score_decile"] = pd.qcut(test_frame.score.rank(method="first"), 10, labels=False) + 1
    calibration = test_frame.groupby("score_decile", as_index=False).agg(loans=("observed_default", "size"), mean_score=("score", "mean"), observed_default_rate=("observed_default", "mean"))
    # Train score bounds and feature bins define PSI buckets; no later window determines bins.
    train_pred = model.predict_proba(X[train_mask])[:, 1]
    train_logit = np.log(np.clip(train_pred, 1e-12, 1-1e-12) / np.clip(1-train_pred, 1e-12, 1))
    train_scores = offset_points - factor * train_logit
    score_edges = np.unique(np.quantile(train_scores, np.linspace(0, 1, 11)))
    psi_rows = []
    for feature in ["score"] + loaded["features"]:
        base_values = train_scores if feature == "score" else feature_codes[feature][train_mask]
        years_later = [z for z in distinct if z > train_years[-1]]
        if feature == "score":
            train_bucket = np.digitize(base_values, score_edges[1:-1])
        else:
            train_bucket = fitted_bins[feature][0][train_mask]
        bins_unique = np.union1d(np.unique(train_bucket), np.array([0]))
        base_share = np.array([(train_bucket == b).mean() for b in bins_unique])
        for year in years_later:
            mask = yr == year
            if feature == "score":
                pp = model.predict_proba(X[mask])[:, 1]
                ll = np.log(np.clip(pp, 1e-12, 1-1e-12) / np.clip(1-pp, 1e-12, 1))
                later_values = offset_points - factor * ll
                later_bucket = np.digitize(later_values, score_edges[1:-1])
            else:
                later_bucket = fitted_bins[feature][0][mask]
                if feature in CATEGORICAL:
                    trained_ids = bins_unique
                    later_bucket = np.where(np.isin(later_bucket, trained_ids), later_bucket, 0)
            later_share = np.array([(later_bucket == b).mean() for b in bins_unique])
            a = np.clip(base_share, 1e-6, None); b = np.clip(later_share, 1e-6, None)
            psi = float(np.sum((b-a) * np.log(b/a)))
            status = "action" if psi > .25 else "watch" if psi > .10 else "stable"
            psi_rows.append({"feature": feature, "issue_year": year, "train_years": ",".join(map(str, train_years)), "psi": psi, "status": status, "loans": int(mask.sum())})
    psi = pd.DataFrame(psi_rows)
    # Fixed quantile sweep, evaluation only; no cutoff is recommended.
    qvals = np.unique(np.quantile(scores, np.linspace(0, 1, 11)))
    cutoffs = sorted(set(float(q) for q in qvals) | {float(scores.max() + 1)})
    strategy_rows = []
    yt = y[test_mask]
    for cutoff in cutoffs:
        approved = scores >= cutoff
        n_approved = int(approved.sum()); n_declined = int((~approved).sum())
        strategy_rows.append({"score_cutoff": cutoff, "test_loans": len(scores), "approved_loans": n_approved,
            "approval_rate": n_approved / len(scores), "bad_rate_approved": float(yt[approved].mean()) if n_approved else "NOT AVAILABLE",
            "bad_rate_declined": float(yt[~approved].mean()) if n_declined else "NOT AVAILABLE", "declined_loans": n_declined})
    strategy = pd.DataFrame(strategy_rows)
    # Save trained coefficients, IV and feature bin definitions for reproducibility/audit.
    output.mkdir(parents=True, exist_ok=True); extracts.mkdir(parents=True, exist_ok=True)
    iv_df = pd.DataFrame(iv_rows).sort_values("information_value", ascending=False)
    metrics = pd.DataFrame([
        {"model": "WoE logistic scorecard", "window": "validation", **val_metrics, "rows": int(val_mask.sum()), "years": ",".join(map(str, val_years))},
        {"model": "WoE logistic scorecard", "window": "test", **test_metrics, "rows": int(test_mask.sum()), "years": ",".join(map(str, test_years))},
        {"model": "grade-only logistic baseline", "window": "test", **grade_metrics, "rows": int(test_mask.sum()), "years": ",".join(map(str, test_years))},
    ])
    metrics.to_csv(extracts / "model_performance.csv", index=False)
    calibration.to_csv(extracts / "score_calibration.csv", index=False)
    psi.to_csv(extracts / "psi_by_year.csv", index=False)
    strategy.to_csv(extracts / "strategy_sweep.csv", index=False)
    iv_df.to_csv(extracts / "feature_information_value.csv", index=False)
    # Explicit points conversion details and fitted model state.
    feature_points = {}
    for i, f in enumerate(loaded["features"]):
        coeff = float(model.coef_[0][i])
        feature_points[f] = {str(bin_id): float(-factor * coeff * woe) for bin_id, woe in fitted_woe[f].items()}
    (output / "scorecard.json").write_text(json.dumps({"seed": SEED, "features": loaded["features"], "categorical": CATEGORICAL,
       "numeric": NUMERIC, "intercept": float(model.intercept_[0]), "coefficients_woe": dict(zip(loaded["features"], model.coef_[0].tolist())),
       "points_factor": factor, "points_offset": offset_points, "base_points": float(offset_points - factor * model.intercept_[0]), "feature_bin_points": feature_points,
       "categorical_value_codes": category_maps,
       "train_years": train_years, "validation_years": val_years, "test_years": test_years,
       "feature_bins": {f: {"woe": w, "edges": None if e is None else e.tolist()} for f, (b, e), w in [(f, fitted_bins[f], fitted_woe[f]) for f in loaded["features"]]},
       "information_value": iv_rows}, indent=2))
    c.close()
    # Memo generated only from computed run values.
    top_iv = iv_df.iloc[0]
    max_psi = psi.loc[psi.feature != "score"].sort_values("psi", ascending=False).iloc[0]
    flags = psi.status.value_counts().to_dict()
    calibration_rows = "\n".join(f"| {int(r.score_decile)} | {int(r.loans):,} | {r.mean_score:.2f} | {r.observed_default_rate:.4%} |" for r in calibration.itertuples())
    feature_lines = ", ".join(loaded["features"])
    memo = f"""# Credit model review

## Validation memo

**Purpose.** Transparent Lending Club default risk scorecard prototype; not a lending policy recommendation.

**Data and target.** Source contains {loaded['raw']:,} rows. Resolved modeling cohort contains {loaded['resolved']:,} loans after issue-date and existing DQ validation ({loaded['invalid']:,} resolved rows rejected by date or existing data-quality checks). Target: Charged Off, Default, and observed policy Charged Off variant versus Fully Paid. Current/unresolved outcomes excluded. Application-time feature candidates present and used: {feature_lines}. Train vintages {train_years[0]}–{train_years[-1]}; validation {val_years}; test {test_years}; splits use issue year, with no random split. WoE quantile boundaries and mappings fitted on training only; fixed seed {SEED}.

**Leakage controls.** Excluded underwriting outputs grade, sub_grade and int_rate from model inputs; grade used only for same-period grade-only benchmark. Excluded observed post-origination fields: {', '.join(loaded['forbidden'])}. No loan status or issue date is a predictor; issue date only assigns temporal partitions. Rows with unavailable fields use missing bins. Numeric IV top feature: **{top_iv.feature}**, {top_iv.information_value:.5f}.

**Performance.** Validation scorecard AUC {val_metrics['auc']:.5f}, KS {val_metrics['ks']:.5f}, Gini {val_metrics['gini']:.5f}. Test scorecard AUC {test_metrics['auc']:.5f}, KS {test_metrics['ks']:.5f}, Gini {test_metrics['gini']:.5f}; grade-only test baseline AUC {grade_metrics['auc']:.5f}, KS {grade_metrics['ks']:.5f}, Gini {grade_metrics['gini']:.5f}. Points use 20 points per odds doubling, with score 600 at 50:1 good-to-bad odds; these are display anchors.

**Calibration.** Test score deciles are ordered by points: decile 1 has lowest score/highest modeled risk; decile 10 has highest score/lowest modeled risk.

| Decile | Loans | Mean score | Observed default rate |
|---:|---:|---:|---:|
{calibration_rows}

**Stability.** Largest feature PSI is {max_psi.feature}, issue year {int(max_psi.issue_year)}, PSI {max_psi.psi:.5f} ({max_psi.status}). Across score and feature/year checks: {int(flags.get('stable',0))} stable, {int(flags.get('watch',0))} watch, {int(flags.get('action',0))} action. Thresholds: >0.10 watch; >0.25 action. Score PSI included separately in `tableau_extracts/psi_by_year.csv`.

**Limitations.** US Lending Club data does not represent a target lender or its policy. Resolved-only selection excludes unresolved loans and creates selection/censoring bias. Rejected-applicant outcomes are unobserved; reject inference is unavailable. Strategy sweep is descriptive, not causal, and makes no cutoff recommendation. No local underwriting policy, target population, regulator context or production outcome monitoring is available. Temporal cohorts and source practices may differ materially from current lending.
"""
    (output / "MODEL_REVIEW.md").write_text(memo)
    print(f"Model review: resolved={loaded['resolved']:,}; train={train_years[0]}-{train_years[-1]} n={int(train_mask.sum()):,}; validation={val_years} AUC={val_metrics['auc']:.5f}; test={test_years} AUC={test_metrics['auc']:.5f}, KS={test_metrics['ks']:.5f}, Gini={test_metrics['gini']:.5f}; grade baseline AUC={grade_metrics['auc']:.5f}; features={len(loaded['features'])}; max feature PSI={max_psi.psi:.5f};")
    return {"loaded": loaded, "train_years": train_years, "validation_years": val_years, "test_years": test_years,
            "train_n": int(train_mask.sum()), "validation_n": int(val_mask.sum()), "test_n": int(test_mask.sum()),
            "validation": val_metrics, "test": test_metrics, "grade": grade_metrics, "features": loaded["features"],
            "max_psi": float(max_psi.psi), "max_psi_feature": max_psi.feature, "metrics": metrics, "psi": psi}
