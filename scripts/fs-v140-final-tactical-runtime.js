(()=>{'use strict';
const DATA=window.FS_TACTICAL_DATA_V140;
const roleMap={P:'PORTIERE',D:'TERZINO_PURO',C:'MEZZALA',A:'ALA'};
function profile(p){return DATA.teams?.[p?.club]||null}
function roleImpact(p){const t=profile(p);if(!t)return 0;const r=roleMap[p.role]||'';let z=0;for(const x of t.valuedRoles||[])if(x.role===r||x.role==='TREQ'&&p.role==='C'||x.role==='ESTERNO_TUTTA_FASCIA'&&p.role==='D')z=Math.max(z,x.score);for(const x of t.penalizedRoles||[])if(x.role===r||x.role==='TREQ_PURO'&&p.role==='C'||x.role==='ALA_PURA'&&p.role==='A'||x.role==='TERZINO_PURO'&&p.role==='D')z=Math.min(z,x.score);return z}
function applyProfiles(){if(!window.TACT?.teams)return;for(const [c,t] of Object.entries(DATA.teams)){TACT.teams[c]={...(TACT.teams[c]||{}),coach:t.coach,module:t.module,confidence:t.confidence,valuedRoles:t.valuedRoles,penalizedRoles:t.penalizedRoles,validFrom:t.validFrom}}TACT.updated=DATA.generatedAt;TACT.sources={...(TACT.sources||{}),T140:'FantaSuite Tactical Integration v14.0 · 20/10/2026'}}
applyProfiles();
const previous=window.matchProjection;
if(typeof previous==='function')window.matchProjection=function(p){const z=previous(p),t=profile(p);if(!t||z?.label==='Indisponibile')return z;const impact=roleImpact(p),weighted=impact*t.confidence,mult=Math.max(.92,Math.min(1.08,1+weighted/250)),efm=Math.max(0,Number(z.efm||0)*mult),score=Number(z.ap??1)*efm-Number(z.uncertainty||0)*.22;return{...z,efm:+efm.toFixed(2),score:+score.toFixed(3),tacticalRoleImpact:impact,tacticalMultiplier:+mult.toFixed(3),tacticalProfile:t}};
window.FS_TACTICAL_V140={data:DATA,profile,roleImpact,version:DATA.version};
try{if(typeof invalidatePrecision118==='function')invalidatePrecision118();if(typeof render==='function')render();const s=document.getElementById('state');if(s)s.textContent=(window.DB?.players?.length||0)+' giocatori · FantaSuite v14.0 · tattica integrata · offline'}catch(e){console.error('FS v14 tactical refresh',e)}
})();
