#!/usr/bin/env python3
"""Check a role's argument specs and asserts against the infra inventories.

usage: infra-spec-check.py ROLE_DIR INFRA_DIR [ROLE_NAME]

The infra playbooks (INFRA_DIR/*.yml) say which hosts run the role: every play that lists the role
under roles:, or includes/imports it in its tasks, together with the entry's when: clauses. Each
playbook runs against the inventories the infra Makefile uses for it (PLAYBOOK_INVENTORIES), and
every host there where the condition holds runs the role's tasks/assert.yml and validates
meta/argument_specs.yml (entry point main) with the host's real variables, over a local connection;
nothing touches the hosts. Clauses that test facts, variables the play's pre_tasks set at runtime
(set_fact, register) or group_vars computed from facts count as true: CI knows none of them. The
play gathers package facts first, like infra's pre_tasks; values computed from them then follow the
runner's packages, which is fine for type and shape checks.

Failures print the host, the task and the assertion or type error, never variable values (the
inventories hold secrets). Exit 1 on any failure, 0 otherwise, also when no playbook applies the
role.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

# As in the infra Makefile: site.yml and the other server playbooks run per server inventory with
# --limit '!localhost'; the workstation playbooks use workstations.yml, github.yml localhost.yml.
WORKSTATION_INVENTORIES = ["workstations.yml"]
PLAYBOOK_INVENTORIES = {"github.yml": ["localhost.yml"]}
SERVER_EXCLUDE = {"workstations.yml", "localhost.yml"}

FACT_CLAUSE = re.compile(r"ansible_facts|\bansible_(distribution|os_family|virtualization|architecture|pkg_mgr|system|kernel|lsb)")
QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")


class _TagLoader(yaml.SafeLoader):
    """SafeLoader that reads !vault and other custom tags as plain strings."""


_TagLoader.add_multi_constructor("!", lambda loader, suffix, node: loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else None)


def load_yaml(path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def fact_derived_vars(infra_dir):
    """group_vars whose value refers to facts (e.g. interfaced from ansible_facts['packages'])."""
    names = set()
    for root, _, files in os.walk(os.path.join(infra_dir, "group_vars")):
        for fname in files:
            if not fname.endswith((".yml", ".yaml")):
                continue
            with open(os.path.join(root, fname), encoding="utf-8") as fh:
                text = fh.read()
            if text.startswith("$ANSIBLE_VAULT"):
                continue
            try:
                data = yaml.load(text, Loader=_TagLoader)
            except yaml.YAMLError:
                continue
            if isinstance(data, dict):
                names.update(k for k, v in data.items() if FACT_CLAUSE.search(json.dumps(v, default=str)))
    return names


def role_name(role_dir, fallback):
    meta = os.path.join(role_dir, "meta", "main.yml")
    if os.path.isfile(meta):
        info = (load_yaml(meta) or {}).get("galaxy_info") or {}
        if info.get("role_name"):
            return info["role_name"]
    return fallback.replace("-", "_")


def as_list(when):
    if when is None:
        return []
    return when if isinstance(when, list) else [when]


def runtime_names(infra_dir, tasks, depth=0):
    """Variables that tasks set at runtime: set_fact keys and register names, also in imported files."""
    names = set()
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        if isinstance(task.get("register"), str):
            names.add(task["register"])
        for key in ("ansible.builtin.set_fact", "set_fact"):
            if isinstance(task.get(key), dict):
                names.update(k for k in task[key] if k != "cacheable")
        for key in ("block", "rescue", "always"):
            names |= runtime_names(infra_dir, task.get(key), depth)
        for key in ("ansible.builtin.import_tasks", "ansible.builtin.include_tasks", "import_tasks", "include_tasks"):
            ref = task.get(key)
            ref = ref.get("file") if isinstance(ref, dict) else ref
            path = os.path.join(infra_dir, ref) if isinstance(ref, str) and "{{" not in ref else ""
            if depth < 3 and os.path.isfile(path):
                names |= runtime_names(infra_dir, load_yaml(path), depth + 1)
    return names


def walk_tasks(tasks, inherited=()):
    """Every task with the when clauses of its enclosing blocks plus its own."""
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        when = [*inherited, *as_list(task.get("when"))]
        if any(k in task for k in ("block", "rescue", "always")):
            for key in ("block", "rescue", "always"):
                yield from walk_tasks(task.get(key), when)
        else:
            yield task, when


def entry_conditions(infra_dir, name):
    """(playbook, when clauses, runtime names) per playbook entry that applies the role."""
    derived = fact_derived_vars(infra_dir)
    entries = []
    for fname in sorted(os.listdir(infra_dir)):
        if not fname.endswith((".yml", ".yaml")):
            continue
        try:
            plays = load_yaml(os.path.join(infra_dir, fname))
        except yaml.YAMLError:
            continue
        if not isinstance(plays, list):
            continue
        for play in plays:
            if not isinstance(play, dict) or "hosts" not in play:
                continue
            runtime = runtime_names(infra_dir, play.get("pre_tasks")) | derived
            for item in play.get("roles") or []:
                rname = item.get("role") or item.get("name") if isinstance(item, dict) else item
                if rname == name:
                    entries.append((fname, as_list(item.get("when") if isinstance(item, dict) else None), runtime))
            for section in ("pre_tasks", "tasks", "post_tasks"):
                for task, when in walk_tasks(play.get(section)):
                    for key in ("ansible.builtin.include_role", "ansible.builtin.import_role", "include_role", "import_role"):
                        args = task.get(key)
                        if isinstance(args, dict) and args.get("name") == name:
                            entries.append((fname, when, runtime))
    return entries


def condition(entries):
    """Jinja test for 'some entry applies the role', fact and runtime clauses dropped."""
    parts = []
    for _, clauses, runtime in entries:
        def runtime_only(clause):
            return any(re.search(rf"\b{re.escape(n)}\b", str(clause)) for n in runtime)
        kept = [f"({c})" for c in clauses if not FACT_CLAUSE.search(str(c)) and not runtime_only(c)]
        if not kept:
            return "true"
        parts.append(" and ".join(kept))
    return " or ".join(f"({p})" for p in parts)


def play_text(name, role_dir, cond):
    spec = os.path.join(role_dir, "meta", "argument_specs.yml")
    has_assert = os.path.isfile(os.path.join(role_dir, "tasks", "assert.yml"))
    tasks = [{
        "name": "Load the role defaults" + (" and run its asserts" if has_assert else ""),
        "ansible.builtin.import_role": {"name": name, "tasks_from": "assert.yml" if has_assert else "main.yml"},
        "when": [cond] if has_assert else [False],
    }]
    if os.path.isfile(spec):
        tasks.append({
            "name": "Validate the argument specs",
            "ansible.builtin.validate_argument_spec": {
                "argument_spec": "{{ (lookup('ansible.builtin.file', %r) | from_yaml).argument_specs.main.options }}" % spec,
            },
            "when": [cond],
        })
    pre = [{"name": "Gather package facts like infra's pre_tasks", "ansible.builtin.package_facts": {}}]
    return yaml.safe_dump([{"name": f"Infra spec check: {name}", "hosts": "all", "connection": "local",
                            "gather_facts": True, "pre_tasks": pre, "tasks": tasks}], sort_keys=False)


def failures(output):
    """host, task, reason from default-callback output; values stay out."""
    found, task = [], ""
    for line in output.splitlines():
        m = re.match(r"TASK \[(.*)\]", line)
        if m:
            task = m.group(1)
            continue
        m = re.match(r"fatal: \[([^\]]+)\]: FAILED! => (\{.*\})\s*$", line)
        if not m:
            continue
        try:
            res = json.loads(m.group(2))
        except ValueError:
            res = {}
        if res.get("assertion"):
            reason = "assertion failed: " + str(res["assertion"])
        else:
            msg = " ".join(str(res.get("msg", "failed")).split())
            # spec errors name the argument and the type; the rest can quote the value
            msg = re.sub(r"(unable to convert to \w+)[^;]*", r"\1", msg)
            msg = re.sub(r"(got:)[^;]*", r"\1 ***", msg)
            # undefined-variable, missing-attribute and spec errors quote names, not values
            if not re.search(r"is undefined|has no attribute|Validation of arguments failed", msg):
                msg = QUOTED.sub("'***'", msg)
            reason = msg[:400]
        found.append((m.group(1), task, reason))
    return found


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    role_dir, infra_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    name = role_name(role_dir, sys.argv[3] if len(sys.argv) > 3 else os.path.basename(role_dir))
    entries = entry_conditions(infra_dir, name)
    if not entries:
        print(f"{name}: no infra playbook applies this role, nothing to check")
        return 0
    failed = []
    inv_dir = os.path.join(infra_dir, "inventories")
    inventories = sorted(i for i in os.listdir(inv_dir) if i.endswith((".yml", ".yaml", ".ini")))
    with tempfile.TemporaryDirectory(prefix="infra-spec-") as tmp:
        os.makedirs(os.path.join(tmp, "roles"))
        os.symlink(role_dir, os.path.join(tmp, "roles", name))
        for sub in ("group_vars", "host_vars"):
            if os.path.isdir(os.path.join(infra_dir, sub)):
                os.symlink(os.path.join(infra_dir, sub), os.path.join(tmp, sub))
        env = dict(os.environ, ANSIBLE_ROLES_PATH=os.path.join(tmp, "roles"), ANSIBLE_STDOUT_CALLBACK="default",
                   ANSIBLE_CALLBACK_RESULT_FORMAT="json", ANSIBLE_NOCOLOR="1", ANSIBLE_LOCAL_TEMP=os.path.join(tmp, "tmp"))
        for playbook in sorted({f for f, _, _ in entries}):
            cond = condition([e for e in entries if e[0] == playbook])
            if playbook.startswith("workstation"):
                invs, limit = WORKSTATION_INVENTORIES, []
            elif playbook in PLAYBOOK_INVENTORIES:
                invs, limit = PLAYBOOK_INVENTORIES[playbook], []
            else:
                invs, limit = [i for i in inventories if i not in SERVER_EXCLUDE], ["--limit", "!localhost"]
            print(f"{name}: applied by {playbook} on {', '.join(invs)}; host condition: {cond}")
            with open(os.path.join(tmp, "play.yml"), "w", encoding="utf-8") as fh:
                fh.write(play_text(name, role_dir, cond))
            for inv in invs:
                if inv not in inventories:
                    continue
                failed += check_inventory(tmp, env, os.path.join(inv_dir, inv), inv, limit)
    for inv, host, task, reason in failed:
        print(f"FAIL {inv} {host}: {task}: {reason}")
    return 1 if failed else 0


def check_inventory(tmp, env, inv_path, inv, limit):
    """Run the generated play against one inventory; failures as (inventory, host, task, reason)."""
    # Extra vars outrank inventory variables: an ansible_connection or ansible_become set in an
    # inventory must never turn this into a real connection or a privilege escalation.
    proc = subprocess.run(["ansible-playbook", "-i", inv_path, *limit,
                           "-e", "ansible_connection=local", "-e", "ansible_become=false",
                           "-e", "ansible_python_interpreter=" + (shutil.which("python3") or "python3"), "play.yml"],
                          cwd=tmp, env=env, capture_output=True, text=True)
    out = proc.stdout + proc.stderr
    found = failures(out)
    recap = re.findall(r"^(\S+)\s+: ok=\d+\s+changed=\d+\s+unreachable=\d+\s+failed=(\d+)\s+skipped=(\d+)", out, re.M)
    checked = [h for h, f, s in recap]
    if proc.returncode != 0 and not found:
        last = [l for l in out.splitlines() if "ERROR" in l or "error" in l.lower()][-1:]
        found = [("-", "ansible-playbook", QUOTED.sub("'***'", last[0]) if last else f"exit {proc.returncode}")]
    print(f"  {inv}: {len(checked)} hosts, {'FAILED' if found else 'ok'}")
    return [(inv, *f) for f in found]


if __name__ == "__main__":
    sys.exit(main())
