htmx.onLoad(function (content) {
  var sortables = content.querySelectorAll('.sortable-team');

  sortables.forEach(function (el) {
    new Sortable(el, {
      group: 'teams',
      animation: 150,
      ghostClass: 'drag-ghost',
      chosenClass: 'drag-chosen',
      filter: '.player-card__remove',

      // onEnd fires BEFORE SortableJS dispatches the DOM 'end' event,
      // so hidden inputs are ready by the time HTMX reacts to the trigger.
      onEnd: function (evt) {
        // 1. Remove all stale hidden inputs from a previous drag.
        document.querySelectorAll('[data-team-input]').forEach(function (el) {
          el.remove();
        });

        // 2. For every column, write one hidden input per player card.
        //    All inputs go to evt.to so they are picked up by hx-include.
        ['team-black', 'team-unassigned', 'team-white'].forEach(function (containerId) {
          var container = document.getElementById(containerId);
          if (!container) return;

          container.querySelectorAll('[data-player-id]').forEach(function (card) {
            var input = document.createElement('input');
            input.type = 'hidden';
            input.name = containerId + '[]';
            input.value = card.dataset.playerId;
            input.setAttribute('data-team-input', '');
            evt.to.appendChild(input);
          });
        });

        // 3. Ask HTMX to POST the updated assignments via the custom trigger.
        htmx.trigger(evt.to, 'sortableEnd');
      }
    });
  });
});
