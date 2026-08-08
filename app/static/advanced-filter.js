/* Filtro avançado (é/não é/contém + E/OU) + visualizações salvas --
 * pedido do usuário, Prompt Mestre, Seção 14, 2026-08-08. Mesmo espírito
 * zero-round-trip de list-filter.js (o filtro simples de texto que já
 * existia): tudo avaliado no client contra atributos `data-field-*` já
 * presentes em cada `.crm-kanban-card` (ou outro item, configurável) --
 * nunca uma query nova no backend. Só "salvar/abrir/apagar visualização"
 * fala com o servidor (app/crm_saved_filters.py), porque isso PRECISA
 * persistir entre sessões/colaboradores.
 *
 * Uso: `<div class="crm-kanban" data-filter-fields='[{"key":"stage",
 * "label":"Stage","type":"select","options":[{"value":"new","label":
 * "New"}]}, {"key":"name","label":"Name","type":"text"}]'
 * data-board-key="leads">` -- um `<div class="advanced-filter-mount">`
 * em qualquer lugar da página vira o botão + painel.
 */
(function () {
  var OPERATORS_BY_TYPE = {
    text: [
      ['contains', 'contains'], ['not_contains', "doesn't contain"],
      ['is', 'is'], ['is_not', 'is not'],
      ['is_empty', 'is empty'], ['is_not_empty', 'is not empty'],
    ],
    select: [
      ['is', 'is'], ['is_not', 'is not'],
      ['is_empty', 'is empty'], ['is_not_empty', 'is not empty'],
    ],
    date: [
      ['on', 'is on'], ['before', 'is before'], ['after', 'is after'],
      ['is_empty', 'is empty'], ['is_not_empty', 'is not empty'],
    ],
    number: [
      ['eq', 'equals'], ['gt', 'is greater than'], ['lt', 'is less than'],
      ['is_empty', 'is empty'], ['is_not_empty', 'is not empty'],
    ],
  };

  function evalCondition(itemEl, condition, fieldsByKey) {
    var field = fieldsByKey[condition.field];
    if (!field) return true;
    var raw = itemEl.getAttribute('data-field-' + condition.field);
    var op = condition.operator;

    if (op === 'is_empty') return !raw;
    if (op === 'is_not_empty') return !!raw;

    var val = (raw || '').toString();
    var target = (condition.value || '').toString();

    if (field.type === 'date') {
      if (!val) return false;
      if (op === 'on') return val === target;
      if (op === 'before') return val < target;
      if (op === 'after') return val > target;
    }
    if (field.type === 'number') {
      var n = parseFloat(val);
      var t = parseFloat(target);
      if (isNaN(n)) return false;
      if (op === 'eq') return n === t;
      if (op === 'gt') return n > t;
      if (op === 'lt') return n < t;
    }
    // text / select
    var valLower = val.toLowerCase();
    var targetLower = target.toLowerCase();
    if (op === 'contains') return valLower.indexOf(targetLower) !== -1;
    if (op === 'not_contains') return valLower.indexOf(targetLower) === -1;
    if (op === 'is') return valLower === targetLower;
    if (op === 'is_not') return valLower !== targetLower;
    return true;
  }

  function evalFilter(itemEl, filter, fieldsByKey) {
    if (!filter || !filter.conditions || !filter.conditions.length) return true;
    var results = filter.conditions.map(function (c) { return evalCondition(itemEl, c, fieldsByKey); });
    return filter.combinator === 'OR' ? results.some(Boolean) : results.every(Boolean);
  }

  function initBoard(container) {
    var boardKey = container.dataset.boardKey;
    var fields;
    try { fields = JSON.parse(container.dataset.filterFields || '[]'); } catch (e) { fields = []; }
    if (!fields.length) return;
    var fieldsByKey = {};
    fields.forEach(function (f) { fieldsByKey[f.key] = f; });

    var itemSelector = container.dataset.filterItem || '.crm-kanban-card';
    var mount = document.querySelector('.advanced-filter-mount[data-board-key="' + boardKey + '"]')
      || document.querySelector('.advanced-filter-mount');
    if (!mount) return;

    var currentFilter = { combinator: 'AND', conditions: [] };

    function applyFilter() {
      container.querySelectorAll(itemSelector).forEach(function (item) {
        var matches = evalFilter(item, currentFilter, fieldsByKey);
        item.style.display = matches ? '' : 'none';
      });
      countBadge.textContent = currentFilter.conditions.length
        ? currentFilter.conditions.length + ' filter' + (currentFilter.conditions.length > 1 ? 's' : '')
        : '';
      toggleBtn.style.background = currentFilter.conditions.length ? 'var(--accent)' : 'none';
      toggleBtn.style.color = currentFilter.conditions.length ? '#fff' : 'var(--text)';
    }

    function conditionRow(condition) {
      condition = condition || { field: fields[0].key, operator: OPERATORS_BY_TYPE[fields[0].type][0][0], value: '' };
      var row = document.createElement('div');
      row.className = 'advanced-filter-row';
      row.style.cssText = 'display:flex;gap:6px;align-items:center;margin-bottom:6px;flex-wrap:wrap;';

      var fieldSelect = document.createElement('select');
      fieldSelect.style.cssText = 'font-size:0.8rem;';
      fields.forEach(function (f) {
        var opt = document.createElement('option');
        opt.value = f.key; opt.textContent = f.label;
        if (f.key === condition.field) opt.selected = true;
        fieldSelect.appendChild(opt);
      });

      var opSelect = document.createElement('select');
      opSelect.style.cssText = 'font-size:0.8rem;';

      var valueWrap = document.createElement('span');

      function renderOperators() {
        var field = fieldsByKey[fieldSelect.value] || fields[0];
        opSelect.innerHTML = '';
        (OPERATORS_BY_TYPE[field.type] || OPERATORS_BY_TYPE.text).forEach(function (pair) {
          var opt = document.createElement('option');
          opt.value = pair[0]; opt.textContent = pair[1];
          if (pair[0] === condition.operator) opt.selected = true;
          opSelect.appendChild(opt);
        });
        renderValueInput();
      }

      function renderValueInput() {
        var field = fieldsByKey[fieldSelect.value] || fields[0];
        valueWrap.innerHTML = '';
        if (opSelect.value === 'is_empty' || opSelect.value === 'is_not_empty') return;
        var input;
        if (field.type === 'select' && field.options) {
          input = document.createElement('select');
          input.style.cssText = 'font-size:0.8rem;';
          field.options.forEach(function (o) {
            var opt = document.createElement('option');
            opt.value = o.value; opt.textContent = o.label;
            if (o.value === condition.value) opt.selected = true;
            input.appendChild(opt);
          });
        } else {
          input = document.createElement('input');
          input.type = field.type === 'date' ? 'date' : (field.type === 'number' ? 'number' : 'text');
          input.style.cssText = 'font-size:0.8rem;width:140px;';
          input.value = condition.value || '';
        }
        input.className = 'advanced-filter-value';
        valueWrap.appendChild(input);
      }

      var removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.textContent = '×';
      removeBtn.title = 'Remove condition';
      removeBtn.style.cssText = 'background:none;border:none;color:var(--muted);cursor:pointer;font-size:1rem;padding:0 4px;';
      removeBtn.addEventListener('click', function () { row.remove(); });

      fieldSelect.addEventListener('change', renderOperators);
      opSelect.addEventListener('change', renderValueInput);
      renderOperators();

      row.appendChild(fieldSelect);
      row.appendChild(opSelect);
      row.appendChild(valueWrap);
      row.appendChild(removeBtn);
      row._getField = fieldSelect;
      row._getOp = opSelect;
      row._getValueEl = function () { return valueWrap.querySelector('.advanced-filter-value'); };
      return row;
    }

    var toggleBtn = document.createElement('button');
    toggleBtn.type = 'button';
    toggleBtn.className = 'icon-btn';
    toggleBtn.style.cssText = 'border:1px solid var(--border);border-radius:var(--radius-sm);padding:7px 12px;cursor:pointer;font-size:0.8rem;background:none;color:var(--text);display:inline-flex;align-items:center;gap:6px;';
    toggleBtn.innerHTML = 'Filters <span class="advanced-filter-count" style="font-size:0.72rem;"></span>';
    var countBadge = toggleBtn.querySelector('.advanced-filter-count');

    var panel = document.createElement('div');
    panel.style.cssText = 'display:none;position:absolute;z-index:20;background:var(--card);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow-md);padding:14px;margin-top:6px;min-width:340px;';

    var rowsWrap = document.createElement('div');
    var addBtn = document.createElement('button');
    addBtn.type = 'button';
    addBtn.textContent = '+ Add condition';
    addBtn.style.cssText = 'background:none;border:1px solid var(--border);border-radius:var(--radius-sm);cursor:pointer;font-size:0.78rem;padding:5px 10px;margin-top:4px;';
    addBtn.addEventListener('click', function () { rowsWrap.appendChild(conditionRow()); });

    var combinatorWrap = document.createElement('div');
    combinatorWrap.style.cssText = 'display:flex;gap:10px;align-items:center;margin:10px 0;font-size:0.8rem;';
    combinatorWrap.innerHTML =
      '<span class="muted">Match</span>' +
      '<label><input type="radio" name="' + boardKey + '-combinator" value="AND" checked> All (AND)</label>' +
      '<label><input type="radio" name="' + boardKey + '-combinator" value="OR"> Any (OR)</label>';

    var actionsWrap = document.createElement('div');
    actionsWrap.style.cssText = 'display:flex;gap:8px;margin-top:10px;';
    var applyBtn = document.createElement('button');
    applyBtn.type = 'button'; applyBtn.className = 'btn'; applyBtn.textContent = 'Apply';
    applyBtn.style.cssText = 'padding:6px 14px;font-size:0.8rem;';
    var clearBtn = document.createElement('button');
    clearBtn.type = 'button'; clearBtn.textContent = 'Clear';
    clearBtn.style.cssText = 'background:none;border:1px solid var(--border);border-radius:var(--radius-sm);cursor:pointer;font-size:0.8rem;padding:6px 14px;';
    var saveBtn = document.createElement('button');
    saveBtn.type = 'button'; saveBtn.textContent = 'Save view…';
    saveBtn.style.cssText = 'background:none;border:1px solid var(--border);border-radius:var(--radius-sm);cursor:pointer;font-size:0.8rem;padding:6px 14px;';

    actionsWrap.appendChild(applyBtn);
    actionsWrap.appendChild(clearBtn);
    actionsWrap.appendChild(saveBtn);

    var savedWrap = document.createElement('div');
    savedWrap.style.cssText = 'margin-top:12px;padding-top:10px;border-top:1px solid var(--border);';
    var savedLabel = document.createElement('div');
    savedLabel.className = 'muted';
    savedLabel.style.cssText = 'font-size:0.76rem;margin-bottom:6px;';
    savedLabel.textContent = 'Saved views';
    var savedList = document.createElement('div');
    savedList.style.cssText = 'display:flex;flex-direction:column;gap:4px;';
    savedWrap.appendChild(savedLabel);
    savedWrap.appendChild(savedList);

    function collectFilter() {
      var conditions = [];
      rowsWrap.querySelectorAll('.advanced-filter-row').forEach(function (row) {
        var valueEl = row._getValueEl();
        conditions.push({
          field: row._getField.value, operator: row._getOp.value,
          value: valueEl ? valueEl.value : '',
        });
      });
      var combinator = combinatorWrap.querySelector('input[name="' + boardKey + '-combinator"]:checked').value;
      return { combinator: combinator, conditions: conditions };
    }

    function loadFilter(filter) {
      rowsWrap.innerHTML = '';
      (filter.conditions || []).forEach(function (c) { rowsWrap.appendChild(conditionRow(c)); });
      var radio = combinatorWrap.querySelector('input[value="' + (filter.combinator || 'AND') + '"]');
      if (radio) radio.checked = true;
      currentFilter = filter;
      applyFilter();
    }

    function refreshSavedViews() {
      fetch('/staff/crm/filtros/' + boardKey).then(function (r) { return r.json(); }).then(function (views) {
        savedList.innerHTML = '';
        if (!views.length) {
          var empty = document.createElement('div');
          empty.className = 'muted'; empty.style.fontSize = '0.76rem';
          empty.textContent = 'No saved views yet.';
          savedList.appendChild(empty);
          return;
        }
        views.forEach(function (v) {
          var row = document.createElement('div');
          row.style.cssText = 'display:flex;justify-content:space-between;align-items:center;gap:6px;';
          var link = document.createElement('button');
          link.type = 'button';
          link.textContent = v.name + (v.scope === 'shared' ? ' (shared)' : '');
          link.style.cssText = 'background:none;border:none;color:var(--accent);cursor:pointer;font-size:0.8rem;padding:2px 0;text-align:left;';
          link.addEventListener('click', function () { loadFilter(v.filter); panel.style.display = 'none'; });
          row.appendChild(link);
          if (v.mine) {
            var del = document.createElement('button');
            del.type = 'button'; del.textContent = '×'; del.title = 'Delete this view';
            del.style.cssText = 'background:none;border:none;color:var(--muted);cursor:pointer;font-size:0.9rem;padding:0 4px;';
            del.addEventListener('click', function () {
              fetch('/staff/crm/filtros/' + v.id + '/excluir', { method: 'POST' }).then(refreshSavedViews);
            });
            row.appendChild(del);
          }
          savedList.appendChild(row);
        });
      });
    }

    applyBtn.addEventListener('click', function () {
      currentFilter = collectFilter();
      applyFilter();
      panel.style.display = 'none';
    });
    clearBtn.addEventListener('click', function () {
      rowsWrap.innerHTML = '';
      currentFilter = { combinator: 'AND', conditions: [] };
      applyFilter();
    });
    saveBtn.addEventListener('click', function () {
      var filter = collectFilter();
      if (!filter.conditions.length) { alert('Add at least one condition first.'); return; }
      var name = prompt('Name this view:');
      if (!name) return;
      var shared = confirm('Share with the whole team? OK = shared, Cancel = just for me.');
      var body = new URLSearchParams();
      body.set('name', name);
      body.set('filter_json', JSON.stringify(filter));
      body.set('scope', shared ? 'shared' : 'personal');
      fetch('/staff/crm/filtros/' + boardKey + '/nova', { method: 'POST', body: body }).then(function (r) { return r.json(); }).then(function (resp) {
        if (resp.error) { alert(resp.error); return; }
        refreshSavedViews();
      });
    });

    toggleBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
    });
    document.addEventListener('click', function (e) {
      if (!panel.contains(e.target) && e.target !== toggleBtn) panel.style.display = 'none';
    });

    panel.appendChild(rowsWrap);
    panel.appendChild(addBtn);
    panel.appendChild(combinatorWrap);
    panel.appendChild(actionsWrap);
    panel.appendChild(savedWrap);

    var wrapper = document.createElement('div');
    wrapper.style.position = 'relative';
    wrapper.appendChild(toggleBtn);
    wrapper.appendChild(panel);
    mount.appendChild(wrapper);

    rowsWrap.appendChild(conditionRow());
    refreshSavedViews();
  }

  document.querySelectorAll('[data-filter-fields]').forEach(initBoard);
})();
