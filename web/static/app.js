// Helpers
const $ = (sel) => document.querySelector(sel);
const api = async (path, body) => {
  const res = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const ct = res.headers.get('content-type') || '';
  let data;
  try {
    data = ct.includes('application/json') ? await res.json() : JSON.parse(await res.text());
  } catch (e) {
    const txt = await res.text().catch(()=>'' );
    throw new Error(txt || 'Non-JSON response');
  }
  if (!res.ok) throw new Error(data.error || 'Request failed');
  return data;
};
const setBalance = (n) => { const el = $('#balance'); if (el) el.textContent = `${n.toLocaleString()} BoulderCoin`; };
let authed = false;
let currentUser = null;

const refreshMe = async () => {
  try {
    const res = await fetch('/api/me');
    if (res.status === 401) {
      authed = false; currentUser = null;
      const login = $('#login'), uinfo = $('#user-info');
      if (login) login.classList.remove('hide');
      if (uinfo) uinfo.classList.add('hide');
      setBalance(0); return;
    }
    const data = await res.json();
    authed = true; currentUser = data.user;
    const dn = $('#display-name'), login = $('#login'), uinfo = $('#user-info');
    if (dn) dn.textContent = currentUser.display_name || currentUser.login;
    if (login) login.classList.add('hide');
    if (uinfo) uinfo.classList.remove('hide');
    setBalance(data.balance);
  } catch (e) { console.error(e); }
};

document.addEventListener('DOMContentLoaded', async () => {
  await refreshMe();
  const page = document.body.getAttribute('data-page');
  if (page === 'double') initDouble();
  if (page === 'slots') initSlots();
  if (page === 'blackjack') initBlackjack();
});

const loginBtn = document.querySelector('#login');
if (loginBtn) loginBtn.addEventListener('click', () => { window.location.href = '/login'; });

// Double or Nothing
function initDouble(){
  const btn = $('#gamble'); if (!btn) return;
  btn.addEventListener('click', async () => {
    if (!authed) return (window.location.href = '/login');
    const amt = parseInt($('#gamble-amount').value, 10);
    if (!amt || amt <= 0) return alert('Enter a valid amount');
    const out = $('#gamble-result');
    out.className = 'result'; out.textContent = 'Rolling...';
    try {
      const data = await api('/api/gamble', { amount: amt });
      setBalance(data.balance);
      out.classList.add(data.outcome === 'win' ? 'win' : 'lose');
      out.textContent = data.outcome === 'win' ? `You won +${data.delta} 🪨!` : `You lost ${-data.delta} 🪨.`;
    } catch (e) {
      if (/unauthenticated/i.test(e.message)) return (window.location.href = '/login');
      out.className = 'result'; out.textContent = e.message;
    }
  });
}

// Slots
function initSlots(){
  const reelsEls = [$('#reel-1'), $('#reel-2'), $('#reel-3')];
  if (!reelsEls[0]) return;
  const SYMBOLS = ['🍒','🍋','🔔','⭐','7️⃣'];
  const randSymbol = () => SYMBOLS[Math.floor(Math.random()*SYMBOLS.length)];
  const animateReel = (reelEl, finalSymbol, durationMs, cells = 16) => new Promise((resolve) => {
    const h = Math.round(reelEl.getBoundingClientRect().height);
    const symbols = Array.from({length: cells}, randSymbol);
    symbols.push(finalSymbol);
    const strip = document.createElement('div');
    strip.className = 'strip';
    strip.innerHTML = symbols.map(s => `<div class="cell" style="height:${h}px"><span>${s}</span></div>`).join('');
    reelEl.innerHTML = '';
    reelEl.appendChild(strip);
    void strip.offsetHeight; // reflow
    strip.style.transition = `transform ${durationMs}ms cubic-bezier(0.2, 0.8, 0.2, 1)`;
    strip.style.transform = `translateY(-${h * (symbols.length - 1)}px)`;
    const done = () => { strip.removeEventListener('transitionend', done); resolve(); };
    strip.addEventListener('transitionend', done);
    setTimeout(done, durationMs + 100);
  });

  // Web Audio SFX (no external files)
  let audioCtx;
  const getCtx = () => {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    return audioCtx;
  };
  const playTone = (freq, dur, type='sine', vol=0.2) => {
    const ctx = getCtx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = type; osc.frequency.value = freq;
    osc.connect(gain); gain.connect(ctx.destination);
    const now = ctx.currentTime;
    gain.gain.setValueAtTime(vol, now);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + dur);
    osc.start(now); osc.stop(now + dur);
  };
  const sfxSpin = () => {
    // sequence of quick ticks to simulate reel spin
    for (let i=0;i<10;i++) {
      setTimeout(() => playTone(500 + i*15, 0.045, 'triangle', 0.08), i*70);
    }
  };
  const sfxWin = () => { playTone(880, 0.12, 'sine', 0.2); setTimeout(()=>playTone(1175, 0.18, 'sine', 0.2), 130); };
  const sfxLose = () => { playTone(220, 0.25, 'sawtooth', 0.14); };

  $('#spin').addEventListener('click', async () => {
    if (!authed) return (window.location.href = '/login');
    const bet = parseInt($('#slots-bet').value, 10);
    if (!bet || bet <= 0) return alert('Enter a valid bet');
    const out = $('#slots-result');
    out.className = 'result'; out.textContent = '';
    const spinBtn = $('#spin'); spinBtn.disabled = true;
    try {
      // ensure audio context active on user gesture
      const ctx = getCtx(); if (ctx.state === 'suspended') { await ctx.resume().catch(()=>{}); }
      sfxSpin();
      const data = await api('/api/slots/spin', { bet });
      const symbols = data.reels; const durations = [1100, 1350, 1600];
      await Promise.all(symbols.map((sym, i) => animateReel(reelsEls[i], sym, durations[i])));
      setBalance(data.balance);
      if (data.won) { sfxWin(); out.classList.add('win'); out.textContent = `WIN x${data.multiplier}! Payout +${data.payout} 🪨`; }
      else { sfxLose(); out.classList.add('lose'); out.textContent = `No win. Lost ${bet} 🪨`; }
    } catch (e) {
      if (/unauthenticated/i.test(e.message)) return (window.location.href = '/login');
      out.className = 'result'; out.textContent = e.message;
    } finally { spinBtn.disabled = false; }
  });
}

