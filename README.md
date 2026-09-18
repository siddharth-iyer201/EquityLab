# EquityLab

Modern Texas Hold'em analysis powered by a custom Monte Carlo simulation engine.

EquityLab helps you study heads-up decisions with weighted ranges, equity/EV analysis,
board texture insights, hand-strength heatmaps, and deterministic decision explanations.

## Run The App

```sh
cd /Users/siddharthiyer/Downloads/holdem-equity
python3 -m pip install -r requirements.txt
python3 -m streamlit run app.py
```

Then open the local URL Streamlit prints, usually `http://localhost:8501`.

## Run Tests

```sh
python3 -m unittest discover -s tests
```
