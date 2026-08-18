"""
MICRO - the market-microstructure system.

  recorder.py       Binance WS -> book reconstruction -> events -> parquet/jsonl
  microfeatures.py  order-book/trade feature engineering (leak-free)
  labeler.py        triple-barrier labeling (BUY/SELL/NO-TRADE)
  train_micro.py    LightGBM 3-class + walk-forward + calibration + hard examples
  predictor.py      live inference -> the MICRO council member (shadow mode first)

Pipeline (see project discussion):
  LIVE EXCHANGE -> RECORDER -> RAW STORE -> FEATURES -> SEQUENCES ->
  TRIPLE-BARRIER LABELS -> LightGBM v1..vN (hard-example loop) ->
  CALIBRATION -> CONFIDENCE GATE -> MICRO council member -> ENTRY/TP/SL
"""
