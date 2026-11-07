const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const fmt = (value, digits=2) => Number(value).toLocaleString('en-US',{maximumFractionDigits:digits,minimumFractionDigits:digits});
const labels = {skilled_proxy:'Stronger proxy',unskilled_proxy:'Other proxy',unknown:'Unknown history'};
const colors = {skilled_proxy:'#b9eab2',unskilled_proxy:'#edab87',unknown:'#96a7a5'};
const category = value => ({equities_and_corporate:'Equities & companies',rates_and_macro:'Rates & macro',ipos_and_deals:'IPOs & deals',commodities:'Commodities',etfs_and_digital_finance:'ETFs & digital finance'}[value] || value);
const utc = value => new Date(Number(value)*1000).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'});
const state = {data:null,config:null,live:false,selected:null,showUnknown:false,page:0,tradePage:0,tradeMarket:null,tradeRequest:0};

async function getJSON(url,options={}) {
  const response = await fetch(url,{...options,signal:AbortSignal.timeout(12000)});
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json();
}
async function query(table,params) {
  return getJSON(`${state.config.supabaseUrl}/rest/v1/${table}?${new URLSearchParams(params)}`,{headers:{apikey:state.config.publishableKey}});
}
function notice(message) {
  $('notice').textContent=message; $('notice').hidden=false;
}

async function start() {
  try {
    const [snapshot,config]=await Promise.all([getJSON('/data/snapshot.json'),getJSON('/config.json')]);
    state.data=snapshot;state.config=config;
    if(config.supabaseUrl && config.publishableKey) {
      try {
        const [datasets,markets,experiments,predictions,candidates]=await Promise.all([
          query('research_datasets',{select:'*',dataset_key:'in.(finance-2025-v1,finance-2026-01-v1)',status:'eq.ready',order:'dataset_key',limit:1000}),
          query('research_markets',{select:'dataset_key,market_id,question,category,source_url,label_available_at,yes_outcome,trading_start,scheduled_end',dataset_key:'in.(finance-2025-v1,finance-2026-01-v1)',order:'dataset_key,market_id',limit:1000}),
          query('research_experiments',{select:'*',experiment_key:'eq.participation-2026-01-v1',status:'eq.ready',limit:1}),
          query('research_predictions',{select:'*',experiment_key:'eq.participation-2026-01-v1',order:'market_id,forecast_at,group_name,side',limit:1000}),
          query('research_candidates',{select:'*',experiment_key:'eq.participation-2026-01-v1',order:'activity_rank',limit:1000})
        ]);
        if(!experiments.length || markets.length!==120 || predictions.length!==120 || candidates.length!==100) throw new Error('Cloud import is not complete');
        state.data={datasets,markets,predictions,candidates,experiment:experiments[0]};state.live=true;
      } catch {
        notice('Cloud reads are unavailable or incomplete. Showing the labeled published snapshot; trade queries are disabled.');
      }
    }
    $('connection').classList.toggle('live',state.live);
    $('connection').innerHTML=`<i></i>${state.live?'Supabase · read only':'Published snapshot preview'}`;
    if(state.live) {
      $('data-description').innerHTML='Query the cloud, 50 trades at a time.<br>No full dataset download required.';
      $('pipeline-status').textContent='Connected to Supabase for read-only queries. Raw files stay in Storage; trade pages are fetched on demand.';
    }
    const summary=state.data.experiment.summary;
    const model=summary.four_requested_counts.model_predicted_wallets.mae_wallets;
    const baseline=summary.four_requested_counts.historical_rate_predicted_wallets.mae_wallets;
    $('headline-mae').textContent=fmt(model);$('model-mae').textContent=fmt(model);$('baseline-mae').textContent=fmt(baseline);
    $('result-improvement').textContent=fmt(100*(1-model/baseline),1)+'%';
    state.testMarkets=state.data.markets.filter(m=>state.data.predictions.some(p=>p.market_id===m.market_id));
    state.selected=state.testMarkets.find(m=>m.market_id==='1032307')?.market_id || state.testMarkets[0]?.market_id;
    $('market-picker').innerHTML=state.testMarkets.map(m=>`<option value="${esc(m.market_id)}">${esc(m.question)}</option>`).join('');
    $('category-filter').innerHTML+=[...new Set(state.data.markets.map(m=>m.category))].sort().map(c=>`<option value="${esc(c)}">${esc(category(c))}</option>`).join('');
    drawScatter();renderSelection();renderCohorts();renderMarkets();wire();
  } catch(error) {
    $('connection').textContent='Data unavailable';
    $('market-question').textContent='The published preview could not load.';
    notice('Reload the page, or open the GitHub report linked below. No results have been generated or substituted.');
  }
}

