REPO_DIR := $(shell pwd)
DATA_DIR := $(shell jupyter --data-dir)

$(if $(wildcard $(DATA_DIR)),,$(error Jupyter data directory not found; is Jupyter installed))
$(info Jupyter data directory found at '$(DATA_DIR)')

JSON_TEMPLATE := $(shell cat sac/kernel.json)
JSON_CONTENTS := $(subst <repository-path>,$(REPO_DIR),$(JSON_TEMPLATE))

install:
	mkdir -p $(DATA_DIR)/kernels
	cp -r sac $(DATA_DIR)/kernels
	echo $(JSON_CONTENTS) > $(DATA_DIR)/kernels/sac/kernel.json
	cd lib; sac2c Jupyter.sac