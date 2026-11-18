"""Fixture tests for scripts/infra-spec-check.py: python3 -m unittest discover scripts/tests (needs ansible-playbook on PATH).

INFRA_SPEC_CHECK points the tests at another copy of the script."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = os.environ.get("INFRA_SPEC_CHECK") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "infra-spec-check.py")
GOOD = "all:\n  hosts:\n    h1:\n      demo_value: ok\n"
BAD = "all:\n  hosts:\n    h1:\n      demo_value: wrong\n"
SITE = "- hosts: all\n  roles:\n    - demo_role\n"
FILES = {
    "role/meta/argument_specs.yml": "argument_specs:\n  main:\n    options:\n      demo_value:\n        type: str\n        default: ok\n",
    # no quiet: true, the failure result is printed with _ansible_verbose_always
    "role/tasks/assert.yml": "- ansible.builtin.assert:\n    that:\n      - demo_value == 'ok'\n    fail_msg: demo_value must be ok\n",
    "role/tasks/main.yml": "- ansible.builtin.debug:\n    msg: demo\n",
}


# In CI a missing ansible-playbook fails the tests instead of skipping them all
@unittest.skipUnless(shutil.which("ansible-playbook") or os.environ.get("CI"), "ansible-playbook not on PATH")
class InfraSpecCheck(unittest.TestCase):
    def setUp(self):
        self.assertTrue(shutil.which("ansible-playbook"), "ansible-playbook not on PATH")
        self.tmp = tempfile.TemporaryDirectory(prefix="infra-spec-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "demo_role")
        os.makedirs(self.root)
        self.write(FILES)

    def write(self, files):
        for rel, text in files.items():
            path = os.path.join(self.root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)

    def run_check(self, files):
        self.write({f"infra/{k}": v for k, v in files.items()})
        proc = subprocess.run([sys.executable, SCRIPT, os.path.join(self.root, "role"), os.path.join(self.root, "infra"), "demo_role"],
                              capture_output=True, text=True, timeout=300)
        return proc.returncode, proc.stdout + proc.stderr

    def test_passing_role(self):
        rc, out = self.run_check({"site.yml": SITE, "inventories/a.yml": GOOD})
        self.assertEqual(rc, 0, out)
        self.assertIn("a.yml: 1 hosts, ok", out)

    def test_failing_assert_names_host_task_and_message(self):
        rc, out = self.run_check({"site.yml": SITE, "inventories/a.yml": BAD})
        self.assertEqual(rc, 1, out)
        self.assertRegex(out, r"FAIL a\.yml h1: .*: assertion failed: demo_value == 'ok'")
        self.assertNotIn("wrong", out)

    def test_unparsable_inventory_fails(self):
        rc, out = self.run_check({"site.yml": SITE, "inventories/a.yml": GOOD, "inventories/b.yml": "all: [unclosed\n"})
        self.assertEqual(rc, 1, out)
        self.assertNotIn("b.yml: 0 hosts, ok", out)

    def test_empty_inventory_fails(self):
        rc, out = self.run_check({"site.yml": SITE, "inventories/a.yml": GOOD, "inventories/b.yml": "all:\n  hosts: {}\n"})
        self.assertEqual(rc, 1, out)
        self.assertRegex(out, r"FAIL b\.yml -: inventory: no hosts")

    def test_playbook_with_yaml_error_fails(self):
        rc, out = self.run_check({"site.yml": SITE, "broken.yml": "- hosts: all\n  roles: [unclosed\n", "inventories/a.yml": GOOD})
        self.assertEqual(rc, 1, out)
        self.assertIn("broken.yml: playbook does not parse", out)

    def test_only_a_broken_playbook_is_not_nothing_to_check(self):
        rc, out = self.run_check({"broken.yml": "- hosts: all\n  roles: [unclosed\n", "inventories/a.yml": GOOD})
        self.assertEqual(rc, 1, out)
        self.assertNotIn("nothing to check", out)

    def test_include_role_in_imported_task_file(self):
        site = "- hosts: all\n  tasks:\n    - ansible.builtin.import_tasks: tasks/demo.yml\n"
        task_file = "- ansible.builtin.include_role:\n    name: demo_role\n"
        rc, out = self.run_check({"site.yml": site, "tasks/demo.yml": task_file, "inventories/a.yml": BAD})
        self.assertNotIn("nothing to check", out)
        self.assertEqual(rc, 1, out)
        self.assertIn("applied by site.yml", out)

    def test_include_role_in_imported_task_file_keeps_when(self):
        site = "- hosts: all\n  tasks:\n    - ansible.builtin.import_tasks: tasks/demo.yml\n      when: inventory_hostname == 'other'\n"
        task_file = "- ansible.builtin.include_role:\n    name: demo_role\n"
        rc, out = self.run_check({"site.yml": site, "tasks/demo.yml": task_file, "inventories/a.yml": BAD})
        self.assertEqual(rc, 0, out)

    def test_nested_import_relative_to_the_including_file(self):
        site = "- hosts: all\n  tasks:\n    - ansible.builtin.import_tasks: tasks/outer.yml\n"
        outer = "- ansible.builtin.import_tasks: inner.yml\n"
        inner = "- ansible.builtin.include_role:\n    name: demo_role\n"
        rc, out = self.run_check({"site.yml": site, "tasks/outer.yml": outer, "tasks/inner.yml": inner, "inventories/a.yml": BAD})
        self.assertEqual(rc, 1, out)
        self.assertIn("applied by site.yml", out)

    def test_imported_task_file_with_yaml_error_fails(self):
        site = SITE + "- hosts: all\n  tasks:\n    - ansible.builtin.import_tasks: tasks/broken.yml\n"
        rc, out = self.run_check({"site.yml": site, "tasks/broken.yml": "- name: [unclosed\n", "inventories/a.yml": GOOD})
        self.assertEqual(rc, 1, out)
        self.assertIn("site.yml: playbook does not parse", out)
        self.assertNotIn("Traceback", out)


if __name__ == "__main__":
    unittest.main()
