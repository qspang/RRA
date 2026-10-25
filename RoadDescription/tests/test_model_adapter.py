import json
import threading
from http.server import BaseHTTPRequestHandler,HTTPServer
from road_description.narrative import model_call


def test_compatible_model_http_contract(monkeypatch):
    observed={}
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            observed['path']=self.path
            observed['body']=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            observed['auth']=self.headers['Authorization']
            body=json.dumps({'choices':[{'message':{'content':'{"paragraphs":[]}'}}],
                             'usage':{'total_tokens':10}}).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body)
        def log_message(self,*args):pass
    server=HTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    monkeypatch.setenv('TEST_RD_KEY','test-key')
    try:
        data,usage=model_call({'enabled':True,'api_base':f'http://127.0.0.1:{server.server_port}/v1',
                              'model_id':'test-model','api_key_env':'TEST_RD_KEY'},[{'role':'user','content':'test'}])
        assert observed['path']=='/v1/chat/completions'
        assert observed['body']['model']=='test-model'
        assert observed['auth']=='Bearer test-key'
        assert data=={'paragraphs':[]} and usage['total_tokens']==10
    finally:server.shutdown();server.server_close();thread.join()
