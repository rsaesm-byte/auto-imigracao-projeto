/* Shared HTML5 drag-and-drop for every CRM kanban board (Cases, Leads,
 * Tasks, Financial Coaching) -- pedido do usuário 2026-08-02: arrastar o
 * card entre colunas em vez de escolher no <select> e clicar "Move".
 *
 * Deliberately does NOT add a new route: each column already knows the
 * exact status-update URL/field for its own board (data-action-template/
 * data-status-field/data-status-value, set by the template) -- dropping a
 * card just builds and submits the same kind of <form> the old select+Move
 * button used to, so server-side behavior (including e.g. the Leads
 * "closed_won without a converted client redirects to the convert screen"
 * special case) is untouched.
 *
 * data-action-template carries a sentinel id (999999) instead of the real
 * one, since the template can't know which card will be dropped ahead of
 * time -- replaced here with the dragged card's real data-item-id. Safe as
 * a plain string replace: none of this app's CRM route prefixes contain a
 * literal "999999" substring.
 */
(function () {
  function initBoard(board) {
    var dragged = null;

    board.querySelectorAll('.crm-kanban-card[draggable="true"]').forEach(function (card) {
      card.addEventListener('dragstart', function () {
        dragged = card;
        card.classList.add('dragging');
      });
      card.addEventListener('dragend', function () {
        card.classList.remove('dragging');
        dragged = null;
        board.querySelectorAll('.crm-kanban-col.drag-over').forEach(function (c) {
          c.classList.remove('drag-over');
        });
      });
    });

    board.querySelectorAll('.crm-kanban-col[data-status-field]').forEach(function (col) {
      col.addEventListener('dragover', function (e) {
        if (!dragged) return;
        e.preventDefault();
        col.classList.add('drag-over');
      });
      col.addEventListener('dragleave', function (e) {
        if (e.target === col) col.classList.remove('drag-over');
      });
      col.addEventListener('drop', function (e) {
        e.preventDefault();
        col.classList.remove('drag-over');
        if (!dragged || dragged.parentElement === col) return;

        var itemId = dragged.dataset.itemId;
        var fieldName = col.dataset.statusField;
        var fieldValue = col.dataset.statusValue;
        var actionUrl = col.dataset.actionTemplate.split('999999').join(itemId);

        var form = document.createElement('form');
        form.method = 'post';
        form.action = actionUrl;
        var input = document.createElement('input');
        input.type = 'hidden';
        input.name = fieldName;
        input.value = fieldValue;
        form.appendChild(input);
        document.body.appendChild(form);
        form.submit();
      });
    });
  }

  document.querySelectorAll('.crm-kanban[data-draggable="true"]').forEach(initBoard);
})();
