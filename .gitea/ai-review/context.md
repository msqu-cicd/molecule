# CICD/molecule

Shared molecule scenarios (`scenarios/kvm`, `scenarios/hetznercloud`, `scenarios/ec2`, `scenarios/vultr`)
and reusable workflows (`.gitea/workflows/role-*.yml`) for the Ansible roles of the private Gitea org
`Ansible`. Each role carries only a short caller (`examples/caller-molecule.yml`). Single maintainer,
private repositories.

Decisions that are deliberate:

- `role-kvm.yml` is the default for roles: unit and integration run as QEMU guests on the `kvm` runner
  (node.bastelpappe.de, capacity 2). `role-hetznercloud.yml` is only for multi-node scenarios whose
  servers must reach each other (k3s, rke2); `role-vultr.yml` for the Arch/macOS workstation roles.
- Debian 13 only: the fleet runs nothing else, so there are no Ubuntu jobs.
- Pushes to the default branch skip the integration test (kvm) or every Hetzner job (hetznercloud),
  and the `changes` job skips lint and tests for a merge whose tree equals its tested pull request
  head (or a fast-forward to it). The skip is fail-open: a failed status lookup runs the tests.
- The status lookup uses `https://git.msqu.de` on purpose: the instance's ROOT_URL is http.
- Hetzner server types fall back across x86 and Arm per size; roles must not depend on the CPU
  architecture.
- kvm guests get a fixed MAC and a NoCloud network-config that names the NIC `eth0`, like the servers.
- Daemonized QEMU is reparented to the job container's non-reaping PID 1 and stays a zombie after
  SIGTERM; destroy treats state Z as gone.
- Runs of one role repository share the concurrency group `molecule-tests` (server and DNS names are
  `molecule-<repo>`) and queue instead of cancelling (`cancel-in-progress: false`).
- The runner image is pinned by digest; Renovate bumps it.
