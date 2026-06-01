// Shared stock search autocomplete.
// Attaches to any <input data-autocomplete> inside a form; queries /api/suggest.
(function () {
  const CSS = `
    .ac-wrap { position: relative; flex: 1; }
    .ac-wrap input { width: 100%; box-sizing: border-box; }
    .ac-suggestions {
      position: absolute; top: calc(100% + 6px); left: 0; right: 0;
      background: #0d1530;
      border: 1px solid rgba(138, 148, 173, 0.15);
      border-radius: 6px;
      overflow: hidden; z-index: 30;
      box-shadow: 0 14px 34px rgba(0, 0, 0, 0.45);
      display: none; text-align: left;
    }
    .ac-suggestions.open { display: block; }
    .ac-suggestion {
      display: flex; align-items: baseline; gap: 14px;
      padding: 11px 14px; cursor: pointer;
      border-bottom: 1px solid rgba(138, 148, 173, 0.15);
    }
    .ac-suggestion:last-child { border-bottom: none; }
    .ac-suggestion:hover, .ac-suggestion.active { background: rgba(37, 185, 95, 0.10); }
    .ac-symbol {
      font-family: 'JetBrains Mono', monospace; font-weight: 600;
      font-size: 14px; color: #e8ecf5; flex-shrink: 0;
    }
    .ac-name {
      flex: 1; text-align: right; font-size: 13px; color: #8a94ad;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    .ac-exch { color: rgba(138, 148, 173, 0.65); }
  `;

  function injectCss() {
    const s = document.createElement('style');
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function init(input) {
    const form = input.form;
    if (!form) return;

    const wrap = document.createElement('div');
    wrap.className = 'ac-wrap';
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    const box = document.createElement('div');
    box.className = 'ac-suggestions';
    box.setAttribute('role', 'listbox');
    wrap.appendChild(box);

    let items = [];
    let active = -1;
    let timer = null;

    function close() {
      box.classList.remove('open');
      box.innerHTML = '';
      items = [];
      active = -1;
    }

    function render() {
      if (!items.length) { close(); return; }
      box.innerHTML = items.map((it, i) =>
        '<div class="ac-suggestion' + (i === active ? ' active' : '') + '" data-i="' + i + '" role="option">' +
          '<span class="ac-symbol">' + escapeHtml(it.symbol) + '</span>' +
          '<span class="ac-name">' + escapeHtml(it.name) +
            (it.exchange ? ' <span class="ac-exch">· ' + escapeHtml(it.exchange) + '</span>' : '') +
          '</span>' +
        '</div>').join('');
      box.classList.add('open');
    }

    function choose(i) {
      if (i < 0 || i >= items.length) return;
      input.value = items[i].symbol;
      close();
      form.submit();
    }

    input.addEventListener('input', function () {
      const q = input.value.trim();
      if (timer) clearTimeout(timer);
      if (!q) { close(); return; }
      timer = setTimeout(function () {
        fetch('/api/suggest?q=' + encodeURIComponent(q))
          .then(r => r.ok ? r.json() : [])
          .then(data => {
            if (input.value.trim() !== q) return;  // stale response
            items = data;
            active = -1;
            render();
          })
          .catch(() => close());
      }, 180);
    });

    input.addEventListener('keydown', function (e) {
      if (!box.classList.contains('open')) return;
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        active = Math.min(active + 1, items.length - 1);
        render();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        active = Math.max(active - 1, 0);
        render();
      } else if (e.key === 'Enter') {
        if (active >= 0) { e.preventDefault(); choose(active); }
      } else if (e.key === 'Escape') {
        close();
      }
    });

    box.addEventListener('mousedown', function (e) {
      const el = e.target.closest('.ac-suggestion');
      if (el) { e.preventDefault(); choose(parseInt(el.dataset.i, 10)); }
    });

    document.addEventListener('click', function (e) {
      if (!wrap.contains(e.target)) close();
    });
  }

  injectCss();
  document.querySelectorAll('input[data-autocomplete]').forEach(init);
})();
