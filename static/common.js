const HUB={
 themes:{Merah:['#ff2d4a','#3b82f6'],Biru:['#3b82f6','#8b5cf6'],Hijau:['#22c55e','#06b6d4'],Oranye:['#f97316','#ef4444'],Ungu:['#a855f7','#ec4899'],Pink:['#ec4899','#f59e0b'],Kuning:['#eab308','#f97316'],Cyan:['#06b6d4','#3b82f6'],Toska:['#14b8a6','#22c55e'],Lime:['#84cc16','#22c55e'],Indigo:['#6366f1','#a855f7'],Sakura:['#f472b6','#fb7185'],Emas:['#e0a82e','#b45309'],Neon:['#d946ef','#06b6d4'],Nila:['#4f46e5','#0ea5e9'],Magma:['#ef4444','#f97316'],Mint:['#34d399','#0ea5e9']},
 modes:{dark:{bg:'#0a0a0c',card:'#141416',line:'#2a2a2e',txt:'#f2f2f2',mut:'#9a9aa3',inp:'#1d1d20'},
 amoled:{bg:'#000000',card:'#0b0b0c',line:'#1f1f23',txt:'#f2f2f2',mut:'#8d8d96',inp:'#131315'},
 light:{bg:'#f3f4f7',card:'#ffffff',line:'#dcdfe6',txt:'#15171a',mut:'#667085',inp:'#eef0f4'}},
 def:{theme:'Merah',a:null,b:null,mode:'dark',fs:1,r:14,bg:1,anim:1}};
function getUI(){let u={};try{u=JSON.parse(localStorage.getItem('ui')||'{}')}catch(e){}
 if(!u.theme&&!u.a)u.theme=localStorage.getItem('theme')||'Merah';return{...HUB.def,...u}}
function setUI(p){localStorage.setItem('ui',JSON.stringify({...getUI(),...p}));applyTheme()}
function applyTheme(){const u=getUI(),t=HUB.themes[u.theme]||HUB.themes.Merah,m=HUB.modes[u.mode]||HUB.modes.dark,e=document.documentElement,s=e.style;
 s.setProperty('--acc',u.a||t[0]);s.setProperty('--acc2',u.b||t[1]);for(const k in m)s.setProperty('--'+k,m[k]);
 s.setProperty('--r',u.r+'px');s.zoom=(self===top)?u.fs:1;s.colorScheme=u.mode=='light'?'light':'dark';
 s.dataset.anim=u.anim?'on':'off';
 s.setProperty('--bgi',u.bg?'radial-gradient(900px 400px at 15% 0,color-mix(in srgb,var(--acc) 16%,transparent),transparent),radial-gradient(900px 500px at 85% 0%,color-mix(in srgb,var(--acc2) 12%,transparent),transparent)':'linear-gradient(transparent,transparent)')}
applyTheme();addEventListener('storage',applyTheme);

/* ===== animasi logo ===== */
function splash(full){
 const u=getUI();if(!u.anim)return;
 const o=document.createElement('div');o.className='splash'+(full?'':' mini');
 o.innerHTML=`<img src="/logo.png" alt="Gaje Studio"><div class="sl-t">GAJE <b>STUDIO</b></div>`;
 document.body.appendChild(o);
 setTimeout(()=>o.remove(),full?1900:900);
}
splash(self===top);
addEventListener('hashchange',()=>splash(false));
