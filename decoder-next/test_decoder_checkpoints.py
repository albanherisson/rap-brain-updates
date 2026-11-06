"""Isolated decoder resume tests: synthetic songs, SQLite and fake Ollama only."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest


SERVER = Path(__file__).with_name('server.py')


class DecoderCheckpointTests(unittest.TestCase):
 def setUp(self):
  self.tmp = tempfile.TemporaryDirectory(prefix='rapbrain-decoder-test-')
  self.addCleanup(self.tmp.cleanup)
  self.old_data = os.environ.get('RAP_BRAIN_DATA')
  os.environ['RAP_BRAIN_DATA'] = self.tmp.name
  self.addCleanup(self.restore_environment)
  sys.path.insert(0,str(SERVER.parent))
  self.addCleanup(lambda: sys.path.remove(str(SERVER.parent)))
  # The decoder does not invoke the separate Creative Engine or RAG modules.
  previous={name:sys.modules.get(name) for name in ('creative_engine','creative_rag')}
  for name in previous:sys.modules[name]=types.ModuleType(name)
  def restore_imports():
   for name,module in previous.items():
    if module is None:sys.modules.pop(name,None)
    else:sys.modules[name]=module
  self.addCleanup(restore_imports)
  spec=importlib.util.spec_from_file_location('synthetic_decoder_server',SERVER)
  self.server=importlib.util.module_from_spec(spec)
  spec.loader.exec_module(self.server)
  self.server.init()
  self.lyrics='Silver train under city light\nCold rain on the avenue tonight\nI count the stops and write another line'
  with self.server.conn() as c:
   self.track=c.execute('INSERT INTO tracks(artist,title,lyrics) VALUES(?,?,?)',('Invented','Synthetic',self.lyrics)).lastrowid
   self.job=c.execute('INSERT INTO jobs(track_id) VALUES(?)',(self.track,)).lastrowid
  self.calls=0
  def fake_ollama(messages,**kwargs):
   self.calls+=1
   return self.make_output(messages)
  self.server.call_ollama=fake_ollama

 def make_output(self,messages):
  prompt=messages[0]['content']
  targets=json.loads(prompt.split(' TARGET: ',1)[1])
  return json.dumps({'lines':[{'line':line['index'],'interpretation':'Une scène de voyage',
   'intention':'Peut évoquer un déplacement','slang':[],'wordplay':[],
   'rhymes':[],'references':[],'writing_lesson':'Écrire une scène originale',
   'techniques':['image'],'confidence':'plausible'} for line in targets]})

 def restore_environment(self):
  if self.old_data is None:os.environ.pop('RAP_BRAIN_DATA',None)
  else:os.environ['RAP_BRAIN_DATA']=self.old_data

 def run_job(self):
  # The macOS maintenance wrapper uses the real user's home directory; exercise
  # its wrapped decoder function against only this synthetic database.
  self.server._rb_original_job_runner_v1(self.job,self.track)
  return self.server.rows('SELECT status,error FROM jobs WHERE id=?',(self.job,))[0]

 def retry(self):
  with self.server.conn() as c:c.execute("UPDATE jobs SET status='pending' WHERE id=?",(self.job,))

 def test_valid_checkpoint_is_reused_without_model_call(self):
  self.assertEqual('done',self.run_job()['status'])
  self.assertEqual(1,self.calls)
  self.retry()
  self.assertEqual('done',self.run_job()['status'])
  self.assertEqual(1,self.calls)
  self.assertEqual(1,len(self.server.rows('SELECT id FROM analyses')))

 def test_missing_report_is_redecoded(self):
  self.assertEqual('done',self.run_job()['status'])
  with self.server.conn() as c:c.execute('DELETE FROM analyses')
  self.retry()
  self.assertEqual('done',self.run_job()['status'])
  self.assertEqual(2,self.calls)
  self.assertEqual(1,len(self.server.rows('SELECT id FROM analyses')))

 def test_misdirected_checkpoint_preserves_unrelated_analysis(self):
  self.assertEqual('done',self.run_job()['status'])
  with self.server.conn() as c:
   other=c.execute('INSERT INTO tracks(artist,title,lyrics) VALUES(?,?,?)',('Other','Track','unrelated')).lastrowid
   innocent=c.execute('INSERT INTO analyses(track_id,kind,content) VALUES(?,?,?)',(other,'manual','Original report')).lastrowid
   c.execute('UPDATE job_segments SET analysis_id=? WHERE job_id=?',(innocent,self.job))
  self.retry()
  self.assertEqual('done',self.run_job()['status'])
  self.assertEqual(2,self.calls)
  self.assertEqual('Original report',self.server.rows('SELECT content FROM analyses WHERE id=?',(innocent,))[0]['content'])
  self.assertEqual(3,len(self.server.rows('SELECT id FROM analyses')))

 def test_changed_lyrics_preserve_old_report(self):
  self.assertEqual('done',self.run_job()['status'])
  old=self.server.rows('SELECT id,content FROM analyses')[0]
  with self.server.conn() as c:c.execute('UPDATE tracks SET lyrics=? WHERE id=?',(self.lyrics.replace('Cold rain','Warm rain'),self.track))
  self.retry()
  self.assertEqual('done',self.run_job()['status'])
  self.assertEqual(2,self.calls)
  self.assertEqual(old['content'],self.server.rows('SELECT content FROM analyses WHERE id=?',(old['id'],))[0]['content'])
  self.assertEqual(2,len(self.server.rows('SELECT id FROM analyses')))

 def test_malformed_saved_report_is_redecoded_without_overwrite(self):
  self.assertEqual('done',self.run_job()['status'])
  old=self.server.rows('SELECT id FROM analyses')[0]['id']
  with self.server.conn() as c:c.execute('UPDATE analyses SET content=? WHERE id=?',('incomplete historical report',old))
  self.retry()
  self.assertEqual('done',self.run_job()['status'])
  self.assertEqual(2,self.calls)
  self.assertEqual('incomplete historical report',self.server.rows('SELECT content FROM analyses WHERE id=?',(old,))[0]['content'])
  self.assertEqual(2,len(self.server.rows('SELECT id FROM analyses')))

 def test_wrong_report_range_is_not_accepted_as_checkpoint(self):
  self.assertEqual('done',self.run_job()['status'])
  old=self.server.rows('SELECT id,content FROM analyses')[0]
  with self.server.conn() as c:
   c.execute('UPDATE analyses SET content=? WHERE id=?',
    (old['content'].replace('## Lignes 1–3/3','## Lignes 1–2/3'),old['id']))
  self.retry()
  self.assertEqual('done',self.run_job()['status'])
  self.assertEqual(2,self.calls)
  self.assertEqual(2,len(self.server.rows('SELECT id FROM analyses')))

 def test_resume_after_later_batch_fails_preserves_first_batch(self):
  lines=[f'Original rap line number {n} with enough words' for n in range(1,8)]
  with self.server.conn() as c:c.execute('UPDATE tracks SET lyrics=? WHERE id=?',('\n'.join(lines),self.track))
  def fail_second(messages,**kwargs):
   targets=json.loads(messages[0]['content'].split(' TARGET: ',1)[1])
   if targets[0]['index']>=4:raise RuntimeError('Synthetic model outage')
   return self.make_output(messages)
  self.server.call_ollama=fail_second
  self.assertEqual('error',self.run_job()['status'])
  first=self.server.rows('SELECT id,content FROM analyses')[0]
  self.assertEqual(1,len(self.server.rows('SELECT job_id FROM job_segments')))
  observed=[]
  def recovered(messages,**kwargs):
   targets=json.loads(messages[0]['content'].split(' TARGET: ',1)[1])
   observed.append([t['index'] for t in targets])
   return self.make_output(messages)
  self.server.call_ollama=recovered
  self.retry()
  self.assertEqual('done',self.run_job()['status'])
  self.assertEqual([[4,5,6],[7]],observed)
  self.assertEqual(3,len(self.server.rows('SELECT job_id FROM job_segments')))
  self.assertEqual(3,len(self.server.rows('SELECT id FROM analyses')))
  self.assertEqual(first['content'],self.server.rows('SELECT content FROM analyses WHERE id=?',(first['id'],))[0]['content'])

 def test_malformed_batch_falls_back_to_each_line_without_gaps(self):
  def malformed_batch(messages,**kwargs):
   targets=json.loads(messages[0]['content'].split(' TARGET: ',1)[1])
   if len(targets)>1:return '{"lines":[]}'
   return self.make_output(messages)
  self.server.call_ollama=malformed_batch
  self.assertEqual('done',self.run_job()['status'])
  content=self.server.rows('SELECT content FROM analyses')[0]['content']
  entries=json.loads(content.split('\n',1)[1])
  self.assertEqual([1,2,3],[x['line'] for x in entries])
  self.assertEqual(self.lyrics.splitlines(),[x['original_line'] for x in entries])

 def test_nested_lexical_claims_are_well_formed_before_saving(self):
  attempts=[]
  def model(messages,**kwargs):
   attempts.append(messages[0]['content'])
   obj=json.loads(self.make_output(messages))
   if len(attempts)==1:
    obj['lines'][0]['slang']=['invented string, not a definition']
   else:
    obj['lines'][0]['slang']=[{'expression':'Silver train','meaning':'Image de voyage',
      'register':'langage courant'}]
   return json.dumps(obj)
  self.server.call_ollama=model
  self.assertEqual('done',self.run_job()['status'])
  self.assertEqual(2,len(attempts))
  self.assertIn('invalid nested fields',attempts[1])
  report=self.server.rows('SELECT content FROM analyses')[0]['content']
  line=json.loads(report.split('\n',1)[1])[0]
  self.assertEqual('Silver train',line['slang'][0]['expression'])

 def test_malformed_nested_claims_never_complete_a_job(self):
  def model(messages,**kwargs):
   obj=json.loads(self.make_output(messages))
   obj['lines'][0]['wordplay']=[{'expression':'train','mechanism':'vague'}]
   return json.dumps(obj)
  self.server.call_ollama=model
  self.assertEqual('error',self.run_job()['status'])
  self.assertEqual([],self.server.rows('SELECT id FROM analyses'))
  self.assertEqual([],self.server.rows('SELECT job_id FROM job_segments'))

 def test_legacy_checkpoint_with_bad_nested_fields_is_preserved_and_repaired(self):
  self.assertEqual('done',self.run_job()['status'])
  old=self.server.rows('SELECT id,content FROM analyses')[0]
  heading,body=old['content'].split('\n',1)
  legacy=json.loads(body)
  legacy[0]['references']=[{'name':'Unattributed place'}]
  damaged=heading+'\n'+json.dumps(legacy)
  with self.server.conn() as c:
   c.execute('UPDATE analyses SET content=? WHERE id=?',(damaged,old['id']))
  self.retry()
  self.assertEqual('done',self.run_job()['status'])
  self.assertEqual(2,self.calls)
  self.assertEqual(damaged,self.server.rows('SELECT content FROM analyses WHERE id=?',(old['id'],))[0]['content'])
  self.assertEqual(2,len(self.server.rows('SELECT id FROM analyses')))

 def test_long_synthetic_song_keeps_every_original_line(self):
  lines=[f'Invented bar {n} about a silver train under the city lights' for n in range(1,104)]
  with self.server.conn() as c:c.execute('UPDATE tracks SET lyrics=? WHERE id=?',('\n'.join(lines),self.track))
  self.assertEqual('done',self.run_job()['status'])
  self.assertEqual(35,self.calls)
  self.assertEqual(35,len(self.server.rows('SELECT job_id FROM job_segments')))
  reports=self.server.rows('SELECT content FROM analyses ORDER BY id')
  recovered=[entry for report in reports for entry in json.loads(report['content'].split('\n',1)[1])]
  self.assertEqual(list(range(1,104)),[entry['line'] for entry in recovered])
  self.assertEqual(lines,[entry['original_line'] for entry in recovered])


if __name__=='__main__':unittest.main()
