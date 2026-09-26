/* Separação Vila Principal / Base do Construtor + catálogo rico de assets. */
S.arsenalBase = S.arsenalBase || 'home';
S.upgradeBase = S.upgradeBase || 'home';
S.plannerBase = S.plannerBase || 'home';
S.assetCatalog = S.assetCatalog || [];
S.richAssetsLoaded = false;

function normBase(value) {
  const v = String(value || '').toLowerCase().replace(/[^a-z]/g, '');
  return v === 'builderbase' || v === 'builder' ? 'builder' : 'home';
}
function manifestBase(base) { return base === 'builder' ? 'builder-base' : 'home-village'; }
function isBuilderApiItem(item) { return normBase(item?.village) === 'builder'; }
function richKey(value) { return assetKey(String(value || '').replace(/_/g, ' ')); }

async function loadRichAssetManifest() {
  if (S.richAssetsLoaded) return;
  S.richAssetsLoaded = true;
  try {
    const response = await fetch(`${A}assets-manifest.json`, {cache: 'no-store'});
    if (!response.ok) return;
    const manifest = await response.json();
    S.assetCatalog = (manifest.assets || []).filter(entry => entry?.path).map(entry => ({
      ...entry,
      category: String(entry.category || '').toLowerCase(),
      _name: richKey(entry.name),
      _entity: richKey(entry.entity),
      _base: String(entry.base || '').toLowerCase(),
      _url: A + String(entry.path).replace(/^\/+/, ''),
    }));
  } catch (error) {
    console.warn('Catálogo rico de assets indisponível:', error);
  }
}

function catalogAsset(category, name, {base = null, level = null} = {}) {
  const key = richKey(name);
  let candidates = (S.assetCatalog || []).filter(entry =>
    entry.category === String(category || '').toLowerCase() &&
    (entry._entity === key || entry._name === key)
  );
  if (base) {
    const b = String(base).toLowerCase();
    const scoped = candidates.filter(entry => entry._base === b);
    if (scoped.length) candidates = scoped;
  }
  if (!candidates.length) return null;
  if (level != null) {
    const exact = candidates.find(entry => Number(entry.level) === Number(level));
    if (exact) return exact._url;
    const leveled = candidates.filter(entry => Number.isFinite(Number(entry.level)))
      .sort((a, b) => Math.abs(Number(a.level) - Number(level)) - Math.abs(Number(b.level) - Number(level)));
    if (leveled.length) return leveled[0]._url;
  }
  const icon = candidates.find(entry => String(entry.name).toLowerCase() === 'icon');
  return (icon || candidates[0])._url;
}

const originalAsset = asset;
asset = function(kind, name) {
  const direct = originalAsset(kind, name);
  if (direct) return direct;
  const dir = KIND_DIR[String(kind || '').toLowerCase()] || String(kind || '').toLowerCase();
  return catalogAsset(dir, name);
};

gameAsset = function(category, name, level = 1, baseHint = null) {
  const cat = String(category || '').toLowerCase();
  const base = baseHint || (cat.startsWith('bb-') ? 'builder' : 'home');
  if (cat === 'trap' || cat === 'bb-trap') {
    return catalogAsset('traps', name, {base: manifestBase(base), level});
  }
  if (['defense','resource','army','townhall','wall','other','bb-defense','bb-resource','bb-army','bb-builder-hall','bb-wall','bb-other'].includes(cat)) {
    if (['builders-apprentice','lab-assistant','prospector','alchemist'].includes(slug(name))) {
      return catalogAsset('helpers', name, {level});
    }
    return catalogAsset('buildings', name, {base: manifestBase(base), level});
  }
  const dir = KIND_DIR[cat] || ({hero:'heroes',troop:'troops',spell:'spells',siege:'troops',pet:'pets',equipment:'equipment'})[cat];
  return dir ? asset(dir, name) : null;
};

function baseSwitch(current, handler) {
  return `<div class="tabs" style="margin:0 0 14px">
    <button class="tab ${current === 'home' ? 'active' : ''}" onclick="${handler}('home')">Vila Principal</button>
    <button class="tab ${current === 'builder' ? 'active' : ''}" onclick="${handler}('builder')">Base do Construtor</button>
  </div>`;
}
function setArsenalBase(base) { S.arsenalBase = base; $('view').innerHTML = arsenal(); }
function setUpgradeBase(base) { S.upgradeBase = base; $('view').innerHTML = upgrades(); }
function setPlannerBase(base) { S.plannerBase = base; planner(); }

