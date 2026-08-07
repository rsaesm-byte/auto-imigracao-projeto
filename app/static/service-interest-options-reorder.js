/* Arrastar-pra-reordenar os itens de "qual serviço você tem interesse"
 * em app/templates/crm_service_interest_options.html (pedido do usuário
 * 2026-08-07). Mesma técnica de app/static/pipeline-stage-reorder.js
 * (HTML5 drag-and-drop nativo, monta e submete um <form> com a ordem
 * final ao soltar) -- arquivo próprio em vez de reusar aquele porque os
 * nomes de classe/atributo lá são específicos de "stage", e usá-los
 * aqui pra IDs de ServiceInterestOption ficaria enganoso pra quem ler o
 * HTML depois.
 */
(function () {
  function getRowAfter(list, y) {
    var rows = [].slice.call(list.querySelectorAll('.option-reorder-row:not(.dragging)'));
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
    var ids = [].slice.call(list.querySelectorAll('.option-reorder-row')).map(function (row) {
      return row.dataset.optionId;
    });
    var form = document.createElement('form');
    form.method = 'post';
    form.action = list.dataset.reorderUrl;
    ids.forEach(function (id) {
      var input = document.createElement('input');
      input.type = 'hidden';
      input.name = 'option_id';
      input.value = id;
      form.appendChild(input);
    });
    document.body.appendChild(form);
    form.submit();
  }

  document.querySelectorAll('.option-reorder-list').forEach(function (list) {
    var dragged = null;
    var moved = false;

    list.querySelectorAll('.option-reorder-row').forEach(function (row) {
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
