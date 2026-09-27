const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const script=fs.readFileSync('master/assets/viewer-recorder.js','utf8');
function harness(supported=true){
 const el={record:{setAttribute(){}},saveClip:{hidden:true},recordNote:{},video:{srcObject:null}},events={},recorders=[],revoked=[];
 let next=0;
 class Recorder{
  static isTypeSupported(t){return t==='video/mp4';}
  constructor(stream,options){this.mimeType=options.mimeType;this.state='inactive';recorders.push(this);}
  start(){this.state='recording';}stop(){this.state='inactive';this.ondataavailable({data:new Blob(['video'],{type:this.mimeType})});this.onstop();}
 }
 const body={dataset:{}},window={confirm:()=>true,addEventListener(n,f){events[n]=f;}};
 const context={document:{getElementById:id=>el[id],body},window,Blob,URL:{createObjectURL:()=>`blob:${++next}`,revokeObjectURL:u=>revoked.push(u)},Date,setInterval:()=>1,clearInterval(){}};
 if(supported)context.MediaRecorder=Recorder;
 vm.runInNewContext(script,context);return{el,body,window,events,recorders,revoked,live(){el.video.srcObject={getVideoTracks:()=>[{readyState:'live'}]};}};
}
test('no stream or unsupported recorder never requests microphone and does not record',()=>{
 const h=harness(false);assert.equal(h.el.record.disabled,true);
 const v=harness();v.el.record.onclick();assert.equal(v.recorders.length,0);assert.match(v.el.recordNote.textContent,/изображения/);
});
test('receiving stream records locally; explicit stop creates MP4 download and no auto restart',()=>{
 const h=harness();h.live();h.el.record.onclick();assert.equal(h.body.dataset.recording,true);
 h.el.record.onclick();assert.equal(h.body.dataset.recording,false);assert.equal(h.el.saveClip.hidden,false);
 assert.match(h.el.saveClip.download,/\.mp4$/);assert.equal(h.el.saveClip.href,'blob:1');
});
test('network close finalizes partial clip and warns before losing unsaved data',()=>{
 const h=harness();h.live();h.el.record.onclick();h.window.fitLabRecorder.stop('Связь потеряна');
 assert.equal(h.el.saveClip.hidden,false);let prevented=false;
 h.events.beforeunload({preventDefault(){prevented=true;}});assert.equal(prevented,true);
 h.window.confirm=()=>false;h.el.record.onclick();assert.equal(h.recorders.length,1);assert.equal(h.el.saveClip.href,'blob:1');
});
test('memory limit stops recording and previous object URL is released only on new capture',()=>{
 const h=harness();h.live();h.el.record.onclick();h.recorders[0].ondataavailable({data:{size:128*1024*1024}});
 assert.equal(h.recorders[0].state,'inactive');assert.equal(h.el.saveClip.hidden,false);
 h.el.record.onclick();assert.deepEqual(h.revoked,['blob:1']);
});