function summaryFor(base) {
  const home = S.d?.summary || {};
  return base === 'builder' ? (home.builder_base || {}) : home;
}
function inventoryFor(base) {
  return (S.d?.summary?.inventory || []).filter(item => (item.base || 'home') === base);
}

function baseOverviewCard(base, summary) {
  const isBuilder = base === 'builder';
  const builders = summary.builders || {};
  const hall = isBuilder ? summary.builder_hall_level : summary.th_level;
  return `<div class="section">
    <div class="row"><div><h2 style="margin:0">${isBuilder ? 'Base do Construtor' : 'Vila Principal'}</h2><div class="small">${isBuilder ? 'Centro do Construtor' : 'Centro de Vila'} ${hall || '—'}</div></div></div>
    <div class="grid stats" style="margin-top:12px">
      <div class="card"><span class="small">Progresso</span><b class="big">${pct(summary.progress_total)}</b><div class="progress"><i style="width:${+summary.progress_total || 0}%"></i></div></div>
      <div class="card"><span class="small">Construtores</span><b class="big">${builders.available ?? '—'} livres</b><span class="small">${builders.busy ?? 0}/${builders.total ?? 0} ocupados${builders.estimated ? ' · estimado' : ''}</span></div>
      <div class="card"><span class="small">Caminho crítico</span><b class="big">${dur(summary.eta?.critical_secs)}</b></div>
      <div class="card"><span class="small">Pendências</span><b class="big">${num(summary.pending_total || 0)}</b><span class="small">níveis restantes</span></div>
    </div>
    <h3>Progresso por categoria</h3>
    <div class="grid categories">${Object.entries(summary.categories || {}).map(([key, category]) => `<div class="card"><div class="row"><b>${esc(category.label || key)}</b><div class="spacer"></div><b>${pct(category.progress)}</b></div><div class="progress"><i style="width:${+category.progress || 0}%"></i></div><div class="small">${category.pending_levels || 0} níveis pendentes</div></div>`).join('') || '<span class="small">Sem export dessa base.</span>'}</div>
    <h3>Recursos necessários</h3><div class="resources">${resources(summary.cost_left)}</div>
  </div>`;
}

overview = function() {
  const home = summaryFor('home');
  const builder = summaryFor('builder');
  const player = S.d.player || {};
  return `<div class="section"><h2>Dados oficiais da Supercell</h2>${supercellOverview(player)}</div>
    ${baseOverviewCard('home', home)}
    ${baseOverviewCard('builder', builder)}
    <div class="section"><h2>Minérios da Vila Principal</h2><div class="resources">${resources(home.ores_needed)}</div></div>`;
};

function apiBaseItems(list, base) {
  return (list || []).filter(item => base === 'builder' ? isBuilderApiItem(item) : !isBuilderApiItem(item));
}
function armySets(base) {
  const raw = S.d.player?._raw || {};
  const troops = apiBaseItems(raw.troops || [], base);
  if (base === 'builder') {
    return {heroes: apiBaseItems(raw.heroes || [], 'builder'), troops};
  }
  return {
    heroes: apiBaseItems(raw.heroes || [], 'home'),
    equipment: raw.heroEquipment || raw.equipment || [],
    pets: troops.filter(item => PETS.has(item.name)),
    troops: troops.filter(item => !PETS.has(item.name) && !SIEGE.has(item.name) && !String(item.name).toLowerCase().includes('siege')),
    spells: apiBaseItems(raw.spells || [], 'home'),
    siege: troops.filter(item => SIEGE.has(item.name) || String(item.name).toLowerCase().includes('siege')),
  };
}
function inventorySets(base) {
  const rows = inventoryFor(base);
  const categories = base === 'builder' ? {
    buildings: new Set(['bb-builder-hall','bb-army','bb-resource','bb-other']),
    defenses: new Set(['bb-defense']), traps: new Set(['bb-trap']), walls: new Set(['bb-wall']),
  } : {
    buildings: new Set(['townhall','army','resource','other']),
    defenses: new Set(['defense']), traps: new Set(['trap']), walls: new Set(['wall']),
  };
  const out = {};
  for (const [key, cats] of Object.entries(categories)) out[key] = rows.filter(item => cats.has(item.category) && !item.helper);
  if (base === 'home') out.helpers = rows.filter(item => item.helper);
  return out;
}
function apiCards(items, kind) {
  return (items || []).map(item => `<div class="card unit ${item.maxLevel && item.level >= item.maxLevel ? 'max' : ''}" style="display:flex;flex-direction:column;align-items:center;justify-content:flex-start;text-align:center;min-height:154px;overflow:hidden">
    ${image(asset(kind, item.name), '', '◈')}<div class="lvl">${item.level ?? '—'}${item.maxLevel ? ' / ' + item.maxLevel : ''}</div><b style="display:block;width:100%;margin-top:8px;line-height:1.2;overflow-wrap:anywhere">${esc(item.name)}</b>
  </div>`).join('') || '<span class="small">Sem dados</span>';
}
function inventoryCards(items, base) {
  return (items || []).map(item => `<div class="card unit" style="display:flex;flex-direction:column;align-items:center;justify-content:flex-start;text-align:center;min-height:154px;overflow:hidden">
    ${image(gameAsset(item.category, item.name, item.lvl, base), '', '◈')}<div class="lvl">Nv ${item.lvl ?? '—'}</div><b style="display:block;width:100%;margin-top:8px;line-height:1.2;overflow-wrap:anywhere">${esc(item.name)}</b><div class="small" style="display:block;width:100%;margin-top:4px">${item.cnt > 1 ? `${item.cnt} unidades` : ''}</div>
  </div>`).join('') || '<span class="small">Sem dados no último JSON.</span>';
}
function arsenalSection(title, html, count) {
  return `<h3>${esc(title)} <span class="small">(${count})</span></h3><div class="grid arsenal">${html}</div>`;
}

