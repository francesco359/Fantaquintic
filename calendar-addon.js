/* FantaQuintoc Calendar Add-on v1 - Giornata 7, stagione 2026/27 */
const FQ_CALENDAR={
  7:[
    {home:'FRO',away:'SAS',label:'Frosinone-Sassuolo',date:'Ven 16 ottobre 2026',time:'20:45'},
    {home:'VEN',away:'NAP',label:'Venezia-Napoli',date:'Sab 17 ottobre 2026',time:'15:00'},
    {home:'BOL',away:'INT',label:'Bologna-Inter',date:'Sab 17 ottobre 2026',time:'18:00'},
    {home:'ROM',away:'GEN',label:'Roma-Genoa',date:'Sab 17 ottobre 2026',time:'20:45'},
    {home:'UDI',away:'LEC',label:'Udinese-Lecce',date:'Dom 18 ottobre 2026',time:'12:30'},
    {home:'FIO',away:'COM',label:'Fiorentina-Como',date:'Dom 18 ottobre 2026',time:'15:00'},
    {home:'MIL',away:'ATA',label:'Milan-Atalanta',date:'Dom 18 ottobre 2026',time:'18:00'},
    {home:'JUV',away:'LAZ',label:'Juventus-Lazio',date:'Dom 18 ottobre 2026',time:'20:45'},
    {home:'MON',away:'CAG',label:'Monza-Cagliari',date:'Lun 19 ottobre 2026',time:'18:30'},
    {home:'PAR',away:'TOR',label:'Parma-Torino',date:'Lun 19 ottobre 2026',time:'20:45'}
  ]
};
function fqFixture(player){
  const games=FQ_CALENDAR[Number(S.round)]||[];
  const game=games.find(g=>g.home===player.club||g.away===player.club);
  if(!game)return null;
  return {...game,isHome:game.home===player.club,opponent:game.home===player.club?game.away:game.home};
}
function fqMatchHTML(player){
  const f=fqFixture(player);
  if(!f)return '<small style="display:block;margin-top:4px">Calendario non integrato per questa giornata</small>';
  return `<small style="display:block;color:var(--g);margin-top:4px;font-weight:800">${f.label}</small>
  <small style="display:block">${f.isHome?'Casa':'Trasferta'} · ${f.date} · ${f.time}</small>`;
}
function fqRenderCalendar(){
  const el=document.querySelector('#fqCalendarList');
  if(!el)return;
  const games=FQ_CALENDAR[Number(S.round)]||[];
  el.innerHTML=games.length?games.map(g=>`<div class="pick"><span><b>${g.label}</b></span><span>${g.date} · ${g.time}</span></div>`).join(''):'<div class="alert">Calendario non ancora integrato per questa giornata.</div>';
}
(function installCalendar(){
  const nav=document.querySelector('nav');
  const app=document.querySelector('#app');
  if(nav&&!document.querySelector('[data-tab="fqcalendar"]')){
    nav.insertAdjacentHTML('beforeend','<button data-tab="fqcalendar">Calendario</button>');
    app.insertAdjacentHTML('beforeend','<section id="fqcalendar" class="tab"><div class="card"><h2>Calendario Serie A</h2><p class="muted">Partite, casa/trasferta, data e orario italiano della giornata selezionata.</p><div id="fqCalendarList"></div></div></section>');
    nav.querySelector('[data-tab="fqcalendar"]').onclick=function(){document.querySelectorAll('nav button').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));this.classList.add('active');document.querySelector('#fqcalendar').classList.add('active');fqRenderCalendar()};
  }
  const oldCard=window.card;
  window.card=function(p){return `<div class="player"><b>${p.name}</b><small>${p.club} · ${p.role}</small>${fqMatchHTML(p)}<div class="pv">${(prob(p)*100).toFixed(0)}% voto · ${value(p).toFixed(2)}</div></div>`};
  const oldProfile=window.profile;
  window.profile=function(p,w){const f=fqFixture(p);const match=f?`<p><b class="role">${f.label}</b><br><small>${f.isHome?'Casa':'Trasferta'} · ${f.date} · ${f.time}</small></p>`:'<p class="muted">Calendario non disponibile</p>';return `<div class="profile ${w?'winner':''}"><h3>${p.name}</h3><p class="muted">${p.role} · ${p.club}</p>${match}${pdata(p).map(x=>`<label>${x[0]}: ${x[1].toFixed(x[0].includes('/90')?3:x[0]==='Indice'?2:0)}</label><div class="meter"><i style="width:${Math.min(100,x[1]/x[2]*100)}%"></i></div>`).join('')}</div>`};
  const oldRender=window.render;
  window.render=function(){oldRender();fqRenderCalendar()};
})();
