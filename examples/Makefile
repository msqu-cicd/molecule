SHELL:=/bin/bash -o pipefail

TMPDIR_PROJECT := $(shell mktemp -d /tmp/project.XXXX)
TMPDIR_GIT := $(shell mktemp -d /tmp/git.XXXX)
TMPDIR_MOLECULE := $(shell mktemp -d /tmp/molecule.XXXX)

DRIVER ?= podman
MOLECULE_DISTRO ?= debian-11
ANSIBLE_VAULT_PASSWORD_FILE_LOCATION := ~/.secrets/ansible-vault-pass
HCLOUD_TOKEN := $(shell cat ~/.secrets/hcloud)

# Gitlab
CI_PROJECT_NAME := ansible
CI_PROJECT_DIR=$(shell pwd)
CI_HOSTNAME=$(shell echo ${MOLECULE_DISTRO} | tr -dc '[:alnum:]\n\r' | tr '[:upper:]' '[:lower:]')
CI_PROJECT_NAME_MOLECULE=$(shell echo ${CI_PROJECT_NAME} | tr '_' '-')
CI_MOLECULE_DIRECTORY ?= $(CI_PROJECT_DIR)/molecule/default/
CI_JOB_ID=1
ANSIBLE_ROOT_REPO=$(shell echo ${CI_PROJECT_NAMESPACE} | sed 's|\(.*\)/.*|\1|')
RANDOM_SUBNET_IP=$(shell shuf -i 2-254 -n 1)
RANDOM_SUBNET_NAME=$(shell cat /dev/urandom | tr -dc 'a-z0-9' | fold -w 16 | head -n 1)

.prepare:
	cp -r . $(TMPDIR_PROJECT)
	#if compgen -G '${CI_MOLECULE_DIRECTORY}/*' >/dev/null; then rsync -avzh --ignore-existing --ignore-errors ${CI_MOLECULE_DIRECTORY} $(TMPDIR)/molecule/default/ ;fi
	mkdir -p $(TMPDIR_PROJECT)/molecule/default/
	cd $(TMPDIR_GIT) && git clone ssh://git@gitea.msqu.de:22222/ansible/molecule.git && rsync -avzh --ignore-existing --ignore-errors molecule/${DRIVER}/ $(TMPDIR_PROJECT)/molecule/default/
	yq -i 'del(.provisioner.inventory)' $(TMPDIR_PROJECT)/molecule/default/molecule.yml

.PHONY: converge
converge: .prepare ## make converge MOLECULE_DISTRO=debian-11 DRIVER=podman
	cd $(TMPDIR_PROJECT) && HCLOUD_TOKEN=$(HCLOUD_TOKEN) CI_HOSTNAME=$(CI_HOSTNAME) CI_PROJECT_NAME_MOLECULE=$(CI_PROJECT_NAME_MOLECULE) CI_JOB_ID=$(CI_JOB_ID) ANSIBLE_VAULT_PASSWORD_FILE=${ANSIBLE_VAULT_PASSWORD_FILE_LOCATION} MOLECULE_DISTRO=$(MOLECULE_DISTRO) MOLECULE_EPHEMERAL_DIRECTORY=$(TMPDIR_MOLECULE)/.cache/ molecule converge
	rm -rf $(TMPDIR_PROJECT) && rm -rf $(TMPDIR_GIT) && rm -rf $(TMPDIR_MOLECULE)

.PHONY: test
test: .prepare ## make test MOLECULE_DISTRO=debian-11 DRIVER=podman
	cd $(TMPDIR_PROJECT) && HCLOUD_TOKEN=$(HCLOUD_TOKEN) CI_HOSTNAME=$(CI_HOSTNAME) CI_PROJECT_NAME_MOLECULE=$(CI_PROJECT_NAME_MOLECULE) CI_JOB_ID=$(CI_JOB_ID) ANSIBLE_VAULT_PASSWORD_FILE=${ANSIBLE_VAULT_PASSWORD_FILE_LOCATION} MOLECULE_DISTRO=$(MOLECULE_DISTRO) MOLECULE_EPHEMERAL_DIRECTORY=$(TMPDIR_MOLECULE)/.cache/ molecule test
	rm -rf $(TMPDIR_PROJECT) && rm -rf $(TMPDIR_GIT) && rm -rf $(TMPDIR_MOLECULE)

.PHONY: destroy
destroy: .prepare ## make destroy MOLECULE_DISTRO=debian-11 DRIVER=podman
	cd $(TMPDIR_PROJECT) && HCLOUD_TOKEN=$(HCLOUD_TOKEN) CI_HOSTNAME=$(CI_HOSTNAME) CI_PROJECT_NAME_MOLECULE=$(CI_PROJECT_NAME_MOLECULE) CI_JOB_ID=$(CI_JOB_ID) ANSIBLE_VAULT_PASSWORD_FILE=${ANSIBLE_VAULT_PASSWORD_FILE_LOCATION} MOLECULE_DISTRO=$(MOLECULE_DISTRO) MOLECULE_EPHEMERAL_DIRECTORY=$(TMPDIR_MOLECULE)/.cache/ molecule destroy
	rm -rf $(TMPDIR_PROJECT) && rm -rf $(TMPDIR_GIT) && rm -rf $(TMPDIR_MOLECULE)

.PHONY: print ## make print-VARIABLE
print-%  : ; @echo $* = $($*)

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
