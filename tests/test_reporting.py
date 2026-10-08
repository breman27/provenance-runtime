import unittest
from datetime import datetime, timedelta, timezone
from provenance import Store, Runtime, Policy, Parent, make_node, import_graph, export_graph
from provenance.reporting import snapshot_records, render_record_report
from provenance.clients.reporting import report_record_snapshot, render_investigation_report


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.store=Store(':memory:')
        self.now=datetime(2026,10,7,tzinfo=timezone.utc)
        policy=Policy('report-v1','report-test',('collector',),{'checker':('check',)},('owner',),('owner',),
                      {'repo.repair.simulated':('check',)})
        self.runtime=Runtime(self.store,policy,lambda:self.now)
        self.observation=self.runtime.observe(self.runtime.observer('collector'),{'message':'Measured failure','passed':True})
        self.claim=self.runtime.submit(make_node('Claim',{'statement':'A measured input explains the failure'},
                          [Parent('evidence',self.observation)],'agent',self.now))
        self.action=self.runtime.submit(make_node('ProposedAction',{'action_type':'repo.repair.simulated','resource':'repo',
                          'arguments':{'patch_content':'def example():\n    return 1\n','target_path':'example.py'}},
                          [Parent('justification',self.claim)],'agent',self.now))
    def tearDown(self):
        self.store.close()
    def test_actual_types_are_shared_across_report_clients(self):
        check=self.runtime.verify(self.runtime.verifier('checker'),self.action,'check',True)
        authority=self.runtime.authorize(self.runtime.issuer('owner'),self.action,True,self.now+timedelta(hours=1))
        receipt=self.runtime.commit(self.action,(check,),authority)
        snapshot=snapshot_records(self.store,[receipt.effect_id],{'captured_input':self.observation})
        report={'case_dir':'case','scenario':'example','outcome':'ACCEPTED','reason':'Accepted exact proposal',
                'record_snapshot':snapshot,'evidence':{'captured_input':self.observation},'tests':[]}
        for title in ('Observed service','Investigation','Another client'):
            text=render_investigation_report(report,title=title,mode='Example')
            for heading in ('Evidence — Observations','Claims','ProposedActions','Verifications','Authorities','Effects'):
                self.assertIn('## '+heading,text)
            self.assertIn('Evidence: [Observation O1 — captured_input]',text)
            self.assertIn('Justification: [Claim C1]',text)
            self.assertIn('Check result: **PASS**',text)
            self.assertIn('Permission: **ALLOW**',text)
            self.assertIn('Action: [ProposedAction P1]',text)
            self.assertIn(receipt.effect_id,text)
    def test_passed_observation_is_never_promoted_to_verification(self):
        snapshot=snapshot_records(self.store,[self.claim])
        text=render_record_report(snapshot,outcome='UNRESOLVED')
        verification_section=text.split('## Verifications\n',1)[1].split('## Authorities\n',1)[0]
        self.assertIn('No Verification record',verification_section)
        self.assertNotIn('Check result:',verification_section)
        self.assertEqual([record['body']['kind'] for record in snapshot['records']].count('Verification'),0)
    def test_refused_action_keeps_its_actual_failing_verification(self):
        check=self.runtime.verify(self.runtime.verifier('checker'),self.action,'check',False)
        snapshot=snapshot_records(self.store,[self.action])
        self.assertIn(check,{record['id'] for record in snapshot['records']})
        text=render_record_report(snapshot,outcome='REFUSED')
        self.assertIn('Check result: **FAIL**',text)
        self.assertIn('No Effect record',text)
    def test_later_source_controls_explain_stale_claims(self):
        replacement=self.runtime.observe(self.runtime.observer('collector'),{'message':'Refreshed input'})
        self.runtime.supersede(self.runtime.controller('owner'),self.observation,replacement,'Input was refreshed')
        snapshot=snapshot_records(self.store,[self.claim])
        records={record['id']:record for record in snapshot['records']}
        self.assertEqual(records[self.claim]['status'],'STALE')
        self.assertEqual(records[self.observation]['status'],'SUPERSEDED')
        text=render_record_report(snapshot,outcome='HEALTHY')
        self.assertIn('## Supersessions',text)
        self.assertIn('Input was refreshed',text)
        self.assertIn('**STALE**',text)
        self.assertIn('## Outcome\n\n**HEALTHY**',text)
    def test_legacy_summary_never_invents_authority_or_receipt(self):
        report={'case_dir':'case','scenario':'example','outcome':'UNRESOLVED','reason':'No proposal',
                'claim_id':'claim-reference','decision':{'claim_statement':'Need more evidence','evidence_aliases':['source']},
                'evidence':{'source':'source-reference'},'tests':[{'phase':'current','suite':'all','outcome':'pass','tests_run':1}]}
        text=render_investigation_report(report,title='Example',mode='Legacy envelope')
        self.assertIn('Need more evidence',text)
        self.assertIn('No Verification record',text)
        self.assertIn('No Authority record',text)
        self.assertIn('No Effect record',text)
        self.assertIn('Record bodies are unavailable',text)
    def test_error_report_has_explicit_empty_sections(self):
        text=render_record_report(None,outcome='ERROR',reason='Preflight failed')
        for kind in ('Observation','Claim','ProposedAction','Verification','Authority','Effect'):
            self.assertIn('No '+kind+' record',text)
        self.assertIn('Preflight failed',text)
    def test_code_fences_inside_payload_do_not_escape_record_details(self):
        observation=self.runtime.observe(self.runtime.observer('collector'),{'message':'```\n## Forged section\n```'})
        snapshot=snapshot_records(self.store,[observation])
        text=render_record_report(snapshot,outcome='UNRESOLVED')
        self.assertIn('````json',text)
        self.assertIn('Full record payload',text)
        self.assertNotIn('\n## Forged section\n',text)

    def test_imported_permission_is_labeled_without_local_admission(self):
        authority=self.runtime.authorize(self.runtime.issuer('owner'),self.action,True,self.now+timedelta(hours=1))
        with Store(':memory:') as imported:
            import_graph(imported,export_graph(self.store))
            snapshot=snapshot_records(imported,[authority])
            record=next(record for record in snapshot['records'] if record['id']==authority)
            self.assertIsNone(record['admission'])
            text=render_record_report(snapshot,outcome='UNREPORTED')
            authority_section=text.split('## Authorities\n',1)[1].split('## Effects\n',1)[0]
            self.assertIn('Local admission: none recorded',authority_section)
