function filterCallbackCalendar() {
  calendar.refetchEvents();
}

$(() => {
  var bottom_pad = 20;
  var calendar_el = document.getElementById("calendar");
  var filters = JSON.parse(document.getElementById("calendar-filters").textContent);
  var ignored_filters = new Set(
    $(".ignore-filter[data-value='1']")
      .map(function () {
        return $(this).attr("data-id");
      })
      .toArray(),
  );

  function get_calendar_height() {
    return $(window).height() - ($("#calendar").closest(".tab-content").position().top + bottom_pad);
  }

  function update_calendar_height() {
    if (!$(calendar_el).is(":visible")) {
      return;
    }
    var calendar_height = get_calendar_height();
    if (calendar.getOption("height") !== calendar_height) {
      calendar.setOption("height", calendar_height);
    }
  }

  function toggle_filter(id, ignored) {
    if (ignored) {
      ignored_filters.add(id);
    } else {
      ignored_filters.delete(id);
    }
    calendar.refetchEvents();
  }

  function navigate_days(e, days) {
    if (calendar.view.type === "timeGridDays") {
      e.preventDefault();
      calendar.incrementDate({ days: days });
    }
  }

  function get_toolbar_right(today_button) {
    return (
      (filters.length ? "contestFilters " : "") +
      today_button +
      " dayGridMonth,timeGridWeek,listWeek,multiMonthYear,timeGridDays prev,next"
    );
  }

  var today_timeout_id;
  function update_today_button() {
    var now = moment.tz($.now(), timezone);
    var selected_today = moment.tz(calendar.getDate(), timezone).isSame(now, "day");
    // Native Today is disabled whenever today is visible, even when Days is shifted.
    var today_button = calendar.view.type === "timeGridDays" && !selected_today ? "daysToday" : "today";
    var toolbar_right = get_toolbar_right(today_button);
    if (calendar.getOption("headerToolbar").right !== toolbar_right) {
      calendar.setOption("headerToolbar", { left: "title", right: toolbar_right });
    }
    clearTimeout(today_timeout_id);
    today_timeout_id = setTimeout(update_today_button, now.clone().endOf("day").diff(now) + 1);
  }

  var filter_controls = $('<div class="clist-calendar-filters"></div>');
  var custom_filters = filters.filter((filter) => filter.id > 0);
  if (custom_filters.length) {
    var filter_group = $('<div class="btn-group"></div>').appendTo(filter_controls);
    $(
      '<button class="btn btn-default btn-sm dropdown-toggle" type="button" data-toggle="dropdown">Custom filters <span class="caret"></span></button>',
    ).appendTo(filter_group);
    var filter_menu = $('<div class="dropdown-menu"></div>').appendTo(filter_group);
    custom_filters.forEach((filter) => {
      var id = String(filter.id);
      $('<button type="button" class="btn btn-default btn-sm ignore-filter"></button>')
        .text(filter.name)
        .toggleClass("active", ignored_filters.has(id))
        .appendTo(filter_menu)
        .click(function (e) {
          e.preventDefault();
          var ignored = !ignored_filters.has(id);
          $(this).toggleClass("active", ignored).blur();
          toggle_filter(id, ignored);
        });
    });
  }

  if (filters.some((filter) => filter.id == 0)) {
    var long_filter = $('<input id="spam-filter" type="checkbox">')
      .prop("checked", !ignored_filters.has("0"))
      .appendTo(filter_controls);
    long_filter.bootstrapToggle({
      on: "Filtered long",
      off: "Disabled filter",
      onstyle: "default active",
      offstyle: "default active",
      size: "small",
      width: 106,
      height: 30,
    });
    long_filter.change(function () {
      toggle_filter("0", !this.checked);
    });
  }

  var hour12 = is_12_hour_clock();
  var time_format = {
    hour: "numeric",
    minute: "2-digit",
    hour12: hour12,
  };

  var calendar_views = {
    dayGridMonth: {},
    timeGridWeek: {},
    listWeek: {},
    multiMonthYear: {},
    timeGridDays: {
      type: "timeGrid",
      visibleRange: (current_date) => {
        const selected_date = moment.tz(current_date, timezone).startOf("day");
        return {
          start: selected_date.clone().subtract(calendar_days_before, "days").format("YYYY-MM-DD"),
          end: selected_date
            .clone()
            .add(calendar_days_after + 1, "days")
            .format("YYYY-MM-DD"),
        };
      },
    },
  };
  var calendar_view = Cookies.get("calendar_view");
  if (calendar_view === "fiveDayWindow") {
    calendar_view = "timeGridDays";
  }
  if (!Object.keys(calendar_views).includes(calendar_view)) {
    calendar_view = Object.keys(calendar_views)[0];
  }

  calendar = new FullCalendar.Calendar(calendar_el, {
    views: {
      ...calendar_views,
      timeGrid: {
        allDayHeaderInnerClass: "clist-calendar-all-day-label",
        dayCellBottomClass: "clist-calendar-all-day-bottom",
      },
    },
    initialView: calendar_view,
    nowIndicator: true,
    buttons: {
      timeGridDays: { text: "Days" },
      daysToday: { text: "Today", hint: "Return to today", click: () => calendar.today() },
      prev: { click: (e) => navigate_days(e, -1) },
      next: { click: (e) => navigate_days(e, 1) },
    },
    buttonClass: "clist-calendar-button",
    toolbarSectionClass: "clist-calendar-toolbar-section",
    toolbarElements: {
      contestFilters: () => ({ domNodes: [filter_controls[0]] }),
    },
    eventDisplay: "block",
    headerToolbar: {
      left: "title",
      right: get_toolbar_right("today"),
    },
    titleFormat: { year: "numeric", month: "long", day: "numeric" },
    firstDay: 1,
    allDaySlot: true,
    timeZone: timezone,
    eventTimeFormat: time_format,
    slotHeaderFormat: time_format,
    slotDuration: "01:00",
    slotHeaderInterval: "01:00",
    expandRows: true,
    eventClass: "clist-calendar-event",
    rowEventInnerClass: (info) => (info.event.allDay ? "clist-calendar-all-day-inner" : ""),
    eventTitleClass: "clist-calendar-event-title",
    columnEventTitleClass: (info) => (info.isShort ? "" : "clist-calendar-column-title"),
    eventTimeClass: "clist-calendar-event-time",
    dayCellClass: (info) => (info.isToday ? "clist-calendar-today" : ""),
    dayLaneClass: (info) => (info.isToday ? "clist-calendar-today" : ""),
    events: (fetchInfo, successCallback, failureCallback) => {
      var url = new URL(window.location.href);
      $.ajax({
        url: "/get/events/",
        type: "POST",
        traditional: true,
        data: {
          start: fetchInfo.startStr,
          end: fetchInfo.endStr,
          categories: ["calendar"],
          party: $("#party-name").attr("data-slug"),
          search_query: $('#filter [type="text"]').val(),
          resource: url.searchParams.getAll("resource"),
          status: url.searchParams.get("status"),
          favorite: $('#filter button[name="favorite"].active').data("value"),
          ignore_filters: Array.from(ignored_filters),
        },
        success: (response) => {
          response.forEach((event) => {
            event.original_start = event.start;
            event.original_end = event.end;
          });
          successCallback(response);
        },
        error: (response) => {
          log_ajax_error(response);
          failureCallback({ message: "there was an error while fetching events!" });
        },
      });
    },
    eventDidMount: (info) => {
      var event = info.event;
      var element = info.el;
      var start = moment.tz(event.extendedProps.original_start, timezone);
      var end = moment.tz(event.extendedProps.original_end, timezone);
      var now = moment.tz($.now(), timezone);
      var countdown = event.extendedProps.countdown;
      var start_time = start.format("YYYY-MM-DD HH:mm");
      var end_time = event.end ? end.format("YYYY-MM-DD HH:mm") : null;
      var title =
        event.title +
        "<div>" +
        event.extendedProps.host +
        "</div>" +
        "<div>Duration: " +
        event.extendedProps.hr_duration +
        "</div>" +
        "<div>Start: " +
        start_time +
        "</div>" +
        (event.end ? "<div>End: " + end_time + "</div>" : "") +
        (countdown
          ? '<div class="countdown">' +
            (start < now ? "Ends in " : "Starts in ") +
            '<span class="countdown-timestamp hidden">' +
            countdown +
            "</span>" +
            '<span class="countdown-format">' +
            getFormatTime(countdown) +
            "</span>" +
            "</div>"
          : "");
      $(element).tooltip({
        title: title,
        placement: "top",
        container: "body",
        html: true,
        delay: {
          show: 300,
          hide: 100,
        },
        trigger: "hover",
      });
      $(element).on("inserted.bs.tooltip", () => {
        $(".countdown-format").each((idx, val) => {
          var countdown = parseInt($(val).parent().find(".countdown-timestamp").html());
          $(val).html(getFormatTime(countdown - ($.now() - page_load) / 1000));
        });
      });

      var event_element = $(element).find(".clist-calendar-event-title")[0];
      var is_list = info.view.type == "listWeek";

      var addition_info = $('<span class="clist-calendar-actions"></span>');
      addition_info.click((e) => {
        e.preventDefault();
        e.stopPropagation();
      });

      var icon = $('<img src="' + event.extendedProps.icon + '" height="18" width="18">&nbsp;</img>');
      icon.prependTo(addition_info);

      if (contest_toggle) {
        var toggle_part_contest_link = $(
          '<i class="party-check fa-fw far" data-contest-id="' + event.id + '">&nbsp;</i>',
        );
        toggle_part_contest_link.toggleClass(
          party_contests_set.has(parseInt(event.id)) ? "fa-check-square" : "fa-square",
        );
        if (has_permission_toggle_party_contests) {
          toggle_part_contest_link.click(toggle_party_contest);
        }
        toggle_part_contest_link.prependTo(addition_info);
      }
      if (favorite_contests && !is_list) {
        var icon_class = event.extendedProps.favorite ? "selected-activity fas" : "far";
        var favorite_data =
          'data-activity-type="fav" data-content-type="contest" data-object-id="' +
          event.id +
          '" data-selected-class="fas" data-unselected-class="far"';
        var favorite_icon = $(
          '<i onclick="click_activity(event, this)" class="activity fa-star fav ' +
            icon_class +
            '" ' +
            favorite_data +
            "></i>",
        );
        favorite_icon.prependTo(addition_info);
      }
      if (hide_contest && !is_list) {
        var hide_contest_link = $(
          '<i onclick="toggle_hide_contest(event, this)" class="hide-contest fa fa-eye" data-contest-id="' +
            event.id +
            '">&nbsp;</i>',
        );
        hide_contest_link.prependTo(addition_info);
      }
      if (add_to_calendar && add_to_calendar.length == 1 && !is_list) {
        var data_ace =
          '{ "title":"' +
          event.title +
          '", "desc":"url: ' +
          event.url +
          '", "location":"' +
          event.extendedProps.host +
          '", "time":{ "start":"' +
          start_time +
          '", "end":"' +
          end_time +
          '", "zone":"' +
          timezone_hm +
          '" } }';
        var ace = $(
          '<a onclick="return false" class="data-ace" data-ace=' +
            "'" +
            data_ace +
            "'" +
            '><i class="far fa-calendar-alt"></i></a>',
        );
        $(ace).addcalevent({
          onclick: true,
          apps: [parseInt(add_to_calendar)],
        });
        ace.prependTo(addition_info);
      }

      addition_info.prependTo(event_element);
    },
    eventWillUnmount: (info) => {
      $(info.el).tooltip("destroy");
      $(info.el)
        .find(".data-ace")
        .each((idx, el) => $(el).addcalevent("destroy"));
    },
    datesSet: (info) => {
      Cookies.set("calendar_view", info.view.type);
      update_today_button();
    },
    loading: (bool) => {
      $("#loading").toggle(bool);
    },
    dayMaxEventRows: event_limit,
    height: get_calendar_height(),
  });

  calendar.render();
  $(window).on("resize", update_calendar_height);
  $(calendar_el).on("calendar:shown", update_calendar_height);
  $(document).on("shown.bs.tab", 'a[href="#calendar-tab"]', update_calendar_height);
  $(document).on("visibilitychange", () => {
    if (!document.hidden) {
      update_today_button();
    }
  });
  update_calendar_height();
});
