# Level 2b — Routing data

Training and evaluation data for the topic classifier. The classifier
itself is a logistic-regression model trained on synthetic claims; see
`../classifier/train.py`.

## Files

- `synthetic_train.csv` — **gitignored.** Generated via a separate
  browser-Claude session and dropped here before training. Regenerate
  any time the topic taxonomy or keyword tables change meaningfully.
- `real_test.csv` — **committed.** Hand-annotated claims used as a
  held-out evaluation set. Keep small (tens of rows) and high-signal.

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
    backend/app/level2b_routing/data/synthetic_train.csv \
    --out backend/app/level2b_routing/classifier/model.pkl
```

`model.pkl` is gitignored — every developer trains locally.
