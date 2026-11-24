"""Local integration of agent accounting and project erasure; synthetic state only."""
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from studio_runtime import erasure
from studio_runtime.agent_store import Journal
from studio_runtime.store import Store, Conflict, project_erasure_key


class AgentErasureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'state')
        self.journal = Journal(self.store)
        self.project = self.store.create_project('local', 'private project')['id']
        self.other = self.store.create_project('local', 'preserved project')['id']
        self.run = self.journal.create(self.project, {'brief': 'private brief'}, 1)['id']
        self.owner = self.journal.claim(self.run)
        self.budget = self.journal.status(self.run)['budget']

    def settle(self):
        call = self.journal.reserve(self.run, self.owner, {'private': 'prompt'}, 700000)
        self.journal.settle(self.run, self.owner, call, response={'private': 'answer'}, usage={}, charge=600000)
        self.journal.step(self.run, self.owner, 1, {'private': 'decision'})
        self.journal.set_state(self.run, self.owner, 'completed')
        self.journal.release(self.run, self.owner)

    def test_erasure_removes_receipts_but_preserves_shared_spending(self):
        self.settle()
        other_run = self.journal.create(self.other, {}, budget=self.budget)['id']
        other_owner = self.journal.claim(other_run)
        preview = erasure.erase_project(self.store, 'local', self.project)
        self.assertEqual(preview['record_counts']['agent_calls'], 1)
        result = erasure.erase_project(self.store, 'local', self.project, True)
        self.assertTrue(result['complete'], result)
        with self.store.connect() as db:
            for table in ('agent_calls', 'agent_steps'):
                self.assertEqual(db.execute(f'SELECT count(*) FROM {table} WHERE run=?', (self.run,)).fetchone()[0], 0)
            self.assertIsNone(db.execute('SELECT 1 FROM agent_runs WHERE id=?', (self.run,)).fetchone())
            self.assertEqual(db.execute('SELECT retired_microusd FROM agent_budgets WHERE id=?', (self.budget,)).fetchone()[0], 600000)
        self.assertEqual(self.journal.status(other_run)['budget_committed_microusd'], 600000)
        self.assertIsNone(self.journal.reserve(other_run, other_owner, {}, 400001))
        self.assertTrue(erasure.erase_project(self.store, 'local', self.project, True)['complete'])
        self.assertEqual(self.store.get_project('local', self.other)['name'], 'preserved project')

    def test_live_or_unsettled_coordinator_refuses_erasure(self):
        with self.assertRaises(Conflict):
            erasure.erase_project(self.store, 'local', self.project, True)
        self.journal.set_state(self.run, self.owner, 'completed')
        with self.assertRaises(Conflict):
            erasure.erase_project(self.store, 'local', self.project, True)

    def test_uncertain_charge_refuses_erasure_even_if_run_marked_terminal(self):
        self.journal.reserve(self.run, self.owner, {}, 700000)
        self.journal.set_state(self.run, self.owner, 'failed')
        self.journal.release(self.run, self.owner)
        with self.assertRaises(Conflict):
            erasure.erase_project(self.store, 'local', self.project, True)

    def test_scoped_authority_cannot_touch_other_run_or_change_budget(self):
        self.settle()
        other_run = self.journal.create(self.other, {}, budget=self.budget)['id']
        key = project_erasure_key('local', self.project)
        with self.store._connect(erasure_key=key) as db:
            db.execute("INSERT INTO project_erasures VALUES(?,'files',?,NULL,0,0)", (key, time.time()))
            for sql, values in (
                ('DELETE FROM agent_runs WHERE id=?', (other_run,)),
                ('UPDATE agent_budgets SET limit_microusd=2 WHERE id=?', (self.budget,)),
                ('UPDATE agent_budgets SET retired_microusd=0 WHERE id=?', (self.budget,)),
                ('DELETE FROM agent_budgets WHERE id=?', (self.budget,)),
            ):
                with self.assertRaises(sqlite3.DatabaseError):
                    db.execute(sql, values)
        with self.assertRaises(sqlite3.DatabaseError):
            self.journal.budget(1)

    def test_both_schema_six_variants_migrate_and_fence_old_writers(self):
        self.settle()
        for variant in ('canonical_erasure', 'agent_only'):
            with self.subTest(variant=variant):
                root = Path(self.temp.name) / variant
                store = Store(root)
                project = store.create_project('local', variant)['id']
                journal = Journal(store)
                run = journal.create(project, {'brief': 'preserve'}, 1)['id']
                with store.connect() as db:
                    for row in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall():
                        db.execute('DROP TRIGGER "' + row[0] + '"')
                    if variant == 'canonical_erasure':
                        for table in ('agent_steps', 'agent_calls', 'agent_runs', 'agent_budgets'):
                            db.execute('DROP TABLE ' + table)
                    else:
                        db.execute('DROP TABLE project_erasures')
                        db.execute('ALTER TABLE agent_budgets DROP COLUMN retired_microusd')
                    db.execute('PRAGMA user_version=6')
                old = sqlite3.connect(store.db)
                self.addCleanup(old.close)
                old.create_function('studio_writer_version', 0, lambda: 6)
                upgraded = Store(root)
                self.assertEqual(upgraded.get_project('local', project)['name'], variant)
                with upgraded.connect() as db:
                    self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 7)
                    self.assertEqual(db.execute('SELECT count(*) FROM project_erasures').fetchone()[0], 0)
                if variant == 'agent_only':
                    self.assertEqual(Journal(upgraded).status(run)['specification']['brief'], 'preserve')
                    self.assertEqual(Journal(upgraded).status(run)['budget_committed_microusd'], 0)
                with self.assertRaises(sqlite3.DatabaseError):
                    old.execute("UPDATE projects SET name='stale writer' WHERE id=?", (project,))
                old.rollback()


if __name__ == '__main__':
    unittest.main()
