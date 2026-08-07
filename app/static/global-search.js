/* Busca global do CRM (Ctrl+K, estilo Notion) -- pedido do usuário
 * 2026-08-06. Abre o <dialog id="global-search-modal"> (markup em
 * app/templates/staff_base.html, aberto/fechado via app/static/
 * ui-components.js pro clique no botão -- este arquivo só cuida do
 * atalho de teclado, do fetch em /staff/busca e da navegação por
 * teclado dentro dos resultados.
 */
(function () {
  var dialog = document.getElementById('global-search-modal');
  if (!dialog) return;

  var input = document.getElementById('global-search-input');
  var results = document.getElementById('global-search-results');
  var empty = document.getElementById('global-search-empty');
  var debounceTimer = null;
  var activeIndex = -1;

  function openSearch() {
    dialog.showModal();
    input.value = '';
    input.focus();
    renderResults([]);
  }

  document.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      openSearch();
    }
  });

  var trigger = document.getElementById('global-search-trigger');
  if (trigger) trigger.addEventListener('click', openSearch);

  function groupLabel(type) {
    var labels = { Client: 'Clients', Lead: 'Leads', Case: 'Cases', Task: 'Tasks', Document: 'Documents', Translator: 'Translators' };
    return labels[type] || type;
  }

  function renderResults(items) {
    results.innerHTML = '';
    activeIndex = -1;
    if (!items.length) {
      empty.hidden = input.value.trim().length < 2;
      empty.textContent = input.value.trim().length < 2
        ? 'Type at least 2 characters to search across Clients, Leads, Cases, Tasks, Documents and Translators.'
        : 'No results.';
      empty.hidden = false;
      return;
    }
    empty.hidden = true;
    var currentType = null;
    items.forEach(function (item, index) {
      if (item.type !== currentType) {
        currentType = item.type;
        var label = document.createElement('div');
        label.className = 'search-group-label';
        label.textContent = groupLabel(item.type);
        results.appendChild(label);
      }
      var a = document.createElement('a');
      a.href = item.url;
      a.className = 'search-result';
      a.dataset.index = index;
      a.innerHTML =
        '<div class="search-result-label"></div>' +
        (item.sublabel ? '<div class="search-result-sublabel"></div>' : '');
      a.querySelector('.search-result-label').textContent = item.label;
      if (item.sublabel) a.querySelector('.search-result-sublabel').textContent = item.sublabel;
      results.appendChild(a);
    });
  }

  function setActive(index) {
    var links = results.querySelectorAll('.search-result');
    if (!links.length) return;
    if (index < 0) index = links.length - 1;
    if (index >= links.length) index = 0;
    links.forEach(function (link) { link.classList.remove('is-active'); });
    links[index].classList.add('is-active');
    links[index].scrollIntoView({ block: 'nearest' });
    activeIndex = index;
  }

  input.addEventListener('input', function () {
    var q = input.value.trim();
    clearTimeout(debounceTimer);
    if (q.length < 2) {
      renderResults([]);
      return;
    }
    debounceTimer = setTimeout(function () {
      fetch('/staff/busca?q=' + encodeURIComponent(q))
        .then(function (r) { return r.json(); })
        .then(function (data) { renderResults(data.results || []); })
        .catch(function () { renderResults([]); });
    }, 200);
  });

  input.addEventListener('keydown', function (e) {
    var links = results.querySelectorAll('.search-result');
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive(activeIndex + 1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive(activeIndex - 1);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (activeIndex >= 0 && links[activeIndex]) {
        window.location.href = links[activeIndex].href;
      } else if (links.length) {
        window.location.href = links[0].href;
      }
    }
  });
})();
