.PHONY: ssot kb kb-dry kb-full nlm-cite nlmq ha-build verify clean

REPO ?= /home/tony/CascadeProjects/chaba

ssot:
	node $(REPO)/scripts/ssot-validate-all.mjs

kb:
	python3 $(REPO)/scripts/notebooklm-kb-sync.py

kb-dry:
	python3 $(REPO)/scripts/notebooklm-kb-sync.py --dry-run

kb-full:
	python3 $(REPO)/scripts/notebooklm-kb-sync.py --force

nlm-cite:
	@:$(if $(SOURCE),,$(error Set SOURCE, e.g. SOURCE=kb/mddb or SOURCE=<source-id>))
	~/.local/bin/nlm-cite $(SOURCE)

nlmq:
	@:$(if $(Q),,$(error Set Q, e.g. Q='What is the tony-dell Tailscale IP?'))
	~/.local/bin/nlmq fdfd3483-6b7e-4cb0-85f3-7f060698769c "$(Q)"

ha-build:
	cd /home/tony/CascadeProjects/sunsynk-power-flow-card && npm run build

verify:
	python3 $(REPO)/scripts/verify-agents-commands.py

clean:
	find $(REPO) -name '__pycache__' -type d -prune -exec rm -rf {} +
