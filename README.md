# Molecule

CI/CD infrastructure for Molecule-based Ansible testing with multiple cloud providers

# Runner image

CI jobs run in `ghcr.io/msqu-devops/molecule:runner`, which is built outside this repository.
The image, its CLIs and its pinned Ansible collections are defined in [DevOps/molecule](https://git.msqu.de/DevOps/molecule) (`dockerfiles/Runner`, `dockerfiles/collections.yml`).

# Scenarios

## Hetzner Cloud

Optimized molecule scenario for Hetzner Cloud infrastructure testing with the following features:

### Performance Optimizations
- **Cloud-init based auto-update disable**: Prevents apt daily services from slowing down instance startup
- **Optional private networking**: Set `HCLOUD_PRIVATE_NET=true` to enable private networks (disabled by default for faster provisioning)
- **Resource labeling**: All resources (servers, volumes, networks) are automatically labeled for easy identification and cleanup

### Environment Variables
- `HCLOUD_TOKEN`: Hetzner Cloud API token (required)
- `HCLOUD_PRIVATE_NET`: Enable private networking (`true`/`false`, default: `false`)
- `INSTANCE_SIZE`: Server type (default: `cx23`; falls back to `cax11`, `cpx22`, `cx33`, `cax21`, `cpx32`, `cx43` when
  unavailable: x86 and Arm per size, roles must not depend on the CPU architecture)
- `INSTANCE_REGION`: Preferred location (default: `hel1`); `fsn1` and `nbg1`, the other eu-central locations, are tried next
- Server type and location candidates are filtered by Hetzner's per-location availability (`server_type_info`),
  and every pair is tried when that lookup fails. A server left by an earlier job keeps its type and location.
- `MOLECULE_DISTRO`: OS image (required, CI uses `debian-13`)

### Resource Management
- All platforms in `molecule.yml` are created, so roles can define multi-node scenarios
- Servers are stopped between CI jobs and rebuilt by the next job; the last job deletes them (the cleanup job and
  the Cloud sweep also remove strays, volumes, networks and DynDNS records)
- Automatic cleanup of all resources after testing
- Labels applied: `environment: molecule`, `project: <project-name>`, `managed-by: molecule`; the cleanup
  job's safety net selects old servers by `managed-by=molecule`, so a role's own `molecule.yml` must keep that label
- root logs in with the registered SSH keys; the cloud-init user data sets no root password and does not enable SSH password login

## KVM (local QEMU)

Boots upstream cloud images as QEMU guests inside the job container, on the runner with the `kvm` label
(its runner passes `/dev/kvm` and an exec tmpfs into unprivileged, network-isolated job containers).
No cloud account, no bridge, no libvirt: the guest's sshd is reached through a user-mode network port
forward on `127.0.0.1`, so the scenario also runs on any workstation with `/dev/kvm` and falls back to
TCG (works, but slow) without it.

### Environment Variables
- `MOLECULE_DISTRO`: `debian-12`, `debian-13`, `ubuntu-24.04` or `ubuntu-26.04` (same names as the Hetzner
  images; the genericcloud/cloudimg qcow2 behind them is verified against the published checksums)
- `KVM_MEMORY` (default `2048` MiB), `KVM_VCPUS` (`2`), `KVM_DISK` (`10G`), `KVM_SSH_PORT` (`2222`; platform
  N of a multi-node scenario uses `KVM_SSH_PORT + N`)
- `KVM_IMAGE_CACHE`: base image directory (default `/var/cache/molecule-images`, bind-mounted from the runner
  host by `role-kvm.yml`); a path that cannot be created or written falls back to molecule's ephemeral directory
- `KVM_WORK_DIR`: overlays, seeds, pid files and serial logs (default: molecule's ephemeral directory; CI
  uses the runner's `/tmp` tmpfs)

### Guests
- q35 machine, `-accel kvm -cpu host`, one qcow2 overlay per platform on the cached base image
- cloud-init NoCloud seed with a per-run root key (`disable_root: false`, no password login)
- the NIC is named `eth0` like on the servers and the Hetzner images (fixed MAC per platform plus a
  `network-config` with `set-name: eth0`; the cloud image would otherwise name it `enp0s2`)
- the serial console is printed when a guest does not become reachable over SSH
- `destroy` sends SIGTERM to each QEMU and removes the work directory
- needs `qemu-system-x86`, `qemu-utils` and `genisoimage` in the job container; `role-kvm.yml` installs
  them when the runner image does not ship them

## Vultr

Used by roles that need distributions Hetzner does not offer (Arch Linux workstations).
- `VULTR_API_KEY` (required), `INSTANCE_SIZE` (default `vhp-1c-1gb-amd`, 1 vCPU, 1 GB, 25 GB NVMe; `vc2-1c-1gb` is no longer offered in `fra`), `INSTANCE_REGION` (default `fra`)
- Instances are labelled `molecule-<repo>`, without a VPC (the single test instance needs no private network).
  `molecule test` leaves the instance (`VULTR_SERVER_STATE=present`); the workflow's cleanup job and the Cloud sweep delete it

## EC2

Uses the official `molecule-plugins` ec2 driver (`create.yml`/`destroy.yml` are its templates) in AWS account
`900010691084`, region `eu-central-1`. The VPC, the subnets (tag `molecule=true`), the security group `molecule`
and the restricted CI user come from [Infrastructure/aws-molecule](https://git.msqu.de/Infrastructure/aws-molecule).
- Secrets `MOLECULE_AWS_ACCESS_KEY_ID` / `MOLECULE_AWS_SECRET_ACCESS_KEY` (outputs of that repo)
- `INSTANCE_SIZE` default `t3.small` (amd64); Graviton types (`t4g.*`) select arm64 images
- The workflow derives `EC2_IMAGE_OWNER`/`EC2_IMAGE_NAME` from the distro (official Debian and Canonical images)
  and picks `EC2_SUBNET_ID` by tag; every job creates and terminates its own instance
- Instances are tagged `managed-by=molecule`, `project=<repo>`; the cleanup job terminates leftovers of the
  repo and any molecule instance older than 3 hours (see Cloud sweep)

## Shared DynDNS (hetznercloud)

Multi-node roles that need a DNS name (k3s, rke2) include `dyndns.yml` from their `converge_override.yml`.
It points `*.<repo>.<zone>` at the first host, waits until Hetzner's nameservers serve it and sets
`molecule_ddns_fqdn` (`k8s.<repo>.<zone>`). `dyndns_cleanup.yml` deletes the records again.
Needs `molecule_ddns.domain` and `hetzner_dns_token` (org secret `HETZNER_DNS_TOKEN`, a Cloud API token
of the project that holds the zone). See the usage comments at the top of both files.

# Usage

## CI workflow

Roles do not carry their own pipeline. Each role's `.gitea/workflows/molecule.yml` is a short caller of a
reusable workflow in this repository, see [examples/caller-molecule.yml](examples/caller-molecule.yml):

```yaml
jobs:
  molecule:
    uses: CICD/molecule/.gitea/workflows/role-kvm.yml@main   # or role-hetznercloud.yml, role-vultr.yml
    with:
      force_run: ${{ format('{0}', inputs.force_run) }}
      molecule_debug: ${{ format('{0}', inputs.molecule_debug) }}
      args: ${{ inputs.args }}
      molecule_ref: ${{ inputs.molecule_ref || 'main' }}
    secrets:
      SSH_PRIVATE_KEY: ${{ secrets.SSH_PRIVATE_KEY }}
      # ... only the secrets the workflow declares
```

Pass inputs through `format('{0}', ...)`: Gitea hands dispatch inputs over as strings, and a non-empty
string like `"false"` is truthy in expressions.

### role-hetznercloud.yml

For roles the kvm runner cannot test, e.g. multi-node scenarios whose servers must reach each other
(k3s, rke2). Every other role uses `role-kvm.yml`.

| Input | Default | Description |
|-------|---------|-------------|
| `force_run` | `'false'` | Run even if only ignored files changed |
| `molecule_debug` | `'false'` | Open a tmate session before the tests |
| `args` | `''` | Extra `molecule test` arguments |
| `unit` / `integration` | `'true'` | Switch the unit / integration jobs (both `'false'` = lint, infra-spec and secret scan only) |
| `debian_distro` | `debian-13` | Hetzner image |
| `instance_size` | scenario default | Server type |
| `extra_files_ignore` | `''` | Additional changed-files ignore patterns |
| `molecule_ref` | `main` | Ref of this repo to take the scenario from |

Secrets: `SSH_PRIVATE_KEY`, `CI_RUNNER_PAT`, `CI_RUNNER_PAT_GITHUB`, `ANSIBLE_VAULT_PASSWORD`, `HCLOUD_TOKEN`, `HETZNER_DNS_TOKEN`.

`role-ec2.yml` has the hetznercloud inputs plus `region` (default `eu-central-1`) and takes
`MOLECULE_AWS_ACCESS_KEY_ID`/`MOLECULE_AWS_SECRET_ACCESS_KEY` instead of the Hetzner secrets. Like the others it is
Debian only and has the infra-spec job. Its only caller is Ansible/apt (`molecule-ec2.yml`, manual dispatch).

`role-vultr.yml` has the same inputs except `unit`/`integration`/`*_distro` (it runs one integration job,
`distro` defaults to `Arch Linux x64`) and takes `VULTR_API_KEY` instead of the Hetzner secrets. The integration
job leaves its instance (`VULTR_SERVER_STATE=present`), so the cleanup job is what deletes it. Callers: the
`desktop-config*` roles and `workstation`.

### role-kvm.yml

The default for roles. Same inputs and secrets as `role-hetznercloud.yml`, except `instance_size`, which
becomes `kvm_memory` (default `'2048'`) and `kvm_vcpus` (`'2'`); `debian_distro` names the cloud image
(`debian-12`/`debian-13`). Unit and integration both run on the `kvm` runner (node.bastelpappe.de, capacity 2), lint stays on
`molecule`, and there is no cleanup job because the guests die with the job container. `HCLOUD_TOKEN` and
`HETZNER_DNS_TOKEN` are accepted but unused, so a caller switches by changing only its `uses:` line.

### Pipeline

1. **changes**: skip the tests when only ignored files changed (deletions count as changes)
2. **lint**: ansible-lint, yamllint and shellcheck (tracked `*.sh`/`*.bash` files and extensionless files
   with a `sh`/`bash` shebang; `*.sh.j2` templates are skipped, they are not valid shell before rendering)
   - **infra-spec** (next to the tests, no test server): `scripts/infra-spec-check.py` runs the role's
     `tasks/assert.yml` and validates `meta/argument_specs.yml` for every host an Infrastructure/infra playbook
     applies the role to, with the host's real variables over a local connection. It reads the playbooks'
     `roles:`/`include_role` entries and their `when:` (clauses on facts, on `pre_tasks` variables or on
     group_vars computed from facts count as true), checks each entry on its own with its play's `hosts:`
     pattern and uses the inventories of the infra Makefile (server playbooks: every server inventory with
     `--limit '!localhost'`; workstation playbooks: `workstations.yml`). Missing inventories and imported task
     files that are not in the checkout print a warning.
     It fails when a spec or assert rejects a value infra sets; errors name the variable and the type, never the value.
3. **unit** (Debian 13): role with `tests/vars.yml`
4. **integration** (Debian 13): role with the infra `group_vars`
5. **cleanup** (hetznercloud, vultr and ec2; always, also after failures/cancellations, but not when the tests
   were skipped because nothing relevant changed or on a push): `molecule destroy` (its failure is tolerated),
   then `scripts/cloud-sweep.sh` for the cloud. The sweep deletes the repo's own leftovers and every molecule
   resource older than 3 hours, and fails the job when the API cannot be queried or a deletion fails. On Hetzner
   it also removes the unattached volumes and unused networks labelled `managed-by=molecule` and the DynDNS
   records (see Cloud sweep). `role-kvm.yml` has no cleanup job because the guests die with the job container.

Outside that order, with no `needs`, **secret-scan** runs gitleaks on every pull request, whatever it changed,
and on every push the caller's `paths-ignore` lets through. A pull request is scanned commit by commit
(`gitleaks git`, `base..HEAD` over the full history), so a secret that is added and removed again inside it is
found; a push or dispatch scans the checked-out tree. It uses gitleaks' built-in rules only: a `.gitleaks.toml`,
`.gitleaksignore` or `gitleaks:allow` in the role is ignored, so a change cannot switch the scan off. Findings
are redacted in the log.

Secrets: the scenarios read the vault through `vault_password_file` (`.vault`, written with `umask 077`), so the
molecule steps get no `ANSIBLE_VAULT_PASSWORD` in their environment, and the scenario and infra checkouts do not
leave `CI_RUNNER_PAT` in `.git/config`.

The fleet runs Debian 13 only, so there are no Ubuntu jobs. Pushes to the default branch (merges, already
tested in their pull request) skip the integration test and, on the cloud workflows, the unit test too: lint,
infra-spec and the secret scan run everywhere, plus the unit test in `role-kvm.yml`. A merge therefore starts no
Hetzner server, Vultr or EC2 instance.

A push that its pull request already tested skips lint and tests entirely: the `changes` job checks whether
the pushed commit is a merge whose tree equals the pull request head (the pull request was up to date with
the target branch) or a fast-forward to that head, and whether the caller's `molecule (pull_request)` status
of that head is `success`. Merges after the target branch moved, squash merges, direct pushes and failed
lookups run as above.

Runs of one repo share the concurrency group `molecule-tests`, because the server and DNS names are
`molecule-<repo>`. A new run waits for the running one instead of cancelling it (`cancel-in-progress: false`).

## Testing changes to this repository

- `ci.yml` lints the scenarios, the examples and the workflows on every push and pull request: ansible-lint,
  yamllint and actionlint (pinned, checksum-verified; it shellchecks the `run:` blocks). `.gitea/actionlint.yaml`
  lists the Gitea runner labels and ignores the full-URL `uses:` form that Gitea supports and GitHub syntax lacks.
  A `run:` block that relies on word splitting on purpose carries `# shellcheck disable=SC2086` with the reason.
- `smoke-test.yml` runs the full Ansible/apt pipeline against the scenarios of the pushed commit
  (`molecule_ref` is the head SHA, not a branch name) whenever `scenarios/**` changes, and fails if apt fails.
  A newer push queues behind a running smoke test instead of cancelling it; a smoke test cancelled by hand
  leaves the apt run running. It does not exercise a changed `role-*.yml`: the apt caller uses
  `role-kvm.yml@main`, and `uses:` takes no expression, so a workflow change is only linted (actionlint) before it
  merges. Gitea's runner would run `uses: ./.gitea/workflows/role-kvm.yml` from this repository, but the
  workflows treat the repository root as the role (lint, `molecule/default`, the role named after the directory),
  so a PR-time test needs a role at the root of this repository or a `role_dir` input in the workflows.
- The runner image is pinned by digest in the workflows; Renovate updates it.

## Cloud sweep

`cloud-sweep.yml` runs `scripts/cloud-sweep.sh` for Hetzner, Vultr and EC2 every two hours and on dispatch
(`dry_run`, `max_age_hours`), independent of any role run. A force-cancelled run, or one cancelled before it
started, skips its `always()` cleanup job, and Hetzner servers stay `stopped` between jobs by design; the sweep
deletes what is older than 3 hours (`managed-by=molecule` on Hetzner and EC2, the `molecule-` label on Vultr).
The role workflows' cleanup jobs run the same script for their repo.

- Hetzner: servers, then the unattached volumes and the networks without servers (`destroy.yml` removes them only
  while the platform's server exists), then the DynDNS records `*.<subdomain>` (A, AAAA) of the zone `picxi.de`
  (`MOLECULE_DNS_ZONE`, `molecule_ddns.domain` in Infrastructure/infra) whose subdomain has no `molecule-<subdomain>`
  server left. The zone is the CI-only zone of Infrastructure/dns; records have no age, so a record without a
  server counts as leftover. The record deletion uses `HETZNER_DNS_TOKEN` (Cloud API token of the project that
  holds the zone) and is skipped when that secret is not passed.
- Secrets: `HCLOUD_TOKEN`, `HETZNER_DNS_TOKEN`, `VULTR_API_KEY`, `MOLECULE_AWS_ACCESS_KEY_ID`,
  `MOLECULE_AWS_SECRET_ACCESS_KEY`; org-level Actions secrets of the CICD org (Infrastructure/gitea,
  `3_ci_stuff/org_secrets.tf`).
- `SWEEP_DRY_RUN=true scripts/cloud-sweep.sh <hetzner|vultr|ec2>` prints what would be deleted.

## Local runs

```bash
molecule test                              # basic test
HCLOUD_PRIVATE_NET=true molecule test      # with private networking
INSTANCE_SIZE=cx33 molecule test           # different server type
MOLECULE_DISTRO=debian-13 KVM_IMAGE_CACHE=~/.cache/molecule-images molecule test   # kvm scenario, needs /dev/kvm
```

`examples/Makefile` copies a scenario (`DRIVER`, default `kvm`; `MOLECULE_REF`, default `main`, a branch, tag or
commit of this repository) into a role and runs molecule with the same environment as CI. `make shellcheck`
checks what CI's Shell Lint checks. It is the copy every role repository carries. `make converge` keeps the instance and its molecule
state in `~/.cache/molecule-make/<repo>` (mode 0700) for `make verify`, `make login` and `make destroy`; `make test`
and `make destroy` remove the state and the scenario files the Makefile copied in, also when molecule fails.
Only files that did not exist before the copy are removed (the cache directory lists them), and never files
tracked in git, so a role's own `verify.yml`, `prepare.yml`, `requirements.yml` or `converge_override.yml` stays,
committed or not. The hcloud token is read from `~/.secrets/hcloud` (or `HCLOUD_TOKEN`) by the molecule targets only.

# Configuration
## Include prerequisite role

* Create `molecule/default/requirements.yml` inside the repository with following content and replace values as needed:

```yaml
- src: https://git.msqu.de/Ansible/example.git
  name: example
  scm: git

```

* Create `molecule/default/converge.yml` inside the repository with following content, replacing `example` as needed:

```yaml
---
- name: Converge
  hosts: all
  become: true

  pre_tasks:
    - name: Update APT Cache
      ansible.builtin.apt:
        update_cache: yes
        cache_valid_time: 600
      register: result
      until: result is succeeded
      when: ansible_facts['os_family'] == 'Debian'

    # skip idempotence tests
    - name: Include Example install role
      ansible.builtin.include_role:
        name: example
      when: "'molecule-idempotence-notest' not in ansible_skip_tags"

  tasks:
    - name: "{{ lookup('env', 'MOLECULE_PROJECT_DIRECTORY') | basename }}"
      ansible.builtin.include_role:
        name: "{{ lookup('env', 'MOLECULE_PROJECT_DIRECTORY') | basename }}"
```

The prerequisite role is included only in the converge stage of molecule, but not in idempotence test cause of the declaration:
`when: "'molecule-idempotence-notest' not in ansible_skip_tags"`


## Disable idempotence check on
- https://molecule.readthedocs.io/en/stable/configuration.html#id8

### Whole role

Create `molecule/default/converge.yml` inside the repository with following content:

```yaml
---
- name: Converge
  hosts: all
  become: true

  pre_tasks:
    - name: Update APT Cache
      ansible.builtin.apt:
        update_cache: yes
        cache_valid_time: 600
      register: result
      until: result is succeeded
      when: ansible_facts['os_family'] == 'Debian'

  tasks:
    # skip idempotence tests
    - name: "{{ lookup('env', 'MOLECULE_PROJECT_DIRECTORY') | basename }}"
      ansible.builtin.include_role:
        name: "{{ lookup('env', 'MOLECULE_PROJECT_DIRECTORY') | basename }}"
      tags:
        - molecule-idempotence-notest
```

### Single tasks

Tag the task with `molecule-idempotence-notest`:

```yaml
# skip idempotence tests
- name: Not idempotent task
  ansible.builtin.command: "echo not-idempotent"
  tags:
    - molecule-idempotence-notest
```

## Skip idempotence check on

### Whole role

Create `molecule/default/converge.yml` inside the repository with following content, replacing `example` as needed:

```yaml
...
  tasks:
    # skip idempotence tests
    - name: Include Example install role
      ansible.builtin.include_role:
        name: example
      when: "'molecule-idempotence-notest' not in ansible_skip_tags"
...
```