arsenal = function() {
  const base = S.arsenalBase || 'home';
  const army = armySets(base); const inv = inventorySets(base);
  let content = '';
  if (base === 'home') {
    content += arsenalSection('Heróis', apiCards(army.heroes, 'heroes'), army.heroes.length);
    content += arsenalSection('Pets', apiCards(army.pets, 'pets'), army.pets.length);
    content += arsenalSection('Tropas', apiCards(army.troops, 'troops'), army.troops.length);
    content += arsenalSection('Feitiços', apiCards(army.spells, 'spells'), army.spells.length);
    content += arsenalSection('Máquinas de Cerco', apiCards(army.siege, 'troops'), army.siege.length);
    content += arsenalSection('Equipamentos', apiCards(army.equipment, 'equipment'), army.equipment.length);
    content += arsenalSection('Construções', inventoryCards(inv.buildings, base), inv.buildings.length);
    content += arsenalSection('Defesas', inventoryCards(inv.defenses, base), inv.defenses.length);
    content += arsenalSection('Armadilhas', inventoryCards(inv.traps, base), inv.traps.length);
    content += arsenalSection('Muros', inventoryCards(inv.walls, base), inv.walls.length);
    content += arsenalSection('Ajudantes', inventoryCards(inv.helpers, base), inv.helpers.length);
  } else {
    content += arsenalSection('Heróis da Base do Construtor', apiCards(army.heroes, 'heroes'), army.heroes.length);
    content += arsenalSection('Tropas da Base do Construtor', apiCards(army.troops, 'troops'), army.troops.length);
    content += arsenalSection('Construções', inventoryCards(inv.buildings, base), inv.buildings.length);
    content += arsenalSection('Defesas', inventoryCards(inv.defenses, base), inv.defenses.length);
    content += arsenalSection('Armadilhas', inventoryCards(inv.traps, base), inv.traps.length);
    content += arsenalSection('Muros', inventoryCards(inv.walls, base), inv.walls.length);
  }
  return `<div class="section"><div class="row"><h2 style="margin:0">Arsenal</h2><div class="spacer"></div></div>${baseSwitch(base, 'setArsenalBase')}<div class="small">${base === 'home' ? 'Vila Principal: exército, heróis, pets, cerco e estruturas próprias.' : 'Base do Construtor: heróis, tropas, construções, defesas e armadilhas independentes.'}</div>${content}</div>`;
};

function upgradeRows(summary, base) {
  const active = summary.active_upgrades || []; const pending = summary.top_pending || [];
  return `<div class="section"><h2>Em andamento</h2><div class="list">${active.map(item => `<div class="item">${image(gameAsset(item.category, item.name, item.to_lvl, base), '', '◈')}<div><b>${esc(item.name)}</b><div class="small">nível ${item.from_lvl} → ${item.to_lvl} · ${esc(item.queue)}</div></div><div class="right"><b>${dur(item.secs_left)}</b><div class="small">${date(item.finish_ts)}</div></div></div>`).join('') || '<div class="small">Nenhum upgrade ativo nessa base.</div>'}</div></div>
  <div class="section"><h2>Principais pendências</h2><div class="list">${pending.slice(0,80).map(item => `<div class="item">${image(gameAsset(item.category, item.name, Number((item.breakdown || '').match(/→ Lv (\d+)/)?.[1] || 1), base), '', '◈')}<div><b>${esc(item.name)}</b><div class="small">${esc(item.breakdown || '')}</div></div><div class="right"><b>${dur(item.secs)}</b></div></div>`).join('') || '<div class="small">Sem pendências conhecidas.</div>'}</div></div>`;
}
upgrades = function() {
  const base = S.upgradeBase || 'home';
  return `<div class="section"><h2>Upgrades por base</h2>${baseSwitch(base, 'setUpgradeBase')}<div class="small">As filas de construtores e laboratório são independentes entre as duas bases.</div></div>${upgradeRows(summaryFor(base), base)}`;
};

