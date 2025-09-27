# Molecule

CI/CD infrastructure for Molecule-based Ansible testing with multiple cloud providers

# Containers

## Lint

Based on latest alpine with following software:
- bash
- curl
- ansible-lint
- shellcheck
- yamllint

## Ubuntu

Upstream Ubuntu 20.04 / 22.04 Docker Container with following extensions:

- Cron
- DNSmasq
- GnuPG
- Python3
- Rsyslog
- SystemD
...

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
- `INSTANCE_SIZE`: Server type (default: `cax11`)
- `INSTANCE_REGION`: Location (default: `fsn1`)
- `MOLECULE_DISTRO`: OS image (default: `debian-13`)

### Resource Management
- Servers use ARM64 `cax11` instances by default (cost-effective)
- Automatic cleanup of all resources after testing
- Labels applied: `environment: molecule`, `project: <project-name>`, `managed-by: molecule`

# Usage

## CI Workflow
Ansible roles are tested using standardized molecule workflows with the following structure:

### Test Execution Order
1. **Changes Detection**: Skip tests if no relevant files changed
2. **Lint**: Ansible-lint and yamllint validation
3. **Unit Tests**: Sequential execution (Debian → Ubuntu)
4. **Integration Tests**: Full deployment tests with fault tolerance

### Workflow Features
- **Concurrency Control**: New runs automatically cancel older ones
- **Reduced Verbosity**: `ANSIBLE_VERBOSITY=1` for cleaner output
- **Environment Parameterization**: Configurable distros and scenarios
- **Fault Tolerance**: Integration tests can proceed even if some unit tests fail

### Example Usage
```bash
# Basic test
molecule test

# With private networking
HCLOUD_PRIVATE_NET=true molecule test

# Different instance size
INSTANCE_SIZE=cx22 molecule test
```

# Configuration
## Only Lint, no Molecule Tests

If your role is not testable inside a Container ( no AWS credentials, hardware related playbook ... ) you can still use the linting,
by setting the following attribute in your roles `meta/main.yml`

```yaml
galaxy_info:
...
  min_ansible_container_version: "X"
...
```

## Allow CI matrix jobs to fail

If you want to include tests which are not mandatory, mark them as `experimental: true`

```yaml
....
  molecule:
    ...
    strategy:
      fail-fast: false
      matrix:
        include:
          ...
          - distro: ubuntu-22.04
            test_type: unit
            python_version: '3.10'
            experimental: true

```

## Include prerequisite role

* Create `molecule/default/requirements.yml` inside the repository with following content and replace values as needed:

```yaml
- src: https://github.com/Rheinwerk/ansible-role-example.git
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
      when: ansible_os_family == 'Debian'

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
      when: ansible_os_family == 'Debian'

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
