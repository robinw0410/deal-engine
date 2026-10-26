PY ?= python3
DAYS ?= 21
PORT ?= 8081

.PHONY: demo demo-data serve-demo test clean-demo

## demo: generate invented data, run the full pipeline over $(DAYS) simulated days, serve the pages
demo: demo-data serve-demo

demo-data:
	$(PY) -m demo.run_demo --days $(DAYS) --quiet

serve-demo:
	@echo "open http://127.0.0.1:$(PORT)/electronics/  and  http://127.0.0.1:$(PORT)/deals/  (Ctrl+C to stop)"
	DEAL_ENGINE_DATA_DIR=data/demo $(PY) -m deals.deals_server --config config.example.yaml --port $(PORT) --web-root data/demo/web

test:
	$(PY) -m pytest -q

clean-demo:
	rm -rf data/demo
