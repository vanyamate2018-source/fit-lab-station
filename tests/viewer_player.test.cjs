// State-machine tests, not a browser or a claim of real video decoding.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const script=fs.readFileSync('master/assets/viewer.html','utf8').split('<script>').at(-1).split('</script>')[0];
function player(){
 let now=0,next=0,autoplay=false,postResolve=null,stationState='streaming';
 const tasks=new Map(),intervals=[],peers=[],requests=[],elements={},windowEvents={},documentEvents={},classes=new Set();
 for(const id of ['video','play','screen','fullscreen','exitFullscreen','placeholder','placeholderText','statusText','fps','rate','loss','buffer','size'])
  elements[id]={textContent:'',hidden:false,addEventListener(){},play(){return autoplay?Promise.reject(Error('autoplay')):Promise.resolve();}};
 class Peer{
  constructor(){peers.push(this);this.iceGatheringState='complete';this.connectionState='new';this.stats=new Map();}
  addTransceiver(){} async createOffer(){return {sdp:'offer'};}
  async setLocalDescription(d){this.localDescription=d;} async setRemoteDescription(){this.answered=true;}
  close(){this.closed=true;} async getStats(){return this.stats;}
 }
 const response=()=>({ok:true,headers:{get:()=>'/live/whep/test'},text:async()=>'answer'});
 const sandbox={document:{getElementById:id=>elements[id],body:{dataset:{},classList:{add:c=>classes.add(c),remove:c=>classes.delete(c),contains:c=>classes.has(c)}},hidden:false,addEventListener(n,fn){documentEvents[n]=fn;}},
  window:{addEventListener(n,fn){windowEvents[n]=fn;}},navigator:{onLine:true},location:{origin:'http://192.168.3.1:8890',hostname:'192.168.3.1'},performance:{now:()=>now},RTCPeerConnection:Peer,MediaStream:class{},URL,AbortController,
  setTimeout(fn,delay){const id=++next;tasks.set(id,{fn,at:now+delay});return id;},clearTimeout(id){tasks.delete(id);},setInterval(fn){intervals.push(fn);},
  fetch(url,options={}){if(url==='/status.json')return Promise.resolve({ok:true,json:async()=>({state:stationState})});requests.push({url,method:options.method});if(options.method==='POST'&&postResolve)return new Promise(resolve=>{postResolve.resolve=resolve;});return Promise.resolve(response());}};
 vm.createContext(sandbox);vm.runInContext(script,sandbox);
 const flush=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
 return {elements,peers,requests,sandbox,flush,response,windowEvents,documentEvents,classes,
  station(value){stationState=value;},autoplay(value){autoplay=value;},holdPost(){postResolve={};return postResolve;},
  async tick(ms){now+=ms;for(const fn of intervals)await fn();for(const [id,task] of [...tasks])if(task.at<=now){tasks.delete(id);task.fn();}await flush();}};
}
test('no first frame causes recovery; Stop cancels pending retry and resets metrics',async()=>{
 const p=player();await p.flush();assert.equal(p.peers.length,1);await p.tick(13000);
 assert.equal(p.peers[0].closed,true);assert.match(p.elements.statusText.textContent,/переподключение/);
 p.elements.fps.textContent='30';p.elements.play.onclick();await p.tick(5000);
 assert.equal(p.peers.length,1);assert.equal(p.elements.fps.textContent,'—');assert.equal(p.elements.statusText.textContent,'Остановлено');
});
test('blocked autoplay is playable with one click and keeps the same connection',async()=>{
 const p=player();await p.flush();p.autoplay(true);p.peers[0].ontrack({streams:[{}]});await p.flush();
 assert.equal(p.elements.play.textContent,'Смотреть');await p.tick(20000);assert.equal(p.peers.length,1);
 p.autoplay(false);p.elements.play.onclick();await p.flush();assert.equal(p.elements.play.textContent,'Остановить');assert.equal(p.peers[0].closed,undefined);
});
test('a late WHEP response after Stop deletes its server session and cannot attach media',async()=>{
 const p=player(),held=p.holdPost();await p.flush();assert.equal(typeof held.resolve,'function');
 p.elements.play.onclick();held.resolve(p.response());await p.flush();
 assert.equal(p.peers[0].answered,undefined);assert.equal(p.peers[0].closed,true);
 assert.ok(p.requests.some(r=>r.method==='DELETE'));
});
test('Wi-Fi loss stops retries; network return reconnects unless viewer pressed Stop',async()=>{
 const p=player();await p.flush();p.sandbox.navigator.onLine=false;p.windowEvents.offline();
 await p.tick(30000);assert.equal(p.peers.length,1);assert.match(p.elements.statusText.textContent,/Wi-Fi/);
 p.sandbox.navigator.onLine=true;p.windowEvents.online();await p.flush();assert.equal(p.peers.length,2);
 p.elements.play.onclick();p.windowEvents.online();await p.flush();assert.equal(p.peers.length,2);
});
test('page suspension closes media and return resumes exactly once',async()=>{
 const p=player();await p.flush();p.windowEvents.pagehide();p.windowEvents.online();await p.tick(30000);
 assert.equal(p.peers.length,1);assert.equal(p.peers[0].closed,true);
 p.windowEvents.pageshow();p.windowEvents.pageshow();await p.flush();assert.equal(p.peers.length,2);
});
test('fullscreen fallback works when native API rejects and Escape exits',async()=>{
 const p=player();await p.flush();p.elements.screen.requestFullscreen=async()=>{throw Error('unavailable');};
 await p.elements.fullscreen.onclick();assert.equal(p.classes.has('immersive'),true);
 p.documentEvents.keydown({key:'Escape'});assert.equal(p.classes.has('immersive'),false);
});
test('unsupported statistics display dashes rather than NaN',async()=>{
 const p=player();await p.flush();
 p.peers[0].stats.set('video',{id:'a',type:'inbound-rtp',kind:'video',timestamp:1000});await p.tick(1000);
 p.peers[0].stats.set('video',{id:'a',type:'inbound-rtp',kind:'video',timestamp:2000});await p.tick(1000);
 for(const id of ['fps','rate','loss','buffer'])assert.equal(p.elements[id].textContent,'—');
});

test('station stop keeps page waiting; enabling broadcast resumes without reload',async()=>{
 const p=player();await p.flush();p.station('stopped');await p.tick(3000);
 assert.equal(p.peers[0].closed,true);assert.match(p.elements.statusText.textContent,/выключена/);
 p.station('streaming');await p.tick(3000);assert.equal(p.peers.length,2);
 p.elements.play.onclick();p.station('stopped');await p.tick(3000);p.station('streaming');await p.tick(3000);
 assert.equal(p.peers.length,2);
});