// Blackjack
function initBlackjack(){
  const dealer = document.querySelector('#bj-dealer');
  if (!dealer) return;
  const player = document.querySelector('#bj-player');
  const res = document.querySelector('#bj-result');
  const hitBtn = document.querySelector('#bj-hit');
  const standBtn = document.querySelector('#bj-stand');
  const dealBtn = document.querySelector('#bj-deal');
  const cardVal = (card) => {
    const r = card.slice(0, -1); // strip suit
    if (r === 'A') return 11;
    if (['K','Q','J'].includes(r)) return 10;
    return parseInt(r,10);
  };
  const handTotal = (cards) => {
    let total = 0, aces = 0;
    for (const c of cards){ const r = c.slice(0,-1); if (r==='A'){ aces++; total += 11; } else if (['K','Q','J'].includes(r)){ total += 10; } else { total += parseInt(r,10); } }
    while (total>21 && aces>0){ total -= 10; aces--; }
    return total;
  };
  const showState = (state) => {
    const d = (state.dealer||[]);
    const p = (state.player||[]);
    const dealerHidden = d.includes('??');
    dealer.textContent = dealerHidden ? `${d.join(' ')}` : `${d.join(' ')} (total: ${handTotal(d)})`;
    player.textContent = `${p.join(' ')} (total: ${handTotal(p)})`;
  };
  dealBtn.addEventListener('click', async () => {
    if (!authed) return (window.location.href = '/login');
    const bet = parseInt(document.querySelector('#bj-bet').value, 10);
    if (!bet || bet <= 0) return alert('Enter a valid bet');
    res.className = 'result'; res.textContent = '';
    try {
      const data = await api('/api/blackjack/new', { bet });
      showState(data.state);
      setBalance(data.balance ?? (await (await fetch('/api/me')).json()).balance);
      if (data.state.done){
        res.textContent = data.outcome || '';
        hitBtn.disabled = true; standBtn.disabled = true; dealBtn.disabled = false;
      } else {
        hitBtn.disabled = false; standBtn.disabled = false; dealBtn.disabled = true;
        if (data.hand_in_progress) res.textContent = 'Hand in progress';
      }
    } catch (e) { res.textContent = String(e.message || e); }
  });
  hitBtn.addEventListener('click', async () => { try { const data = await api('/api/blackjack/hit', {}); showState(data.state); if (data.state.done){ res.textContent = data.outcome || 'bust'; const me = await (await fetch('/api/me')).json(); setBalance(me.balance); hitBtn.disabled = true; standBtn.disabled = true; dealBtn.disabled = false; } } catch (e) { res.textContent = String(e.message || e); } });
  standBtn.addEventListener('click', async () => { try { const data = await api('/api/blackjack/stand', {}); showState(data.state); res.textContent = data.outcome; setBalance(data.balance); hitBtn.disabled = true; standBtn.disabled = true; dealBtn.disabled = false; } catch (e) { res.textContent = String(e.message || e); } });
}

