// Reserve Juggler — Frontend Client Logic

let fanChartInstance = null;
let bufferChartInstance = null;
let isLive = false;
let pollingInterval = null;

// Currency formatter
const fmtUSD = (num) => {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(num);
};

// Initialize Charts
function initCharts() {
  const fanCtx = document.getElementById('fanChart').getContext('2d');
  fanChartInstance = new Chart(fanCtx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [
        {
          label: 'P99.9 Outflow Cap',
          data: [],
          borderColor: 'rgba(239, 68, 68, 0.8)',
          backgroundColor: 'rgba(239, 68, 68, 0.1)',
          fill: '+1',
          tension: 0.3,
          borderDash: [5, 5],
          pointRadius: 0,
        },
        {
          label: 'P99 Outflow',
          data: [],
          borderColor: 'rgba(245, 158, 11, 0.8)',
          backgroundColor: 'rgba(245, 158, 11, 0.15)',
          fill: '+1',
          tension: 0.3,
          pointRadius: 0,
        },
        {
          label: 'P95 Outflow',
          data: [],
          borderColor: 'rgba(59, 130, 246, 0.8)',
          backgroundColor: 'rgba(59, 130, 246, 0.2)',
          fill: '+1',
          tension: 0.3,
          pointRadius: 0,
        },
        {
          label: 'P50 Outflow Expected',
          data: [],
          borderColor: '#3B82F6',
          backgroundColor: 'transparent',
          borderWidth: 2,
          tension: 0.3,
          pointRadius: 2,
        },
        {
          label: 'P50 Inflow Expected',
          data: [],
          borderColor: '#10B981',
          backgroundColor: 'transparent',
          borderWidth: 2,
          borderDash: [4, 4],
          tension: 0.3,
          pointRadius: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: '#9CA3AF', font: { size: 11 } } },
        tooltip: { mode: 'index', intersect: false },
      },
      scales: {
        x: { ticks: { color: '#9CA3AF', font: { size: 10 } }, grid: { color: '#1F2937' } },
        y: {
          ticks: {
            color: '#9CA3AF',
            font: { size: 10 },
            callback: (v) => '$' + (v / 1e6).toFixed(1) + 'M',
          },
          grid: { color: '#1F2937' },
        },
      },
    },
  });

  const bufCtx = document.getElementById('bufferChart').getContext('2d');
  bufferChartInstance = new Chart(bufCtx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [
        {
          label: 'Cash Buffer',
          data: [],
          borderColor: '#10B981',
          backgroundColor: 'rgba(16, 185, 129, 0.15)',
          fill: true,
          tension: 0.2,
          borderWidth: 2,
          pointRadius: 1,
        },
        {
          label: 'Required Cushion',
          data: [],
          borderColor: '#F59E0B',
          borderDash: [4, 4],
          borderWidth: 2,
          fill: false,
          pointRadius: 0,
        },
        {
          label: 'Yield Vault ($M / 10)',
          data: [],
          borderColor: '#3B82F6',
          borderWidth: 1.5,
          fill: false,
          pointRadius: 0,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: '#9CA3AF', font: { size: 11 } } },
      },
      scales: {
        x: { ticks: { color: '#9CA3AF', font: { size: 10 } }, grid: { color: '#1F2937' } },
        y: {
          ticks: {
            color: '#9CA3AF',
            font: { size: 10 },
            callback: (v) => '$' + (v / 1e6).toFixed(1) + 'M',
          },
          grid: { color: '#1F2937' },
        },
      },
    },
  });
}

// Fetch and update telemetry
async function fetchTelemetry() {
  try {
    const res = await fetch('/api/telemetry');
    if (!res.ok) return;
    const data = await res.json();
    renderTelemetry(data);
  } catch (err) {
    console.error('Failed to fetch telemetry:', err);
  }
}

