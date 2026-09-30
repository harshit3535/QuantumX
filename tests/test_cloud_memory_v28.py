from app.memory.db import Database

def test_local_history_and_state_are_saved(tmp_path):
    db=Database(f"sqlite:///{tmp_path/'m.db'}")
    sid=db.create_session('Demo')
    db.add_message(sid,'user','hello')
    db.add_message(sid,'assistant','hi')
    db.set_task_state(sid,{'last_goal':'demo'})
    assert [m['content'] for m in db.history(sid,10)] == ['hello','hi']
    assert db.get_task_state(sid)['last_goal']=='demo'
