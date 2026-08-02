(function (global) {
  "use strict";

  const TERMINAL_STATUSES = new Set(["completed", "failed", "warning", "cancelled", "skipped", "interrupted"]);
  const STATUS_LABEL_CLASSES = {
    completed: "label-success",
    failed: "label-danger",
    error: "label-danger",
    forbidden: "label-danger",
    warning: "label-warning",
    interrupted: "label-warning",
    in_progress: "label-info",
    queued: "label-info",
    none: "label-default",
    cancelled: "label-default",
    skipped: "label-default",
  };
  const STATUS_LABEL_CLASS_NAMES = [...new Set(Object.values(STATUS_LABEL_CLASSES))].join(" ");

  class LiveLogViewer {
    constructor(options) {
      this.output = $(options.output);
      this.progress = $(options.progress);
      this.status = $(options.status);
      this.title = $(options.title);
      this.eventType = $(options.eventType);
      this.eventTypeSeparator = $(options.eventTypeSeparator);
      this.maxLines = options.maxLines || 1000;
      this.onStatus = options.onStatus || function () {};
      this.onEvent = options.onEvent || function () {};
      this.socket = null;
      this.eventLogId = null;
      this.lastSeq = 0;
      this.intentionalClose = false;
      this.terminal = false;
      this.reconnectTimer = null;
      this.resolveTimer = null;
      this.resolveJobId = null;
    }

    reset() {
      this.output.empty();
      this.progress.empty();
      this.renderStatus("");
      this.eventType.text("").addClass("hidden");
      this.eventTypeSeparator.addClass("hidden");
      this.lastSeq = 0;
      this.terminal = false;
    }

    connect(eventLog) {
      const eventLogId = typeof eventLog === "object" ? eventLog.id : eventLog;
      this.disconnect();
      this.reset();
      this.eventLogId = eventLogId;
      this.intentionalClose = false;
      this.openSocket();
      if (typeof eventLog === "object") {
        this.setEventLog(eventLog);
      }
    }

    disconnect() {
      this.intentionalClose = true;
      clearTimeout(this.reconnectTimer);
      clearTimeout(this.resolveTimer);
      this.resolveJobId = null;
      if (this.socket) {
        const socket = this.socket;
        this.socket = null;
        socket.onclose = null;
        socket.close();
      }
    }

    connectJob(jobId, dataUrl) {
      this.disconnect();
      this.reset();
      this.intentionalClose = false;
      this.resolveJobId = jobId;
      this.addLog("INFO", "Update queued. Waiting for the worker to start...");
      this.setStatus("queued");

      const resolve = () => {
        $.getJSON(dataUrl, { job_id: jobId })
          .done((data) => {
            if (this.resolveJobId !== jobId) {
              return;
            }
            if (data.event_logs.length) {
              this.connect(data.event_logs[0]);
            } else if (!this.intentionalClose) {
              this.resolveTimer = setTimeout(resolve, 2000);
            }
          })
          .fail(() => {
            if (!this.intentionalClose && this.resolveJobId === jobId) {
              this.resolveTimer = setTimeout(resolve, 2000);
            }
          });
      };
      resolve();
    }

    openSocket() {
      const protocol = window.location.protocol === "https:" ? "wss://" : "ws://";
      const socket = new WebSocket(
        protocol +
          window.location.host +
          "/ws/live-log/?event_log_id=" +
          encodeURIComponent(this.eventLogId) +
          "&after_seq=" +
          encodeURIComponent(this.lastSeq),
      );
      this.socket = socket;
      socket.onmessage = (message) => this.handleMessage(JSON.parse(message.data));
      socket.onclose = (event) => {
        if (this.socket !== socket) {
          return;
        }
        this.socket = null;
        if (event.code === 4403) {
          this.addLog("ERROR", "You have no permission to view this live log.");
          this.setStatus("forbidden");
          return;
        }
        if (!this.intentionalClose && !this.terminal) {
          this.reconnectTimer = setTimeout(() => this.openSocket(), 2000);
        }
      };
    }

    handleMessage(data) {
      if (data.type === "live_log_snapshot") {
        this.setEventLog(data.event_log);
        return;
      }
      if (data.type !== "live_log" || data.event_log_id !== this.eventLogId) {
        return;
      }
      data.events.forEach((event) => {
        if (event.seq <= this.lastSeq) {
          return;
        }
        this.lastSeq = event.seq;
        if (event.dropped_before) {
          this.addLog(
            "WARNING",
            event.dropped_before + " live events were dropped before this message.",
            event.timestamp,
          );
        }
        if (event.kind === "log") {
          this.addLog(event.level, event.message, event.timestamp);
        } else if (event.kind === "progress") {
          this.updateProgress(event);
        } else if (event.kind === "status") {
          this.setStatus(event.status);
          if (event.message) {
            this.addLog("INFO", event.message, event.timestamp);
          }
        }
        this.onEvent(event);
      });
    }

    formatTimestamp(timestamp) {
      const value =
        timestamp === null || timestamp === undefined
          ? Date.now()
          : typeof timestamp === "number"
            ? timestamp * 1000
            : timestamp;
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) {
        return "--:--:--";
      }
      return date.toLocaleTimeString(undefined, {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      });
    }

    addLog(level, message, timestamp) {
      const shouldScrollToBottom =
        !this.output.length || this.output[0].scrollHeight - this.output.scrollTop() - this.output[0].clientHeight <= 4;
      const normalizedLevel = String(level || "INFO").toUpperCase();
      const line = $("<span>")
        .addClass("live-log-line")
        .append($("<span>").addClass("live-log-time").text(this.formatTimestamp(timestamp)))
        .append($("<span>").addClass("live-log-separator").text(" - "))
        .append(
          $("<span>")
            .addClass("live-log-level live-log-level-" + normalizedLevel.toLowerCase())
            .text(normalizedLevel),
        )
        .append($("<span>").addClass("live-log-separator").text(" - "))
        .append($("<span>").addClass("live-log-message").text(message));
      this.output.append(line);
      while (this.output.children().length > this.maxLines) {
        this.output.children().first().remove();
      }
      if (shouldScrollToBottom && this.output.length) {
        this.output.scrollTop(this.output[0].scrollHeight);
      }
    }

    updateProgress(event) {
      const description = event.description || "Progress";
      const finished = Boolean(event.completed || event.finished);
      let row = this.progress.children('[data-bar-id="' + event.bar_id + '"]');
      if (event.total === 0) {
        row.remove();
        return;
      }
      if (!row.length) {
        row = $(
          '<div class="live-log-progress" data-bar-id="' +
            event.bar_id +
            '">' +
            '<div class="live-log-progress-label"></div>' +
            '<div class="progress"><div class="progress-bar progress-bar-success"></div></div>' +
            "</div>",
        );
        this.progress.prepend(row);
        this.progress.scrollTop(0);
      }
      row.attr("data-description", description);

      let details = description;
      if (event.total !== null && event.total !== undefined) {
        const percentage = Math.max(0, Math.min(100, (event.progress || 0) * 100));
        details += " (" + event.current + "/" + event.total + ", " + percentage.toFixed(2) + "%";
        if (event.eta !== null && event.eta !== undefined) {
          details += ", ETA " + this.formatDuration(event.eta);
        }
        details += ")";
        row
          .find(".progress-bar")
          .css("width", percentage + "%")
          .removeClass("progress-bar-striped active");
      } else {
        row.find(".progress-bar").css("width", "100%").toggleClass("progress-bar-striped active", !finished);
      }
      row.find(".live-log-progress-label").text(details);
      row.toggleClass("live-log-progress-completed", finished);
    }

    formatDuration(seconds) {
      seconds = Math.max(0, Math.round(seconds));
      const minutes = Math.floor(seconds / 60);
      const remainder = seconds % 60;
      return minutes ? minutes + "m " + remainder + "s" : remainder + "s";
    }

    renderStatus(status) {
      const normalizedStatus = status || "";
      const labelClass = STATUS_LABEL_CLASSES[normalizedStatus] || "label-default";
      this.status
        .text(normalizedStatus.replace(/_/g, " "))
        .removeClass(STATUS_LABEL_CLASS_NAMES)
        .addClass(labelClass)
        .toggleClass("hidden", !normalizedStatus);
    }

    setEventLog(eventLog) {
      if (this.title.length) {
        this.title.removeClass("text-muted").text(eventLog.related_name);
      }
      if (this.eventType.length) {
        this.eventType.removeClass("hidden").text(eventLog.name);
        this.eventTypeSeparator.removeClass("hidden");
      }
      if (eventLog.status === "queued" && eventLog.message && !this.output.children().length) {
        this.addLog("INFO", eventLog.message, eventLog.created);
      }
      this.setStatus(eventLog.status);
    }

    setStatus(status) {
      this.renderStatus(status);
      this.terminal = TERMINAL_STATUSES.has(status);
      this.onStatus(status, this.terminal);
    }
  }

  global.LiveLogViewer = LiveLogViewer;

  let updateStatisticsViewer = null;

  function getUpdateStatisticsViewer() {
    if (!updateStatisticsViewer) {
      updateStatisticsViewer = new LiveLogViewer({
        output: "#update-statistics-log-output",
        progress: "#update-statistics-progress-list",
        status: "#update-statistics-status",
        eventType: "#update-statistics-event-type",
        eventTypeSeparator: "#update-statistics-event-type-separator",
        onStatus: function (status, terminal) {
          spinUpdateStatisticsModalButton(!terminal && status !== "forbidden");
        },
        onEvent: function (event) {
          if (event.kind === "log") {
            $("#show_update_statistics_log_btn i").addClass("fa-fade");
          }
        },
      });
    }
    return updateStatisticsViewer;
  }

  function replaceUpdateStatisticsButton() {
    $("#update_statistics_btn").addClass("hidden");
    $("#show_update_statistics_log_btn").removeClass("hidden");
  }

  function spinUpdateStatisticsModalButton(value) {
    const modalButton = $("#modal-update-statistics-btn");
    modalButton.attr("disabled", value);
    modalButton.find("i").toggleClass("fa-spin", value);
  }

  function connectActiveContestLiveLog() {
    if (typeof contest_live_logs_data_url === "undefined") {
      return;
    }
    $.getJSON(contest_live_logs_data_url, { contest_id: contest_pk }).done(function (data) {
      if (!data.event_logs.length) {
        return;
      }
      replaceUpdateStatisticsButton();
      getUpdateStatisticsViewer().connect(data.event_logs[0]);
    });
  }

  global.show_update_statistics_log = function () {
    replaceUpdateStatisticsButton();
    $("#update-statistics-log").modal("show");
    $("#show_update_statistics_log_btn i").removeClass("fa-fade");
  };

  global.update_statistics = function (element) {
    global.show_update_statistics_log();
    const viewer = getUpdateStatisticsViewer();
    const icon = $(element).find("i");
    const button = icon.closest("a");
    icon.addClass("fa-spin");
    button.attr("disabled", "disabled");
    spinUpdateStatisticsModalButton(true);

    $.ajax({
      type: "POST",
      url: change_url,
      data: {
        pk: coder_pk,
        name: "update-statistics",
        id: contest_pk,
      },
      error: log_ajax_error_callback,
      success: function (data) {
        notify("Queued update", "success");
        if (data.can_view_live_log) {
          viewer.connectJob(data.job_id, data.live_logs_data_url);
        } else {
          viewer.reset();
          viewer.addLog("INFO", "Update queued. You do not have permission to view its live log.");
          viewer.setStatus("forbidden");
        }
      },
      complete: function (_jqXHR, textStatus) {
        icon.removeClass("fa-spin");
        button.attr("disabled", false);
        if (textStatus !== "success") {
          spinUpdateStatisticsModalButton(false);
        }
      },
    });
  };

  $(connectActiveContestLiveLog);
})(window);