function renderTelemetry(data) {
  // Update Header
  document.getElementById('cycleIdx').textContent = data.cycle_index;
  document.getElementById('cycleTime').textContent = data.timestamp;

  const modePill = document.getElementById('modePill');
  const modeText = document.getElementById('modeText');
  const modeDot = document.getElementById('modeDot');
  modeText.textContent = data.mode;

  if (data.mode === 'NORMAL') {
    modePill.style.borderColor = 'var(--emerald)';
    modePill.style.color = 'var(--emerald)';
    modePill.style.background = 'rgba(16, 185, 129, 0.1)';
    modeDot.style.backgroundColor = 'var(--emerald)';
  } else if (data.mode === 'PAUSED') {
    modePill.style.borderColor = 'var(--amber)';
    modePill.style.color = 'var(--amber)';
    modePill.style.background = 'rgba(245, 158, 11, 0.1)';
    modeDot.style.backgroundColor = 'var(--amber)';
  } else if (data.mode === 'KILLED') {
    modePill.style.borderColor = 'var(--red)';
    modePill.style.color = 'var(--red)';
    modePill.style.background = 'rgba(239, 68, 68, 0.15)';
    modeDot.style.backgroundColor = 'var(--red)';
  } else {
    modePill.style.borderColor = 'var(--purple)';
    modePill.style.color = 'var(--purple)';
    modePill.style.background = 'rgba(139, 92, 246, 0.1)';
    modeDot.style.backgroundColor = 'var(--purple)';
  }

  // Update Metric Cards
  document.getElementById('cashBufferVal').textContent = fmtUSD(data.cash_buffer_usd);
  document.getElementById('yieldVaultVal').textContent = fmtUSD(data.yield_vault_usd);
  document.getElementById('reqCushionVal').textContent = fmtUSD(data.required_cushion_usd);
  document.getElementById('headroomVal').textContent = `Headroom: ${fmtUSD(data.headroom_usd)}`;

  const alphaPrefix = data.yield_alpha_usd >= 0 ? '+' : '';
  document.getElementById('yieldAlphaVal').textContent = `${alphaPrefix}${fmtUSD(data.yield_alpha_usd)}`;
  document.getElementById('baselineYieldVal').textContent = `Baseline: ${fmtUSD(data.baseline_yield_earned_usd)}`;

  document.getElementById('wapeVal').textContent = (data.current_wape * 100).toFixed(2) + '%';
  document.getElementById('reliabilityVal').textContent = data.payout_success_rate.toFixed(1) + '%';
  document.getElementById('emergencyDrawsVal').textContent = `Emergency Draws: ${data.emergency_draws}`;

  // Update Fan Chart
  if (data.forecast_fan && data.forecast_fan.length > 0) {
    const labels = data.forecast_fan.map((s) => `+${s.step * 15}m`);
    fanChartInstance.data.labels = labels;
    fanChartInstance.data.datasets[0].data = data.forecast_fan.map((s) => s.out_p999);
    fanChartInstance.data.datasets[1].data = data.forecast_fan.map((s) => s.out_p99);
    fanChartInstance.data.datasets[2].data = data.forecast_fan.map((s) => s.out_p95);
    fanChartInstance.data.datasets[3].data = data.forecast_fan.map((s) => s.out_p50);
    fanChartInstance.data.datasets[4].data = data.forecast_fan.map((s) => s.in_p50);
    fanChartInstance.update();
  }

  // Update Buffer Chart
  if (bufferChartInstance.data.labels.length > 30) {
    bufferChartInstance.data.labels.shift();
    bufferChartInstance.data.datasets[0].data.shift();
    bufferChartInstance.data.datasets[1].data.shift();
    bufferChartInstance.data.datasets[2].data.shift();
  }
  bufferChartInstance.data.labels.push(`c${data.cycle_index}`);
  bufferChartInstance.data.datasets[0].data.push(data.cash_buffer_usd);
  bufferChartInstance.data.datasets[1].data.push(data.required_cushion_usd);
  bufferChartInstance.data.datasets[2].data.push(data.yield_vault_usd / 10.0);
  bufferChartInstance.update();

  // Update Audit Log Table
  const tbody = document.getElementById('auditTableBody');
  if (data.recent_audit && data.recent_audit.length > 0) {
    tbody.innerHTML = data.recent_audit
      .slice()
      .reverse()
      .map((r) => {
        let decColor = '#10B981';
        if (r.decision.includes('HOLD')) decColor = '#F59E0B';
        if (r.decision.includes('KILLED') || r.decision.includes('FAILSAFE')) decColor = '#EF4444';
        return `
          <tr>
            <td><strong>#${r.cycle}</strong></td>
            <td>${r.timestamp.split('T')[1]?.substring(0, 5) || r.timestamp}</td>
            <td>${fmtUSD(r.cash)}</td>
            <td>${fmtUSD(r.cushion)}</td>
            <td>${fmtUSD(r.headroom)}</td>
            <td><span style="color:${decColor}; font-weight:700;">${r.decision}</span></td>
            <td>${r.sweep > 0 ? fmtUSD(r.sweep) : '-'}</td>
            <td style="color:#9CA3AF; font-size:11px;">${r.reason}</td>
            <td><code style="background:#1F2937; padding:2px 6px; border-radius:4px; font-size:10px;">${r.hash}</code></td>
          </tr>
        `;
      })
      .join('');
  }
}

