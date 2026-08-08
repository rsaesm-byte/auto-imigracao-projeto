/* Arrastar-pra-reordenar os cartões do Motivation Board (pedido do
 * usuário 2026-08-07). Mesma técnica geral de
 * app/static/service-interest-options-reorder.js (HTML5 drag-and-drop
 * nativo, monta e submete um <form> com a ordem final ao soltar) --
 * arquivo próprio porque aquele algoritmo só compara posição vertical
 * (Y), certo pra uma lista de uma coluna só; aqui os cartões ficam num
 * grid de várias colunas, então o "cartão mais próximo" precisa
 * considerar X e Y juntos (distância euclidiana até o centro de cada
 * cartão), não só Y.
 */
(function () {
  function closestCard(list, x, y) {
    var cards = [].slice.call(list.querySelectorAll('.motivation-reorder-row:not(.dragging)'));
    var closest = null;
    var closestDist = Infinity;
    cards.forEach(function (card) {
      var box = card.getBoundingClientRect();
      var cx = box.left + box.width / 2;
      var cy = box.top + box.height / 2;
      var dist = Math.pow(x - cx, 2) + Math.pow(y - cy, 2);
      if (dist < closestDist) {
        closestDist = dist;
        closest = card;
      }
    });
    return closest;
  }

  function saveOrder(list) {
    var ids = [].slice.call(list.querySelectorAll('.motivation-reorder-row')).map(function (row) {
      return row.dataset.itemId;
    });
    var form = document.createElement('form');
    form.method = 'post';
    form.action = list.dataset.reorderUrl;
    ids.forEach(function (id) {
      var input = document.createElement('input');
      input.type = 'hidden';
      input.name = 'item_id';
      input.value = id;
      form.appendChild(input);
    });
    document.body.appendChild(form);
    form.submit();
  }

  document.querySelectorAll('.motivation-reorder-list').forEach(function (list) {
    var dragged = null;
    var moved = false;

    list.querySelectorAll('.motivation-reorder-row').forEach(function (row) {
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
      var target = closestCard(list, e.clientX, e.clientY);
      if (!target || target === dragged) return;
      var box = target.getBoundingClientRect();
      var before = e.clientX < box.left + box.width / 2;
      var next = before ? target : target.nextElementSibling;
      if (next !== dragged) {
        moved = true;
        list.insertBefore(dragged, next);
      }
    });
  });
})();