function drawScatter() {
  const rows=state.data.predictions.filter(r=>r.group_name!=='unknown');
  const max=Math.max(5,Math.ceil(Math.max(...rows.flatMap(r=>[r.predicted_wallets,r.actual_wallets]))/5)*5);
  const width=460,height=325,left=47,right=16,top=17,bottom=45;
  const x=n=>left+n/max*(width-left-right),y=n=>height-bottom-n/max*(height-top-bottom);
  let svg=`<svg viewBox="0 0 ${width} ${height}" role="group" aria-label="Predicted versus observed counts, ${rows.length} predictions">`;
  for(let i=0;i<=4;i++) {
    const value=max*i/4;
    svg+=`<path d="M${left} ${y(value)}H${width-right}M${x(value)} ${top}V${height-bottom}" stroke="#334044" stroke-width=".7"/><text x="${left-10}" y="${y(value)+3}" fill="#a8b3ad" font-size="9" text-anchor="end">${fmt(value,0)}</text><text x="${x(value)}" y="${height-bottom+17}" fill="#a8b3ad" font-size="9" text-anchor="middle">${fmt(value,0)}</text>`;
  }
  svg+=`<path d="M${x(0)} ${y(0)}L${x(max)} ${y(max)}" stroke="#8c9b94" stroke-dasharray="4 5"/><text x="${width/2}" y="${height-5}" fill="#a8b3ad" font-size="10" text-anchor="middle">Observed wallets →</text><text x="12" y="${height/2}" fill="#a8b3ad" font-size="10" text-anchor="middle" transform="rotate(-90 12 ${height/2})">Predicted wallets →</text>`;
  rows.forEach(r=>{
    const title=`Market ${r.market_id} · ${labels[r.group_name]} ${r.side}: predicted ${fmt(r.predicted_wallets)}, observed ${r.actual_wallets}`;
    svg+=`<circle cx="${x(r.actual_wallets)}" cy="${y(r.predicted_wallets)}" r="4" fill="${colors[r.group_name]}" fill-opacity=".75" data-market="${esc(r.market_id)}" tabindex="0" role="button" aria-label="${esc(title)}"><title>${esc(title)}</title></circle>`;
  });
  $('scatter').innerHTML=svg+'</svg>';
}