// Controls Event Handlers
async function postControl(action, payload = {}) {
  try {
    const res = await fetch('/api/control', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, ...payload }),
    });
    const result = await res.json();
    fetchTelemetry();
    return result;
  } catch (err) {
    console.error('Control error:', err);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  initCharts();
  fetchTelemetry();
  pollingInterval = setInterval(fetchTelemetry, 1500);

  // Button Listeners
  const btnLive = document.getElementById('btnLive');
  btnLive.addEventListener('click', async () => {
    isLive = !isLive;
    if (isLive) {
      await postControl('start_live');
      btnLive.textContent = '⏸ Pause Live Simulation';
      btnLive.classList.remove('btn-primary');
      btnLive.classList.add('btn-secondary');
    } else {
      await postControl('stop_live');
      btnLive.textContent = '▶ Start Live Simulation';
      btnLive.classList.remove('btn-secondary');
      btnLive.classList.add('btn-primary');
    }
  });

  document.getElementById('btnStep').addEventListener('click', () => {
    postControl('step');
  });

  document.getElementById('btnShock').addEventListener('click', () => {
    postControl('inject_shock');
    alert('⚡ 3x Outflow Surge Shock Injected for the next 2 hours (8 buckets)!');
  });

  document.getElementById('btnManualSweep').addEventListener('click', () => {
    const amount = parseFloat(document.getElementById('manualSweepInput').value);
    if (!amount || amount <= 0) {
      alert('Please enter a valid sweep amount in USD.');
      return;
    }
    postControl('manual_sweep', { amount_usd: amount });
    document.getElementById('manualSweepInput').value = '';
  });

  const btnPause = document.getElementById('btnPause');
  let isPaused = false;
  btnPause.addEventListener('click', async () => {
    isPaused = !isPaused;
    if (isPaused) {
      await postControl('pause');
      btnPause.textContent = '▶ Resume Sweeps';
    } else {
      await postControl('resume');
      btnPause.textContent = '⏸ Pause Sweeps';
    }
  });

  const btnKill = document.getElementById('btnKill');
  let isKilled = false;
  btnKill.addEventListener('click', async () => {
    if (!isKilled) {
      if (confirm('🚨 ACTIVATE EMERGENCY KILL SWITCH? Sweeps will be immediately blocked and all cash retained.')) {
        await postControl('kill');
        isKilled = true;
        btnKill.textContent = '↺ RESET KILL SWITCH';
      }
    } else {
      await postControl('reset_kill');
      isKilled = false;
      btnKill.textContent = '🚨 EMERGENCY KILL SWITCH';
    }
  });
});
