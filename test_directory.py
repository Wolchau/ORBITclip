"""End-to-end client-directory protocol test with an in-memory mock relay (no internet)."""
import hashlib
import json
import threading
import time
import tempfile
from pathlib import Path
from urllib.parse import parse_qs,urlsplit
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from orbit_peers import DeviceIdentity, PeerDirectory
from kinetic_remote import http_json, validate_config

class Handler(BaseHTTPRequestHandler):
    records={};requests={};next_id=1
    def log_message(self,*args):pass
    def respond(self,code,obj):
        raw=json.dumps(obj).encode();self.send_response(code);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_POST(self):
        n=int(self.headers.get('Content-Length','0'))
        payload=json.loads(self.rfile.read(n))
        with mutex:
            if self.path=='/v3/hello':
                Handler.records[payload['device']]={**payload, 'seen':time.time()}
                return self.respond(200,{'ok':True,'peers':[
                    {'id':k,'name':v['name'],'public':v['public'],'version':v['version']}
                    for k,v in self.records.items() if k!=payload['device']]})
            if self.path=='/v3/request':
                n=str(self.next_id);Handler.next_id+=1
                a=self.records[payload['device']];b=self.records[payload['to']]
                Handler.requests[n]={'id':n,'from':payload['device'],'to':payload['to'],
                    'name':a['name'],'from_public':a['public'],'to_public':b['public'],'status':'pending'}
                return self.respond(200,{'id':n})
            if self.path=='/v3/respond':
                self.requests[payload['id']]['status']='accepted' if payload['accept'] else 'declined'
                return self.respond(200,{'ok':True})
        self.respond(404,{})
    def do_GET(self):
        req=urlsplit(self.path);device=parse_qs(req.query).get('device',[''])[0]
        with mutex:
            if req.path=='/v3/requests':
                return self.respond(200,{'requests':[v for v in self.requests.values() if device in (v['from'],v['to'])]})
        self.respond(404,{})

mutex=threading.RLock()
server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
url='http://127.0.0.1:'+str(server.server_port)
cfg={'url':url,'token':'a'*32,'tls_pin':''}
with tempfile.TemporaryDirectory() as d:
    a=DeviceIdentity(Path(d)/'a.json');b=DeviceIdentity(Path(d)/'b.json')
    a.rename('Тестовый компьютер A');b.rename('Тестовый компьютер B')
    da=PeerDirectory(a,lambda:cfg,'7.0.3');db=PeerDirectory(b,lambda:cfg,'7.0.3')
    try:
        cutoff=time.time()+4
        while time.time()<cutoff and len(Handler.records)<2:time.sleep(.1)
        assert len(Handler.records)==2
        da.request(b.id)
        while time.time()<cutoff and not Handler.requests:time.sleep(.1)
        assert Handler.requests
        rid=next(iter(Handler.requests))
        db.respond(rid,True)
        while time.time()<cutoff and Handler.requests[rid]['status']!='accepted':time.sleep(.1)
        assert Handler.requests[rid]['status']=='accepted'
        pa=a.pair(b.id,b.name,b.public)
        pb=b.pair(a.id,a.name,a.public)
        assert pa['pair']==pb['pair']
        print('PASS two live devices, invite request, approval and symmetric derived key')
    finally:
        da.stop();db.stop()
server.shutdown();server.server_close()
