(function () {
  "use strict";

  let selectedEventLogId = null;
  let viewer = null;

  function selectEventLog(eventLog) {
    selectedEventLogId = eventLog.id;
    $(".live-log-run").removeClass("active");
    $('.live-log-run[data-event-log-id="' + eventLog.id + '"]').addClass("active");
    viewer.connect(eventLog);
  }

  function renderRuns(eventLogs) {
    const list = $("#live-log-runs");
    list.empty();
    eventLogs.forEach(function (eventLog) {
      const button = $('<button type="button" class="list-group-item live-log-run">')
        .attr("data-event-log-id", eventLog.id)
        .append($("<strong>").text(eventLog.related_name))
        .append($("<br>"))
        .append($("<small>").text(eventLog.name + " · " + eventLog.status));
      button.on("click", function () {
        selectEventLog(eventLog);
      });
      list.append(button);
    });

    $("#live-log-empty").toggleClass("hidden", eventLogs.length > 0);
    const selectedRun = $('.live-log-run[data-event-log-id="' + selectedEventLogId + '"]');
    if (selectedRun.length) {
      selectedRun.addClass("active");
    } else if (selectedEventLogId === null && eventLogs.length) {
      selectEventLog(eventLogs[0]);
    }
  }

  function refreshRuns() {
    $.getJSON($("#live-log-app").data("runs-url"), function (data) {
      renderRuns(data.event_logs);
    });
  }

  $(function () {
    viewer = new LiveLogViewer({
      output: "#live-log-output",
      progress: "#live-log-progress-list",
      status: "#live-log-status",
      title: "#live-log-title",
      eventType: "#live-log-event-type",
      eventTypeSeparator: "#live-log-event-type-separator",
    });
    refreshRuns();
    setInterval(refreshRuns, 5000);
  });
})();
