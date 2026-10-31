SHELL := /bin/bash

# ============================================================================
# Configuration Variables
# ============================================================================

# Container settings
CONTAINER_RUNTIME := docker
MOLECULE_LINT_IMAGE := ghcr.io/msqu-devops/molecule:lint

# Molecule settings
MOLECULE_GIT_REPO := ssh://git@git.msqu.de:22222/CICD/molecule.git
DRIVER ?= hetznercloud
MOLECULE_DISTRO ?= debian-13

# Authentication: the hcloud token is read inside the molecule recipes only,
# a HCLOUD_TOKEN from the environment wins
ANSIBLE_VAULT_PASSWORD_FILE_LOCATION := ~/.secrets/ansible-vault-pass
HCLOUD_TOKEN_FILE := ~/.secrets/hcloud
MOLECULE_RUN := . ~/env/bin/activate && HCLOUD_TOKEN="$${HCLOUD_TOKEN:-$$(cat $(HCLOUD_TOKEN_FILE))}" molecule

# Project paths
CI_PROJECT_NAME := $(shell basename $$(pwd))
CI_PROJECT_DIR := $(shell pwd)
MOLECULE_PROJECT_DIR := $(shell dirname $(CI_PROJECT_DIR))
CI_PROJECT_NAME_MOLECULE := $(shell echo $(CI_PROJECT_NAME) | tr '_' '-')

# Molecule state (instance SSH access included), kept from converge until test or
# destroy cleans up, so that verify and login find the instance. Owner-only, per user.
MOLECULE_CACHE_DIR := $(HOME)/.cache/molecule-make/$(CI_PROJECT_NAME_MOLECULE)

# ============================================================================
# Exported Environment Variables
# ============================================================================

export ANSIBLE_ROLES_PATH := $(MOLECULE_PROJECT_DIR)
export MOLECULE_PROJECT_DIRECTORY := $(MOLECULE_PROJECT_DIR)
export MOLECULE_ROLE_NAME := $(CI_PROJECT_NAME)
export ANSIBLE_VAULT_PASSWORD_FILE := $(ANSIBLE_VAULT_PASSWORD_FILE_LOCATION)
export CI_PROJECT_NAME_MOLECULE
export MOLECULE_DISTRO
export MOLECULE_EPHEMERAL_DIRECTORY := $(MOLECULE_CACHE_DIR)/.cache/

# ============================================================================
# Internal Targets
# ============================================================================

.PHONY: .prepare
.prepare:
	@echo "Preparing molecule scenario files..."
	@mkdir -p $(CI_PROJECT_DIR)/molecule/default/
	@install -d -m 0700 $(MOLECULE_CACHE_DIR)
	@tmp=$$(mktemp -d /tmp/molecule-git.XXXXXXXX) && trap 'rm -rf "$$tmp"' EXIT && \
		git clone --depth 1 --quiet $(MOLECULE_GIT_REPO) "$$tmp/molecule" && \
		rsync -azh --ignore-existing "$$tmp/molecule/scenarios/$(DRIVER)/" $(CI_PROJECT_DIR)/molecule/default/

.PHONY: .cleanup
.cleanup:
	@echo "Cleaning up the molecule state..."
	@rm -rf $(MOLECULE_CACHE_DIR)
	@$(MAKE) --no-print-directory clean-molecule

# ============================================================================
# Molecule Test Targets
# ============================================================================

.PHONY: converge
converge: .prepare ## Run molecule converge (keeps the instance for verify, login and destroy)
	@echo "Running molecule converge with $(MOLECULE_DISTRO)..."
	@$(MOLECULE_RUN) converge

.PHONY: test
test: .prepare ## Run full molecule test suite
	@echo "Running molecule test with $(MOLECULE_DISTRO)..."
	@$(MOLECULE_RUN) test; rc=$$?; $(MAKE) --no-print-directory .cleanup; exit $$rc

