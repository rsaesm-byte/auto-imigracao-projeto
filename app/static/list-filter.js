/* Filtro instantâneo client-side pra listas/kanbans (pedido do usuário
 * 2026-08-06, "algo como Ctrl+F"). Cada `.list-filter-input` filtra os
 * `.crm-kanban-card` (ou outro seletor em data-filter-target) do board
 * mais próximo, comparando o texto do card com a query (sem round-trip
 * ao servidor -- os cards já estão todos na página).
 *
 * "/" foca a primeira caixa de filtro da página em vez de amarrar no
 * atalho Ctrl+F de verdade: esse atalho é reservado pelo navegador pra
 * busca nativa na página, que continua útil por cima disso (ver também
 * app/static/global-search.js, que é o Ctrl+K/Cmd+K de verdade).
 */
(function () {
  // Drill-down a partir dos gráficos de barra da aba Reports (Prompt
  // Mestre, Seção 15 "drill-down", 2026-08-06): um link com `?q=valor`
  // pré-preenche e já aplica o filtro instantâneo assim que a página
  // carrega -- reusa o MESMO filtro client-side que já existia (nenhum
  // mecanismo novo), só o alimenta a partir da URL em vez de só digitação.
  var urlQuery = new URLSearchParams(window.location.search).get('q');

  document.querySelectorAll('.list-filter-input').forEach(function (input) {
    var targetSelector = input.dataset.filterTarget || '.crm-kanban';
    var container = document.querySelector(targetSelector);
    if (!container) return;
    var itemSelector = input.dataset.filterItem || '.crm-kanban-card';

    function applyFilter() {
      var q = input.value.trim().toLowerCase();
      container.querySelectorAll(itemSelector).forEach(function (item) {
        var matches = !q || item.textContent.toLowerCase().indexOf(q) !== -1;
        item.style.display = matches ? '' : 'none';
      });
    }

    input.addEventListener('input', applyFilter);

    if (urlQuery) {
      input.value = urlQuery;
      applyFilter();
    }
  });

  document.addEventListener('keydown', function (e) {
    if (e.key !== '/') return;
    var tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || e.target.isContentEditable) return;
    var firstFilter = document.querySelector('.list-filter-input');
    if (firstFilter) {
      e.preventDefault();
      firstFilter.focus();
    }
  });
})();
