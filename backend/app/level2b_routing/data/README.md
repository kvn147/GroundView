# Level 2b — Routing data

Training and evaluation data for the topic classifier. The classifier
itself is a logistic-regression model trained on synthetic claims; see
`../classifier/train.py`.

## Files

- `synthetic_train_*.csv` — **committed.** Numbered batches of
  generated training claims spanning the 8-topic taxonomy.
- `liar_train.csv` / `liar_eval.csv` — **committed.** Real political
  claims from the LIAR dataset (Wang 2017), remapped to the 8-topic
  taxonomy by `fetch_liar.py`. ~10k rows training, ~200 eval.
- `combined_train.csv` — **committed.** The synthetic batches + LIAR
  training set concatenated and deduped. This is what
  `train.py` consumes by default. Regenerate when synthetic batches
  or LIAR are updated.
- `real_test.csv` — hand-annotated claims used as a held-out
  evaluation set. Keep small (tens of rows) and high-signal.

## CSV schema

Both files share the same header and column order:

```
claim_text,immigration,healthcare,crime,economy,education
```

Rules:

- `claim_text` is double-quoted. Escape literal double-quotes inside a
  claim by doubling them (`""`), per RFC 4180.
- The five label columns are binary (`0` or `1`).
- Multi-label rows are allowed — a claim can hit more than one topic.
- An all-zeros row is the explicit negative class (out-of-scope for
  every canonical topic). Include some of these so the classifier
  learns when to abstain.

Example:

```csv
claim_text,immigration,healthcare,crime,economy,education
"Senator Brown voted against HR 4842 in March 2019.",0,0,0,0,0
"Inflation reached its highest point since 1981 last quarter.",0,0,0,1,0
"The new bill expands Medicaid in 12 additional states.",0,1,0,0,0
"Border crossings dropped 40% after the policy change.",1,0,0,0,0
"She said the murder rate is the highest in 30 years.",0,0,1,0,0
"Student loan forgiveness will cost taxpayers $400 billion.",0,0,0,1,1
```

## Training

```
python -m backend.app.level2b_routing.classifier.train \
    backend/app/level2b_routing/data/combined_train.csv \
    --out backend/app/level2b_routing/classifier/model.pkl
```

`model.pkl` is **not committed** — at 32 MB it overruns git's default
HTTPS push buffer and breaks pushes for everyone else. Every
contributor trains it locally once after clone using the command
above. The pin on `scikit-learn==1.8.0` and `joblib==1.5.3` (see
`backend/requirements.txt`) keeps the artifact reproducible: as long
as you install the pinned deps, training on the committed
`combined_train.csv` produces a model the router will accept.

Retrain whenever the topic taxonomy, keyword tables, or training data
change.