.PHONY: verify
verify: ## Run molecule verify against the instance from make converge
	@echo "Running molecule verify..."
	@$(MOLECULE_RUN) verify

.PHONY: destroy
destroy: .prepare ## Destroy molecule test infrastructure
	@echo "Destroying molecule infrastructure..."
	@export HCLOUD_SERVER_STATE=absent; $(MOLECULE_RUN) destroy; rc=$$?; $(MAKE) --no-print-directory .cleanup; exit $$rc

.PHONY: login
login: ## Log into the instance from make converge
	@$(MOLECULE_RUN) login

# ============================================================================
# Linting Targets
# ============================================================================

.PHONY: lint
lint: ansible-lint yamllint shellcheck ## Run all linters

.PHONY: ansible-lint
ansible-lint: ## Run ansible-lint on role
	@echo "Running ansible-lint..."
	@$(CONTAINER_RUNTIME) run --rm \
		-v $(CURDIR):/git:ro -w /git \
		$(MOLECULE_LINT_IMAGE) \
		ansible-lint --force-color /git

.PHONY: yamllint
yamllint: ## Run yamllint on YAML files
	@echo "Running yamllint..."
	@$(CONTAINER_RUNTIME) run --rm \
		-v $(CURDIR):/git:ro -w /git \
		$(MOLECULE_LINT_IMAGE) \
		yamllint -f colored /git

.PHONY: shellcheck
shellcheck: ## Run shellcheck on shell scripts
	@echo "Running shellcheck..."
	@$(CONTAINER_RUNTIME) run --rm \
		--pull=always \
		-v $(CURDIR):/git:ro -w /git \
		$(MOLECULE_LINT_IMAGE) \
		sh -c 'find . -name .git -type d -prune -o -type f -name "*.sh" -print0 | xargs -0 -r -n1 shellcheck'

# ============================================================================
# Utility Targets
# ============================================================================

.PHONY: clean
clean: ## Clean generated and temporary files
	@echo "Cleaning generated files..."
	@rm -rf .molecule/
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true

.PHONY: clean-molecule
clean-molecule: ## Remove the generated molecule scenario files (keeps tracked files and converge_override.yml)
	@echo "Removing generated molecule files..."
	@git ls-files -z --others molecule/default 2>/dev/null | grep -z -v '/converge_override\.yml$$' | xargs -0 -r rm -f
	@echo "Molecule scenario files removed. Run 'make converge' to regenerate."

.PHONY: print-%
print-%: ## Print value of any variable (e.g., make print-CI_PROJECT_NAME)
	@echo $* = $($*)

.PHONY: vars
vars: ## Show all important variables
	@echo "Project Variables:"
	@echo "  CI_PROJECT_NAME         = $(CI_PROJECT_NAME)"
	@echo "  CI_PROJECT_DIR          = $(CI_PROJECT_DIR)"
	@echo "  MOLECULE_PROJECT_DIR    = $(MOLECULE_PROJECT_DIR)"
	@echo "  CI_PROJECT_NAME_MOLECULE= $(CI_PROJECT_NAME_MOLECULE)"
	@echo "  MOLECULE_CACHE_DIR      = $(MOLECULE_CACHE_DIR)"
	@echo ""
	@echo "Molecule Configuration:"
	@echo "  DRIVER                  = $(DRIVER)"
	@echo "  MOLECULE_DISTRO         = $(MOLECULE_DISTRO)"
	@echo "  ANSIBLE_ROLES_PATH      = $(ANSIBLE_ROLES_PATH)"
	@echo ""
	@echo "Container:"
	@echo "  CONTAINER_RUNTIME       = $(CONTAINER_RUNTIME)"

.PHONY: help
help: ## Show this help message
	@echo "Usage: make [target]"
	@echo ""
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Examples:"
	@echo "  make converge MOLECULE_DISTRO=ubuntu-26.04"
	@echo "  make test DRIVER=kvm"
	@echo "  make print-CI_PROJECT_NAME"

.DEFAULT_GOAL := help
