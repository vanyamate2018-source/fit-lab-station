/* Local recording of the received stream. No camera/microphone permission. */
(() => {
 'use strict';
 const $=id=>document.getElementById(id),button=$('record'),save=$('saveClip'),note=$('recordNote'),video=$('video');
 let recorder=null,chunks=[],bytes=0,url=null,started=0,timer=null,unsaved=false;
 const maxBytes=128*1024*1024,maxDuration=10*60*1000;
 const types=['video/mp4;codecs=avc1.42E01E','video/mp4','video/webm;codecs=vp8','video/webm'];
 const supported=typeof MediaRecorder!=='undefined';
 const mime=supported?types.find(type=>MediaRecorder.isTypeSupported(type)):null;
 const message=text=>{note.textContent=text;};
 function stop(reason='Запись готова'){
  if(!recorder||recorder.state==='inactive')return;
  clearInterval(timer);timer=null;button.disabled=true;message(reason+' · сохраняем фрагмент');
  try{recorder.stop();}catch(e){button.disabled=false;document.body.dataset.recording=false;message('Не удалось завершить запись');}
 }
 function update(){
  const elapsed=Date.now()-started;
  button.textContent='Стоп · '+Math.floor(elapsed/60000)+':'+String(Math.floor(elapsed/1000)%60).padStart(2,'0');
  if(elapsed>=maxDuration)stop('Достигнут предел фрагмента');
 }
 button.onclick=()=>{
  if(recorder&&recorder.state!=='inactive'){stop();return;}
  const stream=video.srcObject;
  if(!stream||!stream.getVideoTracks().some(t=>t.readyState==='live')){message('Дождитесь изображения');return;}
  if(unsaved&&!window.confirm('Предыдущая запись ещё доступна по кнопке «Сохранить». Заменить её новой?'))return;
  let next;
  try{next=new MediaRecorder(stream,{mimeType:mime,videoBitsPerSecond:4000000});}
  catch(e){message('Этот браузер не может записать получаемый поток');return;}
  chunks=[];bytes=0;recorder=next;
  next.ondataavailable=e=>{
   if(e.data&&e.data.size){chunks.push(e.data);bytes+=e.data.size;if(bytes>=maxBytes)stop('Фрагмент достиг 128 МБ');}
  };
  next.onerror=()=>stop('Запись прервана браузером');
  next.onstop=()=>{
   clearInterval(timer);timer=null;document.body.dataset.recording=false;button.disabled=false;button.textContent='Запись';button.setAttribute('aria-label','Запись на это устройство');
   if(!chunks.length){message('Нет данных для сохранения');return;}
   const blob=new Blob(chunks,{type:next.mimeType||mime});chunks=[];
   if(url)URL.revokeObjectURL(url);
   url=URL.createObjectURL(blob);save.href=url;
   save.download='FIT-LAB-'+new Date().toISOString().replace(/[:.]/g,'-')+(blob.type.includes('mp4')?'.mp4':'.webm');
   save.hidden=false;unsaved=true;message('Готово · '+(blob.size/1048576).toFixed(1)+' МБ · сохраните на устройство');
  };
  try{next.start(1000);}
  catch(e){recorder=null;message('Запись недоступна для этого потока');return;}
  if(url){URL.revokeObjectURL(url);url=null;}
  unsaved=false;save.hidden=true;started=Date.now();document.body.dataset.recording=true;
  button.setAttribute('aria-label','Остановить запись');message('Запись на этом устройстве · держите страницу открытой');update();timer=setInterval(update,500);
 };
 save.onclick=()=>{message('Выберите сохранение файла. На iPhone запись будет доступна в «Файлах».');};
 window.fitLabRecorder={stop};
 window.addEventListener('beforeunload',e=>{if(unsaved||(recorder&&recorder.state!=='inactive')){e.preventDefault();e.returnValue='';}});
 if(!mime){button.disabled=true;message('Запись не поддерживается этим браузером');}
})();