function selectMarket(id,scroll=false) {
  state.selected=id;renderSelection();
  if(scroll) $('explorer').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
}
function renderSelection() {
  const market=state.testMarkets.find(m=>m.market_id===state.selected);
  if(!market) return;
  $('market-picker').value=market.market_id;
  $('market-category').textContent=category(market.category).toUpperCase();
  $('market-question').textContent=market.question;
  $('market-link').href=market.source_url;
  const all=state.data.predictions.filter(p=>p.market_id===market.market_id);
  const relevant=all.filter(p=>p.group_name!=='unknown');
  $('window-caption').textContent=`${utc(all[0].forecast_at)} → ${utc(all[0].window_end)} · UTC · 100-candidate universe`;
  $('market-error').textContent=fmt(relevant.reduce((n,r)=>n+Math.abs(r.predicted_wallets-r.actual_wallets),0)/relevant.length);
  const shown=all.filter(r=>state.showUnknown || r.group_name!=='unknown');
  const max=Math.max(1,...shown.flatMap(r=>[r.actual_wallets,r.predicted_wallets]));
  let bars='';
  for(const group of ['skilled_proxy','unskilled_proxy',...(state.showUnknown?['unknown']:[])]) {
    const groupRows=shown.filter(r=>r.group_name===group).sort((a,b)=>a.side.localeCompare(b.side));
    bars+=`<div class="group-title"><span>${esc(labels[group].toUpperCase())}</span><span>${groupRows[0].group_size} CANDIDATE${groupRows[0].group_size===1?'':'S'}</span></div>`;
    for(const row of groupRows) {
      const predicted=row.predicted_wallets/max*300,actual=row.actual_wallets/max*300;
      bars+=`<div class="prediction-row"><span class="action-name">${row.side}</span><svg viewBox="0 0 302 35" preserveAspectRatio="none" role="img" aria-label="${esc(labels[group])} ${row.side}: predicted ${fmt(row.predicted_wallets)}, observed ${row.actual_wallets}"><rect x="0" y="2" width="300" height="10" fill="#273437"/><rect x="0" y="2" width="${predicted}" height="10" fill="${colors[group]}"/><rect x=".5" y="20" width="${Math.max(0,actual-.5)}" height="9" fill="none" stroke="#f0f2e9"/></svg><span class="prediction-numbers">${fmt(row.predicted_wallets)}<small>${row.actual_wallets} observed</small></span></div>`;
    }
  }
  $('prediction-bars').innerHTML=bars;
  $('prediction-table').innerHTML=shown.map(r=>`<tr><td>${esc(labels[r.group_name])}</td><td>${r.side}</td><td class="mono">${fmt(r.predicted_wallets)}</td><td class="mono">${r.actual_wallets}</td><td class="mono">${fmt(r.historical_rate_wallets)}</td><td class="mono">${r.group_size}</td></tr>`).join('');
}
function renderCohorts() {
  const groups=['skilled_proxy','unskilled_proxy','unknown'];
  const rows=[...state.data.candidates].sort((a,b)=>groups.indexOf(a.group_name)-groups.indexOf(b.group_name)||a.activity_rank-b.activity_rank);
  $('cohort-grid').innerHTML=rows.map(r=>`<div class="cohort-cell ${r.group_name}" title="${esc(r.wallet)} · ${esc(labels[r.group_name])} · ${r.earlier_comparable_markets} comparable earlier markets"></div>`).join('');
  $('cohort-legend').innerHTML=groups.map(g=>`<span><i class="dot ${g==='skilled_proxy'?'stronger':g==='unskilled_proxy'?'other':''}"></i><b>${rows.filter(r=>r.group_name===g).length}</b> ${esc(labels[g])}</span>`).join('');
}
function renderMarkets() {
  const search=$('market-search').value.trim().toLowerCase(),phase=$('dataset-filter').value,cat=$('category-filter').value;
  const datasetPhase=Object.fromEntries(state.data.datasets.map(d=>[d.dataset_key,d.phase]));
  const filtered=state.data.markets.filter(m=>(phase==='all'||datasetPhase[m.dataset_key]===phase)&&(cat==='all'||m.category===cat)&&(`${m.question} ${m.market_id}`.toLowerCase().includes(search)))
    .sort((a,b)=>b.label_available_at-a.label_available_at);
  const size=10,last=Math.max(0,Math.ceil(filtered.length/size)-1);state.page=Math.min(state.page,last);
  const visible=filtered.slice(state.page*size,state.page*size+size);
  $('market-table').innerHTML=visible.length?visible.map(m=>`<tr><td class="market-name">${esc(m.question)}<small>MARKET ${esc(m.market_id)}</small></td><td><span class="phase ${datasetPhase[m.dataset_key]}">${datasetPhase[m.dataset_key]==='later'?'2026 / TEST':'2025 / EARLIER'}</span></td><td>${esc(category(m.category))}</td><td class="mono">${utc(m.label_available_at)}</td><td>${datasetPhase[m.dataset_key]==='later'?`<button class="table-action" data-forecast="${esc(m.market_id)}">Forecast ↗</button> · `:''}<button class="table-action" data-records="${esc(m.market_id)}">Records →</button></td></tr>`).join(''):'<tr><td colspan="5">No markets match these filters.</td></tr>';
  $('market-count').textContent=filtered.length?`${state.page*size+1}–${Math.min((state.page+1)*size,filtered.length)} of ${filtered.length} markets`:'0 matching markets';
  $('previous-page').disabled=state.page===0;$('next-page').disabled=state.page===last;
}
async function renderTrades() {
  const market=state.data.markets.find(m=>m.market_id===state.tradeMarket);
  if(!market) return;
  const request=++state.tradeRequest;
  $('trade-panel').hidden=false;$('trade-title').textContent=market.question;
  $('trade-table').innerHTML='';$('trade-page-caption').textContent='';
  $('trades-prev').disabled=true;$('trades-next').disabled=true;
  if(!state.live) {
    $('trade-notice').textContent='Snapshot preview includes market metadata and experiment results. Full trade rows require the Supabase connection; no cloud connection is claimed here.';
    return;
  }
  $('trade-notice').textContent='Loading up to 50 source activity records…';
  try {
    const records=await query('research_trades',{select:'observed_at,wallet,side,outcome,size_shares,price,is_taker',dataset_key:`eq.${market.dataset_key}`,market_id:`eq.${market.market_id}`,order:'observed_at.desc,source_row.desc',limit:50,offset:state.tradePage*50});
    if(request!==state.tradeRequest) return;
    $('trade-notice').textContent='All-side records. Taker records are flags within this feed, not additional volume. Raw snapshots retain full transaction details.';
    $('trade-table').innerHTML=records.length?records.map(r=>`<tr><td class="mono">${new Date(r.observed_at*1000).toISOString().replace('T',' ').slice(0,19)}</td><td class="mono" title="${esc(r.wallet)}">${esc(r.wallet.slice(0,8)+'…'+r.wallet.slice(-6))}</td><td>${r.side}</td><td>${r.outcome}</td><td class="mono">${fmt(r.size_shares)}</td><td class="mono">${fmt(r.price,4)}</td><td>${r.is_taker?'Yes':'No'}</td></tr>`).join(''):'<tr><td colspan="7">No records on this page.</td></tr>';
    $('trade-page-caption').textContent=records.length?`Records ${state.tradePage*50+1}–${state.tradePage*50+records.length}`:'End of records';
    $('trades-prev').disabled=state.tradePage===0;$('trades-next').disabled=records.length<50;
  } catch {
    if(request===state.tradeRequest) $('trade-notice').textContent='The trade page could not be read. Check the connection or try another market; missing data is not zero activity.';
  }
}
function wire() {
  $('market-picker').addEventListener('change',e=>selectMarket(e.target.value));
  $('next-market').addEventListener('click',()=>selectMarket(state.testMarkets[(state.testMarkets.findIndex(m=>m.market_id===state.selected)+1)%state.testMarkets.length].market_id));
  $('toggle-unknown').addEventListener('click',()=>{state.showUnknown=!state.showUnknown;$('toggle-unknown').setAttribute('aria-pressed',String(state.showUnknown));$('toggle-unknown').textContent=state.showUnknown?'Hide unknown group −':'Show unknown group +';renderSelection();});
  for(const id of ['market-search','dataset-filter','category-filter']) $(id).addEventListener(id==='market-search'?'input':'change',()=>{state.page=0;renderMarkets();});
  $('previous-page').addEventListener('click',()=>{state.page--;renderMarkets();});$('next-page').addEventListener('click',()=>{state.page++;renderMarkets();});
  const pickPoint=e=>{const target=e.target.closest('[data-market]');if(target)selectMarket(target.dataset.market,true);};
  $('scatter').addEventListener('click',pickPoint);$('scatter').addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();pickPoint(e);}});
  $('market-table').addEventListener('click',e=>{
    const forecast=e.target.closest('[data-forecast]'),records=e.target.closest('[data-records]');
    if(forecast) selectMarket(forecast.dataset.forecast,true);
    if(records){state.tradeMarket=records.dataset.records;state.tradePage=0;renderTrades();}
  });
  $('close-trades').addEventListener('click',()=>{$('trade-panel').hidden=true;state.tradeRequest++;});
  $('trades-prev').addEventListener('click',()=>{state.tradePage--;renderTrades();});$('trades-next').addEventListener('click',()=>{state.tradePage++;renderTrades();});
}

start();
