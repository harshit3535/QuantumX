from app.models import Plan, AgentResult, Segment
from app.response.composer import compose

def test_code_composer_keeps_files_and_artifact_bundle():
    plan=Plan(kind="task",goal="Build a login page",steps=[],team="Build & Review",deliverables=["Complete files"],success_criteria=["Files work"])
    result=AgentResult(agent="code_agent",segments=[
        Segment(type="text",content="Built the requested login page."),
        Segment(type="code",language="html",filename="index.html",content="<html><body><h1>Login</h1></body></html>"),
        Segment(type="code",language="css",filename="styles.css",content="body{margin:0}"),
        Segment(type="code",language="javascript",filename="script.js",content="console.log('ready')"),
    ])
    out,_=compose(plan,[(1,result)])
    assert out.response_type == "code"
    assert len(out.meta["artifacts"][0]["files"]) == 3
    assert any(s.type=="code" and s.filename=="index.html" for s in out.segments)
