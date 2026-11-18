(()=>{'use strict';
const deck=window.REVIEW_DECK,$=id=>document.getElementById(id),key=`dle-review:${deck.id}:${deck.revision}`;
let saved={};try{const v=JSON.parse(localStorage.getItem(key)||'{}');if(v&&typeof v==='object'&&!Array.isArray(v))saved=v;}catch{}
let queue=[...deck.cards],index=0,revealed=false,session={};
function persist(){try{localStorage.setItem(key,JSON.stringify(saved));}catch{}}
function current(){return queue[index];}
function setQueue(cards){queue=[...cards];index=0;session={};render();}
function render(){
 const card=current(),empty=!card;
 ['card','controls'].forEach(id=>$(id).hidden=empty);document.querySelector('.navigation').hidden=empty;
 $('complete').hidden=!empty;
 const known=deck.cards.filter(c=>saved[c.id]==='known').length;
 $('stats').textContent=`기억났어요 ${known} / ${deck.cards.length}`;
 $('progress').max=Math.max(queue.length,1);$('progress').value=Object.keys(session).length;
 if(empty){$('position').textContent='복습 마침';const good=Object.values(session).filter(v=>v==='known').length;const again=Object.values(session).filter(v=>v==='again').length;$('result').textContent=queue.length?`이번 복습에서 기억난 카드 ${good}장, 다시 볼 카드 ${again}장입니다.`:'아직 다시 볼 카드가 없어요. 전체 복습을 시작해 보세요.';return;}
 revealed=false;$('position').textContent=`${index+1} / ${queue.length} · 한 장씩 떠올리기`;$('card-id').textContent=`EP.${card.episode} · ${card.number.toString().padStart(2,'0')}`;$('situation').textContent=card.situation;$('scene').src=card.art;$('scene').alt=card.situation+' 상황 그림';$('answer').hidden=true;$('grade').hidden=true;$('reveal').hidden=false;$('prompt').hidden=false;$('mode').textContent='기억해서 말하기';$('prev').disabled=index===0;$('download').href=card.front;drawDialogue();$('live').textContent=`${index+1}번째 카드. ${card.situation}`;
}
function drawDialogue(){
 const card=current();$('dialogue').replaceChildren();
 card.dialogue.forEach((d,j)=>{const section=document.createElement('section');section.className='line';const speaker=document.createElement('p');speaker.className='speaker';speaker.textContent=d.speaker;const en=document.createElement('p');en.className='en';
 if(j===card.targetLine){const p=d.en.indexOf(card.target);en.append(document.createTextNode(d.en.slice(0,p)));const target=document.createElement(revealed?'mark':'span');target.textContent=revealed?card.target:'_____';if(!revealed){target.className='blank';target.setAttribute('aria-label','빈칸');}en.append(target,document.createTextNode(d.en.slice(p+card.target.length)));}else en.textContent=d.en;
 const ko=document.createElement('p');ko.className='ko';ko.textContent=d.ko;section.append(speaker,en,ko);$('dialogue').append(section);});
}
function reveal(){if(!current()||revealed)return;revealed=true;drawDialogue();$('target').textContent=current().target;$('meaning').textContent=current().meaning;$('explanation').textContent=current().explanation;$('answer').hidden=false;$('grade').hidden=false;$('reveal').hidden=true;$('prompt').hidden=true;$('mode').textContent='정답 · 기억을 확인해요';$('download').href=current().back;$('live').textContent=`정답: ${current().target}. ${current().meaning}`;$('known').focus({preventScroll:true});}
function grade(value){if(!current()||!revealed)return;saved[current().id]=value;session[current().id]=value;persist();index++;render();if(current())$('reveal').focus({preventScroll:true});else $('restart').focus({preventScroll:true});}
function filtered(){return deck.cards.filter(c=>$('filter').value==='all'||c.episode===$('filter').value);}
function restart(){setQueue(filtered());}
function retry(){setQueue(filtered().filter(c=>saved[c.id]==='again'));}
function shuffle(){const cards=filtered();for(let i=cards.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[cards[i],cards[j]]=[cards[j],cards[i]];}setQueue(cards);}
function move(delta){if(!current())return;index=Math.max(0,Math.min(queue.length-1,index+delta));render();}
const actions={reveal,again:()=>grade('again'),known:()=>grade('known'),next:()=>move(1),prev:()=>move(-1),shuffle,retry,restart,reset:()=>{saved={};persist();restart();}};
Object.entries(actions).forEach(([id,fn])=>$(id).addEventListener('click',fn));$('filter').addEventListener('change',restart);
document.addEventListener('keydown',e=>{if(['INPUT','SELECT','TEXTAREA'].includes(e.target.tagName))return;if(e.code==='Space'&&!['BUTTON','A'].includes(e.target.tagName)){e.preventDefault();reveal();}if(e.key==='1')grade('again');if(e.key==='2')grade('known');if(e.key==='ArrowRight')move(1);if(e.key==='ArrowLeft')move(-1);});
if(deck.youtubeUrl){$('youtube').href=deck.youtubeUrl;$('youtube').hidden=false;}
render();
})();
