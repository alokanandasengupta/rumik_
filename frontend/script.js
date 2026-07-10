// env-config.js (loaded before this file, see index.html) sets
// window.REACT_APP_BACKEND_URL from the environment when one is provided.
// With none set, same-origin /api is the right default, that's what this
// environment's ingress routes to the backend.
const BACKEND_URL = window.REACT_APP_BACKEND_URL || window.location.origin;
const API_BASE = `${BACKEND_URL}/api`;

const form = document.getElementById('score-form');
const submitBtn = document.getElementById('submit-btn');
const formError = document.getElementById('form-error');
const modelBanner = document.getElementById('model-banner');
const results = document.getElementById('results');
const neverActivatedBox = form.elements['never_activated'];
const behaviorFields = document.getElementById('behavior-fields');

const CATEGORICAL_FIELDS = [
  'platform', 'pricing_region_at_signup', 'creation_source', 'active_experiment',
  'channel', 'ad_intent', 'targeting_age_bucket', 'targeting_gender',
  'targeting_interest', 'nudge_experiment_arm',
];

function setBehaviorFieldsEnabled(enabled) {
  behaviorFields.toggleAttribute('disabled', !enabled);
}

neverActivatedBox.addEventListener('change', () => {
  setBehaviorFieldsEnabled(!neverActivatedBox.checked);
});
setBehaviorFieldsEnabled(false);

function populateHourSelect() {
  const select = form.elements['signup_hour_of_day'];
  for (let h = 0; h < 24; h++) {
    const opt = document.createElement('option');
    opt.value = h;
    opt.textContent = `${h.toString().padStart(2, '0')}:00`;
    select.appendChild(opt);
  }
}

async function loadOptions() {
  const res = await fetch(`${API_BASE}/health`);
  const health = await res.json();

  if (health.status !== 'ok') {
    modelBanner.hidden = false;
    modelBanner.textContent = health.missing_files && health.missing_files.length
      ? `Models not loaded yet, missing: ${health.missing_files.join(', ')}. See backend/README.md.`
      : `Models failed to load: ${health.load_error || 'unknown error'}.`;
    submitBtn.disabled = true;
    return;
  }

  const optRes = await fetch(`${API_BASE}/options`);
  const opts = await optRes.json();

  for (const field of CATEGORICAL_FIELDS) {
    const select = form.elements[field];
    const values = opts.categorical_values[field] || opts.channels || [];
    select.innerHTML = '';
    for (const value of values) {
      const opt = document.createElement('option');
      opt.value = value;
      opt.textContent = value;
      select.appendChild(opt);
    }
  }

  submitBtn.disabled = false;
}

function fmtPct(x) {
  return `${(x * 100).toFixed(1)}%`;
}

function renderResults(data) {
  results.hidden = false;

  const pct = data.payer_probability;
  document.getElementById('payer-probability-value').textContent = fmtPct(pct);
  document.getElementById('payer-probability-fill').style.width = fmtPct(pct);

  document.getElementById('ltv-value').textContent =
    `₹${data.predicted_ltv_d30_inr.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
  document.getElementById('signal-weight-value').textContent =
    data.signal_weight_used.toFixed(2);

  const bars = document.getElementById('retention-bars');
  bars.innerHTML = '';
  const days = [
    ['day_1', 'Day 1'],
    ['day_7', 'Day 7'],
    ['day_14', 'Day 14'],
    ['day_30', 'Day 30'],
  ];
  for (const [key, label] of days) {
    const value = data.retention_probability[key];
    const col = document.createElement('div');
    col.className = 'bar-col';

    const valueLabel = document.createElement('div');
    valueLabel.className = 'bar-value';
    valueLabel.textContent = fmtPct(value);

    const shape = document.createElement('div');
    shape.className = 'bar-shape';
    shape.style.height = `${Math.max(value * 100, 2)}%`;

    col.appendChild(valueLabel);
    col.appendChild(shape);
    bars.appendChild(col);
  }

  const labelRow = document.getElementById('retention-day-labels');
  labelRow.innerHTML = '';
  for (const [, label] of days) {
    const el = document.createElement('div');
    el.className = 'bar-day-label';
    el.style.flex = '1';
    el.style.textAlign = 'center';
    el.textContent = label;
    labelRow.appendChild(el);
  }
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  formError.hidden = true;
  submitBtn.disabled = true;
  submitBtn.textContent = 'Scoring...';

  const fd = new FormData(form);
  const neverActivated = form.elements['never_activated'].checked;

  const payload = {
    platform: fd.get('platform'),
    pricing_region_at_signup: fd.get('pricing_region_at_signup'),
    creation_source: fd.get('creation_source'),
    active_experiment: fd.get('active_experiment'),
    channel: fd.get('channel'),
    ad_intent: fd.get('ad_intent'),
    targeting_age_bucket: fd.get('targeting_age_bucket'),
    targeting_gender: fd.get('targeting_gender'),
    targeting_interest: fd.get('targeting_interest'),
    nudge_experiment_arm: fd.get('nudge_experiment_arm'),
    signup_hour_of_day: Number(fd.get('signup_hour_of_day')),
    signup_day_of_week: Number(fd.get('signup_day_of_week')),
    never_activated: neverActivated,
    browse_to_chat_latency_minutes: Number(fd.get('browse_to_chat_latency_minutes') || 0),
    n_app_opens_pre_message: Number(fd.get('n_app_opens_pre_message') || 0),
    pre_message_revenue: Number(fd.get('pre_message_revenue') || 0),
    saw_plans_pre_message: fd.get('saw_plans_pre_message') === 'on',
    purchased_pre_message: fd.get('purchased_pre_message') === 'on',
  };

  try {
    const res = await fetch(`${API_BASE}/score`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    const data = await res.json();
    renderResults(data);
  } catch (err) {
    formError.hidden = false;
    formError.textContent = err.message;
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Score this user';
  }
});

populateHourSelect();
loadOptions().catch((err) => {
  modelBanner.hidden = false;
  modelBanner.textContent = `Could not reach the backend at ${API_BASE}: ${err.message}`;
  submitBtn.disabled = true;
});
