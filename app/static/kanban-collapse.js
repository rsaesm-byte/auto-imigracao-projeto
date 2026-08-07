/* Colunas recolhíveis em todo Kanban do CRM (Leads/Cases/Traduções/
 * Tarefas/Financial Coaching) -- Prompt Mestre, Fase 4 ("Colunas
 * recolhíveis"), 2026-08-06. Injeta o botão de recolher em toda
 * `.crm-kanban-col` sem precisar editar cada template (mesma técnica de
 * app/static/kanban-dnd.js/list-filter.js: um script só, reusado por
 * todo board). Estado (recolhida ou não) persiste em localStorage,
 * chaveado por board (pathname) + `data-status-value` da coluna -- não
 * pelo índice, que mudaria se alguém reordenar as etapas em Pipeline
 * Settings, colapsando a coluna errada na próxima visita.
 */
(function () {
  document.querySelectorAll('.crm-kanban-col').forEach(function (col) {
    var h3 = col.querySelector('h3');
    if (!h3) return;

    var statusValue = col.dataset.statusValue || col.dataset.stageValue || '';
    var key = 'kanban-collapsed:' + window.location.pathname + ':' + statusValue;

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'kanban-collapse-toggle';
    btn.setAttribute('aria-label', 'Collapse column');
    btn.textContent = '‹';
    h3.insertBefore(btn, h3.firstChild);

    function setCollapsed(collapsed) {
      col.classList.toggle('collapsed', collapsed);
      btn.textContent = collapsed ? '›' : '‹';
      btn.setAttribute('aria-label', collapsed ? 'Expand column' : 'Collapse column');
      try { localStorage.setItem(key, collapsed ? '1' : '0'); } catch (e) { /* private mode etc. -- fine to no-op */ }
    }

    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      setCollapsed(!col.classList.contains('collapsed'));
    });
    col.addEventListener('click', function () {
      if (col.classList.contains('collapsed')) setCollapsed(false);
    });

    var stored;
    try { stored = localStorage.getItem(key); } catch (e) { stored = null; }
    if (stored === '1') setCollapsed(true);
  });
})();
