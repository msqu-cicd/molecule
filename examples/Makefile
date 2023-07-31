SHELL:=/bin/bash

MOLECULE_GIT_REPO='ssh://git@gitea.msqu.de:22222/ansible/molecule.git'
MOLECULE_LINT_IMAGE='gitea.msqu.de/devops/molecule:lint'
ANSIBLE_VAULT_PASSWORD_FILE_LOCATION := ~/.secrets/ansible-vault-pass
HCLOUD_TOKEN := $(shell cat ~/.secrets/hcloud)
CONTAINER_RUNTIME ?= $(if $(shell command -v podman ;),podman,docker)

TMPDIR_PROJECT := $(shell mktemp -d /tmp/project.XXXX)
TMPDIR_GIT := $(shell mktemp -d /tmp/git.XXXX)
TMPDIR_MOLECULE := $(shell mktemp -d /tmp/molecule.XXXX)

DRIVER ?= hetznercloud
MOLECULE_DISTRO ?= debian-11
CI_PROJECT_NAME=$$(basename $$(pwd))
CI_PROJECT_DIR=$(shell pwd)
CI_PROJECT_NAME_MOLECULE=$(shell echo ${CI_PROJECT_NAME} | tr '_' '-')

.prepare:
	mkdir -p $(CI_PROJECT_DIR)/molecule/default/
	cd $(TMPDIR_GIT) && git clone $(MOLECULE_GIT_REPO) && rsync -avzh --ignore-existing --ignore-errors molecule/${DRIVER}/ $(CI_PROJECT_DIR)/molecule/default/

.PHONY: converge
converge: .prepare ## make converge MOLECULE_DISTRO=debian-11 DRIVER=podman
	HCLOUD_TOKEN=$(HCLOUD_TOKEN) CI_PROJECT_NAME_MOLECULE=$(CI_PROJECT_NAME_MOLECULE) ANSIBLE_VAULT_PASSWORD_FILE=${ANSIBLE_VAULT_PASSWORD_FILE_LOCATION} MOLECULE_DISTRO=$(MOLECULE_DISTRO) MOLECULE_EPHEMERAL_DIRECTORY=$(TMPDIR_MOLECULE)/.cache/ molecule converge
	rm -rf $(TMPDIR_GIT) && rm -rf $(TMPDIR_MOLECULE)

.PHONY: test
test: .prepare ## make test MOLECULE_DISTRO=debian-11 DRIVER=podman
	HCLOUD_TOKEN=$(HCLOUD_TOKEN) CI_PROJECT_NAME_MOLECULE=$(CI_PROJECT_NAME_MOLECULE) ANSIBLE_VAULT_PASSWORD_FILE=${ANSIBLE_VAULT_PASSWORD_FILE_LOCATION} MOLECULE_DISTRO=$(MOLECULE_DISTRO) MOLECULE_EPHEMERAL_DIRECTORY=$(TMPDIR_MOLECULE)/.cache/ molecule test
	rm -rf $(TMPDIR_GIT) && rm -rf $(TMPDIR_MOLECULE)

.PHONY: destroy
destroy: .prepare ## make destroy MOLECULE_DISTRO=debian-11 DRIVER=podman
	export HCLOUD_SERVER_STATE=absent && HCLOUD_TOKEN=$(HCLOUD_TOKEN) CI_PROJECT_NAME_MOLECULE=$(CI_PROJECT_NAME_MOLECULE) ANSIBLE_VAULT_PASSWORD_FILE=${ANSIBLE_VAULT_PASSWORD_FILE_LOCATION} MOLECULE_DISTRO=$(MOLECULE_DISTRO) MOLECULE_EPHEMERAL_DIRECTORY=$(TMPDIR_MOLECULE)/.cache/ molecule destroy
	rm -rf $(TMPDIR_GIT) && rm -rf $(TMPDIR_MOLECULE) && git clean -xdf molecule/

.PHONY: print ## make print-VARIABLE
print-%  : ; @echo $* = $($*)

.PHONY: ansible-lint
ansible-lint:
	$(CONTAINER_RUNTIME) run --rm \
		-v $(CURDIR):/git -w /git \
		$(MOLECULE_LINT_IMAGE) \
		ansible-lint --force-color /git

.PHONY: yamllint
yamllint:
	$(CONTAINER_RUNTIME) run --rm \
		-v $(CURDIR):/git -w /git \
		$(MOLECULE_LINT_IMAGE) \
		yamllint -f colored /git

.PHONY: shellcheck
shellcheck:
	$(CONTAINER_RUNTIME) run --rm \
		--pull=always \
		-v $(CURDIR):/git -w /git \
		$(MOLECULE_LINT_IMAGE) \
		find . -name .git -type d -prune -o -type f -name \*.sh -print0 | xargs -0 -r -n1 shellcheck

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
