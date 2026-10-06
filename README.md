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
- `INSTANCE_SIZE`: Server type (default: `cx23`; falls back to `cpx22`, `cx33`, `cpx32`, `cx43` when unavailable)
- `INSTANCE_REGION`: Preferred location (default: `hel1`); `fsn1` and `nbg1`, the other eu-central locations, are tried next
- Server type and location candidates are filtered by Hetzner's per-location availability (`server_type_info`),
  and every pair is tried when that lookup fails. A server left by an earlier job keeps its type and location.
- `MOLECULE_DISTRO`: OS image (required, CI uses `debian-13` and `ubuntu-26.04`)

### Resource Management
- All platforms in `molecule.yml` are created, so roles can define multi-node scenarios
- Servers are stopped between CI jobs and rebuilt by the next job; the last job deletes them
- Automatic cleanup of all resources after testing
- Labels applied: `environment: molecule`, `project: <project-name>`, `managed-by: molecule`

## Vultr

Used by roles that need distributions Hetzner does not offer (Arch Linux workstations).
- `VULTR_API_KEY` (required), `INSTANCE_SIZE` (default `vc2-1c-1gb`, 25 GB disk), `INSTANCE_REGION` (default `fra`)
- One VPC per repo (`molecule-<repo>`), instances are labelled `molecule-<repo>`

## EC2

Uses the official `molecule-plugins` ec2 driver (`create.yml`/`destroy.yml` are its templates) in AWS account
`900010691084`, region `eu-central-1`. The VPC, the subnets (tag `molecule=true`), the security group `molecule`
and the restricted CI user come from [Infrastructure/aws-molecule](https://git.msqu.de/Infrastructure/aws-molecule).
- Secrets `MOLECULE_AWS_ACCESS_KEY_ID` / `MOLECULE_AWS_SECRET_ACCESS_KEY` (outputs of that repo)
- `INSTANCE_SIZE` default `t3.small` (amd64); Graviton types (`t4g.*`) select arm64 images
- The workflow derives `EC2_IMAGE_OWNER`/`EC2_IMAGE_NAME` from the distro (official Debian and Canonical images)
  and picks `EC2_SUBNET_ID` by tag; every job creates and terminates its own instance
- Instances are tagged `managed-by=molecule`, `project=<repo>`; the cleanup job terminates leftovers of the
  repo and any molecule instance older than 3 hours

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
    uses: CICD/molecule/.gitea/workflows/role-hetznercloud.yml@main   # or role-vultr.yml
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

| Input | Default | Description |
|-------|---------|-------------|
| `force_run` | `'false'` | Run even if only ignored files changed |
| `molecule_debug` | `'false'` | Open a tmate session before the tests |
| `args` | `''` | Extra `molecule test` arguments |
| `unit` / `integration` | `'true'` | Switch the unit / integration jobs (both `'false'` = lint only) |
| `debian_distro` / `ubuntu_distro` | `debian-13` / `ubuntu-26.04` | Hetzner images |
| `instance_size` | scenario default | Server type |
| `extra_files_ignore` | `''` | Additional changed-files ignore patterns |
| `molecule_ref` | `main` | Ref of this repo to take the scenario from |

Secrets: `SSH_PRIVATE_KEY`, `CI_RUNNER_PAT`, `CI_RUNNER_PAT_GITHUB`, `ANSIBLE_VAULT_PASSWORD`, `HCLOUD_TOKEN`, `HETZNER_DNS_TOKEN`.

`role-ec2.yml` has the hetznercloud inputs plus `region` (default `eu-central-1`); its Debian and Ubuntu
chains run in parallel and it takes `MOLECULE_AWS_ACCESS_KEY_ID`/`MOLECULE_AWS_SECRET_ACCESS_KEY` instead of the Hetzner secrets.

`role-vultr.yml` has the same inputs except `unit`/`integration`/`*_distro` (it runs one integration job,
`distro` defaults to `Arch Linux x64`) and takes `VULTR_API_KEY` instead of the Hetzner secrets.

### Pipeline

1. **changes**: skip the tests when only ignored files changed (deletions count as changes)
2. **lint**: ansible-lint and yamllint
3. **unit** (Debian, then Ubuntu): role with `tests/vars.yml`; servers are stopped between jobs and rebuilt
4. **integration** (Debian, then Ubuntu): role with the infra `group_vars`; the last job deletes the servers
5. **cleanup** (always, also after failures/cancellations): deletes leftover servers and DNS records,
   then a safety net deletes CI servers of any repo older than 3 hours

Runs of one repo share the concurrency group `molecule-tests`; a new run cancels the running one.

## Testing changes to this repository

- `ci.yml` lints the scenarios and workflows on every push and pull request.
- `smoke-test.yml` runs the full Ansible/apt pipeline against the scenarios of the pushed ref
  (`molecule_ref`) whenever `scenarios/**` changes, and fails if apt fails.
- The runner image is pinned by digest in the workflows; Renovate updates it.

## Local runs

```bash
molecule test                              # basic test
HCLOUD_PRIVATE_NET=true molecule test      # with private networking
INSTANCE_SIZE=cx33 molecule test           # different server type
```

`examples/Makefile` copies a scenario into a role and runs molecule with the same environment as CI.

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
