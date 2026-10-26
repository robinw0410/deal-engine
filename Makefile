PY ?= python3
DAYS ?= 21
PORT ?= 8081

.PHONY: demo demo-data demo-de serve-demo serve-demo-de test clean-demo

## demo: generate invented data, run the full pipeline over $(DAYS) simulated days, serve the pages
demo: demo-data serve-demo

demo-data:
	$(PY) -m deal_engine.demo.run_demo --days $(DAYS) --quiet

## demo-de: like demo-data, but with German locale (texts, report, prompts) into data/demo-de
demo-de:
	$(PY) -m deal_engine.demo.run_demo --days $(DAYS) --quiet --locale de --data data/demo-de

serve-demo:
	@echo "open http://127.0.0.1:$(PORT)/electronics/  and  http://127.0.0.1:$(PORT)/deals/  (Ctrl+C to stop)"
	DEAL_ENGINE_DATA_DIR=data/demo $(PY) -m deal_engine.deals.deals_server --config config.example.yaml --port $(PORT) --web-root data/demo/web

test:
	$(PY) -m pytest -q

clean-demo:
	rm -rf data/demo data/demo-de

## serve-demo-de: serve the German demo (after make demo-de)
serve-demo-de:
	DEAL_ENGINE_DATA_DIR=data/demo-de $(PY) -m deal_engine.deals.deals_server --config config.example.yaml --port $(PORT) --web-root data/demo-de/web --locale de
