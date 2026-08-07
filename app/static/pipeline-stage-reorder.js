/* Arrastar-pra-reordenar as etapas de um pipeline em
 * app/templates/crm_pipeline_settings.html (Fase 4 da reforma do CRM,
 * 2026-08-06). Reordena as linhas dentro de `.stage-reorder-list` via
 * HTML5 drag-and-drop nativo (mesma técnica de app/static/kanban-dnd.js,
 * mas reordenando irmãos dentro de UMA lista em vez de mover entre
 * colunas) e, ao soltar, monta e submete um <form> com a ordem final
 * pra persistir -- mesmo padrão de "monta um form em JS e faz o browser
 * navegar" já usado no resto do CRM, nenhuma chamada fetch/AJAX nova.
 */
(function () {
  function getRowAfter(list, y) {
    var rows = [].slice.call(list.querySelectorAll('.stage-reorder-row:not(.dragging)'));
    return rows.reduce(function (closest, row) {
      var box = row.getBoundingClientRect();
      var offset = y - box.top - box.height / 2;
      if (offset < 0 && offset > closest.offset) {
        return { offset: offset, element: row };
      }
      return closest;
    }, { offset: -Infinity, element: null }).element;
  }

  function saveOrder(list) {
    var values = [].slice.call(list.querySelectorAll('.stage-reorder-row')).map(function (row) {
      return row.dataset.stageValue;
    });
    var form = document.createElement('form');
    form.method = 'post';
    form.action = list.dataset.reorderUrl;
    values.forEach(function (value) {
      var input = document.createElement('input');
      input.type = 'hidden';
      input.name = 'stage_value';
      input.value = value;
      form.appendChild(input);
    });
    document.body.appendChild(form);
    form.submit();
  }

  document.querySelectorAll('.stage-reorder-list').forEach(function (list) {
    var dragged = null;
    var moved = false;

    list.querySelectorAll('.stage-reorder-row').forEach(function (row) {
      row.addEventListener('dragstart', function () {
        dragged = row;
        moved = false;
        row.classList.add('dragging');
      });
      row.addEventListener('dragend', function () {
        row.classList.remove('dragging');
        dragged = null;
        if (moved) saveOrder(list);
      });
    });

    list.addEventListener('dragover', function (e) {
      if (!dragged) return;
      e.preventDefault();
      var after = getRowAfter(list, e.clientY);
      var current = after || null;
      if (current !== dragged.nextElementSibling && dragged !== current) {
        moved = true;
        if (after == null) list.appendChild(dragged);
        else list.insertBefore(dragged, after);
      }
    });
  });
})();