planItem = function(item, queueLabel) {
  const base = item.base || S.plannerBase || 'home';
  const when = item.start ? (item.start <= Math.floor(Date.now()/1000)+60 ? 'agora' : date(item.start)) : '—';
  const worker = queueLabel === 'Construtor' ? `Construtor ${item.worker}` : queueLabel;
  return `<div class="item">${image(gameAsset(item.category,item.name,item.to_lvl,base),'','↗')}<div><b>${esc(item.name || 'Upgrade')}</b><div class="small">${esc(worker)} · → nível ${item.to_lvl ?? '—'} · inicia ${esc(when)}</div>${planCost(item)}</div><div class="right"><b>${dur(item.secs)}</b><div class="small">termina ${date(item.end)}</div></div></div>`;
};
planner = async function() {
  const view = $('view'); const base = S.plannerBase || 'home';
  view.innerHTML = `<div class="section"><h2>Planejador de upgrades</h2>${baseSwitch(base,'setPlannerBase')}<div class="empty">Calculando…</div></div>`;
  try {
    const response = await api(`/api/accounts/${S.id}/plan?strategy=${encodeURIComponent(S.plannerStrategy)}`);
    const plan = base === 'builder' ? (response.builder_base || {}) : response;
    const strategyName = response.strategies?.[response.strategy] || response.strategy;
    const labTitle = base === 'builder' ? 'Cronograma do Laboratório Estelar' : 'Cronograma do laboratório';
    view.innerHTML = `<div class="section"><div class="row"><div><h2 style="margin:0">Planejador de upgrades</h2><div class="small">${base === 'builder' ? 'Base do Construtor' : 'Vila Principal'} · ${esc(strategyName || '')}</div></div><div class="spacer"></div><select id="planStrategy" onchange="S.plannerStrategy=this.value;planner()"><option value="balanced">Balanceado</option><option value="defense">Defesa primeiro</option><option value="farm">Farm primeiro</option><option value="fast">Mais rápidos primeiro</option><option value="cheap">Mais baratos primeiro</option></select></div>${baseSwitch(base,'setPlannerBase')}<div class="planner-help"><b>Como usar:</b> cada base é simulada separadamente. O planejador respeita as filas próprias de construtores e laboratório; ajudantes e muros não são tratados como construções com tempo de fila.</div><div class="grid stats plan-stats"><div class="card"><span class="small">Conclusão projetada</span><b class="big compact">${date(plan.projected_all_done)}</b></div><div class="card"><span class="small">Fila construtores</span><b class="big">${plan.builders?.schedule?.length || 0}</b></div><div class="card"><span class="small">Fila laboratório</span><b class="big">${plan.lab?.schedule?.length || 0}</b></div>${base === 'home' ? `<div class="card"><span class="small">Fila pets</span><b class="big">${plan.pets?.schedule?.length || 0}</b></div>` : ''}</div><div class="small planner-note">${esc(response.note || '')}</div></div>
    <div class="section"><h2>Próximos upgrades sugeridos</h2><div class="list">${(plan.suggestions || []).map(item => planItem(item,'Construtor')).join('') || '<div class="small">Nenhuma sugestão disponível.</div>'}</div></div>
    ${scheduleSection('Cronograma dos construtores',plan.builders,'Construtor')}${scheduleSection(labTitle,plan.lab,base === 'builder' ? 'Laboratório Estelar' : 'Laboratório')}${base === 'home' ? scheduleSection('Cronograma da Casa dos Pets',plan.pets,'Casa dos Pets') : ''}`;
    $('planStrategy').value = S.plannerStrategy;
  } catch (error) { view.innerHTML = `<div class="notice error">${esc(error.message)}</div>`; }
};

loadRichAssetManifest().then(() => { if (S.d) tab(S.tab); });
