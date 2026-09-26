const S = {
  me: null,
  status: null,
  accounts: [],
  id: null,
  d: null,
  tab: 'overview',
  plannerStrategy: 'balanced',
  assets: {},
  assetsLoaded: false,
};

const A = '/static/assets/coc/';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
})[char]);
const cookie = name => document.cookie.split('; ').find(x => x.startsWith(name + '='))?.split('=').slice(1).join('=') || '';

async function api(url, opt = {}) {
  const options = {...opt, headers: {...(opt.headers || {})}};
  if ('json' in opt) {
    options.body = JSON.stringify(opt.json);
    options.headers['Content-Type'] = 'application/json';
  }
  if (options.method && options.method !== 'GET') options.headers['X-CSRF'] = cookie('csrf');
  const response = await fetch(url, options);
  let data = {};
  try { data = await response.json(); } catch {}
  if (response.status === 401) {
    location = '/login';
    throw Error('não autenticado');
  }
  if (response.status === 402) {
    renderLapsed(data);
    throw Error('passe inativo');
  }
  if (!response.ok) throw Error(data.error || `Erro ${response.status}`);
  return data;
}

const slug = value => String(value || '')
  .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
  .toLowerCase().replace(/&/g, 'and').replace(/['’]/g, '')
  .replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
const assetKey = value => slug(value).replace(/-/g, '');

const KIND_DIR = {
  hero: 'heroes', heroes: 'heroes',
  troop: 'troops', troops: 'troops', siege: 'troops',
  spell: 'spells', spells: 'spells',
  pet: 'pets', pets: 'pets',
  equipment: 'equipment',
  townhall: 'townhall',
  resources: 'resources',
  icons: 'icons',
  leagues: 'leagues',
};

async function loadAssetManifest() {
  if (S.assetsLoaded) return;
  S.assetsLoaded = true;
  try {
    const response = await fetch(`${A}assets-manifest.json`, {cache: 'no-store'});
    if (!response.ok) return;
    const manifest = await response.json();
    for (const entry of manifest.assets || []) {
      if (!entry?.path) continue;
      const category = String(entry.category || '').toLowerCase();
      const name = entry.name || entry.path.split('/').pop().replace(/\.[^.]+$/, '');
      S.assets[`${category}:${assetKey(name)}`] = A + String(entry.path).replace(/^\/+/, '');
    }
  } catch (error) {
    console.warn('Manifest de assets indisponível:', error);
  }
}

function asset(kind, name) {
  if (!name) return null;
  const dir = KIND_DIR[String(kind || '').toLowerCase()] || String(kind || '').toLowerCase();
  return S.assets[`${dir}:${assetKey(name)}`] || null;
}

function th(level) {
  return asset('townhall', `th${level || 1}`);
}

function resource(name) {
  if (!name) return null;
  const raw = String(name);
  const normalized = assetKey(raw);
  const aliases = {
    gold: 'gold',
    elixir: 'elixir',
    darkelixir: 'dark-elixir',
    dark_elixir: 'dark-elixir',
    shiny: 'shiny-ore',
    shinyore: 'shiny-ore',
    glowing: 'glowy-ore',
    glowingore: 'glowy-ore',
    glowy: 'glowy-ore',
    glowyore: 'glowy-ore',
    starry: 'starry-ore',
    starryore: 'starry-ore',
  };
  return asset('resources', aliases[normalized] || raw);
}

function gameAsset(category, name) {
  const kind = KIND_DIR[String(category || '').toLowerCase()];
  if (!kind || !['heroes', 'troops', 'spells', 'pets', 'equipment'].includes(kind)) return null;
  return asset(kind, name);
}

function image(src, cls = '', fallback = '◈') {
  if (!src) return `<span class="fallback ${cls}">${fallback}</span>`;
  return `<img class="${esc(cls)}" src="${esc(src)}" alt="" onerror="this.style.display='none';this.nextElementSibling.style.display='inline-grid'"><span class="fallback ${esc(cls)}" style="display:none">${fallback}</span>`;
}

const pct = value => Number.isFinite(+value) ? (+value).toFixed(1) + '%' : '—';
const num = value => new Intl.NumberFormat('pt-BR', {
  notation: +value >= 1e6 ? 'compact' : 'standard', maximumFractionDigits: 1
}).format(+value || 0);
const date = timestamp => timestamp ? new Date(timestamp * 1000).toLocaleString('pt-BR') : '—';

function dur(seconds) {
  let value = Math.max(0, +seconds || 0);
  const days = Math.floor(value / 86400);
  const hours = Math.floor(value % 86400 / 3600);
  const minutes = Math.floor(value % 3600 / 60);
  return [days && `${days}d`, hours && `${hours}h`, minutes && `${minutes}m`].filter(Boolean).join(' ') || '<1m';
}

function openM(id) { closeM(); $(id)?.classList.add('open'); }
function closeM() { document.querySelectorAll('.modal-bg').forEach(x => x.classList.remove('open')); }
function toast(message) { console.log(message); }
function displayName(account, player) { return player?.name || account?.name || account?.tag || 'Vila'; }

async function loadAll() {
  await loadAssetManifest();
  S.me = await api('/api/me');
  S.status = await api('/api/status');
  S.accounts = await api('/api/accounts');
  $('who').textContent = S.me.name || S.me.email || S.me.role;
  renderVillages();
  renderUtilities();
  if (!S.id && S.accounts.length) S.id = S.accounts[0].id;
  if (S.id) await selectVillage(S.id);
  else renderEmpty();
}

function renderVillages() {
  $('villages').innerHTML = S.accounts.map(account => {
    const player = account.player || {};
    return `<button class="village ${account.id === S.id ? 'active' : ''}" onclick="selectVillage(${account.id})">
      ${image(th(account.latest?.th_level || player.townHallLevel), '', 'CV')}
      <div>
        <b>${esc(displayName(account, player))}</b>
        <div class="small">${esc(account.tag || 'sem tag')} · ${account.latest ? pct(account.latest.progress_total) : 'sem export'}</div>
      </div>
    </button>`;
  }).join('') || '<div class="small">Nenhuma vila</div>';
}

async function selectVillage(id) {
  S.id = id;
  renderVillages();
  $('app').innerHTML = '<div class="empty">Carregando vila…</div>';
  S.d = await api(`/api/accounts/${id}/detail`);
  renderDetail();
}

function renderEmpty() {
  $('app').innerHTML = '<div class="section empty"><h2>Nenhuma vila cadastrada</h2><p>Cadastre a tag e importe o JSON oficial para iniciar o acompanhamento.</p></div><div class="footer">Conteúdo de fã. COC Control não é afiliado à Supercell.</div>';
}

function renderLapsed(data) {
  $('app').innerHTML = `<div class="section"><div class="notice error"><b>Passe inativo.</b> Seus dados continuam guardados.</div><p>${esc(data.error || 'Renove o passe na Clash Labs.')}</p>${data.store ? `<a class="btn primary" href="${esc(data.store)}">Renovar</a>` : ''}</div>`;
}

function renderDetail() {
  const d = S.d;
  const account = d.account;
  const summary = d.summary || {};
  const player = d.player || {};
  const level = summary.th_level || player.townHallLevel || 1;
  const clan = player.clan || {};
  const official = player.name || '';
  const alias = account.name || '';
  $('app').innerHTML = `<div class="hero">
    ${image(th(level), '', `CV${level}`)}
    <div>
      <h1>${esc(official || alias)}</h1>
      <div class="muted">${esc(account.tag || player.tag || 'sem tag')} · CV ${level}${account.verified ? ' · conta verificada' : ''}</div>
      ${official && alias && official !== alias ? `<div class="small">Alias local: ${esc(alias)}</div>` : ''}
      <div class="badges">
        <span class="pill">${esc(player.league || 'Liga não sincronizada')}</span>
        ${player.trophies != null ? `<span class="pill">🏆 ${num(player.trophies)}</span>` : ''}
        ${clan.name ? `<span class="pill">Clã: ${esc(clan.name)}</span>` : ''}
        ${player.fetched_at ? `<span class="pill">Supercell: ${esc(date(player.fetched_at))}</span>` : ''}
      </div>
    </div>
  </div>
  <div class="tabs">
    ${['overview', 'arsenal', 'upgrades', 'planner', 'history'].map(key => `<button class="tab ${S.tab === key ? 'active' : ''}" onclick="tab('${key}')">${({overview:'Visão geral',arsenal:'Arsenal',upgrades:'Upgrades',planner:'Planejador',history:'Histórico'})[key]}</button>`).join('')}
    <button class="tab" onclick="openM('import')">Importar JSON</button>
    <button class="tab" onclick="syncSC()">Sync Supercell</button>
    <button class="tab" onclick="openEdit()">Editar vila</button>
  </div>
  <div id="view"></div>
  <div class="footer">Dados combinados do export oficial e da API oficial do Clash of Clans. Conteúdo de fã; não afiliado à Supercell.</div>`;
  tab(S.tab);
}

function tab(key) {
  S.tab = key;
  const label = ({overview:'Visão geral',arsenal:'Arsenal',upgrades:'Upgrades',planner:'Planejador',history:'Histórico'})[key];
  document.querySelectorAll('.tab').forEach(button => button.classList.toggle('active', button.textContent.trim() === label));
  const view = $('view');
  if (key === 'overview') view.innerHTML = overview();
  if (key === 'arsenal') view.innerHTML = arsenal();
  if (key === 'upgrades') view.innerHTML = upgrades();
  if (key === 'planner') planner();
  if (key === 'history') view.innerHTML = history();
}

function resources(values, label = 'restante') {
  const rows = Object.entries(values || {}).filter(([key, value]) => key && +value > 0);
  if (!rows.length) return '<span class="small">Sem custo conhecido</span>';
  return rows.map(([key, value]) => `<div class="resource">
    ${image(resource(key), 'resource-icon', '◆')}
    <div><b>${num(value)}</b><div class="small">${esc(key)} · ${label}</div></div>
  </div>`).join('');
}

function supercellOverview(player) {
  if (!player || !player.tag) {
    return '<div class="notice">Nenhum dado da API oficial carregado. Configure o token da Supercell e use <b>Sync Supercell</b>.</div>';
  }
  const fields = [
    ['Nome oficial', player.name],
    ['Nível de XP', player.expLevel],
    ['Liga', player.league],
    ['Troféus', player.trophies],
    ['Melhor troféu', player.bestTrophies],
    ['Troféus Base do Construtor', player.builderBaseTrophies],
    ['Estrelas de guerra', player.warStars],
    ['Vitórias de ataque', player.attackWins],
    ['Vitórias de defesa', player.defenseWins],
    ['Doações', player.donations],
    ['Recebidas', player.donationsReceived],
    ['Contribuição Capital', player.clanCapitalContributions],
  ].filter(([, value]) => value !== null && value !== undefined && value !== '');
  return `<div class="grid categories">${fields.map(([label, value]) => `<div class="card"><span class="small">${esc(label)}</span><b class="big compact">${esc(value)}</b></div>`).join('')}</div>`;
}

function overview() {
  const summary = S.d.summary || {};
  const player = S.d.player || {};
  const builders = summary.builders || {};
  const categories = summary.categories || {};
  return `<div class="grid stats">
    <div class="card"><span class="small">Progresso</span><b class="big">${pct(summary.progress_total)}</b><div class="progress"><i style="width:${+summary.progress_total || 0}%"></i></div></div>
    <div class="card"><span class="small">Construtores</span><b class="big">${builders.available ?? '—'} livres</b><span class="small">${builders.busy ?? 0}/${builders.total ?? 0} ocupados</span></div>
    <div class="card"><span class="small">Caminho crítico</span><b class="big">${dur(summary.eta?.critical_secs)}</b></div>
    <div class="card"><span class="small">Troféus</span><b class="big">${player.trophies == null ? '—' : num(player.trophies)}</b><span class="small">melhor ${player.bestTrophies == null ? '—' : num(player.bestTrophies)}</span></div>
  </div>
  <div class="section"><h2>Dados oficiais da Supercell</h2>${supercellOverview(player)}</div>
  <div class="section"><h2>Progresso por categoria</h2><div class="grid categories">${Object.entries(categories).map(([key, category]) => `<div class="card"><div class="row"><b>${esc(category.label || key)}</b><div class="spacer"></div><b>${pct(category.progress)}</b></div><div class="progress"><i style="width:${+category.progress || 0}%"></i></div><div class="small">${category.pending_levels || 0} níveis pendentes</div></div>`).join('')}</div></div>
  <div class="section"><h2>Recursos necessários</h2><div class="resources">${resources(summary.cost_left)}</div></div>
  <div class="section"><h2>Minérios necessários</h2><div class="resources">${resources(summary.ores_needed)}</div></div>`;
}

const PETS = new Set([
  'L.A.S.S.I', 'Electro Owl', 'Mighty Yak', 'Unicorn', 'Frosty', 'Diggy',
  'Poison Lizard', 'Phoenix', 'Spirit Fox', 'Angry Jelly', 'Sneezy', 'Greedy Raven'
]);
const SIEGE = new Set(['Wall Wrecker','Battle Blimp','Stone Slammer','Siege Barracks','Log Launcher','Flame Flinger','Battle Drill']);

function arsenalSets() {
  const raw = S.d.player?._raw || {};
  const troops = raw.troops || [];
  return {
    heroes: raw.heroes || [],
    equipment: raw.heroEquipment || raw.equipment || [],
    troops: troops.filter(x => !PETS.has(x.name) && !SIEGE.has(x.name) && !String(x.name).toLowerCase().includes('siege')),
    spells: raw.spells || [],
    pets: troops.filter(x => PETS.has(x.name)),
    siege: troops.filter(x => SIEGE.has(x.name) || String(x.name).toLowerCase().includes('siege')),
  };
}

function arsenal() {
  const sets = arsenalSets();
  const labels = {heroes:'Heróis',equipment:'Equipamentos',troops:'Tropas',spells:'Feitiços',siege:'Cerco',pets:'Pets'};
  const kind = {heroes:'heroes',equipment:'equipment',troops:'troops',spells:'spells',siege:'troops',pets:'pets'};
  return `<div class="section"><h2>Arsenal</h2>${Object.keys(labels).map(key => `<h3>${labels[key]} <span class="small">(${sets[key].length})</span></h3><div class="grid arsenal">${sets[key].map(item => `<div class="card unit ${item.maxLevel && item.level >= item.maxLevel ? 'max' : ''}">${image(asset(kind[key], item.name), '', '◈')}<div class="lvl">${item.level ?? '—'}${item.maxLevel ? ' / ' + item.maxLevel : ''}</div><b>${esc(item.name)}</b></div>`).join('') || '<span class="small">Sem dados</span>'}</div>`).join('')}</div>`;
}

function upgrades() {
  const summary = S.d.summary || {};
  const active = summary.active_upgrades || [];
  const pending = summary.top_pending || [];
  return `<div class="section"><h2>Em andamento</h2><div class="list">${active.map(item => `<div class="item">${image(gameAsset(item.category, item.name), '', '◈')}<div><b>${esc(item.name)}</b><div class="small">nível ${item.from_lvl} → ${item.to_lvl} · ${esc(item.queue)}</div></div><div class="right"><b>${dur(item.secs_left)}</b><div class="small">${date(item.finish_ts)}</div></div></div>`).join('') || '<div class="small">Nenhum upgrade ativo no último export.</div>'}</div></div>
  <div class="section"><h2>Principais pendências</h2><div class="list">${pending.slice(0, 80).map(item => `<div class="item">${image(gameAsset(item.category, item.name), '', '◈')}<div><b>${esc(item.name)}</b><div class="small">${esc(item.breakdown || '')} · ${esc(item.category)}</div></div><div class="right"><b>${dur(item.secs)}</b></div></div>`).join('')}</div></div>`;
}

function planCost(item) {
  if (!(+item.cost > 0)) return '';
  return `<div class="small">${num(item.cost)} ${esc(item.res || '')}</div>`;
}

function planItem(item, queueLabel) {
  const when = item.start ? (item.start <= Math.floor(Date.now() / 1000) + 60 ? 'agora' : date(item.start)) : '—';
  const worker = queueLabel === 'Construtor' ? `Construtor ${item.worker}` : queueLabel;
  return `<div class="item">
    ${image(gameAsset(item.category, item.name), '', '↗')}
    <div><b>${esc(item.name || 'Upgrade')}</b><div class="small">${esc(worker)} · → nível ${item.to_lvl ?? '—'} · inicia ${esc(when)}</div>${planCost(item)}</div>
    <div class="right"><b>${dur(item.secs)}</b><div class="small">termina ${date(item.end)}</div></div>
  </div>`;
}

function scheduleSection(title, payload, queueLabel, limit = 30) {
  const schedule = payload?.schedule || [];
  return `<div class="section"><div class="row"><h2>${esc(title)}</h2><div class="spacer"></div><span class="small">${schedule.length} planejados${payload?.not_scheduled ? ` · ${payload.not_scheduled} fora do limite` : ''}</span></div><div class="list">${schedule.slice(0, limit).map(item => planItem(item, queueLabel)).join('') || '<div class="small">Nenhum upgrade pendente nessa fila.</div>'}</div>${payload?.done_at ? `<div class="small plan-done">Fim projetado da fila: ${date(payload.done_at)}</div>` : ''}</div>`;
}

async function planner() {
  const view = $('view');
  view.innerHTML = `<div class="section"><div class="row"><h2 style="margin:0">Planejador de upgrades</h2><div class="spacer"></div><select id="planStrategy" onchange="S.plannerStrategy=this.value;planner()"><option value="balanced">Balanceado</option><option value="defense">Defesa primeiro</option><option value="farm">Farm primeiro</option><option value="fast">Mais rápidos primeiro</option><option value="cheap">Mais baratos primeiro</option></select></div><div class="empty">Calculando…</div></div>`;
  $('planStrategy').value = S.plannerStrategy;
  try {
    const plan = await api(`/api/accounts/${S.id}/plan?strategy=${encodeURIComponent(S.plannerStrategy)}`);
    const strategyName = plan.strategies?.[plan.strategy] || plan.strategy;
    const suggestions = plan.suggestions || [];
    view.innerHTML = `<div class="section">
      <div class="row"><div><h2 style="margin:0">Planejador de upgrades</h2><div class="small">Estratégia atual: ${esc(strategyName)}</div></div><div class="spacer"></div><select id="planStrategy" onchange="S.plannerStrategy=this.value;planner()"><option value="balanced">Balanceado</option><option value="defense">Defesa primeiro</option><option value="farm">Farm primeiro</option><option value="fast">Mais rápidos primeiro</option><option value="cheap">Mais baratos primeiro</option></select></div>
      <div class="planner-help"><b>Como usar:</b> importe um JSON recente, escolha uma estratégia e use a lista de sugestões como próxima ordem de upgrades. O sistema simula quando cada construtor, laboratório e Casa dos Pets ficará livre. Ele não executa upgrades no jogo.</div>
      <div class="grid stats plan-stats">
        <div class="card"><span class="small">Conclusão projetada</span><b class="big compact">${date(plan.projected_all_done)}</b></div>
        <div class="card"><span class="small">Fila construtores</span><b class="big">${plan.builders?.schedule?.length || 0}</b></div>
        <div class="card"><span class="small">Fila laboratório</span><b class="big">${plan.lab?.schedule?.length || 0}</b></div>
        <div class="card"><span class="small">Fila pets</span><b class="big">${plan.pets?.schedule?.length || 0}</b></div>
      </div>
      <div class="small planner-note">${esc(plan.note || '')}</div>
    </div>
    <div class="section"><h2>Próximos upgrades sugeridos</h2><div class="list">${suggestions.map(item => planItem(item, 'Construtor')).join('') || '<div class="small">Nenhuma sugestão disponível.</div>'}</div></div>
    ${scheduleSection('Cronograma dos construtores', plan.builders, 'Construtor')}
    ${scheduleSection('Cronograma do laboratório', plan.lab, 'Laboratório')}
    ${scheduleSection('Cronograma da Casa dos Pets', plan.pets, 'Casa dos Pets')}`;
    $('planStrategy').value = S.plannerStrategy;
  } catch (error) {
    view.innerHTML = `<div class="notice error">${esc(error.message)}</div>`;
  }
}

function history() {
  const d = S.d;
  return `<div class="section"><h2>Histórico de snapshots</h2><div class="list">${(d.history || []).map(item => `<div class="item"><span class="fallback">◷</span><div><b>CV ${item.th_level || '—'}</b><div class="small">Snapshot #${item.id}</div></div><div class="right">${date(item.taken_at)}</div></div>`).join('') || '<div class="small">Sem histórico.</div>'}</div></div>`;
}

async function createVillage() {
  try {
    await api('/api/accounts', {method:'POST', json:{name:$('newName').value, tag:$('newTag').value}});
    closeM(); S.id = null; await loadAll();
  } catch (error) { alert(error.message); }
}

async function importJson() {
  try {
    const text = $('jsonText').value;
    await api(`/api/import?account_id=${S.id}`, {method:'POST', json:{json:JSON.parse(text)}});
    closeM();
    await selectVillage(S.id);
  } catch (error) { alert(error.message); }
}

async function syncSC() {
  try {
    const result = await api(`/api/accounts/${S.id}/sync-supercell`, {method:'POST'});
    await selectVillage(S.id);
    alert(`Sincronizado com a Supercell${result.name ? `: ${result.name}` : ''}`);
  } catch (error) { alert(error.message); }
}

async function openSettings() {
  const settings = await api('/api/settings');
  $('settingsBody').innerHTML = `<h3>Alertas</h3>
    <div class="field"><label><input type="checkbox" id="notify" ${settings.notify_enabled ? 'checked' : ''}> Alertas ativos</label></div>
    ${S.me.role === 'owner' ? `<div class="field"><label><input type="checkbox" id="toast" ${settings.toast_enabled ? 'checked' : ''}> Toast do Windows</label></div>` : ''}
    <div class="field"><label>Antecedência (min)</label><input id="lead" type="number" min="0" max="1440" value="${settings.lead_minutes ?? 30}"></div>
    <div class="field"><label>Resumo diário</label><input id="digest" value="${esc(settings.digest_time || '')}" placeholder="08:00"></div>
    <div class="field"><label>Telegram token</label><input id="telegramToken" value="${esc(settings.telegram_token || '')}" autocomplete="off"></div>
    <div class="field"><label>Telegram chat ID</label><input id="telegramChat" value="${esc(settings.telegram_chat_id || '')}"></div>
    <div class="field"><label>Discord webhook</label><input id="discordWebhook" value="${esc(settings.discord_webhook || '')}"></div>
    <h3>WhatsApp / Evolution API</h3>
    <div class="field"><label>URL</label><input id="evolutionUrl" value="${esc(settings.evolution_url || '')}"></div>
    <div class="field"><label>API key</label><input id="evolutionKey" value="${esc(settings.evolution_apikey || '')}" autocomplete="off"></div>
    <div class="field"><label>Instância</label><input id="evolutionInstance" value="${esc(settings.evolution_instance || 'principal')}"></div>
    <div class="field"><label>Número/JID</label><input id="evolutionNumber" value="${esc(settings.evolution_number || '')}"></div>
    <h3>Supercell</h3>
    <div class="field"><label><input type="checkbox" id="scAutosync" ${settings.supercell_autosync ? 'checked' : ''}> Sincronizar API no import</label></div>
    ${S.me.role === 'owner' ? `<div class="field"><label>Token de desenvolvedor Supercell</label><input id="supercellToken" value="${esc(settings.supercell_token || '')}" autocomplete="off"></div>` : `<div class="small">Token do servidor: ${settings.supercell_configured ? 'configurado' : 'não configurado'}</div>`}
    <div class="row"><button class="btn primary" onclick="saveSettings()">Salvar</button><button class="btn" onclick="testNotification()">Testar alerta</button></div>
    <hr style="border-color:var(--line)"><h3>API e dados</h3>
    <div class="small">API key atual: ${S.me.api_key_hint ? '••••' + esc(S.me.api_key_hint) : 'não gerada'}</div>
    <div class="row"><button class="btn" onclick="newApiKey()">Gerar nova API key</button><button class="btn" onclick="exportData()">Exportar meus dados</button>${S.me.role === 'subscriber' ? '<button class="btn danger" onclick="deleteData()">Excluir conta e dados</button>' : ''}${S.me.role === 'owner' ? '<button class="btn" onclick="loadSubscribers()">Assinantes</button>' : ''}</div><div id="apiKeyOnce"></div><div id="subs"></div>`;
  openM('settings');
}

async function saveSettings() {
  try {
    const body = {
      notify_enabled: $('notify').checked,
      lead_minutes: +$('lead').value,
      digest_time: $('digest').value,
      telegram_token: $('telegramToken').value,
      telegram_chat_id: $('telegramChat').value,
      discord_webhook: $('discordWebhook').value,
      evolution_url: $('evolutionUrl').value,
      evolution_apikey: $('evolutionKey').value,
      evolution_instance: $('evolutionInstance').value,
      evolution_number: $('evolutionNumber').value,
      supercell_autosync: $('scAutosync').checked,
    };
    if (S.me.role === 'owner') {
      body.toast_enabled = $('toast').checked;
      body.supercell_token = $('supercellToken').value;
    }
    await api('/api/settings', {method:'PUT', json:body});
    alert('Configurações salvas');
  } catch (error) { alert(error.message); }
}

function exportData() { location = '/api/me/export'; }
async function deleteData() {
  if (!confirm('Excluir permanentemente suas vilas, snapshots e configurações?')) return;
  await api('/api/me/data', {method:'DELETE'});
  location = '/login';
}

async function loadSubscribers() {
  const subscribers = await api('/api/admin/subscribers');
  $('subs').innerHTML = '<h3>Assinantes</h3>' + subscribers.map(item => `<div class="resource"><div><b>${esc(item.name || item.email || item.labs_user_id)}</b><div class="small">${item.villages} vilas · ${item.suspended_at ? 'suspenso' : 'ativo'}</div></div><div class="spacer"></div><button class="btn" onclick="suspend(${item.id},${item.suspended_at ? 'false' : 'true'})">${item.suspended_at ? 'Reativar' : 'Suspender'}</button></div>`).join('');
}

async function suspend(id, on) {
  let reason = '';
  if (on) reason = prompt('Motivo da suspensão:') || '';
  await api(`/api/admin/subscribers/${id}/suspension`, {method:'POST', json:{suspended:on, reason}});
  loadSubscribers();
}

function renderUtilities() {
  const button = $('watcherBtn');
  if (S.me?.role === 'owner' && S.status?.watcher?.available) {
    button.style.display = 'block';
    button.textContent = `Watcher: ${S.status.watcher.enabled ? 'ligado' : 'desligado'}`;
  } else button.style.display = 'none';
}

async function toggleWatcher() {
  try {
    const result = await api('/api/watcher', {method:'POST', json:{enabled:!S.status?.watcher?.enabled}});
    S.status.watcher.enabled = result.enabled;
    renderUtilities();
  } catch (error) { alert(error.message); }
}

async function importClipboard() {
  try {
    const text = await navigator.clipboard.readText();
    await api(`/api/import${S.id ? '?account_id=' + S.id : ''}`, {method:'POST', json:{json:JSON.parse(text)}});
    await loadAll();
  } catch (error) { alert('Não foi possível importar do clipboard: ' + error.message); }
}

async function syncAll() {
  try {
    const result = await api('/api/sync-all', {method:'POST'});
    alert(`${result.synced}/${result.total} vilas sincronizadas`);
    await loadAll();
  } catch (error) { alert(error.message); }
}

function openEdit() {
  const account = S.d.account;
  $('editName').value = account.name || '';
  $('editTag').value = account.tag || '';
  $('editNotes').value = account.notes || '';
  $('verifyToken').value = '';
  openM('edit');
}

async function saveVillage() {
  try {
    await api(`/api/accounts/${S.id}`, {method:'PATCH', json:{name:$('editName').value, tag:$('editTag').value, notes:$('editNotes').value}});
    closeM();
    await loadAll();
  } catch (error) { alert(error.message); }
}

async function deleteVillage() {
  if (!confirm('Excluir esta vila e todo o histórico?')) return;
  try {
    await api(`/api/accounts/${S.id}`, {method:'DELETE'});
    closeM(); S.id = null; await loadAll();
  } catch (error) { alert(error.message); }
}

async function verifyVillage() {
  try {
    const result = await api(`/api/accounts/${S.id}/verify`, {method:'POST', json:{token:$('verifyToken').value}});
    alert(result.verified ? 'Posse verificada' : 'Token não validado');
    await selectVillage(S.id);
  } catch (error) { alert(error.message); }
}

async function newApiKey() {
  try {
    const result = await api('/api/apikey', {method:'POST'});
    $('apiKeyOnce').innerHTML = `<div class="notice"><b>Copie agora. Ela não será mostrada novamente.</b><br><code>${esc(result.api_key)}</code></div>`;
    S.me.api_key_hint = result.hint;
  } catch (error) { alert(error.message); }
}

async function testNotification() {
  try {
    const result = await api('/api/notify/test', {method:'POST'});
    alert(result.sent?.length ? `Enviado: ${result.sent.join(', ')}` : 'Nenhum canal enviou o teste');
  } catch (error) { alert(error.message); }
}

async function logout() {
  await api('/api/logout', {method:'POST'});
  location = '/login';
}

loadAll().catch(error => $('app').innerHTML = `<div class="notice error">${esc(error.message)}</div>`);
