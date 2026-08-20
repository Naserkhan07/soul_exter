const $ = selector => document.querySelector(selector);
let snapshot, currentProduct, fulfillmentToken, paymentToken, paymentPollTimer, restoredPayment = false;

const esc = value => String(value ?? '').replace(/[&<>'"]/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
})[char]);
const money = value => new Intl.NumberFormat(snapshot?.currency === 'INR' ? 'en-IN' : 'en-US', {
  style: 'currency', currency: snapshot?.currency || 'INR'
}).format((value || 0) / 100);
const until = value => {
  if (!value) return 'unscheduled';
  const seconds = (new Date(value) - Date.now()) / 1000;
  if (seconds <= 0) return 'due now';
  if (seconds < 60) return `in ${Math.ceil(seconds)}s`;
  if (seconds < 3600) return `in ${Math.ceil(seconds / 60)}m`;
  return `in ${Math.ceil(seconds / 3600)}h`;
};
const ago = value => {
  const seconds = (Date.now() - new Date(value)) / 1000;
  if (seconds < 60) return `${Math.max(0, Math.floor(seconds))}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
};
const icon = {birth:'◉', bootstrap:'○', launch:'↗', sale:'+$', promotion:'↑', thought:'··', replication:'◇', death:'×', error:'!'};

function render(state) {
  snapshot = state;
  $('#mode').textContent = `${state.mode.toUpperCase()} MODE`;
  $('#balance').textContent = money(state.totals.balance);
  $('#revenue').textContent = money(state.totals.revenue);
  $('#population').textContent = `${state.totals.alive} / ${state.agents.length}`;
  $('#survival').textContent = state.totals.balance === 0 ? 'SEEKING REVENUE' : 'EARNING';
  $('#runway').textContent = 'receive-only · never debited';
  const phonepe = state.phonepe_totals || {};
  $('#phonepe-confirmed').textContent = money(phonepe.confirmed_amount);
  $('#phonepe-confirmed-meta').textContent = `${Number(phonepe.confirmed_payments || 0)} verified payments`;
  $('#phonepe-pending').textContent = money(phonepe.pending_amount);
  $('#phonepe-pending-meta').textContent = `${Number(phonepe.pending_payments || 0)} pending checkouts`;
  $('#clone-rule').textContent = `REVENUE MILESTONE ${money(state.replication_threshold_cents)} · MAX ${state.max_agents} AGENTS`;

  const laneNames = {agent_operations:'PRODUCTS & DISTRIBUTION', opportunity_research:'OPPORTUNITY RESEARCH', strategy_research:'STRATEGY ANALYSIS', phonepe_payments:'PHONEPE PAYMENTS'};
  $('#workstream-grid').innerHTML = (state.workstreams || []).length ? state.workstreams.map(workstream => `
    <article class="workstream-card"><header><h3>${esc(laneNames[workstream.name] || workstream.name.replaceAll('_',' ').toUpperCase())}</h3>
    <span class="lane-status">${esc(workstream.status)}</span></header>
    <p>${esc(workstream.last_error ? `Error: ${workstream.last_error}` : JSON.stringify(workstream.last_result || {}))}</p>
    <small>${Number(workstream.runs)} RUNS · LAST ${workstream.last_completed_at ? ago(workstream.last_completed_at) : 'NONE'} · NEXT ${until(workstream.next_run_at)}</small></article>`).join('') : '<div class="empty">Initializing autonomous workstreams…</div>';

  $('#agents').innerHTML = state.agents.map(agent => {
    const progress = Math.min(100, agent.lifetime_revenue_cents / state.replication_threshold_cents * 100);
    return `<article class="agent"><div><div class="agent-top"><i class="status-dot"></i><h3>${esc(agent.name)}</h3></div>
      <p>GEN ${Number(agent.generation)} · ACTIVE · RECEIVE-ONLY TREASURY · BORN ${ago(agent.born_at)}</p></div>
      <div class="agent-money">${money(agent.balance_cents)}<small>${agent.lifetime_revenue_cents ? `${money(agent.lifetime_revenue_cents)} EARNED` : 'NO SALES YET'}</small></div>
      <div class="meter"><i style="width:${progress}%"></i></div></article>`;
  }).join('');

  $('#products').innerHTML = state.products.length ? state.products.map((product, index) => `
    <article class="product"><span class="product-no">PRODUCT / ${String(index + 1).padStart(2,'0')} · ${Number(product.sales_count)} SOLD</span>
    <h3>${esc(product.title)}</h3><p>${esc(product.tagline)}</p><div class="product-foot"><div><strong>${money(product.price_cents)}</strong>
    <p>BY ${esc(product.agent_name)}</p></div><button data-slug="${esc(product.slug)}" aria-label="View ${esc(product.title)}">↗</button></div></article>`).join('') : '<div class="empty">The first product is being assembled…</div>';
  $('#products').querySelectorAll('button[data-slug]').forEach(button => button.onclick = () => openProduct(button.dataset.slug));

  $('#events').innerHTML = state.events.slice(0,12).map(item => `<div class="event"><time>${ago(item.created_at)}</time><p>${esc(item.message)}<small>${icon[item.type] || '·'} ${esc(item.type.toUpperCase())}</small></p></div>`).join('');
  $('#transactions').innerHTML = state.ledger.slice(0,12).map(item => `<div class="transaction"><time>${ago(item.created_at)}</time><p>${esc(item.description)}</p><span class="amount ${item.amount_cents >= 0 ? 'positive' : 'negative'}">${item.amount_cents >= 0 ? '+' : '−'}${money(Math.abs(item.amount_cents))}</span></div>`).join('');
  $('#last-update').textContent = `SIGNAL ${new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'})}`;
}

async function load() {
  try {
    const response = await fetch('/api/state');
    render(await response.json());
    if (!restoredPayment) {
      restoredPayment = true;
      const token = new URLSearchParams(location.search).get('payment');
      if (token) await restorePhonePePayment(token);
    }
  } catch (_) {
    $('#mode').textContent = 'OFFLINE';
  }
}

async function restorePhonePePayment(token) {
  paymentToken = token;
  try {
    const response = await fetch(`/api/payments/phonepe/${encodeURIComponent(token)}`);
    const payload = await response.json();
    if (!response.ok) throw Error(payload.detail || 'PhonePe order was not found');
    if (payload.paid) return unlockPaid(payload);
    currentProduct = snapshot.products.find(product => product.slug === payload.product_slug) || {title: payload.product_title, description: 'PhonePe payment status'};
    resetCheckout(false);
    paymentToken = token;
    $('#dialog-title').textContent = currentProduct.title;
    $('#dialog-description').textContent = currentProduct.description;
    $('#dialog-price').textContent = currentProduct.price_cents ? money(currentProduct.price_cents) : money(payload.amount);
    $('#checkout-note').textContent = `PhonePe ${String(payload.environment || '').toUpperCase()} checkout status.`;
    $('#buy').hidden = true;
    $('#phonepe-payment').hidden = false;
    $('#phonepe-status').textContent = `Status: ${payload.status}. Checking again automatically.`;
    $('#product-dialog').showModal();
    if (payload.status !== 'FAILED') paymentPollTimer = setTimeout(pollPhonePeStatus, 5000);
  } catch (error) {
    toast(error.message);
  }
}

async function pollPhonePeStatus() {
  if (!paymentToken) return;
  try {
    const response = await fetch(`/api/payments/phonepe/${encodeURIComponent(paymentToken)}`);
    const payload = await response.json();
    if (!response.ok) throw Error(payload.detail || 'Unable to check PhonePe payment');
    if (payload.paid) return unlockPaid(payload);
    $('#phonepe-status').textContent = `Status: ${payload.status}. Waiting for verified completion…`;
    if (payload.status !== 'FAILED') paymentPollTimer = setTimeout(pollPhonePeStatus, 5000);
  } catch (error) {
    $('#phonepe-status').textContent = `${error.message}. Retrying…`;
    paymentPollTimer = setTimeout(pollPhonePeStatus, 10000);
  }
}

function resetCheckout(clearPayment = true) {
  fulfillmentToken = null;
  if (clearPayment) paymentToken = null;
  clearTimeout(paymentPollTimer);
  $('#delivery').hidden = true;
  $('#brief-form').hidden = true;
  $('#phonepe-payment').hidden = true;
  $('#buy').hidden = false;
  $('#phonepe-status').textContent = '';
}

window.openProduct = slug => {
  history.replaceState(null, '', `${location.pathname}#market`);
  fetch(`/api/analytics/view/${encodeURIComponent(slug)}`, {method:'POST', keepalive:true}).catch(() => {});
  currentProduct = snapshot.products.find(product => product.slug === slug);
  resetCheckout();
  $('#dialog-title').textContent = currentProduct.title;
  $('#dialog-description').textContent = currentProduct.description;
  $('#dialog-price').textContent = money(currentProduct.price_cents);
  $('#checkout-note').textContent = snapshot.mode === 'simulation'
    ? 'Demo checkout — no real payment is requested.'
    : `Secure PhonePe ${String(snapshot.payment_environment || '').toUpperCase()} checkout. Delivery unlocks only after server-side verification.`;
  $('#product-dialog').showModal();
};

function closeDialog() {
  clearTimeout(paymentPollTimer);
  $('#product-dialog').close();
}
$('#product-dialog .close').onclick = closeDialog;
$('#product-dialog').onclick = event => { if (event.target === $('#product-dialog')) closeDialog(); };

function unlockPaid(payload) {
  clearTimeout(paymentPollTimer);
  history.replaceState(null, '', `${location.pathname}#market`);
  if (payload.brief_required) {
    fulfillmentToken = payload.fulfillment_token;
    $('#phonepe-payment').hidden = true;
    $('#buy').hidden = true;
    $('#brief-form').hidden = false;
    $('#checkout-note').textContent = 'PhonePe payment verified. Complete the brief to create your private report.';
    toast('PHONEPE CONFIRMED · BRIEF UNLOCKED');
  } else {
    $('#phonepe-payment').hidden = true;
    $('#delivery').textContent = payload.content;
    $('#delivery').hidden = false;
    toast('PHONEPE CONFIRMED · PRODUCT DELIVERED');
  }
  load();
}

$('#buy').onclick = async () => {
  if (!currentProduct) return;
  $('#buy').disabled = true;
  $('#buy').textContent = 'PROCESSING…';
  try {
    if (snapshot.mode === 'simulation') {
      const response = await fetch(`/api/simulate-sale/${currentProduct.slug}`, {method:'POST'});
      const payload = await response.json();
      if (!response.ok) throw Error(payload.detail);
      $('#delivery').textContent = payload.content;
      $('#delivery').hidden = false;
      toast('DEMO SALE RECORDED');
      await load();
    } else {
      const referral = new URLSearchParams(location.search).get('ref') || '';
      const response = await fetch(`/api/products/${currentProduct.slug}/checkout?ref=${encodeURIComponent(referral)}`, {method:'POST'});
      const payload = await response.json();
      if (!response.ok) throw Error(payload.detail || 'Could not create PhonePe checkout');
      if (payload.provider !== 'phonepe') throw Error('Unexpected payment provider');
      location.href = payload.redirect_url;
    }
  } catch (error) {
    toast(error.message || 'CHECKOUT FAILED');
  } finally {
    $('#buy').disabled = false;
    $('#buy').textContent = 'PURCHASE';
  }
};

$('#brief-form').onsubmit = async event => {
  event.preventDefault();
  if (!fulfillmentToken) return;
  const button = event.submitter;
  button.disabled = true;
  button.textContent = 'GENERATING…';
  try {
    const payload = Object.fromEntries(new FormData(event.target));
    const response = await fetch(`/api/fulfillment/${fulfillmentToken}`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
    const result = await response.json();
    if (!response.ok) throw Error(result.detail || 'Generation failed');
    location.href = result.delivery_url;
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = 'Generate private report';
  }
};

$('#diagnostic-form').onsubmit = async event => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  button.textContent = 'ANALYZING…';
  try {
    const payload = Object.fromEntries(new FormData(event.target));
    const response = await fetch('/api/free-diagnostic', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
    const result = await response.json();
    if (!response.ok) throw Error(result.detail || 'Diagnostic failed');
    $('#diagnostic-result').innerHTML = result.observations.map((item,index) => `${index + 1}. ${esc(item)}`).join('<br>') + `<br><a href="#market">${esc(result.next_step)}</a>`;
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = 'Run free diagnostic';
  }
};

function toast(text) {
  $('#toast').textContent = text;
  $('#toast').classList.add('show');
  setTimeout(() => $('#toast').classList.remove('show'), 3500);
}

load();
setInterval(load, 10000);
